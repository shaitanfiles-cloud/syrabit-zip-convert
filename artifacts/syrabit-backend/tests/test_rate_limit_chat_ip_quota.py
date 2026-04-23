"""Task #768 — production wiring test for the per-IP daily quota in
``auth_deps.rate_limit_chat_optional``.

The dependency now charges 1 credit per anonymous request through
``db_ops.atomic_deduct_ip_credit``. This test exercises the dependency
end-to-end (no mocks of the deduct primitive itself, only the Redis
backend swapped to fakeredis) and asserts that the 31st anonymous
request from the same IP raises HTTPException(429) — proving that the
Lua-script atomic check-and-increment is what gates the live route,
not just an unused helper.
"""
import asyncio

import pytest
from fastapi import HTTPException

from tests._deps_stub import install_deps_stub

install_deps_stub(force=True)

import deps  # noqa: E402
import db_ops  # noqa: E402
import auth_deps  # noqa: E402

fakeredis = pytest.importorskip("fakeredis")


class _FakeReq:
    def __init__(self, ip: str):
        self.client = type("c", (), {"host": ip})()
        self.headers = {}


def test_rate_limit_chat_optional_enforces_per_ip_daily_quota(monkeypatch):
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    # auth_deps.check_rate_limit and atomic_deduct_ip_credit both read
    # their respective module-level redis_client refs — set both.
    monkeypatch.setattr(auth_deps, "redis_client", fake, raising=False)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)
    monkeypatch.setattr(deps, "redis_client", fake, raising=False)

    # Make the per-minute guard effectively unlimited so we isolate the
    # daily-quota path.
    monkeypatch.setattr(
        auth_deps, "check_rate_limit",
        lambda *a, **kw: True,
    )

    ip = "192.0.2.7"
    req = _FakeReq(ip)

    async def _call_once():
        return await auth_deps.rate_limit_chat_optional(req, user=None)

    # First 30 anonymous calls succeed.
    for i in range(30):
        result = asyncio.run(_call_once())
        assert result is None, f"call #{i+1} should pass; got {result!r}"

    # The 31st must trip the daily quota (HTTP 429).
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_call_once())
    assert excinfo.value.status_code == 429
    assert "Daily" in excinfo.value.detail or "quota" in excinfo.value.detail.lower()


def test_rate_limit_chat_optional_fails_closed_when_redis_down(monkeypatch):
    """Locks in the deliberate availability tradeoff: when Redis is down
    we cannot make the cross-worker atomic guarantee, so anonymous
    traffic is rejected with 429 rather than silently letting abusers
    through. Documented in the task commit message and runbook."""
    monkeypatch.setattr(auth_deps, "redis_client", None, raising=False)
    monkeypatch.setattr(db_ops, "redis_client", None, raising=False)
    monkeypatch.setattr(deps, "redis_client", None, raising=False)
    monkeypatch.setattr(auth_deps, "check_rate_limit", lambda *a, **kw: True)

    req = _FakeReq("198.51.100.5")
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(auth_deps.rate_limit_chat_optional(req, user=None))
    assert excinfo.value.status_code == 429
