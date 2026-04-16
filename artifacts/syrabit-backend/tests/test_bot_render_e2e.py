"""End-to-end tests for BotRenderMiddleware using FastAPI TestClient.

Unlike test_bot_render_routing.py (routing unit tests) and
test_bot_middleware_integration.py (direct dispatch calls against mocks),
these tests wire BotRenderMiddleware into a real FastAPI app and use
TestClient to issue GET requests with a Googlebot User-Agent. They verify
that the response body is valid HTML containing the expected <title>,
<link rel="canonical">, and JSON-LD structured data — catching broken
templates before they reach production.

They also verify that the same paths requested with a normal browser
User-Agent fall through to the SPA placeholder handler (i.e. the
middleware does not intercept human traffic).
"""
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from routes import cms_sarvam_health  # noqa: E402
from routes.cms_sarvam_health import BotRenderMiddleware  # noqa: E402


GOOGLEBOT_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)
HUMAN_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

SPA_MARKER = "<!-- SPA-SHELL-MARKER -->"


def _build_app() -> FastAPI:
    """Build a FastAPI app with BotRenderMiddleware + a catch-all SPA stub."""
    app = FastAPI()
    app.add_middleware(BotRenderMiddleware)

    async def spa_shell(full_path: str = ""):
        return HTMLResponse(
            f"<!doctype html><html><body>{SPA_MARKER}</body></html>"
        )

    # Catch-all for any path — this is what human UAs should receive.
    app.get("/")(spa_shell)
    app.get("/{full_path:path}")(spa_shell)
    return app


_HOMEPAGE_HTML = """<!DOCTYPE html>
<html lang="en-IN">
<head>
<meta charset="UTF-8">
<title>Syrabit.ai — AI Study Assistant for Assam Board Students</title>
<link rel="canonical" href="https://syrabit.ai/">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"WebSite","name":"Syrabit.ai","url":"https://syrabit.ai"}</script>
</head>
<body><h1>Syrabit.ai</h1></body>
</html>"""


_SUBJECT_HTML = """<!DOCTYPE html>
<html lang="en-IN">
<head>
<meta charset="UTF-8">
<title>Physics — AHSEC Class 12 | Syrabit.ai</title>
<link rel="canonical" href="https://syrabit.ai/ahsec/class-12/physics">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"CollectionPage","name":"Physics — AHSEC Class 12","url":"https://syrabit.ai/ahsec/class-12/physics"}</script>
</head>
<body><h1>Physics — AHSEC Class 12</h1></body>
</html>"""


def _make_httpx_mock(url_to_response: dict):
    """Build a context-manager replacement for httpx.AsyncClient that returns
    canned responses keyed by URL substring."""
    def _factory(*args, **kwargs):
        client = MagicMock()

        async def _get(url, *a, **kw):
            resp = MagicMock()
            resp.status_code = 404
            resp.text = ""
            resp.headers = {"content-type": "text/plain"}
            for key, body in url_to_response.items():
                if key in url:
                    resp.status_code = 200
                    resp.text = body
                    resp.headers = {"content-type": "text/html; charset=utf-8"}
                    break
            return resp

        client.get = AsyncMock(side_effect=_get)

        class _Ctx:
            async def __aenter__(self_inner):
                return client

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()

    return _factory


@pytest.fixture(autouse=True)
def _clear_cache():
    cms_sarvam_health._bot_html_cache.clear()
    yield
    cms_sarvam_health._bot_html_cache.clear()


@pytest.fixture
def client():
    return TestClient(_build_app())


# ---------- Helpers ----------


def _assert_valid_bot_html(body: str, expected_canonical: str, expected_title_sub: str):
    """Assert the response body has a <title>, canonical link, and JSON-LD."""
    assert "<title>" in body and "</title>" in body, "missing <title>"
    title_match = re.search(r"<title>([^<]+)</title>", body)
    assert title_match, "could not parse <title>"
    assert expected_title_sub.lower() in title_match.group(1).lower(), (
        f"expected {expected_title_sub!r} in title, got {title_match.group(1)!r}"
    )

    assert f'<link rel="canonical" href="{expected_canonical}">' in body, (
        f"missing canonical link for {expected_canonical}"
    )

    ld_matches = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        body,
        flags=re.DOTALL,
    )
    assert ld_matches, "no JSON-LD <script> block found"
    for raw in ld_matches:
        # Each JSON-LD block must be valid JSON with schema.org context.
        parsed = json.loads(raw)
        assert isinstance(parsed, dict), "JSON-LD must be a JSON object"
        assert parsed.get("@context") == "https://schema.org", (
            f"JSON-LD missing schema.org @context: {parsed!r}"
        )
        # Must declare either a node type or a @graph of nodes.
        assert parsed.get("@type") or parsed.get("@graph"), (
            "JSON-LD must have either @type or @graph"
        )


# ---------- Bot receives pre-rendered HTML ----------


def test_googlebot_homepage_receives_prerendered_html(client):
    mock = _make_httpx_mock({"/api/seo/html/homepage": _HOMEPAGE_HTML})
    with patch("httpx.AsyncClient", mock):
        resp = client.get("/", headers={"user-agent": GOOGLEBOT_UA})

    assert resp.status_code == 200
    assert resp.headers.get("X-Bot-Rendered") == "1"
    body = resp.text
    assert SPA_MARKER not in body, "bot should NOT receive SPA shell"
    _assert_valid_bot_html(
        body,
        expected_canonical="https://syrabit.ai/",
        expected_title_sub="Syrabit.ai",
    )


def test_googlebot_pricing_receives_prerendered_html(client):
    # /pricing is rendered inline in the middleware (no SEO API call needed).
    resp = client.get("/pricing", headers={"user-agent": GOOGLEBOT_UA})

    assert resp.status_code == 200
    assert resp.headers.get("X-Bot-Rendered") == "1"
    body = resp.text
    assert SPA_MARKER not in body
    _assert_valid_bot_html(
        body,
        expected_canonical="https://syrabit.ai/pricing",
        expected_title_sub="Pricing",
    )


def test_googlebot_subject_page_receives_prerendered_html(client):
    mock = _make_httpx_mock(
        {"/api/seo/html/subject/ahsec/class-12/physics": _SUBJECT_HTML}
    )
    with patch("httpx.AsyncClient", mock):
        resp = client.get(
            "/ahsec/class-12/physics", headers={"user-agent": GOOGLEBOT_UA}
        )

    assert resp.status_code == 200
    assert resp.headers.get("X-Bot-Rendered") == "1"
    body = resp.text
    assert SPA_MARKER not in body
    _assert_valid_bot_html(
        body,
        expected_canonical="https://syrabit.ai/ahsec/class-12/physics",
        expected_title_sub="Physics",
    )


# ---------- Human UA falls through to the SPA ----------


@pytest.mark.parametrize(
    "path",
    ["/", "/pricing", "/ahsec/class-12/physics"],
)
def test_human_ua_falls_through_to_spa(client, path):
    resp = client.get(path, headers={"user-agent": HUMAN_UA})

    assert resp.status_code == 200
    # No bot-render marker on human traffic
    assert resp.headers.get("X-Bot-Rendered") is None
    body = resp.text
    assert SPA_MARKER in body, (
        f"expected SPA shell for human UA at {path}, got: {body[:200]!r}"
    )
