"""Syrabit.ai — LLM infrastructure: batching, smart key pool, streaming."""
import os, re, json, asyncio, uuid, time, logging
from typing import Dict, Optional
from fastapi import HTTPException
from emergentintegrations.llm.chat import LlmChat, UserMessage
from config import (
    LLM_PROVIDER, LLM_MODEL, OPENAI_API_KEY, SARVAM_THINK_BUFFER,
    _GROQ_KEY, _GEMINI_KEY, _XAI_KEY, _OPENAI_KEY, _FIREWORKS_KEY,
    _SARVAM_LLM_KEY, _AWS_ACCESS_KEY, _AWS_SECRET_KEY, _AWS_REGION,
)
from deps import sarvam_llm_client, logger as _dep_logger
from cache import _cache_key

logger = logging.getLogger(__name__)

_LLM_SEMAPHORE = asyncio.Semaphore(int(os.environ.get("LLM_MAX_CONCURRENT", 20)))
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

    async def call(self, messages: list, model: str = None, max_tokens: int = 1024) -> str:
        batch_key = _cache_key(
            "".join(m.get("content", "") for m in messages if m.get("role") in ("user", "system"))
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
                asyncio.ensure_future(self._execute(batch_key, messages, model, max_tokens, future))

        try:
            return await asyncio.wait_for(future, timeout=120)
        except asyncio.TimeoutError:
            logger.error(f"LLM batch TIMEOUT: {batch_key}")
            raise HTTPException(status_code=504, detail="AI response timed out. Please try again.")

    async def _execute(self, batch_key: str, messages: list, model: str, max_tokens: int, future: asyncio.Future):
        await asyncio.sleep(_LLM_BATCH_WINDOW_MS / 1000.0)

        try:
            async with _LLM_SEMAPHORE:
                result = await _call_llm_raw(messages, model, max_tokens)
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
# Gemini first — most reliable right now (Fireworks suspended, Groq rate-limited)
if _GEMINI_KEY:
    _LLM_PROVIDERS.append({"provider": "gemini",      "key": _GEMINI_KEY,     "default_model": "gemini-2.5-flash-preview-05-20"})
if _GROQ_KEY and _GROQ_KEY != 'x':
    _LLM_PROVIDERS.append({"provider": "groq",        "key": _GROQ_KEY,       "default_model": "llama-3.1-8b-instant"})
if _FIREWORKS_KEY:
    _LLM_PROVIDERS.append({"provider": "fireworksai", "key": _FIREWORKS_KEY,  "default_model": "accounts/fireworks/models/deepseek-v3p2"})
if _SARVAM_LLM_KEY:
    _LLM_PROVIDERS.append({"provider": "sarvam",      "key": _SARVAM_LLM_KEY, "default_model": "sarvam-m"})
if _XAI_KEY:
    _LLM_PROVIDERS.append({"provider": "xai",         "key": _XAI_KEY,        "default_model": "grok-3-fast"})
if _OPENAI_KEY and _OPENAI_KEY != 'x':
    _LLM_PROVIDERS.append({"provider": "openai",      "key": _OPENAI_KEY,     "default_model": "gpt-4o-mini"})

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
    # Gemini 2.5 Flash Preview — primary: best accuracy + reasoning
    ("gemini",      "gemini-2.5-flash-preview-05-20",                    6),
    # Gemini 2.0 Flash — fallback: high TPS when primary is rate-limited
    ("gemini",      "gemini-2.0-flash",                                  6),
    # Gemini 2.0 Flash Lite — hot fallback: highest TPS, lowest latency
    ("gemini",      "gemini-2.0-flash-lite",                             8),
    # Groq as secondary (rate-limited but fast when available)
    ("groq",        "llama-3.3-70b-versatile",                           8),
    ("groq",        "llama-3.1-8b-instant",                              4),
    # Fireworks last (currently suspended)
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
        pmap = {p["provider"]: p["key"] for p in _LLM_PROVIDERS}
        self._slots = []
        for pname, model_id, max_con in candidates:
            key = pmap.get(pname, "")
            # bedrock uses AWS env-var credentials, not a provider API key
            # sarvam also has no key in pmap
            if key or pname in ("sarvam", "bedrock"):
                # for bedrock: only add slot if AWS credentials are present
                if pname == "bedrock" and not (_AWS_ACCESS_KEY and _AWS_SECRET_KEY):
                    logger.info("SLM pool: skipping bedrock slot (AWS credentials not set)")
                    continue
                self._slots.append({
                    "provider": pname, "key": key, "model": model_id,
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

def _resolve_provider_for_model(model: str):
    preferred = _MODEL_PROVIDER_MAP.get(model)
    if preferred:
        for p in _LLM_PROVIDERS:
            if p["provider"] == preferred:
                return p["provider"], p["key"]
    if _LLM_PROVIDERS:
        return _LLM_PROVIDERS[0]["provider"], _LLM_PROVIDERS[0]["key"]
    return LLM_PROVIDER, OPENAI_API_KEY

async def _call_sarvam_llm(messages: list, api_key: str, model: str, max_tokens: int) -> str:
    """Non-streaming call to Sarvam LLM — reuses persistent sarvam_llm_client (zero TCP overhead).
    Adds SARVAM_THINK_BUFFER so the <think> block never consumes the user's answer budget."""
    api_max = max_tokens + SARVAM_THINK_BUFFER  # thinking tokens don't count toward user quota
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": api_max,
        "temperature": 0.05,
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

async def _call_single_provider(messages: list, provider: str, api_key: str, model: str, max_tokens: int) -> str:
    if provider == "sarvam":
        return await _call_sarvam_llm(messages, api_key, model, max_tokens)

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

async def _call_llm_raw(messages: list, model: str = None, max_tokens: int = 1024) -> str:
    import time as _t
    use_model = model or LLM_MODEL
    primary_provider, primary_key = _resolve_provider_for_model(use_model)

    if not primary_key and not _LLM_PROVIDERS:
        raise HTTPException(status_code=503, detail="LLM API key not configured")

    tried: set = set()  # tracks (provider, model) tuples — allows multiple models per provider
    last_err = None

    provider, key = primary_provider, primary_key
    try_model = use_model
    try:
        tried.add((provider, try_model))
        _t0 = _t.perf_counter()
        result = await _call_single_provider(messages, provider, key, try_model, max_tokens)
        _dur = int((_t.perf_counter() - _t0) * 1000)
        logger.info(f"llm_call provider={provider} model={try_model} duration_ms={_dur} tokens_approx={len(result.split())}")
        return result
    except Exception as e:
        last_err = e
        logger.warning(f"LLM primary failed ({provider}/{try_model}): {type(e).__name__}: {str(e)[:150]}")

    for fallback in _LLM_PROVIDERS:
        fb_model = fallback["default_model"]
        if (fallback["provider"], fb_model) in tried:
            continue
        tried.add((fallback["provider"], fb_model))
        try:
            _t0 = _t.perf_counter()
            result = await _call_single_provider(messages, fallback["provider"], fallback["key"], fb_model, max_tokens)
            _dur = int((_t.perf_counter() - _t0) * 1000)
            logger.info(f"llm_call provider={fallback['provider']} model={fb_model} duration_ms={_dur} tokens_approx={len(result.split())} fallback=true")
            return result
        except Exception as e:
            last_err = e
            logger.warning(f"LLM fallback failed ({fallback['provider']}/{fb_model}): {type(e).__name__}: {str(e)[:150]}")

    logger.error(f"All LLM providers exhausted. Last error: {last_err}")
    raise HTTPException(status_code=503, detail="AI service temporarily unavailable. Please try again.")

async def call_llm_api(messages: list, model: str = None, max_tokens: int = 2048) -> str:
    """Smart-batched LLM call: deduplicates identical requests, limits concurrency."""
    return await _llm_batcher.call(messages, model, max_tokens)


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
        "temperature": 0.0,
        "top_p": 1.0,
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
        model=model, messages=messages, max_tokens=max_tokens, stream=True, temperature=0.05,
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
        model=model, messages=messages, max_tokens=max_tokens, stream=True, temperature=0.05,
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
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.05},
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
    provider, key = _resolve_provider_for_model(use_model_resolved)
    if use_model_raw != use_model_resolved:
        logger.info(f"Model alias '{use_model_raw}' → '{use_model_resolved}' ({provider})")
    # If still not a known API model, fall back to provider default
    if use_model_resolved not in _MODEL_PROVIDER_MAP:
        matched = next((p for p in _LLM_PROVIDERS if p["provider"] == provider), None)
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
        if p_name == "sarvam":
            async for token in _stream_sarvam(messages, p_key, p_model, max_tokens):
                yield token
        elif p_name == "gemini":
            logger.info(f"LLM stream: provider=gemini, model={p_model}")
            async for token in _stream_gemini(messages, p_key, p_model, max_tokens):
                yield token
        elif p_name == "xai":
            logger.info(f"LLM stream: provider=xai, model={p_model}")
            async for token in _stream_xai(messages, p_key, p_model, max_tokens):
                yield token
        elif p_name == "bedrock":
            logger.info(f"LLM stream: provider=bedrock, model={p_model}")
            async for token in _stream_bedrock(messages, p_model, max_tokens):
                yield token
        else:
            logger.info(f"LLM stream: provider={p_name}, model={p_model}")
            chat = LlmChat(api_key=p_key or OPENAI_API_KEY, session_id=str(uuid.uuid4())).with_model(p_name, p_model)
            async for token in chat.stream_messages(messages, max_tokens=max_tokens):
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
                is_429 = "429" in err_str or "rate" in err_str.lower() or "quota" in err_str.lower() or "throttl" in err_str.lower()
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
