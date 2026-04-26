"""Task #937 — unit tests for topic_discovery_service.

Covers the pure / well-isolated pieces of the autonomous topic-discovery
agent so we can refactor with confidence:

* parse_grader_response — JSON extraction + clamping + default-blend
* decide                — threshold tiering + cap demote-to-draft
* _dedupe_candidates    — multi-source merge + sort priority
* collect_*             — Mongo adapter contracts (GSC, suggest, trending)
* run_topic_discovery_once — end-to-end with mocked LLM + suggest, walks
                             dedup → grade → budget cap → enqueue → persist
* apply_override        — promote re-enqueues; reject does not
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

import topic_discovery_service as tds


def _run(coro):
    """Synchronous wrapper — project doesn't ship pytest-asyncio."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── parse_grader_response ─────────────────────────────────────────────


def test_parse_grader_response_strict_json():
    out = tds.parse_grader_response(
        '{"intent_fit": 80, "syllabus_alignment": 90, "difficulty": 70,'
        ' "aeo_readability": 85, "total": 82, "reason": "fits AHSEC"}'
    )
    assert out["intent_fit"] == 80
    assert out["syllabus_alignment"] == 90
    assert out["total"] == 82
    assert out["reason"] == "fits AHSEC"


def test_parse_grader_response_strips_markdown_fence():
    # LLM-reported total is now ignored — parse computes it
    # deterministically from the four axis scores using configured
    # weights (defaults: 0.35*syl + 0.25*intent + 0.20*aeo + 0.20*diff).
    # 0.35*60 + 0.25*50 + 0.20*80 + 0.20*70 = 21 + 12.5 + 16 + 14 = 63.5 → 64
    text = "```json\n{\"intent_fit\":50,\"syllabus_alignment\":60,\"difficulty\":70,\"aeo_readability\":80,\"total\":65,\"reason\":\"ok\"}\n```"
    out = tds.parse_grader_response(text)
    assert out is not None
    assert out["total"] == 64


def test_parse_grader_response_finds_embedded_object():
    # 0.35*20 + 0.25*10 + 0.20*40 + 0.20*30 = 7 + 2.5 + 8 + 6 = 23.5 → 24
    text = "Sure! Here is the score: {\"intent_fit\":10,\"syllabus_alignment\":20,\"difficulty\":30,\"aeo_readability\":40,\"total\":25,\"reason\":\"weak\"} hope this helps."
    out = tds.parse_grader_response(text)
    assert out is not None
    assert out["total"] == 24
    assert out["reason"] == "weak"


def test_parse_grader_response_ignores_llm_total_uses_weighted_blend():
    """Architect review (Task #937 acceptance gate): the configurable
    scoring formula must be applied deterministically — the LLM's
    self-reported ``total`` is ignored even when present, so a
    grader-side bug or prompt-injection cannot bypass policy."""
    # All axes equal 100 — true weighted blend is 100. LLM reports 1.
    out = tds.parse_grader_response(
        '{"intent_fit":100,"syllabus_alignment":100,"difficulty":100,'
        '"aeo_readability":100,"total":1,"reason":"x"}'
    )
    assert out["total"] == 100


def test_compute_weighted_total_respects_env_weight_override(monkeypatch):
    """Operators can re-weight axes via env vars; the formula
    re-normalises so the total stays in 0-100."""
    monkeypatch.setenv("TOPIC_DISCOVERY_W_SYLLABUS", "1.0")
    monkeypatch.setenv("TOPIC_DISCOVERY_W_INTENT", "0")
    monkeypatch.setenv("TOPIC_DISCOVERY_W_AEO", "0")
    monkeypatch.setenv("TOPIC_DISCOVERY_W_DIFFICULTY", "0")
    # Only syllabus axis matters → total tracks syllabus_alignment.
    out = tds.compute_weighted_total(
        syllabus_alignment=42, intent_fit=99,
        aeo_readability=99, difficulty=99,
    )
    assert out == 42


