"""Tests for SEO Phase A — content-time fan-out (`seo_fanout.py`).

Verifies:
  * fanout_for_page enqueues IndexNow + cache-purge + bot-prewarm tasks
    when enabled, all three with the resolved URL.
  * killswitch (SEO_FANOUT_ENABLED=false) prevents any side effect.
  * Failures inside one signal don't suppress the others.
  * Ring buffer caps at 50 entries and is FIFO.
  * urls_to_purge_for_content_change returns deduped public URLs in the
    expected order (page → parent subject → library → sitemaps).
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _drain():
    async def _go():
        for _ in range(20):
            await asyncio.sleep(0)
    asyncio.run(_go())


def _sample_page():
    return {
        "id": "seo-abcd1234",
        "topic_id": "topic-1",
        "topic_slug": "kinematics",
        "subject_slug": "physics",
        "class_slug": "class-12",
        "board_slug": "ahsec",
        "page_type": "notes",
        "status": "published",
    }


def _patch_helpers(monkeypatch, *,
                   indexnow_result=True,
                   purge_result=True,
                   prewarm_result=True):
    """Patch all 3 downstream helpers and return a recorder dict."""
    calls = {"indexnow": [], "purge": [], "prewarm": []}

    from routes import bot_discovery as bd
    import cloudflare_client as cf

    async def _fake_schedule_indexnow(url, source="fanout"):
        calls["indexnow"].append({"url": url, "source": source})
        if isinstance(indexnow_result, BaseException):
            raise indexnow_result
        return indexnow_result

    async def _fake_purge(url, page_type="notes", parent_subject_url=None):
        calls["purge"].append({
            "url": url, "page_type": page_type,
            "parent_subject_url": parent_subject_url,
        })
        if isinstance(purge_result, BaseException):
            raise purge_result
        return purge_result

    async def _fake_prewarm(urls, rps=1.5):
        calls["prewarm"].append({"urls": list(urls), "rps": rps})
        if isinstance(prewarm_result, BaseException):
            raise prewarm_result
        return prewarm_result

    monkeypatch.setattr(bd, "_schedule_indexnow_for_url", _fake_schedule_indexnow)
    monkeypatch.setattr(cf, "purge_for_content_change", _fake_purge)
    monkeypatch.setattr(bd, "prewarm_bot_cache", _fake_prewarm)

    return calls


# ---------------------------------------------------------------------------
# urls_to_purge_for_content_change — pure-function coverage
# ---------------------------------------------------------------------------

def test_purge_url_set_includes_page_subject_library_and_sitemaps():
    from cloudflare_client import urls_to_purge_for_content_change
    out = urls_to_purge_for_content_change(
        "https://syrabit.ai/ahsec/class-12/physics/kinematics",
        page_type="notes",
        parent_subject_url="https://syrabit.ai/ahsec/class-12/physics",
    )
    assert "https://syrabit.ai/ahsec/class-12/physics/kinematics" in out
    assert "https://syrabit.ai/ahsec/class-12/physics" in out
    assert "https://syrabit.ai/library" in out
    assert "https://syrabit.ai/sitemap-chapters.xml" in out
    assert "https://syrabit.ai/sitemap-index.xml" in out
    # Page must come first so a partial purge still touches the new URL.
    assert out[0] == "https://syrabit.ai/ahsec/class-12/physics/kinematics"
    # Deduped — sitemaps appear once each.
    assert len(out) == len(set(out))


def test_purge_url_set_handles_relative_paths_and_no_parent():
    from cloudflare_client import urls_to_purge_for_content_change
    out = urls_to_purge_for_content_change("/ahsec/class-12/physics/kinematics")
    # Relative input gets prefixed with the public origin.
    assert all(u.startswith("https://") for u in out)
    # Parent missing → still returns page + library + sitemaps.
    assert any("/library" in u for u in out)


# ---------------------------------------------------------------------------
# is_enabled killswitch
# ---------------------------------------------------------------------------

def test_is_enabled_respects_explicit_env(monkeypatch):
    import seo_fanout
    monkeypatch.setenv("SEO_FANOUT_ENABLED", "true")
    assert seo_fanout.is_enabled() is True
    monkeypatch.setenv("SEO_FANOUT_ENABLED", "false")
    assert seo_fanout.is_enabled() is False
    monkeypatch.setenv("SEO_FANOUT_ENABLED", "0")
    assert seo_fanout.is_enabled() is False
    monkeypatch.setenv("SEO_FANOUT_ENABLED", "on")
    assert seo_fanout.is_enabled() is True


def test_is_enabled_defaults_off_under_pytest(monkeypatch):
    import seo_fanout
    monkeypatch.delenv("SEO_FANOUT_ENABLED", raising=False)
    # PYTEST_CURRENT_TEST is set by pytest itself during this test run, so
    # the default branch should evaluate to False.
    assert "PYTEST_CURRENT_TEST" in os.environ
    assert seo_fanout.is_enabled() is False


# ---------------------------------------------------------------------------
# fanout_for_page — full orchestration
# ---------------------------------------------------------------------------

def test_fanout_fires_all_three_signals_when_enabled(monkeypatch):
    async def run():
        monkeypatch.setenv("SEO_FANOUT_ENABLED", "true")
        calls = _patch_helpers(monkeypatch)

        import seo_fanout
        seo_fanout._FANOUT_RING.clear()

        task = seo_fanout.fanout_for_page(_sample_page(), source="unit-test")
        assert task is not None
        await task

        # IndexNow received the resolved public URL.
        assert len(calls["indexnow"]) == 1
        assert calls["indexnow"][0]["url"] == \
            "https://syrabit.ai/ahsec/class-12/physics/kinematics"
        assert calls["indexnow"][0]["source"] == "unit-test"

        # Cache purge received the page URL + parent subject URL.
        assert len(calls["purge"]) == 1
        assert calls["purge"][0]["url"] == \
            "https://syrabit.ai/ahsec/class-12/physics/kinematics"
        assert calls["purge"][0]["parent_subject_url"] == \
            "https://syrabit.ai/ahsec/class-12/physics"
        assert calls["purge"][0]["page_type"] == "notes"

        # Prewarm fired with both the page URL and the parent subject URL.
        assert len(calls["prewarm"]) == 1
        prewarm_urls = calls["prewarm"][0]["urls"]
        assert "https://syrabit.ai/ahsec/class-12/physics/kinematics" in prewarm_urls
        assert "https://syrabit.ai/ahsec/class-12/physics" in prewarm_urls

        # Ring buffer recorded a single ok event.
        events = seo_fanout.recent_fanout_events()
        assert len(events) == 1
        assert events[0]["indexnow"] == "ok"
        assert events[0]["cache_purge"] == "ok"
        assert events[0]["prewarm"] == "ok"
        assert events[0]["url"] == \
            "https://syrabit.ai/ahsec/class-12/physics/kinematics"

    asyncio.run(run())


def test_fanout_skips_everything_when_killswitch_off(monkeypatch):
    async def run():
        monkeypatch.setenv("SEO_FANOUT_ENABLED", "false")
        calls = _patch_helpers(monkeypatch)

        import seo_fanout
        seo_fanout._FANOUT_RING.clear()

        task = seo_fanout.fanout_for_page(_sample_page(), source="unit-test")
        assert task is None
        assert calls["indexnow"] == []
        assert calls["purge"] == []
        assert calls["prewarm"] == []
        # No event recorded either — the ring buffer is reserved for
        # actual attempts, not killswitch-skipped calls.
        assert seo_fanout.recent_fanout_events() == []

    asyncio.run(run())


def test_fanout_continues_when_one_signal_raises(monkeypatch):
    async def run():
        monkeypatch.setenv("SEO_FANOUT_ENABLED", "true")
        calls = _patch_helpers(
            monkeypatch,
            purge_result=RuntimeError("boom"),
        )
        import seo_fanout
        seo_fanout._FANOUT_RING.clear()

        task = seo_fanout.fanout_for_page(_sample_page(), source="unit-test")
        assert task is not None
        await task

        # All three were still attempted.
        assert len(calls["indexnow"]) == 1
        assert len(calls["purge"]) == 1
        assert len(calls["prewarm"]) == 1

        events = seo_fanout.recent_fanout_events()
        assert len(events) == 1
        assert events[0]["indexnow"] == "ok"
        assert events[0]["cache_purge"].startswith("error:")
        assert events[0]["prewarm"] == "ok"

    asyncio.run(run())


def test_fanout_ignores_page_with_unresolvable_url(monkeypatch):
    async def run():
        monkeypatch.setenv("SEO_FANOUT_ENABLED", "true")
        calls = _patch_helpers(monkeypatch)
        import seo_fanout
        seo_fanout._FANOUT_RING.clear()

        # Missing slugs → _page_doc_to_url returns None.
        bad = {"id": "x", "page_type": "notes"}
        task = seo_fanout.fanout_for_page(bad)
        assert task is None
        assert calls == {"indexnow": [], "purge": [], "prewarm": []}
        assert seo_fanout.recent_fanout_events() == []

    asyncio.run(run())


def test_schedule_indexnow_normalizes_relative_path_without_leading_slash():
    """`queue_raw_paths` concatenates BASE_URL + path verbatim, so a
    missing leading slash would produce e.g. `https://syrabit.aiahsec/...`.
    The helper must defensively prepend `/` for non-absolute inputs.
    """
    async def run():
        from routes import bot_discovery as bd
        captured = []

        async def _fake_queue_raw(paths):
            captured.extend(paths)

        async def _fake_queue(_urls):
            captured.append("ABS")

        async def _fake_flush(source=""):
            captured.append(f"flush:{source}")

        bd.indexnow_batcher = MagicMock()
        bd.indexnow_batcher.queue_raw_paths = AsyncMock(side_effect=_fake_queue_raw)
        bd.indexnow_batcher.queue = AsyncMock(side_effect=_fake_queue)
        bd.indexnow_batcher.flush = AsyncMock(side_effect=_fake_flush)

        ok = await bd._schedule_indexnow_for_url(
            "ahsec/class-12/physics", source="t1"
        )
        assert ok is True
        # First captured value is the normalized relative path.
        assert captured[0] == "/ahsec/class-12/physics"

        # Already-leading-slash paths pass through unchanged.
        captured.clear()
        await bd._schedule_indexnow_for_url("/seba/class-10/maths", source="t2")
        assert captured[0] == "/seba/class-10/maths"

        # Absolute URLs go through the abs queue branch instead.
        captured.clear()
        await bd._schedule_indexnow_for_url(
            "https://syrabit.ai/foo", source="t3"
        )
        assert captured[0] == "ABS"

    asyncio.run(run())


def test_recent_events_ring_buffer_caps_at_50(monkeypatch):
    async def run():
        monkeypatch.setenv("SEO_FANOUT_ENABLED", "true")
        _patch_helpers(monkeypatch)
        import seo_fanout
        seo_fanout._FANOUT_RING.clear()

        for i in range(60):
            page = _sample_page()
            page["topic_slug"] = f"k{i}"
            t = seo_fanout.fanout_for_page(page)
            if t is not None:
                await t

        events = seo_fanout.recent_fanout_events()
        assert len(events) == 50  # capped
        # FIFO eviction → newest entries retained.
        assert events[-1]["url"].endswith("/k59")
        assert events[0]["url"].endswith("/k10")

    asyncio.run(run())
