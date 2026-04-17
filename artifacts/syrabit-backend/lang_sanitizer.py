"""Syrabit.ai — Indic (Assamese) language leakage detection and sanitisation.

The Sarvam Indic chat models occasionally emit stray English fragments inside
otherwise-Assamese replies (e.g. "me uses", "ssible", "terms"). This module
provides:

  * `measure_leakage(text)` — diagnostic ratio of non-whitelisted Latin chars.
  * `sanitize_assamese(text, threshold=...)` — strip stray Latin runs when the
    leakage ratio exceeds the threshold, while preserving allowed Latin
    fragments (numbers, units, acronyms, proper nouns, code, math, URLs).

Behaviour and threshold are configurable via env so they can be tuned without
a redeploy:

  * `ASSAMESE_LEAK_THRESHOLD`   (float, default 0.08)
  * `ASSAMESE_LEAK_BEHAVIOUR`   ("strip" | "regenerate" | "off", default "strip")
"""
from __future__ import annotations

import os
import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

ASSAMESE_RE = re.compile(r"[\u0980-\u09FF]")
LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z'’\-]*")

_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")
_MATH_BLOCK_RE = re.compile(r"\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\([^)]+\\\)|\\\[[^\]]+\\\]")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")

_NUMERIC_RE = re.compile(r"^[A-Za-z]?\d+(?:[.,]\d+)*[A-Za-z%°]*$")
_UNIT_RE = re.compile(
    r"^(?:m|cm|mm|km|nm|µm|um|kg|g|mg|µg|ug|s|ms|min|hr|h|hz|khz|mhz|ghz|"
    r"w|kw|mw|n|pa|kpa|mpa|gpa|j|kj|mol|l|ml|°c|°f|°k|c|f|k|hp|psi|amp|a|v|"
    r"kv|mv|b|kb|mb|gb|tb|px|em|rem|pt|°|ev|kev|mev|gev|rad|deg)s?$",
    re.I,
)
_PROPER_NOUN_RE = re.compile(r"^[A-Z][A-Za-z]+$")
_ACRONYM_RE = re.compile(r"^[A-Z]{2,}(?:-?\d+[A-Za-z]?)?$")

# Common English words that *look* like proper nouns when capitalised at
# the start of a sentence ("This", "That", "Use", "Me", "It", …) but are
# not actually proper nouns. Whitelisting these would let real English
# leakage slip past the strip filter, so we explicitly deny them.
_COMMON_ENGLISH_DENYLIST = frozenset({
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "of",
    "in", "on", "at", "to", "from", "by", "for", "with", "as", "is",
    "are", "was", "were", "be", "been", "being", "am", "do", "does",
    "did", "have", "has", "had", "having", "will", "would", "shall",
    "should", "can", "could", "may", "might", "must", "this", "that",
    "these", "those", "it", "its", "he", "she", "they", "them", "his",
    "her", "their", "we", "us", "our", "you", "your", "i", "me", "my",
    "mine", "yours", "ours", "theirs", "use", "uses", "used", "using",
    "make", "makes", "made", "get", "gets", "got", "give", "gives",
    "given", "go", "goes", "went", "gone", "come", "comes", "came",
    "see", "sees", "saw", "seen", "know", "knows", "knew", "known",
    "think", "thinks", "thought", "say", "says", "said", "tell",
    "tells", "told", "ask", "asks", "asked", "find", "finds", "found",
    "look", "looks", "looked", "want", "wants", "wanted", "need",
    "needs", "needed", "try", "tries", "tried", "let", "lets", "put",
    "puts", "set", "sets", "run", "runs", "ran", "take", "takes",
    "took", "taken", "show", "shows", "showed", "shown", "good",
    "bad", "new", "old", "first", "last", "long", "short", "high",
    "low", "hot", "cold", "small", "large", "big", "little", "many",
    "much", "more", "less", "most", "least", "some", "any", "all",
    "every", "each", "no", "not", "yes", "very", "well", "also",
    "even", "still", "just", "only", "so", "than", "such", "what",
    "which", "who", "whom", "whose", "where", "when", "why", "how",
    "here", "there", "now", "then", "today", "yesterday", "tomorrow",
    "terms", "term", "thing", "things", "way", "ways", "time", "times",
    "year", "years", "day", "days", "month", "months", "week", "weeks",
    "people", "person", "man", "woman", "child", "children", "world",
})


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_str(name: str, default: str) -> str:
    val = os.getenv(name)
    return (val or default).strip().lower()


def get_threshold() -> float:
    return _env_float("ASSAMESE_LEAK_THRESHOLD", 0.08)


def get_behaviour() -> str:
    b = _env_str("ASSAMESE_LEAK_BEHAVIOUR", "strip")
    if b not in ("strip", "regenerate", "off"):
        return "strip"
    return b


def _is_allowed_latin_token(tok: str) -> bool:
    if not tok:
        return True
    if _NUMERIC_RE.match(tok):
        return True
    if _UNIT_RE.match(tok):
        return True
    if _ACRONYM_RE.match(tok):
        return True
    # Single uppercase letter (e.g. variable X, point A) — keep.
    if len(tok) == 1 and tok.isupper():
        return True
    # Capitalised proper noun — keep ONLY when it's at least 4 chars long
    # AND not a common English word in disguise (e.g. "This", "That", "Use").
    # Two-letter and three-letter title-case tokens are too risky — they are
    # almost always English function words ("Me", "It", "The", "And").
    if (
        _PROPER_NOUN_RE.match(tok)
        and len(tok) >= 4
        and tok.lower() not in _COMMON_ENGLISH_DENYLIST
    ):
        return True
    return False


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for rx in (_CODE_BLOCK_RE, _MATH_BLOCK_RE, _URL_RE):
        for m in rx.finditer(text):
            spans.append((m.start(), m.end()))
    spans.sort()
    return spans


