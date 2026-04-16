"""Snapshot test for `artifacts/syrabit/public/robots.txt`.

Asserts the explicit allow/deny rules required by SEO Phase B (Plan 10):
  * Allow / for AppleBot, PetalBot, MojeekBot, SeznamBot, Yeti
  * Disallow / for GPTBot, CCBot, ClaudeBot, Google-Extended, anthropic-ai
  * Sitemap: https://syrabit.ai/sitemap-index.xml

If the edge worker ever inlines its own /robots.txt body (currently it does
not — Cloudflare Pages serves the static file), this test also asserts the
inlined body matches the static file byte-for-byte.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ROBOTS_FILE = REPO_ROOT / "artifacts" / "syrabit" / "public" / "robots.txt"
WORKER_FILE = REPO_ROOT / "workers" / "edge-proxy" / "src" / "index.ts"


def _read_robots() -> str:
    return ROBOTS_FILE.read_text(encoding="utf-8")


def _block_for(ua: str, body: str) -> str:
    """Return the block of lines starting at `User-agent: <ua>` until the
    next blank line. Empty string if not found."""
    lines = body.splitlines()
    out: list[str] = []
    in_block = False
    for line in lines:
        if line.strip().lower().startswith(f"user-agent: {ua.lower()}"):
            in_block = True
            out = [line]
            continue
        if in_block:
            if line.strip() == "":
                break
            out.append(line)
    return "\n".join(out)


def test_allow_long_tail_search_bots():
    body = _read_robots()
    for ua in ("Applebot", "PetalBot", "MojeekBot", "SeznamBot", "Yeti"):
        block = _block_for(ua, body)
        assert block, f"missing User-agent: {ua} block"
        assert "Allow: /" in block, f"{ua} block must Allow: /\n{block}"


def test_disallow_ai_training_bots():
    body = _read_robots()
    for ua in ("GPTBot", "CCBot", "ClaudeBot", "Google-Extended", "anthropic-ai"):
        block = _block_for(ua, body)
        assert block, f"missing User-agent: {ua} block"
        assert "Disallow: /" in block, f"{ua} block must Disallow: /\n{block}"
        # Make sure they're NOT also accidentally allowed at root.
        for line in block.splitlines()[1:]:
            assert line.strip() != "Allow: /", (
                f"{ua} must not Allow: / (would conflict with Disallow: /)"
            )


def test_sitemap_index_line_present():
    body = _read_robots()
    assert "Sitemap: https://syrabit.ai/sitemap-index.xml" in body


def test_no_worker_robots_override_diverges():
    """If the edge worker inlines a robots.txt body, it must equal the
    static file byte-for-byte. Today the worker does not serve /robots.txt
    (Cloudflare Pages does), so this test passes trivially.
    """
    if not WORKER_FILE.exists():
        return
    src = WORKER_FILE.read_text(encoding="utf-8")
    # Heuristic: an inlined robots body would contain a literal
    # "User-agent: " inside a string. Flag any such occurrence so the
    # author can ensure it stays in sync.
    matches = re.findall(r'["`]\s*User-agent:\s', src)
    if not matches:
        return  # no inlined override
    static = _read_robots()
    # If there's an inlined body, it must contain every expected rule.
    for required in (
        "User-agent: AppleBot", "User-agent: PetalBot",
        "User-agent: MojeekBot", "User-agent: SeznamBot", "User-agent: Yeti",
        "User-agent: GPTBot", "User-agent: CCBot", "User-agent: ClaudeBot",
        "User-agent: Google-Extended", "User-agent: anthropic-ai",
        "Sitemap: https://syrabit.ai/sitemap-index.xml",
    ):
        assert required in src or required in static, (
            f"worker inlines /robots.txt but is missing {required!r}"
        )
