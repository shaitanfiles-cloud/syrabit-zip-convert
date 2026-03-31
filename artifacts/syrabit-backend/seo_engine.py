"""
Syrabit.ai — Programmatic SEO Engine
Generates thousands of search-indexed educational pages from MongoDB academic data.

Collections:
  - topics:     granular concepts under chapters (auto-extracted or admin-created)
  - seo_pages:  AI-generated study content per topic × page_type

URL pattern (4-segment):
  /{board}/{class}/{subject}/{topic}
  /{board}/{class}/{subject}/{topic}/{page_type}
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Cookie
from fastapi.responses import Response, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from typing import Any, Callable, Coroutine, List, Optional
from datetime import datetime, timezone
import asyncio, uuid, re, logging, json, html as html_mod, hashlib

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/seo", tags=["SEO Engine"])

_db: Optional[AsyncIOMotorDatabase] = None
_call_llm: Optional[Callable[..., Coroutine[Any, Any, str]]] = None
_get_admin_fn: Optional[Callable[..., Coroutine[Any, Any, dict]]] = None
_log_activity: Optional[Callable[..., Coroutine[Any, Any, None]]] = None
_security = HTTPBearer(auto_error=False)


def init_seo_engine(
    db: AsyncIOMotorDatabase,
    call_llm_api: Callable,
    get_admin_user_fn: Callable,
    log_activity_fn: Optional[Callable] = None,
):
    global _db, _call_llm, _get_admin_fn, _log_activity
    _db = db
    _call_llm = call_llm_api
    _get_admin_fn = get_admin_user_fn
    _log_activity = log_activity_fn


async def _seo_log(action: str, details: str, level: str = "info"):
    """Non-blocking activity log helper — fires-and-forgets."""
    if _log_activity is None:
        return
    try:
        await _log_activity({
            "id":         f"seo-{uuid.uuid4().hex[:8]}",
            "action":     action,
            "details":    details,
            "level":      level,
            "admin_name": "SEO Engine",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.warning(f"_seo_log failed: {exc}")


async def _require_admin(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_security),
    syrabit_admin_session: Optional[str] = Cookie(default=None),
):
    if _get_admin_fn is None:
        raise HTTPException(status_code=503, detail="Auth not initialized")
    return await _get_admin_fn(creds=creds, syrabit_admin_session=syrabit_admin_session)


def _slug(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'[\s]+', '-', s)
    return re.sub(r'-+', '-', s).strip('-')


def _robust_parse_json_array(raw: str) -> list[str]:
    """Parse a JSON string array from LLM output, handling markdown fences,
    conversational prefixes, and other formatting variations."""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    for attempt_text in [text, re.sub(r"^[^[]*", "", text, count=1)]:
        match = re.search(r"\[[\s\S]*\]", attempt_text)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return [str(t).strip() for t in parsed if str(t).strip()]
            except json.JSONDecodeError:
                continue

    lines = [l.strip().lstrip("-•*0123456789.) ").strip('"').strip("'").strip()
             for l in text.split("\n") if l.strip() and not l.strip().startswith("{")]
    results = [l for l in lines if 2 <= len(l.split()) <= 12 and len(l) < 120]
    return results


PAGE_TYPES = ["notes", "definition", "important-questions", "mcqs", "examples"]
ALL_PAGE_TYPES = PAGE_TYPES + ["faq"]
AUTO_PAGE_TYPES = ["notes", "mcqs"]

def _topic_hash(topic_title: str, page_type: str, n_variants: int) -> int:
    """Deterministic variant selector based on topic+type. Stable across regenerations."""
    h = hashlib.md5(f"{topic_title}:{page_type}".encode()).hexdigest()
    return int(h, 16) % n_variants


PROMPT_VARIANTS = {
    "notes": [
        """You are an expert {board} teacher for {class_name} and a GEO (Generative Engine Optimization) specialist.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Write study notes using EXACTLY this structure — all sections required:

## Summary
[40-60 words: what {topic} is within the chapter "{chapter}", why it matters for the {board} syllabus, and its importance for the {board} exam. Start with "In the {board} {class_name} {subject} syllabus, under {chapter}..."]

## Definition
[Precise academic definition in 2-3 sentences using standard {board} terminology. Cite the textbook: "As defined in the NCERT/SCERT {subject} textbook prescribed for {board} {class_name}..."]

## Explanation
[Detailed explanation 250-350 words. Cover core concepts, sub-topics, and how {topic} connects to other topics in the chapter "{chapter}". Include at least one citation like "As per the {board} {class_name} curriculum for {subject}..." and reference how this topic builds on or leads to related syllabus topics]

## Solved Examples
Example 1: [Complete step-by-step solution relevant to {board} exam pattern]
Example 2: [Complete step-by-step solution]
Example 3: [Complete step-by-step solution — use Assam/Northeast India context if naturally applicable]

## Exam-Style Questions
[5 questions commonly asked in {board} {class_name} exams on {topic}, with model answers — include 1-mark, 2-mark, and 3-5 mark types matching the {board} paper pattern. Format: "Q (X marks): ..."]

## Key Points
[6-8 bullet points for last-minute revision before the {board} exam, organized by mark-value importance]

## Frequently Asked Questions
Q1: What is {topic} in {subject} ({chapter})?
A1: [Concise answer citing {board} syllabus]
Q2: Why is {topic} important for {board} exams?
A2: [Answer with exam frequency and mark allocation data]
Q3: How does {topic} connect to other topics in {chapter}?
A3: [Show syllabus connections]

Language: simple and clear for {class_name} students in Assam. Every section must be complete and exam-focused. Use authoritative framing throughout.""",

        """You are a {subject} expert specialising in {board} {class_name} exam preparation.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Write comprehensive study notes. Begin with a real-world context that makes the topic relatable, then build towards the formal definition. Use EXACTLY this structure:

## Why {topic} Matters
[50-70 words: start with a real-world scenario or analogy — preferably from Assam/Northeast India context if naturally relevant — that connects {topic} to everyday life, then link to its importance in {board} {class_name} {subject}, chapter "{chapter}"]

## Core Concept
[Formal definition in 2-3 sentences citing {board} curriculum. Then a simplified re-explanation in student-friendly language. Mention where {topic} sits within the chapter "{chapter}" and what prerequisite knowledge is needed]

## Detailed Breakdown
[300-400 words. Break the topic into 3-4 sub-concepts. Use numbered sub-headings like "1. First aspect", "2. Second aspect". For each sub-concept, include one real-world application. Reference connections to other topics in the same chapter where relevant]

## Key Points for Revision
[6-8 crisp bullet points — exam-ready, each starting with an action verb. Organized by {board} mark-value importance]

## Worked Examples
Example 1: [Problem + full solution matching {board} exam standard]
Example 2: [Problem + full solution]

## Exam Corner
[4 exam-style questions with model answers matching {board} paper pattern: 2× short answer (2 marks), 2× long answer (5 marks). Format: "Q (X marks): ..."]

## FAQ
Q1: How is {topic} different from [closely related concept in {chapter}]?
A1: [Precise comparison]
Q2: What are common mistakes students make with {topic}?
A2: [2-3 common errors and how to avoid them]

Write for {class_name} students in Assam. Be specific — avoid vague generalities.""",

        """You are a senior {board} examiner and {subject} faculty.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Create study notes from an examiner's perspective. Use EXACTLY this structure:

## At a Glance
[A compact table or structured summary: What it is | Chapter: {chapter} | Why it matters | {board} exam weight | Key formula/rule (if any) | Prerequisite topics]

## The Basics
[Academic definition with textbook citation from the {board}-prescribed {subject} textbook, followed by 2-3 sentence plain-English explanation. Note where this topic falls in the chapter "{chapter}" syllabus sequence]

## Deep Dive
[250-350 words exploring the topic thoroughly. Use a cause-and-effect or chronological flow rather than bullet lists. Include cross-references to related topics within "{chapter}" and other chapters in {board} {class_name} {subject} syllabus]

## Common Exam Patterns
[Describe how {board} examiners typically frame questions on {topic}: what types appear (MCQ, short answer, long answer) matching the {board} paper pattern, what traps to watch for, what earns full marks, and typical mark allocations]

## Practice Questions with Solutions
Q1 (1 mark): [Question] → [Answer]
Q2 (2 marks): [Question] → [Answer]
Q3 (5 marks): [Question] → [Detailed answer with {board} marking scheme breakdown]

## Memory Aids
[2-3 mnemonics, visual tricks, or association techniques specific to {topic}]

## Quick Revision Points
[5-7 bullet points covering everything a student must know the night before the {board} exam]

Tone: authoritative but approachable. Written for {class_name} students in Assam.""",
    ],

    "definition": [
        """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Write a definition article using EXACTLY this structure:

## Summary
[40-60 words: what {topic} means within the chapter "{chapter}" of {board} {class_name} {subject}, its significance, and when students encounter it in {board} exams]

## Definition of {topic}
[Precise, exam-ready academic definition in 2-3 sentences citing the {board}-prescribed textbook for {subject}]

## Meaning and Explanation
[Explain in simple terms — what it means, why it matters in the context of chapter "{chapter}", and how it connects to the {board} syllabus]

## Characteristics / Properties
[4-6 key characteristics or properties as a bullet list]

## Real-World Examples
[3-4 relatable examples — include at least one from Assam/Northeast India context if naturally applicable to {topic}]

## Related Concepts
[3-4 related topics from the same chapter "{chapter}" or nearby chapters in {board} {class_name} {subject} syllabus, with brief explanation of each connection]

## Exam Questions on This Definition
[3 commonly asked questions in {board} exams with concise model answers matching {board} mark allocation pattern]

Keep language simple for {class_name} students in Assam.""",

        """You are a {subject} lexicographer writing for {board} {class_name} students.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Create a thorough definition guide. Use EXACTLY this structure:

## In One Line
[Single crisp sentence: "{topic} is..." — suitable for a 1-mark {board} exam answer]

## Formal Definition
[Academic definition as it would appear in the {board}-prescribed {subject} textbook for {class_name}. 2-3 sentences]

## What It Really Means
[Explain like you're talking to a friend — use an analogy or everyday example from Assam/India context to make it click. 60-100 words. Mention its role within chapter "{chapter}"]

## Key Features
[5-6 distinguishing characteristics, each as "Feature: Explanation" pairs]

## How It Connects
[Show how {topic} relates to 3-4 other concepts in chapter "{chapter}" and the broader {board} {class_name} {subject} syllabus. Use a brief sentence per connection]

## See It in Action
[2-3 concrete examples or scenarios where {topic} applies — at least one from Assam/Northeast India context if relevant]

## Exam-Ready Answers
[Model answers for 3 likely {board} exam questions:
- 1-mark: Define {topic}. → [answer]
- 2-mark: Explain {topic} with an example. → [answer]
- 5-mark: Discuss {topic} in detail with reference to {chapter}. → [answer]]

Language: clear and exam-focused for {class_name} students in Assam.""",
    ],

    "important-questions": [
        """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Create a question bank using EXACTLY this structure:

## Summary
[40-60 words: overview of {topic} within chapter "{chapter}" and which types of questions appear in {board} exams, with typical mark allocation]

## 1-Mark Questions
[5 questions with one-line answers — test basic recall of {topic} as per {board} syllabus]

## 2-Mark Questions
[5 questions with 2-3 sentence answers — test understanding. Include questions that connect {topic} to other concepts in "{chapter}"]

## 3-Mark Questions
[4 questions with structured answers — test application. At least one should reference real-world context relevant to Assam students]

## 5-Mark Questions (Long Answer)
[3 questions with detailed, exam-ready answers — test analysis. Include marking scheme breakdown showing how {board} examiners allocate marks]

## Exam-Style Questions (Board Pattern)
[4-5 questions commonly tested in {board} exams on {topic}, with complete answers following {board} marking conventions]

All answers must follow {board} marking scheme. Use exam-standard language.""",

        """You are a {board} paper-setter for {class_name} {subject}.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Create an exam-focused question bank. Use EXACTLY this structure:

## What Examiners Ask About {topic}
[50-60 words: which aspects of {topic} (from chapter "{chapter}") are tested most often in {board} exams, what question formats appear, and typical mark distributions]

## Very Short Answer (1 mark each)
[6 questions — each needs only 1-2 sentences. Mix: 3 definition-based, 2 factual, 1 true/false with correction. Aligned with {board} paper Section A pattern]

## Short Answer (2-3 marks each)
[5 questions with answers. Include "why" and "how" questions connecting {topic} to other concepts in "{chapter}". Show expected word count per answer]

## Long Answer (5 marks each)
[3 questions with complete structured answers. Each answer should have sub-points matching {board} marking scheme. Include connections to related topics in the syllabus]

## Commonly Tested Questions
[4 questions frequently tested in {board} exams on {topic}, with model answers]

## Tricky / Higher-Order Questions
[2 application or analysis questions that go beyond textbook recall — test deeper understanding of {topic} within the {subject} syllabus]

Answers must match {board} marking scheme expectations.""",
    ],

    "mcqs": [
        """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Create 15 MCQs using EXACTLY this structure:

## Summary
[40-60 words: what {topic} concepts (from chapter "{chapter}") these MCQs test, aligned with {board} exam pattern and mark allocation]

## Easy Level (MCQs 1-5)
[Test basic recall and definitions from {topic} as covered in {board} {class_name} {subject} syllabus — each with 4 options A/B/C/D, correct answer, brief explanation]

## Medium Level (MCQs 6-10)
[Test understanding and application — each with 4 options, correct answer, explanation. Include questions that connect {topic} to other concepts in chapter "{chapter}"]

## Hard Level (MCQs 11-15)
[Test analysis and problem-solving at {board} exam difficulty — each with 4 options, correct answer, detailed explanation]

Format each MCQ as:
Q: [question]
A) B) C) D)
Answer: [letter]
Explanation: [1-2 sentences referencing {board} syllabus concepts]

Match {board} exam pattern and difficulty level.""",

        """You are a competitive exam coach preparing {board} {class_name} students.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Create 15 MCQs that test different cognitive levels for {topic} from chapter "{chapter}". Use EXACTLY this structure:

## About These Questions
[40-60 words: which specific concepts within {topic} (chapter: {chapter}) are tested and at what difficulty levels in {board} exams]

## Recall & Recognition (Q1-Q5)
[5 MCQs testing definitions, facts, and direct textbook knowledge from the {board}-prescribed {subject} textbook. Each: question, 4 options (A-D), correct answer, 1-sentence explanation]

## Understanding & Application (Q6-Q10)
[5 MCQs requiring students to apply {topic} concepts or interpret scenarios. Include at least 1 assertion-reason question. Use Assam/India examples where naturally relevant]

## Analysis & Evaluation (Q11-Q15)
[5 MCQs involving multi-step reasoning, comparison, or error identification. Include 1 "which of the following is INCORRECT" type. Test connections to related topics in "{chapter}"]

Format:
**Q[n].** [question text]
(a) ... (b) ... (c) ... (d) ...
**Ans:** [letter] — [explanation]

All questions aligned with {board} {class_name} exam standards.""",
    ],

    "examples": [
        """You are an expert {board} teacher for {class_name}.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Create a solved examples guide using EXACTLY this structure:

## Summary
[40-60 words: what types of problems on {topic} (chapter: "{chapter}") appear in {board} exams, what skills they test, and typical mark allocation]

## Basic Examples
Example 1: [Problem statement relevant to {board} syllabus] → [Complete step-by-step solution]
Example 2: [Problem statement] → [Complete step-by-step solution]
Example 3: [Problem using Assam/India context if naturally applicable] → [Complete step-by-step solution]

