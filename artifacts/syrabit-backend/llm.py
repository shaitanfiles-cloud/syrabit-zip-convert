"""Syrabit.ai — LLM infrastructure: batching, smart key pool, streaming."""
import os, re, json, asyncio, uuid, time, logging

_MODEL_MAX_OUTPUT_TOKENS = {
    "llama-3.1-8b-instant": 8192,
    "llama-3.3-70b-versatile": 32768,
    "gemini-2.5-flash": 65536,
    "gemini-2.0-flash": 8192,
}

def _clamp_max_tokens(model: str, max_tokens: int) -> int:
    cap = _MODEL_MAX_OUTPUT_TOKENS.get(model)
    return min(max_tokens, cap) if cap else max_tokens
from typing import Dict, Optional
from fastapi import HTTPException
from emergentintegrations.llm.chat import LlmChat, UserMessage
from config import (
    LLM_PROVIDER, LLM_MODEL, OPENAI_API_KEY, SARVAM_THINK_BUFFER,
    _GROQ_KEY, _GROQ_KEY_2, _GEMINI_KEY, _XAI_KEY, _OPENAI_KEY, _FIREWORKS_KEY,
    _SARVAM_LLM_KEY, _EMERGENT_KEY, _EMERGENT_BASE_URL, _AWS_ACCESS_KEY, _AWS_SECRET_KEY, _AWS_REGION,
)
from deps import sarvam_llm_client, logger as _dep_logger
from cache import _cache_key

logger = logging.getLogger(__name__)

_LLM_SEMAPHORE = asyncio.Semaphore(int(os.environ.get("LLM_MAX_CONCURRENT", 20)))

_LLM_PROVIDER_METRICS: list = []
_LLM_PROVIDER_METRICS_MAX = 20_000

def _record_llm_call(provider: str, model: str, duration_ms: float, success: bool, tokens_approx: int = 0, fallback: bool = False, error_type: str = ""):
    _LLM_PROVIDER_METRICS.append({
        "ts": time.time(),
        "provider": provider,
        "model": model,
        "duration_ms": round(duration_ms, 1),
        "success": success,
        "tokens_approx": tokens_approx,
        "fallback": fallback,
        "error_type": error_type,
    })
    if len(_LLM_PROVIDER_METRICS) > _LLM_PROVIDER_METRICS_MAX:
        del _LLM_PROVIDER_METRICS[:1000]

def get_llm_provider_stats(window_seconds: int = 3600) -> dict:
    cutoff = time.time() - window_seconds
    recent = [m for m in _LLM_PROVIDER_METRICS if m["ts"] >= cutoff]
    by_provider: dict = {}
    for m in recent:
        p = m["provider"]
        if p not in by_provider:
            by_provider[p] = {"calls": 0, "successes": 0, "failures": 0, "total_ms": 0, "tokens": 0, "models": set()}
        by_provider[p]["calls"] += 1
        by_provider[p]["tokens"] += m["tokens_approx"]
        by_provider[p]["total_ms"] += m["duration_ms"]
        by_provider[p]["models"].add(m["model"])
        if m["success"]:
            by_provider[p]["successes"] += 1
        else:
            by_provider[p]["failures"] += 1
    result = {}
    for p, s in by_provider.items():
        result[p] = {
            "calls": s["calls"],
            "success_rate": round(s["successes"] / max(s["calls"], 1) * 100, 1),
            "failures": s["failures"],
            "avg_latency_ms": round(s["total_ms"] / max(s["calls"], 1), 1),
            "tokens_approx": s["tokens"],
            "models": list(s["models"]),
        }
    total_calls = sum(s["calls"] for s in by_provider.values())
    total_success = sum(s["successes"] for s in by_provider.values())
    fallback_calls = sum(1 for m in recent if m["fallback"])
    return {
        "providers": result,
        "total_calls": total_calls,
        "overall_success_rate": round(total_success / max(total_calls, 1) * 100, 1),
        "fallback_rate": round(fallback_calls / max(total_calls, 1) * 100, 1),
        "window_seconds": window_seconds,
    }
_LLM_BATCH_WINDOW_MS = int(os.environ.get("LLM_BATCH_WINDOW_MS", 15))

