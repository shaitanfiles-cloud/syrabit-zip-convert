"""Task #939 — unit tests for the agentic internal-linker service.

Covers the pure helpers (anchor insert / remove / decide_action /
URL builder / LLM parser) and the integration of
``propose_internal_links_for_page`` against an in-memory fake Mongo.

The fake collections mirror the ones used by
``tests/test_admin_seo_remediation_route.py`` so a future shared
helper can be validated against both at once.
"""
from __future__ import annotations

import asyncio
import sys
import types
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

import seo_internal_linker as linker


def _run(coro):
    """Synchronous wrapper — project doesn't ship pytest-asyncio."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─── pure helper tests ─────────────────────────────────────────────────


def test_insert_anchor_basic_replacement():
    body = "<p>Newton's first law of motion explains inertia.</p>"
    out, did = linker.insert_anchor(
        body, anchor_text="first law of motion",
        target_url="/board/class-11/physics/first-law/notes",
        target_page_id="tgt1",
    )
    assert did is True
    assert "<!-- syrabit:autolink:tgt1 -->" in out
    assert 'href="/board/class-11/physics/first-law/notes"' in out
    assert "Newton's" in out  # didn't truncate the prefix
    assert ">first law of motion</a>" in out


def test_insert_anchor_preserves_original_casing():
    body = "<p>Pythagorean Theorem proof here.</p>"
    out, did = linker.insert_anchor(
        body, anchor_text="pythagorean theorem",
        target_url="/x", target_page_id="t",
    )
    assert did is True
    # Anchor text should keep the body's original casing.
    assert ">Pythagorean Theorem</a>" in out


def test_insert_anchor_idempotent_on_marker():
    body = '<p>Newton <!-- syrabit:autolink:t1 --><a href="/x">already</a> linked.</p>'
    out, did = linker.insert_anchor(
        body, anchor_text="Newton", target_url="/y", target_page_id="t1",
    )
    assert did is False
    assert out == body  # body unchanged


def test_insert_anchor_skips_inside_existing_anchor():
    # The only "Newton" sits inside an <a>; we must NOT nest links.
    body = '<p>See <a href="/old">Newton ref</a>.</p>'
    out, did = linker.insert_anchor(
        body, anchor_text="Newton", target_url="/y", target_page_id="t1",
    )
    assert did is False
    assert out == body


def test_insert_anchor_skips_inside_code_pre_and_headings():
    body = (
        "<h2>Newton header</h2>"
        "<pre>Newton pre block</pre>"
        "<code>Newton code</code>"
    )
    out, did = linker.insert_anchor(
        body, anchor_text="Newton", target_url="/y", target_page_id="t1",
    )
    assert did is False
    assert out == body


def test_insert_anchor_first_match_only():
    body = "<p>Newton then later Newton again.</p>"
    out, did = linker.insert_anchor(
        body, anchor_text="Newton", target_url="/y", target_page_id="t1",
    )
    assert did is True
    # Only the FIRST occurrence is wrapped — second remains plain text.
    assert out.count("<!-- syrabit:autolink:t1 -->") == 1
    assert out.count("<a ") == 1


def test_insert_anchor_returns_unchanged_when_anchor_missing():
    body = "<p>nothing relevant here</p>"
    out, did = linker.insert_anchor(
        body, anchor_text="quantum entanglement",
        target_url="/y", target_page_id="t1",
    )
    assert did is False
    assert out == body


def test_remove_anchor_round_trips_with_insert():
    body = "<p>Newton's first law explains inertia.</p>"
    inserted, _ = linker.insert_anchor(
        body, anchor_text="first law",
        target_url="/x", target_page_id="t1",
    )
    restored, did = linker.remove_anchor(inserted, target_page_id="t1")
    assert did is True
    assert restored == body


def test_remove_anchor_no_marker_is_noop():
    body = "<p>plain prose with no autolink.</p>"
    out, did = linker.remove_anchor(body, target_page_id="t1")
    assert did is False
    assert out == body


# ─── decide_action ─────────────────────────────────────────────────────


def test_decide_action_auto_apply_above_threshold():
    out = linker.decide_action(
        confidence=0.9, budget_used=0, budget_cap=100,
        duplicate=False, anchor_findable=True,
    )
    assert out["action"] == linker.ACTION_AUTO_APPLIED


def test_decide_action_drafted_when_below_threshold():
    out = linker.decide_action(
        confidence=0.5, budget_used=0, budget_cap=100,
        duplicate=False, anchor_findable=True,
    )
    assert out["action"] == linker.ACTION_DRAFTED
    assert "threshold" in out["reason"]


def test_decide_action_drafted_when_budget_exhausted():
    out = linker.decide_action(
        confidence=0.9, budget_used=100, budget_cap=100,
        duplicate=False, anchor_findable=True,
    )
    assert out["action"] == linker.ACTION_DRAFTED
    assert "cap reached" in out["reason"]


def test_decide_action_skipped_when_duplicate():
    out = linker.decide_action(
        confidence=0.99, budget_used=0, budget_cap=100,
        duplicate=True, anchor_findable=True,
    )
    assert out["action"] == linker.ACTION_SKIPPED_DUPLICATE


def test_decide_action_skipped_when_anchor_missing():
    out = linker.decide_action(
        confidence=0.99, budget_used=0, budget_cap=100,
        duplicate=False, anchor_findable=False,
    )
    assert out["action"] == linker.ACTION_SKIPPED_NO_ANCHOR


# ─── URL helpers ───────────────────────────────────────────────────────


def test_build_page_url_default_page_type_omits_suffix():
    url = linker._build_page_url({
        "board_slug": "ahsec", "class_slug": "class-11",
        "subject_slug": "physics", "topic_slug": "motion",
        "page_type": "notes",
    })
    assert url == "/ahsec/class-11/physics/motion"


def test_build_page_url_appends_non_default_page_type():
    url = linker._build_page_url({
        "board_slug": "cbse", "class_slug": "class-12",
        "subject_slug": "math", "topic_slug": "calculus",
        "page_type": "mcqs",
    })
    assert url == "/cbse/class-12/math/calculus/mcqs"


def test_build_page_url_returns_empty_when_slugs_missing():
    assert linker._build_page_url({}) == ""


# ─── LLM response parser ───────────────────────────────────────────────


def test_parse_llm_response_strips_fence():
    raw = '```json\n{"links": [{"source_index": 0, "anchor_text": "X", "confidence": 0.8}]}\n```'
    out = linker._parse_llm_response(raw)
    assert len(out) == 1
    assert out[0]["source_index"] == 0
    assert out[0]["confidence"] == pytest.approx(0.8)


def test_parse_llm_response_clamps_confidence_to_unit_interval():
    raw = '{"links": [{"source_index": 1, "anchor_text": "y", "confidence": 5}]}'
    out = linker._parse_llm_response(raw)
    assert out[0]["confidence"] == 1.0


def test_parse_llm_response_rejects_malformed_items():
    raw = '{"links": [{"anchor_text": "no idx"}, "garbage", {"source_index": 2, "anchor_text": ""}]}'
    out = linker._parse_llm_response(raw)
    assert out == []


def test_parse_llm_response_ignores_non_json_preface():
    raw = "Sure thing!\n{\"links\": [{\"source_index\": 3, \"anchor_text\": \"foo bar\", \"confidence\": 0.6, \"reason\": \"r\"}]}"
    out = linker._parse_llm_response(raw)
    assert len(out) == 1
    assert out[0]["anchor_text"] == "foo bar"


# ─── In-memory fake Mongo for propose flow ─────────────────────────────


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._limit = None

    def sort(self, *_a, **_kw):
        return self

    def limit(self, n):
        self._limit = int(n)
        return self

    async def to_list(self, n):
        end = min(self._limit or len(self._docs), int(n))
        return self._docs[:end]


class _FakeColl:
    def __init__(self, docs=None):
        self.docs: List[Dict[str, Any]] = list(docs or [])
        self.update_calls: List[Dict[str, Any]] = []

    def find(self, q=None, _proj=None):
        q = q or {}
        out = [d for d in self.docs if all(d.get(k) == v for k, v in q.items())]
        return _FakeCursor(out)

    async def find_one(self, q, _proj=None):
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if isinstance(v, dict) and "$in" in v:
                    if d.get(k) not in v["$in"]:
                        ok = False
                        break
                elif d.get(k) != v:
                    ok = False
                    break
            if ok:
                return dict(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("id")})()

    @staticmethod
    def _match_one(d, q):
        """Tiny mongo-ish matcher supporting scalars + $lt/$gt/$in/$ne."""
        for k, v in q.items():
            actual = d.get(k)
            if isinstance(v, dict):
                for op, vv in v.items():
                    if op == "$lt" and not (actual is not None and actual < vv):
                        return False
                    if op == "$gt" and not (actual is not None and actual > vv):
                        return False
                    if op == "$lte" and not (actual is not None and actual <= vv):
                        return False
                    if op == "$gte" and not (actual is not None and actual >= vv):
                        return False
                    if op == "$in" and actual not in vv:
                        return False
                    if op == "$ne" and actual == vv:
                        return False
            else:
                if actual != v:
                    return False
        return True

    async def update_one(self, q, update, upsert=False):
        self.update_calls.append({"q": dict(q), "update": update, "upsert": upsert})
        sets = update.get("$set") or {}
        on_insert = update.get("$setOnInsert") or {}
        inc = update.get("$inc") or {}
        for d in self.docs:
            if self._match_one(d, q):
                d.update(sets)
                for k, v in inc.items():
                    d[k] = int(d.get(k) or 0) + int(v)
                return type("R", (), {"modified_count": 1, "upserted_id": None})()
        if upsert:
            # Drop operator dicts when seeding a brand-new doc.
            seed = {k: v for k, v in q.items() if not isinstance(v, dict)}
            new = {**seed, **on_insert, **sets}
            for k, v in inc.items():
                new[k] = int(v)
            self.docs.append(new)
            return type("R", (), {"modified_count": 0, "upserted_id": new.get("_id")})()
        return type("R", (), {"modified_count": 0, "upserted_id": None})()

    async def count_documents(self, q):
        return len(list(self.find(q).to_list(10000) if False else
                        [d for d in self.docs if all(d.get(k) == v for k, v in q.items())]))


class _FakeDb:
    def __init__(self):
        self.seo_pages = _FakeColl()
        self.internal_link_history = _FakeColl()
        self.internal_link_budget = _FakeColl()


def _mk_page(pid, *, topic, body="", subj="phys", subj_slug="physics",
             topic_slug=None, page_type="notes"):
    return {
        "id": pid,
        "topic_id": f"top-{pid}",
        "topic_title": topic,
        "topic_slug": topic_slug or topic.lower().replace(" ", "-"),
        "title": topic,
        "subject_id": subj,
        "subject_slug": subj_slug,
        "subject_name": "Physics",
        "class_slug": "class-11",
        "board_slug": "ahsec",
        "page_type": page_type,
        "status": "published",
        "content": body,
    }


# ─── propose_internal_links_for_page ───────────────────────────────────


def _patch_candidates(candidates):
    """Force ``_select_candidate_sources`` to return a fixed pool so the
    propose-flow tests are decoupled from the (separately-tested)
    lexical scoring layer."""
    async def _f(*_a, **_kw):
        return list(candidates)
    return patch("seo_internal_linker._select_candidate_sources", new=_f)


def test_propose_auto_applies_high_confidence():
    db = _FakeDb()
    target = _mk_page("T", topic="Newton's First Law")
    src = _mk_page(
        "S1", topic="Inertia",
        body="<p>An object at rest tends to stay at rest. Newton explained this.</p>",
    )
    db.seo_pages.docs.extend([target, src])

    with _patch_candidates([src]), patch(
        "seo_internal_linker._llm_rank", new=_async_return([{
            "source_index": 0, "anchor_text": "Newton",
            "confidence": 0.95, "reason": "natural",
        }]),
    ), patch("seo_internal_linker._persist_body_update", new=_async_noop()):
        rows = _run(linker.propose_internal_links_for_page(db, target))
    assert len(rows) == 1
    assert rows[0]["action"] == linker.ACTION_AUTO_APPLIED
    # Budget was consumed.
    budget = _run(linker.get_budget_status(db))
    assert budget["auto_used"] == 1
    # History row carries diff excerpts.
    assert "Newton" in rows[0]["diff"]["after_excerpt"]


def test_propose_drafts_low_confidence():
    db = _FakeDb()
    target = _mk_page("T", topic="Calculus")
    src = _mk_page(
        "S1", topic="Algebra",
        body="<p>Functions and limits are foundational topics.</p>",
    )
    db.seo_pages.docs.extend([target, src])

    with _patch_candidates([src]), patch(
        "seo_internal_linker._llm_rank", new=_async_return([{
            "source_index": 0, "anchor_text": "limits",
            "confidence": 0.4, "reason": "weak",
        }]),
    ), patch("seo_internal_linker._persist_body_update", new=_async_noop()):
        rows = _run(linker.propose_internal_links_for_page(db, target))
    assert len(rows) == 1
    assert rows[0]["action"] == linker.ACTION_DRAFTED
    # No budget consumed for drafts.
    budget = _run(linker.get_budget_status(db))
    assert budget["auto_used"] == 0


def test_propose_skips_duplicate_via_history():
    db = _FakeDb()
    target = _mk_page("T", topic="Inertia")
    src = _mk_page(
        "S1", topic="Newton",
        body="<p>Newton wrote the laws of motion.</p>",
    )
    db.seo_pages.docs.extend([target, src])
    # Pre-existing history row marks (S1 -> T) as already linked.
    db.internal_link_history.docs.append({
        "id": "old", "source_page_id": "S1", "target_page_id": "T",
        "action": linker.ACTION_AUTO_APPLIED,
    })

    with _patch_candidates([src]), patch(
        "seo_internal_linker._llm_rank", new=_async_return([{
            "source_index": 0, "anchor_text": "Newton",
            "confidence": 0.99, "reason": "x",
        }]),
    ), patch("seo_internal_linker._persist_body_update", new=_async_noop()):
        rows = _run(linker.propose_internal_links_for_page(db, target))
    assert len(rows) == 1
    assert rows[0]["action"] == linker.ACTION_SKIPPED_DUPLICATE


def test_propose_drafts_when_budget_exhausted():
    db = _FakeDb()
    # Pre-fill today's budget at the cap.
    today = linker._today_key()
    db.internal_link_budget.docs.append({"_id": today, "auto_applied": 100})

    target = _mk_page("T", topic="Topic")
    src = _mk_page("S1", topic="Other",
                   body="<p>Anchor topic appears here.</p>")
    db.seo_pages.docs.extend([target, src])

    with _patch_candidates([src]), patch(
        "seo_internal_linker._llm_rank", new=_async_return([{
            "source_index": 0, "anchor_text": "Anchor topic",
            "confidence": 0.99, "reason": "x",
        }]),
    ), patch("seo_internal_linker._persist_body_update", new=_async_noop()):
        rows = _run(linker.propose_internal_links_for_page(db, target))
    assert len(rows) == 1
    assert rows[0]["action"] == linker.ACTION_DRAFTED
    assert "cap reached" in rows[0]["reason"]


def test_propose_skips_when_target_is_draft():
    db = _FakeDb()
    target = _mk_page("T", topic="X")
    target["status"] = "draft"
    db.seo_pages.docs.append(target)
    rows = _run(linker.propose_internal_links_for_page(db, target))
    assert rows == []


def test_propose_disabled_returns_no_rows(monkeypatch):
    db = _FakeDb()
    monkeypatch.setenv("SEO_LINKER_ENABLED", "0")
    target = _mk_page("T", topic="X")
    rows = _run(linker.propose_internal_links_for_page(db, target))
    assert rows == []


# ─── apply / reject / revert ──────────────────────────────────────────


def test_apply_pending_inserts_anchor_and_flips_action():
    db = _FakeDb()
    target = _mk_page("T", topic="Newton")
    src = _mk_page("S1", topic="Inertia",
                   body="<p>Newton explained inertia clearly.</p>")
    db.seo_pages.docs.extend([target, src])
    rec = {
        "id": "rec1", "source_page_id": "S1", "target_page_id": "T",
        "anchor_text": "Newton", "target_url": "/ahsec/class-11/physics/newton",
        "action": linker.ACTION_DRAFTED,
    }
    db.internal_link_history.docs.append(rec)
    with patch("seo_internal_linker._persist_body_update", new=_async_noop()):
        out = _run(linker.apply_pending_suggestion(db, "rec1", "alice"))
    assert out["ok"] is True
    after = _run(db.internal_link_history.find_one({"id": "rec1"}))
    assert after["action"] == linker.ACTION_AUTO_APPLIED
    assert after["approved_by"] == "alice"


def test_reject_pending_only_works_for_drafted():
    db = _FakeDb()
    db.internal_link_history.docs.append({
        "id": "r1", "action": linker.ACTION_AUTO_APPLIED,
    })
    out = _run(linker.reject_pending_suggestion(db, "r1", "alice"))
    assert out["ok"] is False
    assert "only drafted" in out["error"]


def test_revert_removes_anchor_from_body():
    db = _FakeDb()
    body = '<p>foo <!-- syrabit:autolink:T --><a href="/x">link</a> bar</p>'
    src = _mk_page("S1", topic="X", body=body)
    db.seo_pages.docs.append(src)
    db.internal_link_history.docs.append({
        "id": "r1", "source_page_id": "S1", "target_page_id": "T",
        "action": linker.ACTION_AUTO_APPLIED,
    })
    captured = {}

    async def _capture(_db, source, new_body):
        captured["body"] = new_body
        captured["source_id"] = source.get("id")

    with patch("seo_internal_linker._persist_body_update", new=_capture):
        out = _run(linker.revert_applied_suggestion(db, "r1", "alice"))
    assert out["ok"] is True
    assert captured["source_id"] == "S1"
    assert "<!-- syrabit:autolink:T -->" not in captured["body"]
    assert "link" in captured["body"]  # original anchor text preserved


def test_revert_already_reverted_is_idempotent():
    """Calling revert on an already-reverted row must be a no-op success
    so admin double-clicks don't surface confusing failures."""
    db = _FakeDb()
    db.internal_link_history.docs.append({
        "id": "r1", "source_page_id": "S1", "target_page_id": "T",
        "action": linker.ACTION_REVERTED,
        "reverted_at": "2026-04-26T09:00:00+00:00",
        "reverted_by": "bob",
    })
    persist_called = {"n": 0}

    async def _spy(_db, _src, _body):
        persist_called["n"] += 1

    with patch("seo_internal_linker._persist_body_update", new=_spy):
        out = _run(linker.revert_applied_suggestion(db, "r1", "alice"))
    assert out["ok"] is True
    assert out.get("idempotent") is True
    assert out.get("reverted_by") == "bob"  # original revert author preserved
    assert persist_called["n"] == 0  # body never touched on idempotent revert


