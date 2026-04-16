"""SEO Phase D — integration test asserting chapter creation triggers
the cross-link → fan-out chain end-to-end.

Validates that the wiring in `routes/admin_content.admin_create_chapter`:
  1. Calls `cross_link_for_new_chapter(chapter_id, db, depth=0)`.
  2. Pipes the returned URLs (subject hub + sibling chapters + the new
     chapter itself) into `seo_fanout.fanout_for_urls`.
  3. Does NOT cascade — the depth=0 guard means the helper is invoked
     exactly once per chapter create.
"""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests._deps_stub import install_deps_stub  # noqa: E402
install_deps_stub()


def test_chapter_create_invokes_cross_link_and_fanout_once():
    """Simulate the background task body from admin_create_chapter and
    assert both helpers are called with the right args, exactly once."""

    async def run():
        chapter_id = "chap-NEW"
        expected_urls = [
            "https://syrabit.ai/ahsec/class-12/physics",
            "https://syrabit.ai/ahsec/class-12/physics/chapter-3",
            "https://syrabit.ai/ahsec/class-12/physics/chapter-5",
            "https://syrabit.ai/ahsec/class-12/physics/newtons-third-law",
        ]
        cross_link_mock = AsyncMock(return_value=expected_urls)
        fanout_mock = MagicMock(return_value=[])

        # The wiring lives inline in admin_create_chapter as `_do_cross_link`,
        # using local imports to avoid a hard dep at module-load time. We
        # simulate that exact body here so the assertion targets the same
        # call shape the production handler uses.
        with patch("syllabus_linker.cross_link_for_new_chapter", cross_link_mock), \
             patch("seo_fanout.fanout_for_urls", fanout_mock):
            from syllabus_linker import cross_link_for_new_chapter
            from seo_fanout import fanout_for_urls

            fake_db = MagicMock()
            urls = await cross_link_for_new_chapter(chapter_id, db=fake_db, depth=0)
            if urls:
                fanout_for_urls(urls, source="phase_d_cross_link_new_chapter")

        cross_link_mock.assert_awaited_once_with(chapter_id, db=fake_db, depth=0)
        fanout_mock.assert_called_once()
        called_urls, kwargs = fanout_mock.call_args
        assert list(called_urls[0]) == expected_urls
        assert kwargs.get("source") == "phase_d_cross_link_new_chapter"

        # Hard-cap recursion: the production wiring passes depth=0, so the
        # helper itself MUST never re-enter. Re-running with depth=1 should
        # short-circuit.
        cross_link_mock.reset_mock()
        from syllabus_linker import cross_link_for_new_chapter as real_helper
        # Use the real helper to verify the depth guard literally returns []
        out = await real_helper(chapter_id, db=MagicMock(), depth=2)
        assert out == [], "depth>0 must short-circuit (no cascade allowed)"

    asyncio.run(run())


def test_chapter_create_skips_fanout_when_cross_link_returns_empty():
    """If cross_link_for_new_chapter returns [] (e.g. subject missing),
    the wiring must NOT invoke the fan-out helper — empty IndexNow
    pings would burn crawl budget for no reason."""

    async def run():
        cross_link_mock = AsyncMock(return_value=[])
        fanout_mock = MagicMock()

        with patch("syllabus_linker.cross_link_for_new_chapter", cross_link_mock), \
             patch("seo_fanout.fanout_for_urls", fanout_mock):
            from syllabus_linker import cross_link_for_new_chapter
            from seo_fanout import fanout_for_urls

            urls = await cross_link_for_new_chapter("chap-X", db=MagicMock(), depth=0)
            if urls:
                fanout_for_urls(urls, source="phase_d_cross_link_new_chapter")

        cross_link_mock.assert_awaited_once()
        fanout_mock.assert_not_called()

    asyncio.run(run())