class _LlmBatcher:
    """
    Smart LLM Batching: deduplicates identical questions arriving within a
    short window so only one API call is made per unique question.
    """
    def __init__(self):
        self._pending: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._stats = {"batched": 0, "deduped": 0, "solo": 0, "errors": 0}

    async def call(self, messages: list, model: str = None, max_tokens: int = 1024, provider_list=None) -> str:
        provider_tag = "chat" if provider_list is _LLM_PROVIDERS_CHAT else "all"
        batch_key = _cache_key(
            provider_tag + ":" + "".join(m.get("content", "") for m in messages if m.get("role") in ("user", "system"))
        )

        async with self._lock:
            if batch_key in self._pending:
                self._stats["deduped"] += 1
                logger.info(f"LLM batch DEDUP: {batch_key} — piggy-backing on in-flight request")
                future = self._pending[batch_key]
        
            else:
                future = asyncio.get_event_loop().create_future()
                self._pending[batch_key] = future
                self._stats["batched"] += 1
                asyncio.ensure_future(self._execute(batch_key, messages, model, max_tokens, future, provider_list))

        try:
            return await asyncio.wait_for(future, timeout=120)
        except asyncio.TimeoutError:
            logger.error(f"LLM batch TIMEOUT: {batch_key}")
            raise HTTPException(status_code=504, detail="AI response timed out. Please try again.")

    async def _execute(self, batch_key: str, messages: list, model: str, max_tokens: int, future: asyncio.Future, provider_list=None):
        await asyncio.sleep(_LLM_BATCH_WINDOW_MS / 1000.0)

        try:
            async with _LLM_SEMAPHORE:
                result = await _call_llm_raw(messages, model, max_tokens, provider_list=provider_list)
            future.set_result(result)
        except Exception as e:
            self._stats["errors"] += 1
            if not future.done():
                future.set_exception(e)
        finally:
            async with self._lock:
                self._pending.pop(batch_key, None)

    @property
    def stats(self):
        return {**self._stats, "pending": len(self._pending)}

_llm_batcher = _LlmBatcher()

_LLM_PROVIDERS = []
# Emergent first — universal key with highest priority (admin content generation only)
if _EMERGENT_KEY:
    _LLM_PROVIDERS.append({"provider": "emergent",    "key": _EMERGENT_KEY,   "default_model": "openai/gpt-4o-mini"})
# Fallback chain: Gemini → Groq → Fireworks → Sarvam → xAI → OpenAI
if _GEMINI_KEY:
    _LLM_PROVIDERS.append({"provider": "gemini",      "key": _GEMINI_KEY,     "default_model": "gemini-2.5-flash"})
if _GROQ_KEY and _GROQ_KEY != 'x':
    _LLM_PROVIDERS.append({"provider": "groq",        "key": _GROQ_KEY,       "default_model": "llama-3.1-8b-instant"})
if _GROQ_KEY_2 and _GROQ_KEY_2 != 'x':
    _LLM_PROVIDERS.append({"provider": "groq",        "key": _GROQ_KEY_2,     "default_model": "llama-3.3-70b-versatile"})
if _FIREWORKS_KEY:
    _LLM_PROVIDERS.append({"provider": "fireworksai", "key": _FIREWORKS_KEY,  "default_model": "accounts/fireworks/models/deepseek-v3p2"})
if _SARVAM_LLM_KEY:
    _LLM_PROVIDERS.append({"provider": "sarvam",      "key": _SARVAM_LLM_KEY, "default_model": "sarvam-m"})
if _XAI_KEY:
    _LLM_PROVIDERS.append({"provider": "xai",         "key": _XAI_KEY,        "default_model": "grok-3-fast"})
if _OPENAI_KEY and _OPENAI_KEY != 'x':
    _LLM_PROVIDERS.append({"provider": "openai",      "key": _OPENAI_KEY,     "default_model": "gpt-4o-mini"})

_LLM_PROVIDERS_CHAT = [p for p in _LLM_PROVIDERS if p["provider"] != "emergent"]

_MODEL_PROVIDER_MAP = {
    "sarvam-m": "sarvam",
    "sarvam-30b": "sarvam",
    "sarvam-30b-16k": "sarvam",
    "sarvam-105b": "sarvam",
    "sarvam-105b-32k": "sarvam",
    "accounts/fireworks/models/qwen2p5-72b-instruct": "fireworksai",
    "accounts/fireworks/models/qwen3-235b-a22b": "fireworksai",
    "accounts/fireworks/models/deepseek-v3p2": "fireworksai",
    "accounts/fireworks/models/gpt-oss-120b": "fireworksai",
    "llama-3.3-70b-versatile": "groq",
    "llama-3.1-8b-instant": "groq",
    # UI display aliases
    "openai/gpt-oss-20b": "groq",        # SLM: fast Groq model
    "openai/gpt-oss-120b": "fireworksai", # MLM: full Fireworks gpt-oss-120b
}

