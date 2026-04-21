"""Integration test for the Workers AI chat fallback wiring (Task #636).

Asserts that when ALL configured chat providers fail with a retryable
error, `_call_llm_raw` returns an `LlmResult` tagged with
`provider="workers-ai"` AND a populated `fallback_reason`. This is the
final guard against regressions like "the policy module works in
isolation but the wiring in llm.py never actually invokes it".

The test mocks `providers.workers_ai.call_chat` directly so we don't
need a live edge worker, and it monkey-patches the provider list to a
single fake provider that always raises a 503 — that way we exercise
the same code path that runs in prod when Cerebras/Gemini are down.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

os.environ.setdefault("WORKERS_AI_FALLBACK_SECRET", "test-secret")
os.environ.setdefault("WORKERS_AI_FALLBACK_ENABLED", "1")

import llm  # noqa: E402
from providers import workers_ai as wai  # noqa: E402


def _503_error() -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://primary.test")
    resp = httpx.Response(503, request=req)
    return httpx.HTTPStatusError("primary down", request=req, response=resp)


def test_chat_falls_back_to_workers_ai_on_total_primary_failure(monkeypatch):
    """The whole point of Task #636 — when every primary provider is
    down, the chat path returns a Workers AI result instead of 503."""
    monkeypatch.setenv("WORKERS_AI_FALLBACK_SECRET", "test-secret")
    monkeypatch.setenv("WORKERS_AI_FALLBACK_ENABLED", "1")
    wai.set_enabled("chat", True)

    # Force one provider, single key, that always throws a retryable 503.
    fake_providers = [{
        "provider": "fake-primary",
        "key": "k-test",
        "default_model": "fake-model",
    }]

    async def always_503(messages, provider, key, model, max_tokens):
        raise _503_error()

    async def fake_workers_ai_chat(messages, max_tokens=1024, temperature=0.3):
        # Sanity: the wiring should pass through the original messages.
        assert isinstance(messages, list) and messages
        return "Hello from Workers AI"

    monkeypatch.setattr(llm, "_call_single_provider", always_503)
    monkeypatch.setattr(wai, "call_chat", fake_workers_ai_chat)
    # Skip the durable load — no Mongo in unit tests.
    async def _noop():
        return None
    monkeypatch.setattr(wai, "_persist_load_if_stale", _noop)

    messages = [
        {"role": "system", "content": "You are a tutor."},
        {"role": "user", "content": "what is 2+2?"},
    ]
    result = asyncio.run(llm._call_llm_raw(messages, model="fake-model",
                                           provider_list=fake_providers))
    assert str(result) == "Hello from Workers AI"
    assert result.provider == "workers-ai"
    # The reason must be populated — that's the metadata the admin
    # dashboard uses to attribute the fallback to the upstream failure.
    assert result.fallback_reason == "http_503"


def test_chat_does_not_fall_back_on_4xx_bad_input(monkeypatch):
    """The other key invariant — a 400 from the primary surfaces as
    503 (after the retry loop), it does NOT silently switch providers
    and hide the bug."""
    from fastapi import HTTPException

    monkeypatch.setenv("WORKERS_AI_FALLBACK_SECRET", "test-secret")
    monkeypatch.setenv("WORKERS_AI_FALLBACK_ENABLED", "1")
    wai.set_enabled("chat", True)

    fake_providers = [{
        "provider": "fake-primary",
        "key": "k-test",
        "default_model": "fake-model",
    }]

    req = httpx.Request("POST", "http://primary.test")

    async def always_400(messages, provider, key, model, max_tokens):
        raise httpx.HTTPStatusError(
            "bad input", request=req,
            response=httpx.Response(400, request=req),
        )

    workers_ai_calls = {"count": 0}

    async def workers_ai_should_not_be_called(messages, **_):
        workers_ai_calls["count"] += 1
        return "should never appear"

    monkeypatch.setattr(llm, "_call_single_provider", always_400)
    monkeypatch.setattr(wai, "call_chat", workers_ai_should_not_be_called)
    async def _noop():
        return None
    monkeypatch.setattr(wai, "_persist_load_if_stale", _noop)

    messages = [{"role": "user", "content": "trigger 400"}]
    with pytest.raises(HTTPException) as exc:
        asyncio.run(llm._call_llm_raw(messages, model="fake-model",
                                      provider_list=fake_providers))
    assert exc.value.status_code == 503
    # Critical: Workers AI must NOT have been invoked.
    assert workers_ai_calls["count"] == 0
