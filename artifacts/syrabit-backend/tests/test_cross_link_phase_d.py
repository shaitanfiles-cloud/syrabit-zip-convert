"""SEO Phase D — auto cross-link new chapter tests.

Covers:
  - Subject hub + ≥2 sibling chapters get an inline `<a>` to the new chapter.
  - All patched URLs (subject hub + siblings + new chapter) are returned for
    fan-out queueing.
  - Re-running the cross-link function is idempotent (stable HTML marker).
  - Recursion is hard-capped at depth=1 — calling with `depth>0` returns [].
  - Picker prefers prev/next chapter neighbours by `order_index`.
"""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests._deps_stub import install_deps_stub  # noqa: E402
install_deps_stub()


def _make_db(subject: dict, new_chapter: dict, siblings: list[dict]):
    """Build a MagicMock db with the four collections cross_link touches."""
    fake_db = MagicMock()
    chapters_by_id = {c["id"]: dict(c) for c in [new_chapter, *siblings]}

    async def _chapters_find_one(query):
        cid = query.get("id")
        return chapters_by_id.get(cid)

    async def _subjects_find_one(query):
        if query.get("id") == subject["id"]:
            return dict(subject)
        return None

    chapters_update_calls: list[tuple[dict, dict]] = []

    async def _chapters_update(q, payload):
        cid = q.get("id")
        if cid in chapters_by_id:
            for k, v in payload.get("$set", {}).items():
                chapters_by_id[cid][k] = v
        chapters_update_calls.append((q, payload))
        return MagicMock(matched_count=1)

    subjects_update_calls: list[tuple[dict, dict]] = []

    async def _subjects_update(q, payload):
        if q.get("id") == subject["id"]:
            for k, v in payload.get("$set", {}).items():
                subject[k] = v
        subjects_update_calls.append((q, payload))
        return MagicMock(matched_count=1)

    class _Cursor:
        def __init__(self, docs):
            self._docs = docs

        async def to_list(self, _n):
            # Return the *current* state of all chapters under this subject
            return [dict(c) for c in chapters_by_id.values()
                    if c.get("subject_id") == subject["id"]]

    def _chapters_find(query):
        return _Cursor(list(chapters_by_id.values()))

    fake_db.chapters.find_one = AsyncMock(side_effect=_chapters_find_one)
    fake_db.chapters.find = MagicMock(side_effect=_chapters_find)
    fake_db.chapters.update_one = AsyncMock(side_effect=_chapters_update)
    fake_db.subjects.find_one = AsyncMock(side_effect=_subjects_find_one)
    fake_db.subjects.update_one = AsyncMock(side_effect=_subjects_update)

    return fake_db, chapters_by_id, subjects_update_calls, chapters_update_calls


def _seed():
    subject = {
        "id": "subj-phys",
        "board_slug": "ahsec", "class_slug": "class-12",
        "slug": "physics",
        "description": "Physics — AHSEC Class 12 study material.",
    }
    siblings = [
        {"id": f"chap-{i}", "subject_id": "subj-phys",
         "title": f"Chapter {i}", "slug": f"chapter-{i}",
         "order_index": i, "content": f"# Chapter {i}\nLorem.",
         "topics": ["mechanics" if i <= 3 else "optics"]}
        for i in range(1, 7)
    ]
    new_chapter = {
        "id": "chap-NEW", "subject_id": "subj-phys",
        "title": "Newton's Third Law", "slug": "newtons-third-law",
        "order_index": 4, "content": "# Newton's Third Law\nIntro.",
        "topics": ["mechanics", "newton"],
    }
    siblings.append(new_chapter)
    return subject, new_chapter, siblings


