"""
Syllabus Auto-Linker  —  NEP FYUGP Degree Mode
===============================================
Takes a structured syllabus entry (extracted from a PDF) and automatically:
  1. Finds or creates a Board in db.boards
  2. Finds or creates a Class (semester) in db.classes for that board
  3. Finds or creates a Stream:
     • NEP cross-stream courses (AEC/SEC/MDC/VAC/GE/CC) → stream = paper_type
     • Discipline courses (Major/Minor) → stream = B.Com / B.A / B.Sc based on stream_target
  4. Finds or creates a Subject in db.subjects for that stream
  5. Creates chapters in db.chapters (idempotent)
  6. Returns a LinkResult with all created / matched IDs for the frontend to display

NEP_DEGREE_ONLY = True  →  PDF importer runs exclusively in degree mode.
All board detection defaults to the DEGREE board for college PDFs.
AHSEC/SEBA are still supported but are not the focus.

NEP FYUGP Course Type → Stream mapping
---------------------------------------
AEC  → Ability Enhancement Compulsory Course  (cross-stream, all students)
SEC  → Skill Enhancement Course               (cross-stream)
MDC  → Multidisciplinary Course               (cross-stream)
VAC  → Value-Added Course                     (cross-stream)
GE   → Generic Elective                       (cross-stream)
CC   → Core Course                            (cross-stream)
Major / Minor → B.Com / B.A / B.Sc based on stream_target in PDF
"""

from __future__ import annotations
import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("syllabus_linker")

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

NEP_DEGREE_ONLY = True  # Degree-focused mode — college PDFs default to DEGREE board

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_DEGREE_BOARD_ID = "b2"
_AHSEC_BOARD_ID  = "b1"
_SEBA_BOARD_ID   = "b3"

_DEGREE_BOARD = {"id": _DEGREE_BOARD_ID, "name": "DEGREE",
                 "slug": "degree", "group_name": "AssamBoard",
                 "description": "AssamBoard — Degree (B.A / B.Com / B.Sc)"}
_AHSEC_BOARD  = {"id": _AHSEC_BOARD_ID, "name": "AHSEC",
                 "slug": "ahsec", "group_name": "AssamBoard",
                 "description": "AssamBoard — AHSEC (Class 11–12)"}
_SEBA_BOARD   = {"id": _SEBA_BOARD_ID, "name": "SEBA",
                 "slug": "seba", "group_name": "AssamBoard",
                 "description": "AssamBoard — SEBA (Secondary Education)"}

# Semester number → human class name
_SEM_CLASS_NAMES = {
    1: "Semester 1",  2: "Semester 2",
    3: "Semester 3",  4: "Semester 4",
    5: "Semester 5",  6: "Semester 6",
    7: "Semester 7",  8: "Semester 8",
}

# ── NEP FYUGP cross-stream course types ───────────────────────────────────────
# When paper_type is one of these, the stream IS the course type (not the discipline).
# All student streams (B.Com/B.A/B.Sc) share one stream node per semester.
NEP_COURSE_STREAMS: dict[str, dict] = {
    "aec": {"name": "AEC",   "slug": "aec",   "description": "Ability Enhancement Compulsory Course", "icon": "🧠"},
    "sec": {"name": "SEC",   "slug": "sec",   "description": "Skill Enhancement Course",              "icon": "⚡"},
    "mdc": {"name": "MDC",   "slug": "mdc",   "description": "Multidisciplinary Course",              "icon": "🌐"},
    "vac": {"name": "VAC",   "slug": "vac",   "description": "Value-Added Course",                   "icon": "✨"},
    "ge":  {"name": "GE",    "slug": "ge",    "description": "Generic Elective",                     "icon": "🔄"},
    "cc":  {"name": "CC",    "slug": "cc",    "description": "Core Course",                          "icon": "⭐"},
}

# Discipline-based paper types — stream determined by stream_target (B.Com / B.A / B.Sc)
DISCIPLINE_PAPER_TYPES = {"major", "minor"}

# Discipline stream definitions (used when paper_type is major/minor)
_DISCIPLINE_STREAMS: dict[str, dict] = {
    "bcom":    {"name": "B.Com",   "slug": "bcom",    "description": "Bachelor of Commerce", "icon": "💼"},
    "ba":      {"name": "B.A",     "slug": "ba",      "description": "Bachelor of Arts",     "icon": "📖"},
    "bsc":     {"name": "B.Sc",    "slug": "bsc",     "description": "Bachelor of Science",  "icon": "🔬"},
    "general": {"name": "General", "slug": "general", "description": "General / All streams","icon": "📚"},
    # AHSEC
    "commerce": {"name": "Commerce",    "slug": "commerce",    "description": "Commerce stream", "icon": "💼"},
    "arts":     {"name": "Arts",        "slug": "arts",        "description": "Arts stream",     "icon": "📖"},
    "science":  {"name": "Science",     "slug": "science",     "description": "Science stream",  "icon": "⚗️"},
}

