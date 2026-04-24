"""Task #793 — production wiring tests for the device-keyed daily quota
in ``auth_deps.rate_limit_chat_optional``.

Replaces the original Task #768 IP-keyed test. The free-tier 30/day
budget is now keyed on a signed HttpOnly device-token cookie minted
by :mod:`device_token` so that AHSEC/SEBA students sharing an egress
IP (Jio/Airtel CGNAT, school WiFi, hostel/cyber-café) each get their
own private 30/day pool. The IP is kept only as a coarse abuse cap.

What we cover here:

* the same device cookie is capped at 30/day end-to-end (route ↔
  Lua deduct ↔ Redis counter);
* two different device cookies sharing one public IP each get their
  own full 30/day budget — the original CGNAT/school-WiFi failure
  mode is no longer reachable;
* a request that arrives without a cookie still succeeds *and* gets
  a fresh signed cookie issued in the response — never produces a
  hard 429 on the very first visit;
* the coarse per-IP cap fires only at the much higher
  ``IP_COARSE_DAILY_CAP`` threshold (not at 30);
* IP-extraction prefers ``cf-connecting-ip`` over ``x-forwarded-for``
  over ``request.client.host`` so quota counters key on the real
  client IP and not on the worker's egress.

The fail-closed-without-Redis case (Task #768) is preserved at the
end so we don't silently regress that availability tradeoff.
"""
import asyncio

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from tests._deps_stub import install_deps_stub

install_deps_stub(force=True)

import deps  # noqa: E402
import db_ops  # noqa: E402
import auth_deps  # noqa: E402
from device_token import DEVICE_COOKIE_NAME, mint_device_token  # noqa: E402

fakeredis = pytest.importorskip("fakeredis")


class _FakeReq:
    """Minimal ``Request`` double for the dependency under test.

    Only the attributes ``rate_limit_chat_optional`` actually reads
    are populated: the ``headers`` mapping (for ``cf-connecting-ip``
    / ``x-forwarded-for``) and ``client.host``. We keep this tiny on
    purpose so a regression that starts reading something new from
    the real ``Request`` immediately fails the tests.
    """

    def __init__(self, ip: str = "", headers: dict | None = None):
        self.client = type("c", (), {"host": ip})()
        # Header lookups in production use lowercase keys (Starlette
        # normalises) so we mirror that here to avoid a false-pass
        # when the implementation later switches to a CIMultiDict.
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


def _install_fake_redis(monkeypatch):
    """Wire fakeredis into every module that holds a redis_client ref.

    ``auth_deps``, ``db_ops`` and ``deps`` all keep their own
    module-level alias to the redis client, so all three have to be
    swapped or the dependency under test still talks to the real
    (offline-in-tests) production client.
    """
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(auth_deps, "redis_client", fake, raising=False)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)
    monkeypatch.setattr(deps, "redis_client", fake, raising=False)
    # Disable the per-minute throttle so we isolate the daily-quota
    # path; the per-minute logic has its own test surface.
    monkeypatch.setattr(auth_deps, "check_rate_limit", lambda *a, **kw: True)
    return fake


async def _call(req: _FakeReq, cookie: str | None = None) -> Response:
    """Drive the dependency once and return the (mutated) response."""
    resp = Response()
    await auth_deps.rate_limit_chat_optional(
        req, resp, user=None, syrabit_device=cookie,
    )
    return resp


def test_first_visit_without_cookie_succeeds_and_sets_cookie(monkeypatch):
    """A brand-new browser must not get a hard 429 on its first hit.

    This is the most-visible failure of the old per-IP code path: a
    student opening the site for the first time on a busy NAT saw
    "Daily free quota exhausted" before they could send a single
    message. The fix issues a fresh device cookie and lets the first
    request through, charged only against the (very high) coarse IP
    cap.
    """
    _install_fake_redis(monkeypatch)
    req = _FakeReq(headers={"cf-connecting-ip": "192.0.2.10"})
    resp = asyncio.run(_call(req, cookie=None))
    raw_cookie = resp.headers.get("set-cookie", "")
    assert DEVICE_COOKIE_NAME in raw_cookie, (
        f"first visit must mint a {DEVICE_COOKIE_NAME} cookie; "
        f"got headers={dict(resp.headers)}"
    )
    assert "HttpOnly" in raw_cookie
    assert "SameSite" in raw_cookie


