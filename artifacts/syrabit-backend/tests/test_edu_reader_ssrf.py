"""SSRF regression tests for ``edu_reader.fetch_and_extract``.

The reader is the public entry-point that turns an external URL into
clean article HTML/text for the AI pipeline. It is the single most
attractive SSRF sink in the backend: a hostile site or admin override
can point the reader at ``127.0.0.1`` / ``169.254.169.254`` / any
RFC1918 address and exfiltrate metadata, hit internal services, or
probe the cluster network.

The defences live in ``edu_reader``:

* ``is_allowed_url`` — textual scheme + private-IP literal check
* ``_validate_host_for_ssrf`` — re-checks the parsed host
* ``_resolves_to_public_ip`` — DNS-time guard for FQDNs that resolve
  to private space (cloud metadata, internal CNAMEs, DNS rebinding)
* ``_safe_get_with_redirects`` — manual redirect follower that reruns
  the full host validation on every hop and caps at ``max_hops``

These tests pin every layer so a future refactor that re-introduces
``follow_redirects=True`` or quietly drops the DNS helper fails CI
loudly instead of silently regressing the SSRF posture.
"""
from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

import httpx
import pytest


_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import edu_reader  # noqa: E402


# ───────────────────────── helpers ─────────────────────────


def _install_loop_with_dns(monkeypatch, dns_map: dict[str, str]) -> asyncio.AbstractEventLoop:
    """Install a fresh event loop whose ``getaddrinfo`` is mocked.

    Each entry in ``dns_map`` maps ``hostname -> ip_string``. Any host
    not in the map raises ``socket.gaierror`` (mirrors a real DNS NXDOMAIN).
    Patching the loop method (rather than ``socket.getaddrinfo``) lets
    ``_resolves_to_public_ip`` exercise its real ``await
    loop.getaddrinfo(...)`` codepath.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _fake_getaddrinfo(host, port, *args, **kwargs):
        if host in dns_map:
            ip = dns_map[host]
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            return [(family, socket.SOCK_STREAM, 6, "", (ip, port or 0))]
        raise socket.gaierror(f"mocked NXDOMAIN for {host!r}")

    # Bind directly on the loop instance so callers using
    # ``asyncio.get_event_loop().getaddrinfo(...)`` see the fake.
    loop.getaddrinfo = _fake_getaddrinfo  # type: ignore[assignment]
    return loop


def _patch_httpx(monkeypatch, handler) -> None:
    """Force ``edu_reader``'s ``httpx.AsyncClient`` to use a MockTransport.

    Every GET issued by the reader (robots.txt, the article fetch,
    every redirect hop) is routed through ``handler``. The handler
    receives an ``httpx.Request`` and must return an ``httpx.Response``.
    """
    transport = httpx.MockTransport(handler)
    OrigClient = httpx.AsyncClient

    class _MockClient(OrigClient):
        def __init__(self, *args, **kwargs):
            kwargs.pop("limits", None)  # MockTransport ignores limits
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(edu_reader.httpx, "AsyncClient", _MockClient)


def _reset_reader_state() -> None:
    """Clear caches so test ordering can't mask a regression."""
    edu_reader._robots_cache.clear()
    for key in list(edu_reader._reader_metrics):
        edu_reader._reader_metrics[key] = 0


def _redirect(url: str, location: str, status: int = 302) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"location": location},
        request=httpx.Request("GET", url),
    )


def _ok_html(url: str, body: bytes | None = None) -> httpx.Response:
    body = body or _SAMPLE_HTML
    return httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8"},
        content=body,
        request=httpx.Request("GET", url),
    )


_SAMPLE_HTML = (
    b"<html><head><title>Limit (mathematics)</title></head>"
    b"<body><article>"
    b"<h1>Limit</h1>"
    + (b"<p>" + (b"In mathematics, a limit is the value that a function approaches "
                 b"as the input approaches some value. ") * 6 + b"</p>") * 4
    + b"</article></body></html>"
)


# ───────────────────────── tests ─────────────────────────


def test_direct_loopback_hostname_is_blocked(monkeypatch):
    """A bare ``http://127.0.0.1/`` URL never opens a socket.

    ``is_allowed_url`` rejects the IP-literal pre-flight, so the reader
    short-circuits with ``error == 'not_allowed'`` and the mock HTTP
    transport (which would 500 on any call) is never invoked.
    """
    _reset_reader_state()

    def _handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"loopback fetch leaked to network: {request.url}")

    loop = _install_loop_with_dns(monkeypatch, {})
    _patch_httpx(monkeypatch, _handler)

    result = loop.run_until_complete(
        edu_reader.fetch_and_extract("http://127.0.0.1/admin", bypass_cache=True)
    )
    assert result["ok"] is False
    # Either pre-allowlist rejection or post-allowlist host validation —
    # both are acceptable defences as long as the request is refused.
    assert result["error"] in {"not_allowed", "host_blocked"}
    assert result.get("detail") in {"private_ip", "scheme", "not_allowlisted"}


def test_localhost_alias_is_blocked(monkeypatch):
    """``http://localhost/`` and friends are blocked by the textual SSRF guard."""
    _reset_reader_state()

    def _handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"localhost fetch leaked to network: {request.url}")

    loop = _install_loop_with_dns(monkeypatch, {})
    _patch_httpx(monkeypatch, _handler)

    result = loop.run_until_complete(
        edu_reader.fetch_and_extract("http://localhost:8080/", bypass_cache=True)
    )
    assert result["ok"] is False
    assert result["error"] in {"not_allowed", "host_blocked"}