def test_revert_rejects_drafted_action():
    """Drafted rows have never been auto-applied so they can't be reverted —
    they should be rejected (or the caller should call /reject instead)."""
    db = _FakeDb()
    db.internal_link_history.docs.append({
        "id": "r1", "action": linker.ACTION_DRAFTED,
    })
    out = _run(linker.revert_applied_suggestion(db, "r1", "alice"))
    assert out["ok"] is False
    assert "only auto_applied" in out["error"]


# ─── hybrid retrieval ──────────────────────────────────────────────────


def test_select_candidates_falls_back_to_keyword_when_embeddings_unavailable():
    """When the embedding helper returns ``None`` (no creds, offline),
    candidate selection must still return a sensible keyword-only
    ranking instead of crashing — Stage 3 generation depends on it."""
    db = _FakeDb()
    target = _mk_page("T", topic="Newton's First Law of Motion")
    # Strong overlap → should rank highest under keyword-only fallback.
    strong = _mk_page("S1", topic="Newton's Second Law", body="<p>Newton motion law.</p>")
    weak = _mk_page("S2", topic="Algebra Basics", body="<p>Equations.</p>")
    db.seo_pages.docs.extend([target, strong, weak])

    async def _none(*_a, **_kw):
        return None  # mimics embed backend unavailable

    with patch("seo_internal_linker._embed_for_linker", new=_none):
        out = _run(linker._select_candidate_sources(db, target))
    ids = [d.get("id") for d in out]
    assert "S1" in ids
    # Weak/no-overlap candidate dropped entirely (keyword score == 0).
    assert "S2" not in ids


