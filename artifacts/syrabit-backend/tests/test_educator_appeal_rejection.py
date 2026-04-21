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
         capture=None, has_proof=True):
    from auth_deps import get_educator_user
    from routes import edu_browser as eb

    async def fake_is_hard_blocked(domain):
        return hard_block
    monkeypatch.setattr(eb, "is_domain_hard_blocked", fake_is_hard_blocked)

    async def fake_mongo_available():
        return mongo_ok
    monkeypatch.setattr(eb, "is_mongo_available", fake_mongo_available)

    # Task #624 proof gate — tests default to True (behaves like
    # redis-down fail-open) so existing happy-path tests stay green.
    monkeypatch.setattr(eb, "_has_appeal_proof", lambda _e, _d: bool(has_proof))

    class FakeColl:
        async def update_one(self, flt, update, upsert=False):
            # Only capture the upsert write (the appeal insert); the
            # Task #625 post-upsert spike-claim call is a non-upsert
            # update_one and would otherwise clobber captures of the
            # original appeal write.
            if capture is not None and upsert:
                capture["filter"] = flt
                capture["update"] = update
                capture["upsert"] = upsert
            class R:
                modified_count = 0
            return R()

        async def find_one(self, _flt, _proj=None):
            return None

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


# ── Task #624: proof-of-prior-rejection contract ─────────────────────────
#
# /educator/appeal-rejection must refuse domains the calling educator
# never probed via /educator/submit-site. The contract is enforced by
# a 1-hour Redis marker written on probe failure; the appeal endpoint
# rejects with HTTP 400 + a clear "no_recent_rejection" detail if
# the marker is missing.


def test_educator_appeal_without_proof_is_rejected(monkeypatch):
    # has_proof=False simulates the attacker case: educator calls the
    # appeal endpoint directly without ever hitting the rejection card
    # in the UI.
    client = _app(
        monkeypatch,
        educator_user={"id": "proof-negative", "email": "noproof@school.in",
                       "role": "educator"},
        has_proof=False,
    )
    r = client.post("/api/edu/educator/appeal-rejection", json={
        "domain": "never-probed.org",
        "probe": {},
    })
    assert r.status_code == 400, r.text
    assert "no_recent_rejection" in r.json()["detail"]


def test_appeal_proof_helpers_round_trip(monkeypatch):
    """Unit-level check that the Redis-backed proof write/read pair
    sees each other when a fake redis_client is installed — guards
    against accidentally regressing the key format."""
    from routes import edu_browser as eb
    import deps

    class FakeRedis:
        def __init__(self):
            self.store = {}
        def set(self, k, v, ex=None):
            self.store[k] = v
        def get(self, k):
            return self.store.get(k)

    fake = FakeRedis()
    monkeypatch.setattr(deps, "redis_client", fake)

    assert eb._has_appeal_proof("edu1", "x.org") is False
    eb._record_appeal_proof("edu1", "x.org", "robots_disallow")
    assert eb._has_appeal_proof("edu1", "x.org") is True
    # Proof is scoped per-educator
    assert eb._has_appeal_proof("other-edu", "x.org") is False
    # …and per-domain
    assert eb._has_appeal_proof("edu1", "other.org") is False


def test_appeal_proof_fail_open_when_redis_unavailable(monkeypatch):
    """Documents and locks in the deliberate availability tradeoff:
    when Redis is not configured / unreachable, _has_appeal_proof
    returns True so legitimate educators aren't trapped behind a
    verification step they cannot satisfy. If this behaviour is ever
    tightened to fail-closed, this test must be updated alongside
    the policy change."""
    from routes import edu_browser as eb
    import deps

    monkeypatch.setattr(deps, "redis_client", None)
    assert eb._has_appeal_proof("edu1", "x.org") is True
    # Writing is a no-op but must not raise.
    eb._record_appeal_proof("edu1", "x.org", "robots_disallow")

    class BrokenRedis:
        def get(self, _k):
            raise RuntimeError("redis exploded")
        def set(self, *_a, **_kw):
            raise RuntimeError("redis exploded")
    monkeypatch.setattr(deps, "redis_client", BrokenRedis())
    # Errors also degrade to fail-open rather than trap the user.
    assert eb._has_appeal_proof("edu1", "x.org") is True
    eb._record_appeal_proof("edu1", "x.org", "robots_disallow")  # swallowed


