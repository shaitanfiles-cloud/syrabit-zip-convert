"""Syrabit.ai — Educational domain allowlist.

Configurable, hot-editable allowlist of domains that the educational
browser/reader is permitted to fetch from. The allowlist is the union of:

  1. A baked-in default seed (BASE_ALLOWLIST) — covers ~30 well-known
     educational publishers so the system works out of the box.
  2. Operator overrides stored in MongoDB (`db.edu_allowlist`) — admins
     add/remove domains via the admin API without redeploying.

Lookups are O(1) (set membership) and cached for 60 seconds with an
explicit invalidate hook used by the admin write path.

Subdomain matching: a request for `cs.example.edu` is allowed when
`example.edu` is on the allowlist (RFC-3986 host suffix match).
"""
from __future__ import annotations

import time
import logging
from typing import Optional, Iterable
from urllib.parse import urlparse

from deps import db, is_mongo_available

logger = logging.getLogger(__name__)

# Curated educational seed list. Operators can disable any of these via
# the admin API (a domain marked status="blocked" overrides the default).
BASE_ALLOWLIST: frozenset = frozenset({
    # Reference / encyclopaedic
    "wikipedia.org", "wikibooks.org", "simple.wikipedia.org",
    "britannica.com", "scholarpedia.org",
    # Indian curriculum + boards
    "ncert.nic.in", "cbse.gov.in", "cbseacademic.nic.in",
    "ahsec.assam.gov.in", "sebaonline.org",
    # Education publishers (kid-safe, English)
    "khanacademy.org", "byjus.com", "vedantu.com", "toppr.com",
    "learncbse.in", "shaalaa.com", "doubtnut.com", "askiitians.com",
    "meritnation.com", "studiestoday.com", "tutorialspoint.com",
    "geeksforgeeks.org", "javatpoint.com", "mathsisfun.com",
    "brilliant.org", "unacademy.com", "embibe.com",
    # Primary research / .edu / .ac.in
    "nature.com", "sciencedirect.com", "jstor.org",
    "iitb.ac.in", "iisc.ac.in", "iitm.ac.in", "iitd.ac.in",
    # Standards bodies / open courseware
    "ocw.mit.edu", "openstax.org", "ck12.org",
    # Government education portals
    "diksha.gov.in", "swayam.gov.in", "epathshala.nic.in",
})

# Domains we always reject regardless of operator config — adult content,
# anonymisers, file lockers, anything that would defeat the kid-safe
# guarantee promised by the educational browser.
HARD_DENYLIST: frozenset = frozenset({
    "pornhub.com", "xvideos.com", "redtube.com", "xnxx.com",
    "4chan.org", "8kun.top",
    "torproject.org",  # not adult, but not appropriate for the use case
})

EDU_ALLOWLIST_COLLECTION = "edu_allowlist"
EDU_BLOCKED_REQUESTS_COLLECTION = "edu_blocked_requests"
EDU_REQUESTED_SITES_COLLECTION = "edu_requested_sites"
EDU_USER_STATE_COLLECTION = "edu_user_state"

_OVERRIDES_CACHE: dict[str, set[str]] = {"allow": set(), "block": set()}
_OVERRIDES_CACHE_TS: float = 0.0
_OVERRIDES_TTL = 60.0


def _normalize_host(host: str) -> str:
    """Lowercase and strip leading `www.` / trailing dot."""
    if not host:
        return ""
    h = host.strip().lower().rstrip(".")
    if h.startswith("www."):
        h = h[4:]
    return h