def test_get_config_normalises_partial_weight_overrides(monkeypatch):
    """A partial override (e.g. only the syllabus weight) must not
    push the implied total above 100. We re-normalise."""
    monkeypatch.setenv("TOPIC_DISCOVERY_W_SYLLABUS", "0.7")
    # other weights unset → fall back to defaults 0.25 / 0.20 / 0.20
    cfg = tds.get_config()
    s = cfg["w_syllabus"] + cfg["w_intent"] + cfg["w_aeo"] + cfg["w_difficulty"]
    assert abs(s - 1.0) < 1e-9
    # All four axes at 100 → blended total is exactly 100.
    assert tds.compute_weighted_total(
        syllabus_alignment=100, intent_fit=100,
        aeo_readability=100, difficulty=100,
    ) == 100


def test_parse_grader_response_clamps_out_of_range():
    out = tds.parse_grader_response(
        '{"intent_fit": 250, "syllabus_alignment": -40, "difficulty": "abc",'
        ' "aeo_readability": 80, "reason": "x"}'
    )
    assert out["intent_fit"] == 100
    assert out["syllabus_alignment"] == 0
    assert out["difficulty"] == 0  # non-numeric → clamp lo
    # No total provided → derived from weighted blend
    assert 0 <= out["total"] <= 100


def test_parse_grader_response_returns_none_on_garbage():
    assert tds.parse_grader_response("") is None
    assert tds.parse_grader_response("nope, no json here") is None


def test_parse_grader_response_clips_long_reason():
    long = "x" * 1000
    out = tds.parse_grader_response(
        '{"intent_fit":50,"syllabus_alignment":50,"difficulty":50,'
        f'"aeo_readability":50,"total":50,"reason":"{long}"}}'
    )
    assert len(out["reason"]) == 280


# ─── decide ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("total,auto_rem,draft_rem,expected", [
    (90, 5, 50, "auto_published"),
    (90, 0, 50, "drafted"),       # auto cap hit → demote
    (90, 0, 0, "rejected"),       # both caps hit
    (60, 5, 50, "drafted"),
    (60, 5, 0, "rejected"),       # in draft band but draft cap hit
    (40, 5, 50, "rejected"),      # below draft threshold
])
def test_decide_tiering_and_cap_demote(total, auto_rem, draft_rem, expected):
    out = tds.decide(
        {"total": total},
        auto_publish_threshold=80,
        draft_threshold=55,
        auto_remaining=auto_rem,
        draft_remaining=draft_rem,
    )
    assert out["decision"] == expected
    assert out["total"] == total
    assert isinstance(out["decision_reason"], str) and out["decision_reason"]


def test_decide_handles_no_score():
    out = tds.decide(
        None,
        auto_publish_threshold=80,
        draft_threshold=55,
        auto_remaining=10,
        draft_remaining=50,
    )
    assert out["decision"] == "error"
    assert out["total"] == 0


# ─── _dedupe_candidates ────────────────────────────────────────────────


def test_dedupe_merges_normalised_queries_and_collects_sources():
    rows = [
        {"source": "gsc_near_miss", "query": "Photosynthesis Class 11",
         "signal": {"impressions": 1200}},
        {"source": "trending", "query": "  photosynthesis class 11 ",
         "signal": {"score": 0.7}},
        {"source": "suggest_expansion", "query": "Photosynthesis Class 11",
         "signal": {"rank": 2}},
        {"source": "gsc_near_miss", "query": "lone query",
         "signal": {"impressions": 5}},
    ]
    out = tds._dedupe_candidates(rows)
    assert len(out) == 2
    merged = out[0]  # multi-source row should sort first
    assert merged["query"].lower().startswith("photosynthesis")
    assert set(merged["sources"]) == {"gsc_near_miss", "trending", "suggest_expansion"}
    assert merged["signals"]["gsc_near_miss"]["impressions"] == 1200
    assert merged["signals"]["trending"]["score"] == 0.7


def test_dedupe_skips_blank_queries_and_caps_total():
    rows = [{"source": "trending", "query": "   ", "signal": {}}]
    rows += [
        {"source": "gsc_near_miss", "query": f"q{i}",
         "signal": {"impressions": 100 - i}}
        for i in range(5)
    ]
    out = tds._dedupe_candidates(rows, cap=3)
    assert len(out) == 3
    # Highest impressions first within single-source tier.
    assert out[0]["signals"]["gsc_near_miss"]["impressions"] == 100


# ─── collect_* (Mongo adapter contracts) ───────────────────────────────


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_kw):
        return self

    def limit(self, n):
        self._docs = self._docs[: int(n)]
        return self

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class _FakeColl:
    def __init__(self, docs):
        self._docs = list(docs)
        self.last_query = None

    def find(self, q, _proj=None):
        self.last_query = q
        return _FakeCursor(self._docs)


