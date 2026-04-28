"""Task #939 — Agentic internal-linker.

After every Stage 3 SEO page is generated, an LLM picks 3-5 best
contextual link sources elsewhere on the site, proposes anchor text +
confidence per source. >= auto-apply threshold → insert anchor into
source page body in-place + re-render. < threshold → admin "Pending
suggestions" queue (`internal_link_history` with action=``drafted``)
with one-click approve / reject + diff preview.

Daily budget cap: default 100 auto-applies/day, unlimited drafts.
Nightly maintenance pass against top-N traffic pages.

Public surface
--------------
* ``propose_internal_links_for_page(db, page_doc, *, source="stage3")``
  — fire-and-forget entry point invoked from
  ``seo_engine._generate_single_page`` after the target page is
  persisted. Awaited only by tests; production callers schedule it via
  ``asyncio.create_task`` so generation latency is unaffected.
* ``apply_pending_suggestion(db, rec_id, admin_label)`` — admin
  approve: insert anchor into source body + flip history row to
  ``auto_applied`` (treated as "manually approved" via
  ``approved_by``).
* ``reject_pending_suggestion(db, rec_id, admin_label)`` — admin
  reject (no body mutation).
* ``revert_applied_suggestion(db, rec_id, admin_label)`` — undo a
  previously auto-applied or admin-approved insertion.
* ``nightly_maintenance_pass(db, *, top_n=None)`` — worker entry
  point invoked from the leader-gated loop. Re-runs the linker
  against the top-N highest-traffic pages so older content benefits
  from links to newer pages.
* ``decide_action(...)`` / ``insert_anchor`` / ``remove_anchor`` —
  pure helpers exposed for unit tests.

Collections
-----------
* ``internal_link_history`` — audit log keyed by ``id``. Each row
  captures one (target_page, source_page) suggestion with action,
  confidence, anchor_text, before/after excerpts.
* ``internal_link_budget`` — one doc per UTC date with ``$inc``
  counter for auto-applied insertions.

Idempotency
-----------
Every inserted link is wrapped with an HTML comment marker
``<!-- syrabit:autolink:{target_page_id} -->`` so:
  - the insert phase can detect "already linked" and skip duplicates,
  - the revert phase can locate and remove the exact link tag,
  - re-running the linker against the same source/target pair never
    double-links or amplifies the body.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

try:  # Optional — only present when running against real MongoDB.
    from pymongo.errors import DuplicateKeyError
except Exception:  # pragma: no cover - test environment with fake db.
    class DuplicateKeyError(Exception):
        pass

logger = logging.getLogger(__name__)

# Action lifecycle for ``internal_link_history`` rows.
ACTION_AUTO_APPLIED = "auto_applied"
ACTION_DRAFTED = "drafted"
ACTION_REJECTED = "rejected"
ACTION_REVERTED = "reverted"
ACTION_FAILED = "failed"
# NB: there is no "skipped_budget" action — by spec, suggestions that
# exceed the daily auto-apply cap fall through to ``ACTION_DRAFTED`` so
# the work is preserved for admin review rather than discarded. Keeping
# the action taxonomy minimal here keeps downstream analytics clean.
ACTION_SKIPPED_DUPLICATE = "skipped_duplicate"
ACTION_SKIPPED_NO_ANCHOR = "skipped_no_anchor"

VALID_ACTIONS = frozenset({
    ACTION_AUTO_APPLIED,
    ACTION_DRAFTED,
    ACTION_REJECTED,
    ACTION_REVERTED,
    ACTION_FAILED,
    ACTION_SKIPPED_DUPLICATE,
    ACTION_SKIPPED_NO_ANCHOR,
})

HISTORY_RETENTION_DAYS = 30


def get_config() -> dict:
    """Operator-tunable knobs. Re-read on every call so test
    monkeypatch on os.environ takes effect without restart."""
    return {
        # Confidence threshold (0-1) above which the LLM's proposal
        # is auto-applied. Below it goes to the pending queue.
        "auto_apply_threshold": float(os.getenv("SEO_LINKER_AUTO_THRESHOLD", "0.75")),
        # Number of links the LLM is asked to return per target.
        "min_links_per_target": int(os.getenv("SEO_LINKER_MIN_PER_TARGET", "3")),
        "max_links_per_target": int(os.getenv("SEO_LINKER_MAX_PER_TARGET", "5")),
        # Candidate pool size handed to the LLM (after lexical scoring).
        "candidate_pool_size": int(os.getenv("SEO_LINKER_POOL_SIZE", "30")),
        # Per-day cap on auto-applied insertions (drafts are unlimited).
        "auto_per_day": int(os.getenv("SEO_LINKER_AUTO_PER_DAY", "100")),
        # Top-N traffic pages re-linked nightly. 0 disables nightly.
        "nightly_top_n": int(os.getenv("SEO_LINKER_NIGHTLY_TOP_N", "50")),
        # Sleep between nightly cycles when no work is queued.
        "nightly_idle_secs": float(os.getenv("SEO_LINKER_NIGHTLY_IDLE_SECS", "3600")),
        # Master kill-switch.
        "enabled": os.getenv("SEO_LINKER_ENABLED", "1") not in ("0", "false", "False", ""),
    }


def _autolink_marker(target_page_id: str) -> str:
    """Idempotency marker placed immediately before each inserted
    anchor. The remove phase searches for this exact comment to
    locate the matching ``<a>`` tag."""
    return f"<!-- syrabit:autolink:{target_page_id} -->"


def _strip_html_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "")


# ---------------------------------------------------------------------------
# Anchor insertion / removal (pure functions, exposed for tests)
# ---------------------------------------------------------------------------
def insert_anchor(body: str, *, anchor_text: str, target_url: str,
                  target_page_id: str) -> tuple[str, bool]:
    """Insert an anchor into ``body`` at the first non-tag occurrence
    of ``anchor_text``. Returns ``(new_body, did_insert)``.

    Skips when:
      - the body already contains the autolink marker for this target
        (idempotency — re-running the linker is a no-op),
      - ``anchor_text`` does not appear verbatim in the visible text,
      - the only matches are inside an existing ``<a>``, ``<code>``,
        ``<pre>`` or heading tag (we never nest links or rewrite code
        samples).
    """
    if not body or not anchor_text or not target_url or not target_page_id:
        return body or "", False
    marker = _autolink_marker(target_page_id)
    if marker in body:
        return body, False  # already linked — idempotency guard

    # Build a regex that matches the anchor text as a whole-word
    # substring, case-insensitive. We do the "is this inside a tag?"
    # check by examining what surrounds each match.
    pattern = re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(anchor_text) + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    # Mask out regions we must never touch: existing <a>, <code>,
    # <pre>, <h1>-<h6>, and HTML tag attributes. We replace them with
    # spaces of the same length so character offsets stay aligned.
    masked = body
    for tag in ("a", "code", "pre", "h1", "h2", "h3", "h4", "h5", "h6"):
        block_re = re.compile(
            rf"<{tag}\b[^>]*>.*?</{tag}>", re.IGNORECASE | re.DOTALL,
        )
        masked = block_re.sub(lambda m: " " * len(m.group(0)), masked)
    # Also mask raw HTML tags (so anchor text inside an attribute
    # value doesn't accidentally match).
    masked = re.sub(r"<[^>]+>", lambda m: " " * len(m.group(0)), masked)

    m = pattern.search(masked)
    if not m:
        return body, False
    start, end = m.start(), m.end()
    # Recover the original-cased substring from ``body`` (so we don't
    # rewrite "Newton" as "newton").
    original_anchor = body[start:end]
    safe_url = target_url.replace('"', "&quot;")
    replacement = (
        f'{marker}<a href="{safe_url}" data-internal-link="{target_page_id}">'
        f'{original_anchor}</a>'
    )
    return body[:start] + replacement + body[end:], True


def remove_anchor(body: str, *, target_page_id: str) -> tuple[str, bool]:
    """Remove the anchor previously inserted for ``target_page_id``.

    Locates the ``<!-- syrabit:autolink:TID -->`` marker and the
    immediately-following ``<a ...>...</a>`` tag, replaces the whole
    thing with the original anchor text. Returns
    ``(new_body, did_remove)``. Idempotent: a body that doesn't
    contain the marker is returned unchanged.
    """
    if not body or not target_page_id:
        return body or "", False
    marker = _autolink_marker(target_page_id)
    pattern = re.compile(
        re.escape(marker) + r"\s*<a\b[^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    m = pattern.search(body)
    if not m:
        return body, False
    return body[:m.start()] + m.group(1) + body[m.end():], True


# ---------------------------------------------------------------------------
# Decision engine (pure, exposed for unit tests)
# ---------------------------------------------------------------------------
def decide_action(*, confidence: float, budget_used: int, budget_cap: int,
                  duplicate: bool, anchor_findable: bool,
                  config: Mapping[str, Any] | None = None) -> dict:
    """Decide what to do with one LLM-proposed (source, anchor) suggestion.

    Returns ``{"action": <ACTION_*>, "reason": str}``. The history row
    written by the worker mirrors this exact shape so the admin UI
    can show *why* each row was auto-applied vs drafted.
    """
    cfg = dict(config or get_config())
    if duplicate:
        return {"action": ACTION_SKIPPED_DUPLICATE,
                "reason": "source already links to this target"}
    if not anchor_findable:
        return {"action": ACTION_SKIPPED_NO_ANCHOR,
                "reason": "anchor text not present in source body"}
    threshold = float(cfg.get("auto_apply_threshold", 0.75))
    if confidence < threshold:
        return {"action": ACTION_DRAFTED,
                "reason": f"confidence {confidence:.2f} < threshold {threshold:.2f}"}
    if budget_used >= int(budget_cap):
        # Above-threshold but no auto budget left — file as draft so
        # the admin can still approve manually rather than dropping.
        return {"action": ACTION_DRAFTED,
                "reason": f"daily auto cap reached ({budget_used}/{budget_cap}); drafted"}
    return {"action": ACTION_AUTO_APPLIED,
            "reason": f"confidence {confidence:.2f} >= threshold {threshold:.2f}"}


# ---------------------------------------------------------------------------
# Budget cap
# ---------------------------------------------------------------------------
def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def get_budget_status(db) -> dict:
    """Return today's auto-apply usage + cap for the admin status pill."""
    cfg = get_config()
    doc = await db.internal_link_budget.find_one({"_id": _today_key()}) or {}
    return {
        "date": _today_key(),
        "auto_used": int(doc.get("auto_applied", 0)),
        "auto_cap": cfg["auto_per_day"],
    }


