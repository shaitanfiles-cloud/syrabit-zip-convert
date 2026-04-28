"""Task #793 — signed device tokens for the per-device free-tier chat quota.

The free tier was previously gated on a per-IP daily counter
(``ip_daily_credits:{ip}:{YYYY-MM-DD}``) charged inside
``auth_deps.rate_limit_chat_optional``. That collapsed for the real
audience: AHSEC/SEBA students sit behind shared egress IPs (Jio/Airtel
mobile CGNAT, school/college WiFi, hostel/cyber-café WiFi). The first
~30 messages from any one of those networks drained the entire pool for
every other user behind the same NAT, so the second visitor on the
same WiFi saw "Daily free quota exhausted" before they could send a
single message.

This module mints opaque, server-signed device tokens that are stored
as an HttpOnly cookie. The token is the **primary** quota key; the IP
is kept only as a coarse abuse cap. Each device gets its own 30/day
budget regardless of how many other devices share its public IP.

Wire format
-----------
Each token is the URL-safe base64 of three concatenated big-endian
fields::

    token = b64url( uuid_bytes(16) || issued_at_be8 || hmac_sha256_truncated(16) )

* ``uuid_bytes`` — 16 random bytes from ``secrets.token_bytes`` (the
  stable identifier we key the daily counter on).
* ``issued_at_be8`` — 8-byte unsigned big-endian unix timestamp at
  which we issued the token; used only for diagnostics today and to
  let us rotate signing keys later.
* ``hmac_sha256_truncated`` — the first 16 bytes of HMAC-SHA-256 of
  ``uuid_bytes || issued_at_be8`` keyed by the device-token signing
  secret. 128 bits of MAC is plenty to make forgery infeasible while
  keeping the cookie value short.

The signing secret is derived from ``JWT_SECRET`` via HKDF-style domain
separation (``HMAC-SHA256(JWT_SECRET, b"syrabit.device_token.v1")``)
so an attacker who learns a leaked device cookie still cannot forge a
session JWT, and vice-versa. Adding a new top-level secret would
expand the operational surface; reusing the existing one with a
context label gives us cryptographic separation for free.

Total cookie value length is ~54 ASCII characters (b64-encoded 40
bytes), well under any browser cookie size limit.

Why not just trust ``X-Anon-ID``?
---------------------------------
``routes/ai_chat.py`` already accepts an ``x-anon-id`` header sourced
from a client-side ``localStorage`` UUID. That value is fine for
analytics correlation but it is *unsigned* and *client-controlled*, so
it can be incremented per request to bypass the quota. The signed
HttpOnly cookie defended here is the actual quota key.
"""
from __future__ import annotations

import base64
import hmac
import hashlib
import secrets
import struct
import time
from typing import Optional

from config import JWT_SECRET

__all__ = [
    "DEVICE_COOKIE_NAME",
    "DEVICE_COOKIE_MAX_AGE_SECONDS",
    "mint_device_token",
    "verify_device_token",
    "device_token_id",
]

# Cookie metadata. 400 days is the longest the spec allows (and
# Chrome/Safari clamp anything higher to 400d anyway). A long expiry
# is fine because we only use the cookie for a per-day quota — the
# secret can be rotated by changing the context label below.
DEVICE_COOKIE_NAME = "syrabit_device"
DEVICE_COOKIE_MAX_AGE_SECONDS = 400 * 24 * 3600  # 400 days

_CONTEXT = b"syrabit.device_token.v1"
_HMAC_LEN = 16              # bytes of MAC kept in the cookie
_UUID_LEN = 16              # raw uuid bytes
_TS_LEN = 8                 # big-endian uint64 unix seconds
_PAYLOAD_LEN = _UUID_LEN + _TS_LEN
_FULL_LEN = _PAYLOAD_LEN + _HMAC_LEN


def _signing_key() -> bytes:
    """Derive the device-token signing key from ``JWT_SECRET``.

    Uses a single HMAC-SHA256 round with a fixed context label as a
    cheap KDF. This is the same trick TLS 1.3 / HKDF use to spawn
    multiple distinct keys from one master secret without the call
    sites needing to know each other's purpose.
    """
    secret = JWT_SECRET.encode("utf-8") if isinstance(JWT_SECRET, str) else JWT_SECRET
    return hmac.new(secret, _CONTEXT, hashlib.sha256).digest()


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def mint_device_token(now: Optional[int] = None) -> str:
    """Mint a fresh, signed device token.

    Returns the URL-safe base64 cookie value the caller should set on
    the outgoing response. The caller does **not** have to remember
    anything server-side — the token is self-describing and verified
    on every subsequent request through :func:`verify_device_token`.
    """
    uuid_bytes = secrets.token_bytes(_UUID_LEN)
    ts = int(now if now is not None else time.time())
    payload = uuid_bytes + struct.pack(">Q", ts)
    mac = hmac.new(_signing_key(), payload, hashlib.sha256).digest()[:_HMAC_LEN]
    return _b64url_encode(payload + mac)


def verify_device_token(cookie_value: Optional[str]) -> Optional[bytes]:
    """Verify a device-token cookie and return the raw uuid bytes.

    Returns the 16 raw uuid bytes on success, or ``None`` if the
    cookie is missing, malformed, or the MAC does not match. The
    caller treats ``None`` as "issue a fresh token" — never as "block
    the request" — so a malicious client clearing/forging the cookie
    just gets a brand-new 30/day budget, no worse than wiping their
    browser profile. The IP coarse cap still pins them.

    All comparisons use :func:`hmac.compare_digest` to be constant-time
    so we don't leak signing-key bits via response timing.
    """
    if not cookie_value:
        return None
    try:
        raw = _b64url_decode(cookie_value)
    except Exception:
        return None
    if len(raw) != _FULL_LEN:
        return None
    payload = raw[:_PAYLOAD_LEN]
    mac = raw[_PAYLOAD_LEN:]
    expected = hmac.new(_signing_key(), payload, hashlib.sha256).digest()[:_HMAC_LEN]
    if not hmac.compare_digest(mac, expected):
        return None
    return payload[:_UUID_LEN]


def device_token_id(cookie_value: Optional[str]) -> Optional[str]:
    """Convenience wrapper: returns the printable token id on success.

    The Redis daily counter key uses the printable id, not the raw
    bytes, so we never base64 in the hot path.
    """
    raw = verify_device_token(cookie_value)
    if raw is None:
        return None
    return raw.hex()