def test_embed_for_linker_swallows_backend_errors():
    """Defence-in-depth: even if vertex_services itself raises, the
    helper must return None and never propagate to the caller."""
    import sys, types
    fake_mod = types.ModuleType("vertex_services")
    async def _boom(*_a, **_kw):
        raise RuntimeError("backend down")
    fake_mod.embed_text = _boom
    sys.modules["vertex_services"] = fake_mod
    try:
        out = _run(linker._embed_for_linker("hello", task_type="RETRIEVAL_QUERY"))
        assert out is None
    finally:
        sys.modules.pop("vertex_services", None)


# ─── budget interactions ──────────────────────────────────────────────


def test_consume_budget_after_nightly_marker_still_reserves_slot(monkeypatch):
    """Regression: the nightly loop creates today's budget doc to claim
    the once-per-day marker. If that upsert forgets to seed
    ``auto_applied: 0``, the later ``{$lt: cap}`` reservation guard
    won't match a missing field and every high-confidence proposal
    would be silently downgraded to drafted for the rest of the day.
    Simulate that ordering and assert auto-apply still succeeds."""
    db = _FakeDb()
    today = linker._today_key()
    # Pre-create a doc that mimics what the nightly upsert leaves behind.
    db.internal_link_budget.docs.append({
        "_id": today,
        "nightly_ran_at": "2026-04-26T00:00:00+00:00",
        "auto_applied": 0,           # ← what the fixed upsert seeds
        "created_at":   "2026-04-26T00:00:00+00:00",
    })
    ok = _run(linker._consume_auto_budget(db, cap=5))
    assert ok is True
    # And the counter actually advanced.
    doc = _run(db.internal_link_budget.find_one({"_id": today}))
    assert doc["auto_applied"] == 1


