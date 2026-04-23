"""Task #770 — JWT secrets must be set explicitly, no derivation
from MONGO_URL/DB_NAME.

Verifies:
1. `_require_secret` returns the env value when set and long enough.
2. `_require_secret` rejects too-short secrets (refuse to start).
3. `_require_secret` raises when unset and we're NOT under pytest
   (i.e. in production / dev outside the test runner).
4. `_require_secret` returns a *random ephemeral* secret under
   pytest — never the deterministic SHA256 of MONGO_URL+DB_NAME the
   audit flagged.
5. The module-level guard rejects ADMIN_JWT_SECRET == JWT_SECRET.

We test `_require_secret` directly to avoid having to reimport the
whole `config` module (which is already imported under the live
process secrets, so reimporting with a clean env is brittle).
"""
from __future__ import annotations

import hashlib
import os

import pytest

import config


# ── _require_secret unit tests ──────────────────────────────────────────


def test_require_secret_returns_env_value(monkeypatch):
    monkeypatch.setenv("FAKE_SECRET_X", "a" * 64)
    assert config._require_secret("FAKE_SECRET_X") == "a" * 64


def test_require_secret_rejects_too_short(monkeypatch):
    monkeypatch.setenv("FAKE_SECRET_X", "short")
    with pytest.raises(RuntimeError, match="only 5 chars long"):
        config._require_secret("FAKE_SECRET_X")


def test_require_secret_raises_when_unset_outside_pytest(monkeypatch):
    monkeypatch.delenv("FAKE_SECRET_X", raising=False)
    monkeypatch.setattr(config, "_RUNNING_UNDER_PYTEST", False)
    with pytest.raises(RuntimeError, match="audit finding S2"):
        config._require_secret("FAKE_SECRET_X")


def test_require_secret_under_pytest_returns_random_not_derived(monkeypatch):
    """The ephemeral test secret MUST be high-entropy random bytes,
    NOT a hash of MONGO_URL+DB_NAME (the exact hole audit S2
    flagged). Two calls back-to-back must yield different values."""
    monkeypatch.delenv("FAKE_SECRET_X", raising=False)
    monkeypatch.setattr(config, "_RUNNING_UNDER_PYTEST", True)
    s1 = config._require_secret("FAKE_SECRET_X")
    s2 = config._require_secret("FAKE_SECRET_X")
    assert len(s1) >= 64
    assert s1 != s2, "ephemeral secret must be random, not deterministic"
    # Belt-and-suspenders: ensure it doesn't match the old derivation
    # formula even by accident.
    derived = hashlib.sha256(
        b"syrabit-jwt-fallback:"
        + (config.MONGO_URL + config.DB_NAME + os.environ.get("REPL_ID", "")).encode()
    ).hexdigest()
    assert s1 != derived
    assert s2 != derived


# ── module-level guarantees ─────────────────────────────────────────────


def test_jwt_and_admin_secrets_are_distinct():
    assert config.JWT_SECRET and config.ADMIN_JWT_SECRET
    assert config.JWT_SECRET != config.ADMIN_JWT_SECRET


def test_admin_secret_not_derived_from_jwt_secret():
    """Old code derived ADMIN_JWT_SECRET as sha256("admin-" + JWT_SECRET).
    The new code requires it to be independently set, so this
    derivation must NOT match the live ADMIN_JWT_SECRET."""
    derived = hashlib.sha256(f"admin-{config.JWT_SECRET}".encode()).hexdigest()
    assert config.ADMIN_JWT_SECRET != derived
