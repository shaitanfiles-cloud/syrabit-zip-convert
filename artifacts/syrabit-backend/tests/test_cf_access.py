"""Task #637 — Cloudflare Access (Zero Trust) JWT verification tests.

Covers:
  * Pure verifier rejects missing/expired/wrong-issuer/wrong-aud tokens
  * Pure verifier accepts a valid RS256 token signed by a fake JWKS
  * FastAPI dependency `require_cf_access_admin` is a no-op when
    enforcement is off (default), and 401s when on without the header
  * Cookie fallback path (browser-initiated requests)
"""
import asyncio
import base64
import importlib
import sys
import time
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


def run(coro):
    """Drive an async function from a synchronous pytest body."""
    return asyncio.run(coro)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _gen_rsa_keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key()
    pub_pem = pub.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return priv_pem, pub_pem, pub


def _jwk_from_public(pub, kid: str) -> dict:
    nums = pub.public_numbers()

    def _b64u(n: int) -> str:
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    return {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": kid,
            "n": _b64u(nums.n), "e": _b64u(nums.e)}


def _make_token(priv_pem, kid: str, *, iss: str, aud: str,
                exp_in: int = 60, extra: dict | None = None) -> str:
    now = int(time.time())
    claims = {"iss": iss, "aud": aud, "iat": now, "exp": now + exp_in,
              "sub": "user@syrabit.ai", "email": "user@syrabit.ai"}
    if extra:
        claims.update(extra)
    return pyjwt.encode(claims, priv_pem, algorithm="RS256",
                        headers={"kid": kid})


@pytest.fixture
def fake_access(monkeypatch):
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "syrabit-test")
    monkeypatch.setenv("CF_ACCESS_AUD_ADMIN", "aud-admin-tag")
    monkeypatch.setenv("CF_ACCESS_AUD_INTERNAL", "aud-internal-tag")
    monkeypatch.setenv("CF_ACCESS_ENFORCE", "true")

    import cf_access
    importlib.reload(cf_access)

    priv_pem, _pub_pem, pub = _gen_rsa_keypair()
    kid = "test-kid-1"
    jwk_key = RSAAlgorithm.from_jwk(_jwk_from_public(pub, kid))

    cf_access._jwks_state["keys_by_kid"] = {kid: jwk_key}
    cf_access._jwks_state["fetched_at"] = time.time()

    async def _no_fetch(client=None):
        return cf_access._jwks_state["keys_by_kid"]

    monkeypatch.setattr(cf_access, "_fetch_jwks", _no_fetch)

    return type("FA", (), {
        "module": cf_access,
        "priv_pem": priv_pem,
        "kid": kid,
        "iss": "https://syrabit-test.cloudflareaccess.com",
        "aud_admin": "aud-admin-tag",
        "aud_internal": "aud-internal-tag",
    })


# ── Pure verifier tests ──────────────────────────────────────────────────────

def test_verify_missing_token(fake_access):
    with pytest.raises(fake_access.module.CfAccessError):
        run(fake_access.module.verify_cf_access_token("", [fake_access.aud_admin]))


def test_verify_valid_token(fake_access):
    tok = _make_token(fake_access.priv_pem, fake_access.kid,
                      iss=fake_access.iss, aud=fake_access.aud_admin)
    claims = run(fake_access.module.verify_cf_access_token(
        tok, [fake_access.aud_admin]
    ))
    assert claims["aud"] == fake_access.aud_admin
    assert claims["email"] == "user@syrabit.ai"


def test_verify_wrong_aud(fake_access):
    tok = _make_token(fake_access.priv_pem, fake_access.kid,
                      iss=fake_access.iss, aud="wrong-aud")
    with pytest.raises(fake_access.module.CfAccessError):
        run(fake_access.module.verify_cf_access_token(
            tok, [fake_access.aud_admin]
        ))


def test_verify_wrong_issuer(fake_access):
    tok = _make_token(fake_access.priv_pem, fake_access.kid,
                      iss="https://attacker.example.com",
                      aud=fake_access.aud_admin)
    with pytest.raises(fake_access.module.CfAccessError):
        run(fake_access.module.verify_cf_access_token(
            tok, [fake_access.aud_admin]
        ))


def test_verify_expired(fake_access):
    tok = _make_token(fake_access.priv_pem, fake_access.kid,
                      iss=fake_access.iss, aud=fake_access.aud_admin,
                      exp_in=-10)
    with pytest.raises(fake_access.module.CfAccessError):
        run(fake_access.module.verify_cf_access_token(
            tok, [fake_access.aud_admin]
        ))


def test_verify_unknown_kid(fake_access):
    bad_priv, _, _ = _gen_rsa_keypair()
    tok = _make_token(bad_priv, "unknown-kid",
                      iss=fake_access.iss, aud=fake_access.aud_admin)
    with pytest.raises(fake_access.module.CfAccessError):
        run(fake_access.module.verify_cf_access_token(
            tok, [fake_access.aud_admin]
        ))