# Map display-alias model names to the actual API model ID to send to the provider
_MODEL_ALIAS_MAP = {
    "openai/gpt-oss-20b":  "llama-3.3-70b-versatile",              # Groq (primary)
    "openai/gpt-oss-120b": "accounts/fireworks/models/gpt-oss-120b", # Fireworks
}

# ── SLM slot table ────────────────────────────────────────────────────────────
# Each entry: (provider, model, max_concurrent)
# Models chosen for HIGHEST RPS on their respective providers.
# Multiple slots per provider = parallel streams up to max_concurrent each.
#
#  Groq        llama-3.3-70b-versatile — PRIMARY: quality + fast, 30 RPM
#              llama-3.1-8b-instant    — fallback: sub-second TTFT, highest TPD
#  Gemini      gemini-2.0-flash-lite   — 30 RPM free, lowest latency Gemini
#              gemini-2.0-flash        — 15 RPM free, higher quality
#  Fireworks   deepseek-v3p2           — high-quality, pay-per-token (no hard RPM cap)
#  Bedrock     amazon.nova-micro-v1:0  — free tier: 30 RPM cap, lowest latency on Bedrock
#                                        paid tier: 66.7 RPS / 33K TPS (no cap)
_SLM_SLOT_CANDIDATES = [
    # Gemini 2.5 Flash — primary: best accuracy + reasoning
    ("gemini",      "gemini-2.5-flash",                                  6),
    # Groq key 1 (rate-limited but fast when available)
    ("groq",        "llama-3.3-70b-versatile",                           8),
    ("groq",        "llama-3.1-8b-instant",                              4),
    # Groq key 2 (doubles rate limit capacity)
    ("groq:2",      "llama-3.3-70b-versatile",                           8),
    ("groq:2",      "llama-3.1-8b-instant",                              4),
    # Sarvam — reliable fallback when Gemini/Groq are rate-limited
    ("sarvam",      "sarvam-m",                                          4),
    # Fireworks (currently suspended)
    ("fireworksai", "accounts/fireworks/models/deepseek-v3p2",           8),
    ("bedrock",     "amazon.nova-micro-v1:0",                            2),
]

class _SmartKeyPool:
    """Concurrent smart pool — maximises RPS across all providers.

    Each slot has:
      sem            asyncio.Semaphore(max_concurrent) — caps parallel in-flight requests
      last_used      float timestamp — drives LRU round-robin between equal-capacity slots
      cooldown_until float timestamp — set after 429 / errors
      errors         int            — error count for exponential back-off

    pick() prefers slots with spare semaphore capacity first (lowest in-flight),
    then falls back to LRU among all non-cooled slots.
    """
    _RL_COOLDOWN  = 60.0   # 429 rate-limit → skip slot for 60 s
    _ERR_COOLDOWN = 15.0   # any other error → skip for 15 s

    def __init__(self, candidates: list):
        pmap: dict = {}
        for p in _LLM_PROVIDERS:
            pname = p["provider"]
            if pname not in pmap:
                pmap[pname] = []
            pmap[pname].append(p["key"])
        self._slots = []
        for pname, model_id, max_con in candidates:
            real_provider = pname.split(":")[0]
            key_idx = int(pname.split(":")[1]) - 1 if ":" in pname else 0
            keys = pmap.get(real_provider, [])
            key = keys[key_idx] if key_idx < len(keys) else ""
            if key or real_provider in ("sarvam", "bedrock"):
                if real_provider == "bedrock" and not (_AWS_ACCESS_KEY and _AWS_SECRET_KEY):
                    logger.info("SLM pool: skipping bedrock slot (AWS credentials not set)")
                    continue
                self._slots.append({
                    "provider": real_provider, "key": key, "model": model_id,
                    "sem": asyncio.Semaphore(max_con), "max_con": max_con,
                    "last_used": 0.0, "cooldown_until": 0.0, "errors": 0,
                })
        logger.info(
            f"SLM SmartKeyPool active slots: "
            f"{[(s['provider'], s['model'], s['max_con']) for s in self._slots]}"
        )

    def pick(self):
        """Return best slot: not cooling down, prefer spare capacity, then LRU."""
        now = time.time()
        available = [s for s in self._slots if now >= s["cooldown_until"]]
        if not available:
            return None
        # Primary: slots that still have semaphore capacity → lowest in-flight first
        with_capacity = [s for s in available if s["sem"]._value > 0]
        pool = with_capacity if with_capacity else available
        # Among equal-capacity slots, pick least-recently-used to spread load
        return min(pool, key=lambda s: (s["max_con"] - s["sem"]._value, s["last_used"]))

    def mark_ok(self, slot):
        slot["last_used"] = time.time()
        slot["errors"] = 0

    def mark_429(self, slot):
        slot["cooldown_until"] = time.time() + self._RL_COOLDOWN
        logger.warning(
            f"SLM pool: {slot['provider']}/{slot['model']} → 429 rate-limit, "
            f"cooling {self._RL_COOLDOWN}s"
        )

    def mark_403(self, slot):
        slot["cooldown_until"] = float("inf")  # permanently disabled for session
        logger.error(
            f"SLM pool: {slot['provider']}/{slot['model']} → 403 Forbidden (auth/permission error). "
            f"Slot permanently disabled. Check the API key for '{slot['provider']}'."
        )

    def mark_err(self, slot):
        slot["errors"] += 1
        cd = min(self._ERR_COOLDOWN * slot["errors"], 120.0)   # cap at 2 min
        slot["cooldown_until"] = time.time() + cd
        logger.warning(
            f"SLM pool: {slot['provider']}/{slot['model']} → error #{slot['errors']}, "
            f"cooling {cd:.0f}s"
        )

    @property
    def all_slots(self):
        return self._slots

