"""Regression for the chat-broken triage on 2026-04-26.

The CF AI Gateway path for Gemini (and every other OpenAI-compat
provider) was sending ``Authorization: ""`` (empty) to CF, which then
forwarded an empty Authorization header to Google AI Studio,
producing the long-running 400 "Missing or invalid Authorization
header" error EVEN THOUGH ``GEMINI_API_KEY`` was healthy.

The fix flipped the default of ``_cf_cache_headers()`` so the OpenAI
SDK's auto-attached ``Authorization: Bearer <key>`` header is left
intact and forwarded upstream by CF. BYOK callsites (placeholder key
+ stored CF binding) must pass ``clear_upstream_auth=True`` to opt in
to the old behaviour.

These tests guard the default so a future "let's clean up the
function signature" refactor cannot silently re-break chat.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def llm_module(monkeypatch):
    # CF gateway must be enabled or the helper short-circuits to {}.
    monkeypatch.setenv("CF_AI_GATEWAY_ACCOUNT_ID", "test-acct")
    monkeypatch.setenv("CF_AI_GATEWAY_ID", "test-gw")
    monkeypatch.setenv("CF_AI_GATEWAY_TOKEN", "test-cf-token")
    # Re-import so the env-derived module-level constants pick up the
    # test values.
    import config as cfg
    importlib.reload(cfg)
    import llm as llm_mod
    importlib.reload(llm_mod)
    # Force the in-process gateway-health flag to UP so the helper does
    # not short-circuit to {} (which would mask the real header shape).
    cfg._cf_gw_healthy = True
    return llm_mod, cfg


def test_cf_cache_headers_default_does_not_clear_authorization(llm_module):
    llm_mod, _ = llm_module
    h = llm_mod._cf_cache_headers()
    # The whole bug: previously ``Authorization`` was being forced to
    # the empty string here, clobbering the OpenAI SDK's bearer auth.
    assert "Authorization" not in h, (
        f"_cf_cache_headers() default MUST NOT include Authorization "
        f"(real api_key callers rely on the SDK's bearer auth reaching "
        f"upstream); got: {h!r}"
    )
    # Cache-control + gateway-auth + BYOK opt-in still attach.
    assert h.get("cf-aig-cache-ttl"), h
    assert h.get("cf-aig-byok-key") == "true", h
    assert h.get("cf-aig-authorization", "").startswith("Bearer "), h


def test_cf_cache_headers_byok_opt_in_clears_authorization(llm_module):
    llm_mod, _ = llm_module
    h = llm_mod._cf_cache_headers(clear_upstream_auth=True)
    # True BYOK callsites still get the empty-Authorization signal so
    # CF substitutes the dashboard-stored key.
    assert h.get("Authorization") == "", (
        f"clear_upstream_auth=True MUST emit Authorization='' so CF "
        f"injects the BYOK-stored key upstream; got: {h!r}"
    )
    assert h.get("cf-aig-byok-key") == "true", h


def test_cf_cache_headers_empty_when_gateway_down(llm_module):
    llm_mod, cfg = llm_module
    cfg.mark_cf_gateway_down()
    # Gateway down → no CF-specific headers at all so the SDK's default
    # ``Authorization: Bearer <key>`` reaches the direct-URL upstream
    # untouched.
    assert llm_mod._cf_cache_headers() == {}
    assert llm_mod._cf_cache_headers(clear_upstream_auth=True) == {}


def test_emergent_cf_cache_headers_default_does_not_clear_authorization(
    monkeypatch,
):
    """Same regression for the LlmChat path (different module, same bug)."""
    monkeypatch.setenv("CF_AI_GATEWAY_ACCOUNT_ID", "test-acct")
    monkeypatch.setenv("CF_AI_GATEWAY_ID", "test-gw")
    monkeypatch.setenv("CF_AI_GATEWAY_TOKEN", "test-cf-token")
    import config as cfg
    importlib.reload(cfg)
    cfg._cf_gw_healthy = True
    from emergentintegrations.llm import chat as chat_mod
    importlib.reload(chat_mod)
    # _cf_cache_headers is a method on LlmChat; we instantiate with the
    # narrowest possible inputs since the bound helper does not touch
    # any other instance state.
    inst = chat_mod.LlmChat(
        api_key="real-provider-key",
        session_id="t",
        system_message="t",
    ).with_model("gemini", "gemini-2.5-flash")
    h = inst._cf_cache_headers() or {}
    assert "Authorization" not in h, (
        f"emergent LlmChat._cf_cache_headers default MUST NOT include "
        f"Authorization; got: {h!r}"
    )
    assert h.get("cf-aig-byok-key") == "true", h