def _in_spans(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    for s, e in spans:
        if s <= start and end <= e:
            return True
        if e <= start:
            continue
        if s >= end:
            break
    return False


def _strip_protected(text: str) -> str:
    out = _CODE_BLOCK_RE.sub(" ", text)
    out = _MATH_BLOCK_RE.sub(" ", out)
    out = _URL_RE.sub(" ", out)
    return out


def measure_leakage(text: str) -> dict:
    """Diagnostic info about Latin leakage inside an Assamese reply."""
    if not text:
        return {"ratio": 0.0, "has_assamese": False, "suspicious_tokens": [], "total": 0, "leaked": 0}
    stripped = _strip_protected(text)
    has_assamese = bool(ASSAMESE_RE.search(stripped))
    if not has_assamese:
        return {"ratio": 0.0, "has_assamese": False, "suspicious_tokens": [], "total": 0, "leaked": 0}
    total_chars = sum(1 for c in stripped if not c.isspace())
    if total_chars == 0:
        return {"ratio": 0.0, "has_assamese": True, "suspicious_tokens": [], "total": 0, "leaked": 0}
    leaked = 0
    susp: list[str] = []
    for m in LATIN_RUN_RE.finditer(stripped):
        tok = m.group(0)
        if _is_allowed_latin_token(tok):
            continue
        leaked += len(tok)
        susp.append(tok)
    return {
        "ratio": leaked / total_chars,
        "has_assamese": True,
        "suspicious_tokens": susp,
        "total": total_chars,
        "leaked": leaked,
    }


def _strip_suspicious_latin(text: str) -> str:
    spans = _protected_spans(text)
    out: list[str] = []
    last = 0
    for m in LATIN_RUN_RE.finditer(text):
        if _in_spans(spans, m.start(), m.end()):
            continue
        tok = m.group(0)
        if _is_allowed_latin_token(tok):
            continue
        out.append(text[last:m.start()])
        last = m.end()
    out.append(text[last:])
    cleaned = "".join(out)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([,.!?।])", r"\1", cleaned)
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def sanitize_assamese(text: str, threshold: float | None = None) -> Tuple[str, dict]:
    """Sanitise Assamese reply if leakage exceeds threshold.

    Returns (cleaned_text, diagnostics). When `action == "stripped"`, the
    caller should prefer `cleaned_text` over the original.
    """
    if not text:
        return text, {"ratio": 0.0, "action": "noop", "has_assamese": False, "suspicious_tokens": [], "total": 0, "leaked": 0}
    thr = threshold if threshold is not None else get_threshold()
    diag = measure_leakage(text)
    diag["action"] = "noop"
    diag["threshold"] = thr
    if not diag["has_assamese"] or diag["ratio"] <= thr:
        return text, diag
    cleaned = _strip_suspicious_latin(text)
    diag["action"] = "stripped"
    diag["cleaned_len"] = len(cleaned)
    return cleaned, diag


async def sanitize_assamese_with_optional_regenerate(
    raw: str,
    *,
    threshold: float | None = None,
    behaviour: str | None = None,
    regenerate_callable=None,
) -> Tuple[str, dict]:
    """Sanitise Assamese output, optionally retrying once via the LLM.

    `regenerate_callable` is an awaitable returning a fresh full reply
    string. It is only invoked when `behaviour == "regenerate"` and the
    initial leakage ratio exceeds the threshold. After regeneration the
    cleaner of the two replies (lower leakage ratio) is sanitised and
    returned. Diagnostics include `regenerated: bool` and `retry_ratio`.
    """
    behaviour = (behaviour or get_behaviour()).strip().lower()
    if behaviour == "off":
        diag = measure_leakage(raw)
        diag.update({"action": "noop", "threshold": threshold or get_threshold(),
                     "regenerated": False, "behaviour": behaviour})
        return raw, diag

    cleaned, diag = sanitize_assamese(raw, threshold=threshold)
    diag["regenerated"] = False
    diag["behaviour"] = behaviour
    if (
        behaviour == "regenerate"
        and diag.get("action") == "stripped"
        and regenerate_callable is not None
    ):
        try:
            retry_raw = await regenerate_callable()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning(f"[INDIC-SANITIZE] regenerate callable failed: {e}")
            retry_raw = None
        if retry_raw:
            retry_diag = measure_leakage(retry_raw)
            diag["retry_ratio"] = retry_diag["ratio"]
            if retry_diag["ratio"] < diag["ratio"]:
                cleaned, retry_clean_diag = sanitize_assamese(retry_raw, threshold=threshold)
                retry_clean_diag["regenerated"] = True
                retry_clean_diag["behaviour"] = behaviour
                retry_clean_diag["original_ratio"] = diag["ratio"]
                return cleaned, retry_clean_diag
    return cleaned, diag


__all__ = [
    "ASSAMESE_RE",
    "measure_leakage",
    "sanitize_assamese",
    "sanitize_assamese_with_optional_regenerate",
    "get_threshold",
    "get_behaviour",
]
