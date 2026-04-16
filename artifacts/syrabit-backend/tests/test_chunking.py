"""Tests for the public chunking adapter in rag.py.

Covers heading-based section boundaries, short-section coalescing, and
sentence-window overlap chunking via the public entry points
`split_into_sections`, `merge_short_sections`, and
`sentence_split_with_overlap`.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()

from rag import (  # noqa: E402
    split_into_sections,
    merge_short_sections,
    sentence_split_with_overlap,
)


class TestSplitIntoSections:
    def test_basic_heading_split(self):
        content = "### Intro\n\nSome text.\n\n### Details\n\nMore text."
        sections = split_into_sections(content)
        assert len(sections) == 2
        assert sections[0]["heading"] == "Intro"
        assert "Some text" in sections[0]["text"]
        assert sections[1]["heading"] == "Details"
        assert "More text" in sections[1]["text"]

    def test_captures_heading_text(self):
        content = "### Introduction to Photosynthesis\n\nContent here."
        sections = split_into_sections(content)
        assert sections[0]["heading"] == "Introduction to Photosynthesis"

    def test_multi_level_headings(self):
        content = (
            "## Chapter 1\n\nText.\n\n"
            "### Section A\n\nMore text.\n\n"
            "#### Subsection\n\nDeep text."
        )
        sections = split_into_sections(content)
        assert len(sections) == 3
        assert [s["heading"] for s in sections] == ["Chapter 1", "Section A", "Subsection"]

    def test_no_headings(self):
        content = "Just plain text with no headings at all."
        sections = split_into_sections(content)
        assert len(sections) == 1
        assert sections[0]["heading"] == ""
        assert "Just plain text" in sections[0]["text"]

    def test_empty_content(self):
        assert split_into_sections("") == []
        assert split_into_sections("   ") == []

    def test_leading_text_before_first_heading(self):
        content = "Preamble text.\n\n### First Section\n\nSection content."
        sections = split_into_sections(content)
        assert len(sections) == 2
        assert sections[0]["heading"] == ""
        assert "Preamble" in sections[0]["text"]
        assert sections[1]["heading"] == "First Section"

    def test_preserves_all_content(self):
        content = "## Part A\n\nContent A here.\n\n## Part B\n\nContent B here."
        sections = split_into_sections(content)
        all_text = " ".join(s["text"] for s in sections)
        assert "Content A" in all_text
        assert "Content B" in all_text


class TestMergeShortSections:
    def test_merges_short_sections(self):
        sections = [
            {"heading": "A", "text": "Short."},
            {"heading": "B", "text": "Also short."},
        ]
        merged = merge_short_sections(sections, target=600)
        assert len(merged) == 1
        # Heading reflects the merge.
        assert "A" in merged[0]["heading"] and "B" in merged[0]["heading"]
        # Both bodies preserved.
        assert "Short." in merged[0]["text"]
        assert "Also short." in merged[0]["text"]

    def test_keeps_long_sections_separate(self):
        sections = [
            {"heading": "A", "text": "x" * 800},
            {"heading": "B", "text": "y" * 800},
        ]
        merged = merge_short_sections(sections, target=600)
        assert len(merged) == 2
        assert merged[0]["heading"] == "A"
        assert merged[1]["heading"] == "B"

    def test_empty_input(self):
        assert merge_short_sections([]) == []

    def test_single_section(self):
        sections = [{"heading": "A", "text": "Content."}]
        merged = merge_short_sections(sections)
        assert len(merged) == 1
        assert merged[0]["heading"] == "A"

    def test_short_then_long_keeps_long_separate(self):
        # Short section grows by absorbing the next, but once it's "full"
        # subsequent long sections stay independent.
        sections = [
            {"heading": "A", "text": "Tiny."},
            {"heading": "B", "text": "z" * 800},
            {"heading": "C", "text": "w" * 800},
        ]
        merged = merge_short_sections(sections, target=600)
        # A merges into something with B; C stays separate.
        assert len(merged) == 2
        assert merged[-1]["heading"] == "C"


class TestSentenceSplitWithOverlap:
    def test_basic_split_produces_multiple_chunks(self):
        text = (
            "First sentence. Second sentence. Third sentence. "
            "Fourth sentence. Fifth sentence."
        )
        chunks = sentence_split_with_overlap(text, target=50, max_len=100, overlap=1)
        assert len(chunks) >= 2

    def test_overlap_produces_shared_sentences(self):
        text = "Alpha one. Beta two. Gamma three. Delta four. Epsilon five. Zeta six."
        chunks = sentence_split_with_overlap(text, target=20, max_len=40, overlap=1)
        assert len(chunks) >= 2
        for i in range(len(chunks) - 1):
            words_a = set(chunks[i].split())
            words_b = set(chunks[i + 1].split())
            assert words_a & words_b, f"No overlap between chunk {i} and {i+1}"

    def test_single_sentence_returns_single_chunk(self):
        text = "Just one sentence."
        chunks = sentence_split_with_overlap(text, target=100)
        assert chunks == [text]

    def test_empty_text(self):
        assert sentence_split_with_overlap("") == []
        assert sentence_split_with_overlap("   ") == []

    def test_pathological_overlap_does_not_hang(self):
        # overlap >= number of sentences in a chunk → loop must still
        # advance by 1 per iteration.
        text = "A one. B two. C three. D four. E five."
        chunks = sentence_split_with_overlap(text, target=5, max_len=10, overlap=10)
        assert len(chunks) < 50  # finite

    def test_respects_max_len(self):
        text = "Short sentence. " * 20
        chunks = sentence_split_with_overlap(text.strip(), target=30, max_len=60, overlap=1)
        for c in chunks:
            # Each chunk grows greedily up to max_len; allow tolerance for
            # the trailing sentence boundary that pushes one over.
            assert len(c) <= 80

    def test_deterministic(self):
        text = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten."
        a = sentence_split_with_overlap(text, target=30, max_len=50, overlap=1)
        b = sentence_split_with_overlap(text, target=30, max_len=50, overlap=1)
        assert a == b

    def test_no_empty_chunks(self):
        text = "A one. B two. C three. D four. E five. F six. G seven."
        chunks = sentence_split_with_overlap(text, target=10, max_len=20, overlap=1)
        for chunk in chunks:
            assert chunk.strip()
