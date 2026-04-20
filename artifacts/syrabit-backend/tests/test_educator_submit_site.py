"""Unit tests for the educator self-serve allowlist flow.

Covers:
* `auth_deps.get_educator_user` role gating (educator + admin accepted,
  student rejected).
* `edu_reader.probe_site_safety` early-exits (invalid domain, private
  IP, hard-denied) without touching the network.
* `routes.edu_browser.educator_submit_site` end-to-end using the
  FastAPI TestClient with dependency overrides + a monkeypatched
  probe + a monkeypatched mongo write.

These tests are hermetic — no network, no MongoDB — so they run fast
in CI.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# ───────────────────────── get_educator_user ─────────────────────────

def test_educator_dep_accepts_educator_and_admin():
    from fastapi import HTTPException
    from auth_deps import get_educator_user

    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(
            get_educator_user(user={"id": "u1", "role": "educator"})
        )["role"] == "educator"
        assert loop.run_until_complete(
            get_educator_user(user={"id": "u2", "role": "admin"})
        )["role"] == "admin"
        assert loop.run_until_complete(
            get_educator_user(user={"id": "u3", "is_admin": True})
        )["is_admin"] is True
        with pytest.raises(HTTPException) as ei:
            loop.run_until_complete(
                get_educator_user(user={"id": "u4", "role": "student"})
            )
        assert ei.value.status_code == 403
    finally:
        loop.close()


# ───────────────────────── probe_site_safety short-circuits ──────────

def test_probe_rejects_private_ip_literal():
    """IP literals are rejected up-front by the strict FQDN normaliser,
    so they fail as invalid_domain (even stronger than the private_ip
    branch — both prevent the probe from hitting localhost)."""
    from edu_reader import probe_site_safety
    loop = asyncio.new_event_loop()
    try:
        for bad in ("127.0.0.1", "10.0.0.1", "169.254.169.254"):
            res = loop.run_until_complete(probe_site_safety(bad))
            assert res["ok"] is False
            assert res["reason"] == "invalid_domain"
    finally:
        loop.close()


def test_probe_rejects_localhost_hostnames():
    """Non-IP hostnames that resolve to private addresses (localhost,
    .local, .internal) are caught by the FQDN regex before the
    private_ip branch — same outcome."""
    from edu_reader import probe_site_safety
    loop = asyncio.new_event_loop()
    try:
        for bad in ("localhost", "host.local", "service.internal"):
            res = loop.run_until_complete(probe_site_safety(bad))
            assert res["ok"] is False
            # Either caught by strict normaliser OR by the private_ip branch.
            assert res["reason"] in ("invalid_domain", "private_ip")
    finally:
        loop.close()


def test_probe_rejects_hard_denied():
    from edu_reader import probe_site_safety
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(probe_site_safety("pornhub.com"))
        assert res["ok"] is False
        assert res["reason"] == "hard_denied"
    finally:
        loop.close()


def test_probe_rejects_invalid_domain():
    from edu_reader import probe_site_safety
    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(probe_site_safety("no-dots-here"))
        assert res["ok"] is False
        assert res["reason"] == "invalid_domain"
    finally:
        loop.close()


# ───────────────────────── educator_submit_site (route) ──────────────

def _build_client(monkeypatch, probe_result: dict, educator_user: dict):
    """Spin up a minimal FastAPI app that mounts only the edu_browser
    router under /api. Dependency overrides inject a fake educator user
    and a monkeypatched probe function."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_deps import get_educator_user
    from routes import edu_browser as eb

    # Replace the probe with a deterministic stub.
    async def fake_probe(domain: str) -> dict:
        return {**probe_result, "url": f"https://{domain}/"}
    monkeypatch.setattr(eb, "probe_site_safety", fake_probe)

    # Simulate "already allowed" false / operator hard-block false.
    async def fake_is_allowed_url(url: str):
        return (False, "not_allowlisted")
    async def fake_is_hard_blocked(domain: str):
        return (False, "ok")
    monkeypatch.setattr(eb, "is_allowed_url", fake_is_allowed_url)
    monkeypatch.setattr(eb, "is_domain_hard_blocked", fake_is_hard_blocked)

    # Stub the mongo write performed by upsert_override so the test
    # never touches the DB.
    captured: dict = {}
    async def fake_upsert(domain, status="allowed", note="", actor="",
                          source="admin", extra=None):
        doc = {"domain": domain, "status": status, "note": note,
               "actor": actor, "source": source}
        if extra:
            doc["provenance"] = extra
        captured["doc"] = doc
        return doc
    monkeypatch.setattr(eb, "upsert_override", fake_upsert)

    app = FastAPI()
    app.include_router(eb.router, prefix="/api")
    app.dependency_overrides[get_educator_user] = lambda: educator_user
    return TestClient(app), captured