def test_cross_link_patches_subject_and_siblings_and_returns_urls():
    async def run():
        from syllabus_linker import cross_link_for_new_chapter

        subject, new_chapter, siblings = _seed()
        db, chapters_by_id, subj_calls, chap_calls = _make_db(subject, new_chapter, siblings)

        urls = await cross_link_for_new_chapter("chap-NEW", db=db, depth=0)

        # Subject hub patched: description now contains the new chapter URL
        assert "newtons-third-law" in subject["description"]
        assert "<!-- syrabit:related:chap-NEW -->" in subject["description"]

        # ≥2 siblings patched (limit is 3)
        patched_siblings = [c for cid, c in chapters_by_id.items()
                             if cid != "chap-NEW"
                             and "<!-- syrabit:related:chap-NEW -->" in (c.get("content") or "")]
        assert len(patched_siblings) >= 2
        assert len(patched_siblings) <= 3
        for c in patched_siblings:
            assert "newtons-third-law" in c["content"]

        # Returned URL list contains subject hub + each patched sibling + new chapter
        expected_min = 1 + len(patched_siblings) + 1  # subject + siblings + new
        assert len(urls) == expected_min
        assert "https://syrabit.ai/ahsec/class-12/physics" in urls
        assert "https://syrabit.ai/ahsec/class-12/physics/newtons-third-law" in urls
        for c in patched_siblings:
            assert f"https://syrabit.ai/ahsec/class-12/physics/{c['slug']}" in urls

    asyncio.run(run())


def test_cross_link_is_idempotent_no_cascade_on_rerun():
    async def run():
        from syllabus_linker import cross_link_for_new_chapter

        subject, new_chapter, siblings = _seed()
        db, chapters_by_id, subj_calls, chap_calls = _make_db(subject, new_chapter, siblings)

        urls_first = await cross_link_for_new_chapter("chap-NEW", db=db)
        n_subj_writes_first = len(subj_calls)
        n_chap_writes_first = len(chap_calls)

        # Second run must NOT re-patch anything (marker present everywhere)
        urls_second = await cross_link_for_new_chapter("chap-NEW", db=db)

        assert len(subj_calls) == n_subj_writes_first, "subject hub re-patched"
        assert len(chap_calls) == n_chap_writes_first, "siblings re-patched"

        # Returned list on the second pass must only contain the new-chapter
        # URL (we always include it so the chapter itself stays warm), but
        # NOT the subject hub / siblings — those would be a cascade signal.
        assert urls_second == ["https://syrabit.ai/ahsec/class-12/physics/newtons-third-law"]
        # Each marker appears exactly once per target
        assert subject["description"].count("<!-- syrabit:related:chap-NEW -->") == 1

    asyncio.run(run())


def test_cross_link_depth_guard_returns_empty():
    """Calling with depth>0 must return [] — Phase D contract."""
    async def run():
        from syllabus_linker import cross_link_for_new_chapter

        subject, new_chapter, siblings = _seed()
        db, *_ = _make_db(subject, new_chapter, siblings)
        out = await cross_link_for_new_chapter("chap-NEW", db=db, depth=1)
        assert out == []
        # And no DB writes performed under depth guard
        db.subjects.update_one.assert_not_called()
        db.chapters.update_one.assert_not_called()

    asyncio.run(run())


def test_cross_link_picker_prefers_prev_next_neighbours():
    """Sibling picker should always include the immediate prev + next chapter
    by order_index (the ones a student is most likely to reach next)."""
    from syllabus_linker import _pick_sibling_chapters

    siblings = [
        {"id": f"c-{i}", "title": f"Ch {i}", "order_index": i,
         "topics": ["unrelated-topic"], "slug": f"ch-{i}"}
        for i in range(1, 7)
    ]
    new = {"id": "c-4-NEW", "order_index": 4, "title": "New",
           "topics": ["totally-unique"], "slug": "new"}
    chosen = _pick_sibling_chapters(siblings, new, limit=3)
    chosen_ids = {c["id"] for c in chosen}
    # c-3 (prev) and c-5 (next) MUST be in the chosen set; the picker is
    # free to fill the third slot however it likes.
    assert "c-3" in chosen_ids
    assert "c-5" in chosen_ids
    assert len(chosen) == 3
