"""Single source of truth for Syrabit's *own* internal bot User-Agents (Task #820).

Several backend processes hit syrabit.ai through Cloudflare with
self-identifying User-Agents:

  * sitemap self-checks / deep-scans  (`SyrabitSEOHealth/1.0`)
  * KV cache pre-warm                 (`syrabit-prewarm/1.0`,
                                       deliberately spoofs Googlebot
                                       so the edge serves the bot HTML
                                       render path on cold-cache hit)
  * RAG / web-content fetcher         (`SyrabitBot/1.0`)
  * Google Suggest probe              (`SyrabitSEOBot/1.0`)

Until this module existed every call-site duplicated its own UA string,
which made Cloudflare bot analytics file each one as a separate
"unknown bot" — making it impossible to distinguish our own internal
traffic from real third-party bot crawls when reading dashboards or
investigating spikes (see Task #820).

This module:

  * Names the canonical UA per call-site so other code imports
    constants instead of typing literals. Every UA carries the shared
    ``SyrabitInternal`` token so a single CF rule / log filter can
    match all of them without enumerating each variant.
  * Records every internal UA token in :data:`INTERNAL_UA_TOKENS` so
    analytics code can drop / label them in one place.
  * Provides ready-made header dicts (``*_headers()`` helpers) that
    always include the ``X-Syrabit-Internal: 1`` header alongside the
    UA. The matching Cloudflare WAF Custom Rule (see
    ``docs/CLOUDFLARE_INTERNAL_BOT_TAGGING.md``) keys on this header so
    the operator does not have to maintain a long substring list in
    the CF dashboard. The header is the long-term canonical tag —
    ``X-Syrabit-Internal: 1`` is what Cloudflare and downstream
    analytics should match on. The UA-token list is defence-in-depth
    so a forgotten header still gets caught.
  * Exposes :func:`is_internal_user_agent` so our own per-UA bot-report
    classifier can drop self-checks before they get bucketed as
    Googlebot — the prewarm UA intentionally spoofs Googlebot to seed
    the edge ``BOT_HTML_CACHE``, which would otherwise inflate
    Googlebot's count by every regenerate-then-prewarm cycle.

When adding a new internal bot:

  1. Add its UA constant + header factory here. Include the
     ``SyrabitInternal`` token in the UA string so the canonical
     marker travels with it.
  2. If the new UA introduces a brand-new distinguishing substring
     (i.e. one not already covered by ``syrabitinternal``), append it
     to :data:`INTERNAL_UA_TOKENS` in lower-case.
  3. Update ``docs/CLOUDFLARE_INTERNAL_BOT_TAGGING.md`` if the
     dashboard CF rule needs adjustment (most won't — the header
     covers them).
"""
from __future__ import annotations


# ── Header-based identifier ─────────────────────────────────────────────
# Every internal request carries this header alongside the UA. The
# Cloudflare WAF Custom Rule documented in
# ``docs/CLOUDFLARE_INTERNAL_BOT_TAGGING.md`` matches on the header so
# the UA list does not need to be maintained inside Cloudflare too.
INTERNAL_HEADER_NAME = "X-Syrabit-Internal"
INTERNAL_HEADER_VALUE = "1"

# Shared canonical token baked into every internal UA below. Anything
# downstream (CF rules, log greps, classifiers) that wants to recognise
# *all* current and future Syrabit-originated internal traffic in one
# pattern should match this token rather than enumerating the per-bot
# variants.
INTERNAL_UA_MARKER = "SyrabitInternal"


# ── Per-call-site UA constants ──────────────────────────────────────────
#
# Existing UA names (`SyrabitSEOHealth`, `syrabit-prewarm`, `SyrabitBot`,
# `SyrabitSEOBot`) are PRESERVED verbatim so any pre-existing
# Cloudflare Super-Bot-Fight-Mode allowlist or log search keyed on them
# keeps working. The only addition is the trailing ``SyrabitInternal``
# marker — appended inside the existing parenthesised comment so the
# UA still parses as a standard ``Mozilla/5.0 (compatible; Foo/1.0; +url)``
# token by the bot-detection libraries that don't tolerate trailing
# free-text.

PREWARM_USER_AGENT = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html; "
    f"{INTERNAL_UA_MARKER}) syrabit-prewarm/1.0"
)

SEO_SELF_CHECK_USER_AGENT = (
    "Mozilla/5.0 (compatible; SyrabitSEOHealth/1.0; "
    f"+https://syrabit.ai/api/seo/health; {INTERNAL_UA_MARKER})"
)

WEB_CONTENT_USER_AGENT = (
    "Mozilla/5.0 (compatible; SyrabitBot/1.0; "
    f"+https://syrabit.ai/bots; {INTERNAL_UA_MARKER})"
)

GOOGLE_SUGGEST_USER_AGENT = (
    "Mozilla/5.0 (compatible; SyrabitSEOBot/1.0; "
    f"+https://syrabit.ai/bots; {INTERNAL_UA_MARKER})"
)