# ── FastAPI dependency tests ─────────────────────────────────────────────────

def test_dependency_noop_when_disabled(monkeypatch):
    """Default config (no env) → dependency returns None so the admin
    chain behaves exactly as before this task merged."""
    for var in ("CF_ACCESS_TEAM_DOMAIN", "CF_ACCESS_AUD_ADMIN",
                "CF_ACCESS_AUD_INTERNAL", "CF_ACCESS_ENFORCE"):
        monkeypatch.delenv(var, raising=False)
    import cf_access
    importlib.reload(cf_access)
    assert cf_access.is_admin_enforcement_enabled() is False
    assert cf_access.is_internal_enforcement_enabled() is False


def _request_with_headers(headers: list[tuple[bytes, bytes]]):
    from fastapi import Request
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/admin/test",
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope)


def test_dependency_blocks_missing_header(fake_access):
    from fastapi import HTTPException
    req = _request_with_headers([])
    with pytest.raises(HTTPException) as ei:
        run(fake_access.module.require_cf_access_admin(req))
    assert ei.value.status_code == 401


def test_dependency_accepts_valid_header(fake_access):
    tok = _make_token(fake_access.priv_pem, fake_access.kid,
                      iss=fake_access.iss, aud=fake_access.aud_admin)
    req = _request_with_headers([(b"cf-access-jwt-assertion", tok.encode())])
    claims = run(fake_access.module.require_cf_access_admin(req))
    assert claims is not None
    assert claims["email"] == "user@syrabit.ai"


def test_dependency_accepts_cookie_fallback(fake_access):
    tok = _make_token(fake_access.priv_pem, fake_access.kid,
                      iss=fake_access.iss, aud=fake_access.aud_admin)
    req = _request_with_headers([(b"cookie", f"CF_Authorization={tok}".encode())])
    claims = run(fake_access.module.require_cf_access_admin(req))
    assert claims["sub"] == "user@syrabit.ai"


def test_internal_dependency_uses_internal_aud(fake_access):
    """A token minted for the admin AUD must NOT pass the internal gate."""
    from fastapi import HTTPException
    tok = _make_token(fake_access.priv_pem, fake_access.kid,
                      iss=fake_access.iss, aud=fake_access.aud_admin)
    req = _request_with_headers([(b"cf-access-jwt-assertion", tok.encode())])
    with pytest.raises(HTTPException) as ei:
        run(fake_access.module.require_cf_access_internal(req))
    assert ei.value.status_code == 401


def test_fail_closed_when_enforce_on_but_config_missing(monkeypatch):
    """ENFORCE=true with no team domain / AUD must refuse with 503,
    not silently fall through to admin-JWT-only acceptance."""
    monkeypatch.setenv("CF_ACCESS_ENFORCE", "true")
    monkeypatch.setenv("CF_ACCESS_TEAM_DOMAIN", "")
    monkeypatch.setenv("CF_ACCESS_AUD_ADMIN", "")
    monkeypatch.setenv("CF_ACCESS_AUD_INTERNAL", "")
    sys.modules.pop("cf_access", None)
    import cf_access as misconf

    # Even with no token at all, the verifier must refuse rather than no-op.
    req = SimpleNamespace(headers={}, cookies={})
    with pytest.raises(HTTPException) as ei:
        run(misconf.require_cf_access_admin(req))
    assert ei.value.status_code == 503
    assert "misconfigured" in ei.value.detail.lower()

    with pytest.raises(HTTPException) as ei2:
        run(misconf.require_cf_access_internal(req))
    assert ei2.value.status_code == 503

    # And the convenience flag must report disabled (because config is incomplete)
    # so callers can't accidentally treat enforcement as active.
    assert misconf.is_admin_enforcement_enabled() is False
    assert misconf.is_internal_enforcement_enabled() is False


@pytest.mark.parametrize("raw,expected", [
    ("syrabit",                                "syrabit"),
    ("syrabit.cloudflareaccess.com",           "syrabit"),
    ("https://syrabit.cloudflareaccess.com",   "syrabit"),
    ("https://syrabit.cloudflareaccess.com/",  "syrabit"),
    ("  syrabit  ",                            "syrabit"),
    ("",                                        ""),
    ("Syrabit.CloudflareAccess.com",           "syrabit"),
])
def test_team_domain_normalizer(raw, expected):
    import cf_access
    assert cf_access._normalize_team_domain(raw) == expected


