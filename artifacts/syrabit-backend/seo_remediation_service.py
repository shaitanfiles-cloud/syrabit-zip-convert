"""Task #938 — closed-loop content remediation agent.

When the existing alerter detects ranking drops, sitemap regressions,
or 404 spikes, this module subscribes to the structured signals,
re-runs the existing Stage 1→3 pipeline against the affected page,
scores the new draft against the same quality gates a human approval
would, and either auto-republishes or files a draft for admin review.

A daily budget cap prevents a flapping detector from flooding
production; a 24h circuit breaker disables the loop when too many
recent attempts fall to draft (signalling the LLM pipeline itself is
producing weak output).

Public surface
--------------
* ``enqueue_remediation_signal(signal)`` — fire-and-forget pubsub
  entry point used by the alerter.
* ``_seo_remediation_loop()`` — long-running worker started from
  ``server.py`` under the leader gate.
* ``decide_action(...)`` / ``compute_quality_delta(...)`` — pure
  helpers exposed for unit tests.
* History collection: ``seo_remediation_history``
* Budget collection: ``seo_remediation_budget`` (one doc per UTC date)
* Circuit doc: ``seo_remediation_circuit`` (single doc id ``state``)
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

SIGNAL_QUEUE_MAXSIZE = 500
HISTORY_RETENTION_DAYS = 30

VALID_SIGNAL_KINDS = frozenset({
    "url_404_spike",
    "seo_health_degraded",
    "seo_health_critical",
    "orphan_page",
    "sitemap_regression",
    "manual_trigger",
})

ACTION_AUTO_REPUBLISHED = "auto_republished"
ACTION_DRAFTED = "drafted"
ACTION_SKIPPED_NO_IMPROVEMENT = "skipped_no_improvement"
ACTION_SKIPPED_OVER_BUDGET = "skipped_over_budget"
ACTION_SKIPPED_CIRCUIT_OPEN = "skipped_circuit_open"
ACTION_SKIPPED_NOT_FOUND = "skipped_page_not_found"
ACTION_FAILED = "failed"

VALID_ACTIONS = frozenset({
    ACTION_AUTO_REPUBLISHED,
    ACTION_DRAFTED,
    ACTION_SKIPPED_NO_IMPROVEMENT,
    ACTION_SKIPPED_OVER_BUDGET,
    ACTION_SKIPPED_CIRCUIT_OPEN,
    ACTION_SKIPPED_NOT_FOUND,
    ACTION_FAILED,
})


def get_config() -> dict:
    """Operator-tunable knobs. Re-read on every call so test
    monkeypatch on os.environ takes effect without process restart."""
    return {
        "auto_per_day": int(os.getenv("SEO_REMEDIATION_AUTOPUBLISH_PER_DAY", "5")),
        "draft_per_day": int(os.getenv("SEO_REMEDIATION_DRAFT_PER_DAY", "20")),
        # Min combined-score improvement to auto-republish (vs. just
        # demote-to-draft). Default +2 is conservative — combined is
        # 0-100, and a +2 swing typically reflects a real win in
        # GEO signals (answer-first / key-facts / citations).
        "min_improvement_delta": int(os.getenv("SEO_REMEDIATION_MIN_DELTA", "2")),
        # Circuit breaker: after >= MIN_ATTEMPTS in the rolling
        # window, if drafted-or-worse fraction >= TRIP_RATIO, open.
        "circuit_window_size": int(os.getenv("SEO_REMEDIATION_CIRCUIT_WINDOW", "10")),
        "circuit_trip_ratio": float(os.getenv("SEO_REMEDIATION_CIRCUIT_RATIO", "0.5")),
        "circuit_cooldown_hours": int(os.getenv("SEO_REMEDIATION_CIRCUIT_COOLDOWN_H", "24")),
        # Per-event fan-out cap so a 100-failing-URL spike snapshot
        # cannot enqueue 100 signals at once (would burn the daily
        # budget and trip the breaker on a single detector firing).
        "fanout_cap_per_event": int(os.getenv("SEO_REMEDIATION_FANOUT_CAP", "5")),
        # Worker poll backoff when queue is empty (sec).
        "idle_backoff_secs": float(os.getenv("SEO_REMEDIATION_IDLE_BACKOFF", "5")),
        # Master kill-switch — admins can disable the loop entirely
        # via env without restarting if they want a hot bypass.
        "enabled": os.getenv("SEO_REMEDIATION_ENABLED", "1") not in ("0", "false", "False", ""),
    }


# ---------------------------------------------------------------------------
# Signal queue (in-process pubsub)
# ---------------------------------------------------------------------------
_signal_queue: Optional[asyncio.Queue] = None


def _get_queue() -> asyncio.Queue:
    """Lazy queue construction — must happen inside the asyncio
    loop, so the loop binding is correct. Production callers always
    invoke from inside the FastAPI loop."""
    global _signal_queue
    if _signal_queue is None:
        _signal_queue = asyncio.Queue(maxsize=SIGNAL_QUEUE_MAXSIZE)
    return _signal_queue


def reset_queue_for_tests() -> None:
    """Drop the module-level queue so each test gets a fresh one
    bound to its event loop. Callers in production must NEVER use
    this — it would silently lose pending signals."""
    global _signal_queue
    _signal_queue = None


def enqueue_remediation_signal(signal: Mapping[str, Any]) -> bool:
    """Fire-and-forget entry point used by the alerter.

    Returns True on enqueue, False on drop (queue full or invalid).
    Never raises — the alerter must continue paging on-call even if
    the remediation pipeline is wedged.
    """
    if not isinstance(signal, Mapping):
        logger.warning("remediation: rejected non-mapping signal %r", type(signal))
        return False
    kind = signal.get("kind")
    if kind not in VALID_SIGNAL_KINDS:
        logger.warning("remediation: rejected unknown signal kind=%r", kind)
        return False
    enriched = dict(signal)
    enriched.setdefault("id", f"sig-{uuid.uuid4().hex[:10]}")
    enriched.setdefault("detected_at", datetime.now(timezone.utc).isoformat())
    try:
        q = _get_queue()
    except RuntimeError:
        # No running loop — caller is outside FastAPI (e.g. a sync
        # script). Drop quietly; not the alerter's job to bootstrap
        # the loop.
        logger.debug("remediation: no running loop, signal dropped")
        return False
    try:
        q.put_nowait(enriched)
        return True
    except asyncio.QueueFull:
        logger.warning(
            "remediation: signal queue full (max=%d), dropped kind=%s url=%s",
            SIGNAL_QUEUE_MAXSIZE, kind, enriched.get("url"),
        )
        return False


# ---------------------------------------------------------------------------
# Decision engine (pure functions, exposed for unit tests)
# ---------------------------------------------------------------------------
def compute_quality_delta(before: Mapping[str, Any] | None,
                          after: Mapping[str, Any] | None) -> dict:
    """Extract before/after combined scores from page docs and
    return ``{"before": int, "after": int, "delta": int}``. Missing
    or malformed scores degrade to 0 — the decision layer treats
    those as "no improvement" so a corrupted before-snapshot can
    never auto-republish a worse page by accident."""
    def _combined(doc: Mapping[str, Any] | None) -> int:
        if not doc:
            return 0
        # Prefer the canonical `combined_score` written by
        # _generate_single_page; fall back to the nested
        # quality.combined_score that older docs use.
        v = doc.get("combined_score")
        if isinstance(v, (int, float)):
            return int(v)
        q = doc.get("quality") or {}
        v = q.get("combined_score")
        if isinstance(v, (int, float)):
            return int(v)
        return 0
    b = _combined(before)
    a = _combined(after)
    return {"before": b, "after": a, "delta": a - b}


def decide_action(*, before: Mapping[str, Any] | None,
                  after: Mapping[str, Any] | None,
                  budget_mode: str,
                  config: Mapping[str, Any] | None = None) -> dict:
    """Decide what to do with a regenerated page.

    ``budget_mode`` is one of ``auto_republish_ok`` /
    ``draft_only`` / ``over_budget`` (returned by
    ``_consume_budget``). The decision honours both the budget and
    the score delta so that:

    - ``over_budget``       → SKIP entirely (revert).
    - ``draft_only``        → cap at draft regardless of how good
                              the new content is (we already hit
                              the auto-republish cap for today).
    - ``auto_republish_ok`` → upgrade to ``auto_republished`` only
                              if the new draft passes quality AND
                              the combined score improves by
                              ``min_improvement_delta`` or more,
                              else fall back to draft / skip.

    Returns ``{"action": <ACTION_*>, "delta": dict, "reason": str}``.
    """
    cfg = dict(config or get_config())
    delta = compute_quality_delta(before, after)
    after_status = (after or {}).get("status") or "unknown"

    if budget_mode == "over_budget":
        return {"action": ACTION_SKIPPED_OVER_BUDGET, "delta": delta,
                "reason": "daily auto + draft caps reached"}

    if budget_mode == "draft_only":
        # We already hit the auto-republish cap. File as draft
        # only if the new content does not regress at all — any
        # negative delta means we'd be replacing a working live
        # page with strictly worse content. The previous tolerance
        # of `delta >= -1` violated the snapshot-revert contract
        # (#938 acceptance criterion 3).
        if delta["delta"] >= 0:
            return {"action": ACTION_DRAFTED, "delta": delta,
                    "reason": "auto cap exhausted, filed as draft"}
        return {"action": ACTION_SKIPPED_NO_IMPROVEMENT, "delta": delta,
                "reason": f"new content regressed by {abs(delta['delta'])}; reverting"}

    # budget_mode == "auto_republish_ok"
    if after_status == "draft":
        # The new regen failed the existing publish threshold
        # (seo_engine self-decided). File as draft only if it's at
        # least non-worse than the live page.
        if delta["delta"] >= 0:
            return {"action": ACTION_DRAFTED, "delta": delta,
                    "reason": "below publish threshold, drafted"}
        return {"action": ACTION_SKIPPED_NO_IMPROVEMENT, "delta": delta,
                "reason": "draft scored worse than current live page"}

    # New content cleared the publish threshold.
    min_delta = int(cfg.get("min_improvement_delta", 2))
    if delta["delta"] >= min_delta:
        return {"action": ACTION_AUTO_REPUBLISHED, "delta": delta,
                "reason": f"combined score improved by {delta['delta']} (>= {min_delta})"}
    if delta["delta"] >= 0:
        # Marginal — keep humans in the loop for the close calls.
        return {"action": ACTION_DRAFTED, "delta": delta,
                "reason": f"marginal improvement (+{delta['delta']}), drafted for review"}
    return {"action": ACTION_SKIPPED_NO_IMPROVEMENT, "delta": delta,
            "reason": f"new content regressed by {abs(delta['delta'])} points"}


# ---------------------------------------------------------------------------
# Budget cap
# ---------------------------------------------------------------------------
def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def get_budget_status(db) -> dict:
    """Return today's spent counters + caps for the admin status panel."""
    cfg = get_config()
    doc = await db.seo_remediation_budget.find_one({"_id": _today_key()}) or {}
    return {
        "date": _today_key(),
        "auto_used": int(doc.get("auto_republished", 0)),
        "auto_cap": cfg["auto_per_day"],
        "draft_used": int(doc.get("drafted", 0)),
        "draft_cap": cfg["draft_per_day"],
    }


