import pytest
from rag import _split_into_sections, _sentence_split_with_overlap


class TestSectionSplitting:
    def test_split_into_sections_with_headings(self):
        content = "## Introduction\n\nSome text here.\n\n### Details\n\nMore details."
        sections = _split_into_sections(content)
        assert len(sections) >= 1
        has_heading = any(s.get("heading") for s in sections)
        assert has_heading, "Sections should capture heading text"

    def test_split_into_sections_captures_heading_text(self):
        content = "## Financial Planning Basics\n\nFinancial planning is important.\n\n### Key Steps\n\nStep 1: Set goals."
        sections = _split_into_sections(content)
        headings = [s.get("heading", "") for s in sections if s.get("heading")]
        assert any("Financial Planning" in h for h in headings), f"Should capture heading text, got: {headings}"

    def test_split_into_sections_no_headings(self):
        content = "Just plain text without any markdown headings. Another sentence."
        sections = _split_into_sections(content)
        assert len(sections) >= 1

    def test_split_into_sections_empty_content(self):
        sections = _split_into_sections("")
        assert isinstance(sections, list)

    def test_split_preserves_all_content(self):
        content = "## Part A\n\nContent A here.\n\n## Part B\n\nContent B here."
        sections = _split_into_sections(content)
        all_text = " ".join(s.get("text", "") for s in sections)
        assert "Content A" in all_text
        assert "Content B" in all_text


class TestSentenceOverlap:
    def test_basic_chunking(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
        chunks = _sentence_split_with_overlap(text, target=50, max_len=80, overlap=1)
        assert len(chunks) >= 2

    def test_overlap_shares_content(self):
        text = "Alpha. Beta. Gamma. Delta. Epsilon. Zeta."
        chunks = _sentence_split_with_overlap(text, target=20, max_len=40, overlap=1)
        if len(chunks) >= 2:
            assert any(word in chunks[1] for word in chunks[0].split()), "Overlap should share some content"

    def test_single_sentence(self):
        text = "Solo sentence."
        chunks = _sentence_split_with_overlap(text, target=100, max_len=200, overlap=1)
        assert len(chunks) == 1

    def test_empty_input(self):
        chunks = _sentence_split_with_overlap("", target=100, max_len=200, overlap=1)
        assert chunks == [] or chunks == [""]

    def test_deterministic_output(self):
        text = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten."
        c1 = _sentence_split_with_overlap(text, target=30, max_len=50, overlap=1)
        c2 = _sentence_split_with_overlap(text, target=30, max_len=50, overlap=1)
        assert c1 == c2, "Same input should produce same output"

    def test_no_empty_chunks(self):
        text = "A. B. C. D. E. F. G. H. I. J."
        chunks = _sentence_split_with_overlap(text, target=10, max_len=20, overlap=1)
        for chunk in chunks:
            assert chunk.strip(), "No empty chunks should be produced"

    def test_large_overlap_doesnt_hang(self):
        text = "Short. Text. Here."
        chunks = _sentence_split_with_overlap(text, target=10, max_len=20, overlap=10)
        assert len(chunks) >= 1
