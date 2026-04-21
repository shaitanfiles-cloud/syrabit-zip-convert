"""Task #594 — backend tests for the Phase 3 study surfaces.

Coverage:
  * Pure helpers: ``_sm2_step`` (SM-2 scheduling math), ``_split_front_back``
    (notebook → flashcard heuristic), ``_norm_tags``, ``_coerce_quiz_payload``.
  * Route ``POST /edu/quiz/generate`` — happy path with mocked LLM,
    parser tolerance for fenced JSON, validation rejection of malformed
    questions, rate-limiter cap.
  * Route ``GET /edu/notes`` (search) and ``GET /edu/notes/export`` (md/csv)
    against a fake asyncpg pool so we exercise the real SQL parameter
    plumbing without standing up Postgres.
  * Route ``POST /edu/guardian/pin/verify`` — exercises the Task #594
    rate limiter (8 attempts per 5 min) so a brute-force attacker can't
    walk the 10⁴ PIN space in seconds.
"""
from __future__ import annotations

import os
import sys
import time
import asyncio
import pathlib
import importlib
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# Pin backend root on sys.path so ``import deps`` etc. resolve.
_BACKEND = pathlib.Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# ───────────────────────── Fake asyncpg pool ─────────────────────────

class _FakeConn:
    """Minimal AsyncConnection stand-in. Each method records the SQL it
    was handed plus the args, and returns whatever the fixture pre-loaded
    in ``self._responses`` (a list, FIFO)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # list[(method, sql, args)]

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return self._next("execute")

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._next("fetch")

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._next("fetchrow")

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._next("fetchval")

    def transaction(self):
        # used by /edu/sync/claim; not exercised here but harmless
        conn = self
        class _T:
            async def __aenter__(self_inner):
                return conn
            async def __aexit__(self_inner, *a):
                return False
        return _T()

    def _next(self, _method):
        if not self._responses:
            return None
        return self._responses.pop(0)


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn
        class _Cm:
            async def __aenter__(self):
                return conn
            async def __aexit__(self, *a):
                return False
        return _Cm()


@pytest.fixture
def fake_conn_factory():
    """Returns a builder that takes a ``responses`` list and patches
    ``deps.pg_pool`` with a pool acquiring a recording fake conn."""
    saved = []

    def _build(responses):
        # Bypass _ensure_schema's schema bootstrap by pre-marking it ready.
        from routes import edu_study
        edu_study._SCHEMA_READY = True
        conn = _FakeConn(responses)
        import deps
        deps.pg_pool = _FakePool(conn)
        saved.append(deps)
        return conn

    yield _build
    for d in saved:
        d.pg_pool = None


# ───────────────────────── App fixture ─────────────────────────

@pytest.fixture
def edu_app():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.edu_study import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


# ───────────────────────── Pure helpers ─────────────────────────

def test_sm2_failed_recall_resets_progress():
    """A grade < 3 must reset reps to 0 and schedule the card for tomorrow
    (interval=1) — this is the "Again" pile in the UI."""
    from routes.edu_study import _sm2_step
    ef, reps, interval = _sm2_step(ef=2.5, reps=4, interval=15, q=2)
    assert reps == 0
    assert interval == 1
    # EF must drop on a lapse but never below the 1.3 floor.
    assert 1.3 <= ef <= 2.4


def test_sm2_easiness_floor_holds():
    """Repeated failures cannot push EF below 1.3 — the SM-2 spec floor."""
    from routes.edu_study import _sm2_step
    ef = 2.5
    for _ in range(20):
        ef, _r, _i = _sm2_step(ef, 0, 1, 0)
    assert ef == pytest.approx(1.3)


def test_sm2_first_two_reviews_use_canonical_intervals():
    """First successful review → 1 day. Second → 6 days. Third onward →
    interval * EF (rounded)."""
    from routes.edu_study import _sm2_step
    ef1, reps1, int1 = _sm2_step(ef=2.5, reps=0, interval=0, q=4)
    assert reps1 == 1 and int1 == 1
    ef2, reps2, int2 = _sm2_step(ef=ef1, reps=reps1, interval=int1, q=4)
    assert reps2 == 2 and int2 == 6
    ef3, reps3, int3 = _sm2_step(ef=ef2, reps=reps2, interval=int2, q=4)
    assert reps3 == 3
    assert int3 == round(int2 * ef2)


def test_split_front_back_handles_definition_pattern():
    from routes.edu_study import _split_front_back
    f, b = _split_front_back("Photosynthesis — process by which plants make food")
    assert f == "Photosynthesis"
    assert "process by which plants make food" in b


def test_split_front_back_falls_back_to_first_sentence():
    from routes.edu_study import _split_front_back
    f, b = _split_front_back("Mitochondria are the powerhouse of the cell. They make ATP.")
    assert f == "Recall this idea:"
    assert "powerhouse" in b


def test_norm_tags_dedupes_lowercases_caps_at_twelve():
    from routes.edu_study import _norm_tags
    tags = _norm_tags(["Bio", "bio", "  Genetics ", "DNA replication"] + [f"x{i}" for i in range(20)])
    assert "bio" in tags
    assert tags.count("bio") == 1
    assert "genetics" in tags
    assert "dna-replication" in tags
    assert len(tags) <= 12


def test_coerce_quiz_payload_strips_code_fences():
    from routes.edu_study import _coerce_quiz_payload
    raw = """Some preamble
