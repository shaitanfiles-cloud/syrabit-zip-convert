"""Tests for the internal-bot UA registry (Task #820).

The registry is the single source of truth for our self-identifying
bot User-Agents (sitemap self-checks, KV cache prewarm, RAG fetcher,
Google Suggest probe). Cloudflare bot analytics and our own per-UA
bot report rely on it to distinguish Syrabit-originated internal
traffic from real third-party bot crawls.

These tests pin:
  * Every per-call-site UA carries the canonical ``SyrabitInternal``
    marker so a single CF rule / log filter can match all of them.
  * The legacy distinct UA names (``SyrabitSEOHealth``,
    ``syrabit-prewarm``, ``SyrabitBot``, ``SyrabitSEOBot``) are still
    present verbatim — any pre-existing CF SBFM allowlist or log
    search keyed on them keeps working.
  * Every header factory injects the ``X-Syrabit-Internal: 1`` header
    alongside the UA. The CF WAF Custom Rule keys on this header.
  * ``is_internal_user_agent`` recognises every variant emitted by the
    factories AND returns False for real third-party bots so the
    per-UA bot report doesn't accidentally drop Googlebot / Bingbot.
"""
from __future__ import annotations

import sys
from pathlib import Path

# `internal_user_agents` has zero deps — no need for the deps stub or
# any of the test fixtures. Just put the backend on sys.path so the
# import resolves the same way it does in production.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from internal_user_agents import (  # noqa: E402
    GOOGLE_SUGGEST_USER_AGENT,
    INTERNAL_HEADER_NAME,
    INTERNAL_HEADER_VALUE,
    INTERNAL_UA_MARKER,
    INTERNAL_UA_TOKENS,
    PREWARM_USER_AGENT,
    RAG_FETCH_USER_AGENT,
    SEO_SELF_CHECK_USER_AGENT,
    WEB_CONTENT_USER_AGENT,
    google_suggest_headers,
    is_internal_user_agent,
    prewarm_headers,
    rag_fetch_headers,
    seo_self_check_headers,
    web_content_headers,
)


# ── Marker / token registry ─────────────────────────────────────────────

def test_internal_header_constants_are_stable():
    """If these change, the Cloudflare WAF Custom Rule documented in
    docs/CLOUDFLARE_INTERNAL_BOT_TAGGING.md MUST be updated in lockstep."""
    assert INTERNAL_HEADER_NAME == "X-Syrabit-Internal"
    assert INTERNAL_HEADER_VALUE == "1"
    assert INTERNAL_UA_MARKER == "SyrabitInternal"


def test_canonical_marker_present_in_every_ua():
    """Every per-call-site UA carries the shared marker so a single
    CF rule / log filter can identify all internal traffic."""
    for ua in (
        PREWARM_USER_AGENT,
        SEO_SELF_CHECK_USER_AGENT,
        WEB_CONTENT_USER_AGENT,
        GOOGLE_SUGGEST_USER_AGENT,
        RAG_FETCH_USER_AGENT,
    ):
        assert INTERNAL_UA_MARKER in ua, f"missing marker: {ua}"


def test_legacy_distinct_ua_names_preserved():
    """Any pre-existing Cloudflare SBFM allowlist or log search keyed
    on these substrings must keep working. Don't rename without
    auditing CF dashboard rules first."""
    assert "SyrabitSEOHealth/1.0" in SEO_SELF_CHECK_USER_AGENT
    assert "syrabit-prewarm/1.0" in PREWARM_USER_AGENT
    assert "SyrabitBot/1.0" in WEB_CONTENT_USER_AGENT
    assert "SyrabitBot/1.0" in RAG_FETCH_USER_AGENT
    assert "SyrabitSEOBot/1.0" in GOOGLE_SUGGEST_USER_AGENT


def test_internal_ua_tokens_are_lowercase():
    """`is_internal_user_agent` lower-cases the candidate UA before
    checking — so registry tokens must be lower-case too or the match
    silently fails."""
    for token in INTERNAL_UA_TOKENS:
        assert token == token.lower(), f"non-lowercase token: {token!r}"


def test_internal_ua_tokens_cover_marker():
    """The canonical marker MUST be in the token registry — that's how
    new internal UAs (which only need to carry the marker) get
    recognised by the per-UA report classifier."""
    assert INTERNAL_UA_MARKER.lower() in INTERNAL_UA_TOKENS


# ── is_internal_user_agent ──────────────────────────────────────────────