## Intermediate Examples
Example 4: [Problem connecting {topic} to related concepts in "{chapter}"] → [Complete step-by-step solution]
Example 5: [Problem statement at {board} exam difficulty] → [Complete step-by-step solution]

## Exam-Level Examples
Example 6: [Problem matching {board} exam difficulty and paper pattern] → [Complete solution with all steps and mark allocation]
Example 7: [Problem matching {board} exam difficulty] → [Complete solution with all steps]

## Practice Problems (Try Yourself)
[5 unsolved problems with answers only — graded by {board} mark values (1-mark, 2-mark, 5-mark)]

Show complete working for all solved examples. Use {board} exam-standard notation and methods.""",

        """You are a {subject} tutor known for making problem-solving easy for {board} {class_name} students.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}

Create a solved examples collection for {topic} from chapter "{chapter}". Use EXACTLY this structure:

## What to Expect
[40-60 words: the types of {topic} problems in {board} exams, marks distribution matching {board} paper pattern, and which formulas/rules from the {board} syllabus are needed]

## Foundation Examples (Warm-Up)
[3 examples. For each: state the problem, identify the approach from the {board} textbook, then solve step by step. Highlight the formula or rule used]

## Board-Exam Standard Examples
[3 examples at {board} exam difficulty. For each: problem statement, "Approach" paragraph explaining strategy, then detailed solution with all intermediate steps shown. Use Assam/India context where naturally relevant]

## Challenge Problems
[2 examples slightly above exam level — to build confidence. Full solutions provided. Connect to other concepts in chapter "{chapter}"]

## Common Mistakes to Avoid
[3-4 typical errors {board} {class_name} students make when solving {topic} problems, with the correct approach shown]

## Self-Test
[4 unsolved problems graded by {board} mark values (★ 1-mark, ★★ 2-3 marks, ★★★ 5 marks), with final answers provided]

