"""Task #767 — regression coverage for Stripe-side payment helpers.

The audit (FULL_APP_AUDIT_2026-04-23.md, finding T1) identified the
``_enrich_payment_record`` helper and the Stripe webhook signature path
as critical, untested code. ``_enrich_payment_record`` is the single
source of money-truth normalisation: every Stripe / Razorpay row hits
it before insert and the FX path is the only thing translating Stripe's
USD cents into the INR rupees that revenue rollups use. A silent
regression here would either inflate or zero out the dashboard's
lifetime-revenue chart.

Cases:
    * INR-native (Razorpay paise) path — no FX call, fx_source="inr_native".
    * USD → INR path — calls ``fx.usd_to_inr``, persists the rate /
      source / fetched_at on the row so the row stays self-describing.
    * Unsupported currency — record is *not* dropped, but ``amount_inr``
      is explicitly None and ``fx_source="unsupported_currency"`` so
      rollups can exclude it instead of mis-summing the wrong unit.
    * Stripe webhook signature verification — bad signature → 400
      (``construct_event`` raises) and missing signature header → 400.
"""
import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from tests._deps_stub import install_deps_stub

install_deps_stub(force=True)

import deps  # noqa: E402
from routes import admin_monetization as mon  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ─────────────────────────────────────────────
# _enrich_payment_record
# ─────────────────────────────────────────────

def test_enrich_inr_native_paise_path():
    record = {
        "user_id": "u1",
        "plan": "starter",
        "provider": "razorpay",
        "amount_paise": 9900,
    }
    out = _run(mon._enrich_payment_record(record))

    assert out["amount_inr"] == 99.0
    assert out["currency_original"] == "INR"
    assert out["amount_original"] == 99.0
    assert out["fx_rate"] == 1.0
    assert out["fx_source"] == "inr_native"
    assert out["fx_fetched_at"] is None
    # The helper must not mutate the caller's dict in place.
    assert "amount_inr" not in record


def test_enrich_usd_to_inr_path(monkeypatch):
    """Stripe USD payment must be converted via the FX helper and the
    row must carry the rate, source, and fetched_at it was priced at."""
    fake_conv = {
        "inr": 8451.20,
        "rate": 84.512,
        "source": "frankfurter",
        "fetched_at": "2026-04-23T06:14:02+00:00",
        "as_of_date": "2026-04-23",
    }
    fake_fx = MagicMock(name="fx_module")
    fake_fx.usd_to_inr = AsyncMock(return_value=fake_conv)

    class _FxRateUnavailable(RuntimeError):
        pass
    fake_fx.FxRateUnavailable = _FxRateUnavailable
    monkeypatch.setitem(sys.modules, "fx", fake_fx)

    record = {
        "user_id": "u1",
        "plan": "pro",
        "provider": "stripe",
        "amount_cents": 10000,  # $100.00
        "currency": "usd",
    }
    out = _run(mon._enrich_payment_record(record))

    fake_fx.usd_to_inr.assert_awaited_once_with(100.0)
    assert out["amount_inr"] == pytest.approx(8451.20)
    assert out["currency_original"] == "USD"
    assert out["amount_original"] == 100.0
    assert out["fx_rate"] == pytest.approx(84.512)
    assert out["fx_source"] == "frankfurter"
    assert out["fx_fetched_at"] == "2026-04-23T06:14:02+00:00"


def test_enrich_unsupported_currency_marks_amount_inr_none():
    """A currency we don't yet have an FX source for must NOT silently
    default to 1:1 — leave amount_inr=None so the rollup excludes it."""
    record = {
        "user_id": "u1",
        "plan": "pro",
        "provider": "stripe",
        "amount_cents": 5000,
        "currency": "eur",
    }
    out = _run(mon._enrich_payment_record(record))
    assert out["amount_inr"] is None
    assert out["currency_original"] == "EUR"
    assert out["amount_original"] == 50.0
    assert out["fx_rate"] is None
    assert out["fx_source"] == "unsupported_currency"


def test_enrich_passthrough_when_amount_inr_already_set():
    """Migration-imported rows already carry amount_inr — don't
    re-derive (would be a noop today, but a future contributor swapping
    the order of helpers shouldn't accidentally re-FX them)."""
    record = {
        "user_id": "u1",
        "amount_paise": 9900,
        "amount_inr": 42.0,  # caller-set, must win
    }
    out = _run(mon._enrich_payment_record(record))
    assert out["amount_inr"] == 42.0


