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
        result = asyncio.run(bot_discovery.seo_health_check(request=None, deep_scan=None))

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
        result = asyncio.run(bot_discovery.seo_health_check(request=None, deep_scan=None))

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

    with patch("httpx.AsyncClient", lambda *a, **kw: fake), \
         patch.object(bot_discovery, "_SEO_HEALTH_RETRY_DELAY_S", 0):
        result = asyncio.run(bot_discovery.seo_health_check(request=None, deep_scan=None))

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


def _fake_admin_request():
    """Build a stand-in `Request` object that satisfies `get_admin_user`'s
    interface for the deep-scan branch of `seo_health_check`. We patch
    `get_admin_user` itself so the actual request shape doesn't matter."""
    class _Req:
        headers = {}
        cookies = {}
    return _Req()


def test_deep_scan_endpoint_rejects_unknown_sitemap():
    """The route must whitelist the `sitemap` query param so an attacker
    can't coerce us into probing arbitrary URLs through this endpoint."""
    from fastapi import HTTPException
    raised = None
    # Patch admin auth to a no-op so we exercise only the whitelist guard.
    with patch.object(bot_discovery, "get_admin_user", new=lambda req: asyncio.sleep(0)):
        try:
            asyncio.run(bot_discovery.seo_health_check(
                request=_fake_admin_request(), deep_scan="../../etc/passwd"))
        except HTTPException as e:
            raised = e
    assert raised is not None, "expected HTTPException for unknown sitemap"
    assert raised.status_code == 400


def test_deep_scan_endpoint_accepts_whitelisted_sitemap():
    """Sanity check: every name in SEO_SITEMAP_FILENAMES is accepted by
    the route (no typos in the whitelist drift away from real sitemaps)."""
    fake = _DeepScanFakeClient(_make_sitemap_xml([]), {})
    with patch.object(bot_discovery, "get_admin_user", new=lambda req: asyncio.sleep(0)):
        for name in bot_discovery.SEO_SITEMAP_FILENAMES:
            with patch("httpx.AsyncClient", lambda *a, **kw: fake):
                res = asyncio.run(bot_discovery.seo_health_check(
                    request=_fake_admin_request(), deep_scan=name))
            assert res["sitemap"] == name


def test_deep_scan_endpoint_requires_admin_auth():
    """Anonymous callers must NOT be able to trigger the deep scan via
    `?deep_scan=`. The path-level dependency would normally raise; here
    we make `get_admin_user` raise to mimic that and verify the route
    propagates the failure before doing any sitemap fetching."""
    from fastapi import HTTPException

    async def _deny(_req):
        raise HTTPException(status_code=401, detail="auth required")

    raised = None
    with patch.object(bot_discovery, "get_admin_user", new=_deny):
        try:
            asyncio.run(bot_discovery.seo_health_check(
                request=_fake_admin_request(), deep_scan="sitemap-learn.xml"))
        except HTTPException as e:
            raised = e
    assert raised is not None, "expected anonymous deep-scan to be rejected"
    assert raised.status_code == 401


# ---------------------------------------------------------------------------
# Task #348: auto-email failing-URL CSV after a deep scan
# ---------------------------------------------------------------------------

def _make_failing(n):
    return [
        {"url": f"https://syrabit.ai/learn/topic-{i}", "status": 404}
        for i in range(n)
    ]


def test_csv_renderer_escapes_formula_injection_and_commas():
    """The shared CSV renderer must escape formula leaders and quote
    fields with commas/quotes so the email attachment is safe to open
    in Excel even if a URL or error string was attacker-controlled."""
    failing = [
        {"url": "=cmd|'/c calc'", "status": 500, "error": "boom"},
        {"url": "https://x/?a=1,b=2", "status": 404, "error": 'has "quote"'},
        {"url": "https://x/normal", "status": 503, "error": None},
    ]
    csv = bot_discovery._build_failing_urls_csv(failing)
    # Header + 3 data rows; BOM prefixed for Excel.
    assert csv.startswith("\ufeff")
    lines = csv.lstrip("\ufeff").splitlines()
    assert lines[0] == "url,status,error"
    # Formula-leading URL must be neutralized with a leading apostrophe.
    assert lines[1].startswith("'=cmd")
    # Comma-bearing URL must be quoted.
    assert '"https://x/?a=1,b=2"' in lines[2]
    # Embedded quotes are doubled per RFC 4180.
    assert '"has ""quote"""' in lines[2]
    # None error becomes empty string, not the literal "None".
    assert lines[3].endswith(",")


def test_email_skipped_below_threshold():
    """≤50 failing URLs must NOT trigger an email — those are routine
    blips and shouldn't spam the alert channel."""
    result = asyncio.run(bot_discovery._maybe_email_failing_csv(
        "sitemap-learn.xml",
        {"failing": _make_failing(50)},
        admin_id=None,
    ))
    assert result["sent"] is False
    assert result["reason"] == "below_threshold"


def test_email_skipped_when_disabled_by_admin():
    """Per-admin opt-out: when the calling admin has the toggle off the
    email must be suppressed even if the threshold is exceeded."""
    async def _prefs(_admin_id):
        return {"email_failing_csv_enabled": False}

    fake_db_ops = types.SimpleNamespace(get_admin_notification_prefs=_prefs)
    with patch.dict(sys.modules, {"db_ops": fake_db_ops}):
        result = asyncio.run(bot_discovery._maybe_email_failing_csv(
            "sitemap-learn.xml",
            {"failing": _make_failing(60)},
            admin_id="admin-1",
        ))
    assert result["sent"] is False
    assert result["reason"] == "disabled_by_admin"