def test_fqdn_resolving_to_private_ip_is_blocked(monkeypatch):
    """A public-looking allowlisted FQDN that resolves into RFC1918 fails closed.

    This is the DNS-rebinding / metadata-IP attack: ``en.wikipedia.org``
    passes ``is_allowed_url`` textually, so the reader also has to
    resolve the host and reject any answer that lands in private space.
    Removing ``_resolves_to_public_ip`` would silently re-open this hole.
    """
    _reset_reader_state()

    def _handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"private-IP fetch leaked to network: {request.url}")

    loop = _install_loop_with_dns(monkeypatch, {"en.wikipedia.org": "10.0.0.7"})
    _patch_httpx(monkeypatch, _handler)

    result = loop.run_until_complete(
        edu_reader.fetch_and_extract(
            "https://en.wikipedia.org/wiki/Limit", bypass_cache=True,
        )
    )
    assert result["ok"] is False
    assert result["error"] == "host_blocked"
    assert result["detail"] == "private_ip"


def test_redirect_to_private_ip_is_blocked(monkeypatch):
    """A 302 from an allowlisted host pointing at ``127.0.0.1`` must be rejected.

    Reproduces the canonical ``follow_redirects=True`` SSRF: a hostile
    ``robots.txt`` or article URL returns ``Location: http://127.0.0.1/``
    and httpx's auto-follower would obediently fetch it. Our manual
    redirect helper re-runs ``_validate_host_for_ssrf`` on every hop.
    """
    _reset_reader_state()

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(404, request=request)
        if "wikipedia.org/wiki/Limit" in url:
            return _redirect(url, "http://127.0.0.1/admin")
        # The reader must never reach the loopback target.
        raise AssertionError(f"redirect followed into private space: {url}")

    loop = _install_loop_with_dns(monkeypatch, {"en.wikipedia.org": "151.101.1.1"})
    _patch_httpx(monkeypatch, _handler)

    result = loop.run_until_complete(
        edu_reader.fetch_and_extract(
            "https://en.wikipedia.org/wiki/Limit", bypass_cache=True,
        )
    )
    assert result["ok"] is False
    assert result["error"] == "redirect_not_allowed"
    assert result["detail"] == "redirect_private_ip"


def test_redirect_to_fqdn_resolving_private_is_blocked(monkeypatch):
    """A 302 to an allowlisted FQDN whose DNS resolves to a private IP fails closed.

    Belt-and-braces: even when neither hop is an IP literal, the
    per-hop DNS check must catch a CNAME/A flip that points the second
    hop at internal infrastructure.
    """
    _reset_reader_state()

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(404, request=request)
        if url == "https://en.wikipedia.org/wiki/Limit":
            return _redirect(url, "https://internal.example.ac.in/secret")
        raise AssertionError(f"redirect followed past DNS guard: {url}")

    loop = _install_loop_with_dns(monkeypatch, {
        "en.wikipedia.org": "151.101.1.1",
        "internal.example.ac.in": "10.4.5.6",
    })
    _patch_httpx(monkeypatch, _handler)

    result = loop.run_until_complete(
        edu_reader.fetch_and_extract(
            "https://en.wikipedia.org/wiki/Limit", bypass_cache=True,
        )
    )
    assert result["ok"] is False
    assert result["error"] == "redirect_not_allowed"
    assert result["detail"] == "redirect_private_ip"


def test_redirect_chain_exceeding_max_hops_is_rejected(monkeypatch):
    """A long redirect chain is bounded by ``_safe_get_with_redirects(max_hops=5)``.

    Without the cap a hostile server could hold the worker open forever
    while bouncing between allowlisted-looking hosts; this test asserts
    we stop with a clean ``too_many_redirects`` rejection.
    """
    _reset_reader_state()

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(404, request=request)
        # Walk an indefinitely long chain on the same allowlisted host.
        if "/hop/" in url or url.endswith("/wiki/Limit"):
            try:
                n = int(url.rsplit("/", 1)[-1]) if "/hop/" in url else 0
            except ValueError:
                n = 0
            return _redirect(url, f"https://en.wikipedia.org/hop/{n + 1}")
        raise AssertionError(f"unexpected URL: {url}")

    loop = _install_loop_with_dns(monkeypatch, {"en.wikipedia.org": "151.101.1.1"})
    _patch_httpx(monkeypatch, _handler)

    result = loop.run_until_complete(
        edu_reader.fetch_and_extract(
            "https://en.wikipedia.org/wiki/Limit", bypass_cache=True,
        )
    )
    assert result["ok"] is False
    assert result["error"] == "redirect_not_allowed"
    assert result["detail"] == "too_many_redirects"


def test_happy_path_public_url_succeeds(monkeypatch):
    """Sanity check: an allowlisted host with a public IP and well-formed
    HTML still extracts cleanly. Without this baseline the SSRF tests
    above could be passing because *every* fetch is being rejected."""
    _reset_reader_state()

    def _handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(404, request=request)
        if url == "https://en.wikipedia.org/wiki/Limit":
            return _ok_html(url)
        raise AssertionError(f"unexpected URL: {url}")

    loop = _install_loop_with_dns(monkeypatch, {"en.wikipedia.org": "151.101.1.1"})
    _patch_httpx(monkeypatch, _handler)

    result = loop.run_until_complete(
        edu_reader.fetch_and_extract(
            "https://en.wikipedia.org/wiki/Limit", bypass_cache=True,
        )
    )
    assert result["ok"] is True, result
    assert result["domain"] == "en.wikipedia.org"
    assert result["url"] == "https://en.wikipedia.org/wiki/Limit"
    assert "limit" in result["text"].lower()
    assert result["char_count"] >= 80
    assert result["from_cache"] is False
