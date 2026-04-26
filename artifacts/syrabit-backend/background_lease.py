"""Task #950 — Shared Mongo-backed lease for cross-replica dedup of
background loops.

Extracted from ``routes/admin_logs.py`` (Task #947) so the same
"only one replica fires this loop at a time" pattern can be reused by
every background loop where running it on N replicas would multiply
external API cost (LLM, GitHub, Cloudflare GraphQL, Cloudflare Pages
deploy hook, etc.).

Why a Mongo lease and not the file-lock ``_is_leader`` gate
-----------------------------------------------------------
``server.py`` historically gated leader-only loops on a per-machine
file lock (``/tmp/.syrabit_startup.lock``). That lock is fine for
"only one gunicorn worker on this machine should run startup
migrations", but it is **per-machine**: two Railway replicas each
acquire their own file lock and each consider themselves "the leader".
Every leader-gated loop then doubles up — the LLM cache pre-warm runs
2× per cycle, the weekly CF GraphQL pull burns 2× the analytics quota,
the nightly Cloudflare Pages deploy hook fires 2× (causing useless
rebuilds), etc.

The shared lease moves the dedup gate from the local filesystem into
``db.job_locks`` so it works across replicas. The file lock can stay,
but only for true once-at-boot work that's idempotent within a single
machine — index creation, seeding, etc.

The lease state machine
-----------------------
Each lease lives in ``db.job_locks`` keyed on a unique ``lock_id``
(Mongo ``_id``). The doc carries three lease fields, alongside any
domain-specific fields the caller wants to keep next to it (e.g. the
CF pull cursor):

  * ``lease_owner``       — opaque per-process id of the holder, or
                            ``None`` when the slot is free.
  * ``lease_expires_at``  — UTC datetime; the holder must renew before
                            this deadline or the next acquirer can take
                            over.
  * ``lease_acquired_at`` — ISO timestamp the current term started.

``try_acquire_lease`` is a single atomic ``find_one_and_update`` — it
succeeds when ANY of these hold on the existing doc:

  * ``lease_owner == owner_id``         — renewal path; refreshes the
                                          deadline so peers stay backed
                                          off.
  * ``lease_expires_at <= now``         — previous owner crashed or was
                                          scaled down without releasing;
                                          a peer may take over.
  * ``lease_owner is None`` / missing   — legacy doc (created before the
                                          lease fields existed); bootstrap
                                          in place without losing
                                          domain-specific fields.

If no doc exists at all (fresh deployment) we fall through to
``insert_one``; ``DuplicateKeyError`` means a peer beat us to it, which
is the desired outcome (they hold the lease, we back off).

``release_lease`` is scoped to ``lease_owner == owner_id`` so we never
clobber a peer that has already taken over.

Recommended TTL
---------------
Set ``ttl_s`` to ~3× the loop's iteration interval. That way a single
missed renewal (transient network blip, slow tick) doesn't trigger a
needless leader fail-over, but a real outage hands over within ~3
ticks instead of waiting hours.

Usage
-----

    from background_lease import make_owner_id, try_acquire_lease, release_lease

    OWNER_ID = make_owner_id("my-loop")
    LOCK_ID = "my_loop_lock"
    LOOP_INTERVAL_S = 600
    FOLLOWER_INTERVAL_S = 30

    async def _my_loop():
        try:
            while True:
                if not await try_acquire_lease(
                    db, LOCK_ID, OWNER_ID, ttl_s=LOOP_INTERVAL_S * 3,
                ):
                    await asyncio.sleep(FOLLOWER_INTERVAL_S)
                    continue
                try:
                    await do_one_iteration()
                except Exception:
                    logger.exception("my_loop tick failed")
                await asyncio.sleep(LOOP_INTERVAL_S)
        finally:
            await asyncio.shield(release_lease(db, LOCK_ID, OWNER_ID))
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Field names on the lease doc. Kept stable so the existing CF pull
# lease (Task #947) stays compatible without a data migration.
LEASE_OWNER_FIELD = "lease_owner"
LEASE_EXPIRES_FIELD = "lease_expires_at"
LEASE_ACQUIRED_FIELD = "lease_acquired_at"
LEASE_RELEASED_FIELD = "released_at"


def make_owner_id(prefix: Optional[str] = None) -> str:
    """Return a stable per-process owner id.

    Format: ``<hostname>-<12 hex>`` (or ``<prefix>-<hostname>-<12 hex>``).
    The hex suffix prevents two replicas with the same ``HOSTNAME``
    (rare in container schedulers but possible during blue/green
    cutovers) from colliding on the lease doc.
    """
    host = os.environ.get("HOSTNAME") or "host"
    suffix = uuid.uuid4().hex[:12]
    if prefix:
        return f"{prefix}-{host}-{suffix}"
    return f"{host}-{suffix}"


async def try_acquire_lease(
    db_handle,
    lock_id: str,
    owner_id: str,
    ttl_s: int,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Atomic CAS on ``db.job_locks[lock_id]`` — return True iff this
    caller now holds the lease.

    Safe across N replicas: only one of them can return True per lease
    term. Returns False (and logs at DEBUG) on any Mongo error so a
    flaky DB never tears down the calling loop — the loop will just
    back off for one follower interval and retry.
    """
    if db_handle is None or not lock_id or not owner_id or ttl_s <= 0:
        return False
    now = now or datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=int(ttl_s))
    set_payload = {
        LEASE_OWNER_FIELD: owner_id,
        LEASE_EXPIRES_FIELD: expires_at,
        LEASE_ACQUIRED_FIELD: now.isoformat(),
    }
    try:
        res = await db_handle.job_locks.find_one_and_update(
            {
                "_id": lock_id,
                "$or": [
                    {LEASE_OWNER_FIELD: owner_id},
                    {LEASE_EXPIRES_FIELD: {"$lte": now}},
                    {LEASE_OWNER_FIELD: None},
                ],
            },
            {"$set": set_payload},
        )
        if res is not None:
            return True
    except Exception as exc:
        logger.debug("[lease %s] CAS failed: %s", lock_id, exc)
        return False

    # Bootstrap path — no doc exists yet. ``insert_one`` is racy across
    # replicas; the loser gets DuplicateKeyError which we swallow and
    # treat as "a peer holds the lease, back off".
    try:
        from pymongo.errors import DuplicateKeyError  # local import keeps test fakes happy
    except Exception:  # pragma: no cover — pymongo is a hard dep in prod
        DuplicateKeyError = Exception  # type: ignore[assignment, misc]
    try:
        await db_handle.job_locks.insert_one({
            "_id": lock_id,
            **set_payload,
        })
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:
        logger.debug(
            "[lease %s] bootstrap insert failed: %s", lock_id, exc,
        )
        return False


async def release_lease(
    db_handle,
    lock_id: str,
    owner_id: str,
) -> None:
    """Best-effort scoped release on graceful shutdown.

    Only clears the lease fields when ``lease_owner`` still matches
    ``owner_id``, so we never clobber a peer that has already taken
    over after a fail-over. Domain-specific fields next to the lease
    (e.g. the CF pull cursor) are intentionally left untouched.
    """
    if db_handle is None or not lock_id or not owner_id:
        return
    try:
        await db_handle.job_locks.update_one(
            {"_id": lock_id, LEASE_OWNER_FIELD: owner_id},
            {"$set": {
                LEASE_OWNER_FIELD: None,
                LEASE_EXPIRES_FIELD: None,
                LEASE_RELEASED_FIELD: datetime.now(timezone.utc).isoformat(),
            }},
        )
    except Exception as exc:
        logger.debug("[lease %s] release failed: %s", lock_id, exc)
