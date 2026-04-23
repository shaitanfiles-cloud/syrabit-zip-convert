"""Cloudflare Access (Zero Trust) JWT verification — Task #637.

Cloudflare Access fronts every protected origin with an authenticated proxy.
On a successful login at the team domain, Access mints a short-lived
RS256 JWT per Access Application and forwards it to the origin in the
``Cf-Access-Jwt-Assertion`` header (also set as a ``CF_Authorization``
cookie). This module verifies that token so the origin can refuse any
request that did not transit Access — defense-in-depth against someone
who learns the run.app / *.railway.app URL and tries to bypass the edge.

Verification rules (per CF docs):
  * Algorithm: RS256
  * Issuer:    ``https://<team>.cloudflareaccess.com``
  * Audience:  the per-application AUD tag (sha256 hex). One AUD per app;
               we accept any AUD configured in env (admin, internal, …).
  * Signature: RSA public keys served from
               ``https://<team>.cloudflareaccess.com/cdn-cgi/access/certs``
               (rotated every ~6 weeks; we cache & refetch on KID miss).

Failure mode policy:
  * Disabled (no team domain set, or ``CF_ACCESS_ENFORCE`` is false): the
    dependency is a no-op so dev / Railway parity stays intact.
  * Enabled but token missing / invalid / wrong AUD: HTTP 401.

The module exposes:
  * ``verify_cf_access_token(token: str, audiences: list[str]) -> dict``
    pure verifier — returns claims, raises ``CfAccessError`` on failure.
  * ``require_cf_access_admin`` / ``require_cf_access_internal`` —
    FastAPI dependencies layered into ``get_admin_user`` and the
    ``/api/_internal/*`` routers.
"""
from __future__ import annotations

import asyncio
import os
import time
import logging
from typing import Optional, Iterable

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# ── Configuration (env-driven, no defaults that would silently disable) ──────
def _normalize_team_domain(raw: str) -> str:
    """Accept any of these forms and reduce to the team slug:

      ``syrabit``                                 → ``syrabit``
      ``syrabit.cloudflareaccess.com``            → ``syrabit``
      ``https://syrabit.cloudflareaccess.com``    → ``syrabit``
      ``https://syrabit.cloudflareaccess.com/``   → ``syrabit``

    Returning the slug (and never the full hostname) means the issuer URL
    and JWKS URL are always built consistently regardless of how an
    operator pasted the value into the env file or dashboard.
    """
    s = (raw or "").strip().rstrip("/")
    if not s:
        return ""
    # Strip scheme if pasted as full URL
    if "://" in s:
        s = s.split("://", 1)[1]
    # Strip path component if any
    s = s.split("/", 1)[0]
    # Cloudflare-issued team domains are always lowercase in the JWT
    # `iss` claim, so normalize to avoid case-mismatch on issuer compare.
    s = s.lower()
    # Strip the well-known suffix to leave only the team slug
    suffix = ".cloudflareaccess.com"
    if s.endswith(suffix):
        s = s[: -len(suffix)]
    return s


CF_ACCESS_TEAM_DOMAIN = _normalize_team_domain(os.environ.get("CF_ACCESS_TEAM_DOMAIN", ""))
CF_ACCESS_AUD_ADMIN = os.environ.get("CF_ACCESS_AUD_ADMIN", "").strip()
CF_ACCESS_AUD_INTERNAL = os.environ.get("CF_ACCESS_AUD_INTERNAL", "").strip()


def _enforce_enabled() -> bool:
    """``CF_ACCESS_ENFORCE`` must be explicitly set to ``true``/``1``.

    Default OFF so existing deployments keep working when this code merges
    before operators provision Access. Once the IdP + Access apps are live
    in production, flip the env var to enforce."""
    val = os.environ.get("CF_ACCESS_ENFORCE", "").strip().lower()
    return val in ("1", "true", "yes", "on")


# ── Break-glass (Task #706) ──────────────────────────────────────────────────
# When Cloudflare Access itself is degraded (Zero Trust outage, AUD tag
# misrotation, IdP failure) the entire admin surface goes 401. Without a
# tested escape hatch the only recovery is "set CF_ACCESS_ENFORCE=false on
# Railway and restart" — which can take minutes during an active incident.
#
# Two break-glass surfaces are supported, both read **at request time** so
# they can flip without a service restart:
#
#  1. ``CF_ACCESS_BREAK_GLASS`` env (truthy values: 1/true/yes/on). Set on
#     the Railway service when an operator already has Railway access.
#  2. ``X-Cf-Access-Break-Glass: <token>`` request header, validated against
#     the ``CF_ACCESS_BREAK_GLASS_TOKEN`` env. The Cloudflare Worker in
#     front of the origin can inject this header from a Worker secret —
#     this is the "non-Railway" path: the on-call edits the Worker secret
#     in the Cloudflare dashboard, traffic resumes within seconds, no
#     FastAPI restart needed.
#
# Activation is **always loud** (CRITICAL log + diagnostics flag) so the
# state cannot silently linger past the incident.
_BREAK_GLASS_HEADER = "x-cf-access-break-glass"