# ─── nightly maintenance: top-traffic source ──────────────────────────


def test_top_traffic_pages_uses_cloudflare_when_available(monkeypatch):
    """When the CF helper returns rows, _top_traffic_pages must (a) call
    it with ``limit=top_n`` (NOT the previously-broken ``top_n=`` kwarg),
    (b) resolve each ``path`` to its seo_pages doc, and (c) flag the
    summary source as ``"cloudflare"`` so prod can detect when the
    analytics path is actually used."""
    db = _FakeDb()
    p1 = _mk_page("P1", topic="Newton First Law")
    p1["topic_slug"] = "newton-first-law"
    p2 = _mk_page("P2", topic="Algebra")
    p2["topic_slug"] = "algebra"
    db.seo_pages.docs.extend([p1, p2])

    captured: dict[str, object] = {}

    async def fake_get_top_pages_cf(**kwargs):
        captured["kwargs"] = kwargs
        return [
            {"path": "/notes/physics/newton-first-law", "views": 1234, "source": "cloudflare"},
            {"path": "/notes/maths/algebra",            "views":  321, "source": "cloudflare"},
        ]

    fake_mod = types.ModuleType("cloudflare_client")
    fake_mod.get_top_pages_cf = fake_get_top_pages_cf
    monkeypatch.setitem(sys.modules, "cloudflare_client", fake_mod)

    pages, source = _run(linker._top_traffic_pages(db, top_n=5))
    # Correct kwarg used (regression guard for the original bug):
    assert "limit" in captured["kwargs"]
    assert "top_n" not in captured["kwargs"]
    assert captured["kwargs"]["limit"] == 5
    # CF rows resolved into seo_pages docs in traffic order:
    assert [p["id"] for p in pages] == ["P1", "P2"]
    assert source == "cloudflare"