class _FakeDb:
    """Minimal db that supports both ``db[name]`` and attribute access."""

    def __init__(self, mapping=None):
        self._map = dict(mapping or {})

    def __getitem__(self, name):
        return self._map.setdefault(name, _FakeColl([]))

    def __getattr__(self, name):
        if name == "_map":
            raise AttributeError(name)
        return self._map.setdefault(name, _FakeColl([]))



def test_collect_gsc_near_misses_shapes_rows():
    now = datetime.now(timezone.utc)
    docs = [
        {"query": "biology question", "position": 14.2, "impressions": 800,
         "clicks": 12, "ctr": 0.015, "recorded_at": now - timedelta(days=1)},
        {"query": "  ", "position": 12, "impressions": 100,
         "recorded_at": now},  # blank query — skipped
    ]
    db = _FakeDb({tds.GSC_NEAR_MISS_COLLECTION: _FakeColl(docs)})
    out = _run(tds.collect_gsc_near_misses(db, now=now))
    assert len(out) == 1
    assert out[0]["source"] == "gsc_near_miss"
    assert out[0]["query"] == "biology question"
    assert out[0]["signal"]["impressions"] == 800


def test_collect_gsc_near_misses_returns_empty_when_db_none():
    assert _run(tds.collect_gsc_near_misses(None)) == []


def test_collect_trending_handles_empty_collection():
    db = _FakeDb({tds.TRENDING_RAW_COLLECTION: _FakeColl([])})
    assert _run(tds.collect_trending(db)) == []


def test_collect_trending_shapes_and_falls_back_on_missing_score():
    now = datetime.now(timezone.utc)
    docs = [
        {"query": "neet 2026 syllabus", "source": "google_trends",
         "score": 0.85, "recorded_at": now},
        {"query": "ahsec routine", "score": None, "recorded_at": now},
    ]
    db = _FakeDb({tds.TRENDING_RAW_COLLECTION: _FakeColl(docs)})
    out = _run(tds.collect_trending(db, now=now))
    assert {r["query"] for r in out} == {"neet 2026 syllabus", "ahsec routine"}
    assert all(r["source"] == "trending" for r in out)


def test_collect_suggest_expansions_uses_seo_topic_seeds():
    seeds_docs = [
        {"primary_keyword": "Photosynthesis", "updated_at": datetime.now(timezone.utc)},
        {"primary_keyword": "Photosynthesis", "updated_at": datetime.now(timezone.utc)},  # dup
        {"topic": "Newton's laws", "updated_at": datetime.now(timezone.utc)},
    ]
    db = _FakeDb()
    db._map["seo_topics"] = _FakeColl(seeds_docs)

    captured_seeds: List[str] = []

    async def fake_suggest(seed, db=None, now=None):
        captured_seeds.append(seed)
        return {"suggestions": [
            {"keyword": f"{seed} class 11", "rank": 1, "locales": ["IN"]},
            {"keyword": f"{seed} class 11", "rank": 2},  # dup, deduped via seen
            {"keyword": "  ", "rank": 3},                # blank, skipped
        ]}

    out = _run(tds.collect_suggest_expansions(
        db, suggest_fetcher=fake_suggest, seed_limit=5,
    ))
    assert "Photosynthesis" in captured_seeds
    assert "Newton's laws" in captured_seeds
    # 2 seeds × 1 unique non-blank suggestion each = 2 rows
    assert len(out) == 2
    assert all(r["source"] == "suggest_expansion" for r in out)


# ─── run_topic_discovery_once (orchestrator integration) ───────────────


