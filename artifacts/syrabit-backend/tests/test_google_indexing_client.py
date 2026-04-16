"""Tests for SEO Phase C — Google Indexing API client + sitemap-ping wiring.

Covers the pure-helper behavior of `google_indexing_client` (quota cap,
stats counters, service-account loading, disabled/missing-secret graceful
paths), the `_ping_google_sitemap` wrapper in routes.bot_discovery, and
the end-to-end hook that `diff_sitemap_against_submitted` fires a sitemap
ping whenever there is at least one queued URL.

All outbound HTTP is mocked via httpx.AsyncClient monkeypatches — no real
network traffic.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from tests._deps_stub import install_deps_stub  # noqa: E402

install_deps_stub()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Minimal fake service-account JSON (valid structure, irrelevant key).
# We monkeypatch _mint_access_token so the fake private_key is never parsed.
# ---------------------------------------------------------------------------

_FAKE_SA = {
    "type": "service_account",
    "client_email": "syrabit-indexing@example.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "token_uri": "https://oauth2.googleapis.com/token",
}


def _fresh_client(monkeypatch, *, enabled=True, limit=None, sa_json=None,
                  token="fake-token"):
    import google_indexing_client as gic

    # Reset all module-level state so tests don't leak into each other.
    gic._reset_state_for_tests()

    if enabled:
        monkeypatch.setenv("GOOGLE_INDEXING_ENABLED", "true")
    else:
        monkeypatch.setenv("GOOGLE_INDEXING_ENABLED", "false")

    if limit is not None:
        monkeypatch.setenv("GOOGLE_INDEXING_DAILY_LIMIT", str(limit))
    else:
        monkeypatch.delenv("GOOGLE_INDEXING_DAILY_LIMIT", raising=False)

    if sa_json is None:
        monkeypatch.setenv("GOOGLE_INDEXING_SERVICE_ACCOUNT", json.dumps(_FAKE_SA))
    elif sa_json == "__missing__":
        monkeypatch.delenv("GOOGLE_INDEXING_SERVICE_ACCOUNT", raising=False)
    else:
        monkeypatch.setenv("GOOGLE_INDEXING_SERVICE_ACCOUNT", sa_json)

    # Short-circuit the real JWT+OAuth exchange so we never touch
    # google-auth's crypto stack in tests.
    async def _fake_mint():
        return token

    monkeypatch.setattr(gic, "_mint_access_token", _fake_mint)
    return gic


class _FakeResponse:
    def __init__(self, status_code=200, text="", json_body=None):
        self.status_code = status_code
        self.text = text
        self._json = json_body

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _FakeAsyncClient:
    """Drop-in for httpx.AsyncClient used as `async with` context manager."""

    def __init__(self, *, post_response=None, get_response=None,
                 post_side_effect=None, get_side_effect=None):
        self._post_response = post_response
        self._get_response = get_response
        self._post_side_effect = post_side_effect
        self._get_side_effect = get_side_effect
        self.post_calls = []
        self.get_calls = []

    def __call__(self, *a, **kw):  # support both patterns
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if self._post_side_effect is not None:
            raise self._post_side_effect
        return self._post_response or _FakeResponse(200, "{}")

    async def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if self._get_side_effect is not None:
            raise self._get_side_effect
        return self._get_response or _FakeResponse(200, "OK")


def _install_httpx(monkeypatch, gic, fake_client: _FakeAsyncClient):
    """Patch httpx.AsyncClient inside the client module to return fake_client."""
    class _Factory:
        def __init__(self, *a, **kw):
            pass
        async def __aenter__(self_inner):
            return fake_client
        async def __aexit__(self_inner, *a):
            return False

    monkeypatch.setattr(gic.httpx, "AsyncClient", _Factory)


# ---------------------------------------------------------------------------
# Service-account loading
# ---------------------------------------------------------------------------

def test_missing_secret_disables_indexing_but_not_ping(monkeypatch):
    gic = _fresh_client(monkeypatch, sa_json="__missing__")
    res = _run(gic.notify_url_updated("https://syrabit.ai/foo"))
    assert res["status"] == "skipped"
    assert res["reason"] == "no_service_account"
    stats = gic.get_stats()
    assert stats["service_account_loaded"] is False
    assert stats["service_account_error"] == "missing_secret"
    assert stats["sent"] == 0


def test_base64_encoded_secret_is_decoded(monkeypatch):
    b64 = base64.b64encode(json.dumps(_FAKE_SA).encode()).decode()
    gic = _fresh_client(monkeypatch, sa_json=b64)
    info = gic._load_service_account()
    assert info is not None
    assert info["client_email"] == _FAKE_SA["client_email"]


def test_malformed_secret_logged_and_skipped(monkeypatch):
    gic = _fresh_client(monkeypatch, sa_json="not-json-and-not-b64!!!")
    info = gic._load_service_account()
    assert info is None
    stats = gic.get_stats()
    assert stats["service_account_loaded"] is False


def test_service_account_missing_required_field(monkeypatch):
    bad = dict(_FAKE_SA)
    del bad["client_email"]
    gic = _fresh_client(monkeypatch, sa_json=json.dumps(bad))
    info = gic._load_service_account()
    assert info is None
    stats = gic.get_stats()
    assert "missing_fields" in (stats["service_account_error"] or "")


# ---------------------------------------------------------------------------
# notify_url_updated happy path + quota + errors
# ---------------------------------------------------------------------------

def test_notify_url_updated_happy_path(monkeypatch):
    gic = _fresh_client(monkeypatch)
    fake = _FakeAsyncClient(post_response=_FakeResponse(200, "{}"))
    _install_httpx(monkeypatch, gic, fake)

    res = _run(gic.notify_url_updated("https://syrabit.ai/ahsec/class-12/physics"))
    assert res["status"] == "ok"
    assert res["http_status"] == 200
    # Verified the right endpoint + payload shape.
    assert len(fake.post_calls) == 1
    url, kwargs = fake.post_calls[0]
    assert url == gic.INDEXING_API_URL
    assert kwargs["json"]["type"] == "URL_UPDATED"
    assert kwargs["json"]["url"].endswith("/physics")
    assert kwargs["headers"]["Authorization"].startswith("Bearer ")

    stats = gic.get_stats()
    assert stats["sent"] == 1
    assert stats["status_2xx"] == 1


def test_daily_quota_stops_further_sends(monkeypatch):
    gic = _fresh_client(monkeypatch, limit=2)
    fake = _FakeAsyncClient(post_response=_FakeResponse(200, "{}"))
    _install_httpx(monkeypatch, gic, fake)

    r1 = _run(gic.notify_url_updated("https://syrabit.ai/a"))
    r2 = _run(gic.notify_url_updated("https://syrabit.ai/b"))
    r3 = _run(gic.notify_url_updated("https://syrabit.ai/c"))

    assert r1["status"] == "ok"
    assert r2["status"] == "ok"
    assert r3["status"] == "quota_blocked"
    assert len(fake.post_calls) == 2  # third never hit the network
    stats = gic.get_stats()
    assert stats["sent"] == 2
    assert stats["quota_blocks"] == 1
    assert stats["quota_remaining"] == 0


def test_notify_url_updated_429_records_quota_error(monkeypatch):
    gic = _fresh_client(monkeypatch)
    fake = _FakeAsyncClient(post_response=_FakeResponse(429, "Too Many"))
    _install_httpx(monkeypatch, gic, fake)
    res = _run(gic.notify_url_updated("https://syrabit.ai/x"))
    assert res["status"] == "quota_error"
    stats = gic.get_stats()
    assert stats["status_4xx"] == 1


def test_notify_url_updated_auth_error_clears_token_cache(monkeypatch):
    gic = _fresh_client(monkeypatch)
    fake = _FakeAsyncClient(post_response=_FakeResponse(401, "invalid token"))
    _install_httpx(monkeypatch, gic, fake)
    # Pre-seed the token cache so the 401 handler actually clears something.
    _run(gic._get_cached_token())
    assert gic._cached_token is not None

    res = _run(gic.notify_url_updated("https://syrabit.ai/y"))
    assert res["status"] == "auth_error"
    assert gic._cached_token_expires_at == 0.0
    stats = gic.get_stats()
    assert stats["status_4xx"] == 1


def test_notify_url_updated_network_error_never_raises(monkeypatch):
    gic = _fresh_client(monkeypatch)
    fake = _FakeAsyncClient(post_side_effect=RuntimeError("network down"))
    _install_httpx(monkeypatch, gic, fake)
    res = _run(gic.notify_url_updated("https://syrabit.ai/z"))
    assert res["status"] == "error"
    assert res["reason"] == "RuntimeError"
    stats = gic.get_stats()
    assert stats["errors"] == 1


def test_notify_url_updated_disabled_killswitch(monkeypatch):
    gic = _fresh_client(monkeypatch, enabled=False)
    res = _run(gic.notify_url_updated("https://syrabit.ai/a"))
    assert res["status"] == "skipped"
    assert res["reason"] == "disabled"


def test_notify_url_updated_empty_url(monkeypatch):
    gic = _fresh_client(monkeypatch)
    res = _run(gic.notify_url_updated(""))
    assert res["status"] == "skipped"
    assert res["reason"] == "empty_url"


# ---------------------------------------------------------------------------
# ping_sitemap
# ---------------------------------------------------------------------------

def test_ping_sitemap_happy_path(monkeypatch):
    gic = _fresh_client(monkeypatch)
    fake = _FakeAsyncClient(get_response=_FakeResponse(200, "OK"))
    _install_httpx(monkeypatch, gic, fake)
    res = _run(gic.ping_sitemap("https://syrabit.ai/sitemap-index.xml"))
    assert res["status"] == "ok"
    assert len(fake.get_calls) == 1
    ping_url, _ = fake.get_calls[0]
    # URL-encoded sitemap param.
    assert ping_url.startswith("https://www.google.com/ping?sitemap=")
    assert "sitemap-index.xml" in ping_url
    stats = gic.get_stats()
    assert stats["sitemap_ping_sent"] == 1
    assert stats["sitemap_ping_2xx"] == 1


def test_ping_sitemap_network_error(monkeypatch):
    gic = _fresh_client(monkeypatch)
    fake = _FakeAsyncClient(get_side_effect=RuntimeError("boom"))
    _install_httpx(monkeypatch, gic, fake)
    res = _run(gic.ping_sitemap())
    assert res["status"] == "error"
    stats = gic.get_stats()
    assert stats["sitemap_ping_errors"] == 1


def test_ping_sitemap_disabled_skips_without_calling(monkeypatch):
    gic = _fresh_client(monkeypatch, enabled=False)
    fake = _FakeAsyncClient(get_response=_FakeResponse(200, "OK"))
    _install_httpx(monkeypatch, gic, fake)
    res = _run(gic.ping_sitemap())
    assert res["status"] == "skipped"
    assert res["reason"] == "disabled"
    assert len(fake.get_calls) == 0


# ---------------------------------------------------------------------------
# token caching
# ---------------------------------------------------------------------------

def test_token_is_cached_across_calls(monkeypatch):
    gic = _fresh_client(monkeypatch)
    fake = _FakeAsyncClient(post_response=_FakeResponse(200, "{}"))
    _install_httpx(monkeypatch, gic, fake)

    call_count = {"n": 0}

    async def _fake_mint_counting():
        call_count["n"] += 1
        return "t"

    monkeypatch.setattr(gic, "_mint_access_token", _fake_mint_counting)
    _run(gic.notify_url_updated("https://syrabit.ai/a"))
    _run(gic.notify_url_updated("https://syrabit.ai/b"))
    assert call_count["n"] == 1  # minted once, reused for 2nd POST


def test_token_refresh_is_single_flight(monkeypatch):
    """Five coroutines race to get a token from an empty cache. The
    single-flight lock must ensure only one mint call actually happens;
    the other four should wait and reuse the freshly-cached token."""
    gic = _fresh_client(monkeypatch)

    call_count = {"n": 0}
    started = asyncio.Event()

    async def _slow_mint():
        call_count["n"] += 1
        started.set()
        # Simulate a slow token-endpoint round-trip; other coroutines will
        # pile up on the refresh lock during this sleep.
        await asyncio.sleep(0.05)
        return "single-flight-token"

    monkeypatch.setattr(gic, "_mint_access_token", _slow_mint)

    async def _drive():
        # Reset the refresh lock so it binds to THIS event loop.
        gic._token_refresh_lock = None
        tokens = await asyncio.gather(*[gic._get_cached_token() for _ in range(5)])
        return tokens

    tokens = _run(_drive())
    assert all(t == "single-flight-token" for t in tokens)
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# _ping_google_sitemap wrapper in routes.bot_discovery
# ---------------------------------------------------------------------------

def test_bot_discovery_ping_helper_delegates(monkeypatch):
    gic = _fresh_client(monkeypatch)
    fake = _FakeAsyncClient(get_response=_FakeResponse(200, "OK"))
    _install_httpx(monkeypatch, gic, fake)
    import routes.bot_discovery as bd
    res = _run(bd._ping_google_sitemap())
    assert res["status"] == "ok"
    assert len(fake.get_calls) == 1


# ---------------------------------------------------------------------------
# diff_sitemap_against_submitted now also fires the Google sitemap ping
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()

    async def to_list(self, length=None):
        return list(self._docs)[:length] if length else list(self._docs)


class _FakeCollection:
    def __init__(self, docs):
        self._docs = list(docs)

    def find(self, *_a, **_kw):
        return _FakeCursor(self._docs)


def test_diff_fires_google_sitemap_ping_when_changes_detected(monkeypatch):
    """End-to-end: a new URL in the sitemap causes the diff loop to call
    `_ping_google_sitemap` exactly once, and the summary captures the
    ping status."""
    import routes.bot_discovery as bd
    import deps as deps_mod

    fake_db = MagicMock()
    fake_db.subjects = _FakeCollection([])
    fake_db.chapters = _FakeCollection([])
    fake_db.streams = _FakeCollection([])
    fake_db.classes = _FakeCollection([])
    fake_db.boards = _FakeCollection([])
    fake_db.seo_pages = _FakeCollection([])
    fake_db.cms_documents = _FakeCollection([])
    fake_db.indexnow_submitted_urls = _FakeCollection([])
    fake_db.indexnow_sitemap_diff_log = MagicMock()
    fake_db.indexnow_sitemap_diff_log.insert_one = AsyncMock()

    async def _avail():
        return True

    monkeypatch.setattr(deps_mod, "db", fake_db, raising=False)
    monkeypatch.setattr(deps_mod, "is_mongo_available", _avail, raising=False)

    fresh_url = f"{bd.BASE_URL}/ahsec/class-12/physics/new-chapter"

    async def _fake_sitemap():
        return [fresh_url]

    monkeypatch.setattr(bd, "_collect_current_sitemap_urls", _fake_sitemap)

    bd.indexnow_batcher = MagicMock()
    bd.indexnow_batcher.queue = AsyncMock()
    bd.indexnow_batcher.flush_force = AsyncMock()

    pings: list = []

    async def _fake_ping(*a, **kw):
        pings.append((a, kw))
        return {"status": "ok", "http_status": 200}

    monkeypatch.setattr(bd, "_ping_google_sitemap", _fake_ping)

    summary = _run(bd.diff_sitemap_against_submitted(source="test"))

    assert summary["new_queued"] == 1
    assert summary["google_sitemap_ping"] == "ok"
    assert len(pings) == 1


def test_diff_skips_google_sitemap_ping_when_no_changes(monkeypatch):
    """If nothing is queued (every URL already submitted AND unedited),
    skip the ping — no point nudging Google to re-fetch an unchanged
    sitemap."""
    import routes.bot_discovery as bd
    import deps as deps_mod

    fake_db = MagicMock()
    for name in ("subjects", "chapters", "streams", "classes", "boards",
                 "seo_pages", "cms_documents"):
        setattr(fake_db, name, _FakeCollection([]))
    fake_db.indexnow_submitted_urls = _FakeCollection([])
    fake_db.indexnow_sitemap_diff_log = MagicMock()
    fake_db.indexnow_sitemap_diff_log.insert_one = AsyncMock()

    async def _avail():
        return True

    monkeypatch.setattr(deps_mod, "db", fake_db, raising=False)
    monkeypatch.setattr(deps_mod, "is_mongo_available", _avail, raising=False)

    # Empty sitemap → no candidates → early-return before queue, and the
    # ping branch is only hit after `to_queue` is populated.
    async def _empty_sitemap():
        return []

    monkeypatch.setattr(bd, "_collect_current_sitemap_urls", _empty_sitemap)

    pings: list = []

    async def _fake_ping(*a, **kw):
        pings.append((a, kw))
        return {"status": "ok"}

    monkeypatch.setattr(bd, "_ping_google_sitemap", _fake_ping)

    summary = _run(bd.diff_sitemap_against_submitted(source="test"))
    assert summary["new_queued"] == 0
    # Empty sitemap returns early — ping never attempted.
    assert len(pings) == 0


# ---------------------------------------------------------------------------
# seo_fanout now runs the Google Indexing hook as a 4th gathered signal
# ---------------------------------------------------------------------------

def test_seo_fanout_includes_google_indexing_step(monkeypatch):
    import seo_fanout
    import google_indexing_client as gic
    gic._reset_state_for_tests()

    monkeypatch.setenv("SEO_FANOUT_ENABLED", "true")

    calls = {"indexing": 0, "indexnow": 0, "purge": 0, "prewarm": 0}

    async def _fake_indexnow(url, source):
        calls["indexnow"] += 1
        return True

    async def _fake_purge(url, parent, page_type):
        calls["purge"] += 1
        return True

    async def _fake_prewarm(urls):
        calls["prewarm"] += 1
        return True

    async def _fake_notify(url, source="x"):
        calls["indexing"] += 1
        return {"status": "ok"}

    monkeypatch.setattr(seo_fanout, "_do_indexnow", _fake_indexnow)
    monkeypatch.setattr(seo_fanout, "_do_cache_purge", _fake_purge)
    monkeypatch.setattr(seo_fanout, "_do_prewarm", _fake_prewarm)
    monkeypatch.setattr(gic, "notify_url_updated", _fake_notify)

    page = {
        "board_slug": "ahsec", "class_slug": "class-12",
        "subject_slug": "physics", "topic_slug": "kinematics",
        "page_type": "notes",
    }

    async def _drive():
        task = seo_fanout.fanout_for_page(page, source="unit-test")
        assert task is not None
        await task

    _run(_drive())

    assert calls["indexing"] == 1
    assert calls["indexnow"] == 1
    assert calls["purge"] == 1
    assert calls["prewarm"] == 1

    events = seo_fanout.recent_fanout_events(limit=1)
    assert events
    assert events[-1]["google_indexing"] == "ok"
