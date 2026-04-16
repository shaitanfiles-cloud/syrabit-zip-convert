"""Tests for the document-extraction "chunking" surface in rag.py.

The previous version of this file targeted private helpers
(`_split_into_sections`, `_merge_short_sections`,
`_sentence_split_with_overlap`) that were removed when the heavy RAG /
chunking pipeline was retired (see `rag.py` module docstring: "web
search and RAG removed"). The only chunking-shaped behavior that
remains in production today is `_extract_relevant_sections`: given a
user document and a query, score every line by keyword overlap and
return a contiguous selection capped at `char_limit`.

These tests pin down that public surface so the document-attachment
flow stays correct.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

from rag import _extract_relevant_sections  # noqa: E402


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
        # The unrelated ribosome line should not be the focus.
        assert "ribosome" not in out.lower() or out.lower().index("photosynthesis") < out.lower().index("ribosome")

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
        # Both the matched line AND its neighbors should be present.
        assert "Intro line" in out
        assert "Photosynthesis converts" in out
        assert "chloroplast" in out

    def test_respects_char_limit(self):
        document = "photosynthesis " * 1000  # ~15k chars, all matching
        out = _extract_relevant_sections(document, "photosynthesis", char_limit=200)
        assert len(out) <= 200

    def test_falls_back_to_document_prefix_when_no_keyword_match(self):
        document = "Alpha beta gamma delta epsilon zeta eta theta."
        out = _extract_relevant_sections(document, "nothing matches here", char_limit=20)
        # No keyword overlap → return a prefix of the original document.
        assert out == document[:20]

    def test_handles_empty_query_gracefully(self):
        document = "Some content here about anything."
        out = _extract_relevant_sections(document, "", char_limit=100)
        # Empty query → no keywords → fall back to document prefix.
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
        # No blank-line runs in output.
        assert "\n\n" not in out

    def test_default_char_limit_is_3000(self):
        document = "photosynthesis " * 1000
        out = _extract_relevant_sections(document, "photosynthesis")
        assert len(out) <= 3000