def _break_glass_env_active() -> bool:
    val = os.environ.get("CF_ACCESS_BREAK_GLASS", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _break_glass_token_env() -> str:
    return os.environ.get("CF_ACCESS_BREAK_GLASS_TOKEN", "").strip()


def break_glass_state(request: Optional[Request] = None) -> dict:
    """Return the current break-glass state.

    Always includes ``env_active``; when a ``request`` is supplied the
    header path is also evaluated. ``active`` is the OR of both sources
    and ``source`` records which one tripped (env wins on tie).
    """
    env_on = _break_glass_env_active()
    header_on = False
    header_present = False
    if request is not None:
        raw = request.headers.get(_BREAK_GLASS_HEADER) or request.headers.get(
            _BREAK_GLASS_HEADER.title()
        )
        if raw:
            header_present = True
            expected = _break_glass_token_env()
            # Constant-time compare so a timing oracle doesn't leak the
            # token byte-by-byte if the Worker leaks the header upstream.
            import hmac as _hmac
            header_on = bool(expected) and _hmac.compare_digest(raw.strip(), expected)
    active = env_on or header_on
    source: Optional[str] = None
    if env_on:
        source = "env"
    elif header_on:
        source = "header"
    return {
        "active": active,
        "source": source,
        "env_active": env_on,
        "header_present": header_present,
        "header_accepted": header_on,
        "header_token_configured": bool(_break_glass_token_env()),
    }


def _log_break_glass(label: str, state: dict, request: Optional[Request]) -> None:
    """Emit a CRITICAL log every time a request bypasses Access.

    Logged per-request (no rate limiting) on purpose: while break-glass is
    active every admin action must be auditable in the log stream. A noisy
    log is also a strong reminder to the operator to disable the bypass
    once the underlying outage is resolved.
    """
    ip = ""
    ua = ""
    if request is not None:
        ip = (request.headers.get("cf-connecting-ip")
              or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
              or (request.client.host if request.client else ""))
        ua = request.headers.get("user-agent", "")[:120]
    logger.critical(
        "CF Access BREAK-GLASS bypass active (%s) source=%s ip=%s ua=%r path=%s",
        label,
        state.get("source"),
        ip or "?",
        ua,
        getattr(getattr(request, "url", None), "path", "?") if request else "?",
    )


def is_admin_enforcement_enabled() -> bool:
    """True when admin enforcement is configured AND complete.

    Used purely to decide *whether the verifier runs*. The fail-closed
    branch for "enforce on but config incomplete" is handled separately
    in ``require_cf_access_admin`` so it returns 503 instead of silently
    no-opping."""
    return bool(_enforce_enabled() and CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD_ADMIN)


def is_internal_enforcement_enabled() -> bool:
    return bool(_enforce_enabled() and CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD_INTERNAL)


# Fire one CRITICAL log line at module import time when enforcement is
# turned on but required config is missing — operators see this in startup
# logs even before the first protected request arrives.
if _enforce_enabled() and not (CF_ACCESS_TEAM_DOMAIN and (CF_ACCESS_AUD_ADMIN or CF_ACCESS_AUD_INTERNAL)):
    logger.critical(
        "CF_ACCESS_ENFORCE=true but required config is missing — "
        "team_domain=%r admin_aud=%r internal_aud=%r. "
        "Protected endpoints will fail-closed (503) until env is fixed.",
        CF_ACCESS_TEAM_DOMAIN,
        bool(CF_ACCESS_AUD_ADMIN),
        bool(CF_ACCESS_AUD_INTERNAL),
    )


def _certs_url() -> str:
    return f"https://{CF_ACCESS_TEAM_DOMAIN}.cloudflareaccess.com/cdn-cgi/access/certs"


def _expected_issuer() -> str:
    return f"https://{CF_ACCESS_TEAM_DOMAIN}.cloudflareaccess.com"


# ── JWKS cache ────────────────────────────────────────────────────────────────
# CF rotates Access signing keys (~6 weeks). We cache for 1h and refetch on
# KID miss. ``_jwks_state`` is a module-level dict so unit tests can monkey-
# patch the cache without re-importing the module.
_JWKS_TTL_SEC = 3600
_jwks_state: dict = {
    "keys_by_kid": {},   # kid -> RSA public key object
    "fetched_at": 0.0,
    "raw": None,         # last raw JSON (debug only)
}
# Single-flight lock so a request flood (or a KID rotation that arrives
# during a traffic burst) does not stampede Cloudflare's certs endpoint.
# The lock is created lazily on first use because module import can run
# outside an event loop (gunicorn worker bootstrap).
_jwks_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _jwks_lock
    if _jwks_lock is None:
        _jwks_lock = asyncio.Lock()
    return _jwks_lock


class CfAccessError(Exception):
    """Raised when a request fails CF Access verification."""


async def _fetch_jwks(client: Optional[httpx.AsyncClient] = None) -> dict:
    """Download and parse the JWKS document; cache parsed RSA keys by KID."""
    url = _certs_url()
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=10)
    try:
        r = await client.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    finally:
        if own_client:
            await client.aclose()
    keys_by_kid: dict = {}
    for jwk in data.get("keys", []) or []:
        kid = jwk.get("kid")
        if not kid:
            continue
        try:
            keys_by_kid[kid] = RSAAlgorithm.from_jwk(jwk)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"CF Access JWKS: skipping bad key kid={kid!r}: {exc}")
    if not keys_by_kid:
        raise CfAccessError("CF Access JWKS returned no usable RSA keys")
    _jwks_state["keys_by_kid"] = keys_by_kid
    _jwks_state["fetched_at"] = time.time()
    _jwks_state["raw"] = data
    return keys_by_kid


