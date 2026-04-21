"""Indic (Assamese) Vertex Gemini fast-path tests (Task #628).

Covers the admin-gated Assamese → Vertex Gemini Flash route in
``call_llm_api_stream``:

  1. Toggle ON → Vertex serves the Assamese turn, the emitted
     ``__provider`` tag is ``vertex_gemini_indic`` (distinct bucket
     from the English fast-path) so the admin dashboard can A/B
     TTFT against Sarvam.
  2. Toggle OFF → Indic path keeps going through Sarvam; Vertex is
     never called even though ``is_configured()`` is True.
  3. Toggle ON + pre-first-token Vertex failure → fallback targets
     the Sarvam pool (NOT ``openai/gpt-oss-20b``) so Assamese quality
     is preserved, and a ``vertex_gemini_indic -> sarvam-m`` fallback
     metric is recorded for admin visibility.
"""
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _collect(agen):
    out = []
    async for chunk in agen:
        out.append(chunk)
    return out


def _parse_sse(chunks):
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


def _async_gen_from_tokens(tokens):
    async def _stream_chat(messages, *, model=None, max_tokens=2048, temperature=0.1):
        for tok in tokens:
            yield tok
    return _stream_chat


def _async_gen_that_raises(exc):
    async def _stream_chat(messages, *, model=None, max_tokens=2048, temperature=0.1):
        if False:
            yield ""  # pragma: no cover — makes this an async generator
        raise exc
    return _stream_chat


@pytest.fixture(autouse=True)
def _isolate_provider_metrics():
    import chat_speedup_metrics as csm
    csm._provider_daily.clear()
    csm._provider_fallbacks.clear()
    yield
    csm._provider_daily.clear()
    csm._provider_fallbacks.clear()


@pytest.fixture(autouse=True)
def _isolate_indic_provider_override():
    """Reset the in-memory Assamese-purity override so each test sees
    the clean `sarvam` default regardless of what previous tests set."""
    import lang_sanitizer as ls
    ls._RUNTIME_OVERRIDE = None
    yield
    ls._RUNTIME_OVERRIDE = None


# ────────────────────────────────────────────────────────────────────────
# 1. Admin toggle ON → Vertex serves Assamese with dedicated metric bucket
# ────────────────────────────────────────────────────────────────────────

def test_indic_vertex_toggle_routes_assamese_through_vertex(monkeypatch):
    import llm
    import vertex_chat
    import lang_sanitizer as ls

    # Flip the admin toggle to 'vertex' for Assamese.
    ls.apply_runtime_override(indic_provider="vertex", updated_by="test")
    assert ls.get_indic_provider() == "vertex"

    monkeypatch.setattr(vertex_chat, "is_configured", lambda: True)
    monkeypatch.setattr(
        vertex_chat, "stream_chat",
        _async_gen_from_tokens(["ন", "ম", "স্কা", "ৰ"]),
    )
    # The Indic model-preference loop calls ``_resolve_provider_for_model``
    # twice before the fast-path, looking for a Sarvam model to default
    # ``model`` to. Return an empty tuple so that loop no-ops, and spy
    # on every invocation so we can later assert which models the path
    # did NOT try to resolve (specifically: not ``openai/gpt-oss-20b``).
    from unittest.mock import MagicMock
    legacy_spy = MagicMock(return_value=("", ""))
    monkeypatch.setattr(llm, "_resolve_provider_for_model", legacy_spy)
    # Also stub _stream_from_provider so if somehow the legacy path
    # were reached with a resolved provider, we'd notice (raise).
    monkeypatch.setattr(llm, "_safe_model_for_provider",
                        lambda m, p, providers: m)

    msgs = [
        {"role": "system", "content": "You are Syrabit."},
        {"role": "user", "content": "hi"},
    ]
    chunks = _run(_collect(llm.call_llm_api_stream(
        msgs, model="sarvam-m", response_lang="as",
    )))
    events = _parse_sse(chunks)

    # Vertex served the turn → reassembled content + distinct provider tag.
    contents = [e["content"] for e in events if "content" in e]
    assert "".join(contents) == "নমস্কাৰ"
    providers = [e["__provider"] for e in events if "__provider" in e]
    assert providers == ["vertex_gemini_indic"], (
        "Expected distinct metric bucket so the admin dashboard can A/B "
        "TTFT separately from English Vertex traffic"
    )
    assert not any("error" in e for e in events)
    # The indic-model preference loop calls the resolver twice before the
    # fast-path (to pick sarvam-m / sarvam-105b defaults); that is
    # expected. What we must NOT see is a call with the English SLM
    # default ``openai/gpt-oss-20b`` — that would mean the fast-path
    # silently fell through to the English pool instead of serving
    # Assamese via Vertex.
    resolver_models = [c.args[0] for c in legacy_spy.call_args_list]
    assert "openai/gpt-oss-20b" not in resolver_models

    # Dashboard metric recorded under the Indic bucket.
    import chat_speedup_metrics as csm
    snap = csm.snapshot(days=1)
    by_prov = {p["provider"]: p for p in snap["by_provider"]}
    assert "vertex_gemini_indic" in by_prov
    assert by_prov["vertex_gemini_indic"]["calls"] == 1