async def _peek_budget_mode(db) -> str:
    """Inspect today's budget without incrementing — the decision
    engine uses this to know whether to attempt auto-republish at
    all. The actual increment happens after the action is final
    so we don't burn budget on signals we end up skipping."""
    s = await get_budget_status(db)
    if s["auto_used"] < s["auto_cap"]:
        return "auto_republish_ok"
    if s["draft_used"] < s["draft_cap"]:
        return "draft_only"
    return "over_budget"


async def _record_budget_consumption(db, action: str) -> None:
    """Increment today's counter for actions that actually used
    budget. Skip-actions don't count (otherwise a flood of
    ``skipped_no_improvement`` signals could lock out a real
    fix later in the day)."""
    if action == ACTION_AUTO_REPUBLISHED:
        field = "auto_republished"
    elif action == ACTION_DRAFTED:
        field = "drafted"
    else:
        return
    await db.seo_remediation_budget.update_one(
        {"_id": _today_key()},
        {
            "$inc": {field: 1},
            "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()},
        },
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------
_CIRCUIT_DOC_ID = "state"


async def get_circuit_status(db) -> dict:
    """Return the current circuit-breaker state for admin display."""
    cfg = get_config()
    doc = await db.seo_remediation_circuit.find_one({"_id": _CIRCUIT_DOC_ID}) or {}
    disabled_until_iso = doc.get("disabled_until")
    is_open = False
    if disabled_until_iso:
        try:
            until = datetime.fromisoformat(disabled_until_iso.replace("Z", "+00:00"))
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            is_open = datetime.now(timezone.utc) < until
        except (ValueError, TypeError):
            is_open = False
    recent = doc.get("recent_attempts") or []
    drafted_or_worse = sum(
        1 for r in recent
        if r.get("action") in {ACTION_DRAFTED, ACTION_SKIPPED_NO_IMPROVEMENT, ACTION_FAILED}
    )
    return {
        "is_open": is_open,
        "disabled_until": disabled_until_iso if is_open else None,
        "window_size": cfg["circuit_window_size"],
        "trip_ratio": cfg["circuit_trip_ratio"],
        "recent_total": len(recent),
        "recent_drafted_or_worse": drafted_or_worse,
        "recent_ratio": (drafted_or_worse / len(recent)) if recent else 0.0,
    }


async def _is_circuit_open(db) -> bool:
    s = await get_circuit_status(db)
    return bool(s["is_open"])


async def _record_attempt_in_circuit(db, action: str) -> None:
    """Append the latest attempt to the rolling window and trip
    the breaker if the drafted-or-worse fraction crosses the
    threshold. Keeps the window at ``circuit_window_size``
    via ``$slice`` so the doc never grows unbounded."""
    cfg = get_config()
    window = int(cfg["circuit_window_size"])
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "action": action,
    }
    await db.seo_remediation_circuit.update_one(
        {"_id": _CIRCUIT_DOC_ID},
        {"$push": {"recent_attempts": {"$each": [entry], "$slice": -window}}},
        upsert=True,
    )
    # Re-read to evaluate the trip condition. Doing a separate read
    # is the safe pattern under Mongo's eventual ordering — the
    # post-update doc reflects the truncation.
    doc = await db.seo_remediation_circuit.find_one({"_id": _CIRCUIT_DOC_ID}) or {}
    recent = doc.get("recent_attempts") or []
    if len(recent) < window:
        return  # not enough data yet to trip
    drafted_or_worse = sum(
        1 for r in recent
        if r.get("action") in {ACTION_DRAFTED, ACTION_SKIPPED_NO_IMPROVEMENT, ACTION_FAILED}
    )
    ratio = drafted_or_worse / len(recent)
    # Strict ``>`` so the breaker trips when more than the
    # configured ratio is drafted-or-worse — at exactly the
    # threshold we give the loop one more cycle to recover. This
    # matches the #938 spec wording ("trips when >50% of last N").
    if ratio <= float(cfg["circuit_trip_ratio"]):
        return
    cooldown = int(cfg["circuit_cooldown_hours"])
    until = datetime.now(timezone.utc) + timedelta(hours=cooldown)
    await db.seo_remediation_circuit.update_one(
        {"_id": _CIRCUIT_DOC_ID},
        {"$set": {
            "disabled_until": until.isoformat(),
            "tripped_at": datetime.now(timezone.utc).isoformat(),
            "tripped_ratio": ratio,
        }},
        upsert=True,
    )
    logger.warning(
        "remediation: circuit breaker TRIPPED (drafted-or-worse %.0f%% over last %d), "
        "disabled until %s",
        ratio * 100, len(recent), until.isoformat(),
    )


