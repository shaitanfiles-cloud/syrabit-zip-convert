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


def test_build_ai_plugin_json_imports_cleanly() -> None:
    """Sibling guard to ``test_bot_discovery_imports_cleanly``: if
    ``build_ai_plugin_json`` raises at import, the /.well-known/ai-plugin.json
    endpoint silently de-registers and bots / ChatGPT plugins get HTML
    instead of JSON."""
    import importlib

    mod = importlib.import_module("routes.bot_discovery")
    assert hasattr(mod, "build_ai_plugin_json"), (
        "routes.bot_discovery.build_ai_plugin_json is gone — the /.well-known/"
        "ai-plugin.json endpoint will 404 or serve SPA shell."
    )
    assert callable(mod.build_ai_plugin_json)


# ── Tests: ai-plugin.json structure ─────────────────────────────────────
# Per https://platform.openai.com/docs/plugins/getting-started/plugin-manifest
# the manifest MUST contain these fields. Missing any one is a silent
# registration failure on ChatGPT's side.
AI_PLUGIN_REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "name_for_human",
    "name_for_model",
    "description_for_human",
    "description_for_model",
    "auth",
    "api",
    "logo_url",
    "contact_email",
    "legal_info_url",
)


@pytest.fixture(scope="module")
def ai_plugin_manifest() -> dict:
    """Parse the manifest from source so this test works without a live API."""
    import json as _json

    from routes.bot_discovery import build_ai_plugin_json

    return _json.loads(build_ai_plugin_json())


@pytest.mark.parametrize("field", AI_PLUGIN_REQUIRED_FIELDS)
def test_ai_plugin_required_fields_present(
    field: str, ai_plugin_manifest: dict
) -> None:
    assert field in ai_plugin_manifest, (
        f"ai-plugin.json is missing required field {field!r} — ChatGPT / "
        "bot plugin registries will reject the manifest."
    )
    assert ai_plugin_manifest[field] not in (None, ""), (
        f"ai-plugin.json field {field!r} is empty — field must have a value."
    )


def test_ai_plugin_auth_type_is_none(ai_plugin_manifest: dict) -> None:
    """We publish a read-only content manifest — auth MUST be `none` so
    bots can register without credentials. Anything else silently breaks
    discovery."""
    assert ai_plugin_manifest["auth"].get("type") == "none", (
        "ai-plugin.json auth.type must be 'none' (public manifest). Got: "
        f"{ai_plugin_manifest['auth']}"
    )


def test_ai_plugin_urls_point_to_production(ai_plugin_manifest: dict) -> None:
    """All URL-shaped fields must point to https://syrabit.ai — a stray
    localhost / staging URL in the prod manifest is a known failure mode
    from dev-config bleeding into prod."""
    url_fields = ("logo_url", "legal_info_url")
    for field in url_fields:
        url = ai_plugin_manifest[field]
        assert url.startswith("https://syrabit.ai"), (
            f"ai-plugin.json {field!r} must start with https://syrabit.ai, got {url!r}"
        )
    api_url = ai_plugin_manifest["api"].get("url", "")
    assert api_url.startswith("https://syrabit.ai"), (
        f"ai-plugin.json api.url must start with https://syrabit.ai, got {api_url!r}"
    )


# ── Tests: llms.txt content completeness ────────────────────────────────
LLMS_TXT_REQUIRED_SECTIONS: tuple[str, ...] = (
    "# Syrabit.ai",
    "## What Is Syrabit.ai",
    "## Boards & Curricula Covered",
    "## Content Types",
    "## URL Structure",
)


@pytest.fixture(scope="module")
def llms_txt_body() -> str:
    """Snapshot of the llms.txt handler output, built in-process."""
    import asyncio

    from routes.admin_advanced import _build_llms_txt

    return asyncio.get_event_loop().run_until_complete(_build_llms_txt())


@pytest.mark.parametrize("section", LLMS_TXT_REQUIRED_SECTIONS)
def test_llms_txt_has_required_sections(section: str, llms_txt_body: str) -> None:
    """llms.txt is the canonical index for LLM crawlers — missing sections
    means AI tutors get incomplete grounding on what Syrabit covers."""
    assert section in llms_txt_body, (
        f"llms.txt missing required section {section!r}. LLMs will have "
        "incomplete grounding on Syrabit's content surface."
    )


def test_llms_txt_references_all_boards(llms_txt_body: str) -> None:
    """Every board we support must be named in llms.txt so LLMs correctly
    associate Syrabit with AHSEC / SEBA / Degree queries."""
    for board in ("AHSEC", "SEBA", "FYUGP"):
        assert board in llms_txt_body, (
            f"llms.txt does not mention {board!r} — LLMs will not surface "
            "Syrabit for queries scoped to that board."
        )


# ── Tests: robots.txt structural hygiene ────────────────────────────────
def test_no_duplicate_user_agent_blocks(robots_body: str) -> None:
    """A duplicate ``User-agent: Foo`` block is almost always a copy-paste
    regression with two conflicting policies — crawlers pick the first
    match silently, causing drift between intended and actual policy."""
    seen: list[str] = []
    for line in robots_body.splitlines():
        low = line.strip().lower()
        if low.startswith("user-agent:"):
            ua = low.split(":", 1)[1].strip()
            seen.append(ua)
    dupes = {ua for ua in seen if seen.count(ua) > 1}
    assert not dupes, (
        f"duplicate User-agent blocks found: {sorted(dupes)} — each UA "
        "must appear at most once in robots.txt."
    )


def test_all_paths_are_absolute(robots_body: str) -> None:
    """Every ``Allow:`` / ``Disallow:`` path must start with ``/``. A
    path like ``Disallow: admin/`` is silently ignored by most crawlers
    (valid-but-meaningless) — looks like a block but isn't one."""
    for ln_no, line in enumerate(robots_body.splitlines(), start=1):
        s = line.strip()
        for directive in ("Allow:", "Disallow:"):
            if s.startswith(directive):
                path = s[len(directive):].strip()
                # Empty value is valid (``Disallow:`` on its own = allow all).
                if not path:
                    continue
                assert path.startswith("/"), (
                    f"robots.txt line {ln_no}: {s!r} — path must start with "
                    f"'/' (got {path!r}). Crawlers silently ignore "
                    "relative paths."
                )


def test_wildcard_user_agent_fallback_exists(robots_body: str) -> None:
    """``User-agent: *`` is the default policy for any unnamed bot. It
    must exist AND must not be a blanket ``Disallow: /`` — otherwise any
    new AI crawler we haven't listed explicitly gets locked out by
    default, defeating the whole 'max LLM reach' policy."""
    block = _block_for("*", robots_body)
    assert block, "robots.txt has no `User-agent: *` wildcard fallback"
    body_lines = [ln.strip() for ln in block[1:]]
    # Must not be a blanket Disallow
    assert "Disallow: /" not in body_lines, (
        "`User-agent: *` is blanket-blocked — every unnamed AI bot (including "
        "future ones we haven't listed) will be locked out. Use scoped "
        "Disallow paths (admin/auth/ai) instead."
    )


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
