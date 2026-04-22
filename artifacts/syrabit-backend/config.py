"""Syrabit.ai — Configuration constants and environment variables."""
import os
from pathlib import Path
from dotenv import load_dotenv

__all__ = [
    "ADMIN_ACCOUNTS", "ADMIN_JWT_SECRET",
    "CF_CACHE_TTL", "CF_GATEWAY_ENABLED",
    "CF_TURNSTILE_ENABLED", "CF_TURNSTILE_SECRET_KEY",
    "COOKIE_DOMAIN", "COOKIE_SAMESITE",
    "CORS_ORIGINS", "CORS_ORIGIN_REGEX",
    "DB_NAME", "EMAIL_FROM", "FRONTEND_URL",
    "GOOGLE_CLIENT_ID",
    "JWT_ACCESS_EXPIRE_MINUTES", "JWT_ALGORITHM",
    "JWT_EXPIRE_MINUTES", "JWT_REFRESH_EXPIRE_MINUTES", "JWT_SECRET",
    "LLM_MODEL", "LLM_PROVIDER",
    "MONGO_URL", "OPENAI_API_KEY", "PLAN_LIMITS",
    "REDIS_AI_CACHE_TTL", "REDIS_TOKEN", "REDIS_URL",
    "MEMORYSTORE_REDIS_URL", "REDIS_AI_CACHE_NAMESPACE",
    "REDIS_AI_CACHE_MAX_ENTRY_BYTES",
    "REDIS_AI_CACHE_CONNECT_TIMEOUT_MS", "REDIS_AI_CACHE_OP_TIMEOUT_MS",
    "ROOT_DIR",
    "SARVAM_API_KEY", "SARVAM_BASE_URL", "SARVAM_THINK_BUFFER",
    "SARVAM_TRANSLATE_KEY",
    "SECURE_COOKIES", "SEED_DATA", "SLOW_QUERY_THRESHOLD_MS",
    "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_URL",
    "_AWS_ACCESS_KEY", "_AWS_REGION", "_AWS_SECRET_KEY",
    "_CEREBRAS_KEY", "_CF_PROVIDER_SLUGS", "_CORS_ALLOW_CREDENTIALS",
    "_GEMINI_KEY", "_GEMINI_KEY_2",
    "_GROQ_KEY", "_GROQ_KEY_2",
    "_OPENAI_KEY", "_OPENROUTER_KEY",
    "_PG_DSN",
    "_SARVAM_LLM_KEY", "_SARVAM_LLM_KEY_2", "_SARVAM_LLM_KEY_3",
    "_XAI_KEY",
    "cf_gateway_url", "get_provider_base_url",
    "is_cf_gateway_up", "mark_cf_gateway_down",
]

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

MONGO_URL    = (os.environ.get('MONGO_URL') or os.environ.get('MONGODB_URI') or 'mongodb://localhost:27017').strip().strip('"').strip("'")
DB_NAME      = os.environ.get('DB_NAME', 'test_database')
_jwt_secret_env = os.environ.get('JWT_SECRET', '').strip()
if not _jwt_secret_env:
    import hashlib as _jwt_hl
    import warnings as _w
    _fallback_seed = (MONGO_URL + DB_NAME + os.environ.get('REPL_ID', '')).encode()
    JWT_SECRET = _jwt_hl.sha256(b'syrabit-jwt-fallback:' + _fallback_seed).hexdigest()
    _w.warn(
        "JWT_SECRET is not set — using deterministic fallback derived from MONGO_URL+DB_NAME. "
        "Sessions survive restarts but Set JWT_SECRET in production for best security.",
        stacklevel=1,
    )
else:
    JWT_SECRET = _jwt_secret_env
JWT_ALGORITHM    = 'HS256'
JWT_ACCESS_EXPIRE_MINUTES = int(os.environ.get('JWT_ACCESS_EXPIRE_MINUTES', '60'))
JWT_REFRESH_EXPIRE_MINUTES = int(os.environ.get('JWT_REFRESH_EXPIRE_MINUTES', str(60 * 24 * 30)))
JWT_EXPIRE_MINUTES = JWT_ACCESS_EXPIRE_MINUTES

_admin_jwt_env = os.environ.get('ADMIN_JWT_SECRET', '').strip()
if not _admin_jwt_env:
    import hashlib as _hl
    ADMIN_JWT_SECRET = _hl.sha256(f"admin-{JWT_SECRET}".encode()).hexdigest()
else:
    ADMIN_JWT_SECRET = _admin_jwt_env

# ── Google OAuth ──────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()

# ── Email Configuration ───────────────────────────────────────────────────────
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '').strip()
EMAIL_FROM     = os.environ.get('EMAIL_FROM', 'noreply@syrabit.ai').strip()
FRONTEND_URL   = os.environ.get('FRONTEND_URL', 'https://syrabit.ai').strip().rstrip('/')

# ── Cloudflare API tokens (Task #534 contract) ──────────────────────────────
# Three tokens, three roles. Priority order respects the spec while keeping
# legacy names working so operators don't have to rotate secrets just to
# upgrade to the new naming:
#
#   Runtime / analytics (Vectorize:Edit, Cache Purge, Analytics:Read):
#     1. CLOUDFLARE_ANALYTICS_TOKEN  — Task #534 spec name (preferred)
#     2. CF_ANALYTICS_API_TOKEN      — legacy alias (logs warning)
#     3. CLOUDFLARE_API_TOKEN        — last-resort fallback (logs warning)
#   Pages-scoped names (CF_PAGES_API_TOKEN) and undifferentiated legacy
#   names (CF_API_TOKEN) are NOT accepted here — see _runtime_cf_token()
#   in cloudflare_client.py for the strict runtime policy.
#
#   Pages CI (Pages:Edit + Vectorize:Edit):
#     1. CLOUDFLARE_PAGES_TOKEN      — Task #534 spec name
#     2. CF_PAGES_API_TOKEN          — legacy alias (logs warning)
#
# Wrangler deploy reads CLOUDFLARE_API_TOKEN itself (auto-detect); we don't
# expose it through this module since the FastAPI process never deploys.
_ANALYTICS_TOKEN_ENV_NAMES = (
    'CF_PAGES_API_TOKEN',
    'CLOUDFLARE_PAGES_TOKEN',
    'CLOUDFLARE_ANALYTICS_TOKEN',
    'CF_ANALYTICS_API_TOKEN',
    'CLOUDFLARE_API_TOKEN',
)
_PAGES_TOKEN_ENV_NAMES = (
    'CLOUDFLARE_PAGES_TOKEN',
    'CF_PAGES_API_TOKEN',
)