def test_educator_submit_auto_approves_safe_site(monkeypatch):
    probe = {
        "ok": True, "reason": "ok", "robots_ok": True,
        "http_status": 200, "kid_safe": True,
        "kid_safe_density": 0.0, "kid_safe_hits": [], "text_chars": 1800,
    }
    client, captured = _build_client(
        monkeypatch, probe, {"id": "e1", "email": "ms.barua@school.in", "role": "educator"},
    )
    r = client.post("/api/edu/educator/submit-site",
                    json={"domain": "example-edu.org", "note": "Grade 10 bio notes"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "auto_approved"
    assert body["domain"] == "example-edu.org"
    assert body["entry"]["source"] == "educator"
    assert body["entry"]["status"] == "allowed"
    assert "ms.barua@school.in" in body["entry"]["note"]
    assert "Grade 10 bio notes" in body["entry"]["note"]
    assert captured["doc"]["source"] == "educator"
    assert captured["doc"]["provenance"]["kid_safe_density"] == 0.0


def test_educator_submit_blocks_unsafe_site(monkeypatch):
    probe = {
        "ok": False, "reason": "unsafe_content", "robots_ok": True,
        "http_status": 200, "kid_safe": False,
        "kid_safe_density": 12.4, "kid_safe_hits": ["redacted"], "text_chars": 4000,
    }
    client, captured = _build_client(
        monkeypatch, probe, {"id": "e1", "email": "teacher@example.com", "role": "educator"},
    )
    r = client.post("/api/edu/educator/submit-site",
                    json={"domain": "sketchy-site.net"})
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "unsafe_content"
    assert "doc" not in captured  # upsert was not called


def test_educator_submit_rejects_robots_disallow(monkeypatch):
    probe = {
        "ok": False, "reason": "robots_disallow", "robots_ok": False,
        "http_status": None, "kid_safe": False,
        "kid_safe_density": 0.0, "kid_safe_hits": [], "text_chars": 0,
    }
    client, captured = _build_client(
        monkeypatch, probe, {"id": "e1", "role": "educator"},
    )
    r = client.post("/api/edu/educator/submit-site",
                    json={"domain": "blocked-by-robots.org"})
    assert r.status_code == 400
    assert r.json()["error"] == "robots_disallow"
    assert "doc" not in captured


def test_normalize_domain_rejects_userinfo_and_ports():
    """SSRF hardening: inputs like `evil.com@169.254.169.254`, `host:8080`,
    paths, and whitespace must normalise to empty (→ invalid_domain)."""
    from edu_allowlist import _normalize_domain
    bad_inputs = [
        "evil.com@169.254.169.254",
        "host:8080",
        "foo/bar",
        "foo bar.com",
        "192.168.1.1",                # IP literal — rejected by FQDN regex
        "user:pass@example.com",
        "example..com",               # empty label
        "-leading.example.com",
        "example.com-",
        "",
    ]
    for b in bad_inputs:
        assert _normalize_domain(b) == "", f"{b!r} should be rejected"
    # Legitimate domains still normalise cleanly.
    assert _normalize_domain("WWW.Example.org") == "example.org"
    assert _normalize_domain("https://en.wikipedia.org/wiki/Foo") == "en.wikipedia.org"
    assert _normalize_domain("ahsec.assam.gov.in") == "ahsec.assam.gov.in"


def test_educator_submit_rejects_malicious_domain_shapes(monkeypatch):
    """The endpoint must 400 before any network work when the user
    tries to smuggle an IP / userinfo via the domain field."""
    probe = {"ok": True, "reason": "ok", "robots_ok": True,
             "http_status": 200, "kid_safe": True,
             "kid_safe_density": 0.0, "kid_safe_hits": [], "text_chars": 1800}
    client, captured = _build_client(
        monkeypatch, probe, {"id": "e1", "role": "educator"},
    )
    for bad in ["evil.com@169.254.169.254", "localhost:8080",
                "192.168.1.1", "host/../etc/passwd"]:
        r = client.post("/api/edu/educator/submit-site", json={"domain": bad})
        assert r.status_code == 400, f"{bad!r} should 400, got {r.status_code}"
    assert "doc" not in captured


def test_educator_submit_rejects_operator_blocked_domain(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth_deps import get_educator_user
    from routes import edu_browser as eb

    async def fake_is_allowed_url(url: str):
        return (False, "operator_blocked")
    async def fake_is_hard_blocked(domain: str):
        return (True, "operator_blocked")
    # If this is ever reached, the test should fail loudly.
    async def fake_probe(domain: str):
        raise AssertionError("probe must not run for blocked domain")
    async def fake_upsert(*args, **kwargs):
        raise AssertionError("upsert must not run for blocked domain")
    monkeypatch.setattr(eb, "is_allowed_url", fake_is_allowed_url)
    monkeypatch.setattr(eb, "is_domain_hard_blocked", fake_is_hard_blocked)
    monkeypatch.setattr(eb, "probe_site_safety", fake_probe)
    monkeypatch.setattr(eb, "upsert_override", fake_upsert)

    app = FastAPI()
    app.include_router(eb.router, prefix="/api")
    app.dependency_overrides[get_educator_user] = lambda: {"id": "e1", "role": "educator"}
    client = TestClient(app)

    r = client.post("/api/edu/educator/submit-site", json={"domain": "blocked-by-admin.org"})
    assert r.status_code == 403
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "operator_blocked"


def test_probe_rejects_public_fqdn_resolving_private(monkeypatch):
    """DNS-based SSRF: if a public-looking hostname resolves to an
    RFC1918 / link-local IP, probe must reject before any HTTP fetch."""
    import edu_reader

    async def fake_resolve(host: str):
        return (False, "private_ip")
    monkeypatch.setattr(edu_reader, "_resolves_to_public_ip", fake_resolve)

    called = {"robots": 0, "http": 0}
    async def fail_robots(url: str):
        called["robots"] += 1
        return True
    monkeypatch.setattr(edu_reader, "_robots_allows", fail_robots)

    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(edu_reader.probe_site_safety("malicious-dns.example"))
        assert res["ok"] is False
        assert res["reason"] == "private_ip"
        assert called["robots"] == 0, "robots/http must not run when DNS fails guard"
    finally:
        loop.close()


def test_probe_dns_failure_is_rejected(monkeypatch):
    """Fail-closed when DNS cannot resolve the host at all."""
    import edu_reader

    async def fake_resolve(host: str):
        return (False, "dns_failed")
    monkeypatch.setattr(edu_reader, "_resolves_to_public_ip", fake_resolve)

    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(edu_reader.probe_site_safety("nx-domain.example"))
        assert res["ok"] is False
        assert res["reason"] == "dns_failed"
    finally:
        loop.close()


def test_probe_redirect_rejects_public_host_resolving_private(monkeypatch):
    """Per-hop DNS SSRF: the probe's manual redirect loop must run the
    DNS-to-public check on every Location target, not just the initial
    submission. A public-looking hostname that resolves to an internal
    IP must abort the probe mid-chain."""
    import edu_reader

    # Initial host resolves public; first redirect host resolves private.
    resolve_map = {
        "legit-start.example": (True, "ok"),
        "sneaky-redirect.example": (False, "private_ip"),
    }
    async def fake_resolve(host: str):
        return resolve_map.get(host, (True, "ok"))
    monkeypatch.setattr(edu_reader, "_resolves_to_public_ip", fake_resolve)

    async def allow_robots(url: str):
        return True
    monkeypatch.setattr(edu_reader, "_robots_allows", allow_robots)

    class _Resp:
        def __init__(self, status, headers=None, content=b"", url=""):
            self.status_code = status
            self.headers = headers or {}
            self.content = content
            self.encoding = "utf-8"
            self.url = url

    class _Client:
        def __init__(self, *a, **kw):
            self.kw = kw
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, *a, **kw):
            if url.startswith("https://legit-start.example"):
                return _Resp(302, {"location": "https://sneaky-redirect.example/"}, b"", url)
            return _Resp(200, {"content-type": "text/html"},
                         b"<html><body>" + b"<p>safe content here " * 30 + b"</p></body></html>", url)

    monkeypatch.setattr(edu_reader.httpx, "AsyncClient", _Client)

    loop = asyncio.new_event_loop()
    try:
        res = loop.run_until_complete(edu_reader.probe_site_safety("legit-start.example"))
        assert res["ok"] is False
        assert res["reason"] == "redirect_private_ip"
    finally:
        loop.close()


def test_fetch_robots_disables_auto_redirects(monkeypatch):
    """Defence-in-depth: _fetch_robots must use follow_redirects=False
    so a hostile /robots.txt cannot pivot into internal space via a
    302. We assert on the AsyncClient kwargs captured at construction."""
    import edu_reader

    captured_kwargs: dict = {}

    class _StubResp:
        status_code = 200
        text = "User-agent: *\nAllow: /\n"
        headers: dict = {}

    class _StubClient:
        def __init__(self, *args, **kwargs):
            captured_kwargs.update(kwargs)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def get(self, url, headers=None):
            return _StubResp()

    monkeypatch.setattr(edu_reader.httpx, "AsyncClient", _StubClient)
    edu_reader._robots_cache.clear()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(edu_reader._fetch_robots("example.org", "https"))
    finally:
        loop.close()
    assert captured_kwargs.get("follow_redirects") is False


def test_educator_submit_requires_educator_role():
    """Without the dependency override, the endpoint must reject
    non-educator callers via the real get_educator_user dep. We simulate
    this by overriding with a HTTP 403 raiser."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from auth_deps import get_educator_user
    from routes import edu_browser as eb

    app = FastAPI()
    app.include_router(eb.router, prefix="/api")

    def _forbid():
        raise HTTPException(status_code=403, detail="Educator role required")
    app.dependency_overrides[get_educator_user] = _forbid

    client = TestClient(app)
    r = client.post("/api/edu/educator/submit-site", json={"domain": "x.com"})
    assert r.status_code == 403