class _FakeUpdateColl:
    """Collection with awaitable update_one + count_documents and an
    async-iterable find()."""

    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.upserts: List[Dict[str, Any]] = []

    def find(self, *_a, **_kw):
        return _FakeCursor(self.docs)

    async def update_one(self, q, update, upsert=False):
        self.upserts.append({"q": q, "update": update, "upsert": upsert})
        # Apply $set so subsequent find_one sees the merged state.
        sets = update.get("$set") or {}
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(sets)
                return
        if upsert:
            new_doc = {**q, **sets}
            self.docs.append(new_doc)

    async def find_one(self, q, _proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def count_documents(self, q):
        def _match(doc, query):
            for k, v in query.items():
                dv = doc.get(k)
                if isinstance(v, dict):
                    for op, opv in v.items():
                        if op == "$gte" and not (dv is not None and dv >= opv):
                            return False
                        if op == "$lt" and not (dv is not None and dv < opv):
                            return False
                        if op == "$ne" and dv == opv:
                            return False
                else:
                    if dv != v:
                        return False
            return True
        return sum(1 for d in self.docs if _match(d, q))


class _FakeWritableDb:
    def __init__(self):
        self._map: Dict[str, _FakeUpdateColl] = {}

    def __getitem__(self, name):
        return self._map.setdefault(name, _FakeUpdateColl())

    def __getattr__(self, name):
        if name == "_map":
            raise AttributeError(name)
        return self._map.setdefault(name, _FakeUpdateColl())



def test_run_topic_discovery_once_end_to_end_with_budget_cap():
    now = datetime.now(timezone.utc)
    db = _FakeWritableDb()
    # Seed GSC + trending so the orchestrator gets candidates.
    db[tds.GSC_NEAR_MISS_COLLECTION].docs = [
        {"query": f"q{i}", "position": 12.0, "impressions": 1000 - i,
         "recorded_at": now}
        for i in range(5)
    ]
    db[tds.TRENDING_RAW_COLLECTION].docs = [
        {"query": "trend1", "source": "rss", "score": 0.9, "recorded_at": now},
    ]

    # Suggest fetcher contributes nothing extra (no seo_topics seeds).
    async def empty_suggest(seed, db=None, now=None):
        return {"suggestions": []}

    # Grader returns descending totals so cap behaviour is deterministic:
    # 95, 90, 85, 80, 75, 70 → with auto_cap=2 we expect 2 auto, the
    # next high scorers demote to draft.
    scores = iter([95, 90, 85, 80, 75, 70])

    async def fake_llm(messages, model=None, max_tokens=None):
        s = next(scores)
        return ('{"intent_fit": %d, "syllabus_alignment": %d, "difficulty": %d,'
                ' "aeo_readability": %d, "total": %d, "reason": "ok"}'
                % (s, s, s, s, s))

    upserts_recorded: List[Dict[str, Any]] = []

    async def fake_upsert_seo_topic(_db, key, doc):
        upserts_recorded.append({"key": key, "doc": doc})

    with patch("seo_writes.upsert_seo_topic", fake_upsert_seo_topic):
        summary = _run(tds.run_topic_discovery_once(
            db,
            now=now,
            suggest_fetcher=empty_suggest,
            llm_caller=fake_llm,
            config={
                "auto_publish_threshold": 80,
                "draft_threshold": 55,
                "auto_publish_cap": 2,
                "draft_cap": 50,
            },
        ))

    totals = summary["totals"]
    assert totals["raw"] == 6
    assert totals["deduped"] == 6
    # 2 land auto, the next 2 scoring ≥80 demote to draft, then the 75/70
    # ones land in draft band → 4 drafted total.
    assert totals["auto_published"] == 2
    assert totals["drafted"] == 4
    assert totals["rejected"] == 0
    assert summary["remaining_after_run"]["auto_publish"] == 0

    # Every auto/draft candidate is enqueued; rejected/error are not.
    assert len(upserts_recorded) == 6
    statuses = {u["doc"]["discovery_status"] for u in upserts_recorded}
    assert statuses == {"auto_publish_pending", "draft_pending"}
    # Run row was persisted.
    assert any(u["q"].get("id") == summary["id"]
               for u in db[tds.RUNS_COLLECTION].upserts)
    # Each candidate row was persisted with deterministic id.
    assert len(db[tds.CANDIDATES_COLLECTION].upserts) == 6



def test_run_topic_discovery_once_marks_grader_failures_as_error():
    now = datetime.now(timezone.utc)
    db = _FakeWritableDb()
    db[tds.GSC_NEAR_MISS_COLLECTION].docs = [
        {"query": "q1", "position": 12.0, "impressions": 100, "recorded_at": now},
    ]

    async def empty_suggest(seed, db=None, now=None):
        return {"suggestions": []}

    async def broken_llm(messages, model=None, max_tokens=None):
        return "no json here"

    with patch("seo_writes.upsert_seo_topic", AsyncMock()):
        summary = _run(tds.run_topic_discovery_once(
            db, now=now, suggest_fetcher=empty_suggest, llm_caller=broken_llm,
        ))
    assert summary["totals"]["error"] == 1
    assert summary["totals"]["auto_published"] == 0
    assert summary["totals"]["drafted"] == 0


# ─── apply_override ────────────────────────────────────────────────────



def test_apply_override_promote_enqueues_when_not_already():
    db = _FakeWritableDb()
    db[tds.CANDIDATES_COLLECTION].docs = [{
        "id": "cand_1", "run_id": "r1", "query": "Photosynthesis",
        "sources": ["gsc_near_miss"], "decision": "rejected",
        "enqueued_topic": None,
    }]
    enqueue_calls: List[Dict[str, Any]] = []

    async def fake_upsert(_db, key, doc):
        enqueue_calls.append(doc)

    with patch("seo_writes.upsert_seo_topic", fake_upsert):
        out = _run(tds.apply_override(
            db, candidate_id="cand_1", new_decision="auto_published",
            admin_reason="manual promote", admin_id="admin-1",
        ))
    assert out["decision"] == "auto_published"
    assert out["admin_decision"] == "auto_published"
    assert out["enqueued_topic"] == "Photosynthesis"
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0]["discovery_status"] == "auto_publish_pending"