# ── Task #625: appeal-spike alerting ─────────────────────────────────────
#
# Once _APPEAL_SPIKE_THRESHOLD educators have appealed the same
# domain, an admin-facing alert should fire exactly once per spike
# cycle. A subsequent dismiss → re-appeal cycle must re-arm the alert
# so a second spike on the same domain re-fires.


def _spike_app(monkeypatch, *, rows, alert_calls, prior_dismissed=False):
    """Harness for the appeal endpoint with a FakeDB that simulates
    the appeal_count / alerted_at lifecycle in-memory so we can
    exercise the conditional `_maybe_alert_appeal_spike` update."""
    from auth_deps import get_educator_user
    from routes import edu_browser as eb

    async def fake_is_hard_blocked(_d):
        return (False, "ok")
    monkeypatch.setattr(eb, "is_domain_hard_blocked", fake_is_hard_blocked)

    async def fake_mongo_available():
        return True
    monkeypatch.setattr(eb, "is_mongo_available", fake_mongo_available)
    monkeypatch.setattr(eb, "_has_appeal_proof", lambda _e, _d: True)

    state = {"row": dict(rows) if rows else None, "dismissed_before": prior_dismissed}

    class FakeColl:
        async def find_one(self, flt, proj=None):
            row = state["row"]
            if not row:
                return None
            # The spike-check find_one projects appeal_count after the
            # conditional update; simulate by returning a copy.
            return dict(row)

        async def update_one(self, flt, update, upsert=False):
            # Upsert path (the appeal insert): apply $inc + $set.
            class R:
                modified_count = 0
            if upsert:
                row = state["row"] or {"domain": flt.get("domain")}
                for k, v in (update.get("$inc") or {}).items():
                    row[k] = int(row.get(k) or 0) + v
                for k, v in (update.get("$set") or {}).items():
                    row[k] = v
                state["row"] = row
                R.modified_count = 1
                return R()
            # Conditional claim: mimic the MongoDB predicate so we can
            # check exactly-once semantics.
            row = state["row"] or {}
            appeal_count = int(row.get("appeal_count") or 0)
            alerted = row.get("alerted_at")
            dismissed = bool(row.get("dismissed"))
            threshold = (flt.get("appeal_count") or {}).get("$gte", 0)
            if (
                row.get("domain") == flt.get("domain")
                and appeal_count >= threshold
                and not dismissed
                and (alerted is None)
            ):
                for k, v in (update.get("$set") or {}).items():
                    row[k] = v
                state["row"] = row
                R.modified_count = 1
            return R()

    class FakeDB(dict):
        def __getitem__(self, _k):
            return FakeColl()
    monkeypatch.setattr(eb, "db", FakeDB())

    # Capture spike alerts synchronously — avoids having to await the
    # fire-and-forget asyncio task.
    def fake_spawn(domain, count):
        alert_calls.append((domain, count))
    monkeypatch.setattr(eb, "_spawn_appeal_spike_alert", fake_spawn)

    app = FastAPI()
    app.include_router(eb.router, prefix="/api")
    app.dependency_overrides[get_educator_user] = lambda: {
        "id": "spike-educator", "email": "spike@school.in", "role": "educator",
    }
    return TestClient(app), state


def _post_appeal(client, domain="popular-edu.org"):
    return client.post("/api/edu/educator/appeal-rejection", json={
        "domain": domain, "reason": "Probe glitched",
        "probe": {"reason": "robots_disallow"},
    })


def test_appeal_spike_fires_once_at_threshold(monkeypatch):
    alerts: list = []
    # Row already has 4 appeals — this 5th appeal crosses the threshold.
    client, state = _spike_app(monkeypatch, rows={
        "domain": "popular-edu.org", "appeal_count": 4, "alerted_at": None,
    }, alert_calls=alerts)
    r = _post_appeal(client)
    assert r.status_code == 200, r.text
    # Exactly one alert for a threshold-crossing write.
    assert len(alerts) == 1, alerts
    assert alerts[0][0] == "popular-edu.org"
    assert alerts[0][1] >= 5
    # alerted_at is now claimed.
    assert state["row"].get("alerted_at") is not None