_slm_pool = _SmartKeyPool(_SLM_SLOT_CANDIDATES)

def _resolve_provider_for_model(model: str, provider_list=None):
    plist = _LLM_PROVIDERS if provider_list is None else provider_list
    preferred = _MODEL_PROVIDER_MAP.get(model)
    if preferred:
        for p in plist:
            if p["provider"] == preferred:
                return p["provider"], p["key"]
    if plist:
        return plist[0]["provider"], plist[0]["key"]
    return LLM_PROVIDER, OPENAI_API_KEY

async def _call_sarvam_llm(messages: list, api_key: str, model: str, max_tokens: int) -> str:
    """Non-streaming call to Sarvam LLM — reuses persistent sarvam_llm_client (zero TCP overhead).
    Adds SARVAM_THINK_BUFFER so the <think> block never consumes the user's answer budget."""
    api_max = max_tokens + SARVAM_THINK_BUFFER  # thinking tokens don't count toward user quota
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": api_max,
        "temperature": 0.1,
        "stream": False,
    }
    client = sarvam_llm_client
    if client is None:
        raise HTTPException(status_code=503, detail="Sarvam LLM client not initialised")
    resp = await client.post("/v1/chat/completions", json=payload)
    resp.raise_for_status()
    data = resp.json()
    choice = data["choices"][0]["message"]
    content = choice.get("content") or ""
    reasoning = choice.get("reasoning_content") or ""
    result = content if content else reasoning
    result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
    result = re.sub(r'<think>.*$', '', result, flags=re.DOTALL).strip()
    return result

async def _call_gemini(messages: list, api_key: str, model: str, max_tokens: int) -> str:
    """Non-streaming call to Google Gemini via its OpenAI-compatible endpoint."""
    import openai as _oai
    client = _oai.AsyncOpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    resp = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, temperature=0.1,
    )
    content = resp.choices[0].message.content or ""
    return re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

async def _call_emergent(messages: list, api_key: str, model: str, max_tokens: int) -> str:
    """Non-streaming call via the Emergent universal key (OpenAI-compatible gateway)."""
    import openai as _oai
    client = _oai.AsyncOpenAI(
        api_key=api_key,
        base_url=_EMERGENT_BASE_URL,
    )
    resp = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, temperature=0.1,
    )
    content = resp.choices[0].message.content or ""
    return re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

async def _call_single_provider(messages: list, provider: str, api_key: str, model: str, max_tokens: int) -> str:
    max_tokens = _clamp_max_tokens(model, max_tokens)
    if provider == "sarvam":
        return await _call_sarvam_llm(messages, api_key, model, max_tokens)
    if provider == "gemini":
        return await _call_gemini(messages, api_key, model, max_tokens)
    if provider == "emergent":
        return await _call_emergent(messages, api_key, model, max_tokens)

    system_msg = ""
    user_msg = ""
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        elif m["role"] == "user":
            user_msg = m["content"]

    chat = LlmChat(
        api_key=api_key,
        session_id=str(uuid.uuid4()),
        system_message=system_msg or "You are a helpful AI tutor.",
    ).with_model(provider, model)

    response = await chat.send_message(UserMessage(text=user_msg))
    response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
    return response

