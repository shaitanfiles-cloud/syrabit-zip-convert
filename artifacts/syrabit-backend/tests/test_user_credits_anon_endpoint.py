"""Task #796 — surface the per-device daily quota on ``/user/credits``.

Anonymous students learn about the 30/day cap silently — they only
discover it when they hit the wall and get a 429. The chat composer
fix is to render "X / 30 free messages left today" against the same
device-keyed Redis counter that ``rate_limit_chat_optional`` charges,
which means ``/user/credits`` has to start returning a real
``used`` / ``remaining`` for un-authenticated callers (it used to
hard-code ``{"used": 0, "remaining": 30}``).

These tests pin down:

* Anon callers with no device cookie get the optimistic
  full-quota response (no false "0 left" on the very first paint).
* Anon callers with a verified device cookie get the *actual*
  Redis-backed count.
* The endpoint is read-only — repeated calls do not move the
  device counter (otherwise simply opening the chat page would
  silently charge the student a credit each time).
* The clamp keeps ``remaining`` >= 0 even if the underlying
  counter has somehow drifted past the daily limit, so the UI
  never displays a negative badge.
"""
import pytest

from tests._deps_stub import install_deps_stub

install_deps_stub(force=True)

import db_ops  # noqa: E402
import deps  # noqa: E402
from device_token import (  # noqa: E402
    DEVICE_COOKIE_NAME,
    mint_device_token,
    device_token_id,
)

fakeredis = pytest.importorskip("fakeredis")
fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routes.user import router as user_router  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)
    monkeypatch.setattr(deps, "redis_client", fake, raising=False)

    app = FastAPI()
    app.include_router(user_router)
    return app, fake


def test_anon_no_cookie_returns_full_quota(app):
    fastapi_app, _ = app
    client = TestClient(fastapi_app)
    resp = client.get("/user/credits")
    assert resp.status_code == 200
    body = resp.json()
    # Optimistic: a brand-new visitor with no device cookie must
    # never see "0 left" — they have not sent anything yet.
    assert body["used"] == 0
    assert body["limit"] >= 1
    assert body["remaining"] == body["limit"]
    assert body.get("anonymous") is True


def test_anon_with_cookie_reflects_redis_counter(app):
    fastapi_app, fake = app
    client = TestClient(fastapi_app)

    # Mint a real device cookie and seed the counter as if the
    # student had already sent 5 messages today.
    cookie = mint_device_token()
    token_id = device_token_id(cookie)
    assert token_id is not None
    for _ in range(5):
        assert db_ops.atomic_deduct_device_credit(token_id, daily_limit=30) is True

    resp = client.get("/user/credits", cookies={DEVICE_COOKIE_NAME: cookie})
    assert resp.status_code == 200
    body = resp.json()
    assert body["used"] == 5
    assert body["remaining"] == body["limit"] - 5


def test_anon_endpoint_does_not_charge_a_credit(app):
    """A student who refreshes the chat composer 100 times must
    still be at the same usage count — otherwise the badge becomes
    a self-fulfilling prophecy and the soft-CTA experience the
    task is trying to ship turns into a hostile one."""
    fastapi_app, _ = app
    client = TestClient(fastapi_app)

    cookie = mint_device_token()
    token_id = device_token_id(cookie)
    db_ops.atomic_deduct_device_credit(token_id, daily_limit=30)
    db_ops.atomic_deduct_device_credit(token_id, daily_limit=30)

    for _ in range(50):
        resp = client.get("/user/credits", cookies={DEVICE_COOKIE_NAME: cookie})
        assert resp.json()["used"] == 2

    # And a real charge still works — the peeks did not move the
    # cursor, so we should now land on 3.
    assert db_ops.atomic_deduct_device_credit(token_id, daily_limit=30) is True
    resp = client.get("/user/credits", cookies={DEVICE_COOKIE_NAME: cookie})
    assert resp.json()["used"] == 3


def test_anon_endpoint_clamps_remaining_to_zero(app):
    """If a legacy / corrupted counter ever exceeds the daily
    limit, the endpoint must still display a sane "0 left" rather
    than a negative number that would render as e.g. "-3 left"
    in the UI."""
    fastapi_app, fake = app
    client = TestClient(fastapi_app)

    cookie = mint_device_token()
    token_id = device_token_id(cookie)
    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fake.set(f"device_daily_credits:{token_id}:{today_str}", 9999)

    resp = client.get("/user/credits", cookies={DEVICE_COOKIE_NAME: cookie})
    body = resp.json()
    assert body["remaining"] == 0
    # ``used`` is also clamped so the UI never renders an
    # impossible "9999 / 30" caption.
    assert body["used"] == body["limit"]