# Lightweight RAG fetcher (kept distinct from web_content so log-grep
# against rag.py failures stays specific). Same SyrabitBot family; the
# trailing ``component=rag`` tag is for log triage only.
RAG_FETCH_USER_AGENT = (
    "Mozilla/5.0 (compatible; SyrabitBot/1.0; "
    f"+https://syrabit.ai/bots; {INTERNAL_UA_MARKER}; component=rag)"
)


# ── Token registry (lower-cased substring match) ────────────────────────
#
# Keep these lower-case — :func:`is_internal_user_agent` lower-cases the
# candidate UA before checking. The shared ``syrabitinternal`` token is
# listed first because it is the long-term canonical marker any future
# internal UA will carry; the legacy distinct UAs are listed for
# defence-in-depth in case something downstream still emits the
# pre-Task-820 strings (e.g. cached responses with stale ``X-Forwarded-UA``
# logs being replayed).
INTERNAL_UA_TOKENS: tuple[str, ...] = (
    INTERNAL_UA_MARKER.lower(),  # "syrabitinternal" — canonical marker
    "syrabitseohealth",          # sitemap self-check / deep-scan
    "syrabit-prewarm",           # bot KV cache prewarm
    "syrabitseobot",             # google-suggest / SEO probe
    "syrabitbot",                # rag / web_content fetcher
)


def is_internal_user_agent(ua: str | None) -> bool:
    """Return ``True`` iff ``ua`` matches any registered internal-bot token.

    Used by per-UA analytics to exclude our own self-checks from the
    Googlebot bucket — the prewarm UA intentionally spoofs Googlebot
    to populate the edge ``BOT_HTML_CACHE``, which would otherwise
    inflate Googlebot's count by every regenerate-then-prewarm cycle.
    """
    if not ua:
        return False
    low = ua.lower()
    return any(token in low for token in INTERNAL_UA_TOKENS)


# ── Header factories ────────────────────────────────────────────────────
# Every internal call-site builds its outbound headers via one of these
# so the ``X-Syrabit-Internal`` header travels with the UA in lock-step.
# The Cloudflare WAF Custom Rule keys on the header so the operator
# does not have to maintain a long UA-substring list inside Cloudflare.

def _with_internal_header(headers: dict[str, str]) -> dict[str, str]:
    out = dict(headers)
    out[INTERNAL_HEADER_NAME] = INTERNAL_HEADER_VALUE
    return out


def seo_self_check_headers() -> dict[str, str]:
    """Headers used by ``seo_health_check`` and ``_deep_scan_sitemap``.

    The default ``python-httpx`` UA is classified by Cloudflare's Super
    Bot Fight Mode as "definitely automated" and served the 403 managed
    challenge — which previously made every self-probe report HTTP 403
    and the SEO health endpoint permanently report ``status=critical``.
    This is NOT a security bypass — sitemaps and SPA pages are public;
    the UA simply identifies our own self-checks at the edge so SBFM
    does not falsely flag them.
    """
    return _with_internal_header({
        "User-Agent": SEO_SELF_CHECK_USER_AGENT,
        "Accept": "application/xml,text/html;q=0.9,*/*;q=0.8",
    })


def prewarm_headers() -> dict[str, str]:
    """Headers used by ``prewarm_bot_cache``.

    Spoofs Googlebot deliberately so the edge serves the bot HTML
    render path on cold-cache hit (see notes in
    ``routes/bot_discovery.py``). The ``X-Syrabit-Internal: 1`` header
    + ``SyrabitInternal`` UA token still let Cloudflare and our own
    analytics distinguish these from real Googlebot traffic.
    """
    return _with_internal_header({
        "User-Agent": PREWARM_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-IN,en;q=0.9,as;q=0.8",
        "X-Syrabit-Prewarm": "1",
    })


def web_content_headers() -> dict[str, str]:
    """Headers used by the RAG / web-content fetcher in
    ``web_content.py::_FETCH_HEADERS``."""
    return _with_internal_header({
        "User-Agent": WEB_CONTENT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })


def google_suggest_headers() -> dict[str, str]:
    """Headers used by ``google_suggest_client.py::_suggest_get``."""
    return _with_internal_header({
        "User-Agent": GOOGLE_SUGGEST_USER_AGENT,
    })


def rag_fetch_headers() -> dict[str, str]:
    """Headers used by ``rag.py`` for arbitrary URL fetches via
    ``safe_get_with_redirects``. Distinct from
    :func:`web_content_headers` only in the ``component=rag`` UA tag so
    log-grep against rag failures stays specific."""
    return _with_internal_header({
        "User-Agent": RAG_FETCH_USER_AGENT,
    })


__all__ = (
    "INTERNAL_HEADER_NAME",
    "INTERNAL_HEADER_VALUE",
    "INTERNAL_UA_MARKER",
    "INTERNAL_UA_TOKENS",
    "PREWARM_USER_AGENT",
    "SEO_SELF_CHECK_USER_AGENT",
    "WEB_CONTENT_USER_AGENT",
    "GOOGLE_SUGGEST_USER_AGENT",
    "RAG_FETCH_USER_AGENT",
    "is_internal_user_agent",
    "seo_self_check_headers",
    "prewarm_headers",
    "web_content_headers",
    "google_suggest_headers",
    "rag_fetch_headers",
)