def test_email_sent_with_csv_attachment_when_above_threshold(monkeypatch):
    """>50 failing URLs + admin opted in + Resend key present + admin
    email configured → Resend.Emails.send is called once with the CSV
    payload as a base64 attachment, the right subject, and a filename
    that includes the sitemap name and a timestamp."""
    async def _prefs(_admin_id):
        return {"email_failing_csv_enabled": True}

    fake_db_ops = types.SimpleNamespace(get_admin_notification_prefs=_prefs)

    async def _noop_load():
        return None

    fake_metrics = types.SimpleNamespace(
        _notification_channels={"email": "oncall@syrabit.ai"},
        _load_alert_settings=_noop_load,
    )
    fake_email_templates = types.SimpleNamespace(
        EMAIL_FROM="Syrabit.ai <noreply@syrabit.ai>",
    )

    monkeypatch.setenv("RESEND_API_KEY", "re_test_123")

    sent_payloads = []
    fake_resend = types.SimpleNamespace(
        api_key=None,
        Emails=types.SimpleNamespace(
            send=lambda payload: sent_payloads.append(payload),
        ),
    )

    with patch.dict(sys.modules, {
        "db_ops": fake_db_ops,
        "metrics": fake_metrics,
        "email_templates": fake_email_templates,
        "resend": fake_resend,
    }):
        result = asyncio.run(bot_discovery._maybe_email_failing_csv(
            "sitemap-learn.xml",
            {"failing": _make_failing(75)},
            admin_id="admin-1",
        ))

    assert result["sent"] is True, result
    assert result["to"] == "oncall@syrabit.ai"
    assert "75" in result["subject"] and "sitemap-learn.xml" in result["subject"]
    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["to"] == ["oncall@syrabit.ai"]
    # Exactly one attachment with the right shape and base64 content.
    assert len(payload["attachments"]) == 1
    att = payload["attachments"][0]
    assert att["filename"].startswith("failing-urls-sitemap-learn-")
    assert att["filename"].endswith(".csv")
    import base64
    decoded = base64.b64decode(att["content"]).decode("utf-8")
    assert decoded.startswith("\ufeff")
    assert "url,status,error" in decoded
    # All 75 URLs are present in the attachment.
    for i in range(75):
        assert f"/topic-{i}" in decoded


def test_deep_scan_route_invokes_email_helper_and_attaches_result():
    """Route-level wiring: seo_health_check(deep_scan=...) must call the
    email helper exactly once and surface its return value under
    response['email'] so the dashboard can show send status to admins
    and so we don't regress the helper integration silently."""
    fake = _DeepScanFakeClient(_make_sitemap_xml([]), {})
    captured_calls = []

    async def _fake_email(sitemap_name, scan_result, *, admin_id):
        captured_calls.append({
            "sitemap": sitemap_name,
            "admin_id": admin_id,
            "failing_count": len(scan_result.get("failing", [])),
        })
        return {"sent": True, "to": "oncall@syrabit.ai", "reason": "stub"}

    async def _fake_admin(_req):
        return {"sub": "admin-42", "email": "admin@syrabit.ai"}

    with patch.object(bot_discovery, "get_admin_user", new=_fake_admin), \
         patch.object(bot_discovery, "_maybe_email_failing_csv", new=_fake_email), \
         patch("httpx.AsyncClient", lambda *a, **kw: fake):
        result = asyncio.run(bot_discovery.seo_health_check(
            request=_fake_admin_request(), deep_scan="sitemap-learn.xml"))

    assert "email" in result, "deep-scan response must include email metadata"
    assert result["email"]["sent"] is True
    assert result["email"]["to"] == "oncall@syrabit.ai"
    assert len(captured_calls) == 1
    assert captured_calls[0]["sitemap"] == "sitemap-learn.xml"
    # admin_id should prefer the JWT subject over the email so per-admin
    # opt-out works even when an admin's email later changes.
    assert captured_calls[0]["admin_id"] == "admin-42"


def test_email_skipped_without_resend_key(monkeypatch):
    """Missing RESEND_API_KEY must be a graceful no-op, not an
    exception — the deep scan itself still succeeded and we don't want
    email delivery problems to blow up the response."""
    async def _prefs(_admin_id):
        return {"email_failing_csv_enabled": True}

    fake_db_ops = types.SimpleNamespace(get_admin_notification_prefs=_prefs)

    async def _noop_load():
        return None
    fake_metrics = types.SimpleNamespace(
        _notification_channels={"email": "oncall@syrabit.ai"},
        _load_alert_settings=_noop_load,
    )
    monkeypatch.delenv("RESEND_API_KEY", raising=False)

    with patch.dict(sys.modules, {
        "db_ops": fake_db_ops, "metrics": fake_metrics,
    }):
        result = asyncio.run(bot_discovery._maybe_email_failing_csv(
            "sitemap-learn.xml",
            {"failing": _make_failing(100)},
            admin_id="admin-1",
        ))
    assert result["sent"] is False
    assert result["reason"] == "no_resend_key"
