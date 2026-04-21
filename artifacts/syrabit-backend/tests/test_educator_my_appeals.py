"""Tests for GET /api/edu/educator/my-appeals (Task #623).

Cross-references ``EDU_REQUESTED_SITES_COLLECTION`` (where an
educator's appeals live) with ``EDU_ALLOWLIST_COLLECTION`` (where the
admin's verdict lands). We verify:
  * only appeals matching the calling educator's actor are returned
  * status is 'allowed' when a matching allow-override exists
  * status is 'pending' when no override is found and not dismissed
  * status is 'dismissed' when the admin has soft-deleted the row
    (``dismissed=true`` + ``dismissed_at`` timestamp) — Task #623
    closes the loop by surfacing the verdict instead of silently
    dropping the row
  * 'allowed' wins over 'dismissed' if an admin changes their mind
  * mongo outage / missing actor collapses to an empty list
  * non-educator callers get 403
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _app(monkeypatch, *, educator_user, appeals_rows=None, overrides=None,
         mongo_ok=True):
    from auth_deps import get_educator_user
    from routes import edu_browser as eb

    async def fake_mongo_available():
        return mongo_ok
    monkeypatch.setattr(eb, "is_mongo_available", fake_mongo_available)

    class _Cursor:
        def __init__(self, rows):
            self._rows = list(rows or [])
        def sort(self, *_a, **_kw): return self
        def limit(self, *_a, **_kw): return self
        def __aiter__(self):
            async def gen():
                for r in self._rows:
                    yield r
            return gen()

    class FakeAppealsColl:
        def find(self, flt, *_a, **_kw):
            # Filter must match {source=educator_appeal, last_actor=<actor>}.
            assert flt.get("source") == "educator_appeal"
            rows = [
                r for r in (appeals_rows or [])
                if r.get("last_actor") == flt.get("last_actor")
            ]
            return _Cursor(rows)

    class FakeAllowlistColl:
        async def find_one(self, flt, *_a, **_kw):
            for doc in (overrides or []):
                if doc.get("domain") == flt.get("domain"):
                    return doc
            return None

    class FakeDB:
        def __getitem__(self, key):
            if key == "edu_requested_sites":
                return FakeAppealsColl()
            if key == "edu_allowlist":
                return FakeAllowlistColl()
            raise KeyError(key)
    monkeypatch.setattr(eb, "db", FakeDB())

    app = FastAPI()
    app.include_router(eb.router, prefix="/api")
    if educator_user is not None:
        app.dependency_overrides[get_educator_user] = lambda: educator_user
    else:
        def _deny():
            raise HTTPException(status_code=403, detail="educator_required")
        app.dependency_overrides[get_educator_user] = _deny
    return TestClient(app)


def test_my_appeals_returns_all_three_verdict_states(monkeypatch):
    educator = {"id": "e1", "email": "ms.barua@school.in", "role": "educator"}
    # Three appeals by this educator (one per verdict state) plus one
    # by someone else that must be filtered out.
    appeals = [
        {"domain": "approved.org", "last_actor": "ms.barua@school.in",
         "last_appeal_at": 1_700_000_100, "appeal_count": 1,
         "last_probe": {"reason": "robots_disallow"}},
        {"domain": "still-pending.org", "last_actor": "ms.barua@school.in",
         "last_appeal_at": 1_700_000_050, "appeal_count": 2,
         "last_probe": {"reason": "unsafe_content"}},
        {"domain": "rejected.org", "last_actor": "ms.barua@school.in",
         "last_appeal_at": 1_700_000_030, "appeal_count": 1,
         "last_probe": {"reason": "robots_disallow"},
         "dismissed": True, "dismissed_at": 1_700_002_000},
        {"domain": "not-mine.org", "last_actor": "someone-else@x.com",
         "last_appeal_at": 1_700_000_200, "appeal_count": 1,
         "last_probe": {}},
    ]
    overrides = [
        {"domain": "approved.org", "status": "allowed", "updated_at": 1_700_001_000},
    ]
    client = _app(monkeypatch, educator_user=educator,
                  appeals_rows=appeals, overrides=overrides)
    r = client.get("/api/edu/educator/my-appeals")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    items = body["items"]
    # someone-else@x.com's appeal must not leak in
    assert all(i["domain"] != "not-mine.org" for i in items)
    by_domain = {i["domain"]: i for i in items}
    # Allowed verdict
    assert by_domain["approved.org"]["status"] == "allowed"
    assert by_domain["approved.org"]["verdict_at"] == 1_700_001_000
    # Pending (no override, not dismissed)
    assert by_domain["still-pending.org"]["status"] == "pending"
    assert by_domain["still-pending.org"]["verdict_at"] is None
    # Dismissed (soft-delete flag) — Task #623 closes the loop
    assert by_domain["rejected.org"]["status"] == "dismissed"
    assert by_domain["rejected.org"]["verdict_at"] == 1_700_002_000
    # Probe snapshot carried through so the educator can remember
    # which rejection each appeal corresponds to.
    assert by_domain["still-pending.org"]["last_probe"]["reason"] == "unsafe_content"
    assert by_domain["rejected.org"]["last_probe"]["reason"] == "robots_disallow"


def test_my_appeals_allow_wins_over_dismiss(monkeypatch):
    # Admin dismissed an appeal, then later changed their mind and
    # allowed the domain. The "allowed" verdict should win so the
    # educator doesn't see stale "dismissed" UI.
    educator = {"id": "e1", "email": "ms.barua@school.in", "role": "educator"}
    appeals = [
        {"domain": "reversed.org", "last_actor": "ms.barua@school.in",
         "last_appeal_at": 1_700_000_100, "appeal_count": 1,
         "dismissed": True, "dismissed_at": 1_700_001_000},
    ]
    overrides = [
        {"domain": "reversed.org", "status": "allowed",
         "updated_at": 1_700_002_000},
    ]
    client = _app(monkeypatch, educator_user=educator,
                  appeals_rows=appeals, overrides=overrides)
    r = client.get("/api/edu/educator/my-appeals")
    body = r.json()
    item = body["items"][0]
    assert item["status"] == "allowed"
    assert item["verdict_at"] == 1_700_002_000


def test_my_appeals_empty_when_no_actor(monkeypatch):
    # Educator record with no email/id → cannot scope the query, so
    # the endpoint returns an empty list rather than leaking every
    # educator_appeal row.
    client = _app(monkeypatch, educator_user={"role": "educator"})
    r = client.get("/api/edu/educator/my-appeals")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "items": [], "count": 0}


def test_my_appeals_empty_when_mongo_unavailable(monkeypatch):
    client = _app(
        monkeypatch,
        educator_user={"id": "e1", "email": "x@y.z", "role": "educator"},
        mongo_ok=False,
    )
    r = client.get("/api/edu/educator/my-appeals")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "items": [], "count": 0}


def test_my_appeals_requires_educator_role(monkeypatch):
    client = _app(monkeypatch, educator_user=None)
    r = client.get("/api/edu/educator/my-appeals")
    assert r.status_code == 403


# ── admin dismiss soft-delete behaviour (Task #623) ─────────────────────
#
# The admin DELETE /admin/edu/requested-sites/<domain> used to hard-delete
# every row. Task #623 changes that to a **soft-delete** for rows with
# source=educator_appeal (so the educator can see `status=dismissed` on
# /my-appeals) while keeping the hard-delete for plain /request-site
# submissions (where no educator is waiting on a verdict).


def _admin_app(monkeypatch, *, existing_row, capture):
    from auth_deps import get_admin_user
    from routes import edu_browser as eb

    async def fake_mongo_available():
        return True
    monkeypatch.setattr(eb, "is_mongo_available", fake_mongo_available)

    class FakeColl:
        async def find_one(self, flt, *_a, **_kw):
            return existing_row
        async def update_one(self, flt, update, **_kw):
            capture["update"] = {"filter": flt, "update": update}
            class R: modified_count = 1
            return R()
        async def delete_one(self, flt, **_kw):
            capture["delete"] = {"filter": flt}
            class R: deleted_count = 1
            return R()

    class FakeDB:
        def __getitem__(self, key):
            return FakeColl()
    monkeypatch.setattr(eb, "db", FakeDB())

    app = FastAPI()
    app.include_router(eb.router, prefix="/api")
    app.dependency_overrides[get_admin_user] = lambda: {"id": "admin1", "email": "a@x"}
    return TestClient(app)


def test_admin_dismiss_soft_deletes_educator_appeal(monkeypatch):
    cap = {}
    client = _admin_app(
        monkeypatch,
        existing_row={"domain": "appealed.org", "source": "educator_appeal"},
        capture=cap,
    )
    r = client.delete("/api/admin/edu/requested-sites/appealed.org")
    assert r.status_code == 200, r.text
    # Must have flipped the soft-delete flag, NOT hard-deleted
    assert "update" in cap
    assert cap["update"]["filter"] == {"domain": "appealed.org"}
    upd = cap["update"]["update"]["$set"]
    assert upd["dismissed"] is True
    assert isinstance(upd["dismissed_at"], float)
    assert "delete" not in cap


def test_admin_dismiss_hard_deletes_plain_request(monkeypatch):
    cap = {}
    client = _admin_app(
        monkeypatch,
        # A plain user /request-site row (no `source=educator_appeal`)
        existing_row={"domain": "random.org", "source": ""},
        capture=cap,
    )
    r = client.delete("/api/admin/edu/requested-sites/random.org")
    assert r.status_code == 200
    # No educator is waiting on a verdict → hard delete is fine
    assert "delete" in cap
    assert cap["delete"]["filter"] == {"domain": "random.org"}
    assert "update" not in cap