async def _call_llm_raw(messages: list, model: str = None, max_tokens: int = 1024, provider_list=None) -> str:
    import time as _t
    providers = _LLM_PROVIDERS if provider_list is None else provider_list
    use_model = model or LLM_MODEL
    primary_provider, primary_key = _resolve_provider_for_model(use_model, providers)

    if not primary_key and not providers:
        raise HTTPException(status_code=503, detail="LLM API key not configured")

    tried: set = set()
    last_err = None

    provider, key = primary_provider, primary_key
    try_model = use_model
    try:
        tried.add((provider, try_model, id(key) if key else 0))
        _t0 = _t.perf_counter()
        result = await _call_single_provider(messages, provider, key, try_model, max_tokens)
        _dur = int((_t.perf_counter() - _t0) * 1000)
        tok = len(result.split())
        _record_llm_call(provider, try_model, _dur, True, tok, False)
        logger.info(f"llm_call provider={provider} model={try_model} duration_ms={_dur} tokens_approx={tok}")
        return result
    except Exception as e:
        _dur = int((_t.perf_counter() - _t0) * 1000)
        _record_llm_call(provider, try_model, _dur, False, 0, False, type(e).__name__)
        last_err = e
        logger.warning(f"LLM primary failed ({provider}/{try_model}): {type(e).__name__}: {str(e)[:150]}")

    for fallback in providers:
        fb_model = fallback["default_model"]
        fb_key_id = id(fallback["key"]) if fallback.get("key") else 0
        if (fallback["provider"], fb_model, fb_key_id) in tried:
            continue
        tried.add((fallback["provider"], fb_model, fb_key_id))
        try:
            _t0 = _t.perf_counter()
            result = await _call_single_provider(messages, fallback["provider"], fallback["key"], fb_model, max_tokens)
            _dur = int((_t.perf_counter() - _t0) * 1000)
            tok = len(result.split())
            _record_llm_call(fallback["provider"], fb_model, _dur, True, tok, True)
            logger.info(f"llm_call provider={fallback['provider']} model={fb_model} duration_ms={_dur} tokens_approx={tok} fallback=true")
            return result
        except Exception as e:
            _dur = int((_t.perf_counter() - _t0) * 1000)
            _record_llm_call(fallback["provider"], fb_model, _dur, False, 0, True, type(e).__name__)
            last_err = e
            logger.warning(f"LLM fallback failed ({fallback['provider']}/{fb_model}): {type(e).__name__}: {str(e)[:150]}")

    logger.error(f"All LLM providers exhausted. Last error: {last_err}")
    raise HTTPException(status_code=503, detail="AI service temporarily unavailable. Please try again.")

async def call_llm_api(messages: list, model: str = None, max_tokens: int = 2048) -> str:
    """Smart-batched LLM call: deduplicates identical requests, limits concurrency.
    Uses all providers including Emergent (admin content generation)."""
    return await _llm_batcher.call(messages, model, max_tokens)

_LLM_PROVIDERS_CONTENT: list[dict] = []
if _GEMINI_KEY:
    _LLM_PROVIDERS_CONTENT.append({"provider": "gemini", "key": _GEMINI_KEY, "default_model": "gemini-2.5-flash"})
for p in _LLM_PROVIDERS:
    if p["provider"] != "gemini" and p["provider"] != "emergent":
        _LLM_PROVIDERS_CONTENT.append(p)

async def call_llm_api_content(messages: list, model: str = None, max_tokens: int = 3072) -> str:
    """LLM call for SEO content generation — Gemini-primary with higher token limit."""
    return await _llm_batcher.call(messages, model or "gemini-2.5-flash", max_tokens, provider_list=_LLM_PROVIDERS_CONTENT)

async def call_llm_api_chat(messages: list, model: str = None, max_tokens: int = 2048) -> str:
    """LLM call for student chat — excludes Emergent provider (admin-only)."""
    return await _llm_batcher.call(messages, model, max_tokens, provider_list=_LLM_PROVIDERS_CHAT)


_THINK_BUDGET_HINT = "/think in one sentence. Answer immediately.\n"