def test_enrich_zero_amount_record_keeps_schema():
    """A zero-amount activation_skipped row still needs the canonical
    fields so admin queries don't have to special-case missing keys."""
    out = _run(mon._enrich_payment_record({"user_id": "u1", "amount_paise": 0}))
    assert out["amount_inr"] == 0.0
    assert out["fx_source"] == "zero"


# ─────────────────────────────────────────────
# Stripe webhook signature verification
# ─────────────────────────────────────────────

class _DummyRequest:
    """Minimal stand-in for starlette.Request — our Stripe webhook only
    reads ``await request.body()`` and ``request.headers.get(...)``."""

    def __init__(self, body: bytes, headers: dict):
        self._body = body
        self.headers = headers

    async def body(self):
        return self._body


@pytest.fixture
def stub_stripe_keys(monkeypatch):
    async def _key():
        return "sk_test_dummy"
    monkeypatch.setattr(mon, "_get_stripe_key", _key)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_dummy")


def test_stripe_webhook_missing_signature_header(stub_stripe_keys, monkeypatch):
    fake_stripe = MagicMock(name="stripe")
    fake_stripe.Webhook = MagicMock()
    fake_stripe.Webhook.construct_event = MagicMock(
        side_effect=AssertionError("must not be called when sig missing"),
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)

    req = _DummyRequest(b'{"x":1}', headers={})
    with pytest.raises(HTTPException) as exc:
        _run(mon.stripe_webhook(req))
    assert exc.value.status_code == 400


def test_stripe_webhook_bad_signature_rejected(stub_stripe_keys, monkeypatch):
    """An invalid signature (construct_event raises) must surface as 400
    with no DB write — a silent 200 here would let an attacker mint
    arbitrary plan upgrades."""
    fake_stripe = MagicMock(name="stripe")

    class _SigError(Exception):
        pass

    fake_stripe.Webhook = MagicMock()
    fake_stripe.Webhook.construct_event = MagicMock(
        side_effect=_SigError("Signature verification failed"),
    )
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)
    deps.db.payments.insert_one = AsyncMock(return_value=None)
    deps.db.users.update_one = AsyncMock(return_value=None)

    req = _DummyRequest(
        body=json.dumps({"type": "checkout.session.completed"}).encode(),
        headers={"stripe-signature": "t=0,v1=deadbeef"},
    )
    with pytest.raises(HTTPException) as exc:
        _run(mon.stripe_webhook(req))
    assert exc.value.status_code == 400
    deps.db.payments.insert_one.assert_not_called()
    deps.db.users.update_one.assert_not_called()


def test_stripe_webhook_secret_missing_returns_503(monkeypatch):
    """If STRIPE_WEBHOOK_SECRET isn't configured, the webhook must
    refuse to process events — never fall back to "trust whatever
    Stripe sends" (the Task that motivated this guard)."""
    async def _key():
        return "sk_test_dummy"
    monkeypatch.setattr(mon, "_get_stripe_key", _key)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    req = _DummyRequest(b"{}", headers={"stripe-signature": "t=0,v1=anything"})
    with pytest.raises(HTTPException) as exc:
        _run(mon.stripe_webhook(req))
    assert exc.value.status_code == 503


# ─────────────────────────────────────────────
# Task #773 — happy-path coverage
# ─────────────────────────────────────────────
#
# The signature-rejection cases above prove we don't *accept* fraud.
# These cases prove we don't *drop* a real, signed payment: every
# downstream side-effect (mongo plan flip, pg mirror, supa mirror,
# activation email, redis session invalidation, payment row insert,
# duplicate-event idempotency, downgrade guard) must fire exactly
# once on a valid `checkout.session.completed`. A regression here
# silently fails to upgrade a paying customer — which is what the
# task title means by "successful payments can't be lost".


def _install_fake_stripe(monkeypatch, event_payload: dict):
    """Bypass real signature verification by stubbing
    ``stripe.Webhook.construct_event`` to return the canned event.
    The bad-signature test above already proves the real verifier
    is wired in; here we exercise the post-verification branches
    end-to-end."""
    fake_stripe = MagicMock(name="stripe")
    fake_stripe.Webhook = MagicMock()
    fake_stripe.Webhook.construct_event = MagicMock(return_value=event_payload)
    monkeypatch.setitem(sys.modules, "stripe", fake_stripe)
    return fake_stripe


def _reset_collections():
    """Refresh the AsyncMock collections we will assert against —
    other tests in the file (or earlier in the run) may have
    `.assert_not_called()` expectations that previously resolved them
    to specific AsyncMock instances we still hold references to.
    Reassigning here gives each happy-path test a clean slate."""
    deps.db.payments.find_one        = AsyncMock(return_value=None)
    deps.db.payments.insert_one      = AsyncMock(return_value=None)
    deps.db.payments.update_one      = AsyncMock(return_value=None)
    deps.db.users.find_one           = AsyncMock(return_value=None)
    deps.db.users.update_one         = AsyncMock(return_value=None)