def test_is_internal_user_agent_recognises_every_factory_output():
    """Every UA emitted by a factory must round-trip through the
    classifier as `True`, otherwise the per-UA report would still
    bucket our own traffic as Googlebot / SyrabitBot / etc."""
    for ua in (
        PREWARM_USER_AGENT,
        SEO_SELF_CHECK_USER_AGENT,
        WEB_CONTENT_USER_AGENT,
        GOOGLE_SUGGEST_USER_AGENT,
        RAG_FETCH_USER_AGENT,
    ):
        assert is_internal_user_agent(ua), f"factory UA not recognised: {ua}"


def test_is_internal_user_agent_real_bots_pass_through():
    """Critical: real third-party bots must NOT be flagged as internal
    — otherwise the per-UA bot report would silently drop Googlebot,
    Bingbot, GPTBot etc. and the operator would see empty dashboards."""
    assert not is_internal_user_agent(
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    )
    assert not is_internal_user_agent("Mozilla/5.0 (compatible; bingbot/2.0)")
    assert not is_internal_user_agent("GPTBot/1.0")
    assert not is_internal_user_agent("Mozilla/5.0 Chrome/123 (humans)")


def test_is_internal_user_agent_handles_empty_and_none():
    assert not is_internal_user_agent(None)
    assert not is_internal_user_agent("")


def test_is_internal_user_agent_case_insensitive():
    assert is_internal_user_agent("FOO SYRABITINTERNAL BAR")
    assert is_internal_user_agent("foo syrabitseohealth bar")


def test_is_internal_user_agent_recognises_legacy_pretask820_strings():
    """Defence-in-depth: pre-Task-820 UAs (without the canonical
    marker) must still be recognised so any cached / replayed log
    entry from before this change still drops out of the per-UA
    report."""
    assert is_internal_user_agent(
        "Mozilla/5.0 (compatible; SyrabitSEOHealth/1.0; +https://syrabit.ai/api/seo/health)"
    )
    assert is_internal_user_agent(
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html) "
        "syrabit-prewarm/1.0"
    )
    assert is_internal_user_agent("Mozilla/5.0 (compatible; SyrabitBot/1.0; +https://syrabit.ai)")
    assert is_internal_user_agent("Mozilla/5.0 (compatible; SyrabitSEOBot/1.0)")


# ── Header factories ────────────────────────────────────────────────────

def _factory_outputs():
    return [
        ("seo_self_check_headers", seo_self_check_headers(), SEO_SELF_CHECK_USER_AGENT),
        ("prewarm_headers", prewarm_headers(), PREWARM_USER_AGENT),
        ("web_content_headers", web_content_headers(), WEB_CONTENT_USER_AGENT),
        ("google_suggest_headers", google_suggest_headers(), GOOGLE_SUGGEST_USER_AGENT),
        ("rag_fetch_headers", rag_fetch_headers(), RAG_FETCH_USER_AGENT),
    ]


def test_every_factory_sets_internal_header():
    """The CF WAF Custom Rule keys on `X-Syrabit-Internal: 1` — a
    factory that forgets the header would silently be classified as
    "unknown bot" by Cloudflare again."""
    for name, headers, _ in _factory_outputs():
        assert headers.get(INTERNAL_HEADER_NAME) == INTERNAL_HEADER_VALUE, (
            f"{name} dropped {INTERNAL_HEADER_NAME}"
        )


def test_every_factory_sets_correct_user_agent():
    for name, headers, expected_ua in _factory_outputs():
        assert headers.get("User-Agent") == expected_ua, (
            f"{name} returned wrong UA: {headers.get('User-Agent')!r}"
        )


def test_factory_outputs_are_independent_dicts():
    """Each call returns a fresh dict so a caller mutating the
    returned headers (e.g. adding a request-specific cookie) cannot
    poison subsequent calls."""
    a = seo_self_check_headers()
    a["X-Test-Mutation"] = "1"
    b = seo_self_check_headers()
    assert "X-Test-Mutation" not in b


def test_prewarm_headers_keep_googlebot_spoof_and_prewarm_flag():
    """The KV cache prewarm path deliberately spoofs Googlebot so the
    edge serves the bot HTML render path on cold-cache hit. Removing
    either signal would break the prewarm flow."""
    headers = prewarm_headers()
    assert "Googlebot" in headers["User-Agent"]
    assert headers.get("X-Syrabit-Prewarm") == "1"
    # And — critically — still flagged internal so it doesn't pollute
    # the Googlebot bucket in our per-UA report.
    assert is_internal_user_agent(headers["User-Agent"])


def test_seo_self_check_headers_accept_xml():
    """Sitemap probes need to accept XML so Cloudflare doesn't 406
    when the origin returns `Content-Type: application/xml`."""
    accept = seo_self_check_headers().get("Accept", "")
    assert "application/xml" in accept
