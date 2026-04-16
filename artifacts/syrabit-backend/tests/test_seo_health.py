"""Tests for /api/seo/health endpoint response structure."""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch


def _install_stubs():
    """Install minimal module stubs so bot_discovery imports cleanly."""
    if "deps" not in sys.modules:
        deps = types.ModuleType("deps")
        deps.db = MagicMock()
        deps.is_mongo_available = AsyncMock(return_value=False)
        sys.modules["deps"] = deps


_install_stubs()
from routes import bot_discovery  # noqa: E402


VALID_SITEMAP_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://syrabit.ai/ahsec/class-12/physics</loc></url>"
    "<url><loc>https://syrabit.ai/seba/class-10/maths</loc></url>"
    "</urlset>"
)


def _mock_response(status: int, text: str = "", json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in."""

    def __init__(self, *_a, **_kw):
        self.get = AsyncMock()
        self.head = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_seo_health_ok_response_shape():
    fake = _FakeAsyncClient()
    fake.get.return_value = _mock_response(200, VALID_SITEMAP_XML)
    fake.head.return_value = _mock_response(200)

    with patch("httpx.AsyncClient", lambda *a, **kw: fake):
        result = asyncio.run(bot_discovery.seo_health_check())

    assert result["status"] == "ok"
    assert "sitemaps" in result
    assert "d1_sync" in result
    assert "checked_at" in result
    assert "summary" in result
    assert result["summary"]["total_sitemaps"] == len(result["sitemaps"])
    assert result["summary"]["valid_sitemaps"] == result["summary"]["total_sitemaps"]
    for sm in result["sitemaps"]:
        assert sm["valid_xml"] is True
        assert sm["url_count"] == 2
        assert all(c["ok"] for c in sm["sample_checks"])


def test_seo_health_marks_critical_when_most_sitemaps_invalid():
    fake = _FakeAsyncClient()
    fake.get.return_value = _mock_response(500, "boom")
    fake.head.return_value = _mock_response(500)

    with patch("httpx.AsyncClient", lambda *a, **kw: fake):
        result = asyncio.run(bot_discovery.seo_health_check())

    assert result["status"] == "critical"
    assert result["summary"]["valid_sitemaps"] == 0
    for sm in result["sitemaps"]:
        assert sm["valid_xml"] is False
        assert "error" in sm


def test_seo_health_degraded_when_some_url_checks_fail():
    """When sitemaps parse but >20% of sample URL checks fail, status=degraded."""
    fake = _FakeAsyncClient()
    fake.get.return_value = _mock_response(200, VALID_SITEMAP_XML)
    # All HEAD checks fail with 404
    fake.head.return_value = _mock_response(404)

    with patch("httpx.AsyncClient", lambda *a, **kw: fake):
        result = asyncio.run(bot_discovery.seo_health_check())

    assert result["status"] == "degraded"
    assert result["summary"]["valid_sitemaps"] == result["summary"]["total_sitemaps"]
    assert result["summary"]["ok_url_checks"] == 0
