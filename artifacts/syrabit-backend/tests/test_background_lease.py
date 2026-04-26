"""Task #950 — Tests for the shared ``background_lease`` helper and the
two highest-cost loops it gates: the LLM-cache pre-warm
(``routes.admin_advanced._cache_warm_loop``) and the weekly Cloudflare
bot report (``routes.bot_discovery._cf_bot_report_loop``).

Why these two specifically
--------------------------
The CF-pull lease tests in ``test_unified_logs_cf_pull.py`` already
cover the Mongo CAS state machine end-to-end, but they only exercise
the wrappers in ``routes/admin_logs.py``. After Task #950 extracted the
state machine into ``background_lease`` and rewired several other
loops, we need direct coverage of:

  * the shared helper itself (so a regression in
    ``background_lease.try_acquire_lease`` is caught even if a future
    refactor drops the CF-pull wrappers); and
  * the two reused gates with the largest blast radius if doubled —
    ``cache_warm`` (every duplicate run = N× LLM token spend) and
    ``cf_bot_report`` (every duplicate run = N× Cloudflare GraphQL
    quota cost).

Both downstream tests assert the *gated body* is invoked exactly once
when two replicas race on the same tick — that is the property we are
actually shipping. A green CAS test alone would not catch a wiring
regression where the loop forgets to honour the lease's False return.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import background_lease
from tests.test_unified_logs_dao import _FakeDb


# ─── background_lease state machine ──────────────────────────────────


def test_make_owner_id_is_unique_per_call():
    """Each call gets a fresh hex suffix so two replicas with the same
    HOSTNAME (rare in container schedulers but possible during
    blue/green cutovers) cannot collide on the lease doc."""
    a = background_lease.make_owner_id("loop")
    b = background_lease.make_owner_id("loop")
    assert a != b
    assert a.startswith("loop-")
    assert b.startswith("loop-")


def test_try_acquire_lease_bootstraps_when_no_doc_exists():
    """Fresh deployment: nothing in job_locks → insert path wins, owner
    is set, expires_at is in the future."""
    async def _inner():
        db = _FakeDb()
        now = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        ok = await background_lease.try_acquire_lease(
            db, "demo_lock", "replica-A", ttl_s=120, now=now,
        )
        assert ok is True
        doc = next((d for d in db.job_locks.docs
                    if d.get("_id") == "demo_lock"), None)
        assert doc is not None
        assert doc[background_lease.LEASE_OWNER_FIELD] == "replica-A"
        assert doc[background_lease.LEASE_EXPIRES_FIELD] > now
    asyncio.run(_inner())


def test_try_acquire_lease_blocks_peer_until_ttl_expires():
    """Core anti-spam property: once replica-A holds the lease, replica-B
    cannot acquire it inside the TTL — so the gated work runs 1× per
    cycle, not N×."""
    async def _inner():
        db = _FakeDb()
        t0 = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        assert await background_lease.try_acquire_lease(
            db, "demo_lock", "replica-A", ttl_s=60, now=t0,
        ) is True
        # B tries 5s later — well inside the TTL.
        assert await background_lease.try_acquire_lease(
            db, "demo_lock", "replica-B", ttl_s=60,
            now=t0 + timedelta(seconds=5),
        ) is False
        # B tries again after the TTL expires — fail-over takes hold.
        assert await background_lease.try_acquire_lease(
            db, "demo_lock", "replica-B", ttl_s=60,
            now=t0 + timedelta(seconds=120),
        ) is True
        doc = next((d for d in db.job_locks.docs
                    if d.get("_id") == "demo_lock"), None)
        assert doc[background_lease.LEASE_OWNER_FIELD] == "replica-B"
    asyncio.run(_inner())


def test_release_lease_only_clears_when_caller_owns_it():
    """A non-owner calling release must NOT clobber a peer's lease —
    otherwise a slow shutdown on replica-B could free a still-active
    lease on replica-A and let a third replica stomp the work."""
    async def _inner():
        db = _FakeDb()
        now = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        await background_lease.try_acquire_lease(
            db, "demo_lock", "replica-A", ttl_s=120, now=now,
        )
        # B's release: no-op.
        await background_lease.release_lease(db, "demo_lock", "replica-B")
        doc = next((d for d in db.job_locks.docs
                    if d.get("_id") == "demo_lock"), None)
        assert doc[background_lease.LEASE_OWNER_FIELD] == "replica-A"
        # A's release: clears the lease so a peer can take over without
        # waiting for the TTL.
        await background_lease.release_lease(db, "demo_lock", "replica-A")
        doc = next((d for d in db.job_locks.docs
                    if d.get("_id") == "demo_lock"), None)
        assert doc[background_lease.LEASE_OWNER_FIELD] is None
    asyncio.run(_inner())


def test_try_acquire_lease_renews_for_same_owner():
    """The leader re-calls try_acquire on every tick. We must allow
    that and push expires_at forward — otherwise a long-running leader
    would ‘lose’ its own lease the moment the TTL elapses, even though
    it is still healthy and looping."""
    async def _inner():
        db = _FakeDb()
        t0 = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        await background_lease.try_acquire_lease(
            db, "demo_lock", "replica-A", ttl_s=120, now=t0,
        )
        first = next(d for d in db.job_locks.docs
                     if d.get("_id") == "demo_lock"
                     )[background_lease.LEASE_EXPIRES_FIELD]
        ok = await background_lease.try_acquire_lease(
            db, "demo_lock", "replica-A", ttl_s=120,
            now=t0 + timedelta(seconds=30),
        )
        assert ok is True
        second = next(d for d in db.job_locks.docs
                      if d.get("_id") == "demo_lock"
                      )[background_lease.LEASE_EXPIRES_FIELD]
        assert second > first
    asyncio.run(_inner())


def test_try_acquire_lease_bootstraps_legacy_doc_without_lease_fields():
    """Migration path: a job_locks doc may pre-date the lease fields
    (e.g. the CF pull cursor existed before Task #947). The CAS branch
    matching ``lease_owner == None`` lets us upgrade in place without
    losing co-located domain fields."""
    async def _inner():
        db = _FakeDb()
        db.job_locks.docs.append({
            "_id": "demo_lock",
            "cursor": "2026-04-26T09:00:00+00:00",
            "updated_at": "2026-04-26T09:00:00+00:00",
        })
        now = datetime(2026, 4, 26, 10, 0, tzinfo=timezone.utc)
        ok = await background_lease.try_acquire_lease(
            db, "demo_lock", "replica-A", ttl_s=120, now=now,
        )
        assert ok is True
        doc = next(d for d in db.job_locks.docs
                   if d.get("_id") == "demo_lock")
        assert doc[background_lease.LEASE_OWNER_FIELD] == "replica-A"
        # Cursor must survive the lease bootstrap.
        assert doc["cursor"] == "2026-04-26T09:00:00+00:00"
    asyncio.run(_inner())


def test_try_acquire_lease_returns_false_on_invalid_inputs():
    """Defensive guard: a None db handle (e.g. Mongo not yet
    initialised at boot) must return False, not raise — otherwise the
    caller's first iteration would crash the loop before the finally
    block could clean up."""
    async def _inner():
        assert await background_lease.try_acquire_lease(
            None, "x", "owner", ttl_s=60,
        ) is False
        db = _FakeDb()
        assert await background_lease.try_acquire_lease(
            db, "", "owner", ttl_s=60,
        ) is False
        assert await background_lease.try_acquire_lease(
            db, "x", "", ttl_s=60,
        ) is False
        assert await background_lease.try_acquire_lease(
            db, "x", "owner", ttl_s=0,
        ) is False
    asyncio.run(_inner())


# ─── Wiring checks: cache_warm + cf_bot_report respect the lease ────


def test_cache_warm_loop_skips_perform_when_peer_holds_lease():
    """``_cache_warm_loop`` must not call ``_perform_cache_warm`` when
    a peer replica already holds the lease — that helper issues real
    LLM completions, so a missed lease check would multiply the LLM
    budget by N replicas every 6h."""
    async def _inner():
        from routes import admin_advanced

        db = _FakeDb()
        # Pre-seed the lease as owned by a peer with TTL well in the
        # future — replica-B (this process) must back off.
        now = datetime.now(timezone.utc)
        await background_lease.try_acquire_lease(
            db, admin_advanced._CACHE_WARM_LOCK_ID, "replica-A",
            ttl_s=admin_advanced._CACHE_WARM_LEASE_TTL_S, now=now,
        )

        async def _no_sleep(_s):
            # Break out of the infinite while loop by raising a
            # cancellation as soon as the loop reaches its first
            # follower-interval sleep — anything else (including the
            # post-warm sleep) means the loop fired the gated work.
            raise asyncio.CancelledError()

        async def _is_mongo_available():
            return True

        perform_calls = []

        async def _fake_perform(*a, **kw):
            perform_calls.append((a, kw))

        with patch.object(admin_advanced, "_perform_cache_warm",
                          new=_fake_perform), \
             patch("deps.db", db), \
             patch("deps.is_mongo_available", new=_is_mongo_available), \
             patch.object(asyncio, "sleep", new=_no_sleep):
            with pytest.raises(asyncio.CancelledError):
                await admin_advanced._cache_warm_loop()
        assert perform_calls == [], (
            "follower replica must not call _perform_cache_warm — "
            "doing so would multiply the LLM budget by replica count"
        )
    asyncio.run(_inner())


def test_cache_warm_loop_runs_perform_when_lease_is_free():
    """Smoke check the *positive* path: when no peer holds the lease,
    the leader replica acquires it and runs ``_perform_cache_warm``
    exactly once before sleeping the full loop interval."""
    async def _inner():
        from routes import admin_advanced

        db = _FakeDb()
        sleep_calls: list[float] = []

        async def _sleep_recorder(s):
            sleep_calls.append(s)
            # Cancel as soon as we reach the post-warm sleep so we
            # don't loop forever.
            if s == admin_advanced._CACHE_WARM_LOOP_INTERVAL_S:
                raise asyncio.CancelledError()

        async def _is_mongo_available():
            return True

        perform_calls = []

        async def _fake_perform(*a, **kw):
            perform_calls.append((a, kw))

        with patch.object(admin_advanced, "_perform_cache_warm",
                          new=_fake_perform), \
             patch("deps.db", db), \
             patch("deps.is_mongo_available", new=_is_mongo_available), \
             patch.object(asyncio, "sleep", new=_sleep_recorder):
            with pytest.raises(asyncio.CancelledError):
                await admin_advanced._cache_warm_loop()
        assert len(perform_calls) == 1
        # The lease must have been acquired then released cleanly via
        # the loop's finally branch — the released_at marker proves
        # both the acquire and the scoped release fired with our
        # owner_id.
        doc = next(d for d in db.job_locks.docs
                   if d.get("_id") == admin_advanced._CACHE_WARM_LOCK_ID)
        assert doc.get(background_lease.LEASE_RELEASED_FIELD) is not None
        assert doc[background_lease.LEASE_OWNER_FIELD] is None
    asyncio.run(_inner())


def test_cf_bot_report_loop_skips_pull_when_peer_holds_lease():
    """``_cf_bot_report_loop`` must not call
    ``_try_run_cf_bot_report_once`` (which fires CF GraphQL queries
    every poll) when a peer replica already holds the lease.  This is
    the property that prevents N× CF analytics quota cost across the
    Railway replica fleet."""
    async def _inner():
        from routes import bot_discovery

        db = _FakeDb()
        now = datetime.now(timezone.utc)
        await background_lease.try_acquire_lease(
            db, bot_discovery._CF_BOT_REPORT_LEASE_LOCK_ID,
            "replica-A",
            ttl_s=bot_discovery._CF_BOT_REPORT_LEASE_TTL_S,
            now=now,
        )

        run_calls = []

        async def _fake_run_once(*a, **kw):
            run_calls.append((a, kw))

        catchup_calls = []

        async def _fake_catchup(*a, **kw):
            catchup_calls.append((a, kw))

        async def _no_sleep(_s):
            raise asyncio.CancelledError()

        async def _is_mongo_available():
            return True

        with patch.object(bot_discovery,
                          "_try_run_cf_bot_report_once",
                          new=_fake_run_once), \
             patch.object(bot_discovery,
                          "_cf_bot_report_catchup_if_missed",
                          new=_fake_catchup), \
             patch("deps.db", db), \
             patch("deps.is_mongo_available", new=_is_mongo_available), \
             patch.object(asyncio, "sleep", new=_no_sleep):
            with pytest.raises(asyncio.CancelledError):
                await bot_discovery._cf_bot_report_loop()
        assert run_calls == [], (
            "follower replica must not call _try_run_cf_bot_report_once "
            "— doing so would multiply the CF GraphQL quota cost by "
            "replica count"
        )
        # Boot catch-up is also lease-gated — a fresh follower must
        # not replay the catch-up the leader already did.
        assert catchup_calls == []
    asyncio.run(_inner())


def test_cf_bot_report_loop_runs_pull_when_lease_is_free():
    """Positive wiring: when no peer holds the lease, the loop
    acquires it, runs the boot-time catch-up once, and proceeds into
    the polling branch (calling ``_try_run_cf_bot_report_once`` on the
    first tick)."""
    async def _inner():
        from routes import bot_discovery

        db = _FakeDb()

        run_calls = []

        async def _fake_run_once(*a, **kw):
            run_calls.append((a, kw))

        catchup_calls = []

        async def _fake_catchup(*a, **kw):
            catchup_calls.append((a, kw))

        async def _sleep_recorder(s):
            # Cancel after the loop fires its post-iteration sleep so
            # we exercise exactly one polling tick.
            if s == bot_discovery._CF_BOT_REPORT_LOOP_SLEEP_S:
                raise asyncio.CancelledError()

        async def _is_mongo_available():
            return True

        with patch.object(bot_discovery,
                          "_try_run_cf_bot_report_once",
                          new=_fake_run_once), \
             patch.object(bot_discovery,
                          "_cf_bot_report_catchup_if_missed",
                          new=_fake_catchup), \
             patch("deps.db", db), \
             patch("deps.is_mongo_available", new=_is_mongo_available), \
             patch.object(asyncio, "sleep", new=_sleep_recorder):
            with pytest.raises(asyncio.CancelledError):
                await bot_discovery._cf_bot_report_loop()
        assert len(catchup_calls) == 1, (
            "leader must run the boot-time catch-up exactly once")
        assert len(run_calls) == 1, (
            "leader must fire the CF GraphQL pull on the first tick")
        # The lease was acquired then released cleanly via the loop's
        # finally branch — the released_at marker proves both the
        # acquire and the scoped release fired with our owner_id.
        doc = next(
            d for d in db.job_locks.docs
            if d.get("_id") == bot_discovery._CF_BOT_REPORT_LEASE_LOCK_ID
        )
        assert doc.get(background_lease.LEASE_RELEASED_FIELD) is not None
        assert doc[background_lease.LEASE_OWNER_FIELD] is None
    asyncio.run(_inner())
