"""Task #17 — regression coverage for the push subscription endpoints.

The frontend ``usePushNotifications`` hook calls two endpoints when the user
grants permission:

  GET  /push/vapid-public-key   — fetch the VAPID public key
  POST /push/subscribe          — register the browser subscription

These tests exercise the backend handlers directly (no HTTP stack) using the
standard stub-deps pattern used elsewhere in this suite.  They confirm:

  * push_subscribe: valid body → update_one called with the correct doc shape,
    correct filter, and upsert=True.
  * push_subscribe: body missing the ``subscription`` key → 400.
  * push_subscribe: subscription dict missing ``endpoint`` → 400.
  * push_subscribe: admin user → role="admin" and admin_id is populated.
  * push_subscribe: regular user → role="student" and admin_id is "".
  * push_subscribe: reactivation fields are reset
    (deactivated_at / deactivation_reason / consecutive_failures_at_prune
    are $unset so a re-subscribe clears auto-prune state).
  * push_vapid_public_key: key present → returns {"public_key": ...}.
  * push_vapid_public_key: key missing → raises HTTPException 503.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from tests._deps_stub import install_deps_stub

# Install the deps stub before importing the route module so the route gets
# the mocked db, not a real Mongo connection attempt.
install_deps_stub(force=True)

import deps  # noqa: E402
from routes import admin_notifications as notif  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously — mirrors the pattern used in
    test_payments_razorpay.py and other tests in this suite."""
    return asyncio.run(coro)


FAKE_SUBSCRIPTION = {
    "endpoint": "https://push.example.com/endpoint/abc123",
    "expirationTime": None,
    "keys": {
        "p256dh": "BNjLs9mITqnCmqbpNxmUaEMb3zF8QKbZ",
        "auth": "secret-auth-key-base64url",
    },
}


def _student_user() -> dict:
    return {
        "id": "user-student-1",
        "email": "student@example.com",
        "is_admin": False,
    }


def _admin_user() -> dict:
    return {
        "id": "user-admin-1",
        "email": "admin@example.com",
        "is_admin": True,
    }


# ---------------------------------------------------------------------------
# push_subscribe — valid paths
# ---------------------------------------------------------------------------

class TestPushSubscribeValid:
    def test_valid_subscription_returns_ok(self):
        deps.db.push_subscriptions.update_one = AsyncMock(return_value=None)

        result = _run(
            notif.push_subscribe(
                {"subscription": FAKE_SUBSCRIPTION},
                user=_student_user(),
            )
        )

        assert result == {"ok": True}

    def test_valid_subscription_calls_update_one_once(self):
        deps.db.push_subscriptions.update_one = AsyncMock(return_value=None)

        _run(
            notif.push_subscribe(
                {"subscription": FAKE_SUBSCRIPTION},
                user=_student_user(),
            )
        )

        deps.db.push_subscriptions.update_one.assert_called_once()

    def test_filter_is_keyed_on_endpoint(self):
        deps.db.push_subscriptions.update_one = AsyncMock(return_value=None)

        _run(
            notif.push_subscribe(
                {"subscription": FAKE_SUBSCRIPTION},
                user=_student_user(),
            )
        )

        filter_doc = deps.db.push_subscriptions.update_one.call_args.args[0]
        assert filter_doc == {"endpoint": FAKE_SUBSCRIPTION["endpoint"]}

    def test_set_doc_contains_endpoint_and_subscription_info(self):
        deps.db.push_subscriptions.update_one = AsyncMock(return_value=None)

        _run(
            notif.push_subscribe(
                {"subscription": FAKE_SUBSCRIPTION},
                user=_student_user(),
            )
        )

        update_doc = deps.db.push_subscriptions.update_one.call_args.args[1]
        set_doc = update_doc["$set"]
        assert set_doc["endpoint"] == FAKE_SUBSCRIPTION["endpoint"]
        assert set_doc["subscription_info"] == FAKE_SUBSCRIPTION
        assert set_doc["active"] is True

    def test_update_one_called_with_upsert_true(self):
        """Resubscribing must upsert so existing docs are updated in place."""
        deps.db.push_subscriptions.update_one = AsyncMock(return_value=None)

        _run(
            notif.push_subscribe(
                {"subscription": FAKE_SUBSCRIPTION},
                user=_student_user(),
            )
        )

        call_kwargs = deps.db.push_subscriptions.update_one.call_args.kwargs
        assert call_kwargs.get("upsert") is True

    def test_reactivation_fields_are_unset(self):
        """A re-subscribe must clear auto-prune state via $unset."""
        deps.db.push_subscriptions.update_one = AsyncMock(return_value=None)

        _run(
            notif.push_subscribe(
                {"subscription": FAKE_SUBSCRIPTION},
                user=_student_user(),
            )
        )

        update_doc = deps.db.push_subscriptions.update_one.call_args.args[1]
        unset_doc = update_doc.get("$unset", {})
        assert "deactivated_at" in unset_doc
        assert "deactivation_reason" in unset_doc
        assert "consecutive_failures_at_prune" in unset_doc


