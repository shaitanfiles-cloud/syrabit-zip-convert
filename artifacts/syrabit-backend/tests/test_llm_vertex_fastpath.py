"""Vertex Gemini Flash fast-path tests (Task #627).

Covers the four behaviours of the ``vertex/gemini-flash`` model branch in
``call_llm_api_stream`` (artifacts/syrabit-backend/llm.py:1150):

  1. Happy path — Vertex streams tokens; we emit ``__provider:
     vertex_gemini`` and never reach the legacy SLM pool.
  2. Pre-first-token failure — Vertex raises before yielding anything;
     we silently fall back to ``openai/gpt-oss-20b`` and a fallback
     metric is recorded.
  3. Mid-stream error — Vertex yields one token then raises; we surface
     ``error: AI service interrupted`` to the client and stop (no
     fallback because we cannot rewind the SSE stream).
  4. Indic bypass — When the response language is Assamese, the Vertex
     fast-path must be skipped entirely so Sarvam-tuned models handle
     the request.
"""
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _collect(agen):
    out = []
    async for chunk in agen:
        out.append(chunk)
    return out


def _parse_sse(chunks):
    """Decode SSE ``data: {...}`` chunks into the list of payload dicts."""
    events = []
    for chunk in chunks:
        for line in chunk.split("\n"):
            line = line.strip()
            if not line.startswith("data:"):
                continue
            try:
                events.append(json.loads(line[len("data:"):].strip()))
            except Exception:
                pass
    return events


@pytest.fixture(autouse=True)
def _isolate_provider_metrics():
    """Reset the in-memory per-provider counters between tests so each
    test sees a clean fallback bucket."""
    import chat_speedup_metrics as csm
    csm._provider_daily.clear()
    csm._provider_fallbacks.clear()
    yield
    csm._provider_daily.clear()
    csm._provider_fallbacks.clear()


def test_vertex_fastpath_happy_path_emits_provider_tag(monkeypatch):
    """Vertex yields tokens → SSE stream contains the ``__provider``
    marker and the legacy SLM pool is never invoked."""
    import llm

    async def _fake_vertex(messages, model, max_tokens):
        for tok in ("Hel", "lo ", "Wor", "ld"):
            yield tok

    monkeypatch.setattr(llm._vertex_chat, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "_stream_vertex_gemini", _fake_vertex)
    legacy_spy = AsyncMock()
    monkeypatch.setattr(llm, "_resolve_provider_for_model", legacy_spy)

    msgs = [{"role": "user", "content": "hi"}]
    chunks = _run(_collect(llm.call_llm_api_stream(
        msgs, model="vertex/gemini-flash", response_lang="english",
    )))
    events = _parse_sse(chunks)

    contents = [e["content"] for e in events if "content" in e]
    assert "".join(contents) == "Hello World"
    providers = [e["__provider"] for e in events if "__provider" in e]
    assert providers == ["vertex_gemini"]
    legacy_spy.assert_not_called()

    import chat_speedup_metrics as csm
    snap = csm.snapshot(days=1)
    by_prov = {p["provider"]: p for p in snap["by_provider"]}
    assert "vertex_gemini" in by_prov
    assert by_prov["vertex_gemini"]["calls"] == 1


def test_vertex_fastpath_pre_first_token_failure_falls_back(monkeypatch):
    """Vertex raises before any token → silently fall back to legacy
    SLM pool. Client should see no error event and the fallback metric
    must increment."""
    import llm

    async def _broken_vertex(messages, model, max_tokens):
        raise RuntimeError("boom: vertex 503")
        yield  # pragma: no cover (make this an async generator)

    monkeypatch.setattr(llm._vertex_chat, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "_stream_vertex_gemini", _broken_vertex)

    # Stub the legacy resolution so we know the fallback was reached
    # without executing a real HTTP request. Returning ``("", "")`` makes
    # the function emit ``LLM API key not configured`` and exit cleanly.
    monkeypatch.setattr(llm, "_resolve_provider_for_model",
                        lambda model, providers: ("", ""))

    msgs = [{"role": "user", "content": "hi"}]
    chunks = _run(_collect(llm.call_llm_api_stream(
        msgs, model="vertex/gemini-flash", response_lang="english",
    )))
    events = _parse_sse(chunks)

    # No ``__provider: vertex_gemini`` should be emitted.
    providers = [e.get("__provider") for e in events if "__provider" in e]
    assert "vertex_gemini" not in providers
    # We hit the legacy fallback, which now reports a key-config error.
    assert any("error" in e for e in events)

    import chat_speedup_metrics as csm
    snap = csm.snapshot(days=1)
    fb = {f["transition"]: f["count"] for f in snap["provider_fallbacks"]}
    assert fb.get("vertex_gemini->openai/gpt-oss-20b") == 1


def test_vertex_fastpath_mid_stream_error_surfaces_error(monkeypatch):
    """Vertex yields a token then raises → client receives the
    ``AI service interrupted`` error and the legacy fallback is NOT
    triggered (we cannot rewind partial SSE output)."""
    import llm

    async def _half_broken(messages, model, max_tokens):
        yield "Hello"
        raise RuntimeError("boom mid-stream")

    monkeypatch.setattr(llm._vertex_chat, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "_stream_vertex_gemini", _half_broken)
    legacy_spy = AsyncMock()
    monkeypatch.setattr(llm, "_resolve_provider_for_model", legacy_spy)

    msgs = [{"role": "user", "content": "hi"}]
    chunks = _run(_collect(llm.call_llm_api_stream(
        msgs, model="vertex/gemini-flash", response_lang="english",
    )))
    events = _parse_sse(chunks)

    # Partial content was streamed.
    assert any(e.get("content") == "Hello" for e in events)
    # And then an explicit error was emitted.
    errors = [e["error"] for e in events if "error" in e]
    assert errors and "interrupted" in errors[-1].lower()
    # No fallback to legacy because the stream had already started.
    legacy_spy.assert_not_called()
    import chat_speedup_metrics as csm
    snap = csm.snapshot(days=1)
    assert snap["provider_fallbacks"] == []


def test_vertex_fastpath_skipped_for_indic_languages(monkeypatch):
    """Assamese responses must bypass Vertex entirely so Sarvam routing
    handles the call. ``_stream_vertex_gemini`` should never be called."""
    import llm

    vertex_spy = AsyncMock()
    monkeypatch.setattr(llm._vertex_chat, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "_stream_vertex_gemini", vertex_spy)

    # Stub the legacy resolver so the Indic path exits cleanly without
    # contacting any provider.
    monkeypatch.setattr(llm, "_resolve_provider_for_model",
                        lambda model, providers: ("", ""))

    msgs = [{"role": "user", "content": "hi"}]
    _run(_collect(llm.call_llm_api_stream(
        msgs, model="vertex/gemini-flash", response_lang="as",
    )))
    vertex_spy.assert_not_called()