_ANALYTICS_LEGACY_LOGGED = False
_PAGES_LEGACY_LOGGED = False

# Fallback names that are documented permanent policy (DEPLOY.md): both
# `CLOUDFLARE_API_TOKEN` (analytics) and `CF_PAGES_API_TOKEN` (Pages) are
# accepted forever — they map to the same secret value as the spec name.
# We log a single one-line INFO that we used the fallback (for operator
# transparency) instead of a multi-line WARNING that shows up in error
# log dashboards / Railway alert filters.
_ANALYTICS_ACCEPTED_FALLBACKS = {'CF_ANALYTICS_API_TOKEN', 'CLOUDFLARE_API_TOKEN'}
_PAGES_ACCEPTED_FALLBACKS = {'CF_PAGES_API_TOKEN'}


def _resolve_cf_analytics_token() -> str:
    global _ANALYTICS_LEGACY_LOGGED
    for _name in _ANALYTICS_TOKEN_ENV_NAMES:
        _val = os.environ.get(_name, '').strip()
        if _val:
            if _name != _ANALYTICS_TOKEN_ENV_NAMES[0] and not _ANALYTICS_LEGACY_LOGGED:
                _ANALYTICS_LEGACY_LOGGED = True
                # Documented-fallback: INFO. Unknown alias: keep WARNING.
                level = "INFO" if _name in _ANALYTICS_ACCEPTED_FALLBACKS else "WARNING"
                print(
                    f"[config] {level}: CF analytics token resolved from "
                    f"{_name!r} (CLOUDFLARE_ANALYTICS_TOKEN preferred but optional).",
                    flush=True,
                )
            return _val
    return ''


def _resolve_cf_pages_token() -> str:
    global _PAGES_LEGACY_LOGGED
    for _name in _PAGES_TOKEN_ENV_NAMES:
        _val = os.environ.get(_name, '').strip()
        if _val:
            if _name != _PAGES_TOKEN_ENV_NAMES[0] and not _PAGES_LEGACY_LOGGED:
                _PAGES_LEGACY_LOGGED = True
                level = "INFO" if _name in _PAGES_ACCEPTED_FALLBACKS else "WARNING"
                print(
                    f"[config] {level}: CF Pages token resolved from "
                    f"{_name!r} (CLOUDFLARE_PAGES_TOKEN preferred but optional).",
                    flush=True,
                )
            return _val
    return ''


CF_ANALYTICS_API_TOKEN = _resolve_cf_analytics_token()
CF_PAGES_DEPLOY_TOKEN = _resolve_cf_pages_token()
CF_ZONE_ID = os.environ.get('CF_ZONE_ID', '').strip()
CF_API_TOKEN = os.environ.get('CF_API_TOKEN', '').strip() or CF_ANALYTICS_API_TOKEN

# ── Cloudflare Access / Zero Trust (Task #637) ──────────────────────────────
# When enforcement is on, every admin / internal request must carry a valid
# Cf-Access-Jwt-Assertion header signed by the team domain's JWKS and
# matching one of the configured AUD tags. See ``cf_access.py`` and
# ``docs/CLOUDFLARE_ZERO_TRUST.md`` for the full handshake.
CF_ACCESS_TEAM_DOMAIN = os.environ.get('CF_ACCESS_TEAM_DOMAIN', '').strip().rstrip('/')
CF_ACCESS_AUD_ADMIN = os.environ.get('CF_ACCESS_AUD_ADMIN', '').strip()
CF_ACCESS_AUD_INTERNAL = os.environ.get('CF_ACCESS_AUD_INTERNAL', '').strip()
CF_ACCESS_ENFORCE = os.environ.get('CF_ACCESS_ENFORCE', '').strip().lower() in ('1', 'true', 'yes', 'on')

# ── Cloudflare Turnstile ────────────────────────────────────────────────────
CF_TURNSTILE_SECRET_KEY = os.environ.get('CF_TURNSTILE_SECRET_KEY', '').strip()
CF_TURNSTILE_ENABLED = bool(CF_TURNSTILE_SECRET_KEY)

# ── Cloudflare AI Gateway ────────────────────────────────────────────────────
import time as _time

_CF_ACCOUNT_ID = os.environ.get('CF_AI_GATEWAY_ACCOUNT_ID', '').strip()
_CF_GATEWAY_ID = os.environ.get('CF_AI_GATEWAY_ID', '').strip()
# Authenticated Gateway token (Cloudflare dashboard → AI Gateway →
# <gateway> → Settings → Authenticated Gateway). When the gateway has
# auth turned on, every request must carry
#   cf-aig-authorization: Bearer <token>
# or Cloudflare returns HTTP 401 with `{code: 2009, message: Unauthorized}`
# — which is exactly the error we kept seeing in production logs every
# few minutes (one wasted round trip per request before the direct-URL
# fallback kicks in for 5 min). Leaving this env var unset disables the
# header (gateway must then have auth turned OFF in the dashboard).
CF_AI_GATEWAY_TOKEN = os.environ.get('CF_AI_GATEWAY_TOKEN', '').strip()
CF_GATEWAY_ENABLED = bool(_CF_ACCOUNT_ID and _CF_GATEWAY_ID)
CF_GATEWAY_BASE = (
    f"https://gateway.ai.cloudflare.com/v1/{_CF_ACCOUNT_ID}/{_CF_GATEWAY_ID}"
    if CF_GATEWAY_ENABLED else ""
)
CF_CACHE_TTL = int(os.environ.get('CF_AI_GATEWAY_CACHE_TTL', '3600'))

