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
    "major": {"name": "Major",  "slug": "major", "description": "Major Discipline Course",              "icon": "🎯"},
    "minor": {"name": "Minor",  "slug": "minor", "description": "Minor Elective Course",               "icon": "📘"},
    "aec":   {"name": "AEC",    "slug": "aec",   "description": "Ability Enhancement Compulsory Course","icon": "🧠"},
    "sec":   {"name": "SEC",    "slug": "sec",   "description": "Skill Enhancement Course",             "icon": "⚡"},
    "mdc":   {"name": "MDC",    "slug": "mdc",   "description": "Multidisciplinary Course",             "icon": "🌐"},
    "vac":   {"name": "VAC",    "slug": "vac",   "description": "Value-Added Course",                   "icon": "✨"},
    "ge":    {"name": "GE",     "slug": "ge",    "description": "Generic Elective",                     "icon": "🔄"},
    "cc":    {"name": "CC",     "slug": "cc",    "description": "Core Course",                          "icon": "⭐"},
}

# Discipline-based streams (kept for AHSEC only — not used for DEGREE/NEP)
DISCIPLINE_PAPER_TYPES: set = set()   # No longer used; all types now in NEP_COURSE_STREAMS

# Discipline stream definitions (AHSEC fallback only — degree PDFs all use NEP_COURSE_STREAMS)
_DISCIPLINE_STREAMS: dict[str, dict] = {
    "general": {"name": "General", "slug": "general", "description": "General / All streams", "icon": "📚"},
    # AHSEC
    "commerce": {"name": "Commerce", "slug": "commerce", "description": "Commerce stream", "icon": "💼"},
    "arts":     {"name": "Arts",     "slug": "arts",     "description": "Arts stream",     "icon": "📖"},
    "science":  {"name": "Science",  "slug": "science",  "description": "Science stream",  "icon": "⚗️"},
}

_NOW = lambda: datetime.now(timezone.utc).isoformat()

# ──────────────────────────────────────────────────────────────────────────────
# SEO Phase D — Auto cross-linking for newly created chapters
# ──────────────────────────────────────────────────────────────────────────────

# Maximum number of sibling chapters to patch per new chapter. Keeping this
# small avoids exhausting Googlebot's per-host crawl budget on the resulting
# IndexNow fan-out and also keeps the patched HTML readable.
_CROSS_LINK_SIBLING_LIMIT = 3

_BASE_URL = "https://syrabit.ai"


def _related_marker(chapter_id: str) -> str:
    """Idempotency marker for a single new chapter. Looking up `chapter_id`
    in another chapter's content tells us whether we've already cross-linked
    to it, so the patch can be safely re-run any number of times."""
    return f"<!-- syrabit:related:{chapter_id} -->"


def _related_block(chapter: dict, subject: dict) -> str:
    """Markdown snippet inserted into sibling chapters / subject hubs.

    Embedded inside a single inline marker so the whole block can be detected
    and (eventually) removed without touching the rest of the content. Uses a
    simple `<a>` anchor (rather than a markdown link) so the patch survives
    intact whether the consumer is rendering markdown, raw HTML, or escaping
    angle brackets — the marker is the source of truth either way.
    """
    bs = subject.get("board_slug", "")
    cs = subject.get("class_slug", "")
    ss = subject.get("slug", "")
    ch_slug = chapter.get("slug", "")
    title = chapter.get("title") or ch_slug
    if not all([bs, cs, ss, ch_slug]):
        return ""
    href = f"/{bs}/{cs}/{ss}/{ch_slug}"
    marker = _related_marker(chapter["id"])
    # Single-line block keeps the diff in chapter.content / subject.description
    # minimal and easy to roll back manually if needed.
    return f"\n\n{marker}\n> **Related:** [{title}]({href})\n"


def _chapter_url(chapter: dict, subject: dict) -> Optional[str]:
    bs = subject.get("board_slug", "")
    cs = subject.get("class_slug", "")
    ss = subject.get("slug", "")
    ch_slug = chapter.get("slug", "")
    if not all([bs, cs, ss, ch_slug]):
        return None
    return f"{_BASE_URL}/{bs}/{cs}/{ss}/{ch_slug}"


