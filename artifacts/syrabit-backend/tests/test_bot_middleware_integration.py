"""Integration tests for BotRenderMiddleware.dispatch — exercises the full
middleware: user-agent detection, page-type dispatch, fallthrough behavior,
and bot-render response shape for curriculum/board/board+class/exam-routine.
"""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch


def _install_stubs():
    if "deps" not in sys.modules:
        deps = types.ModuleType("deps")
        deps.db = MagicMock()
        deps.is_mongo_available = AsyncMock(return_value=False)
        sys.modules["deps"] = deps


_install_stubs()

from routes import cms_sarvam_health  # noqa: E402
from routes.cms_sarvam_health import BotRenderMiddleware  # noqa: E402


GOOGLEBOT_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)
HUMAN_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _build_request(path: str, ua: str):
    """Build a Starlette Request stand-in compatible with the middleware."""
    request = MagicMock()
    request.url = MagicMock()
    request.url.path = path
    request.headers = {"user-agent": ua}
    return request


def _capture_call_next():
    """Returns (call_next, was_called) where was_called is mutable."""
    called = {"hit": False}

    async def call_next(_request):
        called["hit"] = True
        resp = MagicMock()
        resp.headers = {}
        resp.body = b""
        return resp

    return call_next, called


def _run(coro):
    return asyncio.run(coro)


def _clear_bot_cache():
    cms_sarvam_health._bot_html_cache.clear()


# ---------------- Bot detection ----------------

def test_human_ua_falls_through_without_render():
    _clear_bot_cache()
    mw = BotRenderMiddleware(MagicMock())
    call_next, called = _capture_call_next()
    req = _build_request("/curriculum", HUMAN_UA)

    _run(mw.dispatch(req, call_next))

    assert called["hit"] is True


def test_path_with_file_extension_falls_through():
    _clear_bot_cache()
    mw = BotRenderMiddleware(MagicMock())
    call_next, called = _capture_call_next()
    req = _build_request("/static/main.css", GOOGLEBOT_UA)

    _run(mw.dispatch(req, call_next))

    assert called["hit"] is True


def test_unsupported_path_falls_through():
    _clear_bot_cache()
    mw = BotRenderMiddleware(MagicMock())
    call_next, called = _capture_call_next()
    req = _build_request("/unknown-board", GOOGLEBOT_UA)

    _run(mw.dispatch(req, call_next))

    assert called["hit"] is True


# ---------------- Page-type dispatch ----------------

def _bot_get(path: str):
    """Run the middleware for a Googlebot request and return the response."""
    mw = BotRenderMiddleware(MagicMock())
    call_next, called = _capture_call_next()
    req = _build_request(path, GOOGLEBOT_UA)
    resp = _run(mw.dispatch(req, call_next))
    return resp, called["hit"]


def test_curriculum_page_renders_static_html():
    _clear_bot_cache()
    resp, fell_through = _bot_get("/curriculum")

    assert fell_through is False
    body = resp.body.decode("utf-8") if isinstance(resp.body, bytes) else resp.body
    assert "Curriculum Map" in body
    assert "<title>" in body


def test_exam_routine_page_renders_static_html():
    _clear_bot_cache()
    resp, fell_through = _bot_get("/exam-routine")

    assert fell_through is False
    body = resp.body.decode("utf-8") if isinstance(resp.body, bytes) else resp.body
    assert "<title>" in body
    assert "exam" in body.lower() or "routine" in body.lower()


def test_board_page_renders_inline_landing_html():
    """Board pages (/ahsec) render an inline templated landing page with
    title, canonical link, and JSON-LD CollectionPage schema."""
    _clear_bot_cache()
    resp, fell_through = _bot_get("/ahsec")

    assert fell_through is False
    body = resp.body.decode("utf-8") if isinstance(resp.body, bytes) else resp.body
    assert "AHSEC Board" in body
    assert '<link rel="canonical" href="https://syrabit.ai/ahsec">' in body
    assert "CollectionPage" in body  # JSON-LD


def test_board_class_page_renders_inline_landing_html():
    _clear_bot_cache()
    resp, fell_through = _bot_get("/seba/class-10")

    assert fell_through is False
    body = resp.body.decode("utf-8") if isinstance(resp.body, bytes) else resp.body
    assert "SEBA" in body
    assert "Class 10" in body
    assert '<link rel="canonical" href="https://syrabit.ai/seba/class-10">' in body
    assert "BreadcrumbList" in body  # JSON-LD


def test_cache_hit_returns_immediately_without_api_call():
    """Once a page is cached, the middleware must return the cached HTML
    without making any downstream fetch."""
    _clear_bot_cache()
    cms_sarvam_health._bot_html_cache["_curriculum_"] = (
        "<html><body>cached curriculum</body></html>"
    )

    fake = MagicMock()
    fake.get = AsyncMock()
    class _Ctx:
        async def __aenter__(self_inner): return fake
        async def __aexit__(self_inner, *exc): return False

    with patch("httpx.AsyncClient", lambda *a, **kw: _Ctx()):
        resp, fell_through = _bot_get("/curriculum")

    assert fell_through is False
    body = resp.body.decode("utf-8") if isinstance(resp.body, bytes) else resp.body
    assert "cached curriculum" in body
    fake.get.assert_not_called()
