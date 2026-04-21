"""Syrabit.ai — Educational study superpowers (Phase 3).

Adds the following surfaces on top of the existing Edu Browser stack:

  Quiz generator        POST /api/edu/quiz/generate
  Notebook (notes CRUD) GET/POST /api/edu/notes
                        PATCH/DELETE /api/edu/notes/{note_id}
                        GET /api/edu/notes/export?format=md|csv
  Flashcards (SR)       POST /api/edu/flashcards/build
                        GET  /api/edu/flashcards/due
                        POST /api/edu/flashcards/review
                        GET  /api/edu/flashcards/streak
  Study settings        GET/POST /api/edu/study/settings
  Guardian PIN          POST /api/edu/guardian/pin/set
                        POST /api/edu/guardian/pin/verify
  Voice (STT proxy)     POST /api/edu/stt        (multipart audio → text)
  Voice (status)        GET  /api/edu/voice/status

Storage strategy:
  Authenticated users  → PostgreSQL (asyncpg pool from deps.pg_pool).
  Anonymous users      → identified by `x-anon-id` header (matches the
                         IP-credit model elsewhere). Same PG tables, just
                         a different `actor` discriminator.

The PG schema is created lazily on first use (idempotent CREATE TABLE
IF NOT EXISTS). Keeping it out of `deps.py` avoids touching the global
startup path.
"""
from __future__ import annotations

import io
import csv
import json
import time
import uuid
import hmac
import base64
import hashlib
import logging
import re
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from auth_deps import get_current_user, get_current_user_optional, check_rate_limit
from llm import call_llm_api
from guardrails.prompt_safety import validate_llm_output
import deps
from deps import sarvam_client

logger = logging.getLogger(__name__)
router = APIRouter()

# ───────────────────────── Schema bootstrap ─────────────────────────