async def _consume_auto_budget(db, cap: int) -> bool:
    """Atomically reserve **one** auto-apply slot for today.

    Returns ``True`` if the slot was reserved (and the caller may proceed
    with the auto-apply), ``False`` if today's cap has already been
    reached.  We use a single conditional ``update_one`` with a
    ``auto_applied < cap`` guard so concurrent propose tasks running on
    different workers cannot collectively exceed the daily budget — even
    if they all observed remaining budget before this call.
    """
    today = _today_key()
    # Ensure the doc exists so the conditional update has something to
    # match against on day-zero.  Upsert is idempotent; concurrent
    # workers racing on the very first call of the day can both miss
    # the existing doc and both attempt the insert — the loser raises
    # ``DuplicateKeyError`` which we treat as benign.
    try:
        await db.internal_link_budget.update_one(
            {"_id": today},
            {
                "$setOnInsert": {
                    "auto_applied": 0,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            },
            upsert=True,
        )
    except DuplicateKeyError:
        pass
    res = await db.internal_link_budget.update_one(
        {"_id": today, "auto_applied": {"$lt": int(cap)}},
        {"$inc": {"auto_applied": 1}},
    )
    return bool(getattr(res, "modified_count", 0))


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------
def _build_page_url(page: Mapping[str, Any]) -> str:
    """Reconstruct the canonical site-relative URL from the slug
    fields stored on the seo_pages doc. Mirrors the same shape the
    sitemap + IndexNow batcher use so the inserted href is stable
    across re-renders."""
    parts = [
        (page.get("board_slug") or "").strip("/"),
        (page.get("class_slug") or "").strip("/"),
        (page.get("subject_slug") or "").strip("/"),
        (page.get("topic_slug") or "").strip("/"),
    ]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    page_type = (page.get("page_type") or "notes").strip("/")
    # Canonical convention: ``notes`` has no path suffix.
    if page_type and page_type != "notes":
        parts.append(page_type)
    return "/" + "/".join(parts)


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "with",
    "is", "are", "by", "at", "from", "as", "be", "this", "that", "it",
    "its", "what", "how", "why", "when", "where", "which", "introduction",
    "notes", "definition", "questions", "mcqs", "examples", "faq",
    "important", "chapter",
})