_NOW = lambda: datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SyllabusEntry:
    """One extracted subject from a PDF."""
    board_name:   str
    class_year:   str
    semester:     str
    subject_name: str
    paper_type:   str      # aec | sec | mdc | vac | ge | cc | major | minor
    stream_hint:  str      # "Commerce" / "Arts & Science" / "All" / …
    chapters:     list[str] = field(default_factory=list)
    topics:       list[str] = field(default_factory=list)
    guidelines:   str = ""
    course_code:  str = ""
    credits:      int = 0


@dataclass
class LinkResult:
    board_id:      str
    board_name:    str
    class_id:      str
    class_name:    str
    streams:       list[dict]   # [{stream_id, stream_name}]
    subject_ids:   list[str]
    chapter_count: int
    created_nodes: list[str]


# ──────────────────────────────────────────────────────────────────────────────
# Main linker class
# ──────────────────────────────────────────────────────────────────────────────

class SyllabusLinker:
    def __init__(self, db):
        self._db = db

    async def link(self, entry: SyllabusEntry) -> LinkResult:
        created: list[str] = []

        # 1 — Board
        board_id, board_name = await self._find_or_create_board(entry.board_name, created)

        # 2 — Class (semester)
        class_id, class_name = await self._find_or_create_class(entry, board_id, created)

        # 3 — Streams (NEP type stream or discipline stream)
        stream_keys = _resolve_stream_keys(entry.stream_hint, entry.paper_type, board_id)
        linked_streams: list[dict] = []
        for sk in stream_keys:
            sid, sname = await self._find_or_create_stream(class_id, sk, entry.paper_type, created)
            linked_streams.append({"stream_id": sid, "stream_name": sname})

        # 4 + 5 — Subject + Chapters per stream
        subject_ids: list[str] = []
        for s in linked_streams:
            subj_id = await self._find_or_create_subject(s["stream_id"], entry, created)
            subject_ids.append(subj_id)
            await self._upsert_chapters(subj_id, entry.chapters, created)

        return LinkResult(
            board_id=board_id, board_name=board_name,
            class_id=class_id, class_name=class_name,
            streams=linked_streams, subject_ids=subject_ids,
            chapter_count=len(entry.chapters), created_nodes=created,
        )

    # ── Board ─────────────────────────────────────────────────────────────────

    async def _find_or_create_board(self, board_name_raw: str, created: list) -> tuple[str, str]:
        board_key = _detect_board_key(board_name_raw)
        seed_map = {"degree": _DEGREE_BOARD, "ahsec": _AHSEC_BOARD, "seba": _SEBA_BOARD}
        seed = seed_map.get(board_key)

        if seed:
            doc = await self._db.boards.find_one({"id": seed["id"]})
            if not doc:
                await self._db.boards.insert_one({**seed, "created_at": _NOW()})
                created.append(f"Board: {seed['name']}")
            return seed["id"], seed["name"]

        # Unknown → create as custom autonomous-college board
        slug = _slugify(board_name_raw) or "unknown-board"
        doc = await self._db.boards.find_one({"slug": slug})
        if doc:
            return doc["id"], doc["name"]
        new_id = f"board_{slug[:20]}"
        new_board = {
            "id": new_id, "name": board_name_raw, "slug": slug,
            "group_name": "Autonomous College",
            "description": f"{board_name_raw} — Autonomous Degree College (FYUGP/NEP)",
            "created_at": _NOW(),
        }
        await self._db.boards.insert_one(new_board)
        created.append(f"Board: {board_name_raw}")
        return new_id, board_name_raw

    # ── Class ─────────────────────────────────────────────────────────────────

    async def _find_or_create_class(
        self, entry: SyllabusEntry, board_id: str, created: list
    ) -> tuple[str, str]:
        sem_num = _parse_semester_number(entry.semester or entry.class_year)

        if sem_num:
            class_name = _SEM_CLASS_NAMES.get(sem_num, f"Semester {sem_num}")
            class_slug = f"semester-{sem_num}"
        else:
            class_name = entry.class_year or "Unknown Year"
            class_slug = _slugify(class_name) or "unknown-year"

        doc = await self._db.classes.find_one({"board_id": board_id, "slug": class_slug})
        if doc:
            return doc["id"], doc["name"]

        new_id = f"cls_{board_id}_{class_slug}"
        new_class = {
            "id": new_id, "board_id": board_id,
            "name": class_name, "slug": class_slug,
            "description": f"{class_name} — NEP FYUGP",
            "created_at": _NOW(),
        }
        await self._db.classes.insert_one(new_class)
        created.append(f"Class: {class_name}")
        return new_id, class_name

    # ── Stream ────────────────────────────────────────────────────────────────

    async def _find_or_create_stream(
        self, class_id: str, stream_key: str, paper_type: str, created: list
    ) -> tuple[str, str]:
        # NEP course type stream takes priority
        if stream_key in NEP_COURSE_STREAMS:
            defn = NEP_COURSE_STREAMS[stream_key]
        else:
            defn = _DISCIPLINE_STREAMS.get(stream_key, _DISCIPLINE_STREAMS["general"])

        doc = await self._db.streams.find_one({"class_id": class_id, "slug": defn["slug"]})
        if doc:
            return doc["id"], doc["name"]

        new_id = f"strm_{class_id}_{defn['slug']}"
        new_stream = {"id": new_id, "class_id": class_id, **defn, "created_at": _NOW()}
        await self._db.streams.insert_one(new_stream)
        created.append(f"Stream: {defn['name']}")
        return new_id, defn["name"]

    # ── Subject ───────────────────────────────────────────────────────────────

    async def _find_or_create_subject(
        self, stream_id: str, entry: SyllabusEntry, created: list
    ) -> str:
        slug = _slugify(entry.subject_name)
        doc = await self._db.subjects.find_one({"stream_id": stream_id, "slug": slug})
        if doc:
            return doc["id"]

        icon_map = {
            "physics": "⚡", "chemistry": "🧪", "mathematics": "📐",
            "biology": "🌿", "economics": "📊", "commerce": "💼",
            "accountancy": "💰", "history": "🏺", "geography": "🌍",
            "english": "📚", "political": "🏛️", "computer": "💻",
            "environment": "🌱", "yoga": "🧘", "tourism": "✈️",
            "digital": "💻", "ethics": "🤝", "knowledge": "🪔",
            "marketing": "📣", "finance": "💹", "law": "⚖️",
            "management": "🏢", "statistics": "📈", "data": "🗄️",
        }
        icon = "📄"
        for kw, em in icon_map.items():
            if kw in entry.subject_name.lower():
                icon = em
                break

        new_id = str(uuid.uuid4())
        await self._db.subjects.insert_one({
            "id": new_id, "stream_id": stream_id,
            "name": entry.subject_name, "slug": slug,
            "description": f"{entry.subject_name} — {entry.class_year} {entry.paper_type.upper()}",
            "tags": entry.topics[:5],
            "icon": icon, "gradient": "arts",
            "chapter_count": len(entry.chapters),
            "paper_type": entry.paper_type,
            "course_code": entry.course_code,
            "credits": entry.credits,
            "guidelines": entry.guidelines,
            "status": "published",
            "source": "pdf_import",
            "nep": True,
            "created_at": _NOW(),
        })
        created.append(f"Subject: {entry.subject_name}")
        return new_id

    # ── Chapters ──────────────────────────────────────────────────────────────

    async def _upsert_chapters(
        self, subject_id: str, chapter_titles: list[str], created: list
    ) -> None:
        count = 0
        for i, title in enumerate(chapter_titles, 1):
            slug = _slugify(title)
            if await self._db.chapters.find_one({"subject_id": subject_id, "slug": slug}):
                continue
            await self._db.chapters.insert_one({
                "id": str(uuid.uuid4()),
                "subject_id": subject_id,
                "title": title, "slug": slug,
                "chapter_number": i,
                "content": "", "source": "pdf_import",
                "created_at": _NOW(),
            })
            count += 1
        if count:
            created.append(f"{count} chapters added")