def test_appeal_spike_does_not_refire_while_claimed(monkeypatch):
    alerts: list = []
    # Already alerted at count=5; a 6th appeal must NOT re-fire.
    client, state = _spike_app(monkeypatch, rows={
        "domain": "popular-edu.org", "appeal_count": 5, "alerted_at": 12345.0,
    }, alert_calls=alerts)
    r = _post_appeal(client)
    assert r.status_code == 200, r.text
    assert alerts == []
    # alerted_at timestamp is preserved (not bumped every appeal).
    assert state["row"].get("alerted_at") == 12345.0


def test_appeal_spike_below_threshold_does_not_fire(monkeypatch):
    alerts: list = []
    # Row at 3 appeals — 4th is still below threshold (5), no alert.
    client, _state = _spike_app(monkeypatch, rows={
        "domain": "quiet-edu.org", "appeal_count": 3, "alerted_at": None,
    }, alert_calls=alerts)
    r = _post_appeal(client, domain="quiet-edu.org")
    assert r.status_code == 200, r.text
    assert alerts == []


def test_appeal_spike_rearms_after_dismiss_reappeal(monkeypatch):
    # Row was previously dismissed after an earlier spike (alerted_at
    # set, dismissed=True). A fresh appeal must clear alerted_at via
    # the prior-dismissed branch so the next threshold crossing fires
    # again.
    alerts: list = []
    client, state = _spike_app(monkeypatch, rows={
        "domain": "popular-edu.org",
        "appeal_count": 7,
        "alerted_at": 100.0,
        "dismissed": True,
    }, alert_calls=alerts)
    r = _post_appeal(client)
    assert r.status_code == 200, r.text
    # After re-appeal, the row is un-dismissed AND alerted_at has
    # been cleared then re-claimed because count (8) still >= 5.
    assert state["row"]["dismissed"] is False
    assert state["row"].get("alerted_at") is not None
    assert state["row"].get("alerted_at") != 100.0
    assert len(alerts) == 1, alerts


def test_appeal_spike_webhook_body_contains_domain(monkeypatch):
    """When EDU_APPEAL_ALERT_WEBHOOK is set, _spawn posts a message
    that mentions the spiking domain and count — the observable
    effect an admin watching Slack would actually see."""
    import routes.edu_browser as eb

    posted: list = []

    async def fake_post(url, text):
        posted.append((url, text))
    monkeypatch.setattr(eb, "_post_slack_webhook", fake_post)
    monkeypatch.setenv("EDU_APPEAL_ALERT_WEBHOOK", "https://hooks.example/x")
    monkeypatch.delenv("EDU_APPEAL_ALERT_ADMIN_URL", raising=False)

    # Drive via a dedicated loop so we don't disturb the default
    # event loop other tests rely on (asyncio.run() closes and
    # detaches the main-thread loop, which breaks sibling tests
    # that call asyncio.get_event_loop()).
    import asyncio as _aio

    async def _drive():
        eb._spawn_appeal_spike_alert("popular-edu.org", 6)
        # Let the spawned task run to completion.
        await _aio.sleep(0)

    prev_loop = None
    try:
        prev_loop = _aio.get_event_loop()
    except RuntimeError:
        prev_loop = None
    loop = _aio.new_event_loop()
    try:
        _aio.set_event_loop(loop)
        loop.run_until_complete(_drive())
    finally:
        loop.close()
        _aio.set_event_loop(prev_loop)
    assert posted, "webhook should have been posted"
    url, text = posted[0]
    assert url == "https://hooks.example/x"
    assert "popular-edu.org" in text
    assert "6" in text


def test_appeal_spike_webhook_skipped_when_env_unset(monkeypatch):
    """No Slack env → no webhook POST, but no crash either. Admins
    still get the banner via the `alerted_at` field."""
    import routes.edu_browser as eb

    posted: list = []

    async def fake_post(url, text):
        posted.append((url, text))
    monkeypatch.setattr(eb, "_post_slack_webhook", fake_post)
    monkeypatch.delenv("EDU_APPEAL_ALERT_WEBHOOK", raising=False)

    eb._spawn_appeal_spike_alert("popular-edu.org", 6)
    assert posted == []