def test_same_device_cookie_capped_at_30_per_day(monkeypatch):
    """End-to-end check: a single signed device cookie cannot exceed
    the free-plan ``credits_per_day`` (30) regardless of how many
    requests it sends. This is the live wiring of
    ``atomic_deduct_device_credit``.
    """
    _install_fake_redis(monkeypatch)
    cookie = mint_device_token()
    req = _FakeReq(headers={"cf-connecting-ip": "192.0.2.20"})

    # First visit (no cookie) is free under the 30-budget — it only
    # mints the cookie and is charged against the coarse cap. From
    # the *second* call onwards the cookie is presented and counts.
    asyncio.run(_call(req, cookie=None))

    for i in range(30):
        asyncio.run(_call(req, cookie=cookie))

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_call(req, cookie=cookie))
    assert excinfo.value.status_code == 429
    assert "Daily" in excinfo.value.detail or "quota" in excinfo.value.detail.lower()


def test_two_devices_on_same_ip_each_get_own_30(monkeypatch):
    """The original CGNAT/school-WiFi regression. Two browsers behind
    one public IP must NOT compete for the same 30/day pool. After
    one device exhausts its budget, the other device must still have
    a full 30 left.
    """
    _install_fake_redis(monkeypatch)
    cookie_a = mint_device_token()
    cookie_b = mint_device_token()
    shared_ip_headers = {"cf-connecting-ip": "192.0.2.30"}
    req = _FakeReq(headers=shared_ip_headers)

    # Drain device A entirely (30 successful + 1 rejected).
    for _ in range(30):
        asyncio.run(_call(req, cookie=cookie_a))
    with pytest.raises(HTTPException):
        asyncio.run(_call(req, cookie=cookie_a))

    # Device B on the same IP should still have its full 30. We don't
    # have to drain it entirely here; the regression we're guarding
    # against is "first call from B already 429s".
    for i in range(5):
        asyncio.run(_call(req, cookie=cookie_b))


def test_coarse_ip_cap_only_fires_at_high_threshold(monkeypatch):
    """The IP counter must NOT trip at 30 (that was the old bug).
    With a low ``IP_COARSE_DAILY_CAP`` we still need the cap to
    eventually fire so a single host can't script abuse — this test
    pins the boundary at the configured cap, not at ``credits_per_day``.
    """
    _install_fake_redis(monkeypatch)
    monkeypatch.setattr(auth_deps, "IP_COARSE_DAILY_CAP", 60, raising=False)

    req = _FakeReq(headers={"cf-connecting-ip": "192.0.2.40"})
    # Mint the cookie up-front so every call charges the IP counter
    # (the first-visit cookie-mint branch skips the device deduct
    # but still charges the IP cap, which is exactly what we want).
    asyncio.run(_call(req, cookie=None))
    cookie = mint_device_token()

    # 60 - 1 (already charged by the first-visit call) = 59 more.
    # Use a fresh device cookie per call so we never hit the 30/day
    # device cap before the 60/day IP cap.
    for _ in range(59):
        asyncio.run(_call(req, cookie=mint_device_token()))

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_call(req, cookie=mint_device_token()))
    assert excinfo.value.status_code == 429
    assert "network" in excinfo.value.detail.lower() or "ceiling" in excinfo.value.detail.lower()