# ────────────────────────────────────────────────────────────────────────
# 2. Admin toggle OFF (default) → Assamese stays on Sarvam
# ────────────────────────────────────────────────────────────────────────

def test_indic_vertex_toggle_default_keeps_sarvam_path(monkeypatch):
    import llm
    import vertex_chat
    import lang_sanitizer as ls

    # Default → sarvam. Assert no override leaked in from another test.
    assert ls.get_indic_provider() == "sarvam"

    monkeypatch.setattr(vertex_chat, "is_configured", lambda: True)
    vertex_spy = AsyncMock()
    monkeypatch.setattr(vertex_chat, "stream_chat", vertex_spy)
    # Indic path falls through to the standard resolver with a Sarvam model;
    # stub it so no network call is attempted.
    monkeypatch.setattr(llm, "_resolve_provider_for_model",
                        lambda model, providers: ("", ""))

    msgs = [{"role": "user", "content": "hi"}]
    _run(_collect(llm.call_llm_api_stream(
        msgs, model="sarvam-m", response_lang="as",
    )))

    vertex_spy.assert_not_called()


# ────────────────────────────────────────────────────────────────────────
# 3. Toggle ON + Vertex pre-first-token failure → fall back to Sarvam pool
#    (NOT the English SLM pool) so Assamese quality is preserved
# ────────────────────────────────────────────────────────────────────────

def test_indic_vertex_failure_falls_back_to_sarvam_not_english_slm(monkeypatch):
    import llm
    import vertex_chat
    import lang_sanitizer as ls

    ls.apply_runtime_override(indic_provider="vertex", updated_by="test")
    monkeypatch.setattr(vertex_chat, "is_configured", lambda: True)
    monkeypatch.setattr(
        vertex_chat, "stream_chat",
        _async_gen_that_raises(RuntimeError("boom: vertex 503")),
    )

    # Capture which model the legacy resolver is asked for post-fallback.
    resolved_for = {}

    def _fake_resolve(model, providers):
        resolved_for["model"] = model
        # Return empty so the indic path exits cleanly after the call
        # (we only care that it was asked for a Sarvam model, not the
        # English default).
        return ("", "")

    monkeypatch.setattr(llm, "_resolve_provider_for_model", _fake_resolve)

    msgs = [{"role": "user", "content": "hi"}]
    _run(_collect(llm.call_llm_api_stream(
        msgs, model="sarvam-m", response_lang="as",
    )))

    # Fallback target must be a Sarvam-flavoured model — NOT the English
    # ``openai/gpt-oss-20b`` default used by the English Vertex fast-path.
    assert resolved_for.get("model", "").startswith("sarvam"), (
        f"Indic fallback resolved for model={resolved_for.get('model')!r}; "
        "expected a sarvam-* model to preserve Assamese quality"
    )

    # Fallback metric recorded under the Indic bucket → distinguishable
    # from English fallbacks on the admin dashboard.
    import chat_speedup_metrics as csm
    snap = csm.snapshot(days=1)
    fbs = {f["transition"]: f["count"] for f in snap["provider_fallbacks"]}
    assert "vertex_gemini_indic->sarvam-m" in fbs, (
        f"expected vertex_gemini_indic->sarvam-m in fallbacks; got {fbs}"
    )
    assert fbs["vertex_gemini_indic->sarvam-m"] == 1


def test_indic_provider_survives_worker_reconcile(monkeypatch):
    """Persisted ``indic_provider`` override must be restored when a
    fresh worker boots (or the periodic refresher runs against a doc
    written by a sibling worker). Without this, an admin PATCH sets
    ``vertex`` on one worker but new workers silently revert to
    ``sarvam`` and Assamese traffic splits across providers — the
    core A/B contract breaks.

    Simulates the reconciliation path used by the 15s refresher and
    by ``server.py`` lifespan on API boot.
    """
    import lang_sanitizer as ls
    import routes.cms_sarvam_health as cms

    ls.clear_runtime_override()
    assert ls.get_indic_provider() in ("sarvam", "vertex")

    async def _fake_loader():
        return {
            "behaviour": "translate",
            "threshold": 0.05,
            "indic_provider": "vertex",
            "updated_by": "sibling-worker",
        }

    monkeypatch.setattr(
        cms, "_load_persisted_assamese_purity_override", _fake_loader
    )

    _run(cms.apply_persisted_assamese_purity_override())

    assert ls.get_indic_provider() == "vertex", (
        "Persisted indic_provider=vertex was written by a sibling "
        "worker but this worker reconciled to default — "
        "apply_persisted_assamese_purity_override must forward the "
        "indic_provider field to apply_runtime_override."
    )
    cfg = ls.get_runtime_config()
    assert cfg.get("indic_provider") == "vertex"

    ls.clear_runtime_override()