def _subject_url(subject: dict) -> Optional[str]:
    bs = subject.get("board_slug", "")
    cs = subject.get("class_slug", "")
    ss = subject.get("slug", "")
    if not all([bs, cs, ss]):
        return None
    return f"{_BASE_URL}/{bs}/{cs}/{ss}"


def _pick_sibling_chapters(siblings: list[dict], new_chapter: dict,
                            limit: int = _CROSS_LINK_SIBLING_LIMIT) -> list[dict]:
    """Choose at most `limit` siblings to cross-link to the new chapter.

    Strategy (cheap, no embedding lookups — those are reserved for the heavier
    syllabus_embedder path and we explicitly avoid touching them per task
    scope):
      1. Prefer the previous + next chapter by `order_index` (curriculum
         neighbours) — those are the ones a student is most likely to reach
         next, so an inline "Related" link there compounds with internal
         crawler depth.
      2. Fill remaining slots with same-topic similarity by counting shared
         tokens in the chapter `topics` list (a simple Jaccard-style overlap),
         falling back to title-token overlap.
    """
    if not siblings:
        return []

    new_id = new_chapter.get("id")
    pool = [c for c in siblings if c.get("id") != new_id]
    if not pool:
        return []

    new_order = new_chapter.get("order_index") or new_chapter.get("order") or 0
    pool_sorted = sorted(pool, key=lambda c: c.get("order_index") or c.get("order") or 0)

    chosen: list[dict] = []
    seen_ids: set = set()

    # Pass 1 — prev + next neighbours by order
    prev_c = None
    next_c = None
    for c in pool_sorted:
        c_order = c.get("order_index") or c.get("order") or 0
        if c_order < new_order:
            prev_c = c
        elif c_order > new_order and next_c is None:
            next_c = c
            break
    for c in (prev_c, next_c):
        if c and c.get("id") not in seen_ids and len(chosen) < limit:
            chosen.append(c)
            seen_ids.add(c.get("id"))

    # Pass 2 — fill by topic-token overlap
    if len(chosen) < limit:
        new_topics = {t.lower() for t in (new_chapter.get("topics") or []) if isinstance(t, str)}
        new_title_tokens = {w for w in re.split(r"[\s,\-–—/&]+", (new_chapter.get("title") or "").lower()) if len(w) > 2}

        def _overlap(c: dict) -> int:
            c_topics = {t.lower() for t in (c.get("topics") or []) if isinstance(t, str)}
            c_title_tokens = {w for w in re.split(r"[\s,\-–—/&]+", (c.get("title") or "").lower()) if len(w) > 2}
            return len(new_topics & c_topics) * 3 + len(new_title_tokens & c_title_tokens)

        candidates = [(c, _overlap(c)) for c in pool_sorted if c.get("id") not in seen_ids]
        candidates.sort(key=lambda x: (-x[1], x[0].get("order_index") or 0))
        for c, score in candidates:
            if len(chosen) >= limit:
                break
            chosen.append(c)
            seen_ids.add(c.get("id"))

    return chosen[:limit]


