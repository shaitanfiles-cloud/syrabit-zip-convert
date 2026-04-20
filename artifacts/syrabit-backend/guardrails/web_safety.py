"""Syrabit.ai — Kid-safe filter for web grounding results & reader output.

The educational browser surfaces text fetched from the open web. Even
with the educational allowlist, an article can mention adult themes,
self-harm, weapons, or graphic content. This module provides two
small, fast pure-Python filters that the reader and the grounded
answer pipeline call before user content is shown:

* `score_text_kid_safety(text)` — returns `(safe: bool, score: float, hits: list[str])`.
  `score` is 0.0 (clean) → 1.0 (dense unsafe terms); we treat anything
  over `KID_SAFE_THRESHOLD` as unsafe.
* `redact_text(text)` — replaces hits with `[redacted]` so we can still
  show partial context when desired.

The patterns are intentionally narrow and English-leaning. They are
not a replacement for a full content classifier; they exist to catch
the most common failure modes (adult sites that slip through the
allowlist, weapons-manufacturing instructions, self-harm encouragement)
and to be easy for operators to extend via env-driven extra patterns.
"""
from __future__ import annotations

import os
import re
import logging
from typing import Iterable

logger = logging.getLogger(__name__)

# Default threshold — number of distinct unsafe-term hits per 1000 words
# above which we mark content as unsafe. Tunable via env.
KID_SAFE_THRESHOLD = float(os.environ.get("KID_SAFE_THRESHOLD", "1.5"))

_BASE_PATTERNS: list[re.Pattern] = [
    # Adult / sexual
    re.compile(r"\b(porn|pornograph(y|ic)|xxx|nsfw|nudity|nudes?|hentai)\b", re.I),
    re.compile(r"\b(sex(ual)?\s+(act|abuse|assault|exploitation)|incest|bestiality)\b", re.I),
    re.compile(r"\b(escort\s+service|adult\s+(content|chat|webcam)|sugar\s+daddy)\b", re.I),
    # Self-harm / suicide
    re.compile(r"\b(how\s+to\s+(kill|hurt|cut)\s+(my|your)?\s*self)\b", re.I),
    re.compile(r"\b(suicide\s+method|painless\s+suicide|hanging\s+rope|overdose\s+method)\b", re.I),
    # Weapons / explosives manufacture
    re.compile(r"\b(how\s+to\s+(make|build|assemble)\s+(a\s+)?(bomb|pipe\s*bomb|grenade|firearm|gun\s+at\s+home))\b", re.I),
    re.compile(r"\b(homemade\s+(explosive|bomb|napalm|tnt|c[-\s]?4))\b", re.I),
    # Illegal drugs & manufacture
    re.compile(r"\b(synthesize\s+(meth|methamphetamine|fentanyl|cocaine|heroin)|drug\s+lab\s+setup)\b", re.I),
    # Hate speech / slurs (a deliberately tiny seed; operators can extend)
    re.compile(r"\b(n[i1]gg(er|a)|f[a@]gg[o0]t|k[i1]ke|c[h]ink)\b", re.I),
    # Gambling
    re.compile(r"\b(online\s+casino|sports\s+betting\s+tips|gambling\s+addiction\s+strategies?)\b", re.I),
]


def _extra_patterns() -> list[re.Pattern]:
    raw = os.environ.get("KID_SAFE_EXTRA_PATTERNS", "").strip()
    if not raw:
        return []
    out: list[re.Pattern] = []
    for line in raw.split("|||"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(re.compile(line, re.I))
        except re.error:
            logger.warning(f"[web_safety] ignored invalid extra pattern: {line!r}")
    return out


def score_text_kid_safety(text: str) -> tuple[bool, float, list[str]]:
    """Return (safe, density_score, distinct_matches)."""
    if not text or not isinstance(text, str):
        return True, 0.0, []
    sample = text[:30_000]
    word_count = max(1, len(sample.split()))
    hits: list[str] = []
    seen: set[str] = set()
    for pat in (_BASE_PATTERNS + _extra_patterns()):
        for m in pat.finditer(sample):
            tok = m.group(0).lower()
            if tok not in seen:
                seen.add(tok)
                hits.append(tok)
    density = (len(hits) / word_count) * 1000.0
    safe = density < KID_SAFE_THRESHOLD
    return safe, round(density, 3), hits


def redact_text(text: str, replacement: str = "[redacted]") -> str:
    if not text:
        return text
    out = text
    for pat in (_BASE_PATTERNS + _extra_patterns()):
        out = pat.sub(replacement, out)
    return out


def filter_web_results(results: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """Split web grounding results into (kept, dropped).

    Each input dict is expected to have `title`, `snippet`, and `url`.
    A result is dropped when title+snippet trips the kid-safe filter.
    Dropped items get a `_safety_hits` list so admins can audit.
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    for r in results or []:
        blob = " ".join([
            str(r.get("title", "")), str(r.get("snippet", "")),
            str(r.get("body", "")),
        ])
        safe, density, hits = score_text_kid_safety(blob)
        if safe:
            kept.append(r)
        else:
            dropped.append({**r, "_safety_density": density, "_safety_hits": hits[:6]})
    return kept, dropped


__all__ = [
    "KID_SAFE_THRESHOLD",
    "score_text_kid_safety", "redact_text", "filter_web_results",
]