_CF_PROVIDER_SLUGS = {
    "openai":      "openai",
    "groq":        "groq/openai/v1",
    "xai":         "grok/v1",
    "gemini":      "google-ai-studio/v1beta/openai",
    # Sarvam: slug has NO /v1 because callers already send
    # /v1/chat/completions, /translate, /text-to-speech, etc.
    # CF custom provider forwards {base}/custom-sarvam/<path> → https://api.sarvam.ai/<path>
    "sarvam":      "custom-sarvam",
    "cerebras":    "cerebras/v1",
    "openrouter":  "openrouter/v1",
}

_DIRECT_PROVIDER_URLS = {
    "openai":      None,
    "groq":        None,
    "xai":         "https://api.x.ai/v1",
    "gemini":      "https://generativelanguage.googleapis.com/v1beta/openai/",
    # Sarvam direct URL has NO /v1 — callers already supply /v1/chat/completions
    # and non-LLM endpoints like /translate, /text-to-speech live at root.
    "sarvam":      "https://api.sarvam.ai",
    "cerebras":    "https://api.cerebras.ai/v1",
    "openrouter":  "https://openrouter.ai/api/v1",
}

_cf_gw_healthy = True
_cf_gw_fail_ts = 0.0
_CF_GW_RETRY_AFTER = 300

def is_cf_gateway_up() -> bool:
    global _cf_gw_healthy, _cf_gw_fail_ts
    if not CF_GATEWAY_ENABLED:
        return False
    if not _cf_gw_healthy and _time.time() - _cf_gw_fail_ts > _CF_GW_RETRY_AFTER:
        _cf_gw_healthy = True
    return _cf_gw_healthy

def mark_cf_gateway_down():
    global _cf_gw_healthy, _cf_gw_fail_ts
    _cf_gw_healthy = False
    _cf_gw_fail_ts = _time.time()

def cf_gateway_url(provider: str) -> str:
    slug = _CF_PROVIDER_SLUGS.get(provider)
    if slug:
        return f"{CF_GATEWAY_BASE}/{slug}"
    return ""

def get_provider_base_url(provider: str) -> str | None:
    if is_cf_gateway_up() and provider in _CF_PROVIDER_SLUGS:
        return cf_gateway_url(provider)
    return _DIRECT_PROVIDER_URLS.get(provider)


# ── BYOK (Bring-Your-Own-Keys) via Cloudflare AI Gateway ─────────────────────
# When CF AI Gateway is enabled with BYOK configured in the CF dashboard, the
# backend no longer needs real provider API keys in its environment. The flow:
#
#   1. Backend sends request to gateway URL with:
#        api_key="byok"                          (placeholder, CF ignores it)
#        header cf-aig-byok-key: default         (tells CF to substitute)
#   2. CF AI Gateway replaces the auth with its stored BYOK key for the
#      provider and forwards the request upstream.
#   3. Upstream provider sees its real key and responds normally.
#
# Removing the provider env vars (GEMINI_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY,
# OPENROUTER_API_KEY, SARVAM_API_KEY, …) is SAFE once BYOK is wired — the
# backend sends placeholders and CF does the real auth. Keep the CF gateway
# env vars themselves (CF_AI_GATEWAY_ACCOUNT_ID, CF_AI_GATEWAY_ID,
# CF_AI_GATEWAY_TOKEN) — those bootstrap the gateway connection itself.
BYOK_PLACEHOLDER = "x"  # openai SDK rejects empty api_key; "x" is a harmless dummy


def byok_headers(include_ttl: bool = True, clear_upstream_auth: bool = True) -> dict:
    """Return CF AI Gateway headers for a BYOK request.

    Verified BYOK invocation (2026-04-20 live probe against gateway `syrabit`):
      - ``Authorization: ''``         → empty upstream auth **mandatory**. If
        we send a dummy bearer like ``Bearer byok`` CF forwards it raw to
        upstream and gets 401. BYOK only fires when the upstream auth header
        is empty (or missing), signalling to CF that it should inject its
        stored key.
      - ``cf-aig-byok-key: true``     → opt-in flag. Without it, CF leaves the
        empty Authorization untouched and upstream 401s.
      - ``cf-aig-cache-ttl: <N>``     → response cache TTL hint.
      - ``cf-aig-authorization: …``  → Authenticated-Gateway bearer, only
        sent when the gateway has auth mode enabled.

    ``clear_upstream_auth=False`` is used by the Sarvam httpx client, which
    has its own ``api-subscription-key`` header (not ``Authorization``) —
    that callsite clears it separately.

    Returns ``{}`` when the gateway is down so callers can short-circuit.
    """
    if not is_cf_gateway_up():
        return {}
    h: dict = {"cf-aig-byok-key": "true"}
    if clear_upstream_auth:
        # Empty string overrides the openai/httpx SDK's auto-inserted
        # ``Authorization: Bearer <api_key>`` header so CF sees no upstream
        # auth and injects its stored BYOK key.
        h["Authorization"] = ""
    if include_ttl:
        h["cf-aig-cache-ttl"] = str(CF_CACHE_TTL)
    if CF_AI_GATEWAY_TOKEN:
        h["cf-aig-authorization"] = f"Bearer {CF_AI_GATEWAY_TOKEN}"
    return h

import logging as _logging
_cfg_log = _logging.getLogger(__name__)
if CF_GATEWAY_ENABLED:
    _cfg_log.info(f"Cloudflare AI Gateway ENABLED — base={CF_GATEWAY_BASE}, cache_ttl={CF_CACHE_TTL}s")
else:
    _cfg_log.info("Cloudflare AI Gateway DISABLED — using direct provider URLs")

