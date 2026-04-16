"""Tests for the document-extraction "chunking" surface in rag.py.

================================================================
MIGRATION NOTE — read before changing this file
================================================================
The previous version of this module exercised three private helpers
inside rag.py:

  - _split_into_sections           (heading-based section boundaries)
  - _merge_short_sections          (short-section coalescing)
  - _sentence_split_with_overlap   (sentence-window overlap chunking)

Those helpers — and the entire chunking / vector-RAG pipeline they
fed — were intentionally removed. See `rag.py` line 1:

    \"\"\"Syrabit.ai — LLM knowledge-based responses (web search and RAG removed).\"\"\"

The public coroutines that used to materialise chunks
(`auto_chunk_content`, `rechunk_chapter`, `backfill_chunk_embeddings`,
`vector_rag_search`, `rag_search`, `_embed_and_store_chapter`,
`_embed_and_store_page`, `_embed_cms_document`) are now no-op stubs
that return empty / "skipped" sentinels. There is no production code
path today that produces heading-bounded sections, overlapping
sentence windows, or merged short sections, so there is nothing
behind a public entry point to assert those guarantees against.

This module therefore does two things:

  1. Pins the only chunking-shaped behaviour that DOES still ship:
     `_extract_relevant_sections` (keyword-scored line selection used
     inside `resolve_rag_context`'s document branch).

  2. Pins the removed-by-design contract — the stub coroutines must
     keep returning empty/skipped — so that if anyone ever re-enables
     a chunker without rewriting these tests, CI will flag it loudly.

Companion branch coverage for `resolve_rag_context` lives in
`tests/test_rag_pipeline.py`. If the heading-split / overlap / merge
behaviours are ever brought back, replace the contract block below
with real assertions against whatever public adapter materialises
chunks.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

import rag  # noqa: E402
from rag import _extract_relevant_sections  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 1. Live chunking-shaped surface: keyword line selection.
# ---------------------------------------------------------------------------

class TestExtractRelevantSections:
    def test_returns_lines_matching_query_keywords(self):
        document = (
            "Photosynthesis is the process plants use to make food.\n"
            "The mitochondrion is the powerhouse of the cell.\n"
            "Chlorophyll captures light energy in photosynthesis.\n"
            "Ribosomes synthesize proteins."
        )
        out = _extract_relevant_sections(document, "explain photosynthesis")
        assert "photosynthesis" in out.lower()
        assert "chlorophyll" in out.lower()

    def test_includes_neighbor_lines_for_context(self):
        # The scorer pulls a small window (idx-1 .. idx+2) around each match
        # so adjacent context survives even if it has no keyword overlap.
        document = (
            "Intro line with no keyword.\n"
            "Photosynthesis converts CO2 and water into glucose.\n"
            "This happens inside the chloroplast.\n"
            "Final unrelated line about geography."
        )
        out = _extract_relevant_sections(document, "photosynthesis")
        assert "Intro line" in out
        assert "Photosynthesis converts" in out
        assert "chloroplast" in out

    def test_respects_char_limit(self):
        document = "photosynthesis " * 1000
        out = _extract_relevant_sections(document, "photosynthesis", char_limit=200)
        assert len(out) <= 200

    def test_falls_back_to_document_prefix_when_no_keyword_match(self):
        document = "Alpha beta gamma delta epsilon zeta eta theta."
        out = _extract_relevant_sections(document, "nothing matches here", char_limit=20)
        assert out == document[:20]

    def test_handles_empty_query_gracefully(self):
        document = "Some content here about anything."
        out = _extract_relevant_sections(document, "", char_limit=100)
        assert out.startswith("Some content")

    def test_handles_empty_document(self):
        assert _extract_relevant_sections("", "photosynthesis") == ""

    def test_strips_blank_lines_in_output(self):
        document = (
            "Photosynthesis is key.\n"
            "\n"
            "   \n"
            "Chloroplasts contain chlorophyll."
        )
        out = _extract_relevant_sections(document, "photosynthesis chlorophyll")
        assert "\n\n" not in out

    def test_default_char_limit_is_3000(self):
        document = "photosynthesis " * 1000
        out = _extract_relevant_sections(document, "photosynthesis")
        assert len(out) <= 3000


# ---------------------------------------------------------------------------
# 2. Removed-by-design contract: chunking/RAG entry points must stay stubs.
#
# These assertions exist so that if anyone re-enables a real chunker without
# also rewriting the heading-split / overlap / short-section tests that USED
# to live in this file, CI will fail and force the author to either:
#   (a) bring those tests back wired against the new implementation, or
#   (b) update this contract intentionally.
# ---------------------------------------------------------------------------

class TestChunkingPipelineRemovedContract:
    def test_module_docstring_documents_removal(self):
        # Single source of truth — if this changes, the contract below
        # almost certainly needs to change too.
        assert "RAG removed" in (rag.__doc__ or "")

    def test_auto_chunk_content_returns_empty(self):
        assert _run(rag.auto_chunk_content("anything")) == []

    def test_rechunk_chapter_returns_skipped(self):
        result = _run(rag.rechunk_chapter("chapter-id"))
        assert result == {"status": "skipped", "reason": "RAG removed"}

    def test_backfill_chunk_embeddings_returns_skipped(self):
        result = _run(rag.backfill_chunk_embeddings())
        assert result == {"status": "skipped", "reason": "RAG removed"}

    def test_vector_rag_search_returns_empty(self):
        assert _run(rag.vector_rag_search("query")) == []

    def test_rag_search_returns_empty_envelope(self):
        result = _run(rag.rag_search("query"))
        assert result["chunks"] == []
        assert result["chapters"] == []
        assert result["source"] == "none"
        assert result["quality"] == "none"
