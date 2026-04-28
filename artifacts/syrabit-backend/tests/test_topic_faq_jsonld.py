"""Unit tests for the MCQ markdown parser used by the FAQPage JSON-LD endpoint.

Covers the documented quality bar:
  * Substantive Q+A only (>= 30 chars of real answer content).
  * No placeholder / "see our site" answers.
  * Correctly identifies Q+A from the production MCQ markdown format
    (`**Q1.** … (a)/(b)/(c)/(d) … **Ans:** (c) — explanation`).
  * Tolerates format variations: missing em-dash, missing explanation,
    answer letter parenthesised differently, question stems without `?`.
  * Caps at the requested max and dedupes repeated questions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes.topic_faq_jsonld import parse_mcqs_from_markdown


# Mirrors the actual production format observed in db.seo_pages
# (page_type='mcqs') for "Unit 1: Essence of Democracy".
PROD_LIKE_MARKDOWN = """
## Unit 1: Essence of Democracy – NEP FYUGP Semester 2

Democracy is a system of government in which power is vested in the people…

## Recall & Recognition (Q1–Q5)
*These questions evaluate foundational knowledge of definitions, historical
facts, and core democratic principles…*

**Q1.** Which of the following best defines democracy?
(a) Rule by a single powerful leader
(b) Government by the rich and elite
(c) Rule by the people, for the people, and of the people
(d) Administration controlled by military forces
**Ans:** (c) — This definition, popularized by Abraham Lincoln in the
Gettysburg Address, encapsulates the core idea of democracy as a system
where power resides with the citizens.

*Exam tip: This is a standard 2-mark question often asked in NEP FYUGP
semester exams to test basic conceptual clarity.*

**Q2.** Who among the following is known as the "Father of Democracy"?
(a) Karl Marx
(b) Aristotle
(c) Cleisthenes
(d) Plato
**Ans:** (c) — Cleisthenes, an Athenian statesman, introduced political
reforms in 508 BCE that dismantled aristocratic clans and established a
system of citizen participation in governance.

**Q3.** Which of the following is NOT a feature of democracy?
(a) Free and fair elections
(b) Protection of minority rights
(c) Rule by hereditary monarchy
(d) Accountability of rulers
**Ans:** (c) — Hereditary monarchy contradicts the democratic principle
of elected leadership and citizen participation.
"""


def test_parses_production_format_three_questions():
    out = parse_mcqs_from_markdown(PROD_LIKE_MARKDOWN)
    assert len(out) == 3
    q1 = out[0]
    assert "best defines democracy" in q1["question"]
    # Final answer must lead with the correct option label + body, then
    # the substantive explanation. This is what AI engines extract.
    assert q1["answer"].startswith("Correct answer: (c) Rule by the people")
    assert "Abraham Lincoln" in q1["answer"]


def test_every_answer_meets_quality_bar():
    out = parse_mcqs_from_markdown(PROD_LIKE_MARKDOWN)
    for entry in out:
        # Google Rich Results requirement — substantive answer text.
        assert len(entry["answer"]) >= 30, entry
        assert "Refer to Syrabit" not in entry["answer"], (
            "placeholder answer would trigger Google demotion"
        )


def test_max_faqs_cap_enforced():
    md = "\n".join(
        f"**Q{i}.** Which of the following defines concept-{i}?\n"
        f"(a) wrong-1\n(b) wrong-2\n(c) right-{i} which is the correct definition\n(d) wrong-3\n"
        f"**Ans:** (c) — Concept {i} is defined precisely this way per the syllabus textbook."
        for i in range(1, 21)
    )
    out = parse_mcqs_from_markdown(md, max_faqs=5)
    assert len(out) == 5


def test_dedupes_identical_questions():
    md = (
        "**Q1.** Which of the following defines sovereignty?\n"
        "(a) wrong\n(b) wrong\n(c) the supreme authority within a territory\n(d) wrong\n"
        "**Ans:** (c) — Sovereignty is the supreme authority of a state to govern itself.\n\n"
        "**Q2.** Which of the following defines sovereignty?\n"
        "(a) wrong\n(b) wrong\n(c) absolute authority over a polity\n(d) wrong\n"
        "**Ans:** (c) — Sovereignty implies the highest authority over a defined territory."
    )
    out = parse_mcqs_from_markdown(md)
    # Identical question text = single FAQ entry, even with different
    # explanations. Dedup is case- and punctuation-insensitive.
    assert len(out) == 1


def test_skips_question_without_correct_option_body():
    # Answer marker says (e), which is not in the option list — must skip.
    md = (
        "**Q1.** Which of the following is true?\n"
        "(a) wrong-1\n(b) wrong-2\n(c) wrong-3\n(d) wrong-4\n"
        "**Ans:** (e) — none of the above"
    )
    out = parse_mcqs_from_markdown(md)
    assert out == []


def test_skips_non_question_headings():
    # `**Key Points**` and `**Summary**` look like emphasised text but are
    # not question openers, so they must not produce FAQ entries.
    md = (
        "**Key Points**\nDemocracy means rule by the people.\n\n"
        "**Summary**\nA short summary paragraph.\n\n"
        "**Q1.** What is the meaning of democracy?\n"
        "(a) wrong\n(b) wrong\n(c) rule by the people\n(d) wrong\n"
        "**Ans:** (c) — Democracy literally means rule by the people from the Greek roots demos and kratos."
    )
    out = parse_mcqs_from_markdown(md)
    assert len(out) == 1
    assert "meaning of democracy" in out[0]["question"]


def test_handles_question_word_stem_without_question_mark():
    # Real MCQs sometimes phrase the stem as a noun-phrase ending in a
    # period. `Which of the following …` should still be accepted.
    md = (
        "**Q1.** Which of the following best describes federalism.\n"
        "(a) centralisation\n(b) division of powers between centre and states\n(c) monarchy\n(d) anarchy\n"
        "**Ans:** (b) — Federalism distributes constitutional authority between a central government and constituent states."
    )
    out = parse_mcqs_from_markdown(md)
    assert len(out) == 1


def test_empty_or_invalid_input_returns_empty_list():
    assert parse_mcqs_from_markdown("") == []
    assert parse_mcqs_from_markdown(None) == []  # type: ignore[arg-type]
    assert parse_mcqs_from_markdown("just some prose with no questions") == []


def test_answer_marker_without_explanation_falls_back_to_option_body():
    # When the answer line is just `**Ans:** (c)` with no em-dash and
    # no explanation, the parser must still produce a substantive
    # answer by promoting the matching option's body. This is the safety
    # net for sparse content quality.
    md = (
        "**Q1.** Who is regarded as the principal architect of the Indian Constitution?\n"
        "(a) Mahatma Gandhi\n(b) Jawaharlal Nehru\n"
        "(c) Dr. B.R. Ambedkar, who chaired the Drafting Committee of the Constituent Assembly\n"
        "(d) Sardar Patel\n"
        "**Ans:** (c)"
    )
    out = parse_mcqs_from_markdown(md)
    assert len(out) == 1
    assert "Ambedkar" in out[0]["answer"]
    assert "Drafting Committee" in out[0]["answer"]