_SCHEMA_READY = False

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS edu_notes (
    id            TEXT PRIMARY KEY,
    actor_kind    TEXT NOT NULL,           -- 'user' | 'anon'
    actor         TEXT NOT NULL,
    text          TEXT NOT NULL,
    source_url    TEXT,
    source_title  TEXT,
    chapter_ref   TEXT,
    tags          TEXT[] NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS edu_notes_actor_idx ON edu_notes (actor_kind, actor, created_at DESC);
-- Task #612: stamp the moment an offline note was adopted into a user account
-- so the UI can render a "synced from this device" badge for the first session.
ALTER TABLE edu_notes ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS edu_flashcards (
    id            TEXT PRIMARY KEY,
    actor_kind    TEXT NOT NULL,
    actor         TEXT NOT NULL,
    note_id       TEXT,
    front         TEXT NOT NULL,
    back          TEXT NOT NULL,
    ef            REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 0,
    repetitions   INTEGER NOT NULL DEFAULT 0,
    due_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_reviewed TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS edu_flashcards_due_idx ON edu_flashcards (actor_kind, actor, due_at);
ALTER TABLE edu_flashcards ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS edu_study_settings (
    actor_kind        TEXT NOT NULL,
    actor             TEXT NOT NULL,
    strict_mode       BOOLEAN NOT NULL DEFAULT FALSE,
    guardian_pin_hash TEXT,
    streak_count      INTEGER NOT NULL DEFAULT 0,
    streak_last_day   DATE,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (actor_kind, actor)
);
"""


async def _ensure_schema():
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    if not deps.pg_pool:
        raise HTTPException(status_code=503, detail="storage_unavailable")
    async with deps.pg_pool.acquire() as conn:
        await conn.execute(_SCHEMA_SQL)
    _SCHEMA_READY = True


# ───────────────────────── Helpers ─────────────────────────

def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _actor(request: Request, user) -> tuple[str, str]:
    if user and user.get("id"):
        return "user", user["id"]
    anon = request.headers.get("x-anon-id", "").strip()[:80]
    if anon:
        return "anon", anon
    ip = _client_ip(request)
    return "anon", "ip:" + hashlib.sha256(ip.encode()).hexdigest()[:24]


def _strip_md(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[`*_#>~]+", "", s or "")).strip()


def _note_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "text": row["text"],
        "source_url": row["source_url"] or "",
        "source_title": row["source_title"] or "",
        "chapter_ref": row["chapter_ref"] or "",
        "tags": list(row["tags"] or []),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "claimed_at": row["claimed_at"].isoformat() if row["claimed_at"] else None,
    }


# ───────────────────────── Quiz generator ─────────────────────────

class QuizGenReq(BaseModel):
    context: str = Field("", max_length=12000)
    topic: str = Field("", max_length=300)
    chapter_ref: str = Field("", max_length=300)
    subject_name: str = Field("", max_length=200)
    count: int = Field(7, ge=3, le=10)
    response_lang: str = Field("en", max_length=8)


_QUIZ_SYS = """You are an expert exam-question writer for Indian school students.
Return a STRICT JSON object (no prose, no markdown fences) of the form:
{
  "questions": [
    {
      "q": "Question text (concise, factual, single-best-answer MCQ)",
      "choices": ["A choice", "Another", "Third", "Fourth"],
      "answer": 0,
      "explanation": "1-2 sentence reason for the correct choice."
    }
  ]
}
Rules:
- Exactly 4 choices per question.
- "answer" is the 0-based index of the correct choice.
- Cover key facts/definitions/applications from the supplied context.
- Avoid trick questions; aim for board-exam style clarity.
- Never quote PII, never include personal opinions, never reference Syrabit."""


def _coerce_quiz_payload(raw: str) -> dict:
    """Tolerant JSON parse: strip code fences, trim before/after braces."""
    txt = (raw or "").strip()
    if "```" in txt:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", txt)
        if m:
            txt = m.group(1).strip()
    if "{" in txt and "}" in txt:
        txt = txt[txt.index("{"):txt.rindex("}") + 1]
    try:
        return json.loads(txt)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"quiz_parse_error: {e}")


QUIZ_DAILY_CAP = 200          # Task #615: per-actor LLM call budget per UTC day.
QUIZ_DAY_WINDOW_SEC = 86400


def _quiz_daily_key(kind: str, actor: str) -> str:
    """Stable rl2 key for the per-actor daily quiz cap. Kept in one place
    so the admin read/reset endpoints derive the exact same string."""
    return f"edu_quiz_day:{kind}:{actor}"


@router.post("/edu/quiz/generate")
async def quiz_generate(req: QuizGenReq, request: Request,
                        user=Depends(get_current_user_optional)):
    ip = _client_ip(request)
    if not check_rate_limit(f"edu_quiz:{ip}", max_requests=15, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many quiz requests; try again later.")
    # Task #615: even within the per-IP burst limit, cap the absolute number
    # of LLM-backed quiz generations any single actor (signed-in user OR
    # device anon-id, falling back to a salted IP hash) can request per UTC
    # day. This bounds worst-case spend for grinders behind the burst limit.
    kind, actor = _actor(request, user)
    if not check_rate_limit(_quiz_daily_key(kind, actor),
                            max_requests=QUIZ_DAILY_CAP,
                            window_seconds=QUIZ_DAY_WINDOW_SEC):
        raise HTTPException(
            status_code=429,
            detail={
                "error": "quiz_daily_cap",
                "limit": QUIZ_DAILY_CAP,
                "scope": "day",
                "resets_at": "midnight UTC",
                "message": (
                    f"Daily quiz limit reached ({QUIZ_DAILY_CAP}/day). "
                    f"Try again after midnight UTC."
                ),
            },
            headers={
                "Retry-After": "3600",
                "X-RateLimit-Limit": str(QUIZ_DAILY_CAP),
                "X-RateLimit-Scope": "day",
            },
        )
    ctx_text = (req.context or "").strip()
    if not ctx_text and not req.topic:
        raise HTTPException(status_code=400, detail="context or topic required")
    if len(ctx_text) > 12000:
        ctx_text = ctx_text[:12000]
    user_msg_parts = [
        f"Subject: {req.subject_name}" if req.subject_name else "",
        f"Chapter: {req.chapter_ref}" if req.chapter_ref else "",
        f"Topic focus: {req.topic}" if req.topic else "",
        f"Generate exactly {req.count} MCQs.",
    ]
    if req.response_lang and req.response_lang.lower().startswith("as"):
        user_msg_parts.append("Write the questions, choices and explanations in Assamese (as-IN).")
    if ctx_text:
        user_msg_parts.append("\n--- SOURCE TEXT ---\n" + ctx_text)
    messages = [
        {"role": "system", "content": _QUIZ_SYS},
        {"role": "user",   "content": "\n".join([p for p in user_msg_parts if p])},
    ]
    try:
        raw = await call_llm_api(messages, max_tokens=2000)
    except Exception as e:
        logger.warning(f"[edu_quiz] LLM call failed: {e}")
        raise HTTPException(status_code=502, detail="quiz_llm_failed")
    payload = _coerce_quiz_payload(raw)
    questions = payload.get("questions") or []
    cleaned: list[dict] = []
    for q in questions[: req.count]:
        if not isinstance(q, dict):
            continue
        choices = q.get("choices") or []
        if not (isinstance(choices, list) and len(choices) == 4):
            continue
        try:
            ans = int(q.get("answer", 0))
        except Exception:
            ans = 0
        if ans < 0 or ans > 3:
            ans = 0
        cleaned.append({
            "id": str(uuid.uuid4()),
            "q": str(q.get("q", "")).strip()[:500],
            "choices": [str(c).strip()[:240] for c in choices],
            "answer": ans,
            "explanation": str(q.get("explanation", "")).strip()[:600],
        })
    if not cleaned:
        raise HTTPException(status_code=502, detail="quiz_no_questions")
    # Light safety pass on the generated text.
    flat = " ".join(c["q"] + " " + c["explanation"] for c in cleaned)
    ok, _why = validate_llm_output(flat)
    if not ok:
        raise HTTPException(status_code=502, detail="quiz_safety_block")
    return {"ok": True, "questions": cleaned, "count": len(cleaned)}


# ───────────────────────── Notebook (notes) ─────────────────────────

class NoteCreateReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    source_url: str = Field("", max_length=2048)
    source_title: str = Field("", max_length=400)
    chapter_ref: str = Field("", max_length=400)
    tags: List[str] = Field(default_factory=list)


class NotePatchReq(BaseModel):
    text: Optional[str] = Field(None, max_length=8000)
    tags: Optional[List[str]] = None


def _norm_tags(tags) -> list[str]:
    if not tags:
        return []
    out: list[str] = []
    for t in tags:
        s = str(t).strip().lower()
        if not s:
            continue
        s = re.sub(r"[^a-z0-9\-_]+", "-", s)[:32]
        if s and s not in out:
            out.append(s)
        if len(out) >= 12:
            break
    return out


@router.post("/edu/notes")
async def create_note(req: NoteCreateReq, request: Request,
                      user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    if not check_rate_limit(f"edu_note:{actor}", max_requests=120, window_seconds=300):
        raise HTTPException(status_code=429, detail="Save rate limit exceeded.")
    nid = str(uuid.uuid4())
    tags = _norm_tags(req.tags)
    async with deps.pg_pool.acquire() as conn:
        cnt = await conn.fetchval(
            "SELECT COUNT(*) FROM edu_notes WHERE actor_kind=$1 AND actor=$2",
            kind, actor,
        )
        if cnt is not None and cnt >= 2000:
            raise HTTPException(status_code=400, detail="notebook_full")
        row = await conn.fetchrow(
            """INSERT INTO edu_notes (id, actor_kind, actor, text, source_url,
                  source_title, chapter_ref, tags)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               RETURNING *""",
            nid, kind, actor, req.text.strip(), req.source_url.strip(),
            req.source_title.strip(), req.chapter_ref.strip(), tags,
        )
    return {"ok": True, "note": _note_row_to_dict(row)}


@router.get("/edu/notes")
async def list_notes(request: Request, q: str = "", tag: str = "",
                     limit: int = 100, offset: int = 0,
                     user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    sql = ["SELECT * FROM edu_notes WHERE actor_kind=$1 AND actor=$2"]
    args: list[Any] = [kind, actor]
    if q:
        args.append(f"%{q.strip()[:200]}%")
        sql.append(f"AND (text ILIKE ${len(args)} OR source_title ILIKE ${len(args)})")
    if tag:
        args.append(_norm_tags([tag]))
        sql.append(f"AND tags && ${len(args)}::text[]")
    sql.append("ORDER BY created_at DESC")
    args.extend([limit, offset])
    sql.append(f"LIMIT ${len(args) - 1} OFFSET ${len(args)}")
    async with deps.pg_pool.acquire() as conn:
        rows = await conn.fetch(" ".join(sql), *args)
    return {"ok": True, "notes": [_note_row_to_dict(r) for r in rows], "count": len(rows)}


@router.patch("/edu/notes/{note_id}")
async def patch_note(note_id: str, req: NotePatchReq, request: Request,
                     user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    sets, args = [], []
    if req.text is not None:
        args.append(req.text.strip())
        sets.append(f"text=${len(args)}")
    if req.tags is not None:
        args.append(_norm_tags(req.tags))
        sets.append(f"tags=${len(args)}")
    if not sets:
        raise HTTPException(status_code=400, detail="no_fields")
    sets.append("updated_at=NOW()")
    args.extend([note_id, kind, actor])
    async with deps.pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE edu_notes SET {', '.join(sets)} WHERE id=${len(args)-2} "
            f"AND actor_kind=${len(args)-1} AND actor=${len(args)} RETURNING *",
            *args,
        )
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True, "note": _note_row_to_dict(row)}


@router.delete("/edu/notes/{note_id}")
async def delete_note(note_id: str, request: Request,
                      user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    async with deps.pg_pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM edu_notes WHERE id=$1 AND actor_kind=$2 AND actor=$3",
            note_id, kind, actor,
        )
    return {"ok": True, "deleted": result.endswith(" 1")}


@router.get("/edu/notes/export")
async def export_notes(request: Request, format: str = "md",
                       user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    async with deps.pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM edu_notes WHERE actor_kind=$1 AND actor=$2 "
            "ORDER BY created_at DESC",
            kind, actor,
        )
    fmt = (format or "md").lower()
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["created_at", "text", "source_title", "source_url",
                    "chapter_ref", "tags"])
        for r in rows:
            w.writerow([
                r["created_at"].isoformat(), r["text"], r["source_title"] or "",
                r["source_url"] or "", r["chapter_ref"] or "",
                ",".join(r["tags"] or []),
            ])
        return StreamingResponse(
            iter([buf.getvalue()]), media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=syrabit-notebook.csv"},
        )
    # Markdown (default)
    lines = ["# Syrabit Notebook",
             f"_Exported {datetime.now(timezone.utc).isoformat()}_", ""]
    for r in rows:
        ttl = r["source_title"] or r["chapter_ref"] or "Note"
        lines.append(f"## {ttl}")
        lines.append(f"_Saved {r['created_at'].isoformat()}_")
        if r["tags"]:
            lines.append("Tags: " + ", ".join(f"`{t}`" for t in r["tags"]))
        if r["source_url"]:
            lines.append(f"Source: <{r['source_url']}>")
        lines.append("")
        lines.append("> " + (r["text"] or "").replace("\n", "\n> "))
        lines.append("")
    body = "\n".join(lines)
    return StreamingResponse(
        iter([body]), media_type="text/markdown",
        headers={"Content-Disposition": "attachment; filename=syrabit-notebook.md"},
    )


# ───────────────────────── Flashcards (SM-2 lite) ─────────────────────────

class CardBuildReq(BaseModel):
    note_ids: Optional[List[str]] = None  # None → build for ALL un-carded notes


def _flashcard_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "note_id": row["note_id"] or "",
        "front": row["front"],
        "back": row["back"],
        "ef": float(row["ef"]),
        "interval_days": int(row["interval_days"]),
        "repetitions": int(row["repetitions"]),
        "due_at": row["due_at"].isoformat(),
        "last_reviewed": row["last_reviewed"].isoformat() if row["last_reviewed"] else None,
        "claimed_at": row["claimed_at"].isoformat() if row["claimed_at"] else None,
    }


def _split_front_back(text: str) -> tuple[str, str]:
    """Heuristic: turn a note into (front, back). Definition lines like
    `X — Y` or `X: Y` give a Q/A split; otherwise we make a cloze-style
    "What is the key idea?" front."""
    s = (text or "").strip()
    m = re.match(r"^(.{3,80}?)[\s]*[—:\-–][\s]+(.{2,400})$", s)
    if m:
        return m.group(1).strip()[:200], m.group(2).strip()[:400]
    # Sentence-based fallback: first sentence becomes back, prompt fixed.
    first = re.split(r"(?<=[.!?])\s+", s)[0]
    return ("Recall this idea:", first[:400] or s[:400])


@router.post("/edu/flashcards/build")
async def build_flashcards(req: CardBuildReq, request: Request,
                           user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    async with deps.pg_pool.acquire() as conn:
        if req.note_ids:
            rows = await conn.fetch(
                "SELECT * FROM edu_notes WHERE actor_kind=$1 AND actor=$2 "
                "AND id = ANY($3::text[])",
                kind, actor, req.note_ids,
            )
        else:
            rows = await conn.fetch(
                "SELECT n.* FROM edu_notes n LEFT JOIN edu_flashcards f "
                "ON f.note_id = n.id WHERE n.actor_kind=$1 AND n.actor=$2 "
                "AND f.id IS NULL ORDER BY n.created_at DESC LIMIT 200",
                kind, actor,
            )
        created = 0
        for n in rows:
            front, back = _split_front_back(n["text"])
            await conn.execute(
                """INSERT INTO edu_flashcards (id, actor_kind, actor, note_id,
                       front, back, due_at)
                   VALUES ($1,$2,$3,$4,$5,$6,NOW())""",
                str(uuid.uuid4()), kind, actor, n["id"], front, back,
            )
            created += 1
    return {"ok": True, "created": created}


@router.get("/edu/flashcards/due")
async def due_flashcards(request: Request, limit: int = 30,
                         user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    limit = max(1, min(limit, 100))
    async with deps.pg_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM edu_flashcards
               WHERE actor_kind=$1 AND actor=$2 AND due_at <= NOW()
               ORDER BY due_at ASC LIMIT $3""",
            kind, actor, limit,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM edu_flashcards WHERE actor_kind=$1 AND actor=$2",
            kind, actor,
        )
    return {
        "ok": True,
        "cards": [_flashcard_row_to_dict(r) for r in rows],
        "total": int(total or 0),
    }


class CardReviewReq(BaseModel):
    card_id: str
    quality: int = Field(..., ge=0, le=5)  # SM-2 grade


def _sm2_step(ef: float, reps: int, interval: int, q: int) -> tuple[float, int, int]:
    """Apply one SM-2 step. q∈[0,5]: <3 = forgot."""
    if q < 3:
        return max(1.3, ef - 0.2), 0, 1
    new_ef = max(1.3, ef + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_reps = reps + 1
    if new_reps == 1:
        new_int = 1
    elif new_reps == 2:
        new_int = 6
    else:
        new_int = max(1, round(interval * new_ef))
    return new_ef, new_reps, new_int


@router.post("/edu/flashcards/review")
async def review_flashcard(req: CardReviewReq, request: Request,
                           user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    async with deps.pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM edu_flashcards WHERE id=$1 AND actor_kind=$2 AND actor=$3",
            req.card_id, kind, actor,
        )
        if not row:
            raise HTTPException(status_code=404, detail="card_not_found")
        ef, reps, interval = _sm2_step(
            float(row["ef"]), int(row["repetitions"]),
            int(row["interval_days"]), req.quality,
        )
        due_at = datetime.now(timezone.utc) + timedelta(days=interval)
        updated = await conn.fetchrow(
            """UPDATE edu_flashcards SET ef=$1, repetitions=$2, interval_days=$3,
                  due_at=$4, last_reviewed=NOW()
               WHERE id=$5 RETURNING *""",
            ef, reps, interval, due_at, req.card_id,
        )
        # Streak update
        today = date.today()
        s = await conn.fetchrow(
            "SELECT * FROM edu_study_settings WHERE actor_kind=$1 AND actor=$2",
            kind, actor,
        )
        if s is None:
            await conn.execute(
                """INSERT INTO edu_study_settings (actor_kind, actor, streak_count,
                      streak_last_day) VALUES ($1,$2,1,$3)""",
                kind, actor, today,
            )
            streak = 1
        else:
            last = s["streak_last_day"]
            if last == today:
                streak = int(s["streak_count"] or 0)
            elif last and (today - last).days == 1:
                streak = int(s["streak_count"] or 0) + 1
                await conn.execute(
                    "UPDATE edu_study_settings SET streak_count=$1, streak_last_day=$2 "
                    "WHERE actor_kind=$3 AND actor=$4",
                    streak, today, kind, actor,
                )
            else:
                streak = 1
                await conn.execute(
                    "UPDATE edu_study_settings SET streak_count=1, streak_last_day=$1 "
                    "WHERE actor_kind=$2 AND actor=$3",
                    today, kind, actor,
                )
    return {"ok": True, "card": _flashcard_row_to_dict(updated), "streak": streak}


@router.get("/edu/flashcards/streak")
async def flashcards_streak(request: Request,
                            user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    async with deps.pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT streak_count, streak_last_day FROM edu_study_settings "
            "WHERE actor_kind=$1 AND actor=$2",
            kind, actor,
        )
    if not row:
        return {"ok": True, "streak": 0, "last_day": None}
    return {"ok": True, "streak": int(row["streak_count"] or 0),
            "last_day": row["streak_last_day"].isoformat() if row["streak_last_day"] else None}


# ───────────────────────── Settings + guardian PIN ─────────────────────────

class SettingsReq(BaseModel):
    strict_mode: Optional[bool] = None


def _hash_pin(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 50_000).hex()


@router.get("/edu/study/settings")
async def get_study_settings(request: Request,
                             user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    async with deps.pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM edu_study_settings WHERE actor_kind=$1 AND actor=$2",
            kind, actor,
        )
    return {
        "ok": True,
        "strict_mode": bool(row and row["strict_mode"]),
        "guardian_locked": bool(row and row["guardian_pin_hash"]),
        "streak": int(row["streak_count"]) if row else 0,
    }


@router.post("/edu/study/settings")
async def set_study_settings(req: SettingsReq, request: Request,
                             pin: str = "", user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    async with deps.pg_pool.acquire() as conn:
        cur = await conn.fetchrow(
            "SELECT guardian_pin_hash FROM edu_study_settings WHERE actor_kind=$1 AND actor=$2",
            kind, actor,
        )
        # If a PIN exists and we are turning Strict Mode OFF, require it.
        if cur and cur["guardian_pin_hash"] and req.strict_mode is False:
            if not pin:
                raise HTTPException(status_code=403, detail="pin_required")
            salt = f"{kind}:{actor}"
            if not hmac.compare_digest(_hash_pin(pin, salt), cur["guardian_pin_hash"]):
                raise HTTPException(status_code=403, detail="bad_pin")
        await conn.execute(
            """INSERT INTO edu_study_settings (actor_kind, actor, strict_mode)
               VALUES ($1,$2,COALESCE($3, FALSE))
               ON CONFLICT (actor_kind, actor)
               DO UPDATE SET strict_mode=COALESCE($3, edu_study_settings.strict_mode),
                             updated_at=NOW()""",
            kind, actor, req.strict_mode,
        )
    return {"ok": True}


class PinSetReq(BaseModel):
    new_pin: str = Field(..., min_length=4, max_length=12)
    current_pin: str = Field("", max_length=12)


@router.post("/edu/guardian/pin/set")
async def guardian_pin_set(req: PinSetReq, request: Request,
                           user=Depends(get_current_user_optional)):
    await _ensure_schema()
    if not req.new_pin.isdigit():
        raise HTTPException(status_code=400, detail="numeric_pin_required")
    kind, actor = _actor(request, user)
    salt = f"{kind}:{actor}"
    async with deps.pg_pool.acquire() as conn:
        cur = await conn.fetchrow(
            "SELECT guardian_pin_hash FROM edu_study_settings "
            "WHERE actor_kind=$1 AND actor=$2",
            kind, actor,
        )
        if cur and cur["guardian_pin_hash"]:
            if not req.current_pin:
                raise HTTPException(status_code=403, detail="current_pin_required")
            if not hmac.compare_digest(_hash_pin(req.current_pin, salt),
                                       cur["guardian_pin_hash"]):
                raise HTTPException(status_code=403, detail="bad_pin")
        new_hash = _hash_pin(req.new_pin, salt)
        await conn.execute(
            """INSERT INTO edu_study_settings (actor_kind, actor, guardian_pin_hash)
               VALUES ($1,$2,$3)
               ON CONFLICT (actor_kind, actor)
               DO UPDATE SET guardian_pin_hash=$3, updated_at=NOW()""",
            kind, actor, new_hash,
        )
    return {"ok": True}


class PinVerifyReq(BaseModel):
    pin: str = Field(..., min_length=4, max_length=12)


@router.post("/edu/guardian/pin/verify")
async def guardian_pin_verify(req: PinVerifyReq, request: Request,
                              user=Depends(get_current_user_optional)):
    await _ensure_schema()
    kind, actor = _actor(request, user)
    # Task #594: rate-limit PIN verify per actor so an attacker can't
    # brute-force a 4-digit PIN (10⁴ space) in seconds. 8 attempts per
    # 5 minutes is well above any legitimate guardian flow but caps a
    # brute-force run at a few attempts per window.
    if not check_rate_limit(f"edu_pin_verify:{kind}:{actor}",
                            max_requests=8, window_seconds=300):
        raise HTTPException(status_code=429, detail="pin_verify_rate_limited")
    salt = f"{kind}:{actor}"
    async with deps.pg_pool.acquire() as conn:
        cur = await conn.fetchrow(
            "SELECT guardian_pin_hash FROM edu_study_settings "
            "WHERE actor_kind=$1 AND actor=$2",
            kind, actor,
        )
    if not cur or not cur["guardian_pin_hash"]:
        return {"ok": True, "valid": True, "set": False}
    valid = hmac.compare_digest(_hash_pin(req.pin, salt), cur["guardian_pin_hash"])
    return {"ok": True, "valid": valid, "set": True}


# ───────────────────────── Anon → user sync ─────────────────────────

@router.post("/edu/sync/claim")
async def claim_anon_data(request: Request, user=Depends(get_current_user)):
    """Reassign notes / flashcards / settings created under the caller's
    anonymous device id (`x-anon-id`) to their now signed-in user id.

    Idempotent: rerunning after a successful claim returns zero counts
    because the anon rows have already been moved to the user actor.
    """
    await _ensure_schema()
    anon = request.headers.get("x-anon-id", "").strip()[:80]
    user_id = user.get("id") if isinstance(user, dict) else None
    if not anon or not user_id or anon == user_id:
        return {"ok": True, "notes": 0, "flashcards": 0,
                "settings_merged": False}
    notes_count = 0
    cards_count = 0
    settings_merged = False
    pin_dropped = False
    async with deps.pg_pool.acquire() as conn:
        async with conn.transaction():
            notes_res = await conn.execute(
                "UPDATE edu_notes SET actor_kind='user', actor=$1, "
                "claimed_at=NOW() "
                "WHERE actor_kind='anon' AND actor=$2",
                user_id, anon,
            )
            cards_res = await conn.execute(
                "UPDATE edu_flashcards SET actor_kind='user', actor=$1, "
                "claimed_at=NOW() "
                "WHERE actor_kind='anon' AND actor=$2",
                user_id, anon,
            )
            anon_settings = await conn.fetchrow(
                "SELECT * FROM edu_study_settings "
                "WHERE actor_kind='anon' AND actor=$1",
                anon,
            )
            anon_had_pin = bool(anon_settings and anon_settings["guardian_pin_hash"])
            if anon_settings:
                user_settings = await conn.fetchrow(
                    "SELECT * FROM edu_study_settings "
                    "WHERE actor_kind='user' AND actor=$1",
                    user_id,
                )
                anon_strict = bool(anon_settings["strict_mode"])
                anon_streak = int(anon_settings["streak_count"] or 0)
                anon_last = anon_settings["streak_last_day"]
                if not user_settings:
                    # Adopt the anon strict-mode + streak. The guardian
                    # PIN hash is salted with the anon actor id so it
                    # would no longer verify after re-salting; drop it
                    # rather than carry an unusable hash forward.
                    await conn.execute(
                        """INSERT INTO edu_study_settings (actor_kind, actor,
                              strict_mode, guardian_pin_hash, streak_count,
                              streak_last_day)
                           VALUES ('user',$1,$2,NULL,$3,$4)""",
                        user_id, anon_strict, anon_streak, anon_last,
                    )
                    settings_merged = True
                else:
                    # Merge into existing user settings so signed-out
                    # changes are not silently lost.
                    user_strict = bool(user_settings["strict_mode"])
                    user_streak = int(user_settings["streak_count"] or 0)
                    user_last = user_settings["streak_last_day"]
                    # Strict Mode: take the safer (stricter) setting.
                    merged_strict = user_strict or anon_strict
                    # Streak: keep the longer chain; tie-break with the
                    # more recent activity day so the streak's "last
                    # day" stays accurate for the daily-rollover logic.
                    if anon_streak > user_streak:
                        merged_streak, merged_last = anon_streak, anon_last
                    elif anon_streak < user_streak:
                        merged_streak, merged_last = user_streak, user_last
                    else:
                        merged_streak = user_streak
                        if user_last and anon_last:
                            merged_last = max(user_last, anon_last)
                        else:
                            merged_last = user_last or anon_last
                    changed = (
                        merged_strict != user_strict
                        or merged_streak != user_streak
                        or merged_last != user_last
                    )
                    if changed:
                        await conn.execute(
                            """UPDATE edu_study_settings
                               SET strict_mode=$1, streak_count=$2,
                                   streak_last_day=$3, updated_at=NOW()
                               WHERE actor_kind='user' AND actor=$4""",
                            merged_strict, merged_streak, merged_last, user_id,
                        )
                        settings_merged = True
                await conn.execute(
                    "DELETE FROM edu_study_settings "
                    "WHERE actor_kind='anon' AND actor=$1",
                    anon,
                )
            # Task #611: signal to the client that the parental PIN
            # could not be migrated. The PIN hash is salted with the
            # actor id, so a hash created under the anon device id
            # can never be verified once the actor flips to the user.
            # Surface this so the UI can prompt the parent to set a
            # new PIN, instead of silently leaving Strict Mode without
            # a usable lock.
            if anon_had_pin:
                final = await conn.fetchrow(
                    "SELECT strict_mode, guardian_pin_hash FROM edu_study_settings "
                    "WHERE actor_kind='user' AND actor=$1",
                    user_id,
                )
                if final and bool(final["strict_mode"]) and not final["guardian_pin_hash"]:
                    pin_dropped = True
    try:
        notes_count = int(notes_res.split()[-1])
    except Exception:
        notes_count = 0
    try:
        cards_count = int(cards_res.split()[-1])
    except Exception:
        cards_count = 0
    return {"ok": True, "notes": notes_count, "flashcards": cards_count,
            "settings_merged": settings_merged, "pin_dropped": pin_dropped}


# ───────────────────────── Voice (STT + status) ─────────────────────────

@router.get("/edu/voice/status")
async def voice_status():
    return {
        "ok": True,
        "tts_enabled": sarvam_client is not None,
        "stt_enabled": sarvam_client is not None,
        "languages": ["en-IN", "as-IN", "hi-IN", "bn-IN"],
        "browser_stt_recommended": True,
    }


@router.post("/edu/stt")
async def edu_stt(audio: UploadFile = File(...), language: str = Form("en-IN"),
                  request: Request = None, user=Depends(get_current_user_optional)):
    """Server-side fallback STT via Sarvam Saaras. Browser SpeechRecognition
    is preferred on the client; this exists for browsers without it."""
    if sarvam_client is None:
        raise HTTPException(status_code=503, detail="stt_unavailable")
    if request is not None:
        ip = _client_ip(request)
        if not check_rate_limit(f"edu_stt:{ip}", max_requests=30, window_seconds=60):
            raise HTTPException(status_code=429, detail="STT rate limit exceeded.")
    body = await audio.read()
    if not body or len(body) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="audio_size_invalid")
    files = {"file": (audio.filename or "speech.wav",
                      body, audio.content_type or "audio/wav")}
    data = {"language_code": language or "en-IN", "model": "saaras:v2"}
    try:
        resp = await sarvam_client.post("/speech-to-text", files=files, data=data)
    except Exception as e:
        logger.warning(f"[edu_stt] sarvam call failed: {e}")
        raise HTTPException(status_code=502, detail="stt_provider_failed")
    if resp.status_code >= 400:
        logger.warning(f"[edu_stt] provider {resp.status_code}: {resp.text[:300]}")
        raise HTTPException(status_code=502, detail="stt_provider_error")
    payload = resp.json()
    text = payload.get("transcript") or payload.get("text") or ""
    return {"ok": True, "text": text, "language": payload.get("language_code", language)}


__all__ = ["router"]