async def _get_signing_key(kid: str, client: Optional[httpx.AsyncClient] = None):
    """Return the RSA public key for ``kid``.

    Single-flight: at most one task fetches JWKS at a time. After
    acquiring the lock we re-check the cache so the second waiter doesn't
    refetch what the first waiter just populated. Refetch happens when
    the cache is empty, expired, OR the requested ``kid`` is unknown
    (rotation mid-window).
    """
    lock = _get_lock()
    async with lock:
        cache = _jwks_state["keys_by_kid"]
        age = time.time() - _jwks_state["fetched_at"]
        needs_fetch = (
            not cache
            or age > _JWKS_TTL_SEC
            or kid not in cache
        )
        if needs_fetch:
            cache = await _fetch_jwks(client)
        key = cache.get(kid)
    if key is None:
        raise CfAccessError(f"CF Access JWKS has no key for kid={kid!r}")
    return key


async def verify_cf_access_token(
    token: str,
    audiences: Iterable[str],
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Verify a CF Access JWT and return its claims.

    Raises ``CfAccessError`` on any verification failure.
    ``audiences`` is the list of acceptable AUD tags (any-of match).
    """
    if not token:
        raise CfAccessError("Missing CF Access token")
    auds = [a for a in audiences if a]
    if not auds:
        raise CfAccessError("No CF Access audience configured")
    if not CF_ACCESS_TEAM_DOMAIN:
        raise CfAccessError("CF_ACCESS_TEAM_DOMAIN not configured")
    try:
        unverified = jwt.get_unverified_header(token)
    except Exception as exc:  # noqa: BLE001
        raise CfAccessError(f"Malformed CF Access JWT header: {exc}") from exc
    kid = unverified.get("kid")
    if not kid:
        raise CfAccessError("CF Access JWT missing kid")
    key = await _get_signing_key(kid, client=client)
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=auds,
            issuer=_expected_issuer(),
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise CfAccessError("CF Access JWT expired") from exc
    except jwt.InvalidAudienceError as exc:
        raise CfAccessError("CF Access JWT audience mismatch") from exc
    except jwt.InvalidIssuerError as exc:
        raise CfAccessError("CF Access JWT issuer mismatch") from exc
    except jwt.InvalidTokenError as exc:
        raise CfAccessError(f"CF Access JWT invalid: {exc}") from exc
    return claims


def _extract_token(request: Request) -> Optional[str]:
    """Pull the Access JWT from the header CF injects, falling back to the
    cookie for browser-initiated requests."""
    h = request.headers.get("cf-access-jwt-assertion") or request.headers.get(
        "Cf-Access-Jwt-Assertion"
    )
    if h:
        return h.strip()
    cookie = request.cookies.get("CF_Authorization")
    if cookie:
        return cookie.strip()
    return None


async def _require(request: Request, audiences: list[str], label: str) -> dict:
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail=f"Cloudflare Access required ({label}): missing assertion header",
        )
    try:
        return await verify_cf_access_token(token, audiences)
    except CfAccessError as exc:
        # Log INFO: production traffic that bypasses Access is the alarm,
        # not the verifier path. WARN here would spam during JWKS rotation
        # tests.
        logger.info(f"CF Access verify failed ({label}): {exc}")
        raise HTTPException(
            status_code=401,
            detail=f"Cloudflare Access denied ({label})",
        ) from exc


def _fail_closed_if_misconfigured(audience: str, label: str):
    """When the operator has set ``CF_ACCESS_ENFORCE=true`` but the
    accompanying config is incomplete, refuse the request with 503.

    Without this check the dependency would silently no-op (because
    ``is_*_enforcement_enabled()`` requires both the team domain and the
    AUD), turning a misconfiguration into a security bypass: callers
    would still satisfy the admin JWT and reach protected routes with
    no Access challenge in front of them. Failing closed surfaces the
    misconfiguration loudly instead.
    """
    if not _enforce_enabled():
        return
    missing = []
    if not CF_ACCESS_TEAM_DOMAIN:
        missing.append("CF_ACCESS_TEAM_DOMAIN")
    if not audience:
        missing.append(
            "CF_ACCESS_AUD_ADMIN" if label == "admin" else "CF_ACCESS_AUD_INTERNAL"
        )
    if missing:
        logger.critical(
            f"CF Access {label} request refused — enforcement on but "
            f"missing config: {', '.join(missing)}"
        )
        raise HTTPException(
            status_code=503,
            detail=f"Cloudflare Access misconfigured ({label}); refusing to fail-open",
        )


async def require_cf_access_admin(request: Request) -> Optional[dict]:
    """FastAPI dependency for admin-tier Access app.

    No-op when enforcement is disabled (dev / pre-rollout). Production
    sets ``CF_ACCESS_ENFORCE=true`` along with ``CF_ACCESS_TEAM_DOMAIN``
    and ``CF_ACCESS_AUD_ADMIN``. If enforcement is on but config is
    incomplete, the request is refused with 503 (fail-closed).

    Break-glass (Task #706): when ``CF_ACCESS_BREAK_GLASS=true`` or a
    valid ``X-Cf-Access-Break-Glass`` header is present, the Access
    challenge is skipped (CRITICAL log, surfaced via /admin/diagnostics).
    The downstream admin JWT check in ``get_admin_user`` still runs.
    """
    bg = break_glass_state(request)
    if bg["active"]:
        _log_break_glass("admin", bg, request)
        return {"break_glass": True, "source": bg["source"]}
    _fail_closed_if_misconfigured(CF_ACCESS_AUD_ADMIN, "admin")
    if not is_admin_enforcement_enabled():
        return None
    return await _require(request, [CF_ACCESS_AUD_ADMIN], "admin")


async def require_cf_access_internal(request: Request) -> Optional[dict]:
    """FastAPI dependency for internal-tier Access app (operations,
    feature-flags, kill switches, anything ops-only)."""
    bg = break_glass_state(request)
    if bg["active"]:
        _log_break_glass("internal", bg, request)
        return {"break_glass": True, "source": bg["source"]}
    _fail_closed_if_misconfigured(CF_ACCESS_AUD_INTERNAL, "internal")
    if not is_internal_enforcement_enabled():
        return None
    return await _require(request, [CF_ACCESS_AUD_INTERNAL], "internal")


def status(request: Optional[Request] = None) -> dict:
    """Public introspection used by /admin/diagnostics. No secrets.

    Pass ``request`` to also evaluate the per-request break-glass header
    path; without a request only the env-level break-glass flag is
    reflected.
    """
    bg = break_glass_state(request)
    admin_enforced = is_admin_enforcement_enabled() and not bg["active"]
    internal_enforced = is_internal_enforcement_enabled() and not bg["active"]
    return {
        "team_domain": CF_ACCESS_TEAM_DOMAIN or None,
        "enforce": _enforce_enabled(),
        "admin_enforced": admin_enforced,
        "internal_enforced": internal_enforced,
        "admin_aud_configured": bool(CF_ACCESS_AUD_ADMIN),
        "internal_aud_configured": bool(CF_ACCESS_AUD_INTERNAL),
        "jwks_cached_keys": len(_jwks_state["keys_by_kid"]),
        "jwks_fetched_at": _jwks_state["fetched_at"] or None,
        # Task #706 — break-glass surface. ``break_glass_active`` is the
        # field the paging rule alerts on; ``break_glass_source`` records
        # which surface tripped (env vs. header) for incident timelines.
        "break_glass_active": bg["active"],
        "break_glass_source": bg["source"],
        "break_glass_env_active": bg["env_active"],
        "break_glass_header_token_configured": bg["header_token_configured"],
    }