```json
{"questions": [{"q": "1?", "choices": ["a","b","c","d"], "answer": 0}]}
```
trailing chatter"""
    out = _coerce_quiz_payload(raw)
    assert out["questions"][0]["q"] == "1?"


def test_coerce_quiz_payload_raises_on_garbage():
    from fastapi import HTTPException
    from routes.edu_study import _coerce_quiz_payload
    with pytest.raises(HTTPException) as exc:
        _coerce_quiz_payload("definitely not json at all")
    assert exc.value.status_code == 502


# ───────────────────────── /edu/quiz/generate ─────────────────────────

_GOOD_LLM = (
    '{"questions": ['
    '  {"q":"What is 2+2?","choices":["3","4","5","6"],"answer":1,"explanation":"Basic addition."},'
    '  {"q":"Capital of France?","choices":["Berlin","Madrid","Paris","Rome"],"answer":2,"explanation":"Paris is the capital."},'
    '  {"q":"H2O is?","choices":["Water","Oil","Acid","Salt"],"answer":0,"explanation":"H2O is water."}'
    ']}'
)


def test_quiz_generate_returns_cleaned_questions(edu_app):
    with patch("routes.edu_study.call_llm_api", new=AsyncMock(return_value=_GOOD_LLM)):
        res = edu_app.post("/api/edu/quiz/generate", json={
            "context": "Some chapter text about basic facts." * 5,
            "topic": "General knowledge",
            "count": 3,
        })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["count"] == 3
    qs = body["questions"]
    assert qs[0]["choices"] == ["3", "4", "5", "6"]
    assert qs[0]["answer"] == 1
    # Each cleaned question gets a stable id assigned server-side.
    assert all(isinstance(q["id"], str) and q["id"] for q in qs)


def test_quiz_generate_drops_questions_with_wrong_choice_count(edu_app):
    """The LLM occasionally returns 3 or 5 choices. The route must skip
    those entries instead of returning a malformed payload (which would
    crash the front-end MCQ UI)."""
    bad = (
        '{"questions": ['
        '  {"q":"only three?","choices":["a","b","c"],"answer":0},'
        '  {"q":"good one","choices":["a","b","c","d"],"answer":3,"explanation":"d wins"}'
        ']}'
    )
    with patch("routes.edu_study.call_llm_api", new=AsyncMock(return_value=bad)):
        res = edu_app.post("/api/edu/quiz/generate", json={
            "context": "Lorem ipsum dolor sit amet " * 10,
            "count": 3,
        })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 1
    assert body["questions"][0]["q"] == "good one"
    assert body["questions"][0]["answer"] == 3


def test_quiz_generate_clamps_out_of_range_answer_index(edu_app):
    """If the LLM returns ``answer: 7`` for a 4-choice MCQ, the route
    must clamp to 0 rather than render an unscoreable question."""
    bad = (
        '{"questions": ['
        '  {"q":"x?","choices":["a","b","c","d"],"answer":7,"explanation":""}'
        ']}'
    )
    with patch("routes.edu_study.call_llm_api", new=AsyncMock(return_value=bad)):
        res = edu_app.post("/api/edu/quiz/generate", json={
            "context": "ctx " * 30, "count": 3,
        })
    assert res.status_code == 200
    assert res.json()["questions"][0]["answer"] == 0


def test_quiz_generate_rejects_empty_request(edu_app):
    res = edu_app.post("/api/edu/quiz/generate", json={"count": 3})
    assert res.status_code == 400
    assert res.json()["detail"] == "context or topic required"


def test_quiz_generate_returns_502_when_llm_returns_no_valid_questions(edu_app):
    """When every question in the LLM payload fails validation, the
    route must surface a 502 instead of returning an empty list (which
    the frontend would render as "0 / 0", a confusing dead-end)."""
    bad = '{"questions": [{"q":"x","choices":["a","b","c"],"answer":0}]}'
    with patch("routes.edu_study.call_llm_api", new=AsyncMock(return_value=bad)):
        res = edu_app.post("/api/edu/quiz/generate", json={
            "context": "ctx " * 30, "count": 3,
        })
    assert res.status_code == 502
    assert res.json()["detail"] == "quiz_no_questions"


def test_quiz_generate_rate_limiter_caps_at_15_per_5_min(edu_app):
    """The route allows 15 quiz requests per IP per 5 minutes. The 16th
    must 429 — guards against an unbounded LLM bill from a single
    misbehaving client."""
    from auth_deps import _rate_windows
    _rate_windows.clear()
    with patch("routes.edu_study.call_llm_api", new=AsyncMock(return_value=_GOOD_LLM)):
        for _ in range(15):
            r = edu_app.post("/api/edu/quiz/generate",
                             json={"context": "abc " * 30, "count": 3})
            assert r.status_code == 200
        r = edu_app.post("/api/edu/quiz/generate",
                         json={"context": "abc " * 30, "count": 3})
    assert r.status_code == 429


# ───────────────────────── /edu/notes (search + export) ─────────────────────────

def _make_note_row(idx, text="hello world", tags=None, source_title="Source",
                   source_url="https://example.org/x", chapter_ref="ch-1"):
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return {
        "id": f"note-{idx}",
        "actor_kind": "anon",
        "actor": "ip:abc",
        "text": text,
        "source_url": source_url,
        "source_title": source_title,
        "chapter_ref": chapter_ref,
        "tags": list(tags or []),
        "created_at": now,
        "updated_at": now,
    }


def test_notes_search_passes_q_and_tag_filters(edu_app, fake_conn_factory):
    rows = [_make_note_row(1, text="photosynthesis", tags=["bio"]),
            _make_note_row(2, text="photo basics",   tags=["bio"])]
    conn = fake_conn_factory(responses=[rows])

    res = edu_app.get("/api/edu/notes?q=photo&tag=bio&limit=50")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 2
    assert {n["id"] for n in body["notes"]} == {"note-1", "note-2"}

    # The route must have driven its SQL with the user's q + tag filters
    # AND the limit/offset args. Catching a regression here is the
    # whole point of this test — a bug in the parametrised SQL builder
    # would silently return the wrong rows.
    sql, args = conn.calls[-1][1], conn.calls[-1][2]
    assert "ILIKE" in sql
    assert "tags &&" in sql
    assert "%photo%" in args
    assert ["bio"] in args
    assert 50 in args
    assert 0 in args


def test_notes_export_csv_streams_attachment(edu_app, fake_conn_factory):
    rows = [
        _make_note_row(1, text="note one", tags=["bio", "exam"],
                       source_title="Chapter 1", source_url="https://e/1"),
        _make_note_row(2, text="note two", tags=[],
                       source_title="", source_url=""),
    ]
    fake_conn_factory(responses=[rows])

    res = edu_app.get("/api/edu/notes/export?format=csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "syrabit-notebook.csv" in res.headers["content-disposition"]
    body = res.text
    assert "note one" in body
    assert "note two" in body
    # Tags must be joined with commas in the CSV cell.
    assert "bio,exam" in body
    # Header row.
    assert body.splitlines()[0].startswith("created_at,text,")


def test_notes_export_md_default(edu_app, fake_conn_factory):
    rows = [_make_note_row(1, text="markdown body", tags=["alpha"])]
    fake_conn_factory(responses=[rows])

    res = edu_app.get("/api/edu/notes/export")  # no format → md
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")
    body = res.text
    assert body.startswith("# Syrabit Notebook")
    assert "markdown body" in body
    assert "`alpha`" in body  # tag rendered as inline code


# ───────────────────────── /edu/guardian/pin/verify rate limit ─────────────────────────

def _patch_no_pin_set():
    """Patch deps.pg_pool so pin/verify thinks no PIN is set — the route
    will then return ``valid=True, set=False`` very fast, letting us
    pound on it without other DB-related noise."""
    import deps
    from routes import edu_study
    edu_study._SCHEMA_READY = True
    conn = _FakeConn(responses=[None] * 100)  # fetchrow always returns None
    deps.pg_pool = _FakePool(conn)
    return conn


def test_pin_verify_rate_limit_after_eight_attempts(edu_app):
    """Task #594: PIN verify is capped at 8 attempts per 5 min per actor.
    The 9th attempt must 429 — without this, an attacker could brute the
    10⁴ PIN space in a few seconds."""
    from auth_deps import _rate_windows
    _rate_windows.clear()
    _patch_no_pin_set()

    headers = {"x-anon-id": "device-attacker-1"}
    for i in range(8):
        r = edu_app.post("/api/edu/guardian/pin/verify",
                         json={"pin": f"{1000 + i}"}, headers=headers)
        assert r.status_code == 200, f"attempt {i} got {r.status_code}: {r.text}"

    blocked = edu_app.post("/api/edu/guardian/pin/verify",
                           json={"pin": "9999"}, headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "pin_verify_rate_limited"


def test_pin_verify_rate_limit_is_per_actor(edu_app):
    """A different anon device id gets its own bucket — one attacker
    must not lock out another guardian on a shared NAT."""
    from auth_deps import _rate_windows
    _rate_windows.clear()
    _patch_no_pin_set()

    h1 = {"x-anon-id": "device-A"}
    h2 = {"x-anon-id": "device-B"}
    for _ in range(8):
        edu_app.post("/api/edu/guardian/pin/verify",
                     json={"pin": "1234"}, headers=h1)
    blocked = edu_app.post("/api/edu/guardian/pin/verify",
                           json={"pin": "1234"}, headers=h1)
    assert blocked.status_code == 429

    # Second device starts fresh.
    fresh = edu_app.post("/api/edu/guardian/pin/verify",
                         json={"pin": "1234"}, headers=h2)
    assert fresh.status_code == 200