async def cross_link_for_new_chapter(chapter_id: str, db=None,
                                     depth: int = 0) -> list[str]:
    """SEO Phase D — patch the parent subject hub + 2-3 sibling chapters
    with an inline "Related" link to the freshly-created chapter.

    Returns the list of public URLs (subject hub + each patched sibling +
    the new chapter itself) that callers should hand to the Phase A
    `fanout_for_url` helper for IndexNow + cache purge + prewarm.

    Idempotency
    -----------
    Each patch is gated on a stable HTML marker
    (`<!-- syrabit:related:{chapter_id} -->`). If the marker is already
    present in the target's content/description we leave it untouched and
    do **not** include that URL in the returned list — preventing IndexNow
    storms when this function is re-run after a republish.

    Recursion cap
    -------------
    `depth` defaults to 0; the wiring in admin_content.py never bumps it,
    so the function is structurally single-pass. The parameter exists so
    that any future caller that wires cross-linking into a downstream
    rewriter can opt-in without accidentally cascading.
    """
    if depth > 0:
        # Hard guard: cross-linking can never recurse, even if a future
        # caller mistakenly re-enters. The Phase D contract requires depth
        # capped at 1 (i.e. patching the parent must NOT cross-link further).
        return []

    if db is None:
        try:
            from deps import db as _real_db  # local import to keep this
            db = _real_db                     # module independent of FastAPI
        except Exception:
            return []

    new_chapter = await db.chapters.find_one({"id": chapter_id})
    if not new_chapter:
        return []
    subject_id = new_chapter.get("subject_id")
    if not subject_id:
        return []
    subject = await db.subjects.find_one({"id": subject_id})
    if not subject:
        return []

    new_url = _chapter_url(new_chapter, subject)
    if not new_url:
        return []

    block = _related_block(new_chapter, subject)
    if not block:
        return []

    patched_urls: list[str] = []

    # ── 1) Patch parent subject hub ─────────────────────────────────────
    subj_marker = _related_marker(chapter_id)
    subj_desc = subject.get("description") or ""
    if subj_marker not in subj_desc:
        new_desc = subj_desc + block
        await db.subjects.update_one(
            {"id": subject_id},
            {"$set": {"description": new_desc, "updated_at": _NOW()}},
        )
        subject_url = _subject_url(subject)
        if subject_url:
            patched_urls.append(subject_url)

    # ── 2) Patch 2-3 sibling chapters ───────────────────────────────────
    cursor = db.chapters.find({"subject_id": subject_id})
    siblings = await cursor.to_list(500) if hasattr(cursor, "to_list") else list(cursor)
    targets = _pick_sibling_chapters(siblings, new_chapter)

    for sib in targets:
        sib_id = sib.get("id")
        sib_marker = _related_marker(chapter_id)
        sib_content = sib.get("content") or ""
        if sib_marker in sib_content:
            continue
        new_content = sib_content + block
        await db.chapters.update_one(
            {"id": sib_id},
            {"$set": {"content": new_content, "updated_at": _NOW()}},
        )
        sib_url = _chapter_url(sib, subject)
        if sib_url:
            patched_urls.append(sib_url)

    # Always include the new chapter URL itself so the Phase A fan-out
    # picks it up (the chapter-create handler still triggers its own
    # IndexNow ping but the bundled fan-out gives us cache purge + prewarm
    # for free in the same batched call).
    patched_urls.append(new_url)

    return patched_urls



