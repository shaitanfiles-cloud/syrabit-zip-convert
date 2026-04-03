"""
Syrabit.ai — Follow-up context tracking for lesson-by-lesson progression.

Detects follow-up patterns in user messages (e.g., "solve next", "5m",
chapter names) and maintains progression state so the system can continue
from where the student left off.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_FOLLOWUP_PATTERNS = [
    re.compile(r'^(?:solve\s+)?(?:next|continue|more|go\s+on|keep\s+going)$', re.I),
    re.compile(r'^solve\s+(\d+)\s*m(?:arks?)?$', re.I),
    re.compile(r'^(\d+)\s*m(?:arks?)?$', re.I),
    re.compile(r'^(?:show|give|do)\s+(?:the\s+)?(?:next|remaining|rest)$', re.I),
    re.compile(r'^(?:next|remaining)\s+(?:chapter|lesson|section|unit)s?$', re.I),
]


def detect_followup(query: str, conversation_meta: Optional[dict] = None) -> Optional[dict]:
    q = query.strip()
    if not q:
        return None

    followup_ctx = (conversation_meta or {}).get("followup_context")
    if not followup_ctx:
        return None

    prev_intent = followup_ctx.get("intent", "")
    if not prev_intent:
        return None
    remaining = followup_ctx.get("remaining", [])

    q_lower = q.lower().strip()

    for pattern in _FOLLOWUP_PATTERNS:
        match = pattern.match(q_lower)
        if match:
            mark_group = None
            if match.lastindex and match.lastindex >= 1:
                mark_group = match.group(1)

            next_item = remaining[0] if remaining else None
            return {
                "is_followup": True,
                "prev_intent": prev_intent,
                "mark_filter": mark_group,
                "next_item": next_item,
                "remaining": remaining,
                "completed": followup_ctx.get("completed", []),
            }

    if prev_intent in ("notes", "important_questions"):
        for item in remaining:
            if q_lower == item.lower() or q_lower in item.lower():
                return {
                    "is_followup": True,
                    "prev_intent": prev_intent,
                    "mark_filter": None,
                    "next_item": item,
                    "remaining": remaining,
                    "completed": followup_ctx.get("completed", []),
                }

    return None


def build_followup_context(
    intent: str,
    current_item: str = "",
    completed: Optional[list] = None,
    remaining: Optional[list] = None,
) -> dict:
    return {
        "intent": intent,
        "current_item": current_item,
        "completed": completed or [],
        "remaining": remaining or [],
    }


def merge_followup_into_query(
    original_query: str,
    followup_info: dict,
    subject_name: str = "",
    chapter_name: str = "",
) -> str:
    prev_intent = followup_info.get("prev_intent", "")
    next_item = followup_info.get("next_item", "")
    mark_filter = followup_info.get("mark_filter")

    if prev_intent == "pyq" and mark_filter:
        parts = []
        if subject_name:
            parts.append(subject_name)
        parts.append(f"solve {mark_filter} mark questions")
        if chapter_name:
            parts.append(f"from {chapter_name}")
        return " ".join(parts)

    if prev_intent == "notes" and next_item:
        parts = []
        if subject_name:
            parts.append(subject_name)
        parts.append(f"notes for {next_item}")
        return " ".join(parts)

    if prev_intent == "important_questions" and next_item:
        parts = []
        if subject_name:
            parts.append(subject_name)
        parts.append(f"important questions for {next_item}")
        return " ".join(parts)

    if next_item:
        return f"{next_item} {original_query}"

    return original_query
