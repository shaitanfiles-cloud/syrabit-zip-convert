"""Task #562 — end-to-end smoke test for the
publish → sub-sitemap → IndexNow → push-log chain.

Task #560 wired three independent pieces together:

1. Sub-sitemap generators in ``seo_engine.py`` that surface freshly
   published ``seo_pages`` rows with today's ``<lastmod>``.
2. ``notify_indexnow_for_page`` / ``push_indexnow`` in
   ``routes/bot_discovery.py`` that fire IndexNow on every content
   change.
3. ``_log_indexnow_push`` that writes a row to ``indexnow_push_log``
   for every successful (or attempted) push so the admin Submit &
   Monitor panel can prove a fresh URL was actually submitted.

There are unit tests for each piece in isolation
(``test_indexnow_triggers``, ``test_indexnow_sitemap_diff``,
``test_seo_publish_pipeline_e2e`` …) but none of them check the
*chain*. A regression in any of the three steps — page never reaches
the sub-sitemap, sitemap row carries an old ``<lastmod>``, IndexNow
push silently fails to log — would ship without any failing test.

This test simulates the full chain with a fake Mongo + a stubbed
``httpx.AsyncClient`` so it can run in CI on every push (no network,
no real database) and surface a clear failure if any of the three
steps regresses. The same module also exposes a
``run_publish_indexnow_smoke()`` entry point so an admin / cron can
invoke it ad-hoc against the staging stack.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Iterable, List
from unittest.mock import AsyncMock, MagicMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fake motor cursor / collection plumbing.
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, docs: Iterable[dict]):
        self._docs = list(docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()

    def sort(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    def skip(self, *_a, **_kw):
        return self

    async def to_list(self, length=None):
        if length is None:
            return list(self._docs)
        return list(self._docs)[:length]


class _FakeCollection:
    def __init__(self, docs: Iterable[dict] | None = None):
        self._docs: List[dict] = list(docs or [])
        self.insert_one = AsyncMock(side_effect=self._insert_one)

    async def _insert_one(self, doc: dict):
        self._docs.append(dict(doc))
        return MagicMock(inserted_id=doc.get("id"))

    def find(self, *_a, **_kw):
        return _FakeCursor(self._docs)

    async def find_one(self, query: dict | None = None, _proj=None):
        if not query:
            return self._docs[0] if self._docs else None
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                return d
        return None

    async def count_documents(self, _q=None):
        return len(self._docs)

    def aggregate(self, *_a, **_kw):
        return _FakeCursor(self._docs)


def _build_fake_db(seo_pages_docs: list[dict]) -> Any:
    """Build a MagicMock motor db prepopulated with the taxonomy needed
    so ``_build_valid_slug_chains()`` keeps the test page in the sitemap
    and nothing else interferes."""
    db = MagicMock()
    db.seo_pages = _FakeCollection(seo_pages_docs)
    db.boards = _FakeCollection([{"id": "b1", "slug": "ahsec"}])
    db.classes = _FakeCollection([
        {"id": "c1", "board_id": "b1", "slug": "class-12"},
    ])
    db.streams = _FakeCollection([{"id": "st1", "class_id": "c1"}])
    db.subjects = _FakeCollection([{
        "id": "sub-1", "slug": "physics", "stream_id": "st1",
        "status": "published",
        "updated_at": "2026-04-10T00:00:00+00:00",
    }])
    db.chapters = _FakeCollection([])
    db.cms_documents = _FakeCollection([])
    db.indexnow_push_log = _FakeCollection([])
    db.indexnow_submitted_urls = _FakeCollection([])
    return db


# ---------------------------------------------------------------------------
# Step 1: sub-sitemap surfaces the freshly published page with today's lastmod.
# ---------------------------------------------------------------------------


async def _assert_url_in_sitemap_with_today(
    sitemap_endpoint, expected_url: str, today: str,
    *, max_polls: int = 5, poll_delay: float = 0.0,
) -> None:
    """Poll the sub-sitemap endpoint until ``expected_url`` shows up
    paired with today's ``<lastmod>``. Mirrors what an external crawler
    would do after a publish — bounded so a missing chain fails fast in
    CI rather than hanging the suite."""
    last_body = ""
    for _ in range(max_polls):
        resp = await sitemap_endpoint()
        body = resp.body.decode("utf-8") if hasattr(resp, "body") else str(resp)
        last_body = body
        if expected_url in body:
            # Find the surrounding <url>…</url> block and confirm today's lastmod.
            assert f"<lastmod>{today}</lastmod>" in body, (
                f"URL {expected_url!r} appeared in sitemap but no entry "
                f"carried today's lastmod ({today}). Body=\n{body}"
            )
            # Cross-check the URL and lastmod live in the same <url> block
            # — a sitemap with the right URL but stale lastmod elsewhere
            # is exactly the regression Task #562 guards against.
            blocks = body.split("<url>")
            matching = [b for b in blocks if expected_url in b]
            assert any(f"<lastmod>{today}</lastmod>" in b for b in matching), (
                f"URL {expected_url!r} present but its <url> block does "
                f"not carry today's lastmod ({today}). Body=\n{body}"
            )
            return
        if poll_delay:
            await asyncio.sleep(poll_delay)
    raise AssertionError(
        f"Polled sub-sitemap {max_polls}x; URL {expected_url!r} never "
        f"appeared. Last body=\n{last_body}"
    )


# ---------------------------------------------------------------------------
# Step 2: stub httpx so push_indexnow returns success without network I/O.
# ---------------------------------------------------------------------------


class _Stub200Response:
    status_code = 200
    content = b"ok"


class _StubAsyncClient:
    def __init__(self, *_a, **_kw):
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def post(self, url, json=None, **_kw):
        self.calls.append((url, json or {}))
        return _Stub200Response()


# ---------------------------------------------------------------------------
# The test itself.
# ---------------------------------------------------------------------------


def _seed_published_page(today: str) -> dict:
    return {
        "id": "page-e2e-1",
        "board_slug": "ahsec",
        "class_slug": "class-12",
        "subject_slug": "physics",
        "topic_slug": "newtons-laws",
        "page_type": "notes",
        "status": "published",
        "updated_at": f"{today}T00:00:00+00:00",
        "generated_at": f"{today}T00:00:00+00:00",
    }


def test_publish_to_sitemap_to_indexnow_to_push_log_e2e(monkeypatch):
    """End-to-end smoke: publishing a fresh seo_page surfaces in the
    matching sub-sitemap with today's ``<lastmod>`` AND triggers a
    ``indexnow_push_log`` row recording the URL."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    page = _seed_published_page(today)

    fake_db = _build_fake_db([page])

    # Wire the fake db into both sides of the chain.
    import seo_engine
    monkeypatch.setattr(seo_engine, "_db", fake_db, raising=False)

    import deps as deps_mod

    async def _avail():
        return True

    monkeypatch.setattr(deps_mod, "db", fake_db, raising=False)
    monkeypatch.setattr(deps_mod, "is_mongo_available", _avail, raising=False)

    import routes.bot_discovery as bd

    # Suppress the persist-health side effect — it would try to
    # schedule motor writes on a real loop.
    monkeypatch.setattr(bd, "_schedule_persist", lambda *_a, **_kw: None,
                        raising=False)
    monkeypatch.setattr(bd, "_schedule_health_log",
                        lambda *_a, **_kw: None, raising=False)

    # Stub the IndexNow HTTP client.
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _StubAsyncClient)

    expected_url = (
        f"{bd.BASE_URL}/{page['board_slug']}/{page['class_slug']}/"
        f"{page['subject_slug']}/{page['topic_slug']}"
    )

    async def _drive():
        # Step 1: poll the matching sub-sitemap (page_type=notes →
        # /api/seo/sitemap-notes.xml) until the URL appears with today's
        # <lastmod>. Bounded poll so a missing chain fails fast.
        await _assert_url_in_sitemap_with_today(
            seo_engine.get_sitemap_notes, expected_url, today,
        )

        # Step 2: simulate the auto-trigger fired on every publish.
        await bd.notify_indexnow_for_page(page)

        # _log_indexnow_push is fire-and-forget via asyncio.create_task;
        # let the loop drain so the write lands before we inspect the log.
        for _ in range(20):
            await asyncio.sleep(0)
            if fake_db.indexnow_push_log.insert_one.await_count >= 1:
                break

        # Step 3: assert a row was written to indexnow_push_log carrying
        # the URL we just published.
        assert fake_db.indexnow_push_log.insert_one.await_count >= 1, (
            "notify_indexnow_for_page did not result in a "
            "indexnow_push_log row — the publish→IndexNow chain is broken."
        )
        logged = fake_db.indexnow_push_log._docs
        assert any(expected_url in (row.get("urls_sample") or [])
                   for row in logged), (
            f"indexnow_push_log rows did not contain the published URL "
            f"{expected_url!r}. Rows={logged}"
        )
        # The row must also record url_count >= 1 and a pushed_at timestamp.
        row = next(
            r for r in logged
            if expected_url in (r.get("urls_sample") or [])
        )
        assert row.get("url_count", 0) >= 1
        assert isinstance(row.get("pushed_at"), datetime)

    _run(_drive())


