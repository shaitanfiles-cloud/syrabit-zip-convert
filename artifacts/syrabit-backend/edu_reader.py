"""Syrabit.ai — Educational reader/fetch service.

Given an allowlisted educational URL, fetch the page, run a lightweight
Readability-style extraction, sanitise the resulting HTML/text, detect
the language, and return clean article content with metadata.

Design goals
------------
* **Safe** — every URL passes through `edu_allowlist.is_allowed_url`
  *and* an SSRF check (no private IPs, http(s) only). robots.txt is
  consulted with a per-host TTL cache before fetching.
* **Cheap on repeat hits** — successful extractions are cached in Redis
  (`edu_reader:<sha256(url)>`) for 24h so the second fetch is sub-100ms.
* **Self-contained** — no extra dependencies beyond what
  `requirements.txt` already pins (`lxml`, `httpx`). The Readability
  algorithm here is a stripped-down implementation: drop scripts/nav/
  footer/aside, score each `<p>` by text density, return the densest
  cluster wrapped in clean HTML.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser

import httpx

from edu_allowlist import is_allowed_url, log_blocked_request
from deps import redis_client

logger = logging.getLogger(__name__)

USER_AGENT = "SyrabitEduReader/1.0 (+https://syrabit.ai/bot)"
READER_CACHE_PREFIX = "edu_reader:"
READER_CACHE_TTL = 24 * 3600
ROBOTS_CACHE_TTL = 6 * 3600

_FETCH_TIMEOUT = 6.0
_MAX_BYTES = 2_000_000  # 2 MB cap
_MAX_TEXT_CHARS = 60_000

_robots_cache: dict[str, tuple[float, RobotFileParser | None]] = {}

# Per-host concurrency limit (be polite to upstream sites).
_host_locks: dict[str, asyncio.Semaphore] = {}

# In-process metrics — surfaced via get_reader_stats().
_reader_metrics = {
    "fetches_ok": 0,
    "fetches_failed": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "blocked_allowlist": 0,
    "blocked_robots": 0,
    "blocked_too_large": 0,
}


def _get_host_lock(host: str) -> asyncio.Semaphore:
    sem = _host_locks.get(host)
    if sem is None:
        sem = asyncio.Semaphore(2)
        _host_locks[host] = sem
    return sem


def _cache_key(url: str) -> str:
    return READER_CACHE_PREFIX + hashlib.sha256(url.encode("utf-8")).hexdigest()


def _cache_get(url: str) -> Optional[dict]:
    if not redis_client:
        return None
    try:
        raw = redis_client.get(_cache_key(url))
        if raw:
            return json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except Exception as e:
        logger.debug(f"[edu_reader] cache_get failed: {e}")
    return None


def _cache_set(url: str, payload: dict) -> None:
    if not redis_client:
        return
    try:
        redis_client.set(_cache_key(url), json.dumps(payload, default=str), ex=READER_CACHE_TTL)
    except Exception as e:
        logger.debug(f"[edu_reader] cache_set failed: {e}")


_LANG_TOKENS = {
    "en": {"the", "and", "of", "to", "is", "in", "that", "with", "for"},
    "as": set(),  # script-detected below
    "hi": set(),
}


def _detect_language(text: str) -> str:
    """Cheap Unicode-block based language detector.

    Returns 'as' for Assamese (Bengali script + ৰ ৱ), 'hi' for
    Devanagari, otherwise 'en'. Good enough for telemetry; we don't
    pull in a 10MB dictionary just to label the reader output.
    """
    if not text:
        return "en"
    sample = text[:4000]
    bn = sum(1 for c in sample if "\u0980" <= c <= "\u09FF")
    dev = sum(1 for c in sample if "\u0900" <= c <= "\u097F")
    total = max(1, sum(1 for c in sample if c.isalpha()))
    if bn / total > 0.25:
        # Distinguish Assamese from Bengali via the two letters that only
        # Assamese uses: ৰ (U+09F0) and ৱ (U+09F1).
        if any(c in sample for c in ("\u09F0", "\u09F1")):
            return "as"
        return "bn"
    if dev / total > 0.25:
        return "hi"
    return "en"


# ───────────────────────── robots.txt ─────────────────────────

async def _fetch_robots(host: str, scheme: str) -> RobotFileParser | None:
    cached = _robots_cache.get(host)
    now = time.time()
    if cached and (now - cached[0]) < ROBOTS_CACHE_TTL:
        return cached[1]
    rp = RobotFileParser()
    robots_url = f"{scheme}://{host}/robots.txt"
    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
            resp = await client.get(robots_url, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200 and resp.text:
                rp.parse(resp.text.splitlines())
            else:
                # Per RFC 9309: when robots is unreachable / 4xx, default
                # is to allow. We mirror that.
                rp = None
    except Exception as e:
        logger.debug(f"[edu_reader] robots fetch failed for {host}: {e}")
        rp = None
    _robots_cache[host] = (now, rp)
    return rp


async def _robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    rp = await _fetch_robots(host, parsed.scheme or "https")
    if rp is None:
        return True  # treat missing/unreachable robots as allow
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


# ───────────────────────── Readability-lite ─────────────────────────

_BLOCK_TAGS = {"script", "style", "nav", "footer", "header", "aside",
               "form", "noscript", "iframe", "svg", "button"}
_KEEP_TAGS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "pre", "code", "td", "th"}


def _strip_tree(root) -> None:
    from lxml import etree
    for tag in _BLOCK_TAGS:
        for el in root.iter(tag):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
    # Drop comments
    for el in list(root.iter(etree.Comment)):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)


def _text_density(el) -> int:
    text = "".join(el.itertext()) or ""
    return len(re.sub(r"\s+", " ", text).strip())


def _readability_extract(html: str, base_url: str) -> dict:
    from lxml import html as lxml_html
    if not html or len(html) < 200:
        return {"title": "", "html": "", "text": "", "byline": "", "lead_image": ""}
    try:
        doc = lxml_html.fromstring(html)
    except Exception as e:
        logger.debug(f"[edu_reader] lxml parse failed: {e}")
        return {"title": "", "html": "", "text": "", "byline": "", "lead_image": ""}

    # Title
    title = ""
    t_el = doc.find(".//title")
    if t_el is not None and t_el.text:
        title = re.sub(r"\s+", " ", t_el.text).strip()
    og_title = doc.xpath('//meta[@property="og:title"]/@content')
    if og_title and og_title[0]:
        title = re.sub(r"\s+", " ", str(og_title[0])).strip() or title

    # Byline / author
    byline = ""
    for xp in (
        '//meta[@name="author"]/@content',
        '//meta[@property="article:author"]/@content',
        '//*[@rel="author"]/text()',
    ):
        vals = doc.xpath(xp)
        if vals:
            byline = re.sub(r"\s+", " ", str(vals[0])).strip()[:200]
            if byline:
                break

    # Lead image
    lead_image = ""
    og_img = doc.xpath('//meta[@property="og:image"]/@content')
    if og_img and og_img[0]:
        try:
            lead_image = urljoin(base_url, str(og_img[0]).strip())
        except Exception:
            lead_image = ""

    _strip_tree(doc)

    # Score every <p> by text length; pick the parent that aggregates the
    # highest combined density (classic Readability heuristic, simplified).
    candidates: dict = {}
    for p in doc.iter("p"):
        density = _text_density(p)
        if density < 25:
            continue
        parent = p.getparent()
        if parent is None:
            continue
        candidates[parent] = candidates.get(parent, 0) + density + 25

    if not candidates:
        # Fallback: use <body> directly.
        body = doc.find(".//body")
        winner = body if body is not None else doc
    else:
        winner = max(candidates, key=candidates.get)

    # Build sanitized HTML from winner: keep only safe block tags.
    parts_html: list[str] = []
    parts_text: list[str] = []
    for el in winner.iter():
        tag = (el.tag or "").lower() if isinstance(el.tag, str) else ""
        if tag not in _KEEP_TAGS:
            continue
        text = "".join(el.itertext()) or ""
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if tag in ("h1", "h2", "h3", "h4"):
            parts_html.append(f"<{tag}>{_html_escape(text)}</{tag}>")
            parts_text.append(text)
        elif tag == "li":
            parts_html.append(f"<li>{_html_escape(text)}</li>")
            parts_text.append(f"• {text}")
        elif tag == "pre" or tag == "code":
            parts_html.append(f"<pre><code>{_html_escape(text)}</code></pre>")
            parts_text.append(text)
        else:
            parts_html.append(f"<p>{_html_escape(text)}</p>")
            parts_text.append(text)

    clean_html = "\n".join(parts_html)[:_MAX_TEXT_CHARS * 2]
    plain_text = "\n\n".join(parts_text)[:_MAX_TEXT_CHARS]

    return {
        "title": title,
        "html": clean_html,
        "text": plain_text,
        "byline": byline,
        "lead_image": lead_image,
    }


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&#39;"))


# ───────────────────────── Public API ─────────────────────────

async def fetch_and_extract(
    url: str,
    *,
    actor: str = "",
    ip_hash: str = "",
    bypass_cache: bool = False,
) -> dict:
    """Fetch `url`, extract clean article content, return a structured payload.

    Result shape::

        {"ok": True,
         "url": <final url after redirects>,
         "domain": <host>,
         "title": str, "byline": str, "lead_image": str,
         "html": <sanitised html>, "text": <plain text>,
         "language": "en"|"as"|"hi"|"bn",
         "char_count": int, "word_count": int,
         "fetched_at": <unix ts>, "from_cache": bool,
         "elapsed_ms": int}

    On failure::

        {"ok": False, "error": <code>, "detail": <message>, "url": url}
    """
    t0 = time.perf_counter()
    if not bypass_cache:
        cached = _cache_get(url)
        if cached:
            _reader_metrics["cache_hits"] += 1
            cached["from_cache"] = True
            cached["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
            return cached
        _reader_metrics["cache_misses"] += 1

    allowed, reason = await is_allowed_url(url)
    if not allowed:
        _reader_metrics["blocked_allowlist"] += 1
        await log_blocked_request(url, reason, actor=actor, ip_hash=ip_hash)
        return {"ok": False, "error": "not_allowed", "detail": reason, "url": url}

    if not await _robots_allows(url):
        _reader_metrics["blocked_robots"] += 1
        await log_blocked_request(url, "robots_disallow", actor=actor, ip_hash=ip_hash)
        return {"ok": False, "error": "robots_disallow", "detail": "robots.txt forbids this path", "url": url}

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    sem = _get_host_lock(host)

    async with sem:
        try:
            async with httpx.AsyncClient(
                timeout=_FETCH_TIMEOUT,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
                    "Accept-Language": "en-IN,en;q=0.9",
                },
            ) as client:
                resp = await client.get(url)
        except httpx.TimeoutException:
            _reader_metrics["fetches_failed"] += 1
            return {"ok": False, "error": "timeout", "detail": f"upstream did not respond within {_FETCH_TIMEOUT}s", "url": url}
        except Exception as e:
            _reader_metrics["fetches_failed"] += 1
            return {"ok": False, "error": "fetch_failed", "detail": str(e)[:200], "url": url}

    final_url = str(resp.url)
    # Re-check the post-redirect URL — defends against open redirects.
    allowed_final, reason_final = await is_allowed_url(final_url)
    if not allowed_final:
        _reader_metrics["blocked_allowlist"] += 1
        await log_blocked_request(final_url, f"redirect_{reason_final}", actor=actor, ip_hash=ip_hash)
        return {"ok": False, "error": "redirect_not_allowed", "detail": reason_final, "url": final_url}

    if resp.status_code != 200:
        _reader_metrics["fetches_failed"] += 1
        return {"ok": False, "error": f"http_{resp.status_code}", "detail": f"upstream returned {resp.status_code}", "url": final_url}

    ctype = (resp.headers.get("content-type") or "").lower()
    if "html" not in ctype and "xml" not in ctype and ctype:
        _reader_metrics["fetches_failed"] += 1
        return {"ok": False, "error": "unsupported_content_type", "detail": ctype[:80], "url": final_url}

    body = resp.content
    if len(body) > _MAX_BYTES:
        _reader_metrics["blocked_too_large"] += 1
        return {"ok": False, "error": "too_large", "detail": f"{len(body)} bytes > {_MAX_BYTES}", "url": final_url}

    try:
        html_text = body.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        html_text = body.decode("utf-8", errors="replace")

    extracted = _readability_extract(html_text, base_url=final_url)
    if not extracted["text"] or len(extracted["text"]) < 80:
        _reader_metrics["fetches_failed"] += 1
        return {"ok": False, "error": "extraction_failed", "detail": "no readable content", "url": final_url}

    final_host = (urlparse(final_url).hostname or "").lower()
    payload = {
        "ok": True,
        "url": final_url,
        "domain": final_host,
        "title": extracted["title"],
        "byline": extracted["byline"],
        "lead_image": extracted["lead_image"],
        "html": extracted["html"],
        "text": extracted["text"],
        "language": _detect_language(extracted["text"]),
        "char_count": len(extracted["text"]),
        "word_count": len(extracted["text"].split()),
        "fetched_at": time.time(),
        "from_cache": False,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }
    _reader_metrics["fetches_ok"] += 1
    _cache_set(url, payload)
    if final_url != url:
        _cache_set(final_url, payload)
    return payload


def get_reader_stats() -> dict:
    total = _reader_metrics["cache_hits"] + _reader_metrics["cache_misses"]
    hit_rate = (_reader_metrics["cache_hits"] / total * 100) if total else 0.0
    return {**_reader_metrics, "hit_rate_pct": round(hit_rate, 1)}


__all__ = [
    "USER_AGENT", "READER_CACHE_PREFIX", "READER_CACHE_TTL",
    "fetch_and_extract", "get_reader_stats",
]