def test_apply_override_reject_does_not_enqueue():
    db = _FakeWritableDb()
    db[tds.CANDIDATES_COLLECTION].docs = [{
        "id": "cand_1", "run_id": "r1", "query": "spam query",
        "sources": ["trending"], "decision": "drafted",
        "enqueued_topic": None,
    }]
    fake = AsyncMock()
    with patch("seo_writes.upsert_seo_topic", fake):
        out = _run(tds.apply_override(
            db, candidate_id="cand_1", new_decision="rejected",
            admin_reason="off-topic", admin_id="admin-1",
        ))
    assert out["decision"] == "rejected"
    assert out["admin_decision"] == "rejected"
    fake.assert_not_called()



def test_apply_override_skips_re_enqueue_when_already_queued():
    db = _FakeWritableDb()
    db[tds.CANDIDATES_COLLECTION].docs = [{
        "id": "cand_1", "run_id": "r1", "query": "already queued",
        "sources": ["gsc_near_miss"], "decision": "drafted",
        "enqueued_topic": "already queued",
    }]
    fake = AsyncMock()
    with patch("seo_writes.upsert_seo_topic", fake):
        _run(tds.apply_override(
            db, candidate_id="cand_1", new_decision="auto_published",
            admin_reason="bump tier", admin_id="admin-1",
        ))
    fake.assert_not_called()



def test_apply_override_rejects_unknown_decision():
    db = _FakeWritableDb()
    with pytest.raises(ValueError):
        _run(tds.apply_override(
            db, candidate_id="x", new_decision="banana",
            admin_reason="", admin_id="admin",
        ))



def test_apply_override_raises_lookup_error_on_unknown_id():
    db = _FakeWritableDb()
    with pytest.raises(LookupError):
        _run(tds.apply_override(
            db, candidate_id="missing", new_decision="rejected",
            admin_reason="", admin_id="admin",
        ))


# ─── get_config env overrides ──────────────────────────────────────────


def test_run_topic_discovery_once_marks_enqueue_failure():
    """Architect review: an approved candidate that fails the
    upsert_seo_topic call must surface an ``enqueue_error`` flag so
    admins can retry — we do NOT silently downgrade the decision."""
    now = datetime.now(timezone.utc)
    db = _FakeWritableDb()
    db[tds.GSC_NEAR_MISS_COLLECTION].docs = [
        {"query": "q1", "position": 12.0, "impressions": 100, "recorded_at": now},
    ]

    async def empty_suggest(seed, db=None, now=None):
        return {"suggestions": []}

    async def good_llm(messages, model=None, max_tokens=None):
        return ('{"intent_fit":90,"syllabus_alignment":90,"difficulty":90,'
                '"aeo_readability":90,"total":90,"reason":"ok"}')

    async def broken_upsert(_db, key, doc):
        raise RuntimeError("pipeline rejected upsert")

    with patch("seo_writes.upsert_seo_topic", broken_upsert):
        summary = _run(tds.run_topic_discovery_once(
            db, now=now, suggest_fetcher=empty_suggest, llm_caller=good_llm,
        ))
    # Decision still recorded — admin can override / retry.
    assert summary["totals"]["auto_published"] == 1
    cand = db[tds.CANDIDATES_COLLECTION].upserts[0]["update"]["$set"]
    assert cand["decision"] == "auto_published"
    assert cand["enqueued_topic"] is None
    assert "enqueue failed" in (cand.get("enqueue_error") or "")


