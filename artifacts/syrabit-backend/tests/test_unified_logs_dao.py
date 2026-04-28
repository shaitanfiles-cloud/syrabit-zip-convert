"""Task #944 — Unified Log Explorer DAO unit tests.

These cover the pure logic that does not need a real Mongo: record
normalisation, the sampling rule, the filter-builder, and the bulk
insert / query / clear paths against a tiny FakeColl/FakeDb.

The async ``BackendLogShipper`` lifecycle is exercised end-to-end
against the same fake — start it, drop a few records, drain it, stop.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import unified_logs_dao as dao


# ─── tiny fake mongo ──────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = list(docs)
        self._sort_key: str | None = None
        self._sort_dir: int = -1
        self._limit: int | None = None
        self._proj: Dict[str, int] | None = None

    def sort(self, key, direction=None):
        # Accept both sort("k", -1) and sort([("k", -1)]).
        if isinstance(key, list):
            key, direction = key[0]
        self._sort_key = key
        self._sort_dir = int(direction or -1)
        return self

    def limit(self, n):
        self._limit = int(n)
        return self

    async def to_list(self, n):
        out = list(self._docs)
        if self._sort_key is not None:
            out.sort(key=lambda d: d.get(self._sort_key) or "",
                     reverse=(self._sort_dir < 0))
        if self._limit is not None:
            out = out[: self._limit]
        return out[: int(n)]

    def __aiter__(self):
        async def _iter():
            for d in await self.to_list(self._limit or len(self._docs)):
                yield d
        return _iter()


class _FakeColl:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
        self.indexes: List[Dict[str, Any]] = []

    async def create_index(self, spec, **kwargs):
        self.indexes.append({"spec": spec, **kwargs})

    async def insert_many(self, docs, ordered=False):
        # Apply the filter naively — these tests exercise build_filter
        # via query_logs separately.
        self.docs.extend(list(docs))

    async def insert_one(self, doc):
        # Task #947 — needed for the CF pull lease bootstrap path.
        # Enforce the _id uniqueness invariant so the racy
        # "two replicas insert at the same time" branch in
        # ``_try_acquire_cf_pull_lease`` exercises a realistic
        # ``DuplicateKeyError`` path.
        new_id = doc.get("_id")
        if new_id is not None:
            for existing in self.docs:
                if existing.get("_id") == new_id:
                    try:
                        from pymongo.errors import DuplicateKeyError
                    except Exception:
                        DuplicateKeyError = Exception  # type: ignore[assignment, misc]
                    raise DuplicateKeyError(f"duplicate _id={new_id!r}")
        self.docs.append(dict(doc))
        return None

    async def find_one(self, q=None, *_a, **_kw):
        for d in self.docs:
            if _match(d, q or {}):
                return d
        return None

    async def find_one_and_update(self, q, update, upsert=False, **_kw):
        # Task #947 — atomic CAS used by ``_try_acquire_cf_pull_lease``.
        # Returns the *pre-update* doc on a hit (matching the default
        # ``ReturnDocument.BEFORE`` behaviour Motor exposes), or None
        # when no doc matches.
        for d in self.docs:
            if _match(d, q or {}):
                pre = dict(d)
                if "$set" in update:
                    d.update(update["$set"])
                return pre
        return None

    async def update_one(self, q, update, upsert=False):
        # Tiny subset of mongo update. Handles:
        #   * ``$set`` — used by the api_config / job_locks writes.
        #   * ``$push`` with ``{$each: [...], $slice: -N}`` — Task #961
        #     uses this for atomic, race-proof appends to the rolling
        #     ``cf_pull_history`` list on the CF pull cursor doc. The
        #     ``$slice`` keeps only the last N entries (negative means
        #     "from the end") so the list stays bounded without a
        #     separate read-modify-write trim pass.
        def _apply(doc):
            if "$set" in update:
                doc.update(update["$set"])
            for field, spec in (update.get("$push") or {}).items():
                if isinstance(spec, dict) and "$each" in spec:
                    items = list(spec["$each"])
                    sl = spec.get("$slice")
                else:
                    items = [spec]
                    sl = None
                existing = doc.get(field)
                if not isinstance(existing, list):
                    existing = []
                existing = list(existing) + items
                if isinstance(sl, int):
                    # Mongo: positive ``$slice`` keeps the first N,
                    # negative keeps the last N. We support both.
                    existing = existing[sl:] if sl < 0 else existing[:sl]
                doc[field] = existing

        for d in self.docs:
            if _match(d, q or {}):
                _apply(d)
                return None
        if upsert:
            # Build the upserted doc from the (non-operator) fields of
            # the query, then apply the same $set/$push pipeline so
            # upsert + $push reaches the same final state as a
            # subsequent match would.
            new = {k: v for k, v in (q or {}).items() if not isinstance(v, dict) or not any(str(op).startswith("$") for op in v)}
            _apply(new)
            self.docs.append(new)
        return None

    def find(self, q=None, projection=None):
        rows = [d for d in self.docs if _match(d, q or {})]
        return _FakeCursor(rows)

    async def count_documents(self, q, limit=None):
        n = sum(1 for d in self.docs if _match(d, q or {}))
        return min(n, int(limit)) if limit else n

    async def delete_many(self, q):
        keep = [d for d in self.docs if not _match(d, q or {})]
        deleted = len(self.docs) - len(keep)
        self.docs = keep
        class _R: pass
        r = _R(); r.deleted_count = deleted
        return r


def _match(doc: Dict[str, Any], q: Dict[str, Any]) -> bool:
    """Tiny subset of Mongo query semantics — enough for our unit tests."""
    for k, v in q.items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in v):
                return False
            continue
        dv = doc.get(k)
        if isinstance(v, dict):
            for op, opv in v.items():
                if op == "$in":
                    if dv not in opv:
                        return False
                elif op == "$gte":
                    if dv is None or dv < opv:
                        return False
                elif op == "$lte":
                    if dv is None or dv > opv:
                        return False
                elif op == "$lt":
                    if dv is None or dv >= opv:
                        return False
                elif op == "$regex":
                    import re
                    flags = re.I if v.get("$options") == "i" else 0
                    if not isinstance(dv, str) or not re.search(opv, dv, flags):
                        return False
                else:
                    return False
        else:
            if dv != v:
                return False
    return True


class _FakeDb:
    """Mongo-ish stand-in.

    Supports both ``db["coll"]`` and ``db.coll`` access — the routes
    use both styles (``db[UNIFIED_LOGS_COLLECTION]`` for the dynamic
    name, ``db.api_config`` / ``db.job_locks`` for the static ones).
    """
    def __init__(self):
        self._colls: Dict[str, _FakeColl] = {}

    def __getitem__(self, name):
        return self._colls.setdefault(name, _FakeColl())

    def __getattr__(self, name):
        # Only invoked when normal attribute lookup fails — avoids
        # recursion through __init__'s ``self._colls = {}``.
        if name.startswith("_"):
            raise AttributeError(name)
        return self._colls.setdefault(name, _FakeColl())


# ─── _normalize_record ────────────────────────────────────────────────


def test_normalize_record_clips_strings_and_assigns_id():
    rec = dao._normalize_record(
        {"source": "edge", "level": "INFO",
         "message": "a" * 1000, "route": "/x" + ("y" * 1000),
         "status": 200, "duration_ms": 17, "method": "get",
         "country": "INDIA-LONG", "colo": "BLR-LONG-TAG-12345",
         "cache": "HIT", "ray_id": "ray-1", "user_agent": "ua" * 500,
         "extra": {"k": "v"}, "timestamp": "2026-04-26T10:00:00Z"},
        default_source="edge",
        ttl_days=14,
    )
    assert rec is not None
    assert rec["source"] == "edge"
    assert rec["level"] == "info"
    assert rec["status"] == 200
    assert rec["duration_ms"] == 17
    assert rec["method"] == "get"
    assert len(rec["message"]) <= 500
    assert len(rec["route"]) <= 256
    assert rec["cache"] == "hit"
    assert rec["ray_id"] == "ray-1"
    # correlation_id falls back to ray_id when no explicit field given.
    assert rec["correlation_id"] == "ray-1"
    assert "_id" in rec and rec["_id"]
    assert isinstance(rec["expire_at"], datetime)


def test_normalize_record_rejects_unknown_source():
    rec = dao._normalize_record(
        {"source": "rogue-process", "message": "hello"},
        default_source="rogue-process",
        ttl_days=14,
    )
    assert rec is None


def test_normalize_record_uses_default_source_when_missing():
    rec = dao._normalize_record(
        {"message": "no source field"},
        default_source="backend",
        ttl_days=14,
    )
    assert rec is not None and rec["source"] == "backend"


def test_normalize_record_maps_level_aliases():
    for raw, expected in [
        ("warning", "warn"), ("WARN", "warn"),
        ("err", "error"), ("FATAL", "error"), ("critical", "error"),
        ("trace", "debug"), ("verbose", "debug"),
        ("garbage-level", "info"),
    ]:
        rec = dao._normalize_record(
            {"source": "edge", "level": raw},
            default_source="edge", ttl_days=14,
        )
        assert rec is not None
        assert rec["level"] == expected, f"{raw!r} → {rec['level']!r}"


def test_normalize_record_clamps_status_and_duration():
    rec = dao._normalize_record(
        {"source": "edge", "status": 9999, "duration_ms": -5},
        default_source="edge", ttl_days=14,
    )
    assert rec["status"] is None
    assert rec["duration_ms"] is None


# ─── should_keep_request ──────────────────────────────────────────────


def test_should_keep_request_always_keeps_4xx_and_5xx():
    assert dao.should_keep_request(status=404, duration_ms=10, sample_rate=0.0)
    assert dao.should_keep_request(status=500, duration_ms=10, sample_rate=0.0)


def test_should_keep_request_always_keeps_slow_requests():
    assert dao.should_keep_request(status=200, duration_ms=1500, sample_rate=0.0)
    assert dao.should_keep_request(status=200, duration_ms=99999, sample_rate=0.0)


def test_should_keep_request_drops_at_zero_sample_for_fast_2xx():
    assert not dao.should_keep_request(status=200, duration_ms=10, sample_rate=0.0)


def test_should_keep_request_keeps_at_full_sample_rate():
    assert dao.should_keep_request(status=200, duration_ms=10, sample_rate=1.0)


# ─── ensure_indexes ───────────────────────────────────────────────────


def test_ensure_indexes_creates_ttl_and_secondaries():
    async def _inner():
        db = _FakeDb()
        await dao.ensure_indexes(db)
        coll = db[dao.UNIFIED_LOGS_COLLECTION]
        names = [ix.get("name") for ix in coll.indexes]
        assert "ttl_expire_at" in names
        assert "timestamp_desc" in names
        assert "source_timestamp_desc" in names
        assert "correlation_id_sparse" in names
        assert "level_timestamp_desc" in names
        assert "status_timestamp_desc" in names
        # The TTL index must use expireAfterSeconds=0 so the field's
        # datetime value is the deadline (Mongo's standard pattern).
        ttl = next(ix for ix in coll.indexes if ix.get("name") == "ttl_expire_at")
        assert ttl.get("expireAfterSeconds") == 0


    asyncio.run(_inner())
# ─── insert_logs / query_logs / count_logs / clear_logs ──────────────


def test_insert_logs_counts_accepted_and_dropped():
    async def _inner():
        db = _FakeDb()
        res = await dao.insert_logs(
            db,
            [
                {"source": "edge",  "message": "good"},
                {"source": "rogue", "message": "bad"},  # dropped: bad source
                {"source": "edge",  "message": "good 2"},
            ],
            default_source="edge",
        )
        assert res == {"accepted": 2, "dropped": 1}
        assert len(db[dao.UNIFIED_LOGS_COLLECTION].docs) == 2


    asyncio.run(_inner())
def test_build_filter_translates_admin_ui_dict():
    async def _inner():
        f = dao.build_filter({
            "sources": ["edge", "backend", "rogue"],
            "levels": ["error"],
            "status_min": 400, "status_max": 599,
            "route_prefix": "/api/admin/",
            "correlation_id": "abc",
            "q": "boom",
            "since": "2026-04-25T00:00:00Z",
            "until": "2026-04-26T00:00:00Z",
        })
        assert f["source"]["$in"] == ["edge", "backend"]   # rogue dropped
        assert f["level"]["$in"] == ["error"]
        assert f["status"] == {"$gte": 400, "$lte": 599}
        assert f["route"]["$regex"].startswith("^/api/admin/")
        assert f["correlation_id"] == "abc"
        assert f["$or"][0]["message"]["$options"] == "i"
        assert "$gte" in f["timestamp"] and "$lte" in f["timestamp"]


    asyncio.run(_inner())
def test_query_and_count_and_clear_round_trip():
    async def _inner():
        db = _FakeDb()
        await dao.insert_logs(db, [
            {"source": "edge", "status": 200, "timestamp": "2026-04-26T10:00:00Z",
             "message": "ok"},
            {"source": "edge", "status": 500, "timestamp": "2026-04-26T10:01:00Z",
             "message": "boom"},
            {"source": "backend", "status": 200, "timestamp": "2026-04-26T10:02:00Z",
             "message": "fine"},
        ], default_source="edge")

        rows = await dao.query_logs(db, filters={"sources": ["edge"]}, limit=10)
        assert len(rows) == 2

        n = await dao.count_logs(db, {"sources": ["edge"]})
        assert n == 2

        deleted = await dao.clear_logs(db, filters={"sources": ["edge"]})
        assert deleted == 2
        remaining = await dao.query_logs(db, filters={}, limit=10)
        assert len(remaining) == 1
        assert remaining[0]["source"] == "backend"


    asyncio.run(_inner())
def test_iter_export_yields_filtered_rows():
    async def _inner():
        db = _FakeDb()
        await dao.insert_logs(db, [
            {"source": "edge", "status": 200, "timestamp": "2026-04-26T10:00:00Z"},
            {"source": "backend", "status": 500, "timestamp": "2026-04-26T10:01:00Z"},
        ], default_source="edge")
        out = []
        async for row in dao.iter_export(db, {"sources": ["backend"]}, limit=100):
            out.append(row)
        assert len(out) == 1
        assert out[0]["source"] == "backend"


    asyncio.run(_inner())
def test_fetch_trace_orders_ascending_by_timestamp():
    async def _inner():
        db = _FakeDb()
        await dao.insert_logs(db, [
            {"source": "edge",    "correlation_id": "c1",
             "timestamp": "2026-04-26T10:00:01Z"},
            {"source": "backend", "correlation_id": "c1",
             "timestamp": "2026-04-26T10:00:00Z"},
            {"source": "edge",    "correlation_id": "c2"},
        ], default_source="edge")
        rows = await dao.fetch_trace(db, "c1")
        assert [r["source"] for r in rows] == ["backend", "edge"]


    asyncio.run(_inner())
# ─── BackendLogShipper ────────────────────────────────────────────────


def test_backend_shipper_roundtrip(monkeypatch):
    async def _inner():
        dao._reset_backend_shipper_for_tests()
        monkeypatch.setenv("BACKEND_LOG_SAMPLE_RATE", "1.0")
        monkeypatch.delenv("LOGS_PAUSED", raising=False)

        db = _FakeDb()
        s = dao.get_backend_shipper()
        # Tighten the loop so the test doesn't have to sleep 2s.
        s._flush_interval_s = 0.05  # type: ignore[attr-defined]
        s._flush_batch_size = 5     # type: ignore[attr-defined]
        await s.start(db)
        try:
            s.record_request(method="GET", route="/api/x", status=200, duration_ms=10)
            s.record_request(method="GET", route="/api/y", status=500, duration_ms=20)
            await asyncio.sleep(0.2)  # wait for at least one flush tick
        finally:
            await s.stop()
        docs = db[dao.UNIFIED_LOGS_COLLECTION].docs
        assert len(docs) == 2
        assert {d["status"] for d in docs} == {200, 500}
        assert all(d["source"] == "backend" for d in docs)


    asyncio.run(_inner())
def test_backend_shipper_respects_pause_kill_switch(monkeypatch):
    async def _inner():
        dao._reset_backend_shipper_for_tests()
        monkeypatch.setenv("LOGS_PAUSED", "true")
        monkeypatch.setenv("BACKEND_LOG_SAMPLE_RATE", "1.0")
        db = _FakeDb()
        s = dao.get_backend_shipper()
        await s.start(db)
        try:
            s.record_request(method="GET", route="/x", status=500, duration_ms=10)
            await asyncio.sleep(0.05)
        finally:
            await s.stop()
        assert s.dropped_paused == 1
        assert db[dao.UNIFIED_LOGS_COLLECTION].docs == []


    asyncio.run(_inner())
def test_set_runtime_pause_overrides_env(monkeypatch):
    dao._reset_backend_shipper_for_tests()
    monkeypatch.delenv("LOGS_PAUSED", raising=False)
    assert dao._logs_paused_env() is False
    dao.set_runtime_pause(True)
    assert dao._logs_paused_env() is True
    dao.set_runtime_pause(None)
    assert dao._logs_paused_env() is False
