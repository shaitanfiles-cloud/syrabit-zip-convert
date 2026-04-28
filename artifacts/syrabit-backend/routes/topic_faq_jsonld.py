"""FAQPage JSON-LD for chapter / topic pages — P0 #1 of the AI-visibility plan.

Builds a schema.org `FAQPage` document from the multiple-choice questions
already published under each chapter (`seo_pages` where `page_type='mcqs'`).

Why this endpoint exists
========================
Crawlers (Google, Perplexity, ChatGPT) cite content that exposes explicit
Q→A pairs as structured data. The site already produces high-quality
MCQs with verbatim explanations — this endpoint extracts them and emits
schema.org-compliant FAQPage JSON-LD that the React `ChapterPage` injects
into the document head.

Quality bar (Google Rich Results requirements):
    * Each Q+A must reflect content visible on the page.
    * Answer text must be substantive (>= 30 chars of real content).
    * No placeholder / "see our site" answers.
    * Cap at 10 FAQ entries per page (more triggers diminishing returns
      and risks Google demoting the rich result).

The legacy admin endpoint `seo_inject_schema` in `routes/admin_advanced.py`
*also* wrote a `faq_schema` field into `seo_topics`, but those answers were
placeholder strings ("Refer to Syrabit.ai for a detailed answer on …") and
the React app never consumed them. That dead field is intentionally left
alone here — this module is the new source of truth for FAQ JSON-LD on
chapter pages.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Response

from deps import db, is_mongo_available

logger = logging.getLogger(__name__)
# No `/api` prefix here — server.py mounts this router under the main
# `api` APIRouter which already has `prefix="/api"`. Adding it twice
# would produce `/api/api/...` and 404 silently.
router = APIRouter()


# ── Markdown MCQ parser ──────────────────────────────────────────────────────

# Question block opener: `**Q1.**` or `**Q1**` or `**1.**`
_Q_OPEN_RE = re.compile(r"^\s*\*\*Q?(\d+)\.?\*\*\s*(.+?)\s*$", re.MULTILINE)

# Option line: `(a) text`, `a) text`, `a. text`. Captures the letter + body.
_OPTION_RE = re.compile(
    r"^\s*\(?([a-dA-D])[\)\.]\s+(.+?)\s*$",
    re.MULTILINE,
)

# Answer marker. Real production lines look like:
#   `**Ans:** (c) — Cleisthenes, an Athenian statesman …`
#   `**Answer:** **(b)** Federalism distributes authority …`   ← no
#                                                                 separator
#                                                                 before the
#                                                                 explanation
#   `Ans: c — explanation …`
#   `**Ans:** (c)`                                              ← no
#                                                                 explanation
#                                                                 at all
# We tolerate any combination of surrounding `*` emphasis around the
# `Ans` keyword AND the option letter. Between the option letter and
# the explanation we accept ANY mix of whitespace + optional separator
# (em-dash, hyphen, colon) — the separator is informational, not
# structural, and several MCQ generator variants drop it. The
# explanation may wrap onto multiple lines (DOTALL); the caller bounds
# each block by the next question opener via a lookahead instead of
# anchoring to `$`.
_ANS_RE = re.compile(
    # Open: `Ans` / `Answer` / `Correct`, with any wrapping `*` emphasis.
    r"(?:^|\n)\s*\**\s*(?:Ans(?:wer)?|Correct)\s*\**\s*:?\s*"
    # Between marker and option-letter we allow ANY combination of `*`
    # and whitespace (handles `**Answer:** **(b)**` where two distinct
    # `**` runs appear: closing-of-marker + opening-of-option-bold).
    r"[*\s]*\(?\s*([a-dA-D])\s*\)?[*\s]*"
    # Optional separator between option label and explanation.
    r"[—\-:]*\s*"
    # Explanation up to the block boundary (next blank line, next
    # question opener, or end of string). DOTALL so `.` spans newlines.
    r"(.*?)"
    r"(?=\n\s*\n|\n\s*\*\*Q|\Z)",
    re.DOTALL,
)


def _normalise_text(s: str) -> str:
    """Collapse whitespace and strip Markdown emphasis markers from inline text."""
    s = re.sub(r"\s+", " ", s).strip()
    # Strip leading/trailing markdown emphasis but preserve interior emphasis.
    s = re.sub(r"^[*_]+|[*_]+$", "", s).strip()
    return s


def parse_mcqs_from_markdown(content: str, *, max_faqs: int = 10) -> List[Dict[str, Any]]:
    """Extract substantive Q+A pairs from a markdown MCQ page.

    Returns a list of dicts like::

        {"question": "...", "answer": "Correct answer: (c) ... — explanation"}

    Quality filters applied (see module docstring):
        * Question text >= 15 chars and ends with `?` or starts with a
          question word.
        * Correct option exists with body >= 3 chars.
        * Final answer text >= 30 chars of real content.
        * Duplicate questions are deduped (case-insensitive).

    Caller is responsible for clipping to `max_faqs` — the parser already
    enforces it but exposes the param for tests.
    """
    if not content or not isinstance(content, str):
        return []

    out: List[Dict[str, Any]] = []
    seen_questions: set = set()

    # Find every question opener; each block runs from this opener to the
    # next opener (or end of string). This avoids fragile single-block
    # regexes that break on long explanations or stray asterisks.
    openers = list(_Q_OPEN_RE.finditer(content))
    if not openers:
        return []

    for i, m in enumerate(openers):
        if len(out) >= max_faqs:
            break
        block_start = m.end()
        block_end = openers[i + 1].start() if i + 1 < len(openers) else len(content)
        block = content[block_start:block_end]

        question_text = _normalise_text(m.group(2))
        if len(question_text) < 15:
            continue
        # Accept if it ends with `?` OR begins with a question word OR
        # contains "which" / "what" etc. anywhere — MCQ stems often phrase
        # the question as a noun phrase + colon.
        ql = question_text.lower()
        is_question_like = (
            question_text.rstrip().endswith("?")
            or any(ql.startswith(w) for w in (
                "which", "what", "who", "where", "when", "why", "how",
                "in which", "name the", "identify", "choose", "select",
            ))
            or "which of the following" in ql
        )
        if not is_question_like:
            continue

        # Parse options inside this block.
        options: Dict[str, str] = {}
        for om in _OPTION_RE.finditer(block):
            label = om.group(1).lower()
            body = _normalise_text(om.group(2))
            if body and label not in options:
                options[label] = body

        # Parse the answer marker.
        ans_match = _ANS_RE.search(block)
        if not ans_match:
            continue
        correct_label = ans_match.group(1).lower()
        explanation = _normalise_text(ans_match.group(2) or "")

        correct_text = options.get(correct_label, "").strip()
        if len(correct_text) < 3:
            # Sometimes the answer line itself contains the option text in
            # parentheses, e.g. `**Ans:** (c) Cleisthenes — Athenian ...`.
            # Re-parse the explanation if it leads with an option-like body.
            if explanation:
                # Heuristic: take everything before the first em-dash / hyphen
                # as the option text, the rest as the explanation.
                parts = re.split(r"\s+[—\-]\s+", explanation, maxsplit=1)
                if len(parts) == 2 and len(parts[0]) >= 3:
                    correct_text, explanation = parts[0].strip(), parts[1].strip()
                elif len(explanation) >= 3:
                    correct_text = explanation.split(".")[0].strip()[:120]
        if len(correct_text) < 3:
            continue

        # Compose the final answer with substantive content.
        answer_parts = [f"Correct answer: ({correct_label}) {correct_text}."]
        if len(explanation) >= 20:
            answer_parts.append(explanation)
        answer_text = " ".join(answer_parts).strip()
        # Strip any trailing markdown asterisks left from `*Exam tip: …*` etc.
        answer_text = re.sub(r"\s*\*+\s*$", "", answer_text)

        if len(answer_text) < 30:
            continue

        q_key = re.sub(r"\W+", "", question_text.lower())[:80]
        if q_key in seen_questions:
            continue
        seen_questions.add(q_key)

        out.append({"question": question_text, "answer": answer_text})

    return out


# ── In-process cache (1h TTL, identical pattern to topic-pyqs) ───────────────

_CACHE: Dict[str, tuple[float, Any]] = {}
_CACHE_TTL_S = 3600


def _cache_get(key: str) -> Optional[Any]:
    entry = _CACHE.get(key)
    if not entry:
        return None
    ts, val = entry
    if time.time() - ts > _CACHE_TTL_S:
        _CACHE.pop(key, None)
        return None
    return val


def _cache_set(key: str, val: Any) -> None:
    _CACHE[key] = (time.time(), val)
    # Bound memory: keep at most 4096 entries (~5MB).
    if len(_CACHE) > 4096:
        # Evict the oldest 25% by timestamp.
        items = sorted(_CACHE.items(), key=lambda kv: kv[1][0])
        for k, _ in items[: len(items) // 4]:
            _CACHE.pop(k, None)


# ── Public endpoint ──────────────────────────────────────────────────────────

@router.get("/content/chapters/{chapter_id}/faq-jsonld")
async def get_chapter_faq_jsonld(
    chapter_id: str,
    response: Response = None,
    limit: int = 10,
):
    """Return a schema.org FAQPage JSON-LD object for a chapter.

    Source data: published `seo_pages` rows with `page_type='mcqs'` and
    `chapter_slug` matching the resolved chapter. Returns 404 if the
    chapter is unknown or no substantive FAQ entries can be extracted —
    a 404 is preferable to emitting an empty FAQPage that triggers
    Google Search Console warnings.

    Cached for 1h server-side; sets a public Cache-Control header so the
    edge proxy and CDN cache the response too.
    """
    limit = max(1, min(int(limit or 10), 10))
    cache_key = f"chapter-faq-jsonld:{chapter_id}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        if response is not None:
            response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=86400"
        return cached

    if not await is_mongo_available():
        raise HTTPException(503, "Content database unavailable")

    chapter = await db.chapters.find_one(
        {"id": chapter_id},
        {"_id": 0, "id": 1, "slug": 1, "title": 1},
    )
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    chapter_slug = chapter.get("slug")
    if not chapter_slug:
        raise HTTPException(404, "Chapter has no slug")

    # Pull every published MCQ seo_page for this chapter. Most chapters
    # have exactly one (`prompt_variant` rarely exceeds 1 published) but
    # the loop is cheap and tolerant.
    mcq_pages = await db.seo_pages.find(
        {
            "page_type": "mcqs",
            "chapter_slug": chapter_slug,
            "status": "published",
        },
        {"_id": 0, "content": 1, "title": 1, "topic_slug": 1},
    ).to_list(10)

    faq_entries: List[Dict[str, Any]] = []
    for page in mcq_pages:
        if len(faq_entries) >= limit:
            break
        parsed = parse_mcqs_from_markdown(page.get("content", ""), max_faqs=limit)
        for entry in parsed:
            if len(faq_entries) >= limit:
                break
            faq_entries.append(entry)

    # Schema.org FAQPage is only emitted by the React/prerender pipeline
    # when there are >= 2 entries (see `chapterSchema()` in
    # `src/lib/jsonld.js`). Mirror that gate here so a single Q+A doesn't
    # falsely satisfy the API contract while downstream silently drops it.
    if len(faq_entries) < 2:
        raise HTTPException(404, "No FAQ-eligible content for this chapter")

    main_entity = [
        {
            "@type": "Question",
            "name": e["question"],
            "acceptedAnswer": {
                "@type": "Answer",
                "text": e["answer"],
            },
        }
        for e in faq_entries
    ]
    payload = {
        # Raw entries — preferred by the React client which feeds them
        # into the existing `chapterSchema()` builder so the FAQPage node
        # joins the same `@graph` as Article / LearningResource / etc.
        # Avoids emitting a duplicate <script type="application/ld+json">.
        "entries": faq_entries,
        # Pre-built JSON-LD object — kept for any consumer that wants a
        # ready-to-inject FAQPage (server-rendered pages, prerender script,
        # external tooling). Both fields describe the same Q+A set.
        "faq_jsonld": {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": main_entity,
        },
        "count": len(main_entity),
        "chapter_id": chapter_id,
        "chapter_slug": chapter_slug,
    }
    _cache_set(cache_key, payload)
    if response is not None:
        response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=86400"
    return payload