# ──────────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SyllabusEntry:
    """One extracted subject from a PDF."""
    board_name:      str
    class_year:      str
    semester:        str
    subject_name:    str
    paper_type:      str      # aec | sec | mdc | vac | ge | cc | major | minor
    stream_hint:     str      # "Commerce" / "Arts & Science" / "All" / …
    chapters:        list[str] = field(default_factory=list)
    chapter_details: list[dict] = field(default_factory=list)  # [{title, description, topics}]
    topics:          list[str] = field(default_factory=list)
    guidelines:      str = ""
    course_code:     str = ""
    credits:         int = 0


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
        board_id, board_name, board_slug = await self._find_or_create_board(entry.board_name, created)

        # 2 — Class (semester)
        class_id, class_name, class_slug = await self._find_or_create_class(entry, board_id, created)

        # 3 — Streams (NEP type stream or discipline stream)
        stream_keys = _resolve_stream_keys(entry.stream_hint, entry.paper_type, board_id)
        linked_streams: list[dict] = []
        for sk in stream_keys:
            sid, sname, sslug = await self._find_or_create_stream(class_id, sk, entry.paper_type, created)
            linked_streams.append({"stream_id": sid, "stream_name": sname, "stream_slug": sslug})

        # 4 + 5 — Subject + Chapters per stream
        subject_ids: list[str] = []
        ctx = {
            "board_id": board_id, "board_name": board_name, "board_slug": board_slug,
            "class_id": class_id, "class_name": class_name, "class_slug": class_slug,
        }
        for s in linked_streams:
            ctx["stream_name"] = s.get("stream_name", "")
            subj_id = await self._find_or_create_subject(
                s["stream_id"], s["stream_slug"], entry, ctx, created
            )
            subject_ids.append(subj_id)
            await self._upsert_chapters(subj_id, entry.chapters, created, entry.chapter_details)

        return LinkResult(
            board_id=board_id, board_name=board_name,
            class_id=class_id, class_name=class_name,
            streams=linked_streams, subject_ids=subject_ids,
            chapter_count=len(entry.chapters), created_nodes=created,
        )

    # ── Board ─────────────────────────────────────────────────────────────────

    async def _find_or_create_board(self, board_name_raw: str, created: list) -> tuple[str, str, str]:
        board_key = _detect_board_key(board_name_raw)
        seed_map = {"degree": _DEGREE_BOARD, "ahsec": _AHSEC_BOARD, "seba": _SEBA_BOARD}
        seed = seed_map.get(board_key)

        if seed:
            doc = await self._db.boards.find_one({"id": seed["id"]})
            if not doc:
                await self._db.boards.insert_one({**seed, "created_at": _NOW()})
                created.append(f"Board: {seed['name']}")
            return seed["id"], seed["name"], seed["slug"]

        # Unknown → create as custom autonomous-college board
        slug = _slugify(board_name_raw) or "unknown-board"
        doc = await self._db.boards.find_one({"slug": slug})
        if doc:
            return doc["id"], doc["name"], doc.get("slug", slug)
        new_id = f"board_{slug[:20]}"
        new_board = {
            "id": new_id, "name": board_name_raw, "slug": slug,
            "group_name": "Autonomous College",
            "description": f"{board_name_raw} — Autonomous Degree College (FYUGP/NEP)",
            "created_at": _NOW(),
        }
        await self._db.boards.insert_one(new_board)
        created.append(f"Board: {board_name_raw}")
        return new_id, board_name_raw, slug

    # ── Class ─────────────────────────────────────────────────────────────────

    async def _find_or_create_class(
        self, entry: SyllabusEntry, board_id: str, created: list
    ) -> tuple[str, str, str]:
        sem_num = _parse_semester_number(entry.semester or entry.class_year)

        if sem_num:
            class_name = _SEM_CLASS_NAMES.get(sem_num, f"Semester {sem_num}")
            class_slug = f"semester-{sem_num}"
        else:
            class_name = entry.class_year or "Unknown Year"
            class_slug = _slugify(class_name) or "unknown-year"

        doc = await self._db.classes.find_one({"board_id": board_id, "slug": class_slug})
        if doc:
            return doc["id"], doc["name"], doc.get("slug", class_slug)

        new_id = f"cls_{board_id}_{class_slug}"
        new_class = {
            "id": new_id, "board_id": board_id,
            "name": class_name, "slug": class_slug,
            "description": f"{class_name} — NEP FYUGP",
            "created_at": _NOW(),
        }
        await self._db.classes.insert_one(new_class)
        created.append(f"Class: {class_name}")
        return new_id, class_name, class_slug

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
            return doc["id"], doc["name"], doc.get("slug", defn["slug"])

        new_id = f"strm_{class_id}_{defn['slug']}"
        new_stream = {"id": new_id, "class_id": class_id, **defn, "created_at": _NOW()}
        await self._db.streams.insert_one(new_stream)
        created.append(f"Stream: {defn['name']}")
        return new_id, defn["name"], defn["slug"]

    # ── Subject ───────────────────────────────────────────────────────────────

    async def _find_or_create_subject(
        self, stream_id: str, stream_slug: str, entry: SyllabusEntry,
        ctx: dict, created: list
    ) -> str:
        slug = _slugify(entry.subject_name)
        doc = await self._db.subjects.find_one({"stream_id": stream_id, "slug": slug})
        if doc:
            missing = {}
            if not doc.get("board_id") and ctx.get("board_id"):
                missing["board_id"] = ctx["board_id"]
            if not doc.get("class_id") and ctx.get("class_id"):
                missing["class_id"] = ctx["class_id"]
            if not doc.get("board_slug") and ctx.get("board_slug"):
                missing["board_slug"] = ctx["board_slug"]
            if not doc.get("class_slug") and ctx.get("class_slug"):
                missing["class_slug"] = ctx["class_slug"]
            if not doc.get("stream_slug") and stream_slug:
                missing["stream_slug"] = stream_slug
            if ctx.get("board_name") and doc.get("boardName") != ctx["board_name"]:
                missing["boardName"] = ctx["board_name"]
            if ctx.get("class_name") and doc.get("className") != ctx["class_name"]:
                missing["className"] = ctx["class_name"]
            if ctx.get("stream_name") and doc.get("streamName") != ctx["stream_name"]:
                missing["streamName"] = ctx["stream_name"]
            if missing:
                await self._db.subjects.update_one({"id": doc["id"]}, {"$set": missing})
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
            "board_id": ctx.get("board_id", ""),
            "class_id": ctx.get("class_id", ""),
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
            "board_slug": ctx.get("board_slug", ""),
            "class_slug": ctx.get("class_slug", ""),
            "stream_slug": stream_slug,
            "boardId": ctx.get("board_id", ""),
            "boardName": ctx.get("board_name", ""),
            "className": ctx.get("class_name", ""),
            "streamName": ctx.get("stream_name", "") or entry.stream_hint or ctx.get("class_name", ""),
            "created_at": _NOW(),
        })
        created.append(f"Subject: {entry.subject_name}")
        return new_id

    # ── Chapters ──────────────────────────────────────────────────────────────

    async def _upsert_chapters(
        self, subject_id: str, chapter_titles: list[str], created: list,
        chapter_details: list[dict] | None = None,
    ) -> None:
        # Build a lookup by index so we can pull description + topics
        details_map: dict[int, dict] = {}
        if chapter_details:
            for idx, det in enumerate(chapter_details):
                details_map[idx] = det

        count = 0
        for i, title in enumerate(chapter_titles, 1):
            slug = _slugify(title)
            det  = details_map.get(i - 1, {})
            detail_desc  = (det.get("description") or "").strip()
            detail_topics: list[str] = det.get("topics") or []

            # Build a readable content markdown from the topics list
            if detail_topics:
                topics_md = "\n".join(f"- {t}" for t in detail_topics)
                content_md = f"**{title}**\n\n{detail_desc}\n\n**Key Topics:**\n{topics_md}" if detail_desc else f"**{title}**\n\n**Key Topics:**\n{topics_md}"
            elif detail_desc:
                content_md = f"**{title}**\n\n{detail_desc}"
            else:
                content_md = f"**{title}**"

            description = detail_desc or f"Chapter {i}: {title}"

            existing = await self._db.chapters.find_one({"subject_id": subject_id, "slug": slug})
            if existing:
                # Update description/content if we now have richer data
                if detail_desc and not existing.get("description", "").strip():
                    await self._db.chapters.update_one(
                        {"_id": existing["_id"]},
                        {"$set": {"description": description, "content": content_md, "topics": detail_topics}},
                    )
                continue

            await self._db.chapters.insert_one({
                "id": str(uuid.uuid4()),
                "subject_id": subject_id,
                "title": title, "slug": slug,
                "description": description,
                "content": content_md,
                "topics": detail_topics,
                "chapter_number": i,
                "order_index": i,
                "order": i,
                "content_type": "notes",
                "status": "published",
                "source": "pdf_import",
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
    if any(k in n for k in ("ahsec", "higher secondary", "hs board", "hs 1st", "hs 2nd", "class 11", "class 12", "class xi", "class xii")):
        return "ahsec"
    _seba_exact = ("seba", "secondary education", "hslc", "class 9", "class 10")
    _seba_boundary = re.compile(r'\bclass\s+(?:ix|x)\b(?!\s*i)', re.IGNORECASE)
    if any(k in n for k in _seba_exact) or _seba_boundary.search(n):
        return "seba"
    _degree_signals = (
        "college", "university", "autonomous", "degree", "fyugp", "nep",
        "ug", "undergraduate", "b.a", "b.sc", "b.com", "bca", "bba",
        "semester", "tdc", "honours", "honors", "major", "minor",
        "gauhati", "dibrugarh", "cotton", "darrang", "tezpur",
        "assam university", "b.barooah", "handique",
    )
    if any(k in n for k in _degree_signals):
        return "degree"
    return "unknown"


def _resolve_stream_keys(stream_hint: str, paper_type: str, board_id: str) -> list[str]:
    """
    Determine stream key(s) for this entry.
    All NEP course types (Major/Minor/AEC/SEC/MDC/VAC/GE/CC) → stream = paper_type key.
    Hierarchy: Board → Semester (Class) → Course Type (Stream) → Subject.
    AHSEC subjects without a recognised paper_type fall back to discipline streams.
    """
    pt = (paper_type or "").lower().strip()
    h  = (stream_hint or "").lower().strip()

    # All recognised course types map directly to their own stream node
    if pt in NEP_COURSE_STREAMS:
        return [pt]

    # AHSEC fallback — use stream_hint to pick discipline
    if not h or "all" in h or "general" in h:
        return ["general"]

    keys = []
    if "commerce" in h:
        keys.append("commerce")
    if "art" in h:
        keys.append("arts")
    if "science" in h:
        keys.append("science")
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
