"""Tests for `resolve_rag_context`, the public RAG entry point.

The previous version targeted private chunking helpers
(`_split_into_sections`, `_sentence_split_with_overlap`) that were
removed when the RAG pipeline was retired. The current public surface
is `resolve_rag_context`, which selects between three branches:

  1. Document-attached → `_extract_relevant_sections` over the user
     document, returns `source="document"`, `quality="tier0"`.
  2. Subject + non-casual intent → `_fetch_internal_chapters`
     (Mongo). When chapters are found, returns `source="internal"`,
     `quality="tier1"`, `_has_internal_content=True`.
  3. Otherwise → empty context with `_general_knowledge_fallback=True`.

These tests pin all three branches without touching the network or DB.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

import rag  # noqa: E402
from rag import resolve_rag_context  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestDocumentBranch:
    def test_returns_tier0_document_source_when_text_provided(self):
        document = (
            "Photosynthesis is how plants make food.\n"
            "Chlorophyll absorbs light energy.\n"
            "The cell wall is rigid in plants."
        )
        ctx = _run(resolve_rag_context(query="explain photosynthesis", document_text=document))
        assert ctx["source"] == "document"
        assert ctx["quality"] == "tier0"
        assert ctx["chunks"] == []
        assert ctx["chapters"] == []
        assert "photosynthesis" in ctx["document_text"].lower()
        # document_full is the raw doc capped at 5000 chars.
        assert ctx["document_full"].startswith("Photosynthesis")

    def test_document_branch_caps_full_at_5000_chars(self):
        document = "x" * 10_000
        ctx = _run(resolve_rag_context(query="anything", document_text=document))
        assert len(ctx["document_full"]) == 5000

    def test_document_branch_propagates_intent(self):
        ctx = _run(resolve_rag_context(query="q", document_text="some content", intent="notes"))
        assert ctx["intent"] == "notes"

    def test_document_branch_defaults_intent_to_general(self):
        ctx = _run(resolve_rag_context(query="q", document_text="some content"))
        assert ctx["intent"] == "general"

    def test_blank_document_text_does_not_take_document_branch(self):
        # Whitespace-only document should fall through to the no-context branch.
        ctx = _run(resolve_rag_context(query="q", document_text="   \n  "))
        assert ctx["source"] == "none"


class TestInternalBranch:
    def test_uses_prefetched_chapters_without_calling_db(self, monkeypatch):
        prefetched = [
            {"title": "Photosynthesis", "content": "Plants convert light to chemical energy.",
             "slug": "photosynthesis", "subject_id": "bio-101", "type": "chapter"},
        ]

        async def _should_not_run(*a, **kw):
            raise AssertionError("_fetch_internal_chapters must not be called when prefetched is provided")

        monkeypatch.setattr(rag, "_fetch_internal_chapters", _should_not_run)
        ctx = _run(resolve_rag_context(
            query="photosynthesis",
            subject_id="bio-101",
            intent="notes",
            prefetched_chapters=prefetched,
        ))
        assert ctx["source"] == "internal"
        assert ctx["quality"] == "tier1"
        assert ctx["_has_internal_content"] is True
        assert ctx["chunks"] == prefetched
        assert ctx["chapters"] == prefetched
        assert ctx["intent"] == "notes"

    def test_falls_back_when_prefetched_chapters_empty(self, monkeypatch):
        async def _empty(*a, **kw):
            return []

        monkeypatch.setattr(rag, "_fetch_internal_chapters", _empty)
        ctx = _run(resolve_rag_context(
            query="photosynthesis",
            subject_id="bio-101",
            intent="notes",
            prefetched_chapters=[],  # explicit empty
        ))
        assert ctx["source"] == "none"
        assert ctx["_general_knowledge_fallback"] is True

    def test_casual_intent_skips_internal_branch(self, monkeypatch):
        async def _should_not_run(*a, **kw):
            raise AssertionError("internal chapter fetch must be skipped for casual intent")

        monkeypatch.setattr(rag, "_fetch_internal_chapters", _should_not_run)
        ctx = _run(resolve_rag_context(
            query="hello there",
            subject_id="bio-101",
            intent="casual",
        ))
        assert ctx["source"] == "none"
        assert ctx["intent"] == "casual"

    def test_general_intent_skips_internal_branch(self, monkeypatch):
        async def _should_not_run(*a, **kw):
            raise AssertionError("internal chapter fetch must be skipped for general intent")

        monkeypatch.setattr(rag, "_fetch_internal_chapters", _should_not_run)
        ctx = _run(resolve_rag_context(
            query="what is life",
            subject_id="bio-101",
            intent="general",
        ))
        assert ctx["source"] == "none"

    def test_no_subject_skips_internal_branch(self, monkeypatch):
        async def _should_not_run(*a, **kw):
            raise AssertionError("internal chapter fetch must be skipped without a subject")

        monkeypatch.setattr(rag, "_fetch_internal_chapters", _should_not_run)
        ctx = _run(resolve_rag_context(query="explain cells", intent="notes"))
        assert ctx["source"] == "none"
        assert ctx["_general_knowledge_fallback"] is True


class TestNoContextBranch:
    def test_returns_general_knowledge_fallback_marker(self):
        ctx = _run(resolve_rag_context(query="anything"))
        assert ctx["source"] == "none"
        assert ctx["quality"] == "none"
        assert ctx["chunks"] == []
        assert ctx["chapters"] == []
        assert ctx["_general_knowledge_fallback"] is True

    def test_default_intent_is_general_when_omitted(self):
        ctx = _run(resolve_rag_context(query="anything"))
        assert ctx["intent"] == "general"
