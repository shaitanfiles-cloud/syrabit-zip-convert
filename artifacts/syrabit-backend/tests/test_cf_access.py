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
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


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


def test_status_introspection_no_secrets(fake_access):
    s = fake_access.module.status()
    assert s["team_domain"] == "syrabit-test"
    assert s["enforce"] is True
    assert s["admin_enforced"] is True
    assert s["internal_enforced"] is True
    for v in s.values():
        assert "aud-admin-tag" not in str(v)
        assert "aud-internal-tag" not in str(v)