def test_status_introspection_no_secrets(fake_access):
    s = fake_access.module.status()
    assert s["team_domain"] == "syrabit-test"
    assert s["enforce"] is True
    assert s["admin_enforced"] is True
    assert s["internal_enforced"] is True
    # Task #706: break-glass surface ships in the diagnostics payload.
    assert s["break_glass_active"] is False
    assert s["break_glass_source"] is None
    assert s["break_glass_env_active"] is False
    assert s["break_glass_header_token_configured"] is False
    for v in s.values():
        assert "aud-admin-tag" not in str(v)
        assert "aud-internal-tag" not in str(v)


# ── Break-glass tests (Task #706) ────────────────────────────────────────────


def _request_with_headers_and_path(headers: list[tuple[bytes, bytes]], path: str = "/admin/test"):
    """Build a Request scope with a usable ``url.path`` for log assertions."""
    from fastapi import Request
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "headers": headers,
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("203.0.113.5", 12345),
    }
    return Request(scope)


def test_break_glass_env_bypasses_admin(monkeypatch, fake_access):
    """When ``CF_ACCESS_BREAK_GLASS=true``, admin Access enforcement is
    bypassed without a CF-Access JWT — the dependency returns a sentinel
    claims dict instead of raising 401."""
    monkeypatch.setenv("CF_ACCESS_BREAK_GLASS", "true")
    req = _request_with_headers_and_path([])
    claims = run(fake_access.module.require_cf_access_admin(req))
    assert claims is not None
    assert claims.get("break_glass") is True
    assert claims.get("source") == "env"


def test_break_glass_env_reports_in_status(monkeypatch, fake_access):
    """``status()`` flips ``admin_enforced`` to False while break-glass is
    active so the paging rule has a single field to alert on."""
    monkeypatch.setenv("CF_ACCESS_BREAK_GLASS", "true")
    s = fake_access.module.status()
    assert s["break_glass_active"] is True
    assert s["break_glass_source"] == "env"
    assert s["break_glass_env_active"] is True
    assert s["admin_enforced"] is False
    assert s["internal_enforced"] is False


def test_break_glass_header_requires_matching_token(monkeypatch, fake_access):
    """The header path is rejected unless the supplied value matches the
    ``CF_ACCESS_BREAK_GLASS_TOKEN`` env. A mismatched header is the same
    as no header — Access enforcement still runs."""
    from fastapi import HTTPException
    monkeypatch.setenv("CF_ACCESS_BREAK_GLASS_TOKEN", "correct-horse-battery-staple")

    bad_req = _request_with_headers_and_path(
        [(b"x-cf-access-break-glass", b"wrong-token")]
    )
    with pytest.raises(HTTPException) as ei:
        run(fake_access.module.require_cf_access_admin(bad_req))
    assert ei.value.status_code == 401  # bypass not granted; standard 401 path

    good_req = _request_with_headers_and_path(
        [(b"x-cf-access-break-glass", b"correct-horse-battery-staple")]
    )
    claims = run(fake_access.module.require_cf_access_admin(good_req))
    assert claims is not None
    assert claims.get("break_glass") is True
    assert claims.get("source") == "header"


def test_break_glass_header_ignored_when_token_unset(monkeypatch, fake_access):
    """If the operator never staged a break-glass token, the header path
    cannot be activated — preventing accidental wide-open bypass."""
    from fastapi import HTTPException
    monkeypatch.delenv("CF_ACCESS_BREAK_GLASS_TOKEN", raising=False)
    monkeypatch.delenv("CF_ACCESS_BREAK_GLASS", raising=False)
    req = _request_with_headers_and_path(
        [(b"x-cf-access-break-glass", b"any-value")]
    )
    with pytest.raises(HTTPException) as ei:
        run(fake_access.module.require_cf_access_admin(req))
    assert ei.value.status_code == 401


def test_break_glass_logs_critical(monkeypatch, fake_access, caplog):
    """Every bypassed request emits a CRITICAL log line tagged for audit."""
    import logging as _logging
    monkeypatch.setenv("CF_ACCESS_BREAK_GLASS", "true")
    req = _request_with_headers_and_path([], path="/admin/users")
    with caplog.at_level(_logging.CRITICAL, logger="cf_access"):
        run(fake_access.module.require_cf_access_admin(req))
    assert any("BREAK-GLASS bypass active" in rec.message for rec in caplog.records)


def test_break_glass_state_helper_with_no_request(monkeypatch, fake_access):
    """``break_glass_state(None)`` only sees env state — used by callers
    that have no Request handle (e.g. background loops)."""
    monkeypatch.delenv("CF_ACCESS_BREAK_GLASS", raising=False)
    monkeypatch.delenv("CF_ACCESS_BREAK_GLASS_TOKEN", raising=False)
    bg = fake_access.module.break_glass_state(None)
    assert bg["active"] is False
    assert bg["env_active"] is False
    assert bg["header_present"] is False

    monkeypatch.setenv("CF_ACCESS_BREAK_GLASS", "1")
    bg2 = fake_access.module.break_glass_state(None)
    assert bg2["active"] is True


