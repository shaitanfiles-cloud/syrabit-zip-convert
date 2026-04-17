"""Task #428 — per-run audit log endpoint + snippet/PII helpers."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


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


def _find_cursor_mock(rows):
    """Mock motor's `coll.find(...).sort(...).limit(...).to_list(N)` chain.
    All chain steps return the same cursor; only `to_list` is awaitable."""
    cursor = MagicMock()
    cursor.find = MagicMock(return_value=cursor)
    cursor.sort = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=rows)
    return cursor


def _patch_db_with_runs_rows(rows, *, capture=None):
    coll = _find_cursor_mock(rows)
    if capture is not None:
        # `find(query, projection)` is the first call; record `query`
        # so tests can assert filter wiring.
        original_find = coll.find
        def _capture_find(query=None, projection=None, *args, **kwargs):
            capture["query"] = query
            return original_find(query, projection, *args, **kwargs)
        coll.find = MagicMock(side_effect=_capture_find)
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=coll)
    return patch("deps.db", db, create=True)


class TestRunsEndpoint:
    def test_returns_rows_newest_first(self, app_client):
        ts = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
        rows = [
            {
                "ts": ts, "action": "stripped", "behaviour": "translate",
                "ratio": 0.12, "post_ratio": 0.01, "threshold": 0.05,
                "translated": False, "regenerated": False, "has_assamese": True,
                "raw_snippet": "উৰুকা me uses",
                "cleaned_snippet": "উৰুকা",
            },
        ]
        with _patch_db_with_runs_rows(rows):
            r = app_client.get("/admin/assamese-purity/runs")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["limit"] == 50
        assert len(body["entries"]) == 1
        e = body["entries"][0]
        # ts should have been ISO-formatted by the route.
        assert isinstance(e["ts"], str) and "2026-04-17" in e["ts"]
        assert e["action"] == "stripped"
        assert e["raw_snippet"] == "উৰুকা me uses"
        assert e["cleaned_snippet"] == "উৰুকা"

    def test_action_filter_passed_to_mongo(self, app_client):
        capture = {}
        with _patch_db_with_runs_rows([], capture=capture):
            r = app_client.get("/admin/assamese-purity/runs?action=stripped")
        assert r.status_code == 200
        assert capture["query"] == {"action": "stripped"}
        assert r.json()["filters"] == {"action": "stripped"}

    def test_behaviour_filter_passed_to_mongo(self, app_client):
        capture = {}
        with _patch_db_with_runs_rows([], capture=capture):
            r = app_client.get("/admin/assamese-purity/runs?behaviour=translate")
        assert r.status_code == 200
        assert capture["query"] == {"behaviour": "translate"}

    def test_limit_clamped(self, app_client):
        capture = {}
        with _patch_db_with_runs_rows([], capture=capture):
            r = app_client.get("/admin/assamese-purity/runs?limit=99999")
        assert r.status_code == 200
        assert r.json()["limit"] == 200  # clamped upper bound
        with _patch_db_with_runs_rows([], capture=capture):
            r = app_client.get("/admin/assamese-purity/runs?limit=0")
        assert r.json()["limit"] == 1  # clamped lower bound

    def test_suspicious_tokens_round_trip(self, app_client):
        """Task #440 — wire the recorder + the GET endpoint together so
        a future projection tweak that drops `suspicious_tokens` (or a
        recorder change that stops persisting them) gets caught by a
        single test instead of slipping past the unit-level coverage."""
        import asyncio
        from routes.cms_sarvam_health import _record_assamese_run

        # Step 1: drive the real recorder to produce the doc that
        # would be inserted into mongo. This proves the persistence
        # path emits `suspicious_tokens` for active runs.
        captured = {}

        async def _fake_insert(doc):
            captured["doc"] = doc

        async def _drive():
            with patch("routes.cms_sarvam_health._insert_assamese_run", _fake_insert):
                _record_assamese_run({
                    "action": "stripped",
                    "behaviour": "strip",
                    "ratio": 0.0,
                    "original_ratio": 0.2,
                    "threshold": 0.05,
                    "translated": False,
                    "regenerated": False,
                    "has_assamese": True,
                    "raw_text": "উৰুকা me uses ssible terms",
                    "cleaned_text": "উৰুকা",
                    # Duplicate + non-string + PII to also confirm the
                    # scrub/dedupe survives the round trip.
                    "suspicious_tokens": [
                        "me uses",
                        "me uses",
                        "ssible terms",
                        None,
                        "ping user@example.com pls",
                    ],
                })
                await asyncio.sleep(0)

        asyncio.run(_drive())
        persisted_doc = captured["doc"]
        # Sanity: recorder did persist the field.
        assert "suspicious_tokens" in persisted_doc
        persisted_tokens = persisted_doc["suspicious_tokens"]
        assert "me uses" in persisted_tokens
        assert persisted_tokens.count("me uses") == 1  # deduped
        assert "ssible terms" in persisted_tokens
        assert any("[email]" in t for t in persisted_tokens)
        assert all("user@example.com" not in t for t in persisted_tokens)

        # Step 2: feed that exact doc back through the GET endpoint,
        # but with a *projection-aware* cursor mock — so if a future
        # tweak switches the route to an allowlist projection that
        # omits `suspicious_tokens`, this test will fail the way it's
        # supposed to. The default helper's cursor ignores projection
        # semantics, which would mask exactly the regression we want
        # to catch here.
        def _apply_projection(doc, projection):
            if not projection:
                return dict(doc)
            # Detect inclusion vs exclusion the same way mongo does:
            # 1-values mean inclusion (allowlist), 0-values mean
            # exclusion (denylist). `_id` is special and may appear
            # on either side.
            include_keys = {k for k, v in projection.items() if v == 1 and k != "_id"}
            exclude_keys = {k for k, v in projection.items() if v == 0 and k != "_id"}
            if include_keys:
                out = {k: doc[k] for k in include_keys if k in doc}
            else:
                out = {k: v for k, v in doc.items() if k not in exclude_keys}
            if projection.get("_id", 1) and "_id" in doc:
                out["_id"] = doc["_id"]
            return out

        captured_projection = {}

        def _make_cursor(rows):
            cur = MagicMock()
            cur.sort = MagicMock(return_value=cur)
            cur.limit = MagicMock(return_value=cur)
            cur.to_list = AsyncMock(return_value=rows)
            return cur

        coll = MagicMock()

        def _find(query=None, projection=None, *a, **kw):
            captured_projection["projection"] = projection
            projected = [_apply_projection(persisted_doc, projection)]
            return _make_cursor(projected)

        coll.find = MagicMock(side_effect=_find)
        db = MagicMock()
        db.__getitem__ = MagicMock(return_value=coll)

        with patch("deps.db", db, create=True):
            r = app_client.get("/admin/assamese-purity/runs")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert len(body["entries"]) == 1
        entry = body["entries"][0]
        # The actual round-trip assertion: the route's projection must
        # let `suspicious_tokens` through with its persisted contents.
        assert "suspicious_tokens" in entry, (
            f"runs endpoint stripped suspicious_tokens; "
            f"projection was {captured_projection.get('projection')!r}"
        )
        assert entry["suspicious_tokens"] == persisted_tokens

    def test_db_failure_returns_ok_false(self, app_client):
        coll = _find_cursor_mock([])
        coll.to_list = AsyncMock(side_effect=RuntimeError("mongo down"))
        db = MagicMock()
        db.__getitem__ = MagicMock(return_value=coll)
        with patch("deps.db", db, create=True):
            r = app_client.get("/admin/assamese-purity/runs")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["entries"] == []
        assert "mongo down" in body["error"]


class TestSnippetAndPiiScrub:
    def test_scrub_email(self):
        from routes.cms_sarvam_health import _scrub_pii
        assert _scrub_pii("contact me at jane@example.com please") == \
            "contact me at [email] please"

    def test_scrub_phone(self):
        from routes.cms_sarvam_health import _scrub_pii
        out = _scrub_pii("call +91 98765 43210 today")
        assert "[phone]" in out
        assert "98765" not in out

    def test_scrub_long_number(self):
        from routes.cms_sarvam_health import _scrub_pii
        out = _scrub_pii("OTP is 123456 for login")
        assert "123456" not in out
        assert "[num]" in out

    def test_short_number_kept(self):
        from routes.cms_sarvam_health import _scrub_pii
        # 4-digit numbers (years, scores) are preserved.
        assert _scrub_pii("year 2026 result") == "year 2026 result"

    def test_snippet_truncates(self):
        from routes.cms_sarvam_health import _snippet, _ASM_SNIPPET_MAX_CHARS
        long_text = "অ" * (_ASM_SNIPPET_MAX_CHARS + 200)
        out = _snippet(long_text)
        assert len(out) == _ASM_SNIPPET_MAX_CHARS
        assert out.endswith("…")

    def test_snippet_handles_empty(self):
        from routes.cms_sarvam_health import _snippet
        assert _snippet("") == ""
        assert _snippet(None) == ""


class TestRecorderPersistsSnippets:
    def test_record_includes_snippets_for_active_runs(self):
        """The recorder should persist raw/cleaned snippets when action != noop."""
        import asyncio
        from routes.cms_sarvam_health import _record_assamese_run

        captured = {}

        async def _fake_insert(doc):
            captured["doc"] = doc

        async def _run():
            with patch("routes.cms_sarvam_health._insert_assamese_run", _fake_insert):
                _record_assamese_run({
                    "action": "stripped",
                    "behaviour": "translate",
                    "ratio": 0.0,
                    "original_ratio": 0.2,
                    "threshold": 0.05,
                    "translated": False,
                    "regenerated": False,
                    "has_assamese": True,
                    "raw_text": "উৰুকা me uses ssible terms",
                    "cleaned_text": "উৰুকা",
                })
                # let the scheduled task run
                await asyncio.sleep(0)

        asyncio.run(_run())
        doc = captured["doc"]
        assert doc["action"] == "stripped"
        assert doc["ratio"] == 0.2  # uses original_ratio
        assert doc["raw_snippet"] == "উৰুকা me uses ssible terms"
        assert doc["cleaned_snippet"] == "উৰুকা"

    def test_record_omits_snippets_for_noop(self):
        import asyncio
        from routes.cms_sarvam_health import _record_assamese_run

        captured = {}

        async def _fake_insert(doc):
            captured["doc"] = doc

        async def _run():
            with patch("routes.cms_sarvam_health._insert_assamese_run", _fake_insert):
                _record_assamese_run({
                    "action": "noop",
                    "behaviour": "translate",
                    "ratio": 0.01,
                    "threshold": 0.05,
                    "raw_text": "hello",
                    "cleaned_text": "hello",
                })
                await asyncio.sleep(0)

        asyncio.run(_run())
        doc = captured["doc"]
        assert doc["action"] == "noop"
        assert "raw_snippet" not in doc
        assert "cleaned_snippet" not in doc

    def test_record_scrubs_pii_in_snippets(self):
        import asyncio
        from routes.cms_sarvam_health import _record_assamese_run

        captured = {}

        async def _fake_insert(doc):
            captured["doc"] = doc

        async def _run():
            with patch("routes.cms_sarvam_health._insert_assamese_run", _fake_insert):
                _record_assamese_run({
                    "action": "stripped",
                    "behaviour": "strip",
                    "ratio": 0.3,
                    "original_ratio": 0.3,
                    "threshold": 0.05,
                    "raw_text": "অসমীয়া email me at user@example.com or +91 98765 43210",
                    "cleaned_text": "অসমীয়া",
                })
                await asyncio.sleep(0)

        asyncio.run(_run())
        snip = captured["doc"]["raw_snippet"]
        assert "[email]" in snip
        assert "user@example.com" not in snip
        assert "[phone]" in snip
        assert "98765" not in snip


class TestRecorderPersistsSuspiciousTokens:
    """Task #437 — the sanitiser already exposes suspicious_tokens (the
    exact Latin runs that triggered cleanup). The recorder must persist
    them so the admin UI can highlight each token inline in the original
    snippet."""

    def _capture(self, diag):
        import asyncio
        from routes.cms_sarvam_health import _record_assamese_run
        captured = {}

        async def _fake_insert(doc):
            captured["doc"] = doc

        async def _run():
            with patch("routes.cms_sarvam_health._insert_assamese_run", _fake_insert):
                _record_assamese_run(diag)
                await asyncio.sleep(0)

        asyncio.run(_run())
        return captured["doc"]

    def test_tokens_persisted_for_active_run(self):
        doc = self._capture({
            "action": "stripped", "behaviour": "strip",
            "ratio": 0.0, "original_ratio": 0.2, "threshold": 0.05,
            "raw_text": "উৰুকা me uses ssible terms", "cleaned_text": "উৰুকা",
            "suspicious_tokens": ["me uses", "ssible terms"],
        })
        assert doc["suspicious_tokens"] == ["me uses", "ssible terms"]

    def test_tokens_dropped_for_noop(self):
        """Noop runs don't get snippets either, so persisting tokens
        for them would just bloat the collection with no UI benefit."""
        doc = self._capture({
            "action": "noop", "behaviour": "strip",
            "ratio": 0.01, "threshold": 0.05,
            "suspicious_tokens": ["foo"],
        })
        assert "suspicious_tokens" not in doc

    def test_tokens_deduped_and_capped(self):
        """50-token cap protects the doc from a runaway diag; dedup
        keeps the highlighted UI clean when the same token shows up
        many times."""
        toks = ["dup"] * 5 + [f"t{i}" for i in range(60)]
        doc = self._capture({
            "action": "stripped", "behaviour": "strip",
            "ratio": 0.0, "original_ratio": 0.2, "threshold": 0.05,
            "raw_text": "x", "cleaned_text": "y",
            "suspicious_tokens": toks,
        })
        persisted = doc["suspicious_tokens"]
        assert len(persisted) == 50
        assert persisted[0] == "dup"
        assert persisted.count("dup") == 1
        # First-cap policy: order preserved → t0..t48 fill the rest.
        assert persisted[1] == "t0"
        assert persisted[-1] == "t48"

    def test_tokens_scrubbed_for_pii(self):
        """If a Latin run happens to contain an email/phone, scrubbing
        protects the audit log just like it does for the snippet."""
        doc = self._capture({
            "action": "stripped", "behaviour": "strip",
            "ratio": 0.0, "original_ratio": 0.2, "threshold": 0.05,
            "raw_text": "x", "cleaned_text": "y",
            "suspicious_tokens": ["email me at user@example.com pls", "regular run"],
        })
        toks = doc["suspicious_tokens"]
        assert "[email]" in toks[0]
        assert "user@example.com" not in toks[0]
        assert "regular run" in toks

    def test_non_string_tokens_filtered(self):
        doc = self._capture({
            "action": "stripped", "behaviour": "strip",
            "ratio": 0.0, "original_ratio": 0.2, "threshold": 0.05,
            "raw_text": "x", "cleaned_text": "y",
            "suspicious_tokens": ["ok", None, 42, "", "  ", "fine"],
        })
        assert doc["suspicious_tokens"] == ["ok", "fine"]


class TestRecorderPersistsTrace:
    """Task #428 — conversation_id / user_id must reach the run doc so
    admins can answer "which user / which conversation triggered this
    leak?" from the audit panel without grepping Railway logs."""

    def _capture_doc(self, diag):
        import asyncio
        from routes.cms_sarvam_health import _record_assamese_run
        captured = {}

        async def _fake_insert(doc):
            captured["doc"] = doc

        async def _run():
            with patch("routes.cms_sarvam_health._insert_assamese_run", _fake_insert):
                _record_assamese_run(diag)
                await asyncio.sleep(0)

        asyncio.run(_run())
        return captured["doc"]

    def test_trace_ids_persisted(self):
        doc = self._capture_doc({
            "action": "stripped",
            "behaviour": "translate",
            "ratio": 0.0, "original_ratio": 0.2, "threshold": 0.05,
            "raw_text": "উৰুকা me uses",
            "cleaned_text": "উৰুকা",
            "trace": {"conversation_id": "conv-abc-123", "user_id": "user-xyz-9"},
        })
        assert doc["conversation_id"] == "conv-abc-123"
        assert doc["user_id"] == "user-xyz-9"

    def test_trace_absent_when_not_provided(self):
        doc = self._capture_doc({
            "action": "stripped",
            "behaviour": "translate",
            "ratio": 0.0, "original_ratio": 0.2, "threshold": 0.05,
            "raw_text": "উৰুকা me uses",
            "cleaned_text": "উৰুকা",
        })
        assert "conversation_id" not in doc
        assert "user_id" not in doc

    def test_trace_partial_user_only(self):
        doc = self._capture_doc({
            "action": "translated", "behaviour": "translate",
            "ratio": 0.0, "original_ratio": 0.2, "threshold": 0.05,
            "raw_text": "x", "cleaned_text": "y",
            "trace": {"user_id": "u-1"},
        })
        assert doc["user_id"] == "u-1"
        assert "conversation_id" not in doc

    def test_trace_truncated_to_80_chars(self):
        long_id = "c" * 200
        doc = self._capture_doc({
            "action": "stripped", "behaviour": "translate",
            "ratio": 0.0, "original_ratio": 0.2, "threshold": 0.05,
            "raw_text": "x", "cleaned_text": "y",
            "trace": {"conversation_id": long_id, "user_id": long_id},
        })
        assert len(doc["conversation_id"]) == 80
        assert len(doc["user_id"]) == 80

    def test_trace_persisted_for_noop_too(self):
        """Even on noop runs we want to know who triggered the measure
        so audits can correlate "no leak detected" runs with users."""
        doc = self._capture_doc({
            "action": "noop", "behaviour": "translate",
            "ratio": 0.01, "threshold": 0.05,
            "raw_text": "hi", "cleaned_text": "hi",
            "trace": {"conversation_id": "conv-1", "user_id": "u-1"},
        })
        assert doc["conversation_id"] == "conv-1"
        assert doc["user_id"] == "u-1"