def test_cf_connecting_ip_preferred_over_xff_and_client_host(monkeypatch):
    """Real-client-IP detection priority: cf-connecting-ip > xff > host.

    Two requests come in with the *same* xff and client.host (i.e.
    they look identical to the old code path) but different
    cf-connecting-ip values. They must end up on **different** IP
    counters in Redis — proving the higher-trust header wins.
    """
    fake = _install_fake_redis(monkeypatch)
    headers_user_a = {"cf-connecting-ip": "203.0.113.1", "x-forwarded-for": "10.0.0.1"}
    headers_user_b = {"cf-connecting-ip": "203.0.113.2", "x-forwarded-for": "10.0.0.1"}
    req_a = _FakeReq(ip="10.0.0.1", headers=headers_user_a)
    req_b = _FakeReq(ip="10.0.0.1", headers=headers_user_b)

    asyncio.run(_call(req_a, cookie=mint_device_token()))
    asyncio.run(_call(req_b, cookie=mint_device_token()))

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert fake.get(f"ip_daily_credits:203.0.113.1:{today}") == "1", (
        "cf-connecting-ip 203.0.113.1 should have its own counter"
    )
    assert fake.get(f"ip_daily_credits:203.0.113.2:{today}") == "1", (
        "cf-connecting-ip 203.0.113.2 should have its own counter"
    )
    # And critically: the xff IP that BOTH requests carried must NOT
    # have a counter — that would be the old behaviour where both
    # users would be billed against 10.0.0.1 and overlap.
    assert fake.get(f"ip_daily_credits:10.0.0.1:{today}") in (None, "0")


def test_xff_used_when_cf_connecting_ip_absent(monkeypatch):
    """Falls back to the first xff entry when cf-connecting-ip is
    missing. This is the path taken by ``workers/edge-proxy`` which
    strips cf-connecting-ip and rewrites it onto X-Forwarded-For
    before reaching us."""
    fake = _install_fake_redis(monkeypatch)
    req = _FakeReq(
        ip="127.0.0.1",
        headers={"x-forwarded-for": "198.51.100.7, 10.0.0.5"},
    )
    asyncio.run(_call(req, cookie=mint_device_token()))

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert fake.get(f"ip_daily_credits:198.51.100.7:{today}") == "1"
    # The proxy hop in the xff chain (10.0.0.5) and the immediate
    # peer (127.0.0.1) must not be charged.
    assert fake.get(f"ip_daily_credits:10.0.0.5:{today}") in (None, "0")
    assert fake.get(f"ip_daily_credits:127.0.0.1:{today}") in (None, "0")


def test_invalid_cookie_treated_as_first_visit(monkeypatch):
    """A forged or corrupted cookie value must NOT charge somebody
    else's counter; instead, the dependency mints a fresh signed
    cookie and lets the request through under the first-visit
    branch.
    """
    fake = _install_fake_redis(monkeypatch)
    req = _FakeReq(headers={"cf-connecting-ip": "192.0.2.99"})
    resp = asyncio.run(_call(req, cookie="not-a-valid-token"))
    raw_cookie = resp.headers.get("set-cookie", "")
    assert DEVICE_COOKIE_NAME in raw_cookie, (
        "an invalid cookie must trigger a fresh mint, not a 429"
    )
    # And no device counter is created for the bogus token id, since
    # first-visit explicitly skips the device deduct.
    matches = [k for k in fake.scan_iter("device_daily_credits:*")]
    assert matches == [], f"first-visit branch must not write a device counter, found {matches}"


def test_rate_limit_chat_optional_fails_closed_when_redis_down(monkeypatch):
    """Locks in the deliberate availability tradeoff (preserved from
    Task #768): when Redis is down we cannot make the cross-worker
    atomic guarantee, so anonymous traffic that has already been
    issued a device cookie is rejected with 429 rather than silently
    letting abusers through.
    """
    monkeypatch.setattr(auth_deps, "redis_client", None, raising=False)
    monkeypatch.setattr(db_ops, "redis_client", None, raising=False)
    monkeypatch.setattr(deps, "redis_client", None, raising=False)
    monkeypatch.setattr(auth_deps, "check_rate_limit", lambda *a, **kw: True)

    req = _FakeReq(headers={"cf-connecting-ip": "198.51.100.5"})
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_call(req, cookie=mint_device_token()))
    assert excinfo.value.status_code == 429
