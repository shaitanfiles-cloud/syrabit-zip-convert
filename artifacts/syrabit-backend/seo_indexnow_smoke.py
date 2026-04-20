"""Production-importable entry point for the publish → sub-sitemap →
IndexNow → push-log smoke test.

The chain assertion logic originally lived alongside the pytest module
``tests/test_seo_publish_indexnow_e2e.py``. Importing that module at
runtime is unsafe because it calls ``install_deps_stub()`` at import
time which monkey-patches ``sys.modules["deps"]`` for testing. Hosting
``run_publish_indexnow_smoke()`` here keeps the function callable from
admin routes / cron loops without dragging in the test stub.

Task #563: surface this function behind ``POST /api/admin/seo/indexnow/smoke``
so the team can self-verify the publish → Google chain on demand.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone


async def run_publish_indexnow_smoke() -> dict:
    """Run the publish → sub-sitemap → IndexNow → push-log chain against
    whatever ``seo_engine._db`` / ``deps.db`` are currently wired in.

    Returns a summary dict ``{"ok": bool, "url": str, "today": str,
    "in_sitemap": bool, "lastmod_fresh": bool, "push_log_written": bool,
    "error": Optional[str]}``. Designed for an admin route or daily
    cron — a False ``ok`` plus a populated ``error`` is the alerting
    signal.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summary = {
        "ok": False,
        "url": "",
        "today": today,
        "in_sitemap": False,
        "lastmod_fresh": False,
        "push_log_written": False,
        "error": None,
    }
    try:
        import seo_engine
        from routes import bot_discovery as bd
        from deps import db as real_db, is_mongo_available

        if not await is_mongo_available():
            summary["error"] = "mongo_unavailable"
            return summary

        # Pick the most recently updated published page so the smoke
        # actually exercises a "fresh" publish — picking an arbitrary
        # row would produce false negatives whenever its <lastmod> is
        # older than today.
        page = None
        try:
            cursor = real_db.seo_pages.find(
                {"status": "published"}, {"_id": 0}
            ).sort("updated_at", -1).limit(1)
            rows = await cursor.to_list(1)
            if rows:
                page = rows[0]
        except Exception:
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