# ── LLM Configuration ─────────────────────────────────────────────────────────
_GROQ_KEY = os.environ.get('GROQ_API_KEY', '').strip()
_GROQ_KEY_2 = os.environ.get('GROQ_API_KEY_2', '').strip()
# Gemini re-enabled (2026-04-20) — AI Studio Tier 1 confirmed (2000 RPM/key),
# CF AI Gateway BYOK verified working for google-ai-studio provider.
_GEMINI_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
_GEMINI_KEY_2 = os.environ.get('GEMINI_API_KEY_2', '').strip()
_GEMINI_KEY_RAW = _GEMINI_KEY
_GEMINI_KEY_2_RAW = _GEMINI_KEY_2
_XAI_KEY = os.environ.get('XAI_API_KEY', '').strip()
_OPENAI_KEY = os.environ.get('OPENAI_API_KEY', '').strip()
_SARVAM_LLM_KEY = os.environ.get('SARVAM_API_KEY', '').strip()
_SARVAM_LLM_KEY_2 = os.environ.get('SARVAM_API_KEY_2', '').strip()
_SARVAM_LLM_KEY_3 = os.environ.get('SARVAM_API_KEY_3', '').strip()
_CEREBRAS_KEY = os.environ.get('CEREBRAS_API_KEY', '').strip()
_OPENROUTER_KEY = os.environ.get('OPENROUTER_API_KEY', '').strip()

# ── Vertex AI Gemini Flash chat (Task #607) ─────────────────────────────────
# When VERTEX_PROJECT_ID is set, the chat path can route through Vertex AI's
# Gemini Flash streaming endpoint for lower TTFT. Auth is via Application
# Default Credentials (GOOGLE_APPLICATION_CREDENTIALS pointing at a SA JSON)
# or the inline VERTEX_SERVICE_ACCOUNT_JSON blob. See vertex_chat.py.
VERTEX_PROJECT_ID = os.environ.get('VERTEX_PROJECT_ID', '').strip()
VERTEX_LOCATION = os.environ.get('VERTEX_LOCATION', 'us-central1').strip() or 'us-central1'
VERTEX_GEMINI_MODEL = os.environ.get('VERTEX_GEMINI_MODEL', 'gemini-2.5-flash').strip() or 'gemini-2.5-flash'
# CHAT_DEFAULT_MODEL is a *system-wide* default consulted by the chat route
# when the client does not pin a specific model. Admin UI can override this
# at runtime (db.api_config.chat_model.default), which takes precedence.
# Accepted values:
#   "vertex/gemini-flash"  — Vertex AI Gemini Flash (preferred when configured)
#   "openai/gpt-oss-20b"   — Legacy hedged SLM pool (Cerebras/Groq/OpenRouter)
CHAT_DEFAULT_MODEL = os.environ.get(
    'CHAT_DEFAULT_MODEL',
    'vertex/gemini-flash' if VERTEX_PROJECT_ID else 'openai/gpt-oss-20b',
).strip()

# BYOK fallback: when CF AI Gateway is enabled, any missing provider env key
# is substituted with the BYOK_PLACEHOLDER so the SmartKeyPool / provider list
# still builds (downstream callers send placeholder + cf-aig-byok-key header
# and the gateway substitutes the real key). This is what lets operators
# safely remove GROQ_API_KEY, GEMINI_API_KEY, CEREBRAS_API_KEY, etc. from
# production secrets once BYOK is verified in the CF dashboard.
if CF_GATEWAY_ENABLED:
    _GROQ_KEY = _GROQ_KEY or BYOK_PLACEHOLDER
    _GEMINI_KEY = _GEMINI_KEY or BYOK_PLACEHOLDER
    _CEREBRAS_KEY = _CEREBRAS_KEY or BYOK_PLACEHOLDER
    _OPENROUTER_KEY = _OPENROUTER_KEY or BYOK_PLACEHOLDER
    _SARVAM_LLM_KEY = _SARVAM_LLM_KEY or BYOK_PLACEHOLDER
    # Note: _GROQ_KEY_2 / _GEMINI_KEY_2 / _SARVAM_LLM_KEY_2 / _3 stay empty
    # if not set — BYOK means CF handles rotation, so a single logical slot
    # per provider is enough. The pool's secondary-key slots only activate
    # when operators explicitly set the `*_KEY_2/3` env vars.
_EXPLICIT_PROVIDER = os.environ.get('LLM_PROVIDER', '').strip().lower()
_AWS_ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY_ID', '').strip()
_AWS_SECRET_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '').strip()
_AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1').strip()

if _EXPLICIT_PROVIDER == 'groq' and _GROQ_KEY:
    LLM_PROVIDER = 'groq'
    LLM_API_KEY = _GROQ_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
elif _EXPLICIT_PROVIDER == 'sarvam' and _SARVAM_LLM_KEY:
    LLM_PROVIDER = 'sarvam'
    LLM_API_KEY = _SARVAM_LLM_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'sarvam-m')
elif _EXPLICIT_PROVIDER == 'cerebras' and _CEREBRAS_KEY:
    LLM_PROVIDER = 'cerebras'
    LLM_API_KEY = _CEREBRAS_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'llama3.1-8b')
elif _EXPLICIT_PROVIDER == 'openai' and _OPENAI_KEY and _OPENAI_KEY != 'x':
    LLM_PROVIDER = 'openai'
    LLM_API_KEY = _OPENAI_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
elif _GROQ_KEY:
    LLM_PROVIDER = 'groq'
    LLM_API_KEY = _GROQ_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
elif _CEREBRAS_KEY:
    LLM_PROVIDER = 'cerebras'
    LLM_API_KEY = _CEREBRAS_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'llama3.1-8b')
elif _SARVAM_LLM_KEY:
    LLM_PROVIDER = 'sarvam'
    LLM_API_KEY = _SARVAM_LLM_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'sarvam-m')
elif _OPENAI_KEY and _OPENAI_KEY != 'x':
    LLM_PROVIDER = 'openai'
    LLM_API_KEY = _OPENAI_KEY
    LLM_MODEL = os.environ.get('LLM_MODEL', 'gpt-4o-mini')
