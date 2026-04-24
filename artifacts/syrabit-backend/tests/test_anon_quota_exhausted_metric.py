"""Task #798 — `chat.anon_quota_exhausted` metric coverage.

The per-device 30/day cap (Task #793 / #797) is the visible "wall" that
anonymous students hit before being asked to sign up. Without a metric
on how often the wall fires we can't tell whether 30 is the right cap;
without a join against subsequent sign-ups we can't tell whether the
wall is doing its job or just bouncing students off the site.

This file pins the wiring end-to-end:

* the metric fires from `auth_deps.rate_limit_chat_optional` exactly
  once per (device, day) — so a hammering script that retries a
  hundred times after the 429 doesn't inflate the unique-devices
  count we're going to base capacity decisions on;
* a brand-new account created within ~48h of the wall firing is
  attributed to "exhausted -> sign-up" via the device-cookie join;
* the admin chart endpoint surfaces the daily counts + conversion %;
* the one-shot Redis backfill replays today's already-at-cap counters
  so the chart isn't empty on first load.
"""
import asyncio
import importlib

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from tests._deps_stub import install_deps_stub

install_deps_stub(force=True)

import deps  # noqa: E402
import db_ops  # noqa: E402
import auth_deps  # noqa: E402
import metrics  # noqa: E402
from device_token import mint_device_token, device_token_id  # noqa: E402

fakeredis = pytest.importorskip("fakeredis")


class _FakeReq:
    """Same minimal Request double the existing rate-limit tests use."""

    def __init__(self, ip: str = "", headers: dict | None = None):
        self.client = type("c", (), {"host": ip})()
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


def _install_fake_redis(monkeypatch):
    """Wire fakeredis into deps + dependents and reset the per-test
    state on the metrics module so a previous test can't leak counts.

    The metric maintains in-memory window/dedupe/counter state at
    module scope (so workers don't lose data between requests). Each
    test gets a clean slate by zeroing them under the module's own
    lock.
    """
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(auth_deps, "redis_client", fake, raising=False)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)
    monkeypatch.setattr(deps, "redis_client", fake, raising=False)
    # Disable the per-minute throttle so we exercise only the daily
    # quota path (the per-minute logic has its own test surface).
    monkeypatch.setattr(auth_deps, "check_rate_limit", lambda *a, **kw: True)

    # Reset metric state. Hold the lock so we don't race a snapshot
    # collector that might be live in the test interpreter.
    with metrics._anon_exhaust_lock:
        metrics._anon_exhaust_window.clear()
        metrics._anon_exhaust_seen.clear()
        metrics._anon_exhausted_devices.clear()
        metrics._anon_signup_after_exhaust_devices.clear()
    return fake


async def _call(req: _FakeReq, cookie: str | None = None) -> Response:
    resp = Response()
    await auth_deps.rate_limit_chat_optional(
        req, resp, user=None, syrabit_device=cookie,
    )
    return resp


# ─────────────────────────────────────────────────────────────────────
# Wall-firing metric
# ─────────────────────────────────────────────────────────────────────


def test_metric_fires_once_when_device_cap_is_hit(monkeypatch):
    """Drain a single device cookie's 30/day budget end-to-end and
    assert that the 31st request both 429s AND records exactly one
    `chat.anon_quota_exhausted` event for that device."""
    _install_fake_redis(monkeypatch)
    cookie = mint_device_token()
    token_id = device_token_id(cookie)
    req = _FakeReq(headers={"cf-connecting-ip": "192.0.2.50"})

    for _ in range(30):
        asyncio.run(_call(req, cookie=cookie))

    # 31st must 429 and record the metric.
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_call(req, cookie=cookie))
    assert excinfo.value.status_code == 429

    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["total_exhausted"] == 1, stats
    assert stats["unique_devices_exhausted"] == 1, stats
    assert stats["has_data"] is True

    # Cross-worker tracking: the device hash should be in today's
    # Redis sorted set (TTL 48h) so a sign-up join from another
    # gunicorn worker can find it.
    fake = deps.redis_client
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert fake.zscore(f"chat:anon_exhausted_devices:{today}", token_id) is not None


def test_metric_dedupes_repeated_429s_from_same_device(monkeypatch):
    """The cap fires on every retry from an already-exhausted device.
    The metric must collapse those into a single event per device per
    day — otherwise a 100-rps panic-retry loop would dwarf the real
    "students who hit the wall" signal we want to chart.
    """
    _install_fake_redis(monkeypatch)
    cookie = mint_device_token()
    req = _FakeReq(headers={"cf-connecting-ip": "192.0.2.51"})

    for _ in range(30):
        asyncio.run(_call(req, cookie=cookie))

    # 10 hammered retries after the cap. All must 429; the metric
    # must record exactly one event total.
    for _ in range(10):
        with pytest.raises(HTTPException):
            asyncio.run(_call(req, cookie=cookie))

    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["total_exhausted"] == 1, stats
    assert stats["unique_devices_exhausted"] == 1, stats


