"""Task #485 — surface the staleness monitor's lock doc in
``GET /seo/auto-publish/schedule`` so admins can confirm the monitor
itself is alive without shell access.

Covers:
 * Missing lock doc (fresh install) → ``last_state=None`` so the UI
   can distinguish "not yet observed" from "observed and healthy".
 * Healthy doc → fields surface unchanged; debounce is 0 when no
   ``last_alert_at`` exists.
 * Active debounce → ``debounce_remaining_h`` reports the correct
   time remaining inside the 24h window.
 * Expired alert → debounce clamps to ``0`` instead of going
   negative.
 * The auto_publish_schedule endpoint includes the ``staleness_monitor``
   block in its response.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import seo_engine


def _now():
    return datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


# ─── _build_staleness_monitor_state ─────────────────────────────────────────

def test_build_state_missing_doc_reports_unknown():
    """A fresh install has no lock doc yet. We surface ``last_state=None``
    (NOT 'healthy') so the admin UI can render 'Not yet observed' and
    distinguish it from a monitor that ran and saw a healthy scheduler.
    Debounce must be 0 since there's nothing to debounce."""
    state = seo_engine._build_staleness_monitor_state(None, _now())
    assert state["last_state"] is None
    assert state["last_alert_at"] is None
    assert state["last_run_at_observed"] is None
    assert state["updated_at"] is None
    assert state["realert_interval_h"] == seo_engine._SEO_STALENESS_REALERT_INTERVAL_H
    assert state["debounce_remaining_h"] == 0.0


def test_build_state_healthy_doc_no_alert_has_zero_debounce():
    """A healthy bootstrap doc persists ``last_state`` + ``updated_at``
    but no ``last_alert_at`` (no alert was ever sent). Debounce must be
    0 — we'd page immediately on the next stale observation."""
    now = _now()
    state = seo_engine._build_staleness_monitor_state({
        "last_state": "healthy",
        "updated_at": (now - timedelta(hours=2)).isoformat(),
        "last_run_at_observed": (now - timedelta(hours=2)).isoformat(),
    }, now)
    assert state["last_state"] == "healthy"
    assert state["debounce_remaining_h"] == 0.0


def test_build_state_active_debounce_reports_time_remaining():
    """An alert was sent 3h ago — the next re-page is gated for ~21h."""
    now = _now()
    state = seo_engine._build_staleness_monitor_state({
        "last_state": "stale",
        "last_alert_at": (now - timedelta(hours=3)).isoformat(),
        "updated_at": now.isoformat(),
    }, now)
    assert state["last_state"] == "stale"
    # 24h window minus 3h elapsed = 21h remaining (allow tiny float drift).
    assert state["debounce_remaining_h"] == pytest.approx(21.0, abs=0.01)


def test_build_state_expired_alert_clamps_to_zero():
    """An alert sent 30h ago is well past the 24h debounce — the
    helper must clamp to 0 instead of returning a negative value
    (which would render as nonsense in the UI)."""
    now = _now()
    state = seo_engine._build_staleness_monitor_state({
        "last_state": "stale",
        "last_alert_at": (now - timedelta(hours=30)).isoformat(),
    }, now)
    assert state["debounce_remaining_h"] == 0.0


def test_build_state_handles_malformed_alert_timestamp():
    """A corrupt ``last_alert_at`` (parse failure) must not crash the
    response — fall back to 0 debounce so the UI still renders."""
    state = seo_engine._build_staleness_monitor_state({
        "last_state": "stale",
        "last_alert_at": "not-a-real-timestamp",
    }, _now())
    assert state["debounce_remaining_h"] == 0.0


# ─── /seo/auto-publish/schedule integration ─────────────────────────────────

class _FakeCursor:
    def __init__(self, items):
        self._items = list(items)
    def sort(self, *a, **kw):
        return self
    def limit(self, *a, **kw):
        return self
    async def to_list(self, n):
        return self._items[:n]


class _FakeColl:
    def __init__(self):
        self.docs: dict = {}
        self.log_rows: list = []
    async def find_one(self, query, projection=None, sort=None):
        if "_id" in query:
            d = self.docs.get(query["_id"])
            return dict(d) if d else None
        return None
    def find(self, *a, **kw):
        return _FakeCursor(self.log_rows)


class _FakeDb:
    def __init__(self):
        self.job_locks = _FakeColl()
        self.seo_generation_log = _FakeColl()


def test_endpoint_includes_staleness_monitor_block_with_active_debounce():
    """End-to-end: the route must read the staleness lock doc and
    return a ``staleness_monitor`` block alongside ``config``,
    ``last_marker``, and ``recent_runs``. With a 5h-old alert the
    debounce must report ~19h remaining."""
    fake_db = _FakeDb()
    # The route calls ``datetime.now(timezone.utc)`` directly, so anchor
    # the test on the same wall clock to avoid drift from our fixture's
    # frozen ``_now()``.
    now = datetime.now(timezone.utc)
    fake_db.job_locks.docs[seo_engine._SEO_STALENESS_ALERT_LOCK_ID] = {
        "_id": seo_engine._SEO_STALENESS_ALERT_LOCK_ID,
        "last_state": "stale",
        "last_alert_at": (now - timedelta(hours=5)).isoformat(),
        "last_run_at_observed": (now - timedelta(hours=50)).isoformat(),
        "updated_at": (now - timedelta(minutes=10)).isoformat(),
    }
    with patch.object(seo_engine, "_db", fake_db), \
         patch.object(seo_engine, "_require_admin", lambda: {"is_admin": True}):
        result = asyncio.run(seo_engine.auto_publish_schedule(_admin={"is_admin": True}))

    assert "staleness_monitor" in result
    mon = result["staleness_monitor"]
    assert mon["last_state"] == "stale"
    assert mon["last_alert_at"] is not None
    # ~19h remaining (24 - 5); allow modest slack for the wall-clock
    # advance between fixture setup and the route's own now() call.
    assert mon["debounce_remaining_h"] == pytest.approx(19.0, abs=0.1)
    assert mon["realert_interval_h"] == 24


def test_endpoint_returns_unknown_block_when_lock_doc_absent():
    """No lock doc yet (fresh install): the endpoint must still return
    a well-formed ``staleness_monitor`` block so the UI doesn't have
    to guard against ``undefined``."""
    fake_db = _FakeDb()
    with patch.object(seo_engine, "_db", fake_db), \
         patch.object(seo_engine, "_require_admin", lambda: {"is_admin": True}):
        result = asyncio.run(seo_engine.auto_publish_schedule(_admin={"is_admin": True}))

    mon = result["staleness_monitor"]
    assert mon["last_state"] is None
    assert mon["debounce_remaining_h"] == 0.0
    assert mon["realert_interval_h"] == 24