def _inject_think_budget(messages: list) -> list:
    """Prepend a concise reasoning directive to the system message so sarvam-m
    spends fewer tokens in its <think> block, reducing TTFT significantly."""
    out = []
    injected = False
    for m in messages:
        if m.get("role") == "system" and not injected:
            out.append({**m, "content": _THINK_BUDGET_HINT + m["content"]})
            injected = True
        else:
            out.append(m)
    if not injected:
        out.insert(0, {"role": "system", "content": _THINK_BUDGET_HINT})
    return out

async def _stream_sarvam(messages: list, api_key: str, model: str, max_tokens: int):
    """Token-by-token SSE streaming from Sarvam — reuses persistent sarvam_llm_client (zero TCP overhead).
    Adds SARVAM_THINK_BUFFER so <think> reasoning never crowds out the user's answer budget.

    Speed knobs applied:
      • temperature=0.0  — greedy decoding, no sampling overhead
      • top_p/freq/pres penalties all zeroed for minimal compute
      • _inject_think_budget — caps reasoning tokens at the prompt level
    """
    api_max = max_tokens + SARVAM_THINK_BUFFER
    patched = _inject_think_budget(messages)
    payload = {
        "model": model,
        "messages": patched,
        "max_tokens": api_max,
        "temperature": 0.1,
        "top_p": 0.95,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "stream": True,
    }
    client = sarvam_llm_client
    if client is None:
        raise HTTPException(status_code=503, detail="Sarvam LLM client not initialised")
    async with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
        if resp.status_code >= 400:
            body = await resp.aread()
            logger.error(f"Sarvam {resp.status_code} error body: {body.decode()[:500]}")
            resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                break
            try:
                chunk = json.loads(raw)
                delta = chunk["choices"][0]["delta"]
                token = delta.get("content") or ""
                if token:
                    yield token
            except Exception:
                continue

async def _stream_gemini(messages: list, api_key: str, model: str, max_tokens: int):
    """Token-by-token streaming from Google Gemini via its OpenAI-compatible endpoint."""
    import openai as _oai
    client = _oai.AsyncOpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    stream = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, stream=True, temperature=0.1,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content

async def _stream_emergent(messages: list, api_key: str, model: str, max_tokens: int):
    """Token-by-token streaming via the Emergent universal key (OpenAI-compatible gateway)."""
    import openai as _oai
    client = _oai.AsyncOpenAI(
        api_key=api_key,
        base_url=os.environ.get("EMERGENT_BASE_URL", "https://api.emergentmind.com/v1"),
    )
    stream = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, stream=True, temperature=0.1,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content

async def _stream_xai(messages: list, api_key: str, model: str, max_tokens: int):
    """Token-by-token streaming from xAI Grok via its OpenAI-compatible endpoint."""
    import openai as _oai
    client = _oai.AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.x.ai/v1",
    )
    stream = await client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, stream=True, temperature=0.1,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content

async def _stream_bedrock(messages: list, model: str, max_tokens: int):
    """Token-by-token streaming from Amazon Bedrock via Converse streaming API.
    boto3 is synchronous — runs in a thread pool; tokens passed back via asyncio.Queue.
    Supports Amazon Nova family (nova-micro, nova-lite, nova-pro) and any Converse-compatible model.
    """
    if not _AWS_ACCESS_KEY or not _AWS_SECRET_KEY:
        raise ValueError("AWS credentials not configured (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)")

    # Convert OpenAI-format messages to Bedrock Converse format
    system_parts = []
    converse_messages = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            system_parts.append({"text": content})
        else:
            converse_messages.append({"role": role, "content": [{"text": content}]})

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _sync_stream():
        try:
            import boto3 as _boto3
            client = _boto3.client(
                "bedrock-runtime",
                region_name=_AWS_REGION,
                aws_access_key_id=_AWS_ACCESS_KEY,
                aws_secret_access_key=_AWS_SECRET_KEY,
            )
            kwargs = dict(
                modelId=model,
                messages=converse_messages,
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.1},
            )
            if system_parts:
                kwargs["system"] = system_parts
            resp = client.converse_stream(**kwargs)
            for event in resp["stream"]:
                if "contentBlockDelta" in event:
                    text = event["contentBlockDelta"].get("delta", {}).get("text", "")
                    if text:
                        loop.call_soon_threadsafe(queue.put_nowait, text)
            loop.call_soon_threadsafe(queue.put_nowait, None)   # sentinel → done
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)

    loop.run_in_executor(None, _sync_stream)

    while True:
        item = await queue.get()
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        yield item