# ---------------------------------------------------------------------------
# Failure-mode coverage: a sub-sitemap regression that drops the URL must
# fail this test loudly, not silently pass.
# ---------------------------------------------------------------------------


def test_smoke_fails_when_sitemap_regresses(monkeypatch):
    """If the sub-sitemap silently stops emitting freshly published rows,
    the polling helper must raise rather than swallow the regression."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async def _empty_sitemap():
        from fastapi.responses import Response
        return Response(
            content=(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                '</urlset>'
            ),
            media_type="application/xml",
        )

    async def _drive():
        try:
            await _assert_url_in_sitemap_with_today(
                _empty_sitemap,
                "https://syrabit.ai/ahsec/class-12/physics/newtons-laws",
                today,
                max_polls=2,
            )
        except AssertionError:
            return "ok"
        return "regression-undetected"

    assert _run(_drive()) == "ok"


def test_smoke_fails_when_lastmod_is_stale(monkeypatch):
    """If the URL is in the sitemap but its <lastmod> is from yesterday,
    the polling helper must raise — a stale lastmod is exactly the
    Google-side symptom Task #560 was meant to avoid."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    expected_url = "https://syrabit.ai/ahsec/class-12/physics/newtons-laws"

    async def _stale_sitemap():
        from fastapi.responses import Response
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'<url><loc>{expected_url}</loc>'
            '<lastmod>2025-01-01</lastmod></url>'
            '</urlset>'
        )
        return Response(content=body, media_type="application/xml")

    async def _drive():
        try:
            await _assert_url_in_sitemap_with_today(
                _stale_sitemap, expected_url, today, max_polls=2,
            )
        except AssertionError:
            return "ok"
        return "regression-undetected"

    assert _run(_drive()) == "ok"


