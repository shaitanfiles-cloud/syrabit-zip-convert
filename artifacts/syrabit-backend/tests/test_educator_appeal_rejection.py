"""Tests for POST /api/edu/educator/appeal-rejection.

The endpoint lets an educator escalate a probe rejection to admin
review by inserting/updating an entry in
``EDU_REQUESTED_SITES_COLLECTION`` with ``source=educator_appeal``
and a snapshot of the probe outcome they saw. We verify:
  * happy path stores the probe snapshot + actor
  * non-educator users cannot reach the endpoint
  * hard-blocked domains are not appealable (403)
  * storage outage surfaces as 503
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _app(monkeypatch, *, educator_user, mongo_ok=True, hard_block=(False, "ok"),
         capture=None):
    from auth_deps import get_educator_user
    from routes import edu_browser as eb

    async def fake_is_hard_blocked(domain):
        return hard_block
    monkeypatch.setattr(eb, "is_domain_hard_blocked", fake_is_hard_blocked)

    async def fake_mongo_available():
        return mongo_ok
    monkeypatch.setattr(eb, "is_mongo_available", fake_mongo_available)

    class FakeColl:
        async def update_one(self, flt, update, upsert=False):
            if capture is not None:
                capture["filter"] = flt
                capture["update"] = update
                capture["upsert"] = upsert
            class R: ...
            return R()

    class FakeDB(dict):
        def __getitem__(self, key):
            return FakeColl()
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


def test_educator_appeal_happy_path(monkeypatch):
    captured = {}
    client = _app(
        monkeypatch,
        educator_user={"id": "e1", "email": "ms.barua@school.in", "role": "educator"},
        capture=captured,
    )
    r = client.post("/api/edu/educator/appeal-rejection", json={
        "domain": "EXAMPLE-edu.org",
        "reason": "Used in chapter 4 grade 9 — robots.txt was a glitch yesterday",
        "probe": {
            "reason": "robots_disallow",
            "kid_safe": True,
            "kid_safe_density": 0.0,
            "robots_ok": False,
            "http_status": None,
        },
        "probe_error": "robots_disallow",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "queued"
    assert body["domain"] == "example-edu.org"
    assert body["source"] == "educator_appeal"

    upd = captured["update"]
    assert captured["upsert"] is True
    assert upd["$set"]["source"] == "educator_appeal"
    assert upd["$set"]["appeal"] is True
    assert upd["$set"]["last_actor"] == "ms.barua@school.in"
    assert upd["$set"]["last_probe"]["reason"] == "robots_disallow"
    assert upd["$set"]["last_probe"]["robots_ok"] is False
    assert upd["$inc"] == {"count": 1, "appeal_count": 1}


def test_educator_reappeal_clears_dismissal(monkeypatch):
    # Regression for Task #623: if admin previously dismissed an appeal
    # (soft-delete), a brand-new appeal on the same domain must CLEAR
    # dismissed / dismissed_at so the row re-enters the admin queue
    # and /my-appeals shows `pending` again instead of staying stuck
    # on "Dismissed by admin".
    captured = {}
    client = _app(
        monkeypatch,
        educator_user={"id": "reappeal-test-user", "email": "reappeal@school.in", "role": "educator"},
        capture=captured,
    )
    r = client.post("/api/edu/educator/appeal-rejection", json={
        "domain": "previously-dismissed.org",
        "reason": "Re-appealing with more context",
        "probe": {"reason": "robots_disallow", "kid_safe": True},
    })
    assert r.status_code == 200, r.text
    set_fields = captured["update"]["$set"]
    assert set_fields["dismissed"] is False
    assert set_fields["dismissed_at"] is None


def test_educator_appeal_rejects_hard_blocked(monkeypatch):
    client = _app(
        monkeypatch,
        educator_user={"id": "e1", "role": "educator"},
        hard_block=(True, "operator_blocked"),
    )
    r = client.post("/api/edu/educator/appeal-rejection",
                    json={"domain": "blocked.example.com"})
    assert r.status_code == 403
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "operator_blocked"


def test_educator_appeal_storage_unavailable(monkeypatch):
    client = _app(
        monkeypatch,
        educator_user={"id": "e1", "role": "educator"},
        mongo_ok=False,
    )
    r = client.post("/api/edu/educator/appeal-rejection",
                    json={"domain": "ok-domain.org"})
    assert r.status_code == 503
    assert r.json()["detail"] == "storage_unavailable"


def test_educator_appeal_rejects_invalid_domain(monkeypatch):
    client = _app(
        monkeypatch,
        educator_user={"id": "e1", "role": "educator"},
    )
    for bad in ["evil.com@169.254.169.254", "host:8080", "no-dot",
                "192.168.1.1", "user:pass@example.com"]:
        r = client.post("/api/edu/educator/appeal-rejection",
                        json={"domain": bad})
        assert r.status_code == 400, f"{bad!r} should 400"


def test_educator_appeal_requires_educator_role(monkeypatch):
    client = _app(monkeypatch, educator_user=None)
    r = client.post("/api/edu/educator/appeal-rejection",
                    json={"domain": "ok-domain.org"})
    assert r.status_code == 403