# ──────────────────────────────────────────────────────────────────────────────
# Pure helper functions
# ──────────────────────────────────────────────────────────────────────────────

def _detect_board_key(board_name: str) -> str:
    n = (board_name or "").lower()
    if any(k in n for k in ("ahsec", "higher secondary", "hs board")):
        return "ahsec"
    if any(k in n for k in ("seba", "secondary education", "hslc")):
        return "seba"
    # Everything else (colleges, universities) → DEGREE in NEP_DEGREE_ONLY mode
    return "degree"


def _resolve_stream_keys(stream_hint: str, paper_type: str, board_id: str) -> list[str]:
    """
    Determine stream key(s) for this entry.
    NEP cross-stream types (AEC/SEC/MDC/VAC/GE/CC) → stream = paper_type key
    Discipline types (Major/Minor) → stream determined by stream_hint (B.Com/B.A/B.Sc)
    """
    pt = (paper_type or "").lower().strip()
    h  = (stream_hint or "").lower().strip()

    # NEP cross-stream: the paper_type IS the stream
    if pt in NEP_COURSE_STREAMS:
        return [pt]

    # Discipline courses (Major / Minor) — use stream_hint to pick discipline
    if not h or "all" in h or "general" in h:
        return ["general"]

    keys = []
    if "commerce" in h or "b.com" in h:
        keys.append("bcom")
    if "art" in h or "b.a" in h:
        keys.append("ba")
    if "science" in h or "b.sc" in h:
        keys.append("bsc")
    return keys or ["general"]


def _parse_semester_number(text: str) -> Optional[int]:
    if not text:
        return None
    text = text.lower().strip()
    ordinals = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
                "5th": 5, "6th": 6, "7th": 7, "8th": 8,
                "first": 1, "second": 2, "third": 3, "fourth": 4}
    for word, num in ordinals.items():
        if word in text and "sem" in text:
            return num
    m = re.search(r"sem(?:ester)?[\s\-]*(\d)", text)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 8 else None
    return None


def _slugify(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^\w\s-]", "", t)
    t = re.sub(r"[\s_]+", "-", t)
    t = re.sub(r"-+", "-", t).strip("-")
    return t[:80]