def test_stripe_webhook_checkout_session_completed_happy_path(
    stub_stripe_keys, monkeypatch
):
    """A signed `checkout.session.completed` for an upgrading user
    must:
      * insert a `completed` payment row tagged with the session id,
      * flip mongo `users.plan` + bump credits_limit,
      * mirror the same plan/credits to Postgres,
      * fire-and-forget mirror to Supabase (`_supa_mirror` called),
      * queue the activation email via `email_templates`,
      * invalidate the user's redis session.
    """
    _reset_collections()
    # User is currently on free; the webhook should upgrade to pro.
    deps.db.users.find_one = AsyncMock(return_value={
        "id": "u-paying",
        "plan": "free",
        "email": "buyer@example.com",
        "name": "Buyer",
        "credits_limit": 0,
    })

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test_HAPPY",
            "metadata": {"user_id": "u-paying", "plan": "pro"},
            "amount_total": 1299,
            "currency": "usd",
        }},
    }
    _install_fake_stripe(monkeypatch, event)

    # Patch the side-effecting collaborators so we can assert on them.
    supa_mirror = MagicMock(name="_supa_mirror")
    monkeypatch.setattr(mon, "_supa_mirror", supa_mirror)
    redis_invalidate = MagicMock(name="_redis_invalidate_session")
    monkeypatch.setattr(mon, "_redis_invalidate_session", redis_invalidate)
    email_module = MagicMock(name="email_templates")
    email_module.send_plan_activation = AsyncMock(return_value=None)
    monkeypatch.setattr(mon, "email_templates", email_module)

    req = _DummyRequest(
        body=json.dumps(event).encode(),
        headers={"stripe-signature": "t=0,v1=signed"},
    )
    out = _run(mon.stripe_webhook(req))
    assert out == {"received": True}

    # Idempotency probe ran with the right session id.
    deps.db.payments.find_one.assert_awaited_once_with(
        {"stripe_session_id": "cs_test_HAPPY"}
    )
    # Payment row written exactly once with status=completed and the
    # canonical Stripe identifiers.
    deps.db.payments.insert_one.assert_awaited_once()
    inserted = deps.db.payments.insert_one.await_args.args[0]
    assert inserted["status"] == "completed"
    assert inserted["provider"] == "stripe"
    assert inserted["stripe_session_id"] == "cs_test_HAPPY"
    assert inserted["plan"] == "pro"
    assert inserted["amount_cents"] == 1299
    # Mongo plan flip happened with $set+$inc.
    deps.db.users.update_one.assert_awaited_once()
    upd_args = deps.db.users.update_one.await_args
    assert upd_args.args[0] == {"id": "u-paying"}
    assert upd_args.args[1]["$set"]["plan"] == "pro"
    assert upd_args.args[1]["$set"]["document_access"] == "full"
    assert upd_args.args[1]["$inc"]["credits_limit"] == mon.PLAN_CREDITS["pro"]
    # Supa mirror queued exactly once.
    assert supa_mirror.call_count == 1
    # Redis session invalidated for this user.
    redis_invalidate.assert_called_once_with("u-paying")
    # Activation email queued (asyncio.create_task wraps the coro;
    # assert the underlying call was made with the right kwargs).
    email_module.send_plan_activation.assert_called_once()
    email_kwargs = email_module.send_plan_activation.call_args.kwargs
    assert email_kwargs["email"] == "buyer@example.com"
    assert email_kwargs["plan"] == "pro"
    assert email_kwargs["credits"] == mon.PLAN_CREDITS["pro"]
    assert email_kwargs["amount_paise"] == mon.PLAN_PRICES_INR["pro"]


def test_stripe_webhook_duplicate_session_is_idempotent(
    stub_stripe_keys, monkeypatch
):
    """Stripe is at-least-once. A second `checkout.session.completed`
    for the same session id (or a delayed retry) must NOT double-credit
    or re-flip the plan."""
    _reset_collections()
    deps.db.payments.find_one = AsyncMock(return_value={
        "stripe_session_id": "cs_test_DUP",
        "status": "completed",
    })

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test_DUP",
            "metadata": {"user_id": "u-paying", "plan": "pro"},
            "amount_total": 1299,
            "currency": "usd",
        }},
    }
    _install_fake_stripe(monkeypatch, event)
    supa_mirror = MagicMock()
    monkeypatch.setattr(mon, "_supa_mirror", supa_mirror)

    req = _DummyRequest(b"{}", headers={"stripe-signature": "t=0,v1=signed"})
    out = _run(mon.stripe_webhook(req))
    assert out == {"received": True}

    # No write side-effects on the duplicate.
    deps.db.payments.insert_one.assert_not_awaited()
    deps.db.users.update_one.assert_not_awaited()
    supa_mirror.assert_not_called()