def test_top_traffic_pages_falls_back_to_recency_on_cf_error(monkeypatch):
    """When the CF helper raises (token missing, network down) the
    nightly pass must still return a sensible ``recency_fallback``
    set of pages so the loop continues to do useful work."""
    db = _FakeDb()
    db.seo_pages.docs.extend([
        {**_mk_page("P1", topic="Old"), "updated_at": "2020-01-01T00:00:00+00:00"},
        {**_mk_page("P2", topic="New"), "updated_at": "2026-04-25T00:00:00+00:00"},
    ])

    async def boom(**_kw):
        raise RuntimeError("CF token missing")

    fake_mod = types.ModuleType("cloudflare_client")
    fake_mod.get_top_pages_cf = boom
    monkeypatch.setitem(sys.modules, "cloudflare_client", fake_mod)

    pages, source = _run(linker._top_traffic_pages(db, top_n=2))
    # Fallback path is exercised and returns useful work for the loop.
    assert source == "recency_fallback"
    assert {p["id"] for p in pages} == {"P1", "P2"}


def test_select_candidates_blends_embedding_with_keyword():
    """When embeddings are available, the combined score must prefer a
    candidate that has a moderate keyword score *and* a strong cosine
    over a candidate that only wins on keywords."""
    db = _FakeDb()
    target = _mk_page("T", topic="Newton First Law Motion Inertia")
    a = _mk_page("S_kw", topic="Newton motion law force",  # strong keyword overlap
                 body="<p>Newton motion force law.</p>")
    b = _mk_page("S_emb", topic="Inertia explained simply",  # weaker keyword
                 body="<p>Resting bodies stay at rest.</p>")
    db.seo_pages.docs.extend([target, a, b])

    # Stub embeddings: target points one way, S_emb is identical, S_kw is orthogonal.
    async def _embed(text, *, task_type):
        if "Newton First Law Motion Inertia" in text:
            return [1.0, 0.0]
        if "Inertia explained" in text:
            return [1.0, 0.0]  # cosine = 1.0
        if "Newton motion law force" in text:
            return [0.0, 1.0]  # cosine = 0.0
        return [0.5, 0.5]

    with patch("seo_internal_linker._embed_for_linker", new=_embed):
        out = _run(linker._select_candidate_sources(db, target))
    ids = [d.get("id") for d in out]
    # Both should appear; embedding-strong candidate must rank above
    # the keyword-only candidate after the 0.6 / 0.4 blend.
    assert ids.index("S_emb") < ids.index("S_kw")


# ─── helpers ───────────────────────────────────────────────────────────


def _async_return(value):
    async def _f(*_a, **_kw):
        return value
    return _f


def _async_noop():
    async def _f(*_a, **_kw):
        return None
    return _f