def test_metric_counts_distinct_devices_separately(monkeypatch):
    """Two devices sharing a NAT each consume their own 30/day quota
    (Task #793). Each one hitting the wall must register as its own
    event in the metric — that's the per-device unique we want to
    track for capacity tuning."""
    _install_fake_redis(monkeypatch)
    cookie_a = mint_device_token()
    cookie_b = mint_device_token()
    req = _FakeReq(headers={"cf-connecting-ip": "192.0.2.52"})

    for cookie in (cookie_a, cookie_b):
        for _ in range(30):
            asyncio.run(_call(req, cookie=cookie))
        with pytest.raises(HTTPException):
            asyncio.run(_call(req, cookie=cookie))

    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["unique_devices_exhausted"] == 2, stats
    assert stats["total_exhausted"] == 2, stats


def test_metric_emits_label_breakdowns(monkeypatch):
    """The chart needs at least one populated by-hour and by-day-of-week
    bucket. The exact day/hour depends on the test wall-clock, but the
    sum across all buckets must equal `total_exhausted` so the chart
    components don't render empty bars."""
    _install_fake_redis(monkeypatch)
    cookie = mint_device_token()
    req = _FakeReq(headers={"cf-connecting-ip": "192.0.2.53"})

    for _ in range(30):
        asyncio.run(_call(req, cookie=cookie))
    with pytest.raises(HTTPException):
        asyncio.run(_call(req, cookie=cookie))

    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert sum(stats["by_hour"].values()) == stats["total_exhausted"]
    assert sum(stats["by_day_of_week"].values()) == stats["total_exhausted"]
    assert any(v > 0 for v in stats["by_hour"].values())


# ─────────────────────────────────────────────────────────────────────
# Sign-up conversion join
# ─────────────────────────────────────────────────────────────────────


def test_signup_with_recent_exhausted_device_counts_as_conversion(monkeypatch):
    """The whole point of the metric: a brand-new account created on
    a device that hit the wall ~hours ago is the funnel we want to
    measure. `record_signup_with_device` must return True and bump
    the cumulative conversion counter."""
    _install_fake_redis(monkeypatch)
    token_id = "f" * 32
    metrics.record_anon_quota_exhausted(token_id, ip="203.0.113.10", plan_target="free")

    matched = metrics.record_signup_with_device(token_id)
    assert matched is True

    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["signup_after_exhaust"] >= 1
    assert stats["unique_devices_exhausted"] == 1
    # 1 signup / 1 unique exhausted device = 100% in the toy test.
    assert stats["conversion_pct"] == 100.0


def test_signup_with_unrelated_device_does_not_count(monkeypatch):
    """An organic sign-up from a device that never hit the wall must
    NOT inflate the conversion ratio — otherwise the metric would
    just track total sign-ups and tell us nothing about the cap."""
    _install_fake_redis(monkeypatch)
    metrics.record_anon_quota_exhausted("a" * 32, ip="203.0.113.11", plan_target="free")
    matched = metrics.record_signup_with_device("b" * 32)  # different device
    assert matched is False
    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["signup_after_exhaust"] == 0
    assert stats["conversion_pct"] == 0.0


def test_signup_join_uses_redis_so_it_works_across_workers(monkeypatch):
    """The exhaustion event happened on worker A; the sign-up arrives
    on worker B with no in-memory state. The Redis sorted set is what
    bridges them. We simulate that by clearing the in-process mirror
    AFTER the exhaustion is recorded but BEFORE the sign-up call —
    the join must still find the device via Redis.
    """
    _install_fake_redis(monkeypatch)
    token_id = "c" * 32
    metrics.record_anon_quota_exhausted(token_id, ip="203.0.113.12", plan_target="free")

    # Wipe the in-process mirror to simulate a different gunicorn
    # worker that never saw the original 429.
    with metrics._anon_exhaust_lock:
        metrics._anon_exhausted_devices.clear()

    matched = metrics.record_signup_with_device(token_id)
    assert matched is True


# ─────────────────────────────────────────────────────────────────────
# Redis-down misclassification guard
# ─────────────────────────────────────────────────────────────────────