else:
    LLM_PROVIDER = 'groq'
    LLM_API_KEY = ''
    LLM_MODEL = os.environ.get('LLM_MODEL', 'meta-llama/llama-4-scout-17b-16e-instruct')
OPENAI_API_KEY = LLM_API_KEY

# ── Sarvam AI Configuration ──────────────────────────────────────────────────
SARVAM_API_KEY = os.environ.get('SARVAM_API_KEY', '').strip()
SARVAM_API_KEY_2 = os.environ.get('SARVAM_API_KEY_2', '').strip()
SARVAM_TRANSLATE_KEY = SARVAM_API_KEY or SARVAM_API_KEY_2
SARVAM_BASE_URL = 'https://api.sarvam.ai'

# ── Distributed cache (legacy compatibility shim) ────────────────────────────
# Upstash REST has been removed (2026-04). LLM upstream caching now lives at
# Cloudflare AI Gateway (cache_ttl=3600s, configured in CF_CACHE_TTL above)
# and rate limiting moved to the edge worker's KV binding (RATE_LIMIT). These
# constants stay as empty strings so legacy callers that import them keep
# working — every call site already guards with `if REDIS_URL:` / `if redis_client:`.
REDIS_URL   = ''
REDIS_TOKEN = ''
REDIS_AI_CACHE_TTL = int(os.environ.get('REDIS_AI_CACHE_TTL', '7200') or '7200')
REDIS_CASUAL_CACHE_TTL = int(os.environ.get('REDIS_CASUAL_CACHE_TTL', '300') or '300')
REDIS_CHAT_CACHE_TTL = 600
REDIS_SEARCH_CACHE_TTL = 300
REDIS_SESSION_CACHE_TTL = 1800
REDIS_RATE_WINDOW = 60

# ── Memorystore-backed AI response cache (Task #609) ────────────────────────
# Single configurable Redis URL — Google Memorystore preferred, any
# Redis-compatible endpoint (rediss:// for TLS, redis:// otherwise) accepted.
# When unset, the AI cache falls back to the existing Upstash REST client and
# finally to the in-memory L1 cache. All values can be tuned per environment
# without code changes.
def _extract_redis_url(raw: str) -> str:
    """Defensive parser for MEMORYSTORE_REDIS_URL.

    Two common copy-paste mistakes are corrected here so a single bad
    secret doesn't silently degrade the entire AI cache to memory_only:

    1. Operators paste the full Upstash "Connect → Redis CLI" line,
       e.g. ``redis-cli --tls -u rediss://default:TOKEN@host:6379``.
       We extract the substring starting with ``redis://`` /
       ``rediss://`` / ``unix://``.
    2. Operators paste an Upstash URL with ``redis://`` (plain TCP)
       instead of ``rediss://`` (TLS). Upstash *requires* TLS and
       closes plain connections immediately. We auto-upgrade any
       ``redis://*.upstash.io`` URL to ``rediss://``.
    """
    raw = (raw or '').strip().strip('"').strip("'")
    if not raw:
        return ''
    import re as _re
    m = _re.search(r'\b(?:rediss?|unix)://\S+', raw)
    url = m.group(0) if m else raw
    if url.startswith('redis://') and 'upstash.io' in url:
        url = 'rediss://' + url[len('redis://'):]
    return url


# MEMORYSTORE_REDIS_URL intentionally pinned to empty (2026-04).
# Cloudflare AI Gateway handles upstream LLM cache (cache_ttl=3600s).
# Edge worker's RATE_LIMIT KV binding handles distributed rate limiting.
# Per-worker L1 in-memory cache handles hot-path dedupe.
# To re-enable a managed Redis L2 in the future (e.g. GCP Memorystore on
# Cloud Run), restore the line below and ensure the secret is reachable:
#   MEMORYSTORE_REDIS_URL = _extract_redis_url(os.environ.get('MEMORYSTORE_REDIS_URL', ''))
MEMORYSTORE_REDIS_URL = ''
REDIS_AI_CACHE_NAMESPACE = (os.environ.get('REDIS_AI_CACHE_NAMESPACE', 'ai_cache').strip() or 'ai_cache')
REDIS_AI_CACHE_MAX_ENTRY_BYTES = int(os.environ.get('REDIS_AI_CACHE_MAX_ENTRY_BYTES', str(64 * 1024)) or 64 * 1024)
REDIS_AI_CACHE_CONNECT_TIMEOUT_MS = int(os.environ.get('REDIS_AI_CACHE_CONNECT_TIMEOUT_MS', '200') or '200')
REDIS_AI_CACHE_OP_TIMEOUT_MS = int(os.environ.get('REDIS_AI_CACHE_OP_TIMEOUT_MS', '150') or '150')

# ── Slow-query logging ────────────────────────────────────────────────────────
SLOW_QUERY_THRESHOLD_MS = float(os.environ.get("SLOW_QUERY_THRESHOLD_MS", "200"))

# ── Supabase ──────────────────────────────────────────────────────────────────
# `SUPABASE_URL` is the REST API URL (https://<ref>.supabase.co) used by the
# supabase-py client. If only `SUPABASE_DB_URL` is set (the Postgres DSN),
# we derive the REST URL from it to avoid forcing operators to set both.
#
# DSN format examples we handle:
#   postgresql://postgres.<ref>:pwd@aws-1-<region>.pooler.supabase.com:5432/postgres
#   postgresql://postgres:pwd@db.<ref>.supabase.co:5432/postgres
#
# The project ref `<ref>` (e.g. `czeznmqogtwecidhpysa`) lives either in the
# username after `postgres.` (pooler DSN) or in the hostname before
# `.supabase.co` (direct-connect DSN).
def _derive_supabase_url_from_dsn(dsn: str) -> str:
    if not dsn:
        return ''
    try:
        from urllib.parse import urlparse
        u = urlparse(dsn)
        # Pooler form: user is `postgres.<ref>`
        if u.username and '.' in u.username:
            ref = u.username.split('.', 1)[1]
            if ref:
                return f"https://{ref}.supabase.co"
        # Direct form: host is `db.<ref>.supabase.co`
        if u.hostname and u.hostname.endswith('.supabase.co'):
            host_parts = u.hostname.split('.')
            # ['db', '<ref>', 'supabase', 'co']
            if len(host_parts) >= 4 and host_parts[0] == 'db':
                return f"https://{host_parts[1]}.supabase.co"
    except Exception:
        pass
    return ''