class TestSanitizerThreadsTrace:
    """The sanitiser must propagate the caller-provided trace dict into
    the diag it emits to the recorder, on every behaviour path."""

    def _run_with_trace(self, raw, behaviour, monkeypatch):
        import asyncio
        from lang_sanitizer import sanitize_assamese_with_optional_regenerate
        captured = {}

        def _fake_record(diag):
            captured["diag"] = diag

        monkeypatch.setattr(
            "lang_sanitizer._emit_run", _fake_record,
        )
        monkeypatch.setenv("ASSAMESE_PURITY_BEHAVIOUR", behaviour)

        async def _go():
            return await sanitize_assamese_with_optional_regenerate(
                raw,
                trace={"conversation_id": "conv-T", "user_id": "u-T"},
            )

        asyncio.run(_go())
        return captured["diag"]

    def test_trace_in_off_path(self, monkeypatch):
        diag = self._run_with_trace("hello world", "off", monkeypatch)
        assert diag["trace"] == {"conversation_id": "conv-T", "user_id": "u-T"}

    def test_trace_in_noop_path(self, monkeypatch):
        # Pure ASCII → has_assamese=False → noop path.
        diag = self._run_with_trace("hello world", "strip", monkeypatch)
        assert diag.get("action") == "noop"
        assert diag["trace"]["user_id"] == "u-T"

    def test_trace_in_strip_path(self, monkeypatch):
        # Mostly Assamese with some English leak → strip fires.
        leaky = "অসমীয়া অসমীয়া অসমীয়া me uses ssible"
        diag = self._run_with_trace(leaky, "strip", monkeypatch)
        assert diag["trace"]["conversation_id"] == "conv-T"