async def call_llm_api_stream(messages: list, model: str = None, max_tokens: int = 2048):
    """
    Real token-by-token streaming from the LLM provider.
    Uses native streaming APIs for instant first-token delivery.
    Supports: Sarvam, Groq, Fireworks, Gemini, xAI, Bedrock.
    If the requested model name is not in _MODEL_PROVIDER_MAP (e.g. a display-only alias
    like 'openai/gpt-oss-20b'), the resolved provider's default model is used instead.
    """
    use_model_raw = model or LLM_MODEL
    # Resolve display-alias → real API model name (e.g. openai/gpt-oss-20b → llama-3.3-70b-versatile)
    use_model_resolved = _MODEL_ALIAS_MAP.get(use_model_raw, use_model_raw)
    provider, key = _resolve_provider_for_model(use_model_resolved, _LLM_PROVIDERS_CHAT)
    if use_model_raw != use_model_resolved:
        logger.info(f"Model alias '{use_model_raw}' → '{use_model_resolved}' ({provider})")
    # If still not a known API model, fall back to provider default
    if use_model_resolved not in _MODEL_PROVIDER_MAP:
        matched = next((p for p in _LLM_PROVIDERS_CHAT if p["provider"] == provider), None)
        use_model = matched["default_model"] if matched else LLM_MODEL
        logger.info(f"Unknown model '{use_model_resolved}' → provider default '{use_model}' ({provider})")
    else:
        use_model = use_model_resolved

    if not key and provider != "sarvam":
        yield f"data: {json.dumps({'error': 'LLM API key not configured'})}\n\n"
        return

    in_think = False
    buf = ""

    # Batch small tokens before serialising — reduces JSON ops from ~150 → ~8 per response
    _SSE_BATCH = 8    # flush frequently — words appear one-by-one, not in large chunks

    async def _emit_tokens(token_source):
        nonlocal in_think, buf
        _CLOSE_KEEP = len('</think>') - 1   # 7
        think_done  = False  # once True: no more think-blocks possible → fast path
        batch       = ""     # accumulator for batched SSE content

        async for token in token_source:
            # ── Fast path: think block already finished, just batch & yield ──
            if think_done:
                batch += token
                if len(batch) >= _SSE_BATCH:
                    yield f"data: {json.dumps({'content': batch})}\n\n"
                    batch = ""
                continue

            # ── Slow path: still scanning for <think>...</think> ─────────────
            buf += token
            while buf:
                if in_think:
                    close_idx = buf.find('</think>')
                    if close_idx != -1:
                        buf = buf[close_idx + 8:]
                        in_think   = False
                        think_done = True   # no more think blocks after this
                        # flush any content that immediately follows </think>
                        if buf:
                            batch += buf
                            buf = ""
                            if len(batch) >= _SSE_BATCH:
                                yield f"data: {json.dumps({'content': batch})}\n\n"
                                batch = ""
                        break
                    else:
                        buf = buf[-_CLOSE_KEEP:] if len(buf) > _CLOSE_KEEP else buf
                        break
                else:
                    open_idx = buf.find('<think>')
                    if open_idx != -1:
                        before = buf[:open_idx]
                        if before:
                            batch += before
                            if len(batch) >= _SSE_BATCH:
                                yield f"data: {json.dumps({'content': batch})}\n\n"
                                batch = ""
                        buf      = buf[open_idx + 7:]
                        in_think = True
                    elif buf.endswith(('<', '<t', '<th', '<thi', '<thin', '<think')):
                        partial_start = buf.rfind('<')
                        candidate     = buf[partial_start:]
                        if '<think>'[:len(candidate)] == candidate:
                            before = buf[:partial_start]
                            if before:
                                batch += before
                                if len(batch) >= _SSE_BATCH:
                                    yield f"data: {json.dumps({'content': batch})}\n\n"
                                    batch = ""
                            buf = candidate
                            break
                        else:
                            batch += buf
                            buf    = ""
                            if len(batch) >= _SSE_BATCH:
                                yield f"data: {json.dumps({'content': batch})}\n\n"
                                batch = ""
                    else:
                        batch += buf
                        buf    = ""
                        if len(batch) >= _SSE_BATCH:
                            yield f"data: {json.dumps({'content': batch})}\n\n"
                            batch = ""
                        break

        # Flush any remaining content
        if batch and not in_think:
            yield f"data: {json.dumps({'content': batch})}\n\n"
        if buf and not in_think:
            yield f"data: {json.dumps({'content': buf})}\n\n"

    async def _stream_from_provider(p_name: str, p_key: str, p_model: str):
        """Yield raw tokens from a provider. Raises on failure."""
        _mt = _clamp_max_tokens(p_model, max_tokens)
        if p_name == "sarvam":
            async for token in _stream_sarvam(messages, p_key, p_model, _mt):
                yield token
        elif p_name == "gemini":
            logger.info(f"LLM stream: provider=gemini, model={p_model}")
            async for token in _stream_gemini(messages, p_key, p_model, _mt):
                yield token
        elif p_name == "emergent":
            logger.info(f"LLM stream: provider=emergent, model={p_model}")
            async for token in _stream_emergent(messages, p_key, p_model, _mt):
                yield token
        elif p_name == "xai":
            logger.info(f"LLM stream: provider=xai, model={p_model}")
            async for token in _stream_xai(messages, p_key, p_model, _mt):
                yield token
        elif p_name == "bedrock":
            logger.info(f"LLM stream: provider=bedrock, model={p_model}")
            async for token in _stream_bedrock(messages, p_model, _mt):
                yield token
        else:
            logger.info(f"LLM stream: provider={p_name}, model={p_model}")
            chat = LlmChat(api_key=p_key or OPENAI_API_KEY, session_id=str(uuid.uuid4())).with_model(p_name, p_model)
            async for token in chat.stream_messages(messages, max_tokens=_mt):
                yield token

    # ── Syrabit SLM: concurrent smart pool ──────────────────────────────────────
    # pick() returns highest-capacity, least-recently-used slot not in cooldown.
    # async with slot["sem"] lets up to max_concurrent requests run in parallel.
    # asyncio.wait_for enforces a per-slot timeout so a slow provider never
    # blocks the pool — the next slot is tried immediately on timeout.
    _SLM_SLOT_TIMEOUT = 25.0   # max seconds to wait for first token from any slot

    async def _collect_stream(p_name, p_key, p_model):
        """Buffer entire token stream into a list and return it (for timeout wrapper)."""
        tokens = []
        async for chunk in _emit_tokens(_stream_from_provider(p_name, p_key, p_model)):
            tokens.append(chunk)
        return tokens

    if use_model_raw == "openai/gpt-oss-20b":
        _tried = 0
        while _tried < len(_slm_pool.all_slots):
            slot = _slm_pool.pick()
            if slot is None:
                break
            _tried += 1
            p_name, p_key, p_model = slot["provider"], slot["key"], slot["model"]
            try:
                async with slot["sem"]:          # acquire capacity; released after stream
                    chunks = await asyncio.wait_for(
                        _collect_stream(p_name, p_key, p_model),
                        timeout=_SLM_SLOT_TIMEOUT,
                    )
                if chunks:
                    _slm_pool.mark_ok(slot)
                    for chunk in chunks:
                        yield chunk
                    return
                _slm_pool.mark_err(slot)
                logger.warning(f"SLM pool: {p_name}/{p_model} yielded no tokens")
            except asyncio.TimeoutError:
                _slm_pool.mark_err(slot)
                logger.warning(f"SLM pool: {p_name}/{p_model} timed out after {_SLM_SLOT_TIMEOUT}s → trying next")
                continue
            except Exception as e:
                err_str = str(e)
                is_429 = "429" in err_str or "413" in err_str or "rate" in err_str.lower() or "quota" in err_str.lower() or "throttl" in err_str.lower() or "too large" in err_str.lower()
                is_403 = "403" in err_str or "forbidden" in err_str.lower() or "permission" in err_str.lower() or "unauthorized" in err_str.lower()
                if is_429:
                    _slm_pool.mark_429(slot)
                elif is_403:
                    _slm_pool.mark_403(slot)
                else:
                    _slm_pool.mark_err(slot)
                logger.warning(f"SLM pool: {p_name}/{p_model} failed ({type(e).__name__}: {err_str[:80]})")
                continue
        yield f"data: {json.dumps({'error': 'All AI providers temporarily unavailable'})}\n\n"
        return

    # ── All other models: single provider ───────────────────────────────────────
    try:
        async for chunk in _emit_tokens(_stream_from_provider(provider, key, use_model)):
            yield chunk
    except HTTPException as http_err:
        yield f"data: {json.dumps({'error': str(http_err.detail)})}\n\n"
    except Exception as e:
        logger.error(f"LLM streaming error: {type(e).__name__}: {str(e)[:200]}")
        yield f"data: {json.dumps({'error': 'AI service temporarily unavailable'})}\n\n"