# ---------------------------------------------------------------------------
# Admin / cron entry point.
#
# Exposes the same chain as a callable so an operator can drive it
# against a staging stack without going through pytest. It returns a
# structured summary instead of raising so it can be wired into a
# cron/alerting harness directly.
# ---------------------------------------------------------------------------


async def run_publish_indexnow_smoke() -> dict:
    """Run the publish → sub-sitemap → IndexNow → push-log chain against
    whatever ``seo_engine._db`` / ``deps.db`` are currently wired in.

    Returns a summary dict ``{"ok": bool, "url": str, "today": str,
    "in_sitemap": bool, "lastmod_fresh": bool, "push_log_written": bool,
    "error": Optional[str]}``. Designed for an admin route or daily
    cron — a False ``ok`` plus a populated ``error`` is the alerting
    signal."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summary = {
        "ok": False, "url": "", "today": today,
        "in_sitemap": False, "lastmod_fresh": False,
        "push_log_written": False, "error": None,
    }
    try:
        import seo_engine
        from routes import bot_discovery as bd
        from deps import db as real_db, is_mongo_available

        if not await is_mongo_available():
            summary["error"] = "mongo_unavailable"
            return summary

        page = await real_db.seo_pages.find_one(
            {"status": "published"}, {"_id": 0}
        )
        if not page:
            summary["error"] = "no_published_seo_page"
            return summary
        url = bd._page_doc_to_url(page)
        if not url:
            summary["error"] = "page_doc_to_url_failed"
            return summary
        summary["url"] = url

        before = await real_db.indexnow_push_log.count_documents({}) if hasattr(
            real_db, "indexnow_push_log"
        ) else 0

        sitemap_endpoint = {
            "notes": seo_engine.get_sitemap_notes,
            "mcqs": seo_engine.get_sitemap_mcqs,
            "important-questions": seo_engine.get_sitemap_pyqs,
            "examples": seo_engine.get_sitemap_examples,
            "definition": seo_engine.get_sitemap_definitions,
        }.get(page.get("page_type", "notes"), seo_engine.get_sitemap_notes)

        resp = await sitemap_endpoint()
        body = resp.body.decode("utf-8") if hasattr(resp, "body") else str(resp)
        if url in body:
            summary["in_sitemap"] = True
            blocks = body.split("<url>")
            matching = [b for b in blocks if url in b]
            summary["lastmod_fresh"] = any(
                f"<lastmod>{today}</lastmod>" in b for b in matching
            )

        await bd.notify_indexnow_for_page(page)
        for _ in range(50):
            await asyncio.sleep(0.05)
            after = await real_db.indexnow_push_log.count_documents({})
            if after > before:
                summary["push_log_written"] = True
                break

        summary["ok"] = (
            summary["in_sitemap"]
            and summary["lastmod_fresh"]
            and summary["push_log_written"]
        )
        return summary
    except Exception as exc:  # pragma: no cover — defensive
        summary["error"] = f"{type(exc).__name__}: {exc}"
        return summary
