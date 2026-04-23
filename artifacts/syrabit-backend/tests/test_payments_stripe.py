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
