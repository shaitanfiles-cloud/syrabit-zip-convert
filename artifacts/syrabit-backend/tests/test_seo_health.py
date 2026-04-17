"""Tests for /api/seo/health endpoint response structure."""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch


from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()
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


# -------- Task #345: deep-scan single sitemap endpoint --------

class _DeepScanFakeClient:
    """httpx.AsyncClient stand-in that returns canned responses keyed by URL.

    Lets us simulate a sitemap with many URLs where some succeed and some
    fail, so we can verify _deep_scan_sitemap collects them all (not just
    the first 10) and preserves source order.
    """

    def __init__(self, sitemap_xml: str, url_status_map: dict):
        self._sitemap_xml = sitemap_xml
        self._url_status_map = url_status_map

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, *_a, **_kw):
        if url.endswith(".xml"):
            return _mock_response(200, self._sitemap_xml)
        return _mock_response(self._url_status_map.get(url, 200))

    async def head(self, url, *_a, **_kw):
        return _mock_response(self._url_status_map.get(url, 200))


def _make_sitemap_xml(urls):
    body = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{body}</urlset>")


def test_deep_scan_returns_all_failing_urls_not_just_ten():
    """Core promise of #345: when 25 of 30 URLs are 404, the deep scan
    must return all 25 — the standard /seo/health probe would only see
    a random 10-URL sample."""
    urls = [f"https://syrabit.ai/learn/topic-{i}" for i in range(30)]
    status_map = {u: (404 if i < 25 else 200) for i, u in enumerate(urls)}
    fake = _DeepScanFakeClient(_make_sitemap_xml(urls), status_map)

    with patch("httpx.AsyncClient", lambda *a, **kw: fake):
        result = asyncio.run(bot_discovery._deep_scan_sitemap("sitemap-learn.xml"))

    assert result["sitemap"] == "sitemap-learn.xml"
    assert result["total_urls"] == 30
    assert result["checked"] == 30
    assert result["truncated"] is False
    assert len(result["failing"]) == 25
    # Source-order preservation — first failing URL should be topic-0,
    # not whichever probe finished first under concurrency.
    assert result["failing"][0]["url"].endswith("/topic-0")
    assert result["failing"][-1]["url"].endswith("/topic-24")
    for f in result["failing"]:
        assert f["status"] == 404


def test_deep_scan_truncates_oversized_sitemaps():
    """Sitemaps larger than SEO_DEEP_SCAN_MAX_URLS must be truncated so
    a 50k-URL sitemap doesn't hammer our origin or hang the request."""
    cap = bot_discovery.SEO_DEEP_SCAN_MAX_URLS
    urls = [f"https://syrabit.ai/x/{i}" for i in range(cap + 50)]
    status_map = {u: 404 for u in urls}
    fake = _DeepScanFakeClient(_make_sitemap_xml(urls), status_map)

    with patch("httpx.AsyncClient", lambda *a, **kw: fake):
        result = asyncio.run(bot_discovery._deep_scan_sitemap("sitemap-pages.xml"))

    assert result["total_urls"] == cap + 50
    assert result["checked"] == cap
    assert result["truncated"] is True
    assert len(result["failing"]) == cap


def test_deep_scan_records_network_error_as_status_zero():
    """Probes that raise (DNS / timeout / TLS) must be captured with
    status 0 so they appear in the failing list, not silently dropped."""
    urls = ["https://syrabit.ai/learn/dead"]

    class _ErrorClient(_DeepScanFakeClient):
        async def head(self, url, *_a, **_kw):
            raise RuntimeError("connection refused")

    fake = _ErrorClient(_make_sitemap_xml(urls), {})
    with patch("httpx.AsyncClient", lambda *a, **kw: fake):
        result = asyncio.run(bot_discovery._deep_scan_sitemap("sitemap-learn.xml"))

    assert len(result["failing"]) == 1
    assert result["failing"][0]["status"] == 0
    assert "error" in result["failing"][0]


def test_deep_scan_returns_error_when_sitemap_fetch_fails():
    """If the sitemap itself returns 5xx, surface a clear error rather
    than leaking an empty failing list that looks like a healthy scan."""
    fake = _DeepScanFakeClient("", {})

    async def _bad_get(url, *_a, **_kw):
        return _mock_response(503, "")

    fake.get = _bad_get
    with patch("httpx.AsyncClient", lambda *a, **kw: fake):
        result = asyncio.run(bot_discovery._deep_scan_sitemap("sitemap-learn.xml"))

    assert "error" in result
    assert "503" in result["error"]
    assert result["failing"] == []


def test_deep_scan_endpoint_rejects_unknown_sitemap():
    """The route must whitelist the `sitemap` query param so an attacker
    can't coerce us into probing arbitrary URLs through this endpoint."""
    from fastapi import HTTPException
    raised = None
    try:
        asyncio.run(bot_discovery.admin_seo_sitemap_failing_urls(
            sitemap="../../etc/passwd", admin={"id": "x"}))
    except HTTPException as e:
        raised = e
    assert raised is not None, "expected HTTPException for unknown sitemap"
    assert raised.status_code == 400


def test_deep_scan_endpoint_accepts_whitelisted_sitemap():
    """Sanity check: every name in SEO_SITEMAP_FILENAMES is accepted by
    the route (no typos in the whitelist drift away from real sitemaps)."""
    fake = _DeepScanFakeClient(_make_sitemap_xml([]), {})
    for name in bot_discovery.SEO_SITEMAP_FILENAMES:
        with patch("httpx.AsyncClient", lambda *a, **kw: fake):
            res = asyncio.run(bot_discovery.admin_seo_sitemap_failing_urls(
                sitemap=name, admin={"id": "x"}))
        assert res["sitemap"] == name