async def reset_circuit(db) -> None:
    """Admin-callable: clear the cooldown and the rolling window
    so the loop resumes immediately. Used after the operator
    fixes whatever was producing weak output."""
    await db.seo_remediation_circuit.update_one(
        {"_id": _CIRCUIT_DOC_ID},
        {"$set": {"disabled_until": None, "recent_attempts": []}},
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Signal → page resolution
# ---------------------------------------------------------------------------
def _slugs_from_url(url: str) -> list[str]:
    """Split ``/board/class/subject/topic[/page_type]`` into its
    non-empty path segments. Handles trailing slash + query strings."""
    if not url:
        return []
    path = url.split("?", 1)[0].split("#", 1)[0]
    return [s for s in path.strip("/").split("/") if s]


async def _resolve_page_from_signal(db, signal: Mapping[str, Any]) -> Optional[dict]:
    """Find the seo_pages doc the signal is talking about.

    Resolution preference: explicit ``page_id`` > explicit
    ``topic_id`` + ``page_type`` > URL slug parsing. Returns the
    full doc (with `_id` stripped) or None when no match."""
    page_id = signal.get("page_id")
    if page_id:
        doc = await db.seo_pages.find_one({"id": page_id}, {"_id": 0})
        if doc:
            return doc

    topic_id = signal.get("topic_id")
    page_type = signal.get("page_type") or "notes"
    if topic_id:
        doc = await db.seo_pages.find_one(
            {"topic_id": topic_id, "page_type": page_type}, {"_id": 0})
        if doc:
            return doc

    url = signal.get("url") or ""
    parts = _slugs_from_url(url)
    if not parts:
        return None
    # URLs are /{board}/{class}/{subject}/{topic}[/page_type].
    # The last segment is either a page_type (when in PAGE_TYPES)
    # or the topic_slug itself (which defaults to `notes`).
    known_page_types = {"notes", "definition", "important-questions",
                        "mcqs", "examples", "faq"}
    if parts[-1] in known_page_types and len(parts) >= 2:
        topic_slug = parts[-2]
        page_type_inferred = parts[-1]
    else:
        topic_slug = parts[-1]
        page_type_inferred = "notes"

    query = {"topic_slug": topic_slug, "page_type": page_type_inferred}
    if len(parts) >= 4:
        # Add subject_slug to disambiguate same-topic-name across
        # different subjects (e.g. "introduction" appears in many).
        query["subject_slug"] = parts[-3] if parts[-1] in known_page_types else parts[-2]
    return await db.seo_pages.find_one(query, {"_id": 0})


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------
async def _record_history(db, signal: Mapping[str, Any], page: Mapping[str, Any] | None,
                          before_doc: Mapping[str, Any] | None,
                          after_doc: Mapping[str, Any] | None,
                          decision: Mapping[str, Any],
                          error: Optional[str] = None) -> dict:
    """Insert a row into ``seo_remediation_history`` capturing
    everything an admin needs to audit the agent's decision."""
    rec = {
        "id": f"rem-{uuid.uuid4().hex[:10]}",
        "signal_id": signal.get("id"),
        "signal_kind": signal.get("kind"),
        "signal_url": signal.get("url"),
        "signal_details": signal.get("details") or {},
        "detected_at": signal.get("detected_at"),
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "page_id": (page or {}).get("id"),
        "topic_id": (page or {}).get("topic_id"),
        "topic_title": (page or {}).get("topic_title"),
        "page_type": (page or {}).get("page_type"),
        "topic_slug": (page or {}).get("topic_slug"),
        "subject_slug": (page or {}).get("subject_slug"),
        "before_status": (before_doc or {}).get("status"),
        "after_status": (after_doc or {}).get("status"),
        "scores": decision.get("delta"),
        "action": decision.get("action"),
        "reason": decision.get("reason"),
        "error": error,
        "promoted_at": None,
    }
    await db.seo_remediation_history.insert_one(rec)
    rec.pop("_id", None)
    return rec


# ---------------------------------------------------------------------------
# Per-signal remediation
# ---------------------------------------------------------------------------
async def _restore_page_doc(db, page_id: str, before_doc: Mapping[str, Any]) -> None:
    """Revert a seo_pages doc to its pre-remediation snapshot. Used
    when the new draft is no improvement and we don't want to
    silently demote a live page. We exclude only the `_id` (Mongo
    immutable) and re-stamp `updated_at` so downstream cache-purge
    consumers see the change."""
    snapshot = {k: v for k, v in before_doc.items() if k != "_id"}
    snapshot["updated_at"] = datetime.now(timezone.utc).isoformat()
    from seo_writes import upsert_seo_page
    await upsert_seo_page(db, {"id": page_id}, snapshot)


async def _remediate_one(db, signal: Mapping[str, Any]) -> dict:
    """Process a single signal end-to-end. Returns the inserted
    history record (also returned by the manual trigger endpoint
    so admins can see the decision immediately)."""
    page = await _resolve_page_from_signal(db, signal)
    if not page:
        return await _record_history(
            db, signal, None, None, None,
            {"action": ACTION_SKIPPED_NOT_FOUND,
             "delta": {"before": 0, "after": 0, "delta": 0},
             "reason": "could not resolve page from signal"},
        )

    if await _is_circuit_open(db):
        return await _record_history(
            db, signal, page, page, None,
            {"action": ACTION_SKIPPED_CIRCUIT_OPEN,
             "delta": {"before": 0, "after": 0, "delta": 0},
             "reason": "circuit breaker open"},
        )

    budget_mode = await _peek_budget_mode(db)
    if budget_mode == "over_budget":
        return await _record_history(
            db, signal, page, page, None,
            {"action": ACTION_SKIPPED_OVER_BUDGET,
             "delta": {"before": 0, "after": 0, "delta": 0},
             "reason": "daily caps exhausted"},
        )

    before_snapshot = dict(page)

    # Lookup topic + hierarchy. seo_engine's _resolve_hierarchy is
    # the canonical builder used by the batch generator; reusing it
    # guarantees the regenerated page has the same syllabus context
    # the original generation had.
    topic = await db.topics.find_one({"id": page["topic_id"]}, {"_id": 0})
    if not topic:
        return await _record_history(
            db, signal, page, before_snapshot, None,
            {"action": ACTION_SKIPPED_NOT_FOUND,
             "delta": {"before": 0, "after": 0, "delta": 0},
             "reason": "topic doc missing for page"},
        )

    try:
        from seo_engine import _resolve_hierarchy, _generate_single_page
        hierarchy = await _resolve_hierarchy(topic)
        if not hierarchy:
            return await _record_history(
                db, signal, page, before_snapshot, None,
                {"action": ACTION_SKIPPED_NOT_FOUND,
                 "delta": {"before": 0, "after": 0, "delta": 0},
                 "reason": "hierarchy could not be resolved"},
            )
        new_page = await _generate_single_page(topic, page["page_type"], hierarchy)
    except Exception as exc:
        logger.exception("remediation: regeneration failed for page %s", page.get("id"))
        # Restore so a half-generated bad doc cannot persist.
        try:
            await _restore_page_doc(db, page["id"], before_snapshot)
        except Exception as restore_exc:
            logger.error("remediation: revert after failure also failed: %s", restore_exc)
        decision = {"action": ACTION_FAILED,
                    "delta": {"before": 0, "after": 0, "delta": 0},
                    "reason": f"pipeline error: {str(exc)[:200]}"}
        await _record_attempt_in_circuit(db, ACTION_FAILED)
        return await _record_history(
            db, signal, page, before_snapshot, None, decision, error=str(exc)[:500],
        )

    after_doc = new_page or await db.seo_pages.find_one(
        {"id": page["id"]}, {"_id": 0})
    decision = decide_action(
        before=before_snapshot, after=after_doc, budget_mode=budget_mode,
    )
    action = decision["action"]

    if action == ACTION_SKIPPED_NO_IMPROVEMENT:
        # Don't keep a regression on disk — restore the original
        # doc. Wrap so a failure here can't crash the worker mid-
        # decision; we still want to record the history row that
        # tells admins the page may need a manual recovery.
        try:
            await _restore_page_doc(db, page["id"], before_snapshot)
        except Exception as restore_exc:
            logger.error(
                "remediation: restore failed for page %s after regression: %s",
                page.get("id"), restore_exc,
            )
            decision = dict(decision)
            decision["reason"] = (
                f"{decision.get('reason','regressed')}; "
                f"RESTORE FAILED: {str(restore_exc)[:200]}"
            )
    elif action == ACTION_DRAFTED:
        # _generate_single_page already wrote the new doc; downgrade
        # it to draft if seo_engine had cleared it for publish but we
        # don't want it live yet (auto cap exhausted, or marginal).
        if (after_doc or {}).get("status") == "published":
            await db.seo_pages.update_one(
                {"id": page["id"]},
                {"$set": {
                    "status": "draft",
                    "in_sitemap": False,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
    # ACTION_AUTO_REPUBLISHED → leave the new doc as-is; seo_engine
    # has already published it and dispatched IndexNow fanout.

    await _record_budget_consumption(db, action)
    await _record_attempt_in_circuit(db, action)
    return await _record_history(db, signal, page, before_snapshot, after_doc, decision)


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------
async def _seo_remediation_loop():
    """Long-running worker started from server.py under the leader
    gate. Consumes signals one at a time so the LLM-bound pipeline
    never runs concurrently with itself (avoid blowing the
    OpenRouter QPS budget)."""
    from deps import db
    if db is None:
        logger.warning("remediation: deps.db is None, loop will not run")
        return
    logger.info("remediation: loop starting")
    queue = _get_queue()
    while True:
        cfg = get_config()
        if not cfg["enabled"]:
            await asyncio.sleep(cfg["idle_backoff_secs"])
            continue
        try:
            signal = await asyncio.wait_for(queue.get(), timeout=cfg["idle_backoff_secs"])
        except asyncio.TimeoutError:
            continue
        try:
            await _remediate_one(db, signal)
        except Exception:
            logger.exception("remediation: unhandled error processing signal %s", signal.get("id"))
        finally:
            queue.task_done()