def test_metric_not_emitted_when_redis_is_down(monkeypatch):
    """`atomic_deduct_device_credit` returns False in two very different
    states: (a) the device's daily counter actually reached the cap, and
    (b) Redis itself is unreachable (fail-closed). Without the
    `peek_device_credit_used` guard added in Task #798, every request
    during a Redis outage would show up in the chart as a "wall-hit"
    and we'd misread the outage as a sudden capacity-tuning crisis.
    This test pins the guard: with Redis offline, no metric is recorded.
    """
    _install_fake_redis(monkeypatch)
    # Now drop Redis on the floor — same shape as the fail-closed path
    # `atomic_deduct_device_credit` exits through when redis_client is
    # None.
    monkeypatch.setattr(db_ops, "redis_client", None, raising=False)
    monkeypatch.setattr(deps, "redis_client", None, raising=False)

    cookie = mint_device_token()
    req = _FakeReq(headers={"cf-connecting-ip": "192.0.2.99"})

    # The very first request will get a 429 (atomic_deduct returns
    # False because Redis is down), but the metric must NOT fire —
    # the peek guard sees 0 < 30 and short-circuits.
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(_call(req, cookie=cookie))
    assert excinfo.value.status_code == 429

    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["total_exhausted"] == 0, stats
    assert stats["unique_devices_exhausted"] == 0, stats
    assert stats["has_data"] is False


# ─────────────────────────────────────────────────────────────────────
# 24h conversion-window boundary
# ─────────────────────────────────────────────────────────────────────


def test_signup_outside_24h_window_does_not_count_as_conversion(monkeypatch):
    """The product question is `next-24h sign-up conversion among
    exhausted devices`. The Redis sorted set's TTL is sized at 48h to
    catch late signups arriving on a different worker, but the actual
    conversion gate is 24h. A signup arriving at T+25h must NOT be
    counted, otherwise we'd be measuring "next-48h conversion" and
    overstating the funnel by ~30-40%.
    """
    fake = _install_fake_redis(monkeypatch)
    token_id = "d" * 32
    metrics.record_anon_quota_exhausted(token_id, ip="203.0.113.20", plan_target="free")

    # Fast-forward both the in-memory mirror and the Redis zscore back
    # to T-25h so the signup arrives outside the 24h window.
    import time as _t
    twenty_five_h_ago = _t.time() - (25 * 3600)
    with metrics._anon_exhaust_lock:
        metrics._anon_exhausted_devices[token_id] = twenty_five_h_ago
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fake.zadd(f"chat:anon_exhausted_devices:{today}", {token_id: twenty_five_h_ago})

    matched = metrics.record_signup_with_device(token_id)
    assert matched is False, "25h-old exhaustion event must not count"

    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["signup_after_exhaust"] == 0


def test_signup_just_inside_24h_window_does_count(monkeypatch):
    """The strict-boundary partner of the previous test. A signup at
    T+23h59m is still inside the 24h window and must register, so we
    don't accidentally exclude legitimate next-day-morning signups by
    being one second too aggressive.
    """
    fake = _install_fake_redis(monkeypatch)
    token_id = "e" * 32
    metrics.record_anon_quota_exhausted(token_id, ip="203.0.113.21", plan_target="free")

    import time as _t
    just_under_24h_ago = _t.time() - (23 * 3600 + 59 * 60)
    with metrics._anon_exhaust_lock:
        metrics._anon_exhausted_devices[token_id] = just_under_24h_ago
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fake.zadd(f"chat:anon_exhausted_devices:{today}", {token_id: just_under_24h_ago})

    matched = metrics.record_signup_with_device(token_id)
    assert matched is True


def test_signup_conversion_is_unique_per_device(monkeypatch):
    """If a device retries signup (e.g. duplicate-email error then
    successful retry under a new email), `record_signup_with_device`
    will be called twice for the same device cookie. The conversion
    metric must count the device once, not twice — otherwise we'd
    inflate the numerator and could even compute a >100% conversion
    rate, which is nonsensical for a funnel ratio.
    """
    _install_fake_redis(monkeypatch)
    token_id = "1" * 32
    metrics.record_anon_quota_exhausted(token_id, ip="203.0.113.30", plan_target="free")

    assert metrics.record_signup_with_device(token_id) is True
    assert metrics.record_signup_with_device(token_id) is True   # retry path

    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["signup_after_exhaust"] == 1, stats
    assert stats["conversion_pct"] == 100.0


# ─────────────────────────────────────────────────────────────────────
# Backfill
# ─────────────────────────────────────────────────────────────────────