def _tokenize(s: str) -> set[str]:
    if not s:
        return set()
    toks = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", s.lower())
    return {t for t in toks if t not in _STOPWORDS}


def _score_candidate(target_tokens: set[str], cand: Mapping[str, Any]) -> float:
    """BM25-lite keyword relevance: count overlapping topical tokens
    between target and candidate, normalised by candidate token-set
    size so longer titles don't dominate."""
    cand_tokens = _tokenize(cand.get("topic_title", "")) | \
                  _tokenize(cand.get("title", "")) | \
                  _tokenize(cand.get("subject_name", ""))
    if not cand_tokens:
        return 0.0
    overlap = len(target_tokens & cand_tokens)
    if overlap == 0:
        return 0.0
    # Saturate so the signal lives in [0, 1]; matches BM25's diminishing
    # returns shape closely enough for a coarse first-stage filter.
    return overlap / (overlap + 2.0)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def _embed_for_linker(text: str, *, task_type: str) -> Optional[list[float]]:
    """Best-effort embedding via existing vertex_services helper.
    Returns ``None`` when embeddings are unavailable so the rest of
    the pipeline degrades cleanly to keyword-only ranking (offline /
    rate-limited / dev-without-creds)."""
    if not text:
        return None
    try:
        import vertex_services  # local import — keeps test envs offline-safe.
        vec = await vertex_services.embed_text(text, task_type=task_type)
        if isinstance(vec, list) and vec:
            return [float(x) for x in vec]
    except Exception as exc:  # pragma: no cover - logged only.
        logger.debug("internal_linker: embed_text failed (%s) — falling back to keyword-only", exc)
    return None


def _candidate_embed_text(d: Mapping[str, Any]) -> str:
    parts = [d.get("topic_title") or "", d.get("title") or ""]
    body = (d.get("content") or "")
    # Strip HTML tags cheaply and trim — we only need a topical fingerprint.
    body = re.sub(r"<[^>]+>", " ", body)
    parts.append(body[:600])
    return " ".join(p for p in parts if p).strip()


