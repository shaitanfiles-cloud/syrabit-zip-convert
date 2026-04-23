"""Pin the backend's AI-discoverability policy so accidental edits fail CI.

Complements `scripts/smoke_ai_discoverability.sh` (which hits production).
This module runs fully offline by parsing the literal `serve_robots_txt`
handler body out of `server.py` and the bot-UA regexes out of `utils.py`.
It catches regressions BEFORE deploy; the smoke script catches them AFTER
(edge / CF dashboard can still diverge from the backend).

Policy decisions locked in here (see server.py:1444-1457 for rationale):
  * GPTBot is the ONLY bot with a blanket ``Disallow: /`` — it's OpenAI's
    training-only crawler and contributes no citation traffic.
  * Answer / citation bots (OAI-SearchBot, ChatGPT-User, PerplexityBot,
    ClaudeBot, Google-Extended, Applebot-Extended, Meta-ExternalAgent)
    must be ``Allow: /`` — these drive search/answer traffic.
  * Training-only bots (CCBot, anthropic-ai, Cohere-ai, Bytespider,
    Amazonbot, YouBot, Diffbot, PetalBot, AhrefsBot, SemrushBot,
    FacebookBot) must be ``Allow: /`` — product decision: maximum LLM
    reach into open-source corpora (Llama, Mistral, Doubao, …).

If you're intentionally changing the policy, update both (a) the handler
in ``server.py`` and (b) the ANSWER_BOTS / TRAINING_BOTS lists below.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
SERVER_FILE = BACKEND_DIR / "server.py"
UTILS_FILE = BACKEND_DIR / "utils.py"


# ── Canonical policy lists ──────────────────────────────────────────────
# Kept here (not imported from server.py) so a typo'd rename in server.py
# still shows up as a test failure rather than silently passing.
ANSWER_BOTS: tuple[str, ...] = (
    "OAI-SearchBot",
    "ChatGPT-User",
    "PerplexityBot",
    "ClaudeBot",
    "Google-Extended",
    "Applebot-Extended",
    "Meta-ExternalAgent",
)

TRAINING_BOTS_ALLOWED: tuple[str, ...] = (
    "CCBot",
    "anthropic-ai",
    "Cohere-ai",
    "Bytespider",
    "Amazonbot",
    "YouBot",
    "Diffbot",
    "PetalBot",
    "AhrefsBot",
    "SemrushBot",
    "FacebookBot",
)

# Only this UA should have a blanket ``Disallow: /``. Any other blanket
# block is a regression (either a copy-paste error or an untracked policy
# change).
BLOCKED_BOTS: tuple[str, ...] = ("GPTBot",)

# UAs that MUST appear in `_SEARCH_BOT_UA_RE` so `BotRenderMiddleware`
# serves them prerendered HTML once they reach origin. Derived from the
# answer-bot list above (the ones we WANT to see our content) plus the
# two primary search crawlers. Lowercased for case-insensitive match.
SEARCH_BOT_RE_MUST_INCLUDE: tuple[str, ...] = (
    "googlebot",
    "bingbot",
    "gptbot",           # yes — even though blocked in robots.txt,
                        #       middleware needs to recognise it to
                        #       avoid serving SPA shell if it ever hits
    "oai-searchbot",
    "chatgpt-user",
    "perplexitybot",
    "claudebot",
    "claude-web",
    "anthropic-ai",
    "google-extended",
    "applebot-extended",
    "meta-externalagent",
)


# ── Helpers ─────────────────────────────────────────────────────────────
def _extract_robots_body() -> str:
    """Pull the triple-quoted robots.txt body literal out of server.py.

    We deliberately parse the source rather than spin up the FastAPI app:
    the test must pass in environments that don't have Mongo/Redis/etc.
    """
    src = SERVER_FILE.read_text(encoding="utf-8")
    m = re.search(
        r'async def serve_robots_txt\(\).*?txt\s*=\s*"""(.*?)"""',
        src,
        re.DOTALL,
    )
    assert m, (
        "could not locate `serve_robots_txt` handler in server.py — "
        "either the function was renamed or the triple-quoted body was "
        "moved. Update this test to match."
    )
    return m.group(1)


def _block_for(ua: str, body: str) -> list[str]:
    """Return the non-blank lines of the `User-agent: <ua>` block."""
    want = f"user-agent: {ua.lower()}"
    out: list[str] = []
    in_block = False
    for line in body.splitlines():
        low = line.strip().lower()
        if low == want:
            in_block = True
            out = [line]
            continue
        if in_block:
            if line.strip() == "":
                break
            out.append(line)
    return out


@pytest.fixture(scope="module")
def robots_body() -> str:
    return _extract_robots_body()


# ── Tests: robots.txt policy ────────────────────────────────────────────
@pytest.mark.parametrize("ua", ANSWER_BOTS)
def test_answer_bots_allowed(ua: str, robots_body: str) -> None:
    """Citation/answer bots must have explicit `Allow: /` — these drive
    organic traffic from ChatGPT / Perplexity / Gemini / Apple Intelligence."""
    block = _block_for(ua, robots_body)
    assert block, f"{ua!r} block missing from robots.txt — answer bot must be explicitly allowed"
    assert any(ln.strip() == "Allow: /" for ln in block[1:]), (
        f"{ua!r} must contain `Allow: /` (answer/citation bot). Block was:\n"
        + "\n".join(block)
    )


@pytest.mark.parametrize("ua", TRAINING_BOTS_ALLOWED)
def test_training_bots_allowed(ua: str, robots_body: str) -> None:
    """Training-only crawlers are Allow: / by product decision (max LLM
    reach). GPTBot is the one exception — covered by the block test below."""
    block = _block_for(ua, robots_body)
    assert block, f"{ua!r} block missing from robots.txt"
    assert any(ln.strip() == "Allow: /" for ln in block[1:]), (
        f"{ua!r} must contain `Allow: /` per 'maximum LLM reach' policy. Block was:\n"
        + "\n".join(block)
    )
    # And it must NOT accidentally also be Disallow: /
    assert not any(ln.strip() == "Disallow: /" for ln in block[1:]), (
        f"{ua!r} has conflicting Disallow: / — policy ambiguity will make bots "
        f"fall back to the most restrictive interpretation. Block was:\n"
        + "\n".join(block)
    )


@pytest.mark.parametrize("ua", BLOCKED_BOTS)
def test_blocked_bots_are_disallowed(ua: str, robots_body: str) -> None:
    """Only GPTBot should be blanket-blocked."""
    block = _block_for(ua, robots_body)
    assert block, f"{ua!r} block missing — expected Disallow: /"
    assert any(ln.strip() == "Disallow: /" for ln in block[1:]), (
        f"{ua!r} must be Disallow: /. Block was:\n" + "\n".join(block)
    )
    assert not any(ln.strip() == "Allow: /" for ln in block[1:]), (
        f"{ua!r} has conflicting Allow: / line — remove it. Block was:\n"
        + "\n".join(block)
    )


def test_exactly_one_blanket_disallow(robots_body: str) -> None:
    """The whole robots.txt should contain exactly one `Disallow: /` line —
    the GPTBot one. Any other is a regression: either an answer bot was
    accidentally blocked or a training bot slipped back into the block list.
    """
    blanket_lines = [
        ln for ln in robots_body.splitlines() if ln.strip() == "Disallow: /"
    ]
    assert len(blanket_lines) == 1, (
        f"expected exactly 1 blanket `Disallow: /` (GPTBot), found {len(blanket_lines)}. "
        "If this is an intentional policy change, update BLOCKED_BOTS in this test."
    )


def test_sitemap_line_present(robots_body: str) -> None:
    """The robots.txt must advertise the sitemap index so crawlers can
    auto-discover all 18+ per-subject sitemaps."""
    assert "Sitemap:" in robots_body, "robots.txt missing Sitemap: directive"
    assert "syrabit.ai" in robots_body, "Sitemap: line does not reference syrabit.ai"


# ── Tests: BotRenderMiddleware UA coverage ──────────────────────────────
@pytest.mark.parametrize("ua_fragment", SEARCH_BOT_RE_MUST_INCLUDE)
def test_search_bot_ua_regex_recognises(ua_fragment: str) -> None:
    """`_SEARCH_BOT_UA_RE` must match every answer-bot / search-bot UA we
    care about, so BotRenderMiddleware serves prerendered HTML (not the
    SPA shell) when they reach origin.

    Previous NEEDS-VERIFICATION item from the Phase-B audit — now locked.
    """
    src = UTILS_FILE.read_text(encoding="utf-8")
    m = re.search(
        r"_SEARCH_BOT_UA_RE\s*=\s*re\.compile\(\s*\n?\s*r?\"(.+?)\"\s*,\s*re\.IGNORECASE",
        src,
        re.DOTALL,
    )
    assert m, "could not locate `_SEARCH_BOT_UA_RE` in utils.py — rename? moved?"
    pattern_body = m.group(1)
    # The multi-line r"..." literal is reconstructed by concatenating every
    # string fragment inside the compile() call; _extract the raw text.
    raw_literals = re.findall(r'r?"([^"]*)"', src[m.start(): m.end()])
    combined = "".join(raw_literals)
    regex = re.compile(combined, re.IGNORECASE)
    assert regex.search(ua_fragment), (
        f"_SEARCH_BOT_UA_RE does not match {ua_fragment!r} — "
        "BotRenderMiddleware will serve SPA shell instead of prerendered "
        "HTML to this crawler. Add it to the regex in utils.py."
    )


# ── Tests: llms discovery file imports don't crash at boot ──────────────
def test_bot_discovery_imports_cleanly() -> None:
    """If `routes.bot_discovery.build_llms_full_txt` raises at import,
    the /llms-full.txt route silently never registers and the endpoint
    404s (D5 root cause candidate from the audit). This import-only check
    catches that class of bug without needing a live app."""
    import importlib

    mod = importlib.import_module("routes.bot_discovery")
    assert hasattr(mod, "build_llms_full_txt"), (
        "routes.bot_discovery.build_llms_full_txt is gone — the /llms-full.txt "
        "endpoint will 404. Either restore the symbol or update this test to "
        "reflect the new entry-point name."
    )
    assert callable(mod.build_llms_full_txt)


def test_edge_worker_routes_bot_discovery_paths() -> None:
    """Pin the edge worker's routing table: the three LLM-discovery paths
    and /robots.txt must be proxied to backend, not the SPA.

    Regression guard — before the Phase-B fix these paths returned the
    SPA HTML shell because the worker had no routing entry for them.
    """
    worker_src = (
        BACKEND_DIR.parent.parent / "workers" / "edge-proxy" / "src" / "index.ts"
    )
    if not worker_src.exists():
        pytest.skip("edge worker source not present in this checkout")
    src = worker_src.read_text(encoding="utf-8")
    for path in (
        "/robots.txt",
        "/llms.txt",
        "/llms-full.txt",
        "/.well-known/ai-plugin.json",
    ):
        assert path in src, (
            f"edge worker has no routing entry for {path!r} — it will fall "
            "through to the SPA and bots will see <!doctype html>. See "
            "BOT_DISCOVERY_PATHS block in workers/edge-proxy/src/index.ts."
        )