def test_run_topic_discovery_once_respects_per_day_budget_across_runs():
    """Architect review: running twice in one UTC day must share the
    daily cap rather than each run starting fresh from the operator's
    promised limit."""
    now = datetime.now(timezone.utc)
    db = _FakeWritableDb()
    # Pre-seed today's CANDIDATES_COLLECTION with 2 already-auto rows
    # so the orchestrator's per-day accounting subtracts them.
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    db[tds.CANDIDATES_COLLECTION].docs = [
        {"id": "prev_a", "decision": "auto_published",
         "created_at": day_start + timedelta(minutes=5)},
        {"id": "prev_b", "decision": "auto_published",
         "created_at": day_start + timedelta(minutes=10)},
    ]
    db[tds.GSC_NEAR_MISS_COLLECTION].docs = [
        {"query": f"q{i}", "position": 12.0, "impressions": 1000 - i,
         "recorded_at": now}
        for i in range(4)
    ]

    async def empty_suggest(seed, db=None, now=None):
        return {"suggestions": []}

    async def high_llm(messages, model=None, max_tokens=None):
        return ('{"intent_fit":95,"syllabus_alignment":95,"difficulty":95,'
                '"aeo_readability":95,"total":95,"reason":"ok"}')

    with patch("seo_writes.upsert_seo_topic", AsyncMock()):
        summary = _run(tds.run_topic_discovery_once(
            db, now=now, suggest_fetcher=empty_suggest, llm_caller=high_llm,
            config={
                "auto_publish_threshold": 80,
                "draft_threshold": 55,
                "auto_publish_cap": 5,   # 5 - 2 already spent = 3 left
                "draft_cap": 50,
            },
        ))
    # Cap was 5, 2 already consumed today → only 3 of 4 high scorers
    # may auto-publish; the 4th demotes to draft.
    assert summary["totals"]["auto_published"] == 3
    assert summary["totals"]["drafted"] == 1


def test_count_today_decisions_filters_to_utc_day_start():
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    db = _FakeWritableDb()
    db[tds.CANDIDATES_COLLECTION].docs = [
        # Yesterday — must NOT count
        {"id": "old", "decision": "auto_published",
         "created_at": day_start - timedelta(hours=2)},
        # Today
        {"id": "new1", "decision": "auto_published",
         "created_at": day_start + timedelta(minutes=1)},
        {"id": "new2", "decision": "drafted",
         "created_at": day_start + timedelta(minutes=2)},
    ]
    out = _run(tds._count_today_decisions(db, now=now))
    assert out == {"auto_published": 1, "drafted": 1}


def test_count_today_decisions_safe_when_db_none():
    now = datetime.now(timezone.utc)
    assert _run(tds._count_today_decisions(None, now=now)) == {
        "auto_published": 0, "drafted": 0,
    }


def test_get_config_uses_defaults(monkeypatch):
    for k in [
        "TOPIC_DISCOVERY_AUTO_PUBLISH_THRESHOLD",
        "TOPIC_DISCOVERY_DRAFT_THRESHOLD",
        "TOPIC_DISCOVERY_AUTO_PUBLISH_CAP",
        "TOPIC_DISCOVERY_DRAFT_CAP",
        "TOPIC_DISCOVERY_RUN_HOUR_UTC",
        "TOPIC_DISCOVERY_DISABLED",
    ]:
        monkeypatch.delenv(k, raising=False)
    cfg = tds.get_config()
    assert cfg["auto_publish_threshold"] == tds.DEFAULT_AUTO_PUBLISH_THRESHOLD
    assert cfg["draft_threshold"] == tds.DEFAULT_DRAFT_THRESHOLD
    assert cfg["auto_publish_cap"] == tds.DEFAULT_AUTO_PUBLISH_CAP
    assert cfg["draft_cap"] == tds.DEFAULT_DRAFT_CAP
    assert cfg["run_hour_utc"] == tds.DEFAULT_RUN_HOUR_UTC
    assert cfg["disabled"] == 0