async def _select_candidate_sources(
    db, target: Mapping[str, Any], *, exclude_ids: Iterable[str] = (),
    pool_size: Optional[int] = None,
) -> list[dict]:
    """Hybrid retrieval pipeline:

    1. Pull a wide candidate pool (~500 same-subject, fall back to
       whole site) from Mongo.
    2. Score each candidate with **BM25-lite** keyword overlap and
       **embedding cosine** similarity (target topic + summary vs.
       candidate topic + content), then combine ``0.6 * cosine +
       0.4 * keyword`` into a single relevance score.
    3. Truncate to the configured pool size (default ~30) — this is
       the input the LLM ranker actually sees.

    Embeddings are best-effort: if ``vertex_services.embed_text``
    fails, the pipeline degrades to keyword-only ranking, which keeps
    Stage 3 generation resilient when the embedding backend is down.
    """
    cfg = get_config()
    pool = int(pool_size or cfg["candidate_pool_size"])
    target_id = target.get("id")
    target_topic_id = target.get("topic_id")
    excluded = set(exclude_ids) | {target_id} if target_id else set(exclude_ids)
    target_tokens = _tokenize(target.get("topic_title", "")) | \
                    _tokenize(target.get("title", ""))
    if not target_tokens:
        return []

    # ── Stage 1: wide Mongo pool ──────────────────────────────────────
    query: dict = {"status": "published"}
    if target.get("subject_id"):
        query["subject_id"] = target["subject_id"]
    projection = {
        "_id": 0, "id": 1, "topic_id": 1, "topic_slug": 1,
        "subject_id": 1, "subject_slug": 1, "subject_name": 1,
        "class_slug": 1, "board_slug": 1,
        "topic_title": 1, "title": 1, "page_type": 1,
        "content": 1,
    }
    docs = await db.seo_pages.find(query, projection).limit(500).to_list(500)
    if len(docs) < pool and target.get("subject_id"):
        docs = await db.seo_pages.find(
            {"status": "published"}, projection,
        ).limit(800).to_list(800)

    eligible = []
    for d in docs:
        if d.get("id") in excluded:
            continue
        if target_topic_id and d.get("topic_id") == target_topic_id:
            continue
        eligible.append(d)
    if not eligible:
        return []

    # ── Stage 2a: keyword (BM25-lite) score ───────────────────────────
    keyword_scored: list[tuple[float, dict]] = []
    for d in eligible:
        s = _score_candidate(target_tokens, d)
        if s > 0:
            keyword_scored.append((s, d))
    if not keyword_scored:
        return []

    # Pre-truncate to a manageable size for the embedding pass — there's
    # no point spending a vector call on a doc with zero keyword signal.
    # Secondary sort by ``id`` ensures deterministic ordering when two
    # candidates have identical scores (test stability + reproducible
    # nightly runs).
    keyword_scored.sort(key=lambda t: (-t[0], str(t[1].get("id") or "")))
    short_pool = keyword_scored[: max(pool * 3, 60)]

    # ── Stage 2b: embedding cosine (best-effort) ─────────────────────
    target_text = " ".join([
        target.get("topic_title") or "",
        target.get("title") or "",
        re.sub(r"<[^>]+>", " ", target.get("content") or "")[:600],
    ]).strip()
    target_vec = await _embed_for_linker(target_text, task_type="RETRIEVAL_QUERY")
    cand_vecs: dict[str, list[float]] = {}
    if target_vec is not None:
        # Embed candidates serially; the pool is small (≤90) and the
        # embedding helper already pools/caches under the hood.
        for _, d in short_pool:
            v = await _embed_for_linker(
                _candidate_embed_text(d), task_type="RETRIEVAL_DOCUMENT",
            )
            if v is not None:
                cand_vecs[d.get("id", "")] = v

    # ── Stage 3: hybrid blend ────────────────────────────────────────
    final: list[tuple[float, dict]] = []
    for kscore, d in short_pool:
        cscore = 0.0
        if target_vec is not None:
            v = cand_vecs.get(d.get("id", ""))
            if v is not None:
                cscore = max(0.0, _cosine(target_vec, v))
        if target_vec is not None and cand_vecs:
            blended = 0.6 * cscore + 0.4 * kscore
        else:
            # No embeddings available — fall back to keyword-only.
            blended = kscore
        final.append((blended, d))
    final.sort(key=lambda t: (-t[0], str(t[1].get("id") or "")))
    return [d for _, d in final[:pool]]


# ---------------------------------------------------------------------------
# LLM rank
# ---------------------------------------------------------------------------
_LLM_SYSTEM_PROMPT = (
    "You are an SEO internal-linking agent for an Indian school-board "
    "study site. You receive ONE target page (newly published) and a list "
    "of candidate source pages elsewhere on the site. Your job: pick the "
    "best contextual sources to link FROM (source) TO the target. For each "
    "chosen source, return a short anchor text (2-6 words) that already "
    "appears verbatim in the source body, plus a confidence score in "
    "[0,1] reflecting how natural and relevant the link will read in "
    "context. Skip a source if no natural anchor exists. Respond with "
    "STRICT JSON only, no prose."
)


def _build_llm_prompt(target: Mapping[str, Any], candidates: list[dict],
                      *, want_min: int, want_max: int) -> str:
    target_block = (
        f"TARGET PAGE\n"
        f"  title: {target.get('title') or target.get('topic_title') or ''}\n"
        f"  topic: {target.get('topic_title') or ''}\n"
        f"  subject: {target.get('subject_name') or ''}\n"
        f"  page_type: {target.get('page_type') or 'notes'}\n"
        f"  url: {_build_page_url(target)}\n"
        f"  summary: {(target.get('answer_summary') or '')[:300]}\n"
    )
    cand_blocks = []
    for i, c in enumerate(candidates):
        # Snippet is plain text, capped — the LLM only needs enough
        # context to spot a natural anchor phrase.
        snippet = _strip_html_tags(c.get("content", ""))[:400]
        cand_blocks.append(
            f"[{i}] id={c.get('id')} topic={c.get('topic_title') or c.get('title')} "
            f"subject={c.get('subject_name') or ''} type={c.get('page_type') or 'notes'}\n"
            f"    snippet: {snippet}\n"
        )
    schema = (
        f'{{"links": [{{"source_index": <int>, "anchor_text": "<2-6 words found in '
        f'snippet>", "confidence": <0..1>, "reason": "<short>"}}]}}\n'
        f"Pick between {want_min} and {want_max} sources. Anchor text MUST appear "
        f"verbatim in the source snippet. Order by confidence descending."
    )
    return f"{target_block}\nCANDIDATE SOURCES\n{''.join(cand_blocks)}\n{schema}"