# ---------------------------------------------------------------------------
# push_subscribe — role assignment
# ---------------------------------------------------------------------------

class TestPushSubscribeRoles:
    def test_student_user_stores_role_student_and_empty_admin_id(self):
        deps.db.push_subscriptions.update_one = AsyncMock(return_value=None)

        _run(
            notif.push_subscribe(
                {"subscription": FAKE_SUBSCRIPTION},
                user=_student_user(),
            )
        )

        set_doc = deps.db.push_subscriptions.update_one.call_args.args[1]["$set"]
        assert set_doc["role"] == "student"
        assert set_doc["is_admin"] is False
        assert set_doc["admin_id"] == ""

    def test_admin_user_stores_role_admin_and_admin_id(self):
        deps.db.push_subscriptions.update_one = AsyncMock(return_value=None)
        user = _admin_user()

        _run(
            notif.push_subscribe(
                {"subscription": FAKE_SUBSCRIPTION},
                user=user,
            )
        )

        set_doc = deps.db.push_subscriptions.update_one.call_args.args[1]["$set"]
        assert set_doc["role"] == "admin"
        assert set_doc["is_admin"] is True
        assert set_doc["admin_id"] == str(user["id"])


# ---------------------------------------------------------------------------
# push_subscribe — error paths
# ---------------------------------------------------------------------------

class TestPushSubscribeErrors:
    def test_missing_subscription_key_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _run(notif.push_subscribe({}, user=_student_user()))
        assert exc.value.status_code == 400

    def test_none_subscription_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _run(
                notif.push_subscribe(
                    {"subscription": None},
                    user=_student_user(),
                )
            )
        assert exc.value.status_code == 400

    def test_subscription_without_endpoint_raises_400(self):
        """An endpoint is required — without it the DB filter is useless."""
        bad_sub = {"keys": {"p256dh": "x", "auth": "y"}}  # no endpoint
        with pytest.raises(HTTPException) as exc:
            _run(
                notif.push_subscribe(
                    {"subscription": bad_sub},
                    user=_student_user(),
                )
            )
        assert exc.value.status_code == 400

    def test_empty_endpoint_string_raises_400(self):
        bad_sub = {**FAKE_SUBSCRIPTION, "endpoint": ""}
        with pytest.raises(HTTPException) as exc:
            _run(
                notif.push_subscribe(
                    {"subscription": bad_sub},
                    user=_student_user(),
                )
            )
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# push_vapid_public_key
# ---------------------------------------------------------------------------

class TestPushVapidPublicKey:
    def test_returns_public_key_dict(self):
        with patch.object(
            notif,
            "_get_or_create_vapid_keys",
            new=AsyncMock(return_value={"public_key": "BNjLs9mI...test-key"}),
        ):
            result = _run(notif.push_vapid_public_key())

        assert result == {"public_key": "BNjLs9mI...test-key"}

    def test_missing_key_raises_503(self):
        """If VAPID key generation fails the endpoint must refuse to serve."""
        with patch.object(
            notif,
            "_get_or_create_vapid_keys",
            new=AsyncMock(return_value={"public_key": ""}),
        ):
            with pytest.raises(HTTPException) as exc:
                _run(notif.push_vapid_public_key())

        assert exc.value.status_code == 503