def test_get_config_respects_env(monkeypatch):
    monkeypatch.setenv("TOPIC_DISCOVERY_AUTO_PUBLISH_THRESHOLD", "85")
    monkeypatch.setenv("TOPIC_DISCOVERY_DRAFT_THRESHOLD", "60")
    monkeypatch.setenv("TOPIC_DISCOVERY_AUTO_PUBLISH_CAP", "5")
    monkeypatch.setenv("TOPIC_DISCOVERY_DRAFT_CAP", "20")
    monkeypatch.setenv("TOPIC_DISCOVERY_RUN_HOUR_UTC", "26")  # → 2
    monkeypatch.setenv("TOPIC_DISCOVERY_DISABLED", "1")
    cfg = tds.get_config()
    assert cfg["auto_publish_threshold"] == 85
    assert cfg["draft_threshold"] == 60
    assert cfg["auto_publish_cap"] == 5
    assert cfg["draft_cap"] == 20
    assert cfg["run_hour_utc"] == 2
    assert cfg["disabled"] == 1


# ── daily lock semantics ─────────────────────────────────────────────


class _DupKeyError(Exception):
    """Stand-in for pymongo.errors.DuplicateKeyError; the production
    code only inspects ``type(exc).__name__`` to detect it."""

    def __init__(self, msg="duplicate key"):
        super().__init__(msg)


# Force the name match used by _try_claim_daily_lock's exception filter.
_DupKeyError.__name__ = "DuplicateKeyError"


class _LockColl:
    """Tiny fake that enforces _id uniqueness and supports the three
    operations the lock helper needs: insert_one, find_one,
    update_one."""

    def __init__(self):
        self.docs: List[Dict[str, Any]] = []

    async def insert_one(self, doc):
        for d in self.docs:
            if d.get("_id") == doc.get("_id"):
                raise _DupKeyError()
        self.docs.append(dict(doc))

    async def find_one(self, q, _proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def update_one(self, q, update, upsert=False):
        sets = (update.get("$set") or {})
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if k == "$or":
                    if not any(
                        all(
                            (d.get(kk) == vv if not isinstance(vv, dict)
                             else (kk in d) == (not vv.get("$exists", True)))
                            for kk, vv in branch.items()
                        )
                        for branch in v
                    ):
                        ok = False
                        break
                    continue
                if isinstance(v, dict):
                    if "$exists" in v:
                        if (k in d) != v["$exists"]:
                            ok = False
                            break
                    continue
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                d.update(sets)

                class _R:
                    modified_count = 1
                return _R()

        class _R0:
            modified_count = 0
        return _R0()


class _LockDb:
    def __init__(self):
        self._coll = _LockColl()

    def __getitem__(self, _name):
        return self._coll


def test_try_claim_daily_lock_first_writer_wins_and_second_is_blocked():
    db = _LockDb()
    now = datetime.now(timezone.utc)
    lock_id = "daily_lock_2026-04-26"

    a = _run(tds._try_claim_daily_lock(
        db, lock_id=lock_id, owner_token="A", now=now,
    ))
    b = _run(tds._try_claim_daily_lock(
        db, lock_id=lock_id, owner_token="B", now=now,
    ))

    assert a is True
    assert b is False
    # Single doc only — no duplicate _id rows under contention.
    assert len(db._coll.docs) == 1
    assert db._coll.docs[0]["_id"] == lock_id
    assert db._coll.docs[0]["claim_token"] == "A"


def test_try_claim_daily_lock_blocks_after_ran_at_set():
    db = _LockDb()
    now = datetime.now(timezone.utc)
    lock_id = "daily_lock_2026-04-27"

    # Pre-seed a "completed" daily lock from earlier in the day.
    db._coll.docs.append({
        "_id": lock_id,
        "kind": "daily_lock",
        "claim_token": "earlier",
        "claimed_at": now,
        "ran_at": now,
    })

    out = _run(tds._try_claim_daily_lock(
        db, lock_id=lock_id, owner_token="late", now=now,
    ))
    assert out is False
    assert len(db._coll.docs) == 1


def test_try_claim_daily_lock_safe_when_db_none():
    now = datetime.now(timezone.utc)
    assert _run(tds._try_claim_daily_lock(
        None, lock_id="x", owner_token="y", now=now,
    )) is False