def _normalize_domain(domain: str) -> str:
    """Normalise a domain entered via the admin API (strip scheme, path)."""
    raw = (domain or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        try:
            raw = urlparse(raw).hostname or ""
        except Exception:
            return ""
    return _normalize_host(raw)


def _host_matches(host: str, domain: str) -> bool:
    """True when `host` equals `domain` or is a subdomain of it."""
    if not host or not domain:
        return False
    return host == domain or host.endswith("." + domain)


async def _refresh_overrides_cache(force: bool = False) -> None:
    global _OVERRIDES_CACHE_TS
    now = time.time()
    if not force and (now - _OVERRIDES_CACHE_TS) < _OVERRIDES_TTL:
        return
    try:
        if not await is_mongo_available():
            _OVERRIDES_CACHE_TS = now
            return
    except Exception:
        _OVERRIDES_CACHE_TS = now
        return
    try:
        cursor = db[EDU_ALLOWLIST_COLLECTION].find({}, {"_id": 0, "domain": 1, "status": 1})
        allow: set[str] = set()
        block: set[str] = set()
        async for doc in cursor:
            d = _normalize_domain(doc.get("domain", ""))
            status = (doc.get("status") or "").lower().strip()
            if not d:
                continue
            if status == "blocked":
                block.add(d)
            else:
                allow.add(d)
        _OVERRIDES_CACHE["allow"] = allow
        _OVERRIDES_CACHE["block"] = block
        _OVERRIDES_CACHE_TS = now
    except Exception as e:
        logger.warning(f"[edu_allowlist] cache refresh failed: {e}")
        _OVERRIDES_CACHE_TS = now  # avoid hammering the DB on failure


def invalidate_cache() -> None:
    """Force the next lookup to re-read MongoDB. Called by admin writes."""
    global _OVERRIDES_CACHE_TS
    _OVERRIDES_CACHE_TS = 0.0


async def is_allowed_url(url: str) -> tuple[bool, str]:
    """Decide if a URL may be fetched by the reader.

    Returns `(allowed, reason)`. `reason` is one of:
      "ok", "invalid_url", "scheme", "private_ip", "hard_denied",
      "operator_blocked", "not_allowlisted".
    """
    if not url or not isinstance(url, str):
        return False, "invalid_url"
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "invalid_url"
    if parsed.scheme not in ("http", "https"):
        return False, "scheme"
    host = _normalize_host(parsed.hostname or "")
    if not host:
        return False, "invalid_url"

    # Reject loopback / RFC-1918 / link-local hosts so the reader cannot
    # be used as an SSRF primitive against the worker's own network.
    try:
        import ipaddress
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, "private_ip"
    except ValueError:
        if host in {"localhost", "0.0.0.0"} or host.endswith(".local") or host.endswith(".internal"):
            return False, "private_ip"

    for bad in HARD_DENYLIST:
        if _host_matches(host, bad):
            return False, "hard_denied"

    await _refresh_overrides_cache()
    for bad in _OVERRIDES_CACHE["block"]:
        if _host_matches(host, bad):
            return False, "operator_blocked"

    # Common education-suffix shortcut: any *.edu / *.ac.in / *.gov.in is
    # treated as educational by default.
    edu_suffixes = (".edu", ".edu.in", ".ac.in", ".gov.in", ".gov", ".nic.in")
    if any(host.endswith(s) for s in edu_suffixes):
        return True, "ok"

    for good in BASE_ALLOWLIST:
        if _host_matches(host, good):
            return True, "ok"
    for good in _OVERRIDES_CACHE["allow"]:
        if _host_matches(host, good):
            return True, "ok"

    return False, "not_allowlisted"


async def list_overrides() -> list[dict]:
    """Return all admin-managed override entries (allow + block)."""
    if not await is_mongo_available():
        return []
    try:
        cursor = db[EDU_ALLOWLIST_COLLECTION].find({}, {"_id": 0})
        return [doc async for doc in cursor]
    except Exception as e:
        logger.warning(f"[edu_allowlist] list_overrides failed: {e}")
        return []


async def upsert_override(domain: str, status: str = "allowed", note: str = "", actor: str = "") -> dict:
    """Add or update a domain override. status ∈ {allowed, blocked}."""
    d = _normalize_domain(domain)
    if not d:
        raise ValueError("invalid_domain")
    status = (status or "allowed").lower().strip()
    if status not in ("allowed", "blocked"):
        raise ValueError("invalid_status")
    if not await is_mongo_available():
        raise RuntimeError("mongo_unavailable")
    doc = {
        "domain": d,
        "status": status,
        "note": note[:280] if note else "",
        "actor": actor[:120] if actor else "",
        "updated_at": time.time(),
    }
    await db[EDU_ALLOWLIST_COLLECTION].update_one(
        {"domain": d}, {"$set": doc, "$setOnInsert": {"created_at": time.time()}}, upsert=True,
    )
    invalidate_cache()
    return doc


async def remove_override(domain: str) -> bool:
    d = _normalize_domain(domain)
    if not d or not await is_mongo_available():
        return False
    res = await db[EDU_ALLOWLIST_COLLECTION].delete_one({"domain": d})
    invalidate_cache()
    return bool(res.deleted_count)


async def log_blocked_request(url: str, reason: str, actor: str = "", ip_hash: str = "") -> None:
    """Append a blocked-request entry for admin review.

    Best-effort; failures are swallowed so the reader endpoint never
    fails because of telemetry trouble.
    """
    try:
        if not await is_mongo_available():
            return
    except Exception:
        return
    try:
        host = ""
        try:
            host = _normalize_host(urlparse(url).hostname or "")
        except Exception:
            pass
        await db[EDU_BLOCKED_REQUESTS_COLLECTION].insert_one({
            "url": url[:500],
            "domain": host[:200],
            "reason": reason,
            "actor": actor[:120],
            "ip_hash": ip_hash[:64],
            "ts": time.time(),
        })
    except Exception as e:
        logger.debug(f"[edu_allowlist] log_blocked_request failed: {e}")


async def list_blocked_requests(limit: int = 200) -> list[dict]:
    if not await is_mongo_available():
        return []
    try:
        limit = max(1, min(1000, int(limit)))
        cursor = db[EDU_BLOCKED_REQUESTS_COLLECTION].find({}, {"_id": 0}).sort("ts", -1).limit(limit)
        return [doc async for doc in cursor]
    except Exception as e:
        logger.warning(f"[edu_allowlist] list_blocked_requests failed: {e}")
        return []


def effective_allowlist() -> dict:
    """Snapshot of the currently effective allow/block sets (for admin UI)."""
    return {
        "base": sorted(BASE_ALLOWLIST),
        "operator_allowed": sorted(_OVERRIDES_CACHE["allow"]),
        "operator_blocked": sorted(_OVERRIDES_CACHE["block"]),
        "hard_denied": sorted(HARD_DENYLIST),
        "edu_suffixes": [".edu", ".edu.in", ".ac.in", ".gov.in", ".gov", ".nic.in"],
    }


__all__ = [
    "BASE_ALLOWLIST", "HARD_DENYLIST",
    "EDU_ALLOWLIST_COLLECTION", "EDU_BLOCKED_REQUESTS_COLLECTION",
    "is_allowed_url", "invalidate_cache",
    "list_overrides", "upsert_override", "remove_override",
    "log_blocked_request", "list_blocked_requests",
    "effective_allowlist",
]
