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
    """If the edge worker ever inlines a /robots.txt response, the bytes
    must match the static `artifacts/syrabit/public/robots.txt` exactly.

    Today the worker does not serve /robots.txt (Cloudflare Pages serves
    the static file), so this test guards against future drift: as soon as
    a `/robots.txt` route OR an inlined `User-agent:` block appears in the
    worker source, the worker source must contain the static file's bytes
    verbatim. No heuristic substring/containment fallbacks.
    """
    if not WORKER_FILE.exists():
        return
    src = WORKER_FILE.read_text(encoding="utf-8")

    # Detect a worker-side robots.txt response by looking for an inlined
    # `User-agent:` block inside a string literal — that is the only way
    # the worker would author its own robots body. Bare path references
    # like `/api/robots.txt` (a backend route the worker proxies) do not
    # count: the worker only proxies them, it does not synthesize a body.
    has_inlined_block = bool(re.search(r'["`]\s*User-agent:\s', src))
    if not has_inlined_block:
        return  # worker is silent on robots.txt — Pages serves the static file

    static_body = _read_robots()
    # Strict byte-for-byte parity: the worker source must literally embed
    # the entire static robots.txt body. If you add a /robots.txt handler,
    # build it by reading this file at build time or by embedding the
    # exact bytes — do NOT hand-roll a parallel rule set.
    assert static_body in src, (
        "worker references /robots.txt or inlines a User-agent block but does "
        "not embed the exact bytes of artifacts/syrabit/public/robots.txt — "
        "this drift is the bug Phase B is designed to prevent. Either remove "
        "the worker-side handler or embed the static file verbatim."
    )