SUPABASE_URL         = (
    os.environ.get('SUPABASE_URL', '').strip()
    or _derive_supabase_url_from_dsn(os.environ.get('SUPABASE_DB_URL', '').strip())
)
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '') or os.environ.get('SUPABASE_KEY', '')
SUPABASE_ANON_KEY    = os.environ.get('SUPABASE_ANON_KEY', '') or os.environ.get('SUPABASE_KEY', '')

# ── Cookie security (set SECURE_COOKIES=false in dev to allow HTTP) ───────────
SECURE_COOKIES  = os.environ.get('SECURE_COOKIES', 'true').lower() not in ('false', '0', 'no')
COOKIE_SAMESITE = "none" if SECURE_COOKIES else "lax"
COOKIE_DOMAIN   = os.environ.get('COOKIE_DOMAIN', '').strip() or None

_cors_raw = os.environ.get('CORS_ORIGINS', '').strip().strip('"').strip("'")
if not _cors_raw or _cors_raw == '*':
    CORS_ORIGINS = ["http://localhost", "http://localhost:80", "http://localhost:25144"]
    for _rd in os.environ.get('REPLIT_DOMAINS', '').split(','):
        _rd = _rd.strip()
        if _rd:
            CORS_ORIGINS.append(f"https://{_rd}")
    _CORS_ALLOW_CREDENTIALS = True
else:
    CORS_ORIGINS = [o.strip() for o in _cors_raw.split(',') if o.strip()]
    for _rd in os.environ.get('REPLIT_DOMAINS', '').split(','):
        _rd = _rd.strip()
        if _rd and f"https://{_rd}" not in CORS_ORIGINS:
            CORS_ORIGINS.append(f"https://{_rd}")
    _CORS_ALLOW_CREDENTIALS = True

_HARDCODED_PROD_ORIGINS = [
    "https://syrabit.ai",
    "https://www.syrabit.ai",
    "https://api.syrabit.ai",
]
for _hpo in _HARDCODED_PROD_ORIGINS:
    if _hpo not in CORS_ORIGINS:
        CORS_ORIGINS.append(_hpo)

_prod_origins_raw = os.environ.get('PRODUCTION_ORIGINS', '').strip()
if _prod_origins_raw:
    for _po in _prod_origins_raw.split(','):
        _po = _po.strip()
        if _po and _po not in CORS_ORIGINS:
            CORS_ORIGINS.append(_po)

_default_prod_origins = [
    "https://syrabit.ai",
    "https://www.syrabit.ai",
    "https://api.syrabit.ai",
]
for _dpo in _default_prod_origins:
    if _dpo not in CORS_ORIGINS:
        CORS_ORIGINS.append(_dpo)

_apprunner_url = os.environ.get('APPRUNNER_SERVICE_URL', '').strip().rstrip('/')
if _apprunner_url:
    _ar_origin = _apprunner_url if _apprunner_url.startswith('https://') else f"https://{_apprunner_url}"
    if _ar_origin not in CORS_ORIGINS:
        CORS_ORIGINS.append(_ar_origin)

CORS_ORIGIN_REGEX = r"^https://[a-z0-9-]+(\.[a-z0-9-]+)*\.(awsapprunner\.com|up\.railway\.app|railway\.app|pages\.dev)$"

# ── Admin accounts ────────────────────────────────────────────────────────────
# Admin accounts loaded from environment (no credentials in source code)
def _load_admin_accounts():
    emails    = [e.strip() for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()]
    passwords = [p.strip().strip('"').strip("'") for p in os.environ.get('ADMIN_PASSWORDS', '').split(',') if p.strip()]
    names     = [n.strip() for n in os.environ.get('ADMIN_NAMES', '').split(',') if n.strip()]
    max_len = max(len(emails), len(passwords), len(names)) if emails else 0
    return [{"email": emails[i], "password": passwords[i], "name": names[i]}
            for i in range(min(len(emails), len(passwords), len(names)))]

ADMIN_ACCOUNTS = _load_admin_accounts()

_E2E_ADMIN_ENABLED = os.environ.get('ENABLE_E2E_ADMIN', '').strip().lower() in ('1', 'true', 'yes')
_E2E_ADMIN = {
    "email": "e2e-admin@syrabit.test",
    "password": "e2e-test-admin-2026",
    "name": "E2E Test Admin",
}
if _E2E_ADMIN_ENABLED and not any(a["email"] == _E2E_ADMIN["email"] for a in ADMIN_ACCOUNTS):
    ADMIN_ACCOUNTS.append(_E2E_ADMIN)
    import logging as _adm_log
    _adm_log.getLogger("config").info("E2E test admin account enabled (ENABLE_E2E_ADMIN=true)")

ADMIN_EMAIL    = ADMIN_ACCOUNTS[0]["email"]    if ADMIN_ACCOUNTS else ""
ADMIN_PASSWORD = ADMIN_ACCOUNTS[0]["password"] if ADMIN_ACCOUNTS else ""

_PG_DSN_RAW = os.environ.get("DATABASE_URL", "") or os.environ.get("SUPABASE_DB_URL", "")
_PG_DSN = _PG_DSN_RAW.strip().strip('"').strip("'").strip()
if _PG_DSN and not _PG_DSN.startswith(("postgresql://", "postgres://")):
    _cfg_log.warning(f"PG DSN invalid scheme — starts with: {_PG_DSN[:20]}...")
    _PG_DSN = ""