def test_stripe_webhook_downgrade_guard_logs_skipped(
    stub_stripe_keys, monkeypatch
):
    """A late event for a lower-tier plan (e.g. user upgraded
    starter→pro out-of-band, then a delayed starter checkout webhook
    arrives) must NOT downgrade them. The payment is logged with
    `status=skipped` so admins can audit, but `users.update_one` is
    never called."""
    _reset_collections()
    deps.db.users.find_one = AsyncMock(return_value={
        "id": "u-paying", "plan": "pro",
    })

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test_LATE",
            "metadata": {"user_id": "u-paying", "plan": "starter"},
            "amount_total": 199,
            "currency": "usd",
        }},
    }
    _install_fake_stripe(monkeypatch, event)

    req = _DummyRequest(b"{}", headers={"stripe-signature": "t=0,v1=signed"})
    out = _run(mon.stripe_webhook(req))
    assert out == {"received": True}

    # Payment row inserted, but as `skipped` with the audit reason.
    deps.db.payments.insert_one.assert_awaited_once()
    skipped = deps.db.payments.insert_one.await_args.args[0]
    assert skipped["status"] == "skipped"
    assert skipped["activation_skipped"] is True
    assert "higher plan" in skipped["skip_reason"]
    # User row was NOT mutated (no plan flip, no credit grant).
    deps.db.users.update_one.assert_not_awaited()


def test_stripe_webhook_invoice_paid_renewal_tops_up_credits(
    stub_stripe_keys, monkeypatch
):
    """Subscription renewal: `invoice.paid` for a known plan must
    add the same credit grant *without* re-flipping the plan column
    (the user already owns it) and must be idempotent on invoice id."""
    _reset_collections()
    event = {
        "type": "invoice.paid",
        "data": {"object": {
            "id": "in_test_RENEW",
            "subscription": "sub_test_1",
            "amount_paid": 1299,
            "currency": "usd",
            "subscription_details": {
                "metadata": {"user_id": "u-paying", "plan": "pro"},
            },
            "lines": {"data": []},
        }},
    }
    _install_fake_stripe(monkeypatch, event)

    req = _DummyRequest(b"{}", headers={"stripe-signature": "t=0,v1=signed"})
    out = _run(mon.stripe_webhook(req))
    assert out == {"received": True}

    deps.db.payments.find_one.assert_awaited_once_with(
        {"stripe_invoice_id": "in_test_RENEW"}
    )
    deps.db.payments.insert_one.assert_awaited_once()
    row = deps.db.payments.insert_one.await_args.args[0]
    assert row["status"] == "completed"
    assert row["renewal"] is True
    assert row["stripe_invoice_id"] == "in_test_RENEW"
    assert row["stripe_subscription_id"] == "sub_test_1"
    # Renewal tops up credits but does NOT rewrite the `plan` column.
    deps.db.users.update_one.assert_awaited_once()
    upd = deps.db.users.update_one.await_args.args[1]
    assert "plan" not in upd["$set"]
    assert upd["$inc"]["credits_limit"] == mon.PLAN_CREDITS["pro"]


def test_stripe_webhook_invoice_paid_unknown_plan_no_op(
    stub_stripe_keys, monkeypatch
):
    """Defensive: an `invoice.paid` with no recognisable user_id /
    plan in metadata (test invoices, ad-hoc invoices in the dashboard,
    etc.) must return 200 without touching any collection — not 4xx,
    or Stripe will keep retrying forever."""
    _reset_collections()
    event = {
        "type": "invoice.paid",
        "data": {"object": {
            "id": "in_test_GHOST",
            "amount_paid": 1,
            "currency": "usd",
            "lines": {"data": [{"metadata": {}}]},
        }},
    }
    _install_fake_stripe(monkeypatch, event)

    req = _DummyRequest(b"{}", headers={"stripe-signature": "t=0,v1=signed"})
    out = _run(mon.stripe_webhook(req))
    assert out == {"received": True}

    deps.db.payments.insert_one.assert_not_awaited()
    deps.db.users.update_one.assert_not_awaited()
