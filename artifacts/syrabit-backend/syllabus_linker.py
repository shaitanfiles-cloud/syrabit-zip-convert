"""
Syllabus Auto-Linker
====================
Takes a structured syllabus entry (extracted from a PDF) and automatically:
  1. Finds or creates a Board in db.boards
  2. Finds or creates a Class (semester / year) in db.classes for that board
  3. Finds or creates a Stream (B.Com / B.A / B.Sc / General / Arts / Commerce / Science…)
     in db.streams for that class — VAC/MDC "All" courses create entries under all streams
  4. Finds or creates a Subject in db.subjects for that stream
  5. Creates chapters in db.chapters (idempotent)
  6. Returns a SyllabusLinkResult with all created / matched IDs for the frontend to display

Board detection heuristics
---------------------------
- College name in PDF → mapped to DEGREE board (any autonomous / affiliated college in Assam)
- AHSEC / Higher Secondary in name → AHSEC board
- SEBA / Secondary in name → SEBA board
- Gauhati University / Dibrugarh University / Cotton University → DEGREE board

Semester mapping
----------------
"Semester 1" / "1st Semester" / "Sem 1" → class slug "semester-1"  (1st Year Sem 1)
"Semester 2"                             → class slug "semester-2"  (1st Year Sem 2)
… up to Semester 8                       (4th Year FYUGP)

Stream mapping
--------------
"Commerce" / "B.Com"         → B.Com
"Arts" / "B.A"               → B.A
"Science" / "B.Sc"           → B.Sc
"All" / "General"            → General (cross-stream; also linked to all three)
"Arts & Science"             → creates under both B.A and B.Sc
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
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_DEGREE_BOARD_ID   = "b2"   # from SEED_DATA
_AHSEC_BOARD_ID    = "b1"
_SEBA_BOARD_ID     = "b3"

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

# Stream key → canonical stream definition
_STREAM_DEFS = {
    "bcom":    {"name": "B.Com",    "slug": "bcom",    "description": "Bachelor of Commerce", "icon": "💼"},
    "ba":      {"name": "B.A",      "slug": "ba",      "description": "Bachelor of Arts",     "icon": "📖"},
    "bsc":     {"name": "B.Sc",     "slug": "bsc",     "description": "Bachelor of Science",  "icon": "🔬"},
    "general": {"name": "General",  "slug": "general", "description": "General / All streams","icon": "📚"},
    # HS streams
    "commerce":{"name": "Commerce", "slug": "commerce","description": "Commerce stream",      "icon": "💼"},
    "arts":    {"name": "Arts",     "slug": "arts",    "description": "Arts stream",          "icon": "📖"},
    "science": {"name": "Science",  "slug": "science", "description": "Science stream",       "icon": "⚗️"},
}

# SEBA / AHSEC year-class fallback mapping
_YEAR_CLASS_MAP = {
    "hs 1st year": "c1", "hs 2nd year": "c2",
    "class 9": "c5",     "class 10": "c6",
}

_NOW = lambda: datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SyllabusEntry:
    """One extracted subject from a PDF."""
    board_name:   str
    class_year:   str       # e.g. "1st Year", "Semester 1", "HS 1st Year"
    semester:     str       # e.g. "Semester 1", "Semester 2", ""
    subject_name: str
    paper_type:   str       # major | minor | mdc | vac
    stream_hint:  str       # "Commerce" / "Arts & Science" / "All" / …
    chapters:     list[str] = field(default_factory=list)
    topics:       list[str] = field(default_factory=list)
    guidelines:   str = ""
    course_code:  str = ""
    credits:      int = 0


@dataclass
class LinkResult:
    board_id:    str
    board_name:  str
    class_id:    str
    class_name:  str
    streams:     list[dict]    # [{stream_id, stream_name}] — may be >1 for "All"
    subject_ids: list[str]     # one per stream
    chapter_count: int
    created_nodes: list[str]   # human-readable list of what was created


# ──────────────────────────────────────────────────────────────────────────────
# Main linker class
# ──────────────────────────────────────────────────────────────────────────────

class SyllabusLinker:
    def __init__(self, db):
        self._db = db

    async def link(self, entry: SyllabusEntry) -> LinkResult:
        created = []

        # 1 — Board
        board_id, board_name = await self._find_or_create_board(entry.board_name, created)

        # 2 — Class (semester / year)
        class_id, class_name = await self._find_or_create_class(
            entry, board_id, created
        )

        # 3 — Streams
        stream_keys = _resolve_stream_keys(entry.stream_hint, board_id)
        linked_streams: list[dict] = []
        for sk in stream_keys:
            sid, sname = await self._find_or_create_stream(class_id, sk, created)
            linked_streams.append({"stream_id": sid, "stream_name": sname})

        # 4 + 5 — Subject + Chapters for each stream
        subject_ids = []
        for s in linked_streams:
            subj_id = await self._find_or_create_subject(
                s["stream_id"], entry, created
            )
            subject_ids.append(subj_id)
            await self._upsert_chapters(subj_id, entry.chapters, created)

        return LinkResult(
            board_id=board_id,
            board_name=board_name,
            class_id=class_id,
            class_name=class_name,
            streams=linked_streams,
            subject_ids=subject_ids,
            chapter_count=len(entry.chapters),
            created_nodes=created,
        )

    # ── Board ─────────────────────────────────────────────────────────────────

    async def _find_or_create_board(self, board_name_raw: str, created: list) -> tuple[str, str]:
        board_key = _detect_board_key(board_name_raw)
        seed = {"degree": _DEGREE_BOARD, "ahsec": _AHSEC_BOARD, "seba": _SEBA_BOARD}.get(board_key)

        if seed:
            doc = await self._db.boards.find_one({"id": seed["id"]})
            if not doc:
                await self._db.boards.insert_one({**seed, "created_at": _NOW()})
                created.append(f"Board: {seed['name']}")
            return seed["id"], seed["name"]

        # Unknown board → create as custom DEGREE-affiliated board
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
            # Fall back to class_year text
            class_name = entry.class_year or "Unknown Year"
            class_slug = _slugify(class_name) or "unknown-year"

        doc = await self._db.classes.find_one({"board_id": board_id, "slug": class_slug})
        if doc:
            return doc["id"], doc["name"]

        # Create
        new_id = f"cls_{board_id}_{class_slug}"
        new_class = {
            "id": new_id, "board_id": board_id,
            "name": class_name, "slug": class_slug,
            "description": f"{class_name} — {board_id}",
            "created_at": _NOW(),
        }
        await self._db.classes.insert_one(new_class)
        created.append(f"Class: {class_name}")
        return new_id, class_name

    # ── Stream ────────────────────────────────────────────────────────────────

    async def _find_or_create_stream(
        self, class_id: str, stream_key: str, created: list
    ) -> tuple[str, str]:
        defn = _STREAM_DEFS.get(stream_key, _STREAM_DEFS["general"])
        doc = await self._db.streams.find_one({"class_id": class_id, "slug": defn["slug"]})
        if doc:
            return doc["id"], doc["name"]

        new_id = f"strm_{class_id}_{defn['slug']}"
        new_stream = {
            "id": new_id, "class_id": class_id,
            **defn,
            "created_at": _NOW(),
        }
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
        }
        icon = "📄"
        for kw, em in icon_map.items():
            if kw in entry.subject_name.lower():
                icon = em
                break

        new_id = str(uuid.uuid4())
        subj_doc = {
            "id": new_id, "stream_id": stream_id,
            "name": entry.subject_name, "slug": slug,
            "description": f"{entry.subject_name} — {entry.class_year} {entry.paper_type.upper()} paper",
            "tags": entry.topics[:5],
            "icon": icon,
            "gradient": "arts",
            "chapter_count": len(entry.chapters),
            "paper_type": entry.paper_type,
            "course_code": entry.course_code,
            "credits": entry.credits,
            "guidelines": entry.guidelines,
            "status": "published",
            "source": "pdf_import",
            "created_at": _NOW(),
        }
        await self._db.subjects.insert_one(subj_doc)
        created.append(f"Subject: {entry.subject_name}")
        return new_id

    # ── Chapters ──────────────────────────────────────────────────────────────

    async def _upsert_chapters(
        self, subject_id: str, chapter_titles: list[str], created: list
    ) -> None:
        for i, title in enumerate(chapter_titles, 1):
            slug = _slugify(title)
            existing = await self._db.chapters.find_one({"subject_id": subject_id, "slug": slug})
            if existing:
                continue
            await self._db.chapters.insert_one({
                "id": str(uuid.uuid4()),
                "subject_id": subject_id,
                "title": title,
                "slug": slug,
                "chapter_number": i,
                "content": "",
                "source": "pdf_import",
                "created_at": _NOW(),
            })
        if chapter_titles:
            created.append(f"{len(chapter_titles)} chapters added")


# ──────────────────────────────────────────────────────────────────────────────
# Pure helper functions
# ──────────────────────────────────────────────────────────────────────────────

def _detect_board_key(board_name: str) -> str:
    """Map a raw board name string to 'degree' | 'ahsec' | 'seba' | ''."""
    n = (board_name or "").lower()
    if any(k in n for k in ("ahsec", "higher secondary", "hs board")):
        return "ahsec"
    if any(k in n for k in ("seba", "secondary education", "class 9", "class 10", "hslc")):
        return "seba"
    # Degree colleges — any college / university in Assam
    if any(k in n for k in (
        "degree", "college", "university", "gauhati", "dibrugarh", "cotton",
        "bodoland", "tezpur", "assam", "fyugp", "nep", "b.a", "b.com", "b.sc",
    )):
        return "degree"
    return "degree"  # sensible default for autonomous colleges


def _parse_semester_number(text: str) -> Optional[int]:
    """Extract the integer semester number from strings like 'Semester 1', '2nd Semester', 'Sem-3'."""
    if not text:
        return None
    text = text.lower().strip()
    # Ordinal words
    ordinals = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
                "5th": 5, "6th": 6, "7th": 7, "8th": 8,
                "first": 1, "second": 2, "third": 3, "fourth": 4}
    for word, num in ordinals.items():
        if word in text and "sem" in text:
            return num
    # Direct digit after sem/semester
    m = re.search(r"sem(?:ester)?[\s\-]*(\d)", text)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 8 else None
    return None


def _resolve_stream_keys(stream_hint: str, board_id: str) -> list[str]:
    """Map a stream hint string to a list of canonical stream keys."""
    h = (stream_hint or "").lower().strip()
    if not h or "all" in h or "general" in h or not h:
        if board_id in (_DEGREE_BOARD_ID,) or "board_" in board_id:
            return ["general"]
        return ["general"]
    # Multi-stream
    keys = []
    if "commerce" in h or "b.com" in h or "bcom" in h:
        keys.append("bcom" if board_id in (_DEGREE_BOARD_ID,) or "board_" in board_id else "commerce")
    if "art" in h or "b.a" in h or "ba" == h.strip("."):
        keys.append("ba" if board_id in (_DEGREE_BOARD_ID,) or "board_" in board_id else "arts")
    if "science" in h or "b.sc" in h or "bsc" in h:
        keys.append("bsc" if board_id in (_DEGREE_BOARD_ID,) or "board_" in board_id else "science")
    return keys or ["general"]


def _slugify(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^\w\s-]", "", t)
    t = re.sub(r"[\s_]+", "-", t)
    t = re.sub(r"-+", "-", t).strip("-")
    return t[:80]