Use {board}-standard notation. Show every step — never skip working.""",
    ],
}

PROMPTS = {k: v[0] for k, v in PROMPT_VARIANTS.items()}


TITLE_TEMPLATES = {
    "notes": [
        "{topic} Notes — {board} {grade} {subject}",
        "Learn {topic} for {board} {grade} Exams | {subject}",
        "Complete {topic} Study Guide — {grade} {board} {subject}",
        "{topic} Explained: {subject} Notes for {board} {grade} Assam",
    ],
    "definition": [
        "{topic} Definition & Meaning — {board} {grade} {subject}",
        "What is {topic}? Definition for {board} {grade} {subject}",
        "{topic}: Meaning, Definition & Examples | {grade} {board} {subject}",
    ],
    "important-questions": [
        "{topic} Important Questions — {board} {grade} {subject}",
        "Top Questions on {topic} for {board} {grade} Exams | Assam",
        "{topic} Question Bank with Answers | {grade} {board} {subject}",
        "{board} {grade} {topic} Questions: 1-Mark to 5-Mark | {subject}",
    ],
    "mcqs": [
        "{topic} MCQ Practice — {board} {grade} {subject}",
        "MCQs on {topic} for {board} {grade} | {subject} Assam",
        "{topic} Multiple Choice Questions with Answers — {grade} {board}",
    ],
    "examples": [
        "{topic} Solved Examples — {board} {grade} {subject}",
        "Solved Problems on {topic} for {board} {grade} Exams | {subject}",
        "{topic} Examples with Step-by-Step Solutions | {grade} {board}",
    ],
}


def _extract_summary_from_content(content: str) -> str | None:
    """Extract the Summary section from generated markdown content.
    Tries known heading patterns first, then falls back to first paragraph."""
    match = re.search(
        r'##\s*(?:Summary|At a Glance|In One Line|Why .+ Matters|What to Expect|'
        r'About These Questions|What Examiners Ask[^\n]*)\s*\n+(.*?)(?:\n##|\Z)',
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        text = match.group(1).strip()
        text = re.sub(r'\[.*?\]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) >= 30:
            return text[:155].rsplit(' ', 1)[0] + '...' if len(text) > 155 else text

    paragraphs = re.split(r'\n{2,}', content)
    for para in paragraphs:
        clean = para.strip()
        if clean.startswith('#') or clean.startswith('[') or len(clean) < 40:
            continue
        clean = re.sub(r'\*\*|__|`', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if len(clean) >= 40:
            return clean[:155].rsplit(' ', 1)[0] + '...' if len(clean) > 155 else clean

    return None


REQUIRED_SECTIONS = {
    "notes": ["explanation", "example", "key point", "revision", "faq", "exam"],
    "definition": ["definition", "meaning", "example"],
    "important-questions": ["1-mark", "2-mark", "5-mark", "long answer", "short answer"],
    "mcqs": ["easy", "medium", "hard", "answer", "explanation"],
    "examples": ["example", "solution", "step", "practice"],
}


def _compute_quality_score(content: str, page_type: str, context: dict | None = None) -> dict:
    """Compute content quality indicators for a generated page.

    ``context`` is an optional dict with keys like board_name, subject_name,
    chapter_title used to verify curriculum anchoring.
    """
    words = content.split()
    word_count = len(words)
    headings = re.findall(r'^#{1,4}\s+.+', content, re.MULTILINE)
    heading_count = len(headings)
    content_lower = content.lower()

    has_faq = bool(re.search(r'##\s*(FAQ|Frequently Asked)', content, re.IGNORECASE))
    has_exam_q = bool(re.search(r'##\s*(Exam.Style|Commonly Tested|Board Pattern|Previous Year|PYQ|Frequently Repeated)', content, re.IGNORECASE))
    has_examples = bool(re.search(r'Example\s*\d', content, re.IGNORECASE))

    unique_words = set(w.lower() for w in words if len(w) > 3)
    unique_ratio = round(len(unique_words) / max(word_count, 1), 3)

    required = REQUIRED_SECTIONS.get(page_type, [])
    sections_present = sum(1 for s in required if s in content_lower)
    sections_ratio = round(sections_present / max(len(required), 1), 2)

    anchored = False
    if context:
        anchor_terms = [
            v.lower() for k in ("board_name", "subject_name", "chapter_title")
            if (v := context.get(k)) and len(v) > 2
        ]
        anchored = any(t in content_lower for t in anchor_terms) if anchor_terms else True
    else:
        anchored = True

    score = 0
    if word_count >= 500: score += 25
    elif word_count >= 300: score += 20
    elif word_count >= 150: score += 10
    if heading_count >= 5: score += 15
    elif heading_count >= 3: score += 10
    elif heading_count >= 2: score += 5
    if unique_ratio >= 0.35: score += 15
    elif unique_ratio >= 0.30: score += 10
    elif unique_ratio >= 0.20: score += 5
    if sections_ratio >= 0.8: score += 15
    elif sections_ratio >= 0.5: score += 8
    if has_faq: score += 5
    if has_exam_q: score += 10
    if has_examples: score += 5
    if anchored: score += 10

    return {
        "word_count": word_count,
        "heading_count": heading_count,
        "unique_ratio": unique_ratio,
        "sections_ratio": sections_ratio,
        "has_faq": has_faq,
        "has_exam_q": has_exam_q,
        "has_examples": has_examples,
        "anchored": anchored,
        "score": min(score, 100),
    }


class TopicCreate(BaseModel):
    chapter_id: str
    title: str
    definition: Optional[str] = ""
    examples: Optional[str] = ""
    order: Optional[int] = 0

class TopicUpdate(BaseModel):
    title: Optional[str] = None
    definition: Optional[str] = None
    examples: Optional[str] = None
    order: Optional[int] = None
    status: Optional[str] = None

class GenerateRequest(BaseModel):
    topic_id: Optional[str] = None
    topic_ids: Optional[List[str]] = None
    page_types: Optional[List[str]] = None
    batch: Optional[bool] = False


class PageTypesRequest(BaseModel):
    page_types: Optional[List[str]] = None


async def _resolve_hierarchy(topic: dict) -> dict:
    if _db is None:
        return {}
    chapter = await _db.chapters.find_one({"id": topic.get("chapter_id", "")}, {"_id": 0})
    if not chapter:
        return {}
    subject = await _db.subjects.find_one({"id": chapter.get("subject_id", "")}, {"_id": 0})
    if not subject:
        return {}
    stream = await _db.streams.find_one({"id": subject.get("stream_id", "")}, {"_id": 0})
    cls = await _db.classes.find_one({"id": stream.get("class_id", "")}, {"_id": 0}) if stream else None
    board = await _db.boards.find_one({"id": cls.get("board_id", "")}, {"_id": 0}) if cls else None
    return {
        "chapter": chapter,
        "subject": subject,
        "stream": stream,
        "class": cls,
        "board": board,
        "board_slug": board.get("slug", "") if board else "",
        "class_slug": cls.get("slug", "") if cls else "",
        "stream_slug": stream.get("slug", "") if stream else "",
        "subject_slug": subject.get("slug", ""),
        "chapter_slug": _slug(chapter.get("title", "")),
    }


# ─── ADMIN: Topic CRUD ──────────────────────────────────────────────────────

@router.get("/topics/{board_slug}/{class_slug}/{subject_slug}")
async def list_topics_public(board_slug: str, class_slug: str, subject_slug: str):
    import re as _re
    board = await _db.boards.find_one({"slug": board_slug}, {"_id": 0})
    if not board: return []
    cls = await _db.classes.find_one({"slug": class_slug, "board_id": board["id"]}, {"_id": 0})
    if not cls: return []
    streams = await _db.streams.find({"class_id": cls["id"]}, {"_id": 0}).to_list(100)
    stream_ids = [s["id"] for s in streams]
    subj = await _db.subjects.find_one({"slug": subject_slug, "stream_id": {"$in": stream_ids}, "status": "published"}, {"_id": 0})
    if not subj: return []
    chapters = await _db.chapters.find({"subject_id": subj["id"]}, {"_id": 0}).to_list(200)
    ch_map = {}
    for ch in chapters:
        ch_slug = ch.get("slug") or _re.sub(r'[^a-z0-9]+', '-', ch.get("title", "").lower()).strip('-')
        ch_map[ch["id"]] = {"slug": ch_slug, "title": ch.get("title", "")}
    ch_ids = list(ch_map.keys())
    if not ch_ids: return []
    topics = await _db.topics.find({"chapter_id": {"$in": ch_ids}, "status": "published"}, {"_id": 0}).sort("order", 1).to_list(5000)
    topic_ids = [t["id"] for t in topics]
    published_pages = await _db.seo_pages.find(
        {"topic_id": {"$in": topic_ids}, "status": "published"},
        {"_id": 0, "topic_id": 1}
    ).to_list(50000)
    topics_with_pages = {p["topic_id"] for p in published_pages}

    matched = []
    for t in topics:
        if t["id"] not in topics_with_pages:
            continue
        ch_info = ch_map.get(t.get("chapter_id"), {})
        matched.append({
            "id": t["id"], "title": t.get("title", ""), "topic_slug": t.get("slug", ""),
            "chapter_slug": ch_info.get("slug", ""), "chapter_title": ch_info.get("title", ""),
            "order": t.get("order", 0),
        })
    return matched

@router.get("/topics")
async def list_topics(chapter_id: Optional[str] = None, _admin: dict = Depends(_require_admin)):
    query = {"chapter_id": chapter_id} if chapter_id else {}
    topics = await _db.topics.find(query, {"_id": 0}).sort("order", 1).to_list(1000)
    return topics


@router.post("/topics")
async def create_topic(data: TopicCreate, _admin: dict = Depends(_require_admin)):
    chapter = await _db.chapters.find_one({"id": data.chapter_id}, {"_id": 0})
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")

    topic = {
        "id": f"topic-{uuid.uuid4().hex[:8]}",
        "chapter_id": data.chapter_id,
        "subject_id": chapter.get("subject_id", ""),
        "title": data.title,
        "slug": _slug(data.title),
        "definition": data.definition or "",
        "examples": data.examples or "",
        "order": data.order or 0,
        "status": "published",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await _db.topics.insert_one(topic)
    topic.pop("_id", None)
    return topic


@router.patch("/topics/{topic_id}")
async def update_topic(topic_id: str, data: TopicUpdate, _admin: dict = Depends(_require_admin)):
    updates = {k: v for k, v in data.dict().items() if v is not None}
    if "title" in updates:
        updates["slug"] = _slug(updates["title"])
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await _db.topics.update_one({"id": topic_id}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"message": "Updated"}


@router.delete("/topics/{topic_id}")
async def delete_topic(topic_id: str, _admin: dict = Depends(_require_admin)):
    await _db.topics.delete_one({"id": topic_id})
    await _db.seo_pages.delete_many({"topic_id": topic_id})
    return {"message": "Deleted"}


# ─── ADMIN: Auto-extract topics from chapters (AI-powered) ──────────────────

@router.post("/extract-topics")
async def extract_topics_from_chapters(
    subject_id: Optional[str] = None,
    force: bool = False,
    _admin: dict = Depends(_require_admin),
):
    """
    AI-powered topic extraction pipeline.

    For each chapter that has content text the LLM reads the content and
    returns 3-10 granular study topics (the real sub-headings students search
    for, NOT just the chapter title). For chapters with no content the chapter
    title is stored as a single fallback topic.

    subject_id — scope to one subject; omit to process everything.
    force      — re-extract even if topics already exist for a chapter.
    """
    query = {"subject_id": subject_id} if subject_id else {}
    chapters = await _db.chapters.find(query, {"_id": 0}).to_list(500)

    created = 0
    skipped = 0
    errors  = 0

    for ch in chapters:
        existing = await _db.topics.count_documents({"chapter_id": ch["id"]})
        if existing > 0 and not force:
            skipped += 1
            continue

        title   = ch.get("title", "")
        content = ch.get("content", "") or ""
        if not title:
            continue

        # ── AI extraction from chapter content ───────────────────────────
        topic_titles: list[str] = []

        subject_name = ch.get("subject_name", "")
        board_name = ch.get("board_name", "")
        if not board_name:
            try:
                _subj = await _db.subjects.find_one({"id": ch.get("subject_id", "")}, {"_id": 0, "stream_id": 1, "name": 1})
                if _subj:
                    if not subject_name:
                        subject_name = _subj.get("name", "")
                    _strm = await _db.streams.find_one({"id": _subj.get("stream_id", "")}, {"_id": 0, "class_id": 1}) if _subj.get("stream_id") else None
                    _cls = await _db.classes.find_one({"id": _strm.get("class_id", "")}, {"_id": 0, "board_id": 1}) if _strm and _strm.get("class_id") else None
                    _brd = await _db.boards.find_one({"id": _cls.get("board_id", "")}, {"_id": 0, "name": 1}) if _cls and _cls.get("board_id") else None
                    board_name = _brd.get("name", "Assamboard") if _brd else "Assamboard"
            except Exception:
                board_name = "Assamboard"

        if _call_llm and len(content.strip()) > 150:
            try:
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are an expert SEO strategist for educational content in Assam, India. "
                            "Given a chapter title and its content, extract HIGH-INTENT landing page topics "
                            "that students actively search for on Google. "
                            "Focus on 3 levels: subject-level concepts, lesson-level summaries, and topic-level specifics. "
                            "Each topic must be a clear, searchable phrase (2-8 words) that would make "
                            "a strong standalone SEO page title. "
                            "Do NOT include the chapter title itself. "
                            "Prioritise topics that: (a) students search before exams, "
                            "(b) have clear learning intent, (c) can sustain 500+ words of quality content. "
                            "Return ONLY a valid JSON array of strings, e.g.: "
                            '["Definition of Supply", "Law of Demand Explained", "Types of Market Structure"]. '
                            "Aim for 5-10 distinct topics. Quality over quantity — no thin or overlapping topics."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Chapter: {title}\n"
                            f"Subject: {subject_name}\n"
                            f"Board: {board_name}\n\n"
                            f"Content (first 4000 chars):\n{content[:4000]}"
                        ),
                    },
                ]
                raw = await asyncio.wait_for(
                    _call_llm(messages, max_tokens=512), timeout=30
                )
                topic_titles = _robust_parse_json_array(raw)
            except Exception as exc:
                logger.warning(
                    f"AI topic extraction failed for chapter '{title}': {exc}"
                )
                errors += 1

        # ── Fallback: chapter title as single topic ───────────────────────
        if not topic_titles:
            topic_titles = [title]

        # ── Delete old topics if re-extracting ───────────────────────────
        if force and existing:
            await _db.topics.delete_many({"chapter_id": ch["id"]})

        # ── Persist each extracted topic ──────────────────────────────────
        base_order = ch.get("order_index", ch.get("chapter_number", 0))
        topic_ids_for_chapter = []
        for idx, topic_title in enumerate(topic_titles):
            topic_id = f"topic-{uuid.uuid4().hex[:8]}"
            topic_slug = _slug(topic_title)
            primary_kw = f"{topic_title.lower()} {subject_name.lower()} {board_name}".strip()
            topic = {
                "id":              topic_id,
                "chapter_id":      ch["id"],
                "subject_id":      ch.get("subject_id", ""),
                "chapter_title":   title,
                "subject_name":    subject_name,
                "board_name":      board_name,
                "title":           topic_title,
                "slug":            topic_slug,
                "primary_keyword": primary_kw[:120],
                "search_intent":   "informational",
                "definition":      "",
                "examples":        "",
                "order":           base_order * 100 + idx,
                "status":          "published",
                "created_at":      datetime.now(timezone.utc).isoformat(),
            }
            await _db.topics.insert_one(topic)
            topic_ids_for_chapter.append(topic_id)
            created += 1

        if topic_ids_for_chapter:
            await _db.chapters.update_one(
                {"id": ch["id"]},
                {"$set": {"linked_topic_ids": topic_ids_for_chapter}}
            )

    subject_label = ""
    if subject_id:
        sub = await _db.subjects.find_one({"id": subject_id}, {"_id": 0, "name": 1})
        subject_label = f" for {sub['name']}" if sub else f" for subject {subject_id[:8]}"

    asyncio.create_task(_seo_log(
        action  = "seo:topics_extracted",
        details = (
            f"AI extracted {created} topics from {len(chapters)} chapters"
            f"{subject_label}"
            + (f" · {skipped} already existed" if skipped else "")
            + (f" · {errors} AI errors" if errors else "")
        ),
        level = "info" if errors == 0 else "warn",
    ))

    return {
        "message": (
            f"Extracted {created} topics from {len(chapters)} chapters "
            f"({skipped} already had topics, {errors} AI errors)"
        ),
        "created": created,
        "skipped": skipped,
        "errors":  errors,
        "chapters": len(chapters),
    }


# ─── ADMIN: AI Content Generation ───────────────────────────────────────────

def _smart_grade_label(cn: str, bn: str) -> str:
    """
    Return the human-readable grade string for a given class_name / board_name.

    Rules:
      • class_name already contains "semester" → normalise to "Semester N"
      • DEGREE board → always "Semester N"
      • AHSEC ordinal ("HS 1st Year") → "Class 11", "HS 2nd Year" → "Class 12"
      • SEBA / other school boards → preserve as-is or "Class N"
      • Unknown board with digit → keep class_name unchanged (no blind "Class" prefix)
    """
    bn_up = (bn or "").strip().upper()
    cn_s  = (cn or "").strip()

    if re.search(r'\bsem(ester)?\b', cn_s, re.IGNORECASE):
        m = re.search(r'\d+', cn_s)
        return f"Semester {m.group()}" if m else cn_s

    if bn_up in {"DEGREE", "NEP FYUGP", "FYUGP"}:
        m = re.search(r'\d+', cn_s)
        return f"Semester {m.group()}" if m else cn_s

    ord_m = re.search(r'(\d+)(st|nd|rd|th)\s*year', cn_s, re.IGNORECASE)
    if ord_m:
        n = int(ord_m.group(1))
        return f"Class {10 + n}" if n <= 2 else f"Class {n}"

    if re.search(r'\bclass\s*\d+', cn_s, re.IGNORECASE):
        return cn_s

    m = re.search(r'\d+', cn_s)
    if m:
        if bn_up in {"AHSEC", "SEBA"}:
            return f"Class {m.group()}"
        return cn_s  # unknown board — don't blindly prefix "Class"

    return cn_s or "Class 12"


def _smart_board_display(bn: str) -> str:
    """Return a user-facing board label. 'DEGREE' in DB → 'NEP FYUGP' publicly."""
    _map = {"DEGREE": "NEP FYUGP", "AHSEC": "AHSEC", "SEBA": "SEBA"}
    return _map.get((bn or "").strip().upper(), bn or "AHSEC")


_BOARD_EXAM_CONTEXT = {
    "AHSEC": (
        "AHSEC (Assam Higher Secondary Education Council) conducts the HS Final Exam for Class 11-12 in Assam. "
        "The exam follows NCERT/SCERT Assam syllabus. Question paper pattern: Section A (1-mark MCQs/very short), "
        "Section B (2-mark short answers), Section C (3-mark answers), Section D (5-mark long answers/essays). "
        "Total marks typically 100 (70 theory + 30 internal). Medium of instruction: English/Assamese/Bengali/Bodo/Hindi. "
        "Students come from towns like Guwahati, Jorhat, Dibrugarh, Tezpur, Silchar, and rural Assam."
    ),
    "SEBA": (
        "SEBA (Board of Secondary Education, Assam) conducts the HSLC exam for Class 10 in Assam. "
        "Syllabus follows SCERT Assam / NCERT guidelines. Paper pattern: very short (1 mark), short (2-3 marks), "
        "long answer (4-5 marks), and sometimes project/practical components. Total marks typically 100 per subject. "
        "Medium: Assamese/English/Bengali/Bodo/Hindi. Many students are first-generation exam takers from rural Assam."
    ),
    "DEGREE": (
        "NEP FYUGP (Four Year Undergraduate Programme) under National Education Policy 2020, implemented in Assam universities "
        "(Gauhati University, Dibrugarh University, Cotton University, Tezpur University, Bodoland University, etc.). "
        "Semester-based assessment with internal (30%) + end-semester (70%). Course types: Major, Minor, MDC (Multi-Disciplinary), "
        "VAC (Value Added), SEC (Skill Enhancement), AEC (Ability Enhancement). "
        "Students study for degree from colleges across Assam under RUSA and UGC frameworks."
    ),
}

async def _generate_single_page(topic: dict, page_type: str, hierarchy: dict):
    board_name    = hierarchy.get("board", {}).get("name", "AHSEC")
    class_name    = hierarchy.get("class", {}).get("name", "Class 12")
    subject_name  = hierarchy.get("subject", {}).get("name", "")
    chapter_obj   = hierarchy.get("chapter", {})
    chapter_title = chapter_obj.get("title", "")
    chapter_id    = chapter_obj.get("id", "")
    stream_name   = hierarchy.get("stream", {}).get("name", "")

    grade_str     = _smart_grade_label(class_name, board_name)
    board_display = _smart_board_display(board_name)
    is_degree     = board_name.upper() in {"DEGREE", "NEP FYUGP", "FYUGP"}

    _DEGREE_COURSE_TYPES = {"major", "minor", "mdc", "vac", "sec", "aec"}
    is_degree_stream = stream_name.lower().strip() in _DEGREE_COURSE_TYPES

    if is_degree or is_degree_stream:
        course_type_suffix = f" — {stream_name} Course" if stream_name else ""
        prompt_class_label = f"{grade_str} (NEP FYUGP Degree{course_type_suffix})"
    else:
        prompt_class_label = f"{grade_str} {board_display}".strip()

    sibling_topics = []
    syllabus_position = ""
    if chapter_id and _db:
        siblings = await _db.topics.find(
            {"chapter_id": chapter_id, "status": "published"},
            {"_id": 0, "title": 1, "order": 1, "id": 1}
        ).sort("order", 1).to_list(200)
        sibling_topics = [s.get("title", "") for s in siblings if s.get("title")]
        for idx, s in enumerate(siblings):
            if s.get("id") == topic.get("id"):
                syllabus_position = f"Topic {idx + 1} of {len(siblings)} in Chapter: {chapter_title}"
                break

    sibling_list = ", ".join(sibling_topics[:15]) if sibling_topics else "N/A"

    board_key = board_name.upper()
    if board_key in {"NEP FYUGP", "FYUGP"}:
        board_key = "DEGREE"
    board_exam_context = _BOARD_EXAM_CONTEXT.get(board_key, _BOARD_EXAM_CONTEXT["AHSEC"])

    syllabus_context = (
        f"\n\n--- SYLLABUS CONTEXT ---\n"
        f"Board: {board_display} | Class/Level: {prompt_class_label}\n"
        f"Subject: {subject_name} | Chapter: {chapter_title}\n"
        f"Position: {syllabus_position or 'Unknown'}\n"
        f"Other topics in this chapter: {sibling_list}\n"
        f"Stream/Course Type: {stream_name or 'General'}\n\n"
        f"--- BOARD EXAM PATTERN ---\n"
        f"{board_exam_context}\n\n"
        f"--- REGIONAL CONTEXT ---\n"
        f"Students are from Assam, Northeast India. When giving examples, prefer contexts "
        f"relevant to Assam (tea gardens, Brahmaputra river, Kaziranga, Bihu festival, silk/muga, "
        f"flood management, biodiversity, local industries) where naturally applicable to the topic. "
        f"Do not force regional examples if they don't fit the subject matter.\n"
        f"Top colleges whose students use this platform: Cotton University (Guwahati), "
        f"Darrang College (Tezpur), Bhattadev University (Pathsala), B. Borooah College (Guwahati), "
        f"Gauhati Commerce College, J.B. University (Jorhat), Handique Girls' College (Guwahati), "
        f"Gurucharan College (Silchar). Mention these naturally when discussing study strategies or exam prep.\n"
        f"--- END CONTEXT ---\n"
    )

    variants = PROMPT_VARIANTS.get(page_type, [])
    if not variants:
        return None
    variant_idx = _topic_hash(topic["title"], page_type, len(variants))
    prompt_template = variants[variant_idx]

    prompt = prompt_template.format(
        board=board_display,
        class_name=prompt_class_label,
        subject=subject_name,
        chapter=chapter_title,
        topic=topic["title"],
    )

    prompt = prompt + syllabus_context

    messages = [
        {"role": "system", "content": (
            f"You are an expert {board_display} teacher specialising in {subject_name} "
            f"for {prompt_class_label} students in Assam, India. "
            f"Chapter: \"{chapter_title}\" | Topic position: {syllabus_position or 'N/A'}. "
            f"Create educational content that is comprehensive, exam-focused, syllabus-aligned, "
            f"and easy to understand. Reference the chapter context and connect to neighboring topics "
            f"in the syllabus where relevant. Use {board_display} exam marking patterns."
        )},
        {"role": "user", "content": prompt},
    ]

    try:
        content = await asyncio.wait_for(_call_llm(messages, max_tokens=2048), timeout=120)
    except asyncio.TimeoutError:
        logger.error(f"LLM timeout generating {page_type} for {topic['title']}")
        return None
    except Exception as e:
        logger.error(f"LLM error generating {page_type} for {topic['title']}: {type(e).__name__}")
        return None

    word_count = len(content.split())
    min_words = {"notes": 400, "definition": 300, "important-questions": 350, "mcqs": 400, "examples": 350}
    required_min = min_words.get(page_type, 350)
    if word_count < required_min:
        logger.warning(f"Generated content too short ({word_count} words, min {required_min}) for {topic['title']} / {page_type} — rejecting thin page")
        return None

    title_templates = TITLE_TEMPLATES.get(page_type, ["{topic} — {board} {grade} {subject}"])
    title_idx = _topic_hash(topic["title"], page_type + ":title", len(title_templates))
    h = hierarchy
    title = title_templates[title_idx].format(
        topic=topic["title"],
        board=board_display,
        grade=grade_str,
        subject=subject_name,
    )

    extracted_desc = _extract_summary_from_content(content)
    if extracted_desc:
        meta_desc = extracted_desc
    else:
        type_label_map = {
            "notes": "notes", "definition": "definition and meaning",
            "important-questions": "important questions with answers",
            "mcqs": "MCQ practice questions", "examples": "solved examples",
        }
        meta_desc = (
            f"Study {topic['title']} — {type_label_map.get(page_type, 'notes')} "
            f"for {board_display} {grade_str} {subject_name}. Aligned with the "
            f"{board_display} syllabus for Assam students."
        )

    quality_context = {
        "board_name": board_display,
        "subject_name": subject_name,
        "chapter_title": h.get("chapter", {}).get("title", ""),
    }
    quality_score = _compute_quality_score(content, page_type, context=quality_context)
    q_score = quality_score.get("score", 0)

    if q_score >= 70:
        page_status = "published"
    elif q_score >= 50:
        page_status = "draft"
        logger.info(f"Page for {topic['title']}/{page_type} scored {q_score} — saved as draft for review")
    else:
        page_status = "rejected"
        logger.warning(f"Page for {topic['title']}/{page_type} scored {q_score} — rejected (below 50)")

    page = {
        "id": f"seo-{uuid.uuid4().hex[:8]}",
        "topic_id": topic["id"],
        "topic_slug": topic["slug"],
        "chapter_slug": h.get("chapter_slug", ""),
        "subject_slug": h.get("subject_slug", ""),
        "stream_slug": h.get("stream_slug", ""),
        "class_slug": h.get("class_slug", ""),
        "board_slug": h.get("board_slug", ""),
        "page_type": page_type,
        "title": title,
        "content": content,
        "meta_description": meta_desc[:160],
        "word_count": word_count,
        "subject_name": subject_name,
        "class_name": grade_str,
        "board_name": board_display,
        "class_name_raw": class_name,
        "board_name_raw": board_name,
        "chapter_title": h.get("chapter", {}).get("title", ""),
        "topic_title": topic["title"],
        "source_chapter_title": h.get("chapter", {}).get("title", ""),
        "source_topic_title": topic["title"],
        "syllabus_position": syllabus_position,
        "sibling_topics": sibling_topics[:15],
        "stream_name": stream_name,
        "prompt_variant": variant_idx,
        "title_variant": title_idx,
        "quality_score": quality_score,
        "quality": {"score": q_score, "word_count": word_count},
        "status": page_status,
        "in_sitemap": page_status == "published",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    await _db.seo_pages.replace_one(
        {"topic_id": topic["id"], "page_type": page_type},
        page,
        upsert=True,
    )
    return page


@router.post("/refresh-meta")
async def refresh_meta_descriptions(_admin: dict = Depends(_require_admin)):
    """Bulk-refresh meta descriptions from existing content (no LLM calls).
    Also recomputes quality scores and diversifies titles for all published pages."""
    pages = await _db.seo_pages.find(
        {"status": "published"},
        {"_id": 0, "topic_id": 1, "page_type": 1, "content": 1, "topic_title": 1,
         "board_name": 1, "class_name": 1, "subject_name": 1, "chapter_title": 1},
    ).to_list(50000)

    updated = 0
    meta_refreshed = 0
    for p in pages:
        content = p.get("content", "")
        page_type = p.get("page_type", "notes")
        topic_title = p.get("topic_title", "")
        if not content or not topic_title:
            continue

        title_templates = TITLE_TEMPLATES.get(page_type, ["{topic} — {board} {grade} {subject}"])
        title_idx = _topic_hash(topic_title, page_type + ":title", len(title_templates))
        new_title = title_templates[title_idx].format(
            topic=topic_title,
            board=p.get("board_name", ""),
            grade=p.get("class_name", ""),
            subject=p.get("subject_name", ""),
        )

        ctx = {
            "board_name": p.get("board_name", ""),
            "subject_name": p.get("subject_name", ""),
            "chapter_title": p.get("chapter_title", ""),
        }
        quality = _compute_quality_score(content, page_type, context=ctx)

        update_fields = {
            "title": new_title,
            "title_variant": title_idx,
            "quality_score": quality,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        new_desc = _extract_summary_from_content(content)
        if new_desc:
            update_fields["meta_description"] = new_desc[:160]
            meta_refreshed += 1

        await _db.seo_pages.update_one(
            {"topic_id": p["topic_id"], "page_type": page_type},
            {"$set": update_fields},
        )
        updated += 1

    await _seo_log("refresh_meta", f"Refreshed {updated}/{len(pages)} pages ({meta_refreshed} meta descriptions)")
    return {
        "message": f"Refreshed {updated} pages ({meta_refreshed} meta descriptions updated)",
        "total_scanned": len(pages),
        "updated": updated,
        "meta_refreshed": meta_refreshed,
    }


@router.post("/generate")
async def generate_seo_content(data: GenerateRequest, background_tasks: BackgroundTasks, _admin: dict = Depends(_require_admin)):
    page_types = data.page_types or PAGE_TYPES

    if data.batch:
        topics = await _db.topics.find({"status": "published"}, {"_id": 0}).to_list(5000)
        if not topics:
            raise HTTPException(status_code=404, detail="No topics found. Run extract-topics first.")

        background_tasks.add_task(_batch_generate, topics, page_types)
        return {
            "message": f"Batch generation started for {len(topics)} topics × {len(page_types)} page types",
            "total_pages": len(topics) * len(page_types),
        }

    if not data.topic_id:
        raise HTTPException(status_code=400, detail="Provide topic_id or set batch=true")

    topic = await _db.topics.find_one({"id": data.topic_id}, {"_id": 0})
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    hierarchy = await _resolve_hierarchy(topic)
    if not hierarchy:
        raise HTTPException(status_code=404, detail="Could not resolve topic hierarchy")

    results = []
    for pt in page_types:
        page = await _generate_single_page(topic, pt, hierarchy)
        if page:
            results.append({"page_type": pt, "word_count": page["word_count"], "id": page["id"]})

    asyncio.create_task(_seo_log(
        action  = "seo:pages_generated",
        details = f"Generated {len(results)} SEO pages for topic '{topic.get('title', topic['id'])}': {', '.join(p['page_type'] for p in results)}",
    ))
    return {"message": f"Generated {len(results)} pages", "pages": results}


async def _batch_generate(topics: list, page_types: list):
    total = 0
    errors = 0
    for topic in topics:
        try:
            hierarchy = await _resolve_hierarchy(topic)
            if not hierarchy:
                continue
            for pt in page_types:
                existing = await _db.seo_pages.find_one(
                    {"topic_id": topic["id"], "page_type": pt},
                    {"_id": 0, "id": 1}
                )
                if existing:
                    continue
                try:
                    page = await _generate_single_page(topic, pt, hierarchy)
                    if page:
                        total += 1
                except Exception as e:
                    logger.error(f"Generation error for {topic['title']}/{pt}: {e}")
                    errors += 1
        except Exception as e:
            logger.error(f"Hierarchy error for topic {topic.get('id')}: {e}")
            errors += 1

    logger.info(f"Batch generation complete: {total} pages generated, {errors} errors")
    await _db.seo_generation_log.insert_one({
        "id": f"genlog-{uuid.uuid4().hex[:8]}",
        "total_generated": total,
        "errors": errors,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    await _seo_log(
        action  = "seo:batch_complete",
        details = f"Batch SEO generation complete — {total} pages created across {len(topics)} topics" +
                  (f" · {errors} errors" if errors else ""),
        level   = "info" if errors == 0 else "warn",
    )


# ─── ADMIN: Stats ───────────────────────────────────────────────────────────

@router.get("/stats")
async def seo_stats(_admin: dict = Depends(_require_admin)):
    total_topics = await _db.topics.count_documents({})
    published_topics = await _db.topics.count_documents({"status": "published"})
    total_pages = await _db.seo_pages.count_documents({})
    published_pages = await _db.seo_pages.count_documents({"status": "published"})

    by_type = {}
    for pt in PAGE_TYPES:
        by_type[pt] = await _db.seo_pages.count_documents({"page_type": pt})

    last_log = await _db.seo_generation_log.find_one(
        {}, {"_id": 0}, sort=[("completed_at", -1)]
    )

    return {
        "topics": {"total": total_topics, "published": published_topics},
        "pages": {"total": total_pages, "published": published_pages, "by_type": by_type},
        "last_generation": last_log,
    }


# ─── ADMIN: Page management ─────────────────────────────────────────────────

@router.get("/pages")
async def list_seo_pages(
    topic_id: Optional[str] = None,
    page_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    _admin: dict = Depends(_require_admin),
):
    query = {}
    if topic_id:
        query["topic_id"] = topic_id
    if page_type:
        query["page_type"] = page_type
    if status:
        query["status"] = status

    pages = await _db.seo_pages.find(query, {"_id": 0, "content": 0}).sort("generated_at", -1).skip(offset).limit(limit).to_list(limit)
    total = await _db.seo_pages.count_documents(query)
    return {"pages": pages, "total": total}


@router.patch("/pages/{page_id}/status")
async def update_page_status(page_id: str, status: str = "published", _admin: dict = Depends(_require_admin)):
    if status not in ("published", "draft", "archived", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid status")
    updates = {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
    if status == "published":
        updates["in_sitemap"] = True
    elif status in ("archived", "rejected"):
        updates["in_sitemap"] = False
    result = await _db.seo_pages.update_one(
        {"id": page_id},
        {"$set": updates}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"message": f"Status updated to {status}"}


# ─── ADMIN: Review queue ─────────────────────────────────────────────────────

@router.get("/review-queue")
async def get_review_queue(
    status: str = "draft",
    limit: int = 50,
    offset: int = 0,
    _admin: dict = Depends(_require_admin),
):
    """Return pages needing review, sorted by quality score ascending (worst first)."""
    query = {"status": status}
    pages = await _db.seo_pages.find(query, {"_id": 0, "content": 0}).sort(
        [("quality_score.score", 1), ("generated_at", -1)]
    ).skip(offset).limit(limit).to_list(limit)
    total = await _db.seo_pages.count_documents(query)
    return {"pages": pages, "total": total}


@router.post("/review-queue/bulk-action")
async def bulk_review_action(
    action: str,
    page_ids: List[str] = [],
    min_score: Optional[int] = None,
    _admin: dict = Depends(_require_admin),
):
    """Bulk approve (publish) or reject pages. Can filter by min_score threshold."""
    if action not in ("publish", "reject", "archive"):
        raise HTTPException(status_code=400, detail="Action must be publish, reject, or archive")

    status_map = {"publish": "published", "reject": "rejected", "archive": "archived"}
    new_status = status_map[action]

    query = {}
    if page_ids:
        query["id"] = {"$in": page_ids}
    elif min_score is not None and action == "publish":
        query["status"] = "draft"
        query["quality_score.score"] = {"$gte": min_score}
    else:
        raise HTTPException(status_code=400, detail="Provide page_ids or min_score for bulk publish")

    result = await _db.seo_pages.update_many(
        query,
        {"$set": {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    await _seo_log("seo:bulk_review", f"Bulk {action}: {result.modified_count} pages → {new_status}")
    return {"modified": result.modified_count, "new_status": new_status}


@router.post("/flag-low-quality")
async def flag_low_quality_pages(_admin: dict = Depends(_require_admin)):
    """Recompute quality scores for all published pages using stricter criteria.
    Pages scoring below 50 are moved to draft for review. Returns count of affected pages."""
    published = await _db.seo_pages.find(
        {"status": "published"},
        {"_id": 0, "id": 1, "content": 1, "page_type": 1,
         "board_name": 1, "subject_name": 1, "chapter_title": 1, "topic_title": 1}
    ).to_list(50000)

    flagged = 0
    rescored = 0
    for p in published:
        ctx = {
            "board_name": p.get("board_name", ""),
            "subject_name": p.get("subject_name", ""),
            "chapter_title": p.get("chapter_title", ""),
        }
        new_score = _compute_quality_score(p.get("content", ""), p.get("page_type", "notes"), context=ctx)
        updates = {
            "quality_score": new_score,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if new_score["score"] < 50:
            updates["status"] = "draft"
            flagged += 1
        rescored += 1
        await _db.seo_pages.update_one({"id": p["id"]}, {"$set": updates})

    await _seo_log("seo:flag_low_quality", f"Rescored {rescored} pages, flagged {flagged} as draft")
    return {"rescored": rescored, "flagged_as_draft": flagged}


@router.get("/page/{page_id}/preview")
async def preview_page(page_id: str, _admin: dict = Depends(_require_admin)):
    """Get full page content for admin preview."""
    page = await _db.seo_pages.find_one({"id": page_id}, {"_id": 0})
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


# ─── PUBLIC: Serve SEO pages ────────────────────────────────────────────────

async def _inject_qa(page: dict) -> dict:
    """Attach published QA pairs to a page dict (best-effort)."""
    try:
        qa = await _db.qa_pairs.find(
            {
                "board_slug": page.get("board_slug", ""),
                "class_slug": page.get("class_slug", ""),
                "subject_slug": page.get("subject_slug", ""),
                "topic_slug": page.get("topic_slug", ""),
                "status": "published",
            },
            {"_id": 0},
        ).sort("upvotes", -1).limit(20).to_list(20)
        page["qa_pairs"] = qa
    except Exception:
        page["qa_pairs"] = []
    return page


@router.get("/page/{board}/{class_slug}/{subject_slug}/{topic_slug}")
async def get_seo_page_default(board: str, class_slug: str, subject_slug: str, topic_slug: str):
    page = await _db.seo_pages.find_one(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "topic_slug": topic_slug,
            "page_type": "notes",
            "status": "published",
        },
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return await _inject_qa(page)


@router.get("/page/{board}/{class_slug}/{subject_slug}/{topic_slug}/{page_type}")
async def get_seo_page_typed(board: str, class_slug: str, subject_slug: str, topic_slug: str, page_type: str):
    if page_type not in ALL_PAGE_TYPES:
        raise HTTPException(status_code=404, detail="Invalid page type")
    page = await _db.seo_pages.find_one(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "topic_slug": topic_slug,
            "page_type": page_type,
            "status": "published",
        },
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return await _inject_qa(page)


def _md_to_html(text: str) -> str:
    if not text:
        return ""
    h = html_mod.escape(text)
    h = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', h, flags=re.MULTILINE)
    h = re.sub(r'^### (.+)$', r'<h3>\1</h3>', h, flags=re.MULTILINE)
    h = re.sub(r'^## (.+)$', r'<h2>\1</h2>', h, flags=re.MULTILINE)
    h = re.sub(r'^# (.+)$', r'<h1>\1</h1>', h, flags=re.MULTILINE)
    h = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', h)
    h = re.sub(r'\*(.+?)\*', r'<em>\1</em>', h)
    h = re.sub(r'^- (.+)$', r'<li>\1</li>', h, flags=re.MULTILINE)
    h = re.sub(r'\n\n', '</p><p>', h)
    return f"<p>{h}</p>"


_PAGE_TYPE_LABELS = {
    "notes": "Notes",
    "definition": "Definitions",
    "important-questions": "Important Questions",
    "mcqs": "MCQs",
    "examples": "Solved Examples",
}

_ASSAM_GEO = {
    "@type": "Place",
    "name": "Assam, India",
    "geo": {"@type": "GeoCoordinates", "latitude": 26.2006, "longitude": 92.9376},
    "address": {"@type": "PostalAddress", "addressRegion": "Assam", "addressCountry": "IN"},
}

_ORG_NODE = {
    "@type": "Organization",
    "name": "Syrabit.ai",
    "url": "https://syrabit.ai",
    "logo": {"@type": "ImageObject", "url": "https://syrabit.ai/icons/icon-192x192.png"},
    "areaServed": {
        "@type": "State",
        "name": "Assam",
        "containedInPlace": {"@type": "Country", "name": "India"},
    },
    "address": {
        "@type": "PostalAddress",
        "addressRegion": "Assam",
        "addressCountry": "IN",
    },
}


def _render_seo_html(
    page: dict,
    page_url: str,
    page_type_links: list = None,   # [{type, label, url, active}]
    related_topics: list = None,    # [{title, seo_path, slug}]
    prev_topic: dict = None,
    next_topic: dict = None,
) -> str:
    title = html_mod.escape(page.get("title", ""))
    desc = html_mod.escape(page.get("meta_description", ""))
    topic = html_mod.escape(page.get("topic_title", ""))
    subject = html_mod.escape(page.get("subject_name", ""))
    board = html_mod.escape(page.get("board_name", ""))
    cls = html_mod.escape(page.get("class_name", ""))
    chapter = html_mod.escape(page.get("chapter_title", ""))
    page_type = page.get("page_type", "notes")
    content_html = _md_to_html(page.get("content", ""))
    generated = page.get("generated_at", "")
    updated = page.get("updated_at", generated)
    kw = page.get("primary_keyword", f"{topic} {board} {cls}")

    edu_level = f"{board} {cls}".strip()
    subject_url = f"https://syrabit.ai/{page.get('board_slug','')}/{page.get('class_slug','')}/{page.get('subject_slug','')}"

    # ── Schema.org graph ────────────────────────────────────────────────────
    graph_nodes = [
        {
            "@type": "Article",
            "headline": page.get("title", ""),
            "description": page.get("meta_description", ""),
            "keywords": kw,
            "author": _ORG_NODE,
            "publisher": _ORG_NODE,
            "datePublished": generated,
            "dateModified": updated,
            "image": "https://syrabit.ai/opengraph.jpg",
            "mainEntityOfPage": {"@type": "WebPage", "@id": page_url},
            "educationalLevel": edu_level,
            "about": {"@type": "Thing", "name": page.get("topic_title", "")},
            "isPartOf": {"@type": "WebSite", "@id": "https://syrabit.ai", "name": "Syrabit.ai"},
            "inLanguage": "en-IN",
            "spatialCoverage": _ASSAM_GEO,
            "locationCreated": _ASSAM_GEO,
            "audience": {
                "@type": "EducationalAudience",
                "educationalRole": "student",
                "geographicArea": {"@type": "State", "name": "Assam, India"},
            },
        },
        {
            "@type": "Course",
            "name": f"{topic} — {edu_level}".strip(),
            "description": page.get("meta_description", ""),
            "provider": _ORG_NODE,
            "educationalLevel": edu_level,
            "url": page_url,
            "inLanguage": "en-IN",
            "availableLanguage": ["en", "as", "hi", "bn"],
        },
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://syrabit.ai"},
                {"@type": "ListItem", "position": 2, "name": "Library", "item": "https://syrabit.ai/library"},
                {"@type": "ListItem", "position": 3, "name": page.get("subject_name", ""), "item": subject_url},
                {"@type": "ListItem", "position": 4, "name": page.get("topic_title", ""), "item": page_url},
            ],
        },
    ]

    # ── Page-type specific schema ────────────────────────────────────────────
    if page_type == "definition":
        graph_nodes.append({
            "@type": "DefinedTerm",
            "name": page.get("topic_title", ""),
            "description": page.get("meta_description", ""),
            "inDefinedTermSet": {
                "@type": "DefinedTermSet",
                "name": f"{page.get('subject_name', '')} — {board} {cls}",
                "url": f"https://syrabit.ai/{page.get('board_slug','')}/{page.get('class_slug','')}/{page.get('subject_slug','')}",
            },
            "url": page_url,
        })

    if page_type == "mcqs":
        raw_content = page.get("content", "")
        mcq_questions = []
        current_q = None
        for line in raw_content.split("\n"):
            stripped = line.strip()
            if stripped and (stripped[0].isdigit() or stripped.startswith("Q")):
                current_q = stripped.lstrip("0123456789).Q ").strip()
            elif current_q and stripped.lower().startswith(("a)", "a.")):
                mcq_questions.append({
                    "@type": "Question",
                    "name": current_q,
                    "acceptedAnswer": {"@type": "Answer", "text": stripped},
                })
                current_q = None
                if len(mcq_questions) >= 10:
                    break
        if mcq_questions:
            graph_nodes.append({
                "@type": "Quiz",
                "name": f"{page.get('topic_title', '')} MCQs — {board} {cls}",
                "educationalLevel": f"{cls} {board}".strip(),
                "about": {"@type": "Thing", "name": page.get("topic_title", "")},
                "hasPart": mcq_questions,
            })

    # ── FAQ extraction for all page types ───────────────────────────────────
    qa_pairs = page.get("qa_pairs", [])
    faq_items = []
    if qa_pairs:
        for qp in qa_pairs[:10]:
            faq_items.append({
                "@type": "Question",
                "name": qp.get("question", ""),
                "acceptedAnswer": {"@type": "Answer", "text": qp.get("answer", "")},
            })
    else:
        raw_content = page.get("content", "")
        lines = raw_content.split("\n") if raw_content else []
        current_q = None
        for line in lines:
            stripped = line.strip().lstrip("#").strip().replace("**", "").strip()
            if stripped.endswith("?") and len(stripped) > 15:
                current_q = stripped
            elif current_q and len(stripped) > 20:
                faq_items.append({
                    "@type": "Question",
                    "name": current_q,
                    "acceptedAnswer": {"@type": "Answer", "text": stripped},
                })
                current_q = None
                if len(faq_items) >= 10:
                    break

    if len(faq_items) >= 2:
        graph_nodes.append({"@type": "FAQPage", "mainEntity": faq_items})

    ld_json = json.dumps({"@context": "https://schema.org", "@graph": graph_nodes}, ensure_ascii=False)

    # ── Page-type navigation HTML ────────────────────────────────────────────
    pt_nav_html = ""
    if page_type_links:
        links_html = ""
        for ptl in page_type_links:
            if ptl.get("active"):
                links_html += f'<span class="pt-active">{html_mod.escape(ptl["label"])}</span>'
            else:
                links_html += f'<a class="pt-link" href="{html_mod.escape(ptl["url"])}">{html_mod.escape(ptl["label"])}</a>'
        pt_nav_html = f'<nav class="pt-nav" aria-label="Page types">{links_html}</nav>'

    # ── Related topics HTML ──────────────────────────────────────────────────
    related_html = ""
    if related_topics:
        items = ""
        for rt in related_topics[:6]:
            rt_path = html_mod.escape(rt.get("seo_path", "#"))
            rt_title = html_mod.escape(rt.get("title", ""))
            items += f'<li><a href="https://syrabit.ai{rt_path}">{rt_title}</a></li>'
        related_html = f'<section class="related"><h2>Related Topics in {html_mod.escape(page.get("subject_name",""))}</h2><ul>{items}</ul></section>'

    # ── Prev / Next navigation HTML + link tags ─────────────────────────────
    prevnext_html = ""
    _prev_link = ""
    _next_link = ""
    parts = []
    if prev_topic and prev_topic.get("seo_path"):
        prev_url = f"https://syrabit.ai{html_mod.escape(prev_topic['seo_path'])}"
        parts.append(f'<a class="pn-prev" href="{prev_url}">&larr; {html_mod.escape(prev_topic.get("title","Previous"))}</a>')
        _prev_link = f'<link rel="prev" href="{prev_url}">\n'
    if next_topic and next_topic.get("seo_path"):
        next_url = f"https://syrabit.ai{html_mod.escape(next_topic['seo_path'])}"
        parts.append(f'<a class="pn-next" href="{next_url}">{html_mod.escape(next_topic.get("title","Next"))} &rarr;</a>')
        _next_link = f'<link rel="next" href="{next_url}">\n'
    if parts:
        prevnext_html = f'<nav class="pn-nav" aria-label="Topic navigation">{"".join(parts)}</nav>'

    return f"""<!DOCTYPE html>