def _parse_llm_response(raw: str) -> list[dict]:
    """Tolerant JSON extraction. The content LLM occasionally wraps
    the JSON in a ```json ... ``` fence or prepends a one-line
    preface; we strip both before json.loads."""
    if not raw:
        return []
    text = raw.strip()
    # Prefer the first JSON object in the response.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    items = obj.get("links") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for it in items:
        if not isinstance(it, Mapping):
            continue
        try:
            idx = int(it.get("source_index"))
        except (TypeError, ValueError):
            continue
        anchor = (it.get("anchor_text") or "").strip()
        if not anchor:
            continue
        try:
            conf = float(it.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        out.append({
            "source_index": idx,
            "anchor_text": anchor,
            "confidence": conf,
            "reason": (it.get("reason") or "")[:300],
        })
    return out


async def _llm_rank(target: Mapping[str, Any],
                    candidates: list[dict]) -> list[dict]:
    """Hand the target + candidate snippets to the content LLM, parse
    the JSON response back into ``[{source_index, anchor_text,
    confidence, reason}]``. Returns an empty list when the LLM is
    unavailable so the caller falls back to "no suggestions"."""
    if not candidates:
        return []
    cfg = get_config()
    prompt = _build_llm_prompt(
        target, candidates,
        want_min=cfg["min_links_per_target"], want_max=cfg["max_links_per_target"],
    )
    try:
        from llm import call_llm_api_content_with_retry
        raw = await call_llm_api_content_with_retry(
            [
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
        )
    except Exception as exc:
        logger.warning("internal_linker: LLM call failed: %s", exc)
        return []
    parsed = _parse_llm_response(raw)
    # Hard-clamp server-side to the configured per-target window so a
    # chatty LLM cannot blow past the 3-5 cap promised in the spec.
    cap = max(1, int(cfg["max_links_per_target"]))
    if len(parsed) > cap:
        # Highest-confidence first so the cap drops the weakest tail.
        parsed.sort(key=lambda r: float(r.get("confidence") or 0.0), reverse=True)
        parsed = parsed[:cap]
    return parsed


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------
async def _record_history(db, *, target: Mapping[str, Any],
                          source: Mapping[str, Any] | None,
                          anchor_text: str, confidence: float,
                          decision: Mapping[str, Any],
                          before_excerpt: str = "",
                          after_excerpt: str = "",
                          source_label: str = "stage3",
                          error: Optional[str] = None) -> dict:
    """Insert one ``internal_link_history`` row capturing everything
    an admin needs to audit the agent decision."""
    rid = f"il-{uuid.uuid4().hex[:10]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    target_url = _build_page_url(target)
    source_url = _build_page_url(source) if source else None
    row = {
        "id": rid,
        "target_page_id": target.get("id"),
        "target_topic_id": target.get("topic_id"),
        "target_topic_title": target.get("topic_title") or target.get("title"),
        "target_url": target_url,
        "target_page_type": target.get("page_type"),
        "source_page_id": (source or {}).get("id"),
        "source_topic_id": (source or {}).get("topic_id"),
        "source_topic_title": (source or {}).get("topic_title")
                              or (source or {}).get("title"),
        "source_url": source_url,
        "source_page_type": (source or {}).get("page_type"),
        "anchor_text": anchor_text,
        "confidence": float(confidence),
        "action": decision.get("action"),
        "reason": decision.get("reason"),
        "trigger": source_label,
        "diff": {
            "before_excerpt": before_excerpt[:600],
            "after_excerpt": after_excerpt[:600],
        },
        "created_at": now_iso,
        "applied_at": now_iso if decision.get("action") == ACTION_AUTO_APPLIED else None,
        "approved_at": None,
        "approved_by": None,
        "reverted_at": None,
        "reverted_by": None,
        "rejected_at": None,
        "rejected_by": None,
        "error": error,
    }
    await db.internal_link_history.insert_one(row)
    return row


def _excerpt_around(body: str, anchor_text: str, *, span: int = 120) -> str:
    """Pull a context excerpt centred on the first occurrence of
    ``anchor_text`` for the diff preview the admin UI shows."""
    if not body or not anchor_text:
        return (body or "")[:240]
    idx = body.lower().find(anchor_text.lower())
    if idx < 0:
        return body[:240]
    start = max(0, idx - span)
    end = min(len(body), idx + len(anchor_text) + span)
    return body[start:end]


# ---------------------------------------------------------------------------
# In-place body update (writes through seo_writes for stamp safety)
# ---------------------------------------------------------------------------
async def _persist_body_update(db, source: Mapping[str, Any],
                               new_body: str) -> None:
    """Write the rewritten source body back to ``seo_pages`` via the
    centralized helper so created_at / updated_at stamps stay
    consistent. Fire IndexNow + prerender refresh so search engines
    + the static cache see the link quickly."""
    from seo_writes import upsert_seo_page
    sid = source.get("id")
    if not sid:
        # No stable id — fall back to (topic_id, page_type) which is
        # the upsert key seo_engine.py uses.
        filt = {
            "topic_id": source.get("topic_id"),
            "page_type": source.get("page_type") or "notes",
        }
    else:
        filt = {"id": sid}
    await upsert_seo_page(db, filt, {"content": new_body})
    # Best-effort fan-out: IndexNow + prerender refresh. Mirror the
    # exact pattern used by routes/admin_content.py so a deploy-hook
    # outage never breaks the linker.
    try:
        from seo_fanout import fanout_for_page
        fanout_for_page(source, source="internal_linker_apply")
    except Exception as exc:
        logger.debug("internal_linker: seo_fanout dispatch failed: %s", exc)
    try:
        from routes.admin_content import _schedule_prerender_refresh
        _schedule_prerender_refresh("internal_linker_apply")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Pipeline: propose links for one target page
# ---------------------------------------------------------------------------
async def propose_internal_links_for_page(
    db, target: Mapping[str, Any], *, source: str = "stage3",
) -> list[dict]:
    """Main entry point. Selects candidates, asks the LLM to rank,
    auto-applies high-confidence picks (subject to the daily budget),
    drafts the rest into the pending queue. Returns the list of
    history rows written so callers (tests, the admin trigger
    endpoint) can inspect what happened. Always swallows its own
    errors — failure here must never break Stage 3 publishing."""
    cfg = get_config()
    if not cfg["enabled"]:
        return []
    if not target or not target.get("id"):
        return []
    if (target.get("status") or "published") != "published":
        # Only link from / to live pages.
        return []
    rows: list[dict] = []
    try:
        candidates = await _select_candidate_sources(db, target)
        if not candidates:
            return []
        proposals = await _llm_rank(target, candidates)
        if not proposals:
            return []
        budget = await get_budget_status(db)
        used = budget["auto_used"]
        cap = budget["auto_cap"]
        seen_sources: set[str] = set()
        for p in proposals:
            try:
                idx = int(p.get("source_index"))
            except (TypeError, ValueError):
                continue
            if idx < 0 or idx >= len(candidates):
                continue
            cand = candidates[idx]
            cand_id = cand.get("id")
            if not cand_id or cand_id in seen_sources:
                continue
            seen_sources.add(cand_id)
            # Duplicate guard — has the source already linked to this
            # target before? Uses the audit log + the body marker as
            # belt-and-braces.
            existing = await db.internal_link_history.find_one({
                "source_page_id": cand_id,
                "target_page_id": target.get("id"),
                "action": {"$in": [ACTION_AUTO_APPLIED, ACTION_DRAFTED]},
            }, {"_id": 0, "id": 1})
            duplicate = bool(existing)
            body_already_marked = _autolink_marker(target.get("id", "")) in (cand.get("content") or "")
            if body_already_marked:
                duplicate = True
            anchor_text = (p.get("anchor_text") or "").strip()
            confidence = float(p.get("confidence", 0))
            # Probe insert (without persisting) to know whether the
            # anchor is locatable in the source body.
            new_body, did_insert = insert_anchor(
                cand.get("content") or "", anchor_text=anchor_text,
                target_url=_build_page_url(target),
                target_page_id=target.get("id", ""),
            )
            anchor_findable = did_insert
            decision = decide_action(
                confidence=confidence, budget_used=used, budget_cap=cap,
                duplicate=duplicate, anchor_findable=anchor_findable,
                config=cfg,
            )
            before_excerpt = _excerpt_around(cand.get("content") or "", anchor_text)
            after_excerpt = _excerpt_around(new_body, anchor_text) if did_insert else ""
            error: Optional[str] = None
            if decision["action"] == ACTION_AUTO_APPLIED:
                # Reserve the budget slot atomically *before* we touch the
                # body — under concurrent propose tasks this is the only
                # thing standing between us and exceeding the daily cap.
                reserved = await _consume_auto_budget(db, cap)
                if not reserved:
                    decision = {
                        "action": ACTION_DRAFTED,
                        "reason": (
                            f"auto-apply daily cap reached "
                            f"(cap={cap}); queued for admin review"
                        ),
                    }
                    after_excerpt = ""
                else:
                    try:
                        await _persist_body_update(db, cand, new_body)
                        used += 1
                    except Exception as exc:
                        logger.warning(
                            "internal_linker: auto-apply persist failed "
                            "src=%s tgt=%s: %s",
                            cand_id, target.get("id"), exc,
                        )
                        decision = {"action": ACTION_FAILED,
                                    "reason": "persist body update failed"}
                        error = str(exc)[:300]
                        # Release the slot we just claimed — body never
                        # actually got the anchor so it shouldn't count.
                        try:
                            await db.internal_link_budget.update_one(
                                {"_id": _today_key(),
                                 "auto_applied": {"$gt": 0}},
                                {"$inc": {"auto_applied": -1}},
                            )
                        except Exception:
                            pass
            row = await _record_history(
                db, target=target, source=cand, anchor_text=anchor_text,
                confidence=confidence, decision=decision,
                before_excerpt=before_excerpt, after_excerpt=after_excerpt,
                source_label=source, error=error,
            )
            rows.append(row)
    except Exception as exc:
        # Last-resort guard so a propose() crash never breaks Stage 3.
        logger.warning(
            "internal_linker: propose() crashed for target=%s: %s",
            target.get("id"), exc,
        )
    return rows


def schedule_propose(db, target: Mapping[str, Any], *,
                     source: str = "stage3") -> None:
    """Fire-and-forget scheduler used by Stage 3. Wraps the coroutine
    in ``asyncio.create_task`` if a loop is running; falls back to a
    no-op when called from a sync context (tests)."""
    cfg = get_config()
    if not cfg["enabled"]:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(propose_internal_links_for_page(db, dict(target), source=source))


# ---------------------------------------------------------------------------
# Admin actions
# ---------------------------------------------------------------------------
async def apply_pending_suggestion(db, rec_id: str, admin_label: str) -> dict:
    """Admin approve flow: insert the anchor into the source page,
    flip the history row to ``auto_applied`` (and stamp
    ``approved_by``/``approved_at`` so the audit trail distinguishes
    bot vs human approvals)."""
    rec = await db.internal_link_history.find_one({"id": rec_id}, {"_id": 0})
    if not rec:
        return {"ok": False, "error": "not_found"}
    # Approve only operates on the pending queue. To re-approve a row that
    # was previously rejected, an admin must explicitly re-trigger the
    # linker — that keeps the audit trail honest and prevents accidental
    # resurrection of rejected suggestions from the history view.
    if rec.get("action") != ACTION_DRAFTED:
        return {"ok": False, "error": f"can only approve drafted suggestions (got action={rec.get('action')})"}
    sid = rec.get("source_page_id")
    tid = rec.get("target_page_id")
    if not sid or not tid:
        return {"ok": False, "error": "missing source/target id"}
    # Defence-in-depth: target_url is admin-mediated and produced by
    # _build_page_url at draft time, but tighten the contract anyway so
    # a hand-edited / corrupted history row can't insert a foreign-host
    # anchor or a javascript: URL into a published page body.
    target_url = (rec.get("target_url") or "").strip()
    if not target_url.startswith("/") or target_url.startswith("//"):
        return {"ok": False, "error": "target_url must be a site-relative path"}
    if any(c in target_url for c in ('"', "'", "<", ">", "\n", "\r")):
        return {"ok": False, "error": "target_url contains illegal characters"}
    source = await db.seo_pages.find_one({"id": sid}, {"_id": 0})
    if not source:
        return {"ok": False, "error": "source page no longer exists"}
    new_body, did = insert_anchor(
        source.get("content") or "", anchor_text=rec.get("anchor_text") or "",
        target_url=target_url,
        target_page_id=tid,
    )
    if not did:
        return {"ok": False, "error": "anchor not findable in current body"}
    await _persist_body_update(db, source, new_body)
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.internal_link_history.update_one(
        {"id": rec_id},
        {"$set": {
            "action": ACTION_AUTO_APPLIED,
            "approved_at": now_iso, "approved_by": admin_label,
            "applied_at": now_iso,
            "diff.after_excerpt": _excerpt_around(new_body, rec.get("anchor_text") or "")[:600],
        }},
    )
    return {"ok": True}


async def reject_pending_suggestion(db, rec_id: str, admin_label: str) -> dict:
    """Admin reject flow: stamps the history row but does not touch
    any page body."""
    rec = await db.internal_link_history.find_one({"id": rec_id}, {"_id": 0})
    if not rec:
        return {"ok": False, "error": "not_found"}
    if rec.get("action") != ACTION_DRAFTED:
        return {"ok": False, "error": f"only drafted suggestions can be rejected (got {rec.get('action')})"}
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.internal_link_history.update_one(
        {"id": rec_id},
        {"$set": {
            "action": ACTION_REJECTED,
            "rejected_at": now_iso, "rejected_by": admin_label,
        }},
    )
    return {"ok": True}


async def revert_applied_suggestion(db, rec_id: str, admin_label: str) -> dict:
    """Admin revert flow: removes the inserted anchor from the
    source page body, flips the row to ``reverted``. Idempotent —
    calling revert on an already-reverted row is a no-op."""
    rec = await db.internal_link_history.find_one({"id": rec_id}, {"_id": 0})
    if not rec:
        return {"ok": False, "error": "not_found"}
    # True idempotency — calling revert on an already-reverted row is a
    # no-op rather than an error so admin double-clicks don't surface
    # confusing failures.
    if rec.get("action") == ACTION_REVERTED:
        return {"ok": True, "idempotent": True,
                "reverted_at": rec.get("reverted_at"),
                "reverted_by": rec.get("reverted_by")}
    if rec.get("action") != ACTION_AUTO_APPLIED:
        return {"ok": False, "error": f"only auto_applied rows can be reverted (got {rec.get('action')})"}
    sid = rec.get("source_page_id")
    tid = rec.get("target_page_id")
    if not sid or not tid:
        return {"ok": False, "error": "missing source/target id"}
    source = await db.seo_pages.find_one({"id": sid}, {"_id": 0})
    if not source:
        # Page is gone — still mark the row reverted so it falls out
        # of the active history; nothing to undo on the body.
        await db.internal_link_history.update_one(
            {"id": rec_id},
            {"$set": {"action": ACTION_REVERTED,
                      "reverted_at": datetime.now(timezone.utc).isoformat(),
                      "reverted_by": admin_label}},
        )
        return {"ok": True, "warning": "source page missing; row marked reverted only"}
    new_body, did = remove_anchor(source.get("content") or "", target_page_id=tid)
    if did:
        await _persist_body_update(db, source, new_body)
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.internal_link_history.update_one(
        {"id": rec_id},
        {"$set": {
            "action": ACTION_REVERTED,
            "reverted_at": now_iso, "reverted_by": admin_label,
        }},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Nightly maintenance pass
# ---------------------------------------------------------------------------
async def _top_traffic_pages(db, top_n: int) -> tuple[list[dict], str]:
    """Best-effort top-N traffic source. Uses the cloudflare_client
    helper when available; falls back to the most-recently-updated
    published pages so the loop still does useful work in dev / when
    the analytics token is missing.

    Returns (pages, source) where source is one of ``"cloudflare"`` or
    ``"recency_fallback"`` so the caller can log/observe whether the
    analytics path was actually exercised."""
    try:
        from cloudflare_client import get_top_pages_cf  # type: ignore
        # NB: helper signature is ``(days: int = 30, limit: int = 20)``;
        # pass ``limit`` keyword (NOT ``top_n``) — using the wrong kwarg
        # silently forces the recency fallback every night.
        rows = await get_top_pages_cf(limit=top_n) or []
        # Page-type suffixes that follow a topic slug on this site
        # (e.g. /<board>/<class>/<subject>/<topic>/mcqs). When the
        # last URL segment is one of these, the *previous* segment
        # is the actual ``topic_slug`` we want to look up.
        PAGE_TYPE_SUFFIXES = {
            "notes", "mcqs", "mcq", "flashcards", "pyq",
            "summary", "syllabus", "questions",
        }
        ids: list[str] = []
        for r in rows:
            # CF helper returns ``{"path": "/x/y", "views": N, ...}``.
            path = (r.get("path") or r.get("url") or "").split("?", 1)[0]
            slug_parts = [s for s in path.strip("/").split("/") if s]
            if not slug_parts:
                continue
            # Try the leaf first, then walk one segment back if it
            # was a page-type suffix — covers both /…/topic and
            # /…/topic/<page-type> URL shapes.
            candidates = [slug_parts[-1]]
            if len(slug_parts) >= 2 and slug_parts[-1].lower() in PAGE_TYPE_SUFFIXES:
                candidates.append(slug_parts[-2])
            doc = None
            for slug in candidates:
                doc = await db.seo_pages.find_one(
                    {"topic_slug": slug, "status": "published"},
                    {"_id": 0},
                )
                if doc:
                    break
            if doc and doc.get("id") not in ids:
                ids.append(doc.get("id"))
        if ids:
            docs: list[dict] = []
            for i in ids[:top_n]:
                d = await db.seo_pages.find_one({"id": i}, {"_id": 0})
                if d:
                    docs.append(d)
            if docs:
                return docs, "cloudflare"
    except Exception as exc:
        logger.warning("internal_linker: CF top-pages lookup failed → recency fallback (%s)", exc)
    # Fallback path: surfaces in nightly summary so prod can detect regressions.
    docs = await db.seo_pages.find(
        {"status": "published"}, {"_id": 0},
    ).sort("updated_at", -1).limit(top_n).to_list(top_n)
    return docs, "recency_fallback"


async def nightly_maintenance_pass(db, *, top_n: Optional[int] = None) -> dict:
    """Re-run the linker against the top-N highest-traffic pages.
    Returns a summary dict for logging / the admin status panel."""
    cfg = get_config()
    n = int(top_n if top_n is not None else cfg["nightly_top_n"])
    if n <= 0 or not cfg["enabled"]:
        return {"ran": False, "reason": "disabled or top_n=0"}
    pages, traffic_source = await _top_traffic_pages(db, n)
    auto = drafted = failed = 0
    for p in pages:
        rows = await propose_internal_links_for_page(db, p, source="nightly")
        for r in rows:
            a = r.get("action")
            if a == ACTION_AUTO_APPLIED:
                auto += 1
            elif a == ACTION_DRAFTED:
                drafted += 1
            elif a == ACTION_FAILED:
                failed += 1
    return {"ran": True, "pages_processed": len(pages),
            "auto_applied": auto, "drafted": drafted, "failed": failed,
            "traffic_source": traffic_source}


async def _internal_linker_loop(db) -> None:
    """Background worker. Sleeps ``nightly_idle_secs`` between cycles.

    Runs the maintenance pass once per UTC date by holding an atomic
    per-date marker in ``internal_link_budget`` (avoids running
    multiple times within the same day across leader fail-overs).

    Cross-replica dedup (Task #950): every replica may run this loop,
    but only the holder of the ``internal_linker_lease`` actually
    runs the maintenance pass. The per-date marker remains as a
    belt-and-braces guard against fail-overs mid-day. Followers stand
    down for the same ``nightly_idle_secs`` so they pick up leadership
    on the next cycle if the leader dies.
    """
    import background_lease as _bglease
    owner_id = _bglease.make_owner_id("internal-linker")
    lock_id = "internal_linker_lease"
    logger.info("internal_linker: nightly maintenance loop started")
    try:
        while True:
            try:
                cfg = get_config()
                if not cfg["enabled"]:
                    await asyncio.sleep(cfg["nightly_idle_secs"])
                    continue
                ttl_s = max(int(cfg["nightly_idle_secs"]) * 3, 3 * 3600)
                if not await _bglease.try_acquire_lease(
                    db, lock_id, owner_id, ttl_s,
                ):
                    # A peer replica holds the lease — back off for one
                    # full cycle so leader fail-over is picked up on
                    # the next iteration without N× hitting the upstream
                    # data sources (GA4, content embeddings, LLM).
                    await asyncio.sleep(cfg["nightly_idle_secs"])
                    continue
                today = _today_key()
                # Atomic CAS marker so leader fail-overs within the same
                # UTC day don't double-run the pass. The marker piggy-
                # backs on the budget doc (tiny, already exists).  When
                # two workers race on day-zero the loser raises
                # ``DuplicateKeyError`` — that just means the other
                # worker already claimed today's slot, so we move on.
                won = False
                try:
                    # IMPORTANT: this upsert may create today's budget doc
                    # *before* any auto-apply ever happens. We MUST seed
                    # ``auto_applied: 0`` here too, otherwise the later
                    # ``{auto_applied: {$lt: cap}}`` guard inside
                    # ``_consume_auto_budget`` won't match a missing field
                    # and every high-confidence proposal for the rest of
                    # the day silently downgrades to drafted.
                    res = await db.internal_link_budget.update_one(
                        {"_id": today, "nightly_ran_at": {"$exists": False}},
                        {
                            "$set": {
                                "nightly_ran_at": datetime.now(timezone.utc).isoformat(),
                            },
                            "$setOnInsert": {
                                "auto_applied": 0,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            },
                        },
                        upsert=True,
                    )
                    won = bool(
                        getattr(res, "modified_count", 0)
                        or getattr(res, "upserted_id", None)
                    )
                except DuplicateKeyError:
                    won = False
                if won:
                    summary = await nightly_maintenance_pass(db)
                    logger.info("internal_linker: nightly pass: %s", summary)
                await asyncio.sleep(cfg["nightly_idle_secs"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("internal_linker: nightly loop error: %s", exc)
                await asyncio.sleep(60)
    finally:
        try:
            await asyncio.shield(_bglease.release_lease(
                db, lock_id, owner_id,
            ))
        except Exception:
            pass