# ── Task #710 — one-click force-disable ───────────────────────────────────────

class _FakeRedis:
    """In-memory stand-in for the sync redis client used by force-disable."""

    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


@pytest.fixture
def fake_redis(monkeypatch):
    """Patch the deps.redis_client used by cf_access.force_disable_break_glass."""
    import deps as _deps
    fr = _FakeRedis()
    monkeypatch.setattr(_deps, "redis_client", fr, raising=False)
    return fr


def test_force_disable_clears_env_and_persists(monkeypatch, fake_access, fake_redis):
    """Clicking 'Disable now' must (a) clear the env vars in the calling
    worker so the local request is no longer bypassed, (b) persist a
    Redis-backed flag so the OTHER gunicorn workers also stop bypassing."""
    monkeypatch.setenv("CF_ACCESS_BREAK_GLASS", "true")
    monkeypatch.setenv("CF_ACCESS_BREAK_GLASS_TOKEN", "secret123")

    rec = fake_access.module.force_disable_break_glass(actor="ops@syrabit.ai")

    assert rec["actor"] == "ops@syrabit.ai"
    assert rec["redis_persisted"] is True
    assert set(rec["env_cleared"]) == {"CF_ACCESS_BREAK_GLASS", "CF_ACCESS_BREAK_GLASS_TOKEN"}
    # Local-process env vars are gone
    import os as _os
    assert "CF_ACCESS_BREAK_GLASS" not in _os.environ
    assert "CF_ACCESS_BREAK_GLASS_TOKEN" not in _os.environ
    # Redis flag is set with the actor + timestamp
    raw = fake_redis.store["cf_access:break_glass_force_disabled"]
    import json as _json
    payload = _json.loads(raw)
    assert payload["actor"] == "ops@syrabit.ai"
    assert payload["disabled_at"]


def test_force_disable_makes_break_glass_inactive_in_status(monkeypatch, fake_access, fake_redis):
    """Even if a fresh worker still sees CF_ACCESS_BREAK_GLASS=true in its
    env, the Redis force-disable flag must override it so status() and the
    request-time gate report break-glass OFF."""
    # Simulate "another worker still has the env set" by re-setting it
    # AFTER the force-disable persists the Redis flag.
    fake_access.module.force_disable_break_glass(actor="ops@syrabit.ai")
    monkeypatch.setenv("CF_ACCESS_BREAK_GLASS", "true")

    s = fake_access.module.status()
    assert s["break_glass_active"] is False
    assert s["break_glass_force_disabled"] is True
    assert s["break_glass_force_disabled_by"] == "ops@syrabit.ai"
    assert s["break_glass_env_active"] is True  # raw env still reports true
    # And the admin gate now refuses to bypass — the env flag is masked.
    from fastapi import HTTPException
    req = _request_with_headers_and_path([])
    with pytest.raises(HTTPException) as ei:
        run(fake_access.module.require_cf_access_admin(req))
    assert ei.value.status_code == 401


def test_force_disable_works_without_redis(monkeypatch, fake_access):
    """If Redis is unavailable, the disable still pops env in this process
    but reports redis_persisted=False so the caller can warn the operator
    about multi-worker drift."""
    import deps as _deps
    monkeypatch.setattr(_deps, "redis_client", None, raising=False)
    monkeypatch.setenv("CF_ACCESS_BREAK_GLASS", "true")

    rec = fake_access.module.force_disable_break_glass(actor="ops@syrabit.ai")

    assert rec["redis_persisted"] is False
    assert "CF_ACCESS_BREAK_GLASS" in rec["env_cleared"]
    import os as _os
    assert "CF_ACCESS_BREAK_GLASS" not in _os.environ


def test_clear_force_disable_rearms(fake_access, fake_redis):
    """clear_force_disable() removes the Redis flag so a fresh env-set
    can re-arm break-glass (used by tests / explicit operator re-arm)."""
    fake_access.module.force_disable_break_glass(actor="ops@syrabit.ai")
    assert "cf_access:break_glass_force_disabled" in fake_redis.store

    ok = fake_access.module.clear_force_disable()
    assert ok is True
    assert "cf_access:break_glass_force_disabled" not in fake_redis.store


def test_force_disable_audit_log_is_warning(fake_access, fake_redis, caplog):
    """The disable action must emit a WARNING-level audit log carrying the
    actor identity so SOC tooling can stitch the bypass timeline."""
    import logging as _logging
    with caplog.at_level(_logging.WARNING, logger="cf_access"):
        fake_access.module.force_disable_break_glass(actor="ops@syrabit.ai")
    assert any(
        "BREAK-GLASS force-disabled" in rec.message and "ops@syrabit.ai" in rec.message
        for rec in caplog.records
    )