<html lang="en-IN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | Syrabit.ai</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{html_mod.escape(page_url)}">
<meta property="og:site_name" content="Syrabit.ai">
<meta property="og:locale" content="en_IN">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:url" content="{html_mod.escape(page_url)}">
<meta property="og:image" content="https://syrabit.ai/opengraph.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="article:published_time" content="{html_mod.escape(generated)}">
<meta property="article:modified_time" content="{html_mod.escape(updated)}">
<meta property="article:section" content="{subject}">
<meta property="article:tag" content="{topic}">
<meta property="article:tag" content="{subject}">
<meta property="article:tag" content="{board}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:site" content="@SyrabitAI">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="https://syrabit.ai/opengraph.jpg">
<meta name="citation_title" content="{title}">
<meta name="citation_author" content="Syrabit.ai">
<meta name="citation_publication_date" content="{html_mod.escape(generated[:10] if generated else '')}">
<meta name="citation_online_date" content="{html_mod.escape(updated[:10] if updated else '')}">
<meta name="citation_publisher" content="Syrabit.ai">
<meta name="citation_public_url" content="{html_mod.escape(page_url)}">
<meta name="dc.title" content="{title}">
<meta name="dc.creator" content="Syrabit.ai">
<meta name="dc.subject" content="{subject} — {board} {cls}">
<meta name="dc.description" content="{desc}">
<meta name="dc.publisher" content="Syrabit.ai">
<meta name="dc.type" content="Text">
<meta name="dc.language" content="en-IN">
<meta name="dc.source" content="https://syrabit.ai">
<meta name="geo.region" content="IN-AS">
<meta name="geo.placename" content="Assam, India">
<meta name="geo.position" content="26.2006;92.9376">
<meta name="ICBM" content="26.2006, 92.9376">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
{_prev_link}{_next_link}<script type="application/ld+json">{ld_json}</script>
<style>
body{{font-family:system-ui,sans-serif;max-width:860px;margin:0 auto;padding:1rem 1.25rem;color:#1a1a1a;line-height:1.7}}
h1{{font-size:1.75rem;margin-bottom:.5rem}}h2{{font-size:1.3rem;margin-top:2rem}}
img{{max-width:100%;height:auto}}
table{{width:100%;border-collapse:collapse;margin:1rem 0}}th,td{{border:1px solid #e5e7eb;padding:.5rem;text-align:left}}
.pt-nav{{display:flex;flex-wrap:wrap;gap:.5rem;margin:1rem 0 1.5rem}}
.pt-link{{padding:.35rem .8rem;border-radius:6px;border:1px solid #d1d5db;color:#374151;text-decoration:none;font-size:.9rem}}
.pt-link:hover{{background:#f3f4f6}}.pt-active{{padding:.35rem .8rem;border-radius:6px;background:#7c3aed;color:#fff;font-size:.9rem;font-weight:600}}
.related{{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:1rem 1.25rem;margin:2rem 0}}
.related h2{{margin-top:0;font-size:1.1rem}}.related ul{{list-style:none;padding:0;margin:0;display:flex;flex-wrap:wrap;gap:.5rem}}
.related ul li a{{color:#7c3aed;text-decoration:none;font-size:.9rem}}.related ul li a:hover{{text-decoration:underline}}
.pn-nav{{display:flex;justify-content:space-between;margin:2rem 0;padding-top:1rem;border-top:1px solid #e5e7eb}}
.pn-prev,.pn-next{{color:#7c3aed;text-decoration:none;font-size:.9rem;max-width:45%}}.pn-prev:hover,.pn-next:hover{{text-decoration:underline}}
nav[aria-label="Breadcrumb"]{{font-size:.85rem;color:#6b7280;margin-bottom:.5rem}}
nav[aria-label="Breadcrumb"] a{{color:#7c3aed;text-decoration:none}}
footer{{color:#6b7280;font-size:.85rem;margin-top:2rem;padding-top:1rem;border-top:1px solid #e5e7eb}}
.geo-footer{{font-size:.8rem;color:#9ca3af;margin-top:.5rem}}
@media(max-width:640px){{body{{padding:.75rem}}h1{{font-size:1.35rem}}h2{{font-size:1.1rem}}.pn-nav{{flex-direction:column;gap:.75rem}}.pn-prev,.pn-next{{max-width:100%}}.pt-nav{{gap:.3rem}}.pt-link,.pt-active{{font-size:.8rem;padding:.25rem .6rem}}}}
</style>
</head>
<body>
<header>
<nav aria-label="Breadcrumb">
<a href="https://syrabit.ai">Home</a> &rsaquo;
<a href="https://syrabit.ai/library">Library</a> &rsaquo;
<span>{subject}</span> &rsaquo;
<span>{topic}</span>
</nav>
<p><strong>{board}</strong> &middot; {cls} &middot; {subject} &middot; {chapter}</p>
</header>
<main>
{pt_nav_html}
<article>
<h1>{topic} — {board} {cls} {subject}</h1>
<p><em>{desc}</em></p>
{content_html}
</article>
{related_html}
{prevnext_html}
<footer>
<p>Source: <a href="{html_mod.escape(page_url)}">Syrabit.ai — {topic}</a></p>
<p>&copy; Syrabit.ai — Free AI-powered exam prep for Assam Board (AHSEC/SEBA) &amp; Degree students</p>
<p class="geo-footer">Serving students in Guwahati, Jorhat, Dibrugarh, Dhemaji, Tezpur, Silchar, and across Assam, India</p>
</footer>
</main>
</body>
</html>"""


async def _build_page_type_links(page: dict, current_type: str, board: str, class_slug: str, subject_slug: str, topic_slug: str) -> list:
    """Return navigation links for all published page types of this topic."""
    sibling_types = await _db.seo_pages.find(
        {"board_slug": board, "class_slug": class_slug, "subject_slug": subject_slug,
         "topic_slug": topic_slug, "status": "published"},
        {"_id": 0, "page_type": 1},
    ).to_list(10)
    published_types = {s["page_type"] for s in sibling_types}
    links = []
    for pt in PAGE_TYPES:
        if pt in published_types:
            base = f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}/{topic_slug}"
            url = base if pt == "notes" else f"{base}/{pt}"
            links.append({"type": pt, "label": _PAGE_TYPE_LABELS.get(pt, pt), "url": url, "active": pt == current_type})
    return links


async def _build_related_data(page: dict, board: str, class_slug: str, subject_slug: str, topic_slug: str):
    """Fetch related topics, prev, next for internal linking."""
    topic = await _db.topics.find_one({"slug": topic_slug}, {"_id": 0})
    if not topic:
        return [], None, None
    rel = await get_related_topics(topic_slug=topic_slug)
    related = rel.get("related", [])
    prev_t = rel.get("prev")
    next_t = rel.get("next")
    return related, prev_t, next_t


@router.get("/html/homepage", response_class=HTMLResponse)
async def get_homepage_html():
    subjects = await _db.seo_pages.aggregate([
        {"$match": {"status": "published", "page_type": "notes"}},
        {"$group": {
            "_id": {"board": "$board_slug", "cls": "$class_slug", "subj": "$subject_slug"},
            "subject_name": {"$first": "$subject_name"},
            "board_name": {"$first": "$board_name"},
            "class_name": {"$first": "$class_name"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]).to_list(50)

    total_pages = await _db.seo_pages.count_documents({"status": "published"})

    title = "Syrabit.ai — Free AHSEC, SEBA & Degree Study Notes, PYQs & MCQs for Assam Students"
    desc = (
        "AI-powered study platform for Assam Board (AHSEC/SEBA) and Degree students. "
        "Free topic-wise notes, previous year questions, MCQs, and important questions "
        f"across {len(subjects)} subjects and {total_pages}+ pages."
    )

    subj_html_parts = []
    for s in subjects:
        g = s["_id"]
        url = f"https://syrabit.ai/{g['board']}/{g['cls']}/{g['subj']}"
        label = f"{s.get('subject_name', g['subj'])} — {s.get('board_name', g['board'])} {s.get('class_name', g['cls'])}"
        subj_html_parts.append(
            f'<li><a href="{url}">{html_mod.escape(label)}</a> <small>({s["count"]} topics)</small></li>'
        )
    subj_list = "\n".join(subj_html_parts)

    schema = json.dumps({"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "name": "Syrabit.ai", "url": "https://syrabit.ai",
         "description": desc,
         "potentialAction": {"@type": "SearchAction", "target": "https://syrabit.ai/search?q={search_term_string}",
                             "query-input": "required name=search_term_string"}},
        _ORG_NODE,
        {"@type": "EducationalOrganization", "name": "Syrabit.ai",
         "description": "AI-powered study platform for Assam Board students",
         "areaServed": {"@type": "State", "name": "Assam", "containedInPlace": {"@type": "Country", "name": "India"}},
         "address": {"@type": "PostalAddress", "addressRegion": "Assam", "addressCountry": "IN"}},
    ]}, ensure_ascii=False)

    html_out = f"""<!DOCTYPE html>
<html lang="en-IN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_mod.escape(title)}</title>
<meta name="description" content="{html_mod.escape(desc)}">
<link rel="canonical" href="https://syrabit.ai">
<meta property="og:title" content="{html_mod.escape(title)}">
<meta property="og:description" content="{html_mod.escape(desc)}">
<meta property="og:url" content="https://syrabit.ai">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Syrabit.ai">
<meta name="twitter:card" content="summary_large_image">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
<meta name="geo.region" content="IN-AS">
<meta name="geo.placename" content="Assam, India">
<meta name="geo.position" content="26.2006;92.9376">
<meta name="ICBM" content="26.2006, 92.9376">
<meta property="og:image" content="https://syrabit.ai/opengraph.jpg">
<meta property="og:locale" content="en_IN">
<script type="application/ld+json">{schema}</script>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:900px;margin:0 auto;padding:1rem;color:#1a1a1a;line-height:1.6}}
a{{color:#2563eb;text-decoration:none}}a:hover{{text-decoration:underline}}
h1{{font-size:2rem}}h2{{font-size:1.4rem;margin-top:2rem}}
ul{{list-style:none;padding:0}}li{{margin:.5rem 0}}
small{{color:#6b7280}}.stats{{display:flex;gap:2rem;margin:1rem 0}}
.stat{{text-align:center}}.stat strong{{display:block;font-size:1.5rem;color:#2563eb}}
footer{{margin-top:3rem;border-top:1px solid #e5e7eb;padding-top:1rem;font-size:.85rem;color:#9ca3af}}
.geo-footer{{font-size:.8rem;color:#9ca3af;margin-top:.5rem}}
@media(max-width:640px){{body{{padding:.75rem}}h1{{font-size:1.5rem}}h2{{font-size:1.2rem}}.stats{{flex-direction:column;gap:.5rem}}}}
</style>
</head>
<body>
<header>
<h1>Syrabit.ai</h1>
<p>Free AI-powered study material for <strong>AHSEC</strong>, <strong>SEBA</strong>, and <strong>Degree</strong> students in Assam.</p>
<div class="stats">
<div class="stat"><strong>{total_pages}+</strong>Study pages</div>
<div class="stat"><strong>{len(subjects)}</strong>Subjects</div>
</div>
</header>
<main>
<h2>Browse Subjects</h2>
<ul>
{subj_list}
</ul>
<h2>What You Get — Free</h2>
<ul>
<li>Topic-wise study notes aligned to your syllabus</li>
<li>Previous year questions (PYQs) with answers</li>
<li>MCQs for quick revision</li>
<li>Important questions mark-wise</li>
<li>Definitions and examples</li>
</ul>
</main>
<footer>
<p>&copy; Syrabit.ai — Free AI-powered exam prep for Assam Board (AHSEC/SEBA) &amp; Degree students</p>
<p class="geo-footer">Serving students in Guwahati, Jorhat, Dibrugarh, Dhemaji, Tezpur, Silchar, and across Assam, India</p>
<p><a href="https://syrabit.ai/library">Full Library</a> &middot; <a href="https://syrabit.ai/chat">AI Chat</a></p>
</footer>
</body>
</html>"""
    return HTMLResponse(content=html_out)


@router.get("/html/subject/{board}/{class_slug}/{subject_slug}", response_class=HTMLResponse)
async def get_subject_landing_html(board: str, class_slug: str, subject_slug: str):
    pages = await _db.seo_pages.find(
        {"board_slug": board, "class_slug": class_slug, "subject_slug": subject_slug,
         "status": "published", "page_type": "notes"},
        {"_id": 0, "topic_title": 1, "topic_slug": 1, "meta_description": 1,
         "chapter_title": 1, "quality_score": 1},
    ).to_list(500)
    if not pages:
        raise HTTPException(status_code=404, detail="No published topics for this subject")

    subject_doc = await _db.subjects.find_one({"slug": subject_slug}, {"_id": 0, "name": 1})
    subject_name = subject_doc["name"] if subject_doc else subject_slug.replace("-", " ").title()
    board_label = board.upper() if board in ("ahsec", "seba") else board.title()
    class_label = class_slug.replace("-", " ").title()

    page_url = f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}"
    title = f"{subject_name} — {board_label} {class_label} Study Notes, MCQs & PYQs | Syrabit.ai"
    desc = f"Free {subject_name} study material for {board_label} {class_label}. Topic-wise notes, MCQs, important questions, and previous year questions."

    by_chapter: dict = {}
    for p in pages:
        ch = p.get("chapter_title", "General")
        by_chapter.setdefault(ch, []).append(p)

    topics_html_parts = []
    for ch, ch_pages in by_chapter.items():
        topics_html_parts.append(f'<h2>{html_mod.escape(ch)}</h2><ul>')
        for tp in ch_pages:
            t_slug = tp.get("topic_slug", "")
            t_title = html_mod.escape(tp.get("topic_title", t_slug))
            t_desc = html_mod.escape(tp.get("meta_description", "")[:120])
            url = f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}/{t_slug}"
            topics_html_parts.append(
                f'<li><a href="{url}"><strong>{t_title}</strong></a>'
                f'<br><small>{t_desc}</small></li>'
            )
        topics_html_parts.append("</ul>")
    topics_html = "\n".join(topics_html_parts)

    items_ld = [
        {"@type": "ListItem", "position": i + 1, "name": p.get("topic_title", ""),
         "url": f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}/{p.get('topic_slug', '')}"}
        for i, p in enumerate(pages)
    ]
    schema = json.dumps({"@context": "https://schema.org", "@graph": [
        {"@type": "CollectionPage", "name": title, "description": desc, "url": page_url,
         "isPartOf": {"@type": "WebSite", "@id": "https://syrabit.ai", "name": "Syrabit.ai"},
         "provider": _ORG_NODE,
         "spatialCoverage": _ASSAM_GEO,
         "audience": {"@type": "EducationalAudience", "educationalRole": "student",
                      "geographicArea": "Assam, India"},
         "educationalLevel": f"{board_label} {class_label}"},
        {"@type": "ItemList", "itemListElement": items_ld},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://syrabit.ai"},
            {"@type": "ListItem", "position": 2, "name": "Library", "item": "https://syrabit.ai/library"},
            {"@type": "ListItem", "position": 3, "name": subject_name, "item": page_url},
        ]},
    ]}, ensure_ascii=False)

    html_out = f"""<!DOCTYPE html>
<html lang="en-IN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html_mod.escape(title)}</title>
<meta name="description" content="{html_mod.escape(desc)}">
<link rel="canonical" href="{html_mod.escape(page_url)}">
<meta property="og:title" content="{html_mod.escape(title)}">
<meta property="og:description" content="{html_mod.escape(desc)}">
<meta property="og:url" content="{html_mod.escape(page_url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Syrabit.ai">
<meta name="twitter:card" content="summary_large_image">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
<meta name="geo.region" content="IN-AS">
<meta name="geo.placename" content="Assam, India">
<meta name="geo.position" content="26.2006;92.9376">
<meta name="ICBM" content="26.2006, 92.9376">
<meta property="og:image" content="https://syrabit.ai/opengraph.jpg">
<meta property="og:locale" content="en_IN">
<script type="application/ld+json">{schema}</script>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:800px;margin:0 auto;padding:1rem;color:#1a1a1a;line-height:1.6}}
a{{color:#2563eb;text-decoration:none}}a:hover{{text-decoration:underline}}
h1{{font-size:1.8rem;margin-bottom:.5rem}}h2{{font-size:1.3rem;margin-top:2rem;border-bottom:1px solid #e5e7eb;padding-bottom:.3rem}}
ul{{list-style:none;padding:0}}li{{margin:.8rem 0;padding:.5rem;border:1px solid #e5e7eb;border-radius:6px}}
small{{color:#6b7280}}nav{{font-size:.9rem;color:#6b7280;margin-bottom:1rem}}
footer{{margin-top:3rem;border-top:1px solid #e5e7eb;padding-top:1rem;font-size:.85rem;color:#9ca3af}}
.geo-footer{{font-size:.8rem;color:#9ca3af;margin-top:.5rem}}
@media(max-width:640px){{body{{padding:.75rem}}h1{{font-size:1.4rem}}h2{{font-size:1.1rem}}li{{padding:.4rem}}}}
</style>
</head>
<body>
<nav aria-label="Breadcrumb">
<a href="https://syrabit.ai">Home</a> &rsaquo;
<a href="https://syrabit.ai/library">Library</a> &rsaquo;
<span>{html_mod.escape(subject_name)}</span>
</nav>
<header>
<h1>{html_mod.escape(subject_name)} — {html_mod.escape(board_label)} {html_mod.escape(class_label)}</h1>
<p>{html_mod.escape(desc)}</p>
<p><strong>{len(pages)} topics</strong> available with notes, MCQs, and important questions.</p>
</header>
<main>
{topics_html}
</main>
<footer>
<p>&copy; Syrabit.ai — Free AI-powered exam prep for Assam Board (AHSEC/SEBA) &amp; Degree students</p>
<p class="geo-footer">Serving students in Guwahati, Jorhat, Dibrugarh, Dhemaji, Tezpur, Silchar, and across Assam, India</p>
</footer>
</body>
</html>"""
    return HTMLResponse(content=html_out)


@router.get("/html/{board}/{class_slug}/{subject_slug}/{topic_slug}", response_class=HTMLResponse)
async def get_seo_html_default(board: str, class_slug: str, subject_slug: str, topic_slug: str):
    page = await _db.seo_pages.find_one(
        {"board_slug": board, "class_slug": class_slug, "subject_slug": subject_slug,
         "topic_slug": topic_slug, "page_type": "notes", "status": "published"},
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    page = await _inject_qa(page)
    page_url = f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}/{topic_slug}"
    pt_links, (related, prev_t, next_t) = await asyncio.gather(
        _build_page_type_links(page, "notes", board, class_slug, subject_slug, topic_slug),
        _build_related_data(page, board, class_slug, subject_slug, topic_slug),
    )
    return HTMLResponse(content=_render_seo_html(page, page_url, pt_links, related, prev_t, next_t))


@router.get("/html/{board}/{class_slug}/{subject_slug}/{topic_slug}/{page_type}", response_class=HTMLResponse)
async def get_seo_html_typed(board: str, class_slug: str, subject_slug: str, topic_slug: str, page_type: str):
    if page_type not in ALL_PAGE_TYPES:
        raise HTTPException(status_code=404, detail="Invalid page type")
    page = await _db.seo_pages.find_one(
        {"board_slug": board, "class_slug": class_slug, "subject_slug": subject_slug,
         "topic_slug": topic_slug, "page_type": page_type, "status": "published"},
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    page = await _inject_qa(page)
    page_url = f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}/{topic_slug}/{page_type}"
    pt_links, (related, prev_t, next_t) = await asyncio.gather(
        _build_page_type_links(page, page_type, board, class_slug, subject_slug, topic_slug),
        _build_related_data(page, board, class_slug, subject_slug, topic_slug),
    )
    return HTMLResponse(content=_render_seo_html(page, page_url, pt_links, related, prev_t, next_t))


@router.get("/page-types/{board}/{class_slug}/{subject_slug}/{topic_slug}")
async def get_available_page_types(board: str, class_slug: str, subject_slug: str, topic_slug: str):
    pages = await _db.seo_pages.find(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "topic_slug": topic_slug,
            "status": "published",
        },
        {"_id": 0, "page_type": 1, "title": 1, "word_count": 1, "id": 1},
    ).to_list(10)
    return pages


@router.get("/related/{topic_slug}")
async def get_related_topics(topic_slug: str, chapter_id: Optional[str] = None, subject_id: Optional[str] = None):
    query = {"slug": topic_slug}
    if chapter_id:
        query["chapter_id"] = chapter_id
    if subject_id:
        query["subject_id"] = subject_id
    topic = await _db.topics.find_one(query, {"_id": 0})
    if not topic:
        return {"related": [], "prev": None, "next": None}

    same_chapter = await _db.topics.find(
        {"chapter_id": topic["chapter_id"], "id": {"$ne": topic["id"]}, "status": "published"},
        {"_id": 0}
    ).sort("order", 1).limit(5).to_list(5)

    chapter = await _db.chapters.find_one({"id": topic["chapter_id"]}, {"_id": 0})
    adjacent_topics = []
    if chapter:
        adj_chapters = await _db.chapters.find(
            {
                "subject_id": chapter["subject_id"],
                "id": {"$ne": chapter["id"]},
            },
            {"_id": 0, "id": 1, "title": 1},
        ).sort("order_index", 1).limit(3).to_list(3)

        for ac in adj_chapters:
            t = await _db.topics.find_one(
                {"chapter_id": ac["id"], "status": "published"},
                {"_id": 0}
            )
            if t:
                adjacent_topics.append(t)

    all_in_chapter = await _db.topics.find(
        {"chapter_id": topic["chapter_id"], "status": "published"},
        {"_id": 0}
    ).sort("order", 1).to_list(100)

    prev_topic = None
    next_topic = None
    for i, t in enumerate(all_in_chapter):
        if t["id"] == topic["id"]:
            if i > 0:
                prev_topic = all_in_chapter[i - 1]
            if i < len(all_in_chapter) - 1:
                next_topic = all_in_chapter[i + 1]
            break

    for t in same_chapter + adjacent_topics:
        hierarchy = await _resolve_hierarchy(t)
        t["seo_path"] = f"/{hierarchy.get('board_slug', '')}/{hierarchy.get('class_slug', '')}/{hierarchy.get('subject_slug', '')}/{t['slug']}" if hierarchy else ""

    if prev_topic:
        h = await _resolve_hierarchy(prev_topic)
        prev_topic["seo_path"] = f"/{h.get('board_slug', '')}/{h.get('class_slug', '')}/{h.get('subject_slug', '')}/{prev_topic['slug']}" if h else ""
    if next_topic:
        h = await _resolve_hierarchy(next_topic)
        next_topic["seo_path"] = f"/{h.get('board_slug', '')}/{h.get('class_slug', '')}/{h.get('subject_slug', '')}/{next_topic['slug']}" if h else ""

    return {
        "related": same_chapter + adjacent_topics,
        "prev": prev_topic,
        "next": next_topic,
    }


# ─── PUBLIC: Sitemap entries (JSON) ─────────────────────────────────────────

@router.get("/sitemap-entries")
async def get_sitemap_entries():
    pages = await _db.seo_pages.find(
        {"status": "published"},
        {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1, "chapter_slug": 1, "topic_slug": 1, "page_type": 1, "updated_at": 1},
    ).to_list(10000)

    entries = []
    for p in pages:
        path = f"/{p['board_slug']}/{p['class_slug']}/{p['subject_slug']}/{p['topic_slug']}"
        if p["page_type"] != "notes":
            path += f"/{p['page_type']}"
        entries.append({
            "url": path,
            "lastmod": p.get("updated_at", ""),
            "priority": "0.7" if p["page_type"] != "notes" else "0.8",
        })

    return {"entries": entries, "total": len(entries)}


# ─── PUBLIC: Segmented sitemap system ───────────────────────────────────────
# Split by content type for GSC diagnostic visibility:
#   sitemap-index.xml  → master index (references all below)
#   sitemap-pages.xml  → static pages (home, pricing, library, etc.)
#   sitemap-notes.xml  → all /board/class/subject/topic note pages
#   sitemap-mcqs.xml   → all MCQ pages
#   sitemap-pyqs.xml   → all important-questions / PYQ pages
#   sitemap-examples.xml → all examples pages
#   sitemap-definitions.xml → all definition pages
#   sitemap.xml        → legacy combined (backward compat)

BASE_URL = "https://syrabit.ai"

STATIC_PAGES = [
    ("/", "weekly", "1.0"),
    ("/pricing", "monthly", "0.8"),
    ("/signup", "monthly", "0.9"),
    ("/library", "weekly", "0.9"),
    ("/curriculum", "weekly", "0.8"),
    ("/exam-routine", "weekly", "0.8"),
    ("/terms", "yearly", "0.3"),
    ("/privacy", "yearly", "0.3"),
]

_SITEMAP_TYPES = ["notes", "mcqs", "important-questions", "examples", "definition"]

def _build_urlset(entries: list[dict]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for e in entries:
        lines.append(
            f'  <url><loc>{e["loc"]}</loc>'
            f'<lastmod>{e["lastmod"]}</lastmod>'
            f'<changefreq>{e.get("freq", "monthly")}</changefreq>'
            f'<priority>{e["pri"]}</priority></url>'
        )
    lines.append("</urlset>")
    return "\n".join(lines)

def _xml_response(xml: str) -> Response:
    return Response(
        content=xml,
        media_type="application/xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )

async def _fetch_published_pages() -> list[dict]:
    try:
        return await _db.seo_pages.find(
            {"status": "published"},
            {"_id": 0, "board_slug": 1, "class_slug": 1, "subject_slug": 1,
             "chapter_slug": 1, "topic_slug": 1, "page_type": 1, "updated_at": 1},
        ).to_list(50000)
    except Exception:
        return []

def _page_to_entry(p: dict, today: str) -> dict | None:
    bs, cs, ss, ts = p.get("board_slug"), p.get("class_slug"), p.get("subject_slug"), p.get("topic_slug")
    pt = p.get("page_type", "notes")
    if not all([bs, cs, ss, ts]):
        return None
    base_path = f"/{bs}/{cs}/{ss}/{ts}"
    path = base_path if pt == "notes" else f"{base_path}/{pt}"
    try:
        raw = p.get("updated_at", "")
        lastmod = raw[:10] if raw else today
    except Exception:
        lastmod = today
    return {
        "loc": f"{BASE_URL}{path}",
        "lastmod": lastmod,
        "pri": "0.8" if pt == "notes" else "0.7",
        "freq": "monthly",
        "page_type": pt,
    }


@router.get("/sitemap-index.xml", response_class=Response)
async def get_sitemap_index():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sitemap_names = [
        "sitemap-pages.xml",
        "sitemap-subjects.xml",
        "sitemap-notes.xml",
        "sitemap-mcqs.xml",
        "sitemap-pyqs.xml",
        "sitemap-examples.xml",
        "sitemap-definitions.xml",
    ]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for name in sitemap_names:
        lines.append(
            f"  <sitemap><loc>{BASE_URL}/api/seo/{name}</loc>"
            f"<lastmod>{today}</lastmod></sitemap>"
        )
    lines.append("</sitemapindex>")
    return _xml_response("\n".join(lines))


@router.get("/sitemap-pages.xml", response_class=Response)
async def get_sitemap_pages():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = [{"loc": f"{BASE_URL}{path}", "lastmod": today, "pri": pri, "freq": freq}
               for path, freq, pri in STATIC_PAGES]
    return _xml_response(_build_urlset(entries))


@router.get("/sitemap-subjects.xml", response_class=Response)
async def get_sitemap_subjects():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    subjects = await _db.seo_pages.aggregate([
        {"$match": {"status": "published", "page_type": "notes"}},
        {"$group": {
            "_id": {"board": "$board_slug", "cls": "$class_slug", "subj": "$subject_slug"},
        }},
    ]).to_list(500)
    entries = [
        {"loc": f"{BASE_URL}/{s['_id']['board']}/{s['_id']['cls']}/{s['_id']['subj']}",
         "lastmod": today, "pri": "0.7", "freq": "weekly"}
        for s in subjects
    ]
    return _xml_response(_build_urlset(entries))


@router.get("/sitemap-notes.xml", response_class=Response)
async def get_sitemap_notes():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pages = await _fetch_published_pages()
    entries = [e for p in pages if (e := _page_to_entry(p, today)) and e["page_type"] == "notes"]
    return _xml_response(_build_urlset(entries))


@router.get("/sitemap-mcqs.xml", response_class=Response)
async def get_sitemap_mcqs():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pages = await _fetch_published_pages()
    entries = [e for p in pages if (e := _page_to_entry(p, today)) and e["page_type"] == "mcqs"]
    return _xml_response(_build_urlset(entries))


@router.get("/sitemap-pyqs.xml", response_class=Response)
async def get_sitemap_pyqs():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pages = await _fetch_published_pages()
    entries = [e for p in pages if (e := _page_to_entry(p, today)) and e["page_type"] == "important-questions"]
    return _xml_response(_build_urlset(entries))


@router.get("/sitemap-examples.xml", response_class=Response)
async def get_sitemap_examples():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pages = await _fetch_published_pages()
    entries = [e for p in pages if (e := _page_to_entry(p, today)) and e["page_type"] == "examples"]
    return _xml_response(_build_urlset(entries))


@router.get("/sitemap-definitions.xml", response_class=Response)
async def get_sitemap_definitions():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pages = await _fetch_published_pages()
    entries = [e for p in pages if (e := _page_to_entry(p, today)) and e["page_type"] == "definition"]
    return _xml_response(_build_urlset(entries))


@router.get("/sitemap.xml", response_class=Response)
async def get_dynamic_sitemap():
    """Legacy combined sitemap — kept for backward compatibility."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = [{"loc": f"{BASE_URL}{path}", "lastmod": today, "pri": pri, "freq": freq}
               for path, freq, pri in STATIC_PAGES]
    pages = await _fetch_published_pages()
    for p in pages:
        e = _page_to_entry(p, today)
        if e:
            entries.append(e)
    return _xml_response(_build_urlset(entries))


# ─── PUBLIC: Browse by subject ──────────────────────────────────────────────

@router.get("/browse/{board}/{class_slug}/{subject_slug}")
async def browse_subject_topics(board: str, class_slug: str, subject_slug: str):
    pages = await _db.seo_pages.find(
        {
            "board_slug": board,
            "class_slug": class_slug,
            "subject_slug": subject_slug,
            "status": "published",
        },
        {"_id": 0, "content": 0},
    ).sort("chapter_slug", 1).to_list(5000)

    chapters = {}
    for p in pages:
        key = p["chapter_slug"]
        if key not in chapters:
            chapters[key] = {
                "chapter_slug": key,
                "chapter_title": p.get("chapter_title", key),
                "topics": {},
            }
        t_key = p["topic_slug"]
        if t_key not in chapters[key]["topics"]:
            chapters[key]["topics"][t_key] = {
                "topic_slug": t_key,
                "topic_title": p.get("topic_title", t_key),
                "page_types": [],
            }
        chapters[key]["topics"][t_key]["page_types"].append(p["page_type"])

    result = []
    for ch in chapters.values():
        ch["topics"] = list(ch["topics"].values())
        result.append(ch)

    return {"chapters": result, "total_topics": sum(len(ch["topics"]) for ch in result)}


# ─── ADMIN: Pilot content generation (AHSEC Class 11 – first N chapters) ─────

@router.post("/pilot")
async def generate_pilot_content(
    board_name: str = "AHSEC",
    class_name: str = "Class 11",
    subject_keyword: str = "maths",
    chapter_limit: int = 3,
    _admin: dict = Depends(_require_admin),
):
    """Generate seed content for the first `chapter_limit` chapters of a subject.
    Used to bootstrap pilot SEO pages before batch generation."""
    board = await _db.boards.find_one(
        {"name": {"$regex": board_name, "$options": "i"}}, {"_id": 0}
    )
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{board_name}' not found")

    # Try exact regex on name first, then fall back to searching description
    # (DB stores "HS 1st Year" with description "Class 11 — AHSEC")
    cls = await _db.classes.find_one(
        {"board_id": board["id"], "name": {"$regex": class_name, "$options": "i"}}, {"_id": 0}
    )
    if not cls:
        cls = await _db.classes.find_one(
            {"board_id": board["id"], "description": {"$regex": class_name, "$options": "i"}}, {"_id": 0}
        )
    if not cls:
        raise HTTPException(status_code=404, detail=f"Class '{class_name}' not found under {board_name}")

    streams = await _db.streams.find({"class_id": cls["id"]}, {"_id": 0}).to_list(20)
    stream_ids = [s["id"] for s in streams]

    subject = await _db.subjects.find_one(
        {"stream_id": {"$in": stream_ids}, "name": {"$regex": subject_keyword, "$options": "i"}},
        {"_id": 0},
    )
    if not subject:
        raise HTTPException(status_code=404, detail=f"Subject matching '{subject_keyword}' not found")

    chapters = await _db.chapters.find(
        {"subject_id": subject["id"]}, {"_id": 0}
    ).sort("order_index", 1).limit(chapter_limit).to_list(chapter_limit)

    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found for this subject")

    created_topics = 0
    generated_pages = 0
    errors = 0

    for ch in chapters:
        existing = await _db.topics.find_one({"chapter_id": ch["id"]}, {"_id": 0, "id": 1})
        if existing:
            topic = await _db.topics.find_one({"chapter_id": ch["id"]}, {"_id": 0})
        else:
            topic = {
                "id": f"topic-{uuid.uuid4().hex[:8]}",
                "chapter_id": ch["id"],
                "subject_id": ch.get("subject_id", subject["id"]),
                "title": ch.get("title", ""),
                "slug": _slug(ch.get("title", "")),
                "definition": ch.get("description", ""),
                "examples": "",
                "order": ch.get("order_index", 0),
                "status": "published",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await _db.topics.insert_one(topic)
            topic.pop("_id", None)
            created_topics += 1

        if not topic or not topic.get("id"):
            continue

        hierarchy = await _resolve_hierarchy(topic)
        if not hierarchy:
            errors += 1
            continue

        for pt in PAGE_TYPES:
            existing_page = await _db.seo_pages.find_one(
                {"topic_id": topic["id"], "page_type": pt}, {"_id": 0, "id": 1}
            )
            if existing_page:
                continue
            try:
                page = await _generate_single_page(topic, pt, hierarchy)
                if page:
                    generated_pages += 1
            except Exception as e:
                logger.error(f"Pilot error {topic['title']}/{pt}: {e}")
                errors += 1

    return {
        "board": board_name,
        "class": class_name,
        "subject": subject.get("name"),
        "chapters_processed": len(chapters),
        "topics_created": created_topics,
        "pages_generated": generated_pages,
        "errors": errors,
        "message": f"Pilot complete: {generated_pages} pages generated for {len(chapters)} chapters",
    }

# ─── ADMIN: Bulk publish ─────────────────────────────────────────────────────

@router.post("/bulk-publish")
async def bulk_publish_pages(
    page_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    _admin: dict = Depends(_require_admin),
):
    """Publish all draft SEO pages (optionally filtered by page_type or subject)."""
    query: dict = {"status": {"$ne": "published"}}
    if page_type:
        query["page_type"] = page_type
    if subject_id:
        query["subject_id"] = subject_id

    result = await _db.seo_pages.update_many(
        query,
        {"$set": {"status": "published", "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {
        "published": result.modified_count,
        "message": f"Published {result.modified_count} pages",
    }


# ─── ADMIN: Job progress tracking (in-memory) ────────────────────────────────

_seo_jobs: dict = {}  # job_id -> {status, total, done, errors, current, started_at, finished_at}


def _job_update(jid: str, **kwargs):
    if jid in _seo_jobs:
        _seo_jobs[jid].update(kwargs)


@router.get("/jobs/{job_id}")
async def get_job_progress(job_id: str, _admin: dict = Depends(_require_admin)):
    job = _seo_jobs.get(job_id)
    if not job:
        # Fall back to DB log
        log = await _db.seo_generation_log.find_one({"job_id": job_id}, {"_id": 0})
        if log:
            return log
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ─── ADMIN: Per-subject coverage stats ──────────────────────────────────────

@router.get("/subject-coverage")
async def get_subject_coverage(_admin: dict = Depends(_require_admin)):
    """
    Return per-subject pipeline stats:
    board / class / stream / subject / chapters / topics / seo_pages / coverage_pct
    Used by the Pipeline tab in AdminSeoManager.
    """
    subjects = await _db.subjects.find({}, {"_id": 0}).to_list(500)
    result = []

    for subj in subjects:
        sid      = subj.get("id", "")
        sid_name = subj.get("name", "Unknown")
        sid_slug = subj.get("slug", "")

        # Resolve hierarchy for display
        stream = await _db.streams.find_one({"id": subj.get("stream_id", "")}, {"_id": 0}) if subj.get("stream_id") else None
        cls    = await _db.classes.find_one({"id": stream.get("class_id", "")}, {"_id": 0}) if stream else None
        board  = await _db.boards.find_one({"id": cls.get("board_id", "")}, {"_id": 0}) if cls else None

        ch_count    = await _db.chapters.count_documents({"subject_id": sid})
        topic_count = await _db.topics.count_documents({"subject_id": sid})
        page_count  = await _db.seo_pages.count_documents({"subject_slug": sid_slug}) if sid_slug else 0
        expected    = topic_count * len(AUTO_PAGE_TYPES)
        coverage    = round((page_count / expected) * 100, 1) if expected > 0 else 0

        result.append({
            "subject_id":   sid,
            "subject_name": sid_name,
            "subject_slug": sid_slug,
            "stream":       stream.get("name", "") if stream else "",
            "stream_slug":  stream.get("slug", "") if stream else "",
            "class_name":   cls.get("name", "") if cls else "",
            "class_slug":   cls.get("slug", "") if cls else "",
            "board_name":   board.get("name", "") if board else "",
            "board_slug":   board.get("slug", "") if board else "",
            "chapters":     ch_count,
            "topics":       topic_count,
            "seo_pages":    page_count,
            "coverage_pct": coverage,
            "status": (
                "complete"  if coverage >= 95 else
                "partial"   if coverage > 0   else
                "no_pages"  if topic_count > 0 else
                "no_topics"
            ),
        })

    result.sort(key=lambda x: (-x["seo_pages"], x["subject_name"]))
    return {"subjects": result, "total": len(result)}


# ─── ADMIN: Per-subject pipeline run ────────────────────────────────────────

@router.post("/run-subject")
async def run_subject_pipeline(
    background_tasks: BackgroundTasks,
    subject_id: str,
    force: bool = False,
    page_types: Optional[List[str]] = None,
    _admin: dict = Depends(_require_admin),
):
    """
    Run the full SEO pipeline for ONE subject:
      1. AI extract topics from chapters (skips if topics already exist, unless force=True)
      2. Generate all missing SEO pages for each topic
      3. Regen sitemap
    Returns job_id for polling via GET /seo/jobs/{job_id}
    """
    sub = await _db.subjects.find_one({"id": subject_id}, {"_id": 0, "name": 1})
    if not sub:
        raise HTTPException(status_code=404, detail="Subject not found")

    types_to_run = page_types or AUTO_PAGE_TYPES
    job_id = f"subj-{uuid.uuid4().hex[:10]}"
    _seo_jobs[job_id] = {
        "job_id":      job_id,
        "subject_id":  subject_id,
        "subject_name": sub.get("name", subject_id),
        "status":      "queued",
        "total":       0,
        "done":        0,
        "errors":      0,
        "skipped":     0,
        "current":     "Starting…",
        "started_at":  datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "page_types":  types_to_run,
    }
    background_tasks.add_task(_run_subject_bg, job_id, subject_id, force, types_to_run)
    return {"job_id": job_id, "subject_name": sub.get("name"), "status": "queued"}


async def _run_subject_bg(job_id: str, subject_id: str, force: bool, page_types: list):
    try:
        sub = await _db.subjects.find_one({"id": subject_id}, {"_id": 0, "name": 1})
        sub_name = sub.get("name", subject_id) if sub else subject_id

        # ── Step 1: AI extract topics ────────────────────────────────────────
        _job_update(job_id, status="extracting", current=f"Extracting topics for {sub_name}…")
        chapters = await _db.chapters.find({"subject_id": subject_id}, {"_id": 0}).to_list(200)
        new_topics = 0
        errors = 0

        for ch in chapters:
            existing = await _db.topics.count_documents({"chapter_id": ch["id"]})
            if existing > 0 and not force:
                continue
            title   = ch.get("title", "").strip()
            content = (ch.get("content") or "").strip()
            if not title:
                continue

            topic_titles: list[str] = []
            if _call_llm and len(content) > 150:
                try:
                    msgs = [
                        {"role": "system", "content": (
                            "You are an educational curriculum analyst. "
                            "Extract 4-10 specific study topics a student would search for from this chapter. "
                            "Each topic: 2-7 words, NOT the chapter title itself. "
                            'Return ONLY a valid JSON array of strings, e.g. ["Topic One", "Topic Two"].'
                        )},
                        {"role": "user", "content": f"Chapter: {title}\n\nContent:\n{content[:4000]}"},
                    ]
                    raw = await asyncio.wait_for(_call_llm(msgs, max_tokens=512), timeout=30)
                    topic_titles = _robust_parse_json_array(raw)
                except Exception as exc:
                    logger.warning(f"[run-subject] topic extract failed for {title!r}: {exc}")
                    errors += 1

            if not topic_titles:
                topic_titles = [title]

            if force and existing:
                await _db.topics.delete_many({"chapter_id": ch["id"]})

            base_order = ch.get("order_index", ch.get("chapter_number", 0))
            for idx, t_title in enumerate(topic_titles):
                await _db.topics.insert_one({
                    "id":            f"topic-{uuid.uuid4().hex[:8]}",
                    "chapter_id":    ch["id"],
                    "subject_id":    subject_id,
                    "chapter_title": title,
                    "title":         t_title,
                    "slug":          _slug(t_title),
                    "definition":    ch.get("description", ""),
                    "examples":      "",
                    "order":         base_order * 100 + idx,
                    "status":        "published",
                    "created_at":    datetime.now(timezone.utc).isoformat(),
                })
                new_topics += 1

        # ── Step 2: Generate SEO pages ────────────────────────────────────────
        topics = await _db.topics.find(
            {"subject_id": subject_id, "status": "published"}, {"_id": 0}
        ).to_list(2000)

        total_ops = len(topics) * len(page_types)
        _job_update(
            job_id,
            status="generating",
            total=total_ops,
            current=f"Generating pages for {len(topics)} topics × {len(page_types)} types…",
        )

        done = 0
        skipped = 0

        for topic in topics:
            _job_update(job_id, current=f"Topic: {topic.get('title', '')}")
            try:
                hierarchy = await _resolve_hierarchy(topic)
                if not hierarchy:
                    skipped += len(page_types)
                    done    += len(page_types)
                    _job_update(job_id, done=done, skipped=skipped)
                    continue

                for pt in page_types:
                    existing = await _db.seo_pages.find_one(
                        {"topic_id": topic["id"], "page_type": pt}, {"_id": 0, "id": 1}
                    )
                    if existing and not force:
                        skipped += 1
                        done    += 1
                        _job_update(job_id, done=done, skipped=skipped)
                        continue
                    try:
                        page = await _generate_single_page(topic, pt, hierarchy)
                        done += 1 if page else done
                    except Exception as ge:
                        logger.error(f"[run-subject] gen error {topic.get('id')}/{pt}: {ge}")
                        errors += 1
                        done   += 1
                    _job_update(job_id, done=done, errors=errors)

            except Exception as te:
                logger.error(f"[run-subject] topic loop error {topic.get('id')}: {te}")
                errors  += len(page_types)
                done    += len(page_types)
                _job_update(job_id, done=done, errors=errors)

        # ── Step 3: Log + finish ──────────────────────────────────────────────
        now = datetime.now(timezone.utc).isoformat()
        await _db.seo_generation_log.insert_one({
            "job_id": job_id, "subject_id": subject_id, "subject_name": sub_name,
            "new_topics": new_topics, "total_ops": total_ops,
            "generated": done - skipped - errors,
            "skipped": skipped, "errors": errors,
            "completed_at": now,
        })
        _job_update(
            job_id,
            status="done",
            finished_at=now,
            current=f"Done — {new_topics} new topics, {done - skipped - errors} pages generated, {skipped} skipped, {errors} errors",
        )
        await _seo_log(
            action="seo:subject_pipeline",
            details=f"Pipeline done for {sub_name}: {new_topics} topics + {done - skipped - errors} seo_pages generated",
        )

    except Exception as e:
        logger.error(f"[run-subject] bg job failed: {e}")
        _job_update(job_id, status="error", current=str(e), finished_at=datetime.now(timezone.utc).isoformat())


# ─── ADMIN: Full auto-run pipeline ──────────────────────────────────────────

@router.post("/auto-run")
async def auto_run_pipeline(
    background_tasks: BackgroundTasks,
    data: PageTypesRequest = PageTypesRequest(),
    _admin: dict = Depends(_require_admin),
):
    """One-click: extract all topics → generate all missing pages → regen sitemap.
    Defaults to AUTO_PAGE_TYPES (notes + mcqs) unless explicit page_types provided."""
    types_to_run = (data.page_types if data else None) or AUTO_PAGE_TYPES
    job_id = f"job-{uuid.uuid4().hex[:10]}"
    _seo_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "total": 0,
        "done": 0,
        "errors": 0,
        "skipped": 0,
        "current": "Starting…",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "page_types": types_to_run,
    }
    background_tasks.add_task(_auto_run_bg, job_id, types_to_run)
    return {"job_id": job_id, "message": "Pipeline started", "status": "queued"}


async def _auto_run_bg(job_id: str, page_types: list):
    try:
        _job_update(job_id, status="extracting", current="Extracting topics from chapters…")

        chapters = await _db.chapters.find({}, {"_id": 0}).to_list(5000)
        new_topics = 0
        for ch in chapters:
            existing = await _db.topics.count_documents({"chapter_id": ch["id"]})
            if existing > 0:
                continue
            title = ch.get("title", "").strip()
            if not title:
                continue
            has_syllabus_content = bool(ch.get("description") or ch.get("content"))
            topic = {
                "id": f"topic-{uuid.uuid4().hex[:8]}",
                "chapter_id": ch["id"],
                "subject_id": ch.get("subject_id", ""),
                "title": title,
                "slug": _slug(title),
                "definition": ch.get("description", ""),
                "examples": "",
                "order": ch.get("order_index", ch.get("chapter_number", 0)),
                "status": "published" if has_syllabus_content else "suggested",
                "source": "syllabus" if has_syllabus_content else "gap-fill",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            await _db.topics.insert_one(topic)
            new_topics += 1
            if not has_syllabus_content:
                logger.info(f"Auto-run: topic '{title}' created as suggested (no syllabus content in chapter)")


        # Step 2: Generate missing pages for all topics
        all_topics = await _db.topics.find({"status": "published"}, {"_id": 0}).to_list(10000)
        total_ops = len(all_topics) * len(page_types)
        _job_update(job_id, status="generating", total=total_ops, current=f"Generating pages for {len(all_topics)} topics…")

        done = 0
        errors = 0
        skipped = 0

        for topic in all_topics:
            _job_update(job_id, current=f"Processing: {topic.get('title', topic.get('id', ''))}")
            try:
                hierarchy = await _resolve_hierarchy(topic)
                if not hierarchy:
                    logger.warning(f"Auto-run: no hierarchy for topic {topic.get('id')} (chapter_id={topic.get('chapter_id')}) — skipping")
                    skipped += len(page_types)
                    done += len(page_types)
                    _job_update(job_id, done=done, skipped=skipped)
                    continue

                for pt in page_types:
                    existing = await _db.seo_pages.find_one(
                        {"topic_id": topic["id"], "page_type": pt},
                        {"_id": 0, "id": 1}
                    )
                    if existing:
                        skipped += 1
                        done += 1
                        _job_update(job_id, done=done, skipped=skipped)
                        continue
                    try:
                        page = await _generate_single_page(topic, pt, hierarchy)
                        if page:
                            done += 1
                        else:
                            errors += 1
                            done += 1
                    except Exception as e:
                        logger.error(f"Auto-run gen error {topic.get('id')}/{pt}: {e}")
                        errors += 1
                        done += 1
                    _job_update(job_id, done=done, errors=errors)

            except Exception as e:
                logger.error(f"Auto-run topic error {topic.get('id')}: {e}")
                errors += len(page_types)
                done += len(page_types)
                _job_update(job_id, done=done, errors=errors)

        # Step 3: Log to DB
        now = datetime.now(timezone.utc).isoformat()
        await _db.seo_generation_log.insert_one({
            "job_id": job_id,
            "total_generated": done - skipped - errors,
            "skipped": skipped,
            "errors": errors,
            "new_topics": new_topics,
            "completed_at": now,
        })

        _job_update(
            job_id,
            status="done",
            current=f"Complete — {done - skipped - errors} pages generated, {skipped} skipped, {errors} errors",
            finished_at=now,
        )
        logger.info(f"Auto-run {job_id} complete: done={done} skip={skipped} err={errors}")

    except Exception as e:
        logger.error(f"Auto-run pipeline error: {e}")
        _job_update(job_id, status="error", current=f"Pipeline error: {str(e)[:120]}", finished_at=datetime.now(timezone.utc).isoformat())


# ─── ADMIN: Gap-fill insights ────────────────────────────────────────────────

@router.get("/insights")
async def seo_insights(_admin: dict = Depends(_require_admin)):
    """AI gap analysis — returns actionable insight cards per subject/type."""
    # Aggregate: for each subject, count pages per page_type
    all_topics = await _db.topics.find({"status": "published"}, {"_id": 0, "id": 1, "chapter_id": 1, "title": 1, "subject_id": 1}).to_list(10000)
    topic_ids = [t["id"] for t in all_topics]

    # Count pages per topic_id × page_type
    page_docs = await _db.seo_pages.find(
        {"topic_id": {"$in": topic_ids}},
        {"_id": 0, "topic_id": 1, "page_type": 1, "subject_name": 1, "class_name": 1, "board_name": 1, "status": 1}
    ).to_list(100000)

    # Index existing pages
    page_index: dict = {}  # topic_id -> set of page_types
    subject_counts: dict = {}  # subject_name -> {page_type -> count, total_topics}
    for p in page_docs:
        tid = p["topic_id"]
        pt = p["page_type"]
        if tid not in page_index:
            page_index[tid] = set()
        page_index[tid].add(pt)

        sname = p.get("subject_name", "Unknown")
        if sname not in subject_counts:
            subject_counts[sname] = {
                "subject": sname,
                "board": p.get("board_name", ""),
                "class": p.get("class_name", ""),
                **{pt: 0 for pt in PAGE_TYPES},
                "published": 0,
                "draft": 0,
            }
        subject_counts[sname][pt] = subject_counts[sname].get(pt, 0) + 1
        if p.get("status") == "published":
            subject_counts[sname]["published"] += 1
        else:
            subject_counts[sname]["draft"] += 1

    # Topics with no pages at all
    no_pages = [t for t in all_topics if t["id"] not in page_index]
    # Topics missing specific page types
    gaps: dict = {}  # page_type -> count missing
    for t in all_topics:
        covered = page_index.get(t["id"], set())
        for pt in PAGE_TYPES:
            if pt not in covered:
                gaps[pt] = gaps.get(pt, 0) + 1

    # Build insight cards
    insights = []

    if no_pages:
        insights.append({
            "type": "critical",
            "icon": "alert",
            "title": f"{len(no_pages)} topics have no SEO pages at all",
            "description": f"Run Auto-Extract + Generate to create {len(no_pages) * len(PAGE_TYPES)} pages instantly.",
            "action": "auto-run",
            "count": len(no_pages),
        })

    for pt, missing_count in sorted(gaps.items(), key=lambda x: -x[1]):
        if missing_count == 0:
            continue
        labels = {"notes": "Notes", "definition": "Definitions", "important-questions": "Important Questions", "mcqs": "MCQs", "examples": "Solved Examples"}
        insights.append({
            "type": "gap",
            "icon": "generate",
            "title": f"{missing_count} topics missing {labels.get(pt, pt)} pages",
            "description": f"Generate {labels.get(pt, pt)} for all {missing_count} uncovered topics in one click.",
            "action": "generate",
            "page_type": pt,
            "count": missing_count,
        })

    # Per-subject breakdown (top 8 by draft/missing)
    subject_list = sorted(
        subject_counts.values(),
        key=lambda s: -(s.get("draft", 0))
    )[:8]

    return {
        "insights": insights,
        "subject_breakdown": subject_list,
        "summary": {
            "total_topics": len(all_topics),
            "topics_with_no_pages": len(no_pages),
            "page_type_gaps": gaps,
        },
    }


# ─── ADMIN: Board-level gap expand ──────────────────────────────────────────

@router.post("/expand/{board_slug}")
async def expand_board_content(
    board_slug: str,
    background_tasks: BackgroundTasks,
    data: PageTypesRequest = PageTypesRequest(),
    _admin: dict = Depends(_require_admin),
):
    """Generate all missing pages for a specific board (gap-fill only, skips existing)."""
    board = await _db.boards.find_one({"slug": board_slug}, {"_id": 0})
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{board_slug}' not found")

    types_to_run = (data.page_types if data else None) or PAGE_TYPES
    job_id = f"expand-{board_slug}-{uuid.uuid4().hex[:8]}"

    _seo_jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "board": board_slug,
        "total": 0,
        "done": 0,
        "errors": 0,
        "skipped": 0,
        "current": f"Starting gap-fill for {board.get('name', board_slug)}…",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    background_tasks.add_task(_expand_board_bg, job_id, board, types_to_run)
    return {"job_id": job_id, "message": f"Gap-fill started for {board.get('name', board_slug)}", "status": "queued"}


async def _expand_board_bg(job_id: str, board: dict, page_types: list):
    try:
        board_id = board["id"]
        classes = await _db.classes.find({"board_id": board_id}, {"_id": 0}).to_list(50)
        class_ids = [c["id"] for c in classes]
        streams = await _db.streams.find({"class_id": {"$in": class_ids}}, {"_id": 0}).to_list(200)
        stream_ids = [s["id"] for s in streams]
        subjects = await _db.subjects.find({"stream_id": {"$in": stream_ids}}, {"_id": 0}).to_list(500)
        subject_ids = [s["id"] for s in subjects]
        chapters = await _db.chapters.find({"subject_id": {"$in": subject_ids}}, {"_id": 0}).to_list(5000)
        ch_ids = [c["id"] for c in chapters]
        topics = await _db.topics.find({"chapter_id": {"$in": ch_ids}, "status": "published"}, {"_id": 0}).to_list(10000)

        total_ops = len(topics) * len(page_types)
        _job_update(job_id, status="generating", total=total_ops, current=f"Processing {len(topics)} topics for {board.get('name', '')}…")

        done = 0
        errors = 0
        skipped = 0

        for topic in topics:
            _job_update(job_id, current=f"{topic.get('title', topic.get('id', ''))}")
            try:
                hierarchy = await _resolve_hierarchy(topic)
                if not hierarchy:
                    errors += len(page_types)
                    done += len(page_types)
                    _job_update(job_id, done=done, errors=errors)
                    continue
                for pt in page_types:
                    existing = await _db.seo_pages.find_one({"topic_id": topic["id"], "page_type": pt}, {"_id": 0, "id": 1})
                    if existing:
                        skipped += 1
                        done += 1
                        _job_update(job_id, done=done, skipped=skipped)
                        continue
                    try:
                        page = await _generate_single_page(topic, pt, hierarchy)
                        done += 1
                        if not page:
                            errors += 1
                    except Exception as e:
                        logger.error(f"Expand gen error {topic.get('id')}/{pt}: {e}")
                        errors += 1
                        done += 1
                    _job_update(job_id, done=done, errors=errors)
            except Exception as e:
                logger.error(f"Expand topic error {topic.get('id')}: {e}")
                errors += len(page_types)
                done += len(page_types)
                _job_update(job_id, done=done, errors=errors)

        now = datetime.now(timezone.utc).isoformat()
        _job_update(
            job_id, status="done",
            current=f"Done — {done - skipped - errors} new pages, {skipped} skipped, {errors} errors",
            finished_at=now,
        )
    except Exception as e:
        logger.error(f"Expand board error: {e}")
        _job_update(job_id, status="error", current=str(e)[:200], finished_at=datetime.now(timezone.utc).isoformat())
