"""Task #423 — recorder hook + stats endpoint tests."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.fixture
def mock_admin():
    return {"id": "admin-1", "email": "ops@syrabit.ai", "is_admin": True}


@pytest.fixture
def app_client(mock_admin):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.cms_sarvam_health import router

    app = FastAPI()
    app.include_router(router)
    from auth_deps import get_admin_user
    app.dependency_overrides = {get_admin_user: lambda: mock_admin}
    return TestClient(app)


def _aggregate_mock(results):
    """Mock motor's `coll.aggregate(...).to_list(length=N)` chain — the
    cursor returned by `aggregate()` is a synchronous object whose
    `to_list` method is the awaitable."""
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=results)
    return cursor


def _runs_collection_mock(*, overall, actions, behaviours, ratios=None):
    """Builds a MagicMock collection where successive `aggregate()`
    calls return the four pipelines in the order the route runs them:
    overall → actions → behaviours → ratio sample."""
    coll = MagicMock()
    coll.aggregate = MagicMock(side_effect=[
        _aggregate_mock(overall),
        _aggregate_mock(actions),
        _aggregate_mock(behaviours),
        _aggregate_mock(ratios or []),
    ])
    coll.insert_one = AsyncMock(return_value=None)
    coll.create_index = AsyncMock(return_value=None)
    return coll


def _patch_db_with_runs_coll(coll):
    """Routes do `from deps import db as _db` then `_db[_ASM_RUNS_COLLECTION]`,
    so we need __getitem__ to return the right collection."""
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=coll)
    db.api_config = MagicMock()
    db.api_config.find_one = AsyncMock(return_value=None)
    return patch("deps.db", db, create=True)


class TestStatsEndpoint:
    def test_window_validation(self, app_client):
        coll = _runs_collection_mock(overall=[], actions=[], behaviours=[])
        with _patch_db_with_runs_coll(coll):
            r = app_client.get("/admin/assamese-purity/stats?window=junk")
        assert r.status_code == 400

    def test_empty_window_returns_zero_totals(self, app_client):
        coll = _runs_collection_mock(overall=[], actions=[], behaviours=[])
        with _patch_db_with_runs_coll(coll):
            r = app_client.get("/admin/assamese-purity/stats?window=24h")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["window"] == "24h"
        assert body["total"] == 0
        assert body["active"] == 0
        assert body["avg_ratio"] == 0.0
        assert body["p95_ratio"] == 0.0
        assert body["actions"] == {}
        assert body["behaviours"] == {}

    def test_aggregates_total_active_and_p95(self, app_client):
        # 10 runs with ratios 0.01..0.10 — p95 (nearest-rank) is 0.10.
        ratios = [round(0.01 * (i + 1), 4) for i in range(10)]
        overall = [{
            "_id": None,
            "total": 10,
            "avg_ratio": sum(ratios) / len(ratios),
            "active": 6,         # 6 non-noop
            "translated": 4,
            "regenerated": 1,
        }]
        actions = [
            {"_id": "noop", "count": 4},
            {"_id": "translated", "count": 4},
            {"_id": "stripped", "count": 1},
            {"_id": "translated+stripped", "count": 1},
        ]
        behaviours = [
            {"_id": "translate", "count": 7},
            {"_id": "translate+regenerate", "count": 3},
        ]
        coll = _runs_collection_mock(
            overall=overall, actions=actions, behaviours=behaviours,
            ratios=[{"ratio": r} for r in ratios],
        )
        with _patch_db_with_runs_coll(coll):
            r = app_client.get("/admin/assamese-purity/stats?window=7d")
        assert r.status_code == 200
        body = r.json()
        assert body["window"] == "7d"
        assert body["total"] == 10
        assert body["active"] == 6
        assert body["translated"] == 4
        assert body["regenerated"] == 1
        # nearest-rank p95 over 10 sorted samples → index 9 (0-based).
        assert body["p95_ratio"] == pytest.approx(0.10, abs=1e-6)
        assert body["avg_ratio"] == pytest.approx(0.055, abs=1e-6)
        # Action / behaviour breakdown is preserved as a dict.
        assert body["actions"]["noop"] == 4
        assert body["actions"]["translated"] == 4
        assert body["behaviours"]["translate"] == 7
        # Window timestamp is the lower bound, in iso-8601.
        assert "T" in body["since"]

    def test_p95_uses_ceil_nearest_rank_for_small_samples(self, app_client):
        """For n=11, nearest-rank p95 = sample at index ceil(0.95*11)-1
        = 10, i.e. the maximum value. The earlier `round(0.95*11)-1` =
        9 understated p95 by one rank — lock that down."""
        ratios = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.99]
        overall = [{"_id": None, "total": 11, "avg_ratio": sum(ratios) / 11,
                    "active": 11, "translated": 0, "regenerated": 0}]
        coll = _runs_collection_mock(
            overall=overall, actions=[{"_id": "stripped", "count": 11}],
            behaviours=[{"_id": "strip", "count": 11}],
            ratios=[{"ratio": r} for r in ratios],
        )
        with _patch_db_with_runs_coll(coll):
            r = app_client.get("/admin/assamese-purity/stats?window=24h")
        assert r.status_code == 200
        # ceil(0.95 * 11) - 1 = 10 → ratios_sorted[10] = 0.99 (the max)
        assert r.json()["p95_ratio"] == pytest.approx(0.99, abs=1e-6)

    def test_aggregation_failure_returns_safe_payload(self, app_client):
        """If mongo blows up, the dashboard must still get a sane shape
        — admins shouldn't see a 500 just because the stats collection
        is unavailable."""
        coll = MagicMock()
        coll.aggregate = MagicMock(side_effect=RuntimeError("mongo down"))
        with _patch_db_with_runs_coll(coll):
            r = app_client.get("/admin/assamese-purity/stats?window=24h")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["total"] == 0
        assert "error" in body


class TestRecorderInstallation:
    """The route module installs `_record_assamese_run` as the
    lang_sanitizer recorder at import time. Verify it (a) is installed,
    (b) builds the expected mongo doc, (c) never raises."""

    def test_recorder_is_wired(self):
        import lang_sanitizer
        from routes.cms_sarvam_health import _record_assamese_run
        assert lang_sanitizer._RUN_RECORDER is _record_assamese_run

    def test_recorder_silent_when_no_running_loop(self):
        from routes.cms_sarvam_health import _record_assamese_run
        # No event loop running → just returns; should not raise.
        _record_assamese_run({"action": "noop", "behaviour": "off"})

    def test_recorder_schedules_insert_when_loop_running(self):
        """Inside a running loop, the recorder should fire-and-forget an
        insert into the runs collection. We verify the insert was
        attempted with the expected normalised doc shape."""
        from routes.cms_sarvam_health import _record_assamese_run

        recorded = {}

        async def _fake_insert(doc):
            recorded.update(doc)

        async def _run():
            with patch("routes.cms_sarvam_health._insert_assamese_run", _fake_insert):
                _record_assamese_run({
                    "action": "translated+stripped",
                    "behaviour": "translate",
                    "ratio": 0.02,
                    "original_ratio": 0.18,
                    "threshold": 0.05,
                    "translated": True,
                    "regenerated": False,
                    "has_assamese": True,
                })
                # Yield so the scheduled task runs.
                await asyncio.sleep(0)
                await asyncio.sleep(0)

        asyncio.run(_run())
        # `ratio` in the persisted doc is the PRE-cleanup ratio, not the
        # post-cleanup ratio — that's what the dashboard charts.
        assert recorded.get("ratio") == pytest.approx(0.18)
        assert recorded.get("post_ratio") == pytest.approx(0.02)
        assert recorded.get("action") == "translated+stripped"
        assert recorded.get("behaviour") == "translate"
        assert recorded.get("translated") is True
        assert recorded.get("regenerated") is False
        assert "ts" in recorded


class TestSanitizerEmitsRuns:
    """The sanitiser must call the recorder at every return point so the
    dashboard sees noop runs AND active cleanup runs."""

    def setup_method(self):
        from lang_sanitizer import set_run_recorder
        self._captured = []
        set_run_recorder(lambda d: self._captured.append(d))

    def teardown_method(self):
        # Re-install the production recorder so other tests aren't
        # affected by our temporary swap.
        from lang_sanitizer import set_run_recorder
        from routes.cms_sarvam_health import _record_assamese_run
        set_run_recorder(_record_assamese_run)

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_off_behaviour_emits_noop(self):
        from lang_sanitizer import sanitize_assamese_with_optional_regenerate
        text = "উৰুকা হৈছে মাঘ বিহুৰ পূৰ্বৰ ৰাতিৰ উৎসৱ। me uses ssible terms."
        self._run(sanitize_assamese_with_optional_regenerate(text, behaviour="off"))
        assert len(self._captured) == 1
        assert self._captured[0]["action"] == "noop"
        assert self._captured[0]["behaviour"] == "off"

    def test_clean_text_emits_noop(self):
        from lang_sanitizer import sanitize_assamese_with_optional_regenerate
        text = "উৰুকা হৈছে মাঘ বিহুৰ পূৰ্বৰ ৰাতিৰ উৎসৱ।"
        self._run(sanitize_assamese_with_optional_regenerate(text, behaviour="strip"))
        assert any(d["action"] == "noop" for d in self._captured)

    def test_regenerate_emits_exactly_one_run(self):
        """Regression for #423 review finding: a successful regenerate
        used to emit TWO docs (inner translate/strip + outer regenerate),
        inflating dashboard totals. Each top-level invocation must
        produce exactly one persisted run."""
        from lang_sanitizer import sanitize_assamese_with_optional_regenerate
        leaky = "উৰুকা me uses ssible terms চমুকৈ ক'লে maths chapter problems."
        clean_retry = "উৰুকা হৈছে মাঘ বিহুৰ পূৰ্বৰ ৰাতিৰ উৎসৱ। সকলোৱে ইয়াত আনন্দ কৰে।"

        async def _regen():
            return clean_retry

        self._run(sanitize_assamese_with_optional_regenerate(
            leaky, behaviour="translate+regenerate", regenerate_callable=_regen,
        ))
        assert len(self._captured) == 1, (
            f"expected 1 run doc, got {len(self._captured)}: "
            f"{[d.get('action') for d in self._captured]}"
        )
        # The single emitted doc should reflect the OUTER regenerate
        # event (not the inner translate/strip step).
        assert self._captured[0].get("regenerated") is True
        assert "regenerated" in self._captured[0]["action"]

    def test_regenerate_with_leaky_retry_emits_exactly_one_run(self):
        """Even when the regenerate retry is improved over the original
        but STILL above threshold (so the inner pipeline must strip),
        we must emit exactly one run doc — the inner strip emission is
        suppressed via `_emit=False` and only the outer wrapper emits."""
        from lang_sanitizer import sanitize_assamese_with_optional_regenerate
        leaky = (
            "উৰুকা me uses ssible terms চমুকৈ ক'লে maths chapter problems "
            "and physics formulas list. ssible help required."
        )
        improved_but_leaky = (
            "উৰুকা হৈছে মাঘ বিহুৰ ৰাতিৰ উৎসৱ। still some leftover english."
        )

        async def _regen():
            return improved_but_leaky

        self._run(sanitize_assamese_with_optional_regenerate(
            leaky, behaviour="regenerate", regenerate_callable=_regen,
        ))
        actions = [d.get("action") for d in self._captured]
        assert len(self._captured) == 1, (
            f"expected 1 run doc with leaky retry, got {len(self._captured)}: {actions}"
        )
        assert self._captured[0].get("regenerated") is True
        assert "regenerated" in self._captured[0]["action"]

    def test_strip_emits_active_run(self):
        from lang_sanitizer import sanitize_assamese_with_optional_regenerate
        text = "উৰুকা হৈছে মাঘ বিহুৰ পূৰ্বৰ ৰাতিৰ উৎসৱ। me uses ssible terms চমুকৈ ক'লে ই এটা উৎসৱ।"
        self._run(sanitize_assamese_with_optional_regenerate(text, behaviour="strip"))
        assert len(self._captured) == 1
        diag = self._captured[0]
        # Active cleanup → action is something other than noop and we
        # have an original_ratio (pre-cleanup) for the dashboard.
        assert diag["action"] != "noop"
        assert "original_ratio" in diag
        assert diag["behaviour"] == "strip"
