"""Task #793 — guard the StreamingResponse cookie-propagation
regression that the architect review flagged as the critical
production blocker.

The chat dependency (``auth_deps.rate_limit_chat_optional``) calls
``set_cookie`` on the FastAPI-injected ``Response`` object. That
mechanism works fine when the route returns a JSON-serialisable
value, because FastAPI builds the wire response from the injected
``Response``. It silently fails when the route returns its own
``Response`` instance (e.g. ``StreamingResponse`` for SSE streaming),
because FastAPI uses the route's response and discards the injected
one. The ``/ai/chat/stream`` SSE endpoint is the actual user-facing
chat path on Syrabit, so the silent-failure mode meant the device
cookie was *never* getting persisted in production — collapsing the
new per-device 30/day cap back to the coarse per-IP cap and undoing
the entire CGNAT/school-WiFi fix this task exists for.

The fix in ``server.py`` is to install ``DeviceCookieMiddleware``,
which transplants any pending device cookie (stashed on
``request.state.device_cookie_to_set`` by the dependency) onto the
final outgoing response. This test mounts a tiny FastAPI app that
mirrors the production wiring — the real dependency, the real
middleware — and verifies a ``StreamingResponse`` route really does
end up carrying the ``Set-Cookie: syrabit_device=…`` header that
the dependency minted.
"""
import pytest

from tests._deps_stub import install_deps_stub

install_deps_stub(force=True)

import auth_deps  # noqa: E402
import db_ops  # noqa: E402
import deps  # noqa: E402
from device_token import DEVICE_COOKIE_NAME, mint_device_token, device_token_id  # noqa: E402

fakeredis = pytest.importorskip("fakeredis")
fastapi = pytest.importorskip("fastapi")
from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from middleware import DeviceCookieMiddleware  # noqa: E402


@pytest.fixture
def app(monkeypatch):
    """Build a minimal FastAPI app that mirrors the production wiring
    around the chat rate-limit dependency: real dependency, real
    middleware, fakeredis-backed counters, per-minute throttle
    bypassed so we isolate cookie behaviour.
    """
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(auth_deps, "redis_client", fake, raising=False)
    monkeypatch.setattr(db_ops, "redis_client", fake, raising=False)
    monkeypatch.setattr(deps, "redis_client", fake, raising=False)
    monkeypatch.setattr(auth_deps, "check_rate_limit", lambda *a, **kw: True)

    app = FastAPI()
    app.add_middleware(DeviceCookieMiddleware)

    async def _stream():
        # Two tiny SSE-style chunks so the response is unambiguously
        # a StreamingResponse, not something FastAPI could decide to
        # re-wrap as JSON.
        yield b"data: hello\n\n"
        yield b"data: world\n\n"

    @app.post("/stream")
    async def stream_route(_=Depends(auth_deps.rate_limit_chat_optional)):
        # Mirrors `/ai/chat/stream` — returns a concrete Response,
        # so FastAPI does NOT merge the dependency-injected Response.
        # The middleware is the only thing that can make the device
        # cookie reach the wire.
        return StreamingResponse(_stream(), media_type="text/event-stream")

    @app.post("/json")
    async def json_route(_=Depends(auth_deps.rate_limit_chat_optional)):
        # Mirrors `/ai/chat` — returns a dict, so FastAPI builds the
        # response from the injected Response. The middleware should
        # NOT double-set the cookie here.
        return {"ok": True}

    return app, fake


def test_streaming_response_persists_device_cookie_on_first_visit(app):
    """Regression for the architect's primary blocker: a fresh
    anonymous client hitting the streaming chat path must receive a
    Set-Cookie header carrying the signed device token.
    """
    fastapi_app, _ = app
    client = TestClient(fastapi_app)
    resp = client.post(
        "/stream",
        headers={"cf-connecting-ip": "192.0.2.41"},
        json={"message": "hi"},
    )
    assert resp.status_code == 200, resp.text
    set_cookies = resp.headers.get("set-cookie", "")
    assert DEVICE_COOKIE_NAME in set_cookies, (
        f"streaming response must carry a {DEVICE_COOKIE_NAME} cookie; "
        f"got headers={dict(resp.headers)}"
    )
    # And the cookie really is a valid signed token (not garbage).
    cookie_value = client.cookies.get(DEVICE_COOKIE_NAME)
    assert cookie_value, "TestClient should have stored the cookie"
    assert device_token_id(cookie_value) is not None, (
        "the cookie value the middleware emitted must verify"
    )