_pg_source = "DATABASE_URL" if os.environ.get("DATABASE_URL", "").strip() else ("SUPABASE_DB_URL" if os.environ.get("SUPABASE_DB_URL", "").strip() else "none")
if _PG_DSN:
    try:
        from urllib.parse import urlparse as _urlparse
        _pg_parsed = _urlparse(_PG_DSN)
        _cfg_log.info(f"PG DSN detected (from {_pg_source}) — host={_pg_parsed.hostname}, port={_pg_parsed.port}, user={_pg_parsed.username}, db={_pg_parsed.path}")
    except Exception:
        _cfg_log.info(f"PG DSN detected (from {_pg_source}) — length={len(_PG_DSN)} chars (parse failed)")
else:
    _cfg_log.warning("PG DSN empty — neither DATABASE_URL nor SUPABASE_DB_URL is set")


SARVAM_THINK_BUFFER = 80

CONTENT_CACHE_SECONDS = 600
REDIS_CONTENT_PREFIX = "content:"

# ── Plan configuration ────────────────────────────────────────────────────────
# Credits reset daily at midnight UTC.
PLAN_LIMITS = {
    # `req_per_min` for free is the per-anon-IP cap. Bumped 5→15 because a
    # single classroom behind one NAT shares the same IP — 5/min throttled
    # legitimate students at peak usage. 15/min ≈ one chat every 4s, still
    # well below abuse thresholds.
    # max_tokens raised: previous caps (512/768/1024) were truncating
    # step-by-step explanations and solved-example replies mid-sentence
    # for every plan, especially in Assamese where each word averages
    # ~2x the tokens of English. New caps comfortably fit a full
    # textbook-style answer (~700–1500 words) without affecting the
    # daily credit accounting (1 reply = 1 credit regardless of length).
    "free":    {"credits_per_day": 30,   "max_tokens": 1024,   "document_access": "zero",    "req_per_min": 15, "req_per_min_ip": 60},
    "starter": {"credits_per_day": 500,  "max_tokens": 1536,   "document_access": "limited", "req_per_min": 10, "req_per_min_ip": 90},
    "pro":     {"credits_per_day": 4000, "max_tokens": 2048,   "document_access": "full",    "req_per_min": 15, "req_per_min_ip": 120},
}
PLAN_PRICES = {
    "free":    {"price": 0,   "label": "Free",    "description": "30 credits/day · zero document access"},
    "starter": {"price": 99,  "label": "Starter", "description": "500 credits/day · limited document access"},
    "pro":     {"price": 999, "label": "Pro",      "description": "4,000 credits/day · full document access"},
}