def test_backfill_replays_already_exhausted_devices_today(monkeypatch):
    """Today's chart would otherwise be empty until the first new
    exhaustion event under the deployed metric. The backfill scans
    the existing `device_daily_credits:*:<today>` keys and replays
    the metric for any counter already at the cap."""
    fake = _install_fake_redis(monkeypatch)
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Three devices already at cap (30/30) and one well below (5/30).
    fake.set(f"device_daily_credits:dev_a:{today}", "30")
    fake.set(f"device_daily_credits:dev_b:{today}", "30")
    fake.set(f"device_daily_credits:dev_c:{today}", "30")
    fake.set(f"device_daily_credits:dev_d:{today}", "5")

    backfilled = metrics.backfill_anon_quota_exhausted_today()
    assert backfilled == 3, backfilled

    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["unique_devices_exhausted"] == 3
    assert stats["total_exhausted"] == 3


def test_backfill_is_idempotent(monkeypatch):
    """A clumsy admin clicking "Backfill" twice in a row must not
    double-count. Dedupe inside `record_anon_quota_exhausted` is what
    protects us — this test pins that contract from the backfill
    entry point."""
    fake = _install_fake_redis(monkeypatch)
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fake.set(f"device_daily_credits:dev_x:{today}", "30")
    fake.set(f"device_daily_credits:dev_y:{today}", "30")

    first = metrics.backfill_anon_quota_exhausted_today()
    second = metrics.backfill_anon_quota_exhausted_today()
    assert first == 2
    assert second == 0   # already counted; no new events
    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["unique_devices_exhausted"] == 2


# ─────────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────────


def test_metric_no_op_without_token(monkeypatch):
    """`record_anon_quota_exhausted("")` must not crash and must not
    record anything. Belt-and-braces against a future caller that
    forgets to pass the token id."""
    _install_fake_redis(monkeypatch)
    assert metrics.record_anon_quota_exhausted("", ip="") is True
    # An anonymous-IP-only event WAS recorded (we don't lose the signal),
    # but the unique-devices counter stays at 0 since no token was given.
    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["unique_devices_exhausted"] == 0
    assert stats["total_exhausted"] == 1


def test_signup_no_op_without_token(monkeypatch):
    """`record_signup_with_device("")` must short-circuit to False so
    we don't accidentally tag the entire anonymous sign-up funnel as
    "converted" the first time the metric ships."""
    _install_fake_redis(monkeypatch)
    metrics.record_anon_quota_exhausted("a" * 32, ip="", plan_target="free")
    assert metrics.record_signup_with_device("") is False
    stats = metrics.get_anon_quota_exhausted_stats(days=1)
    assert stats["signup_after_exhaust"] == 0


# ─────────────────────────────────────────────────────────────────────
# Admin endpoint contract
# ─────────────────────────────────────────────────────────────────────


def test_admin_endpoint_returns_payload_and_honours_backfill(monkeypatch):
    """`GET /admin/chat/anon-quota-exhausted` is the only consumer of
    the metric today. Pin the contract:
      * gated on `get_admin_user` (we override it to a fake admin
        rather than actually authing — the production gating is
        covered by `auth_deps.get_admin_user`'s own tests);
      * empty state returns a clean `has_data: false` envelope, not
        a 500;
      * `?backfill=1` triggers the Redis scan and returns the count
        in `backfilled_today` so the admin UI can show "+N events
        seeded" feedback;
      * the response shape includes `daily`, `by_hour`,
        `by_day_of_week`, `signup_after_exhaust`, `conversion_pct`,
        `period_days`, and `alert` so the dashboard component
        doesn't have to defensively guard against missing keys.
    """
    fake = _install_fake_redis(monkeypatch)
    fastapi = pytest.importorskip("fastapi")
    from fastapi import FastAPI  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    from routes.admin_advanced import router as admin_router  # noqa: E402
    from auth_deps import get_admin_user  # noqa: E402

    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[get_admin_user] = lambda: {"email": "admin@example.com"}

    client = TestClient(app)

    # 1. Empty-state happy path.
    r = client.get("/admin/chat/anon-quota-exhausted?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    for k in (
        "period_days", "total_exhausted", "unique_devices_exhausted",
        "signup_after_exhaust", "conversion_pct", "daily",
        "by_hour", "by_day_of_week", "has_data", "backfilled_today",
        "alert",
    ):
        assert k in body, f"missing key {k} in response: {body}"
    assert body["has_data"] is False
    assert body["backfilled_today"] == 0
    assert body["alert"] == "green"

    # 2. Seed Redis with two at-cap devices and call with backfill=1.
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fake.set(f"device_daily_credits:dev_admin_a:{today}", "30")
    fake.set(f"device_daily_credits:dev_admin_b:{today}", "30")

    r = client.get("/admin/chat/anon-quota-exhausted?days=7&backfill=1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["backfilled_today"] == 2
    assert body["unique_devices_exhausted"] == 2
    assert body["has_data"] is True

    app.dependency_overrides = {}