def test_streaming_response_does_not_double_set_cookie(app, monkeypatch):
    """When the dependency *also* set the cookie on the injected
    Response (the JSON route path), the middleware must not append a
    second Set-Cookie for the same name. This guards against subtle
    cookie-stomping bugs where the second value (different token)
    overwrites the first in the browser jar.
    """
    fastapi_app, _ = app
    client = TestClient(fastapi_app)
    resp = client.post(
        "/json",
        headers={"cf-connecting-ip": "192.0.2.42"},
        json={"message": "hi"},
    )
    assert resp.status_code == 200, resp.text
    # ``raw`` exposes every Set-Cookie individually (httpx joins them
    # with ", " on `.headers["set-cookie"]` which is ambiguous when
    # cookies themselves contain commas, e.g. an Expires field).
    raw_cookies = [
        v for (k, v) in resp.headers.raw
        if k.lower() == b"set-cookie"
    ]
    device_cookies = [
        c for c in raw_cookies if c.startswith(DEVICE_COOKIE_NAME.encode() + b"=")
    ]
    assert len(device_cookies) == 1, (
        f"expected exactly one {DEVICE_COOKIE_NAME} Set-Cookie, "
        f"got {len(device_cookies)}: {device_cookies!r}"
    )


def test_streaming_response_with_valid_cookie_does_not_remint(app):
    """A returning visitor who already has a valid cookie must NOT
    get a fresh Set-Cookie on every request — that would churn the
    token id on every call and silently reset the daily counter on
    each request, completely breaking quota enforcement.
    """
    fastapi_app, _ = app
    client = TestClient(fastapi_app)
    existing = mint_device_token()
    client.cookies.set(DEVICE_COOKIE_NAME, existing)
    resp = client.post(
        "/stream",
        headers={"cf-connecting-ip": "192.0.2.43"},
        json={"message": "hi"},
    )
    assert resp.status_code == 200, resp.text
    assert DEVICE_COOKIE_NAME not in resp.headers.get("set-cookie", ""), (
        "valid cookies must not be rewritten on every request"
    )


def test_streaming_response_per_device_quota_enforced_after_first_visit(app):
    """End-to-end: after the cookie round-trip, subsequent requests
    from the same TestClient (which automatically carries the cookie
    forward) must be charged against the per-device 30/day counter
    and 429 on the 32nd request (1 first-visit + 30 charged + 1
    over-cap).
    """
    fastapi_app, _ = app
    client = TestClient(fastapi_app)
    headers = {"cf-connecting-ip": "192.0.2.44"}

    # First visit — mints cookie, succeeds, NOT charged against the
    # 30/day device counter (the dependency intentionally skips the
    # device-deduct on first visit).
    r0 = client.post("/stream", headers=headers, json={"m": "x"})
    assert r0.status_code == 200
    assert client.cookies.get(DEVICE_COOKIE_NAME)

    # Next 30 calls with the cookie — all should succeed.
    for i in range(30):
        r = client.post("/stream", headers=headers, json={"m": "x"})
        assert r.status_code == 200, (
            f"request {i + 1}/30 unexpectedly returned {r.status_code}: {r.text}"
        )

    # 31st cookied call — must trip the per-device cap, NOT the
    # coarse per-IP cap.
    r_over = client.post("/stream", headers=headers, json={"m": "x"})
    assert r_over.status_code == 429
    detail = r_over.json().get("detail", "")
    assert "Daily" in detail or "quota" in detail.lower(), (
        f"expected per-device-quota 429, got: {detail!r}"
    )