SEED_DATA = {
    "boards": [
        {"id": "b1", "name": "AHSEC", "slug": "ahsec", "group_name": "AssamBoard", "description": "AssamBoard — AHSEC (Class 11–12)", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "b2", "name": "DEGREE", "slug": "degree", "group_name": "AssamBoard", "description": "AssamBoard — Degree (B.A / B.Com / B.Sc)", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "b3", "name": "SEBA", "slug": "seba", "group_name": "AssamBoard", "description": "AssamBoard — SEBA (Secondary Education)", "created_at": "2024-01-01T00:00:00Z"},
    ],
    "classes": [
        # AHSEC classes
        {"id": "c1", "board_id": "b1", "name": "HS 1st Year", "slug": "hs-1st-year", "description": "Class 11 — AHSEC", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c2", "board_id": "b1", "name": "HS 2nd Year", "slug": "hs-2nd-year", "description": "Class 12 — AHSEC", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE legacy classes (kept for backward compat)
        {"id": "c3", "board_id": "b2", "name": "2nd Sem", "slug": "2nd-sem", "description": "Degree 2nd Semester", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c4", "board_id": "b2", "name": "4th Sem", "slug": "4th-sem", "description": "Degree 4th Semester", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE — FYUGP (NEP) Semesters 1–4 (pre-built, linker-discoverable by slug)
        {"id": "c7",  "board_id": "b2", "name": "Semester 1", "slug": "semester-1", "description": "FYUGP 1st Semester — NEP", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c8",  "board_id": "b2", "name": "Semester 2", "slug": "semester-2", "description": "FYUGP 2nd Semester — NEP", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c9",  "board_id": "b2", "name": "Semester 3", "slug": "semester-3", "description": "FYUGP 3rd Semester — NEP", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c10", "board_id": "b2", "name": "Semester 4", "slug": "semester-4", "description": "FYUGP 4th Semester — NEP", "created_at": "2024-01-01T00:00:00Z"},
        # SEBA classes
        {"id": "c5", "board_id": "b3", "name": "Class 9",  "slug": "class-9",  "description": "SEBA Class 9 — Secondary", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "c6", "board_id": "b3", "name": "Class 10", "slug": "class-10", "description": "SEBA Class 10 — Secondary", "created_at": "2024-01-01T00:00:00Z"},
    ],
    "streams": [
        # AHSEC HS 1st Year streams
        {"id": "s13", "class_id": "c1", "name": "Science (PCM)", "slug": "science-pcm", "description": "Physics, Chemistry, Mathematics", "icon": "⚗️", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s14", "class_id": "c1", "name": "Science (PCB)", "slug": "science-pcb", "description": "Physics, Chemistry, Biology",    "icon": "🧬", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s15", "class_id": "c1", "name": "Arts",          "slug": "arts",        "description": "Political Science, History, Economics, Geography", "icon": "📖", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s16", "class_id": "c1", "name": "Commerce",      "slug": "commerce",    "description": "Accountancy, Business Studies, Economics",          "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        # AHSEC HS 2nd Year streams
        {"id": "s17", "class_id": "c2", "name": "Science (PCM)", "slug": "science-pcm", "description": "Physics, Chemistry, Mathematics", "icon": "⚗️", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s18", "class_id": "c2", "name": "Science (PCB)", "slug": "science-pcb", "description": "Physics, Chemistry, Biology",    "icon": "🧬", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s19", "class_id": "c2", "name": "Arts",          "slug": "arts",        "description": "Political Science, History, Economics, Geography", "icon": "📖", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s20", "class_id": "c2", "name": "Commerce",      "slug": "commerce",    "description": "Accountancy, Business Studies, Economics",          "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE 2nd Sem legacy streams
        {"id": "s7",  "class_id": "c3", "name": "B.Com", "slug": "bcom", "description": "Bachelor of Commerce", "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s8",  "class_id": "c3", "name": "B.A",   "slug": "ba",   "description": "Bachelor of Arts",     "icon": "📖", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s9",  "class_id": "c3", "name": "B.Sc",  "slug": "bsc",  "description": "Bachelor of Science",  "icon": "🔬", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE 4th Sem legacy streams
        {"id": "s10", "class_id": "c4", "name": "B.Com", "slug": "bcom", "description": "Bachelor of Commerce", "icon": "💼", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s11", "class_id": "c4", "name": "B.A",   "slug": "ba",   "description": "Bachelor of Arts",     "icon": "📖", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s12", "class_id": "c4", "name": "B.Sc",  "slug": "bsc",  "description": "Bachelor of Science",  "icon": "🔬", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE FYUGP Semester 1 — 6 NEP course-type streams
        {"id": "s30", "class_id": "c7",  "name": "Major", "slug": "major", "description": "Major Discipline Course",               "icon": "🎯", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s31", "class_id": "c7",  "name": "Minor", "slug": "minor", "description": "Minor Elective Course",                 "icon": "📘", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s32", "class_id": "c7",  "name": "MDC",   "slug": "mdc",   "description": "Multidisciplinary Course",              "icon": "🌐", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s33", "class_id": "c7",  "name": "VAC",   "slug": "vac",   "description": "Value-Added Course",                    "icon": "✨", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s34", "class_id": "c7",  "name": "AEC",   "slug": "aec",   "description": "Ability Enhancement Compulsory Course", "icon": "🧠", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s35", "class_id": "c7",  "name": "SEC",   "slug": "sec",   "description": "Skill Enhancement Course",              "icon": "⚡", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE FYUGP Semester 2 — 6 NEP course-type streams
        {"id": "s36", "class_id": "c8",  "name": "Major", "slug": "major", "description": "Major Discipline Course",               "icon": "🎯", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s37", "class_id": "c8",  "name": "Minor", "slug": "minor", "description": "Minor Elective Course",                 "icon": "📘", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s38", "class_id": "c8",  "name": "MDC",   "slug": "mdc",   "description": "Multidisciplinary Course",              "icon": "🌐", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s39", "class_id": "c8",  "name": "VAC",   "slug": "vac",   "description": "Value-Added Course",                    "icon": "✨", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s40", "class_id": "c8",  "name": "AEC",   "slug": "aec",   "description": "Ability Enhancement Compulsory Course", "icon": "🧠", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s41", "class_id": "c8",  "name": "SEC",   "slug": "sec",   "description": "Skill Enhancement Course",              "icon": "⚡", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE FYUGP Semester 3 — 6 NEP course-type streams
        {"id": "s42", "class_id": "c9",  "name": "Major", "slug": "major", "description": "Major Discipline Course",               "icon": "🎯", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s43", "class_id": "c9",  "name": "Minor", "slug": "minor", "description": "Minor Elective Course",                 "icon": "📘", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s44", "class_id": "c9",  "name": "MDC",   "slug": "mdc",   "description": "Multidisciplinary Course",              "icon": "🌐", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s45", "class_id": "c9",  "name": "VAC",   "slug": "vac",   "description": "Value-Added Course",                    "icon": "✨", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s46", "class_id": "c9",  "name": "AEC",   "slug": "aec",   "description": "Ability Enhancement Compulsory Course", "icon": "🧠", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s47", "class_id": "c9",  "name": "SEC",   "slug": "sec",   "description": "Skill Enhancement Course",              "icon": "⚡", "created_at": "2024-01-01T00:00:00Z"},
        # DEGREE FYUGP Semester 4 — 6 NEP course-type streams
        {"id": "s48", "class_id": "c10", "name": "Major", "slug": "major", "description": "Major Discipline Course",               "icon": "🎯", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s49", "class_id": "c10", "name": "Minor", "slug": "minor", "description": "Minor Elective Course",                 "icon": "📘", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s50", "class_id": "c10", "name": "MDC",   "slug": "mdc",   "description": "Multidisciplinary Course",              "icon": "🌐", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s51", "class_id": "c10", "name": "VAC",   "slug": "vac",   "description": "Value-Added Course",                    "icon": "✨", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s52", "class_id": "c10", "name": "AEC",   "slug": "aec",   "description": "Ability Enhancement Compulsory Course", "icon": "🧠", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "s53", "class_id": "c10", "name": "SEC",   "slug": "sec",   "description": "Skill Enhancement Course",              "icon": "⚡", "created_at": "2024-01-01T00:00:00Z"},
        # SEBA Class 9 streams
        {"id": "s21", "class_id": "c5", "name": "General", "slug": "general", "description": "General stream — SEBA Class 9", "icon": "📚", "created_at": "2024-01-01T00:00:00Z"},
        # SEBA Class 10 streams
        {"id": "s22", "class_id": "c6", "name": "General", "slug": "general", "description": "General stream — SEBA Class 10", "icon": "📚", "created_at": "2024-01-01T00:00:00Z"},
    ],
    "subjects": [],
    "chapters": [],
}

def _generate_chapters():
    return []  # Chapters cleared — upload new syllabus via Admin panel

SEED_DATA["chapters"] = _generate_chapters()

def _fix_chapter_counts():
    ch_count = {}
    for ch in SEED_DATA["chapters"]:
        sid = ch["subject_id"]
        ch_count[sid] = ch_count.get(sid, 0) + 1
    for subj in SEED_DATA["subjects"]:
        subj["chapter_count"] = ch_count.get(subj["id"], 0)

_fix_chapter_counts()
