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
Primary keyword: "{topic} notes {board} {class_name}"

CRITICAL CONTENT RULES:
- Write ONLY about what {topic} actually covers according to the {board} {subject} syllabus under chapter "{chapter}". Do NOT invent content outside the topic's scope.
- First paragraph must be 2-3 sentences MAX, keyword-focused, starting with "{topic}" directly.
- Do NOT include generic math-style "solved examples" or "step-by-step problems" unless the topic genuinely involves calculations or problem-solving. For conceptual/theoretical topics, use illustrative case studies, real-world applications, or exam-style descriptive answers instead.
- Use keyword variations naturally: "{topic} notes", "{topic} summary", "{topic} {subject} notes {class_name}", "{topic} important points"
- Add human touches: "In simple terms…", "You can remember this as…", "Many students confuse X and Y — here's the difference."
- When mentioning other units/chapters, name them clearly (e.g., "Unit I: Introduction to..." or "Unit III: ...")

Write study notes using EXACTLY this structure — all sections required:

## What is {topic}? (Quick Answer)
[2-3 sentences ONLY. Direct, keyword-rich definition suitable for Google featured snippet. Start with "{topic} is..." or "{topic} refers to...". End with its relevance to {board} {class_name} {subject}.]

## {topic} — Detailed Notes for {board} {class_name}
[350-500 words. Cover ALL core concepts, sub-topics, and key ideas that {topic} contains according to the {board} syllabus for "{chapter}". Go deep into each concept — explain why it matters, how it works, and how it connects to other topics in this chapter. Use natural student-friendly language. Include Assam/Northeast India examples where relevant. Reference related syllabus topics by NAME.]

## Key Points for Revision
[8-10 bullet points covering the most important facts, definitions, and concepts from {topic}. Each should be a complete, exam-ready statement. Add one bullet like "Don't confuse [X] with [Y] — examiners love testing this."]

## Important Concepts & Applications
[For each major concept in {topic}, explain it with a real-world application or case study. Use Assam/India examples where they naturally fit. Format as 3-4 sub-sections with ### headings. This should demonstrate understanding, not math-style problem solving.]

## Exam-Style Questions with Answers
[6 questions with complete model answers covering {topic}:
- 2× short answer (1-2 marks): definition/factual recall
- 2× medium answer (3 marks): explain/compare/distinguish
- 2× long answer (5-7 marks): detailed analysis/discussion
Format: "Q (X marks): ..." with full model answer below each.]

## Frequently Asked Questions
Q1: What is {topic}? (1-mark answer)
A1: [Crisp 1-line answer]
Q2: What are the key concepts covered in {topic}?
A2: [List 4-5 main concepts]
Q3: Why is {topic} important for {board} exams?
A3: [Answer with exam relevance and mark weightage]
Q4: How does {topic} connect to other topics in {chapter}?
A4: [Show connections by naming related topics]

Language: simple, clear, and exam-focused for {class_name} students in Assam. Sound like a helpful teacher, not a textbook. Every section must contain substantive academic content specific to {topic}.""",

        """You are a {subject} expert specialising in {board} {class_name} exam preparation.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}
Primary keyword: "{topic} notes {board} {class_name}"

CRITICAL CONTENT RULES:
- Write ONLY about the actual academic content of {topic} as defined in the {board} syllabus under "{chapter}". Study the topic name carefully — it tells you exactly what to cover.
- Do NOT add generic "solved examples" with step-by-step math unless {topic} genuinely requires calculations. For descriptive/conceptual topics, use case studies, real-world illustrations, and application-based discussions instead.
- Naturally include search terms: "{topic} notes", "{topic} summary", "{topic} {subject} notes", "{topic} important questions"
- Add student-friendly lines: "Many students find this tricky — but it's actually straightforward.", "Pro tip:", "Common mistake:"
- Name other units/chapters explicitly when cross-referencing

Write comprehensive study notes using EXACTLY this structure:

## {topic} — Overview
[2-3 sentences ONLY. Start with "{topic}" directly. State what it covers, which chapter it belongs to, and why it matters for {board} {class_name} exams. Featured snippet paragraph.]

## Why {topic} Matters
[50-70 words: connect {topic} to real-world relevance using Assam/Northeast India context if applicable, then link to {board} importance. Add: "This is one of the most scoring topics in {subject}."]

## Core Concept
[Formal definition citing {board} curriculum. Then simplified: "In simple terms, {topic} means..." Mention what prerequisite knowledge is needed from earlier topics.]

## Detailed Breakdown
[400-500 words. Break {topic} into 3-5 sub-concepts based on what the topic actually covers in the syllabus. Use numbered ### sub-headings. For each sub-concept:
- Explain the concept thoroughly (what, why, how)
- Give one real-world application or Assam-relevant example
- Add an informal touch: "You can remember this as...", "A common exam mistake here is..."
Cross-reference other units by name where relevant.]

## Key Points for Revision
[8-10 crisp bullet points — exam-ready, complete statements. Include one "Don't confuse X with Y" point.]

## Exam Corner
[5 questions with model answers directly testing knowledge of {topic}:
- 1× define/identify (1 mark)
- 2× explain/describe (2-3 marks)
- 2× discuss/analyze (5 marks)
Add tips like "Examiners expect you to mention..." for long answers.]

## FAQ
Q1: What is {topic}? (Define in one line)
A1: [Single crisp sentence]
Q2: What are the main concepts covered in {topic}?
A2: [List 3-4 key concepts]
Q3: How is {topic} different from [related concept in {chapter}]?
A3: [Precise comparison]
Q4: What are common mistakes students make with {topic}?
A4: [2-3 common errors and how to avoid them]

Write for {class_name} students in Assam. Every section must contain genuine academic content specific to what {topic} actually covers — no filler, no generic examples.""",

        """You are a senior {board} examiner and {subject} faculty.

Topic: {topic}
Subject: {subject} | Chapter: {chapter} | Class: {class_name} | Board: {board}
Primary keyword: "{topic} notes {board} {class_name}"

CRITICAL CONTENT RULES:
- Focus EXCLUSIVELY on the academic content of {topic} as covered in the {board} {subject} syllabus under "{chapter}". The topic title tells you exactly what to write about.
- Do NOT force mathematical "solved examples" or "step-by-step problems" unless the topic involves actual problem-solving. For theory-based topics, use illustrative examples, case studies, comparisons, or exam-style descriptive answers instead.
- Include keyword variations: "{topic} notes", "{topic} summary", "{topic} {subject} notes {class_name}"
- Human signals: "This is arguably the most important concept in {chapter}.", "Here's what most toppers do...", "Don't skip this section."
- Name all cross-referenced units/chapters explicitly

Create study notes from an examiner's perspective using EXACTLY this structure:

## {topic} — Quick Summary
[2-3 sentences ONLY. Direct definition starting with "{topic}". State chapter, subject, board context. Featured-snippet optimized.]

## At a Glance
- **Topic**: {topic}
- **Chapter**: {chapter}
- **Subject**: {subject} ({board} {class_name})
- **Exam Weight**: [estimated marks based on topic importance]
- **Key Concepts**: [list 3-4 main concepts covered]
- **Related Topics**: [name 2-3 from same/nearby chapters]

## The Basics
[Academic definition with textbook citation. Then plain-English: "In simple terms..." Note prerequisite topics by name.]

## In-Depth Analysis
[350-500 words. Cover every important concept within {topic} thoroughly. Use cause-and-effect or thematic flow — NOT bullet lists. Include:
- Deep explanations of each sub-concept within {topic}
- Cross-references to other chapters BY NAME
- Real-world applications or case studies relevant to Assam/India
- "Many students confuse this with... — here's how to tell them apart."
- "A helpful way to remember this is..."]

## Common Exam Patterns
[How {board} examiners frame questions on {topic}. What aspects they test most. What traps to watch for. What earns full marks. Add: "Pro tip: Always mention [X] in your answer — it's worth 1 extra mark."]

## Exam Questions with Model Answers
Q1 (1 mark): Define {topic}. → [1-line answer]
Q2 (2 marks): [Explain/describe question on {topic}] → [Complete answer]
Q3 (3 marks): [Compare/distinguish question] → [Structured answer]
Q4 (5 marks): [Discuss/analyze question on {topic}] → [Detailed answer with marking scheme points]

## Memory Aids
[2-3 mnemonics or tricks specific to {topic}. Format as memorable phrases students can actually use in exams.]

## Quick Revision Points
[7-10 bullet points covering everything a student must know about {topic} the night before the {board} exam. Each should be a complete statement. Include: "If you remember nothing else, remember THIS: ..."]

Tone: authoritative but warm. Every section must contain high-quality academic content specific to {topic} — no filler or generic content.""",
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
        "{topic} Notes for {board} {subject} ({grade}) – Complete Guide",
        "{topic} Notes {board} {grade} {subject} | Summary & Key Points",
        "{topic} {subject} Notes – {board} {grade} Assam Universities",
        "{topic} Study Notes for {board} {grade} {subject} Exam Prep",
    ],
    "definition": [
        "What is {topic}? Definition for {board} {grade} {subject}",
        "{topic} Definition & Meaning – {board} {grade} {subject} Notes",
        "Define {topic} – {subject} {board} {grade} (1-Mark Answer)",
    ],
    "important-questions": [
        "{topic} Important Questions – {board} {grade} {subject} Exam",
        "{topic} Questions & Answers for {board} {grade} | 1 to 5 Marks",
        "{board} {grade} {topic} Important Questions with Answers | {subject}",
        "{topic} Question Bank – {subject} {board} {grade} Assam",
    ],
    "mcqs": [
        "{topic} MCQs with Answers – {board} {grade} {subject}",
        "{topic} MCQ Practice for {board} {grade} Exam | {subject}",
        "{topic} Multiple Choice Questions – {grade} {board} {subject}",
    ],
    "examples": [
        "{topic} Solved Examples – {board} {grade} {subject}",
        "{topic} Problems with Solutions for {board} {grade} Exams",
        "{topic} Step-by-Step Solutions | {grade} {board} {subject}",
    ],
}


def _strip_markdown_symbols(text: str) -> str:
    """Remove all markdown symbols from text for clean meta descriptions."""
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}', '', text)
    text = re.sub(r'_{1,3}', '', text)
    text = re.sub(r'`{1,3}', '', text)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _normalize_headings(content: str) -> str:
    """Normalize malformed markdown headings from LLM output.
    Fixes: **## H**, ## **H**, ### ## H, ---\\n## H, and missing spaces."""
    content = re.sub(r'\*{1,3}(#{1,6})\s*(.+?)\*{1,3}', r'\1 \2', content, flags=re.MULTILINE)
    content = re.sub(r'^(#{1,6})\s*\*{1,3}(.+?)\*{1,3}\s*$', r'\1 \2', content, flags=re.MULTILINE)
    content = re.sub(r'^#{1,6}\s+#{1,6}\s+', '## ', content, flags=re.MULTILINE)
    content = re.sub(r'^(#{1,6})([^\s#])', r'\1 \2', content, flags=re.MULTILINE)
    content = re.sub(r'^---+\s*\n(#{1,6}\s)', r'\1', content, flags=re.MULTILINE)
    return content


def _clamp_meta_description(text: str, min_len: int = 140, max_len: int = 160) -> str:
    """Clamp text to 140-160 characters, trimming at word boundary or returning as-is if short."""
    if len(text) > max_len:
        text = text[:155].rsplit(' ', 1)[0] + '...'
    return text


def _extract_summary_from_content(content: str) -> str | None:
    """Extract the Summary section from generated markdown content.
    Tries known heading patterns first, then falls back to first paragraph.
    Returns a clean sentence of 140-160 characters with no markdown symbols."""
    candidates = []

    match = re.search(
        r'##\s*(?:Summary|At a Glance|In One Line|Why .+ Matters|What to Expect|'
        r'About These Questions|What Examiners Ask[^\n]*|'
        r'What is .+\?[^\n]*|.+ (?:—|–) Overview|.+ (?:—|–) Quick Summary)\s*\n+(.*?)(?:\n##|\Z)',
        content,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        text = _strip_markdown_symbols(match.group(1).strip())
        if len(text) >= 30:
            candidates.append(text)

    lines = content.split('\n')
    current_para = []
    for line in lines + ['']:
        stripped = line.strip()
        if not stripped:
            if current_para:
                para_text = ' '.join(current_para)
                clean = _strip_markdown_symbols(para_text)
                if len(clean) >= 40:
                    candidates.append(clean)
                current_para = []
        elif stripped.startswith('#') or stripped.startswith('['):
            if current_para:
                para_text = ' '.join(current_para)
                clean = _strip_markdown_symbols(para_text)
                if len(clean) >= 40:
                    candidates.append(clean)
                current_para = []
        else:
            current_para.append(stripped)

    if not candidates:
        return None

    best = None
    for c in candidates:
        clamped = _clamp_meta_description(c)
        if 140 <= len(clamped) <= 160:
            return clamped
        if best is None or abs(len(clamped) - 150) < abs(len(best) - 150):
            best = clamped

    if best and len(best) < 140 and len(candidates) > 1:
        combined = ' '.join(candidates)
        combined = re.sub(r'\s+', ' ', combined).strip()
        return _clamp_meta_description(combined)

    return best


REQUIRED_SECTIONS = {
    "notes": ["explanation", "example", "key point", "revision", "faq", "exam"],
    "definition": ["definition", "meaning", "example"],
    "important-questions": ["1-mark", "2-mark", "5-mark", "long answer", "short answer"],
    "mcqs": ["easy", "medium", "hard", "answer", "explanation"],
    "examples": ["example", "solution", "step", "practice"],
}


_QUALITY_PUBLISH_THRESHOLD = 90

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

    has_faq = bool(re.search(r'#{2,4}\s*(FAQ|Frequently Asked|Common Question)', content, re.IGNORECASE))
    has_exam_q = bool(re.search(r'#{2,4}\s*(Exam.Style|Commonly Tested|Board Pattern|Previous Year|PYQ|Frequently Repeated|Board Question|Exam Question|Exam.Ready|Practice Question)', content, re.IGNORECASE))
    has_examples = bool(re.search(r'(Example\s*\d|#{2,4}\s*(Example|Solved Example|Illustration|Worked Example|Important Concepts|Applications|Case Stud|In.Depth Analysis))', content, re.IGNORECASE))
    has_key_points = bool(re.search(r'#{2,4}\s*(Key Point|Key Takeaway|Important Point|Revision|Summary|Points to Remember|Quick Recap|At a Glance)', content, re.IGNORECASE))
    has_tips = bool(re.search(r'(exam tip|revision tip|remember|important note|pro tip|study tip|scoring tip)', content_lower))
    has_citations = bool(re.search(r'(syllabus|NCERT|SCERT|textbook|curriculum|prescribed|as per the)', content, re.IGNORECASE))
    has_marks_ref = bool(re.search(r'(\d\s*-?\s*marks?\b|short answer|long answer|objective type|very short)', content, re.IGNORECASE))

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
    if word_count >= 800: score += 18
    elif word_count >= 600: score += 12
    elif word_count >= 400: score += 6
    if heading_count >= 8: score += 12
    elif heading_count >= 6: score += 9
    elif heading_count >= 4: score += 5
    if unique_ratio >= 0.35: score += 8
    elif unique_ratio >= 0.28: score += 4
    if sections_ratio >= 0.8: score += 8
    elif sections_ratio >= 0.5: score += 4
    if has_faq: score += 10
    if has_exam_q: score += 10
    if has_examples: score += 8
    if has_key_points: score += 5
    if has_tips: score += 5
    if anchored: score += 4
    if has_citations: score += 6
    if has_marks_ref: score += 6

    return {
        "word_count": word_count,
        "heading_count": heading_count,
        "unique_ratio": unique_ratio,
        "sections_ratio": sections_ratio,
        "has_faq": has_faq,
        "has_exam_q": has_exam_q,
        "has_examples": has_examples,
        "has_key_points": has_key_points,
        "has_tips": has_tips,
        "anchored": anchored,
        "has_citations": has_citations,
        "has_marks_ref": has_marks_ref,
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
    if chapter_id and _db is not None:
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

    _QUALITY_SYSTEM = (
        f"You are an expert {board_display} teacher specialising in {subject_name} "
        f"for {prompt_class_label} students in Assam, India. "
        f"Chapter: \"{chapter_title}\" | Topic position: {syllabus_position or 'N/A'}. "
        f"Create educational content that is comprehensive, exam-focused, syllabus-aligned, "
        f"and easy to understand. This is a LESSON-LEVEL page covering the ENTIRE chapter/unit — "
        f"not a subtopic. Cover ALL key concepts from this chapter comprehensively. "
        f"Reference the chapter context and connect to neighboring topics "
        f"in the syllabus where relevant. Use {board_display} exam marking patterns.\n\n"
        f"MANDATORY QUALITY RULES — your content MUST include ALL of these:\n"
        f"1. At least 800 words of detailed, original content with deep explanations\n"
        f"2. At least 8 Markdown headings (## or ###) for clear structure\n"
        f"3. A '## FAQ' or '## Frequently Asked Questions' section with 3-5 Q&As\n"
        f"4. A '## Exam-Style Questions' section with 2-mark, 5-mark, and long-answer board exam pattern questions\n"
        f"5. At least 2 concrete examples (labeled 'Example 1:', 'Example 2:' etc.)\n"
        f"6. A '## Key Points' or '## Revision Notes' section summarizing essentials\n"
        f"7. Include 'Exam tip:', 'Revision tip:', or 'Important note:' callouts\n"
        f"8. Mention the board name ({board_display}), subject ({subject_name}), "
        f"and chapter ({chapter_title}) naturally in the text\n"
        f"9. Use diverse vocabulary — avoid repeating the same phrases\n"
        f"10. MANDATORY: Reference curriculum/syllabus sources — use phrases like "
        f"'As per the {board_display} syllabus', 'prescribed in the SCERT/NCERT curriculum', "
        f"'as outlined in the {subject_name} textbook', 'per the university syllabus'\n"
        f"11. MANDATORY: Include exam marking references — '2-mark question', '5-mark answer', "
        f"'long answer (10 marks)', 'short answer type' to match board exam patterns\n"
        f"12. Include Assam-specific context where relevant — local examples, regional institutions, "
        f"Assamese context that connects the academic content to students' lived experience\n"
    )

    messages = [
        {"role": "system", "content": _QUALITY_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    min_words = {"notes": 700, "definition": 500, "important-questions": 550, "mcqs": 500, "examples": 500}
    required_min = min_words.get(page_type, 500)

    async def _generate_and_score(msgs, attempt=1):
        try:
            raw = await asyncio.wait_for(_call_llm(msgs, max_tokens=3072), timeout=120)
        except asyncio.TimeoutError:
            logger.error(f"LLM timeout generating {page_type} for {topic['title']} (attempt {attempt})")
            return None, 0
        except Exception as e:
            logger.error(f"LLM error generating {page_type} for {topic['title']}: {type(e).__name__} (attempt {attempt})")
            return None, 0
        raw = _normalize_headings(raw)
        wc = len(raw.split())
        if wc < required_min:
            logger.warning(f"Content too short ({wc} words, min {required_min}) for {topic['title']}/{page_type} (attempt {attempt})")
            return None, 0
        qctx = {"board_name": board_display, "subject_name": subject_name, "chapter_title": chapter_title}
        qs = _compute_quality_score(raw, page_type, context=qctx)
        return raw, qs.get("score", 0)

    content, first_score = await _generate_and_score(messages, attempt=1)
    attempt_scores = [{"attempt": 1, "score": first_score}]

    def _build_retry_prompt(current_content, current_score, retry_number):
        qctx = {"board_name": board_display, "subject_name": subject_name, "chapter_title": chapter_title}
        diag = _compute_quality_score(current_content, page_type, context=qctx)

        if retry_number == 1:
            boost = (
                f"The previous attempt scored {current_score}/100. Improve it to score above {_QUALITY_PUBLISH_THRESHOLD}.\n"
                f"MISSING ELEMENTS — add ALL of these:\n"
            )
            if not diag.get("has_faq"):
                boost += "- Add a '## FAQ' section with 3-5 questions and answers\n"
            if not diag.get("has_exam_q"):
                boost += "- Add a '## Exam-Style Questions' section with 2-mark, 5-mark, and long-answer board-pattern questions\n"
            if not diag.get("has_examples"):
                boost += "- Add an 'Important Concepts & Applications' or 'Case Studies' section with real-world applications of the topic (NOT generic math-style solved examples unless the topic involves calculations)\n"
            if diag.get("heading_count", 0) < 8:
                boost += "- Add more ## and ### headings (need at least 8 for comprehensive lesson coverage)\n"
            if diag.get("word_count", 0) < 800:
                boost += "- Expand content to at least 800 words with deeper explanations\n"
            if not diag.get("anchored"):
                boost += f"- Mention {board_display}, {subject_name}, and {chapter_title} in the text\n"
            if not diag.get("has_key_points"):
                boost += "- Add a '## Key Points' or '## Revision Notes' section\n"
            if not diag.get("has_tips"):
                boost += "- Add exam tips, revision tips, or important notes throughout\n"
            if not diag.get("has_citations"):
                boost += f"- Add curriculum citations: 'As per the {board_display} syllabus', 'prescribed in SCERT/NCERT curriculum'\n"
            if not diag.get("has_marks_ref"):
                boost += "- Add exam marks references: '2-mark question', '5-mark answer', 'long answer (10 marks)'\n"
            boost += "\nRewrite the COMPLETE content with ALL improvements. Return ONLY the improved content."
        elif retry_number == 2:
            boost = (
                f"The previous attempt scored {current_score}/100 (target: {_QUALITY_PUBLISH_THRESHOLD}+).\n"
                f"Focus on DEPTH and WORD COUNT:\n"
                f"- Expand every section with deeper explanations, more detail, and real-world examples\n"
                f"- Target at least 800 words of dense, high-value content\n"
                f"- Add more sub-headings (###) for better structure\n"
                f"- Ensure every section has at least 3-4 sentences of explanation\n"
                f"- Add Assam-specific context or {board_display} exam patterns where relevant\n"
                f"\nRewrite the COMPLETE content with deeper, more detailed explanations. Return ONLY the improved content."
            )
        else:
            boost = (
                f"Previous attempts scored below {_QUALITY_PUBLISH_THRESHOLD}. Simplify and ensure these minimum requirements:\n"
                f"- At least 500 words\n"
                f"- At least 5 headings (## or ###)\n"
                f"- A FAQ section with 3 Q&As\n"
                f"- A Key Points section\n"
                f"- Mention {board_display}, {subject_name}, and {chapter_title}\n"
                f"\nWrite clean, simple content covering the topic thoroughly. Return ONLY the content."
            )
        return boost

    best_content, best_score = content, first_score

    for retry_num in range(1, 4):
        if best_content is not None and best_score >= _QUALITY_PUBLISH_THRESHOLD:
            break

        if best_content is not None:
            boost_prompt = _build_retry_prompt(best_content, best_score, retry_num)
            retry_msgs = [
                {"role": "system", "content": _QUALITY_SYSTEM},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": best_content},
                {"role": "user", "content": boost_prompt},
            ]
        else:
            retry_msgs = [
                {"role": "system", "content": _QUALITY_SYSTEM},
                {"role": "user", "content": prompt + "\n\nIMPORTANT: Ensure comprehensive coverage with at least 500 words. Include FAQ, Key Points, and examples."},
            ]

        new_content, new_score = await _generate_and_score(retry_msgs, attempt=retry_num + 1)
        attempt_scores.append({"attempt": retry_num + 1, "score": new_score})
        logger.info(f"Retry {retry_num} for {topic['title']}/{page_type}: score={new_score} (best so far: {best_score})")

        if new_content is not None and (best_content is None or new_score > best_score):
            best_content, best_score = new_content, new_score

    content, first_score = best_content, best_score
    logger.info(f"Generation complete for {topic['title']}/{page_type}: final_score={first_score}, attempts={attempt_scores}")

    if content is None:
        return None

    word_count = len(content.split())
    if word_count < required_min:
        logger.warning(f"Generated content too short ({word_count} words, min {required_min}) for {topic['title']} / {page_type} — rejecting")
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
            "notes": "notes with summary, key points & important questions",
            "definition": "definition, meaning & examples",
            "important-questions": "important questions with answers (1-mark to 5-mark)",
            "mcqs": "MCQ practice questions with answers",
            "examples": "solved examples with step-by-step solutions",
        }
        meta_desc = (
            f"{topic['title']} {type_label_map.get(page_type, 'notes')} "
            f"for {board_display} {grade_str} {subject_name}. "
            f"Exam-focused study material for Assam university students."
        )

    quality_context = {
        "board_name": board_display,
        "subject_name": subject_name,
        "chapter_title": h.get("chapter", {}).get("title", ""),
    }
    quality_score = _compute_quality_score(content, page_type, context=quality_context)
    q_score = quality_score.get("score", 0)

    if q_score >= _QUALITY_PUBLISH_THRESHOLD:
        page_status = "published"
    else:
        page_status = "rejected"
        logger.warning(f"Page for {topic['title']}/{page_type} scored {q_score} — rejected (below {_QUALITY_PUBLISH_THRESHOLD} quality threshold)")

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
            raise HTTPException(status_code=404, detail="No topics found. Run extract-topics or generate-lessons first.")

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


@router.post("/generate-lessons")
async def generate_lesson_pages(background_tasks: BackgroundTasks, _admin: dict = Depends(_require_admin)):
    """Lesson-wise SEO generation: 1 topic + 1 notes page per chapter.
    Directly links to content card lessons. Enforces max 1 page per chapter."""
    chapters = await _db.chapters.find({}, {"_id": 0}).to_list(5000)
    if not chapters:
        raise HTTPException(status_code=404, detail="No chapters found in database")

    existing_topics = {}
    async for t in _db.topics.find({}, {"_id": 0}):
        existing_topics[t.get("chapter_id", "")] = t

    created_topics = 0
    skipped = 0
    to_generate = []

    for ch in chapters:
        ch_id = ch["id"]
        if ch_id in existing_topics:
            existing_page = await _db.seo_pages.find_one(
                {"topic_id": existing_topics[ch_id]["id"], "status": "published"},
                {"_id": 0, "id": 1}
            )
            if existing_page:
                skipped += 1
                continue
            to_generate.append(existing_topics[ch_id])
            continue

        subj = await _db.subjects.find_one({"id": ch.get("subject_id", "")}, {"_id": 0})
        board = None
        if subj:
            board = await _db.boards.find_one({"id": subj.get("board_id", "")}, {"_id": 0})

        subject_name = subj["name"] if subj else ""
        board_name = board["name"] if board else "DEGREE"
        title = ch.get("title", "")

        topic_id = f"topic-{uuid.uuid4().hex[:8]}"
        topic_slug = _slug(title)
        primary_kw = f"{title.lower()} {subject_name.lower()} {board_name}".strip()[:120]

        topic = {
            "id": topic_id,
            "chapter_id": ch_id,
            "subject_id": ch.get("subject_id", ""),
            "chapter_title": title,
            "subject_name": subject_name,
            "board_name": board_name,
            "title": title,
            "slug": topic_slug,
            "primary_keyword": primary_kw,
            "search_intent": "informational",
            "definition": "",
            "examples": "",
            "order": ch.get("order_index", 0),
            "status": "published",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await _db.topics.insert_one(topic)
        await _db.chapters.update_one(
            {"id": ch_id},
            {"$set": {"linked_topic_ids": [topic_id]}}
        )
        created_topics += 1
        to_generate.append(topic)

    if to_generate:
        background_tasks.add_task(_batch_generate, to_generate, ["notes"])

    return {
        "message": (
            f"Lesson-wise generation: {created_topics} topics created, "
            f"{len(to_generate)} pages queued, {skipped} already complete"
        ),
        "total_chapters": len(chapters),
        "topics_created": created_topics,
        "pages_queued": len(to_generate),
        "already_complete": skipped,
    }


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


class QualityEditRequest(BaseModel):
    min_score: Optional[int] = 90
    page_ids: Optional[List[str]] = None
    limit: Optional[int] = 50


@router.post("/quality-edit")
async def quality_edit_pages(data: QualityEditRequest, background_tasks: BackgroundTasks, _admin: dict = Depends(_require_admin)):
    """Delete low-scoring published pages and regenerate them with the quality retry loop."""
    query: dict = {"status": "published"}
    if data.page_ids:
        query["id"] = {"$in": data.page_ids}
    else:
        query["quality_score.score"] = {"$lt": data.min_score}

    low_pages = await _db.seo_pages.find(query, {"_id": 0, "id": 1, "topic_id": 1, "page_type": 1, "quality_score.score": 1}).to_list(data.limit)
    if not low_pages:
        return {"message": "No low-scoring pages found", "count": 0}

    page_ids_to_delete = [p["id"] for p in low_pages]
    regen_specs = [(p["topic_id"], p["page_type"]) for p in low_pages]

    await _db.seo_pages.delete_many({"id": {"$in": page_ids_to_delete}})

    background_tasks.add_task(_quality_regen_batch, regen_specs)
    return {
        "message": f"Deleted {len(page_ids_to_delete)} low-scoring pages, regeneration started",
        "count": len(page_ids_to_delete),
        "deleted_ids": page_ids_to_delete,
    }


async def _quality_regen_batch(specs: list):
    """Regenerate pages from (topic_id, page_type) specs."""
    total = 0
    errors = 0
    for topic_id, page_type in specs:
        try:
            topic = await _db.topics.find_one({"id": topic_id}, {"_id": 0})
            if not topic:
                continue
            hierarchy = await _resolve_hierarchy(topic)
            if not hierarchy:
                continue
            page = await _generate_single_page(topic, page_type, hierarchy)
            if page:
                total += 1
        except Exception as e:
            logger.error(f"Quality regen error for {topic_id}/{page_type}: {e}")
            errors += 1
        await asyncio.sleep(1)

    await _seo_log(
        action="seo:quality_edit_complete",
        details=f"Quality edit regenerated {total}/{len(specs)} pages" + (f" · {errors} errors" if errors else ""),
        level="info" if errors == 0 else "warn",
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


@router.get("/page/{board}/{class_slug}/{subject_slug}/{topic_slug}/{page_type}")
async def get_seo_page_typed(board: str, class_slug: str, subject_slug: str, topic_slug: str, page_type: str):
    from starlette.responses import JSONResponse
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
    result = await _inject_qa(page)
    resp = JSONResponse(result)
    resp.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400"
    return resp


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
    "description": (
        "Syrabit.ai is an academic content platform that produces syllabus-aligned study material "
        "for AHSEC (Assam Higher Secondary Education Council), SEBA (Board of Secondary Education, Assam), "
        "and NEP FYUGP Degree students. Content follows official board/university curricula "
        "and is editorially reviewed for accuracy, exam relevance, and academic depth."
    ),
    "foundingDate": "2025",
    "knowsAbout": [
        "AHSEC syllabus", "SEBA syllabus", "NEP FYUGP curriculum",
        "Assam Board examinations", "Gauhati University syllabus",
        "Dibrugarh University syllabus", "Higher education in Assam",
    ],
    "sameAs": ["https://twitter.com/SyrabitAI"],
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

_BOARD_SYLLABUS_SOURCE = {
    "AHSEC": "Assam Higher Secondary Education Council (AHSEC) official syllabus",
    "SEBA": "Board of Secondary Education, Assam (SEBA) official syllabus",
    "NEP FYUGP": "National Education Policy (NEP) 2020 FYUGP curriculum as adopted by Assam universities (Gauhati University, Dibrugarh University, Cotton University)",
    "Degree": "National Education Policy (NEP) 2020 FYUGP curriculum as adopted by Assam universities (Gauhati University, Dibrugarh University, Cotton University)",
}

_PAGE_TYPE_METHODOLOGY = {
    "notes": "structured study notes following the definition → explanation → examples → exam tips format, aligned to the official syllabus",
    "definition": "formal academic definitions with context, etymology where relevant, and exam-oriented explanations",
    "important-questions": "mark-wise important questions curated from previous year papers and syllabus weightage analysis",
    "mcqs": "multiple choice questions with correct answers and explanations, covering key concepts from the syllabus",
    "examples": "solved examples following the problem → approach → step-by-step solution → exam tip format",
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

    syllabus_source = ""
    for bkey in _BOARD_SYLLABUS_SOURCE:
        if bkey.lower() in board.lower() or bkey.lower() in edu_level.lower():
            syllabus_source = _BOARD_SYLLABUS_SOURCE[bkey]
            break
    if not syllabus_source:
        syllabus_source = _BOARD_SYLLABUS_SOURCE.get("Degree", "Official board/university syllabus")

    content_methodology = _PAGE_TYPE_METHODOLOGY.get(page_type, "syllabus-aligned study material")

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
            "educationalAlignment": {
                "@type": "AlignmentObject",
                "alignmentType": "educationalSubject",
                "educationalFramework": syllabus_source,
                "targetName": page.get("subject_name", ""),
                "targetDescription": f"{page.get('chapter_title', '')} — {page.get('topic_title', '')}",
            },
            "sourceOrganization": _ORG_NODE,
        },
        {
            "@type": "LearningResource",
            "name": f"{topic} — {edu_level}".strip(),
            "description": page.get("meta_description", ""),
            "provider": _ORG_NODE,
            "educationalLevel": edu_level,
            "url": page_url,
            "inLanguage": "en-IN",
            "learningResourceType": {"notes": "Study Notes", "definition": "Definitions", "important-questions": "Practice Questions", "mcqs": "Multiple Choice Questions", "examples": "Examples"}.get(page_type, "Study Material"),
            "isAccessibleForFree": True,
            "educationalAlignment": {
                "@type": "AlignmentObject",
                "alignmentType": "educationalSubject",
                "educationalFramework": syllabus_source,
                "targetName": page.get("subject_name", ""),
            },
            "teaches": page.get("topic_title", ""),
            "assesses": page.get("topic_title", "") if page_type in ("mcqs", "important-questions") else None,
            "competencyRequired": f"Basic understanding of {page.get('subject_name', '')}",
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

    if not faq_items and topic:
        faq_items.append({
            "@type": "Question",
            "name": f"What is {page.get('topic_title', '')} in {page.get('subject_name', '')}?",
            "acceptedAnswer": {
                "@type": "Answer",
                "text": f"{page.get('topic_title', '')} is a topic in {page.get('subject_name', '')} covered under {page.get('chapter_title', '')} for {page.get('board_name', '')} {page.get('class_name', '')} students. Visit Syrabit.ai for detailed study notes, examples, and practice questions.",
            },
        })

    if faq_items:
        graph_nodes.append({
            "@type": "FAQPage",
            "mainEntity": faq_items,
        })

    def _strip_none(obj):
        if isinstance(obj, dict):
            return {k: _strip_none(v) for k, v in obj.items() if v is not None}
        if isinstance(obj, list):
            return [_strip_none(i) for i in obj]
        return obj
    ld_json = json.dumps({"@context": "https://schema.org", "@graph": _strip_none(graph_nodes)}, ensure_ascii=False)

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
<meta http-equiv="content-language" content="en-IN">
<link rel="alternate" hreflang="en-IN" href="{html_mod.escape(page_url)}">
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
.content-info{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem 1.25rem;margin:2rem 0}}
.content-info h2{{margin-top:0;font-size:1rem;color:#334155}}.content-info dl{{margin:0}}.content-info dt{{font-weight:600;color:#475569;margin-top:.5rem;font-size:.9rem}}.content-info dd{{margin:0 0 .25rem 0;color:#64748b;font-size:.85rem}}
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
<section class="content-info">
<h2>About This Study Material</h2>
<dl>
<dt>Syllabus Source</dt><dd>{html_mod.escape(syllabus_source)}</dd>
<dt>Content Type</dt><dd>This page contains {html_mod.escape(content_methodology)}.</dd>
<dt>Subject</dt><dd>{subject} — {board} {cls}</dd>
<dt>Chapter</dt><dd>{chapter}</dd>
<dt>Topic</dt><dd>{topic}</dd>
<dt>Editorial Process</dt><dd>Content is prepared by subject-matter contributors, cross-referenced with the official {html_mod.escape(board)} syllabus, and editorially reviewed for factual accuracy, exam relevance, and completeness. Each page follows a structured academic format: formal definitions, detailed explanations, solved examples with Assam-specific context, exam tips, and practice questions with model answers.</dd>
<dt>Last Updated</dt><dd>{html_mod.escape(updated[:10] if updated else '')}</dd>
<dt>Publisher</dt><dd>Syrabit.ai — Academic content platform for Assam students</dd>
</dl>
</section>
<footer>
<p>Source: <a href="{html_mod.escape(page_url)}">Syrabit.ai — {topic}</a></p>
<p>&copy; Syrabit.ai — Syllabus-aligned study material for {html_mod.escape(board)} ({html_mod.escape(cls)}) students</p>
<p>Content follows the official {html_mod.escape(board)} curriculum. For the latest syllabus, refer to your board/university website.</p>
<p class="geo-footer">Serving students across Assam, India — Guwahati, Jorhat, Dibrugarh, Dhemaji, Tezpur, Silchar, Nagaon, Barpeta, and more.</p>
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
        "Comprehensive study platform for Assam Board (AHSEC/SEBA) and Degree students. "
        "Free syllabus-aligned notes, previous year questions, MCQs, and important questions "
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
         "description": "Syllabus-aligned study platform for Assam Board students",
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
<meta http-equiv="content-language" content="en-IN">
<link rel="alternate" hreflang="en-IN" href="https://syrabit.ai">
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
<p>Free syllabus-aligned study material for <strong>AHSEC</strong>, <strong>SEBA</strong>, and <strong>Degree</strong> students in Assam.</p>
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
<p>&copy; Syrabit.ai — Free syllabus-aligned exam prep for Assam Board (AHSEC/SEBA) &amp; Degree students</p>
<p class="geo-footer">Serving students in Guwahati, Jorhat, Dibrugarh, Dhemaji, Tezpur, Silchar, and across Assam, India</p>
<p><a href="https://syrabit.ai/library">Full Library</a> &middot; <a href="https://syrabit.ai/pricing">Pricing</a> &middot; <a href="https://syrabit.ai/sitemap.xml">Sitemap</a></p>
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

    board_doc = await _db.boards.find_one({"slug": board}, {"_id": 0, "id": 1})
    subject_query = {"slug": subject_slug}
    if board_doc:
        subject_query["board_id"] = board_doc["id"]
    subject_doc = await _db.subjects.find_one(
        subject_query,
        {"_id": 0, "name": 1, "description": 1, "id": 1},
    )
    if not subject_doc:
        subject_doc = await _db.subjects.find_one(
            {"slug": subject_slug},
            {"_id": 0, "name": 1, "description": 1, "id": 1},
        )
    subject_name = subject_doc["name"] if subject_doc else subject_slug.replace("-", " ").title()
    subject_desc_raw = subject_doc.get("description", "") if subject_doc else ""
    board_label = board.upper() if board in ("ahsec", "seba") else board.title()
    class_label = class_slug.replace("-", " ").title()

    chapters_docs = []
    if subject_doc and subject_doc.get("id"):
        chapters_docs = await _db.chapters.find(
            {"subject_id": subject_doc["id"]},
            {"_id": 0, "title": 1, "topics": 1, "order_index": 1},
        ).sort("order_index", 1).to_list(50)

    page_type_counts = {}
    async for rec in _db.seo_pages.aggregate([
        {"$match": {"board_slug": board, "class_slug": class_slug,
                     "subject_slug": subject_slug, "status": "published"}},
        {"$group": {"_id": "$page_type", "count": {"$sum": 1}}},
    ]):
        page_type_counts[rec["_id"]] = rec["count"]
    total_notes = page_type_counts.get("notes", 0)
    total_mcqs = page_type_counts.get("mcqs", 0)
    total_pyqs = page_type_counts.get("important-questions", 0)

    page_url = f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}"
    title = f"{subject_name} — {board_label} {class_label} Complete Study Guide | Syrabit.ai"
    desc = (
        f"Complete {subject_name} study guide for {board_label} {class_label} students. "
        f"Covers {len(chapters_docs) or len(set(p.get('chapter_title','') for p in pages))} chapters with "
        f"topic-wise notes, solved examples, MCQs, important questions, and previous year questions "
        f"aligned to the official syllabus."
    )

    syllabus_source = ""
    for bkey in _BOARD_SYLLABUS_SOURCE:
        if bkey.lower() in board.lower() or bkey.lower() in board_label.lower():
            syllabus_source = _BOARD_SYLLABUS_SOURCE[bkey]
            break
    if not syllabus_source:
        syllabus_source = _BOARD_SYLLABUS_SOURCE.get("Degree", "Official board/university syllabus")

    by_chapter: dict = {}
    for p in pages:
        ch = p.get("chapter_title", "General")
        by_chapter.setdefault(ch, []).append(p)

    subject_intro_html = ""
    if subject_desc_raw:
        subject_intro_html = f"<p>{html_mod.escape(subject_desc_raw)}</p>"

    chapter_names = list(by_chapter.keys())
    if not chapter_names and chapters_docs:
        chapter_names = [c.get("title", "") for c in chapters_docs]

    overview_parts = []
    overview_parts.append(f"<h2>Course Overview</h2>")
    if subject_intro_html:
        overview_parts.append(subject_intro_html)
    overview_parts.append(f"<p>This {html_mod.escape(subject_name)} course for {html_mod.escape(board_label)} {html_mod.escape(class_label)} students covers <strong>{len(chapter_names)} chapters</strong> and <strong>{len(pages)} topics</strong>. Content is prepared following the {html_mod.escape(syllabus_source)}.</p>")

    stats_parts = [f"<strong>{total_notes}</strong> study notes"]
    if total_mcqs:
        stats_parts.append(f"<strong>{total_mcqs}</strong> MCQ sets")
    if total_pyqs:
        stats_parts.append(f"<strong>{total_pyqs}</strong> PYQ sets")
    overview_parts.append(f'<p>Available resources: {", ".join(stats_parts)}.</p>')

    if chapters_docs:
        overview_parts.append("<h2>Syllabus Structure</h2>")
        overview_parts.append("<ol>")
        for ch in chapters_docs:
            ch_title = html_mod.escape(ch.get("title", ""))
            ch_topics = ch.get("topics", "")
            if ch_topics:
                if isinstance(ch_topics, list):
                    topic_list = ", ".join(str(t).strip() for t in ch_topics[:5])
                else:
                    topic_list = ", ".join(t.strip() for t in str(ch_topics).split(",")[:5])
                overview_parts.append(f"<li><strong>{ch_title}</strong> — {html_mod.escape(topic_list)}</li>")
            else:
                overview_parts.append(f"<li><strong>{ch_title}</strong></li>")
        overview_parts.append("</ol>")

    overview_html = "\n".join(overview_parts)

    topics_html_parts = []
    topics_html_parts.append("<h2>Topic-wise Study Material</h2>")
    for ch, ch_pages in by_chapter.items():
        topics_html_parts.append(f'<h3>{html_mod.escape(ch)}</h3><ul>')
        for tp in ch_pages:
            t_slug = tp.get("topic_slug", "")
            t_title = html_mod.escape(tp.get("topic_title", t_slug))
            t_desc = html_mod.escape(tp.get("meta_description", "")[:150])
            url = f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}/{t_slug}"
            topics_html_parts.append(
                f'<li><a href="{url}"><strong>{t_title}</strong></a>'
                f'<br><small>{t_desc}</small></li>'
            )
        topics_html_parts.append("</ul>")
    topics_html = "\n".join(topics_html_parts)

    learning_outcomes = [
        f"Understand core concepts of {subject_name} as prescribed in the {board_label} {class_label} syllabus",
        f"Apply theoretical knowledge to solve exam-style problems and case studies",
        f"Review previous year questions and understand marking patterns",
        f"Build exam confidence through topic-wise MCQs and practice questions",
    ]
    lo_html = "<h2>Learning Outcomes</h2><ul class='lo-list'>" + "".join(f"<li>{html_mod.escape(lo)}</li>" for lo in learning_outcomes) + "</ul>"

    items_ld = [
        {"@type": "ListItem", "position": i + 1, "name": p.get("topic_title", ""),
         "url": f"https://syrabit.ai/{board}/{class_slug}/{subject_slug}/{p.get('topic_slug', '')}"}
        for i, p in enumerate(pages)
    ]

    course_node = {
        "@type": "Course",
        "name": f"{subject_name} — {board_label} {class_label}",
        "description": desc,
        "provider": _ORG_NODE,
        "url": page_url,
        "educationalLevel": f"{board_label} {class_label}",
        "inLanguage": "en-IN",
        "isAccessibleForFree": True,
        "numberOfCredits": len(chapters_docs) or len(by_chapter),
        "hasCourseInstance": {
            "@type": "CourseInstance",
            "courseMode": "online",
            "courseWorkload": f"{len(pages)} topics across {len(chapters_docs) or len(by_chapter)} chapters",
        },
        "educationalAlignment": {
            "@type": "AlignmentObject",
            "alignmentType": "educationalSubject",
            "educationalFramework": syllabus_source,
            "targetName": subject_name,
        },
        "teaches": [p.get("topic_title", "") for p in pages[:10]],
        "audience": {
            "@type": "EducationalAudience",
            "educationalRole": "student",
            "geographicArea": {"@type": "State", "name": "Assam, India"},
        },
    }

    schema = json.dumps({"@context": "https://schema.org", "@graph": [
        {"@type": "CollectionPage", "name": title, "description": desc, "url": page_url,
         "isPartOf": {"@type": "WebSite", "@id": "https://syrabit.ai", "name": "Syrabit.ai"},
         "provider": _ORG_NODE,
         "spatialCoverage": _ASSAM_GEO,
         "audience": {"@type": "EducationalAudience", "educationalRole": "student",
                      "geographicArea": "Assam, India"},
         "educationalLevel": f"{board_label} {class_label}"},
        course_node,
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
<meta name="twitter:title" content="{html_mod.escape(title)}">
<meta name="twitter:description" content="{html_mod.escape(desc)}">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">
<meta name="geo.region" content="IN-AS">
<meta name="geo.placename" content="Assam, India">
<meta name="geo.position" content="26.2006;92.9376">
<meta name="ICBM" content="26.2006, 92.9376">
<meta property="og:image" content="https://syrabit.ai/opengraph.jpg">
<meta property="og:locale" content="en_IN">
<meta http-equiv="content-language" content="en-IN">
<link rel="alternate" hreflang="en-IN" href="{html_mod.escape(page_url)}">
<meta name="citation_title" content="{html_mod.escape(title)}">
<meta name="citation_author" content="Syrabit.ai">
<meta name="citation_publisher" content="Syrabit.ai">
<script type="application/ld+json">{schema}</script>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:800px;margin:0 auto;padding:1rem;color:#1a1a1a;line-height:1.6}}
a{{color:#7c3aed;text-decoration:none}}a:hover{{text-decoration:underline}}
h1{{font-size:1.8rem;margin-bottom:.5rem}}h2{{font-size:1.3rem;margin-top:2rem;border-bottom:1px solid #e5e7eb;padding-bottom:.3rem}}
h3{{font-size:1.1rem;margin-top:1.5rem;color:#374151}}
ul{{list-style:none;padding:0}}li{{margin:.8rem 0;padding:.5rem;border:1px solid #e5e7eb;border-radius:6px}}
ol{{padding-left:1.5rem}}ol li{{border:none;padding:.3rem 0;margin:.3rem 0}}
.lo-list li{{border:none;padding:.2rem 0;margin:.2rem 0;list-style:disc inside}}
small{{color:#6b7280}}nav[aria-label="Breadcrumb"]{{font-size:.9rem;color:#6b7280;margin-bottom:1rem}}
nav[aria-label="Breadcrumb"] a{{color:#7c3aed}}
.stats-row{{display:flex;gap:1.5rem;margin:1rem 0;flex-wrap:wrap}}.stat-badge{{background:#f3f4f6;padding:.4rem .8rem;border-radius:6px;font-size:.9rem}}
.content-info{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:1rem 1.25rem;margin:2rem 0}}
.content-info h2{{margin-top:0;font-size:1rem;color:#334155}}.content-info dt{{font-weight:600;color:#475569;margin-top:.5rem;font-size:.9rem}}.content-info dd{{margin:0 0 .25rem 0;color:#64748b;font-size:.85rem}}
footer{{margin-top:3rem;border-top:1px solid #e5e7eb;padding-top:1rem;font-size:.85rem;color:#9ca3af}}
.geo-footer{{font-size:.8rem;color:#9ca3af;margin-top:.5rem}}
@media(max-width:640px){{body{{padding:.75rem}}h1{{font-size:1.4rem}}h2{{font-size:1.1rem}}li{{padding:.4rem}}.stats-row{{flex-direction:column;gap:.5rem}}}}
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
<div class="stats-row">
<span class="stat-badge">{len(chapters_docs) or len(by_chapter)} Chapters</span>
<span class="stat-badge">{len(pages)} Topics</span>
<span class="stat-badge">{total_notes} Notes</span>
{"<span class='stat-badge'>" + str(total_mcqs) + " MCQ Sets</span>" if total_mcqs else ""}
{"<span class='stat-badge'>" + str(total_pyqs) + " PYQ Sets</span>" if total_pyqs else ""}
</div>
</header>
<main>
{overview_html}
{lo_html}
{topics_html}
<section class="content-info">
<h2>About This Study Guide</h2>
<dl>
<dt>Syllabus Source</dt><dd>{html_mod.escape(syllabus_source)}</dd>
<dt>Board</dt><dd>{html_mod.escape(board_label)} — {html_mod.escape(class_label)}</dd>
<dt>Editorial Process</dt><dd>Content is prepared by subject-matter contributors, cross-referenced with the official {html_mod.escape(board_label)} syllabus, and editorially reviewed for factual accuracy, exam relevance, and completeness.</dd>
<dt>Publisher</dt><dd>Syrabit.ai — Academic content platform for Assam students</dd>
</dl>
</section>
</main>
<footer>
<p>Source: <a href="{html_mod.escape(page_url)}">Syrabit.ai — {html_mod.escape(subject_name)}</a></p>
<p>&copy; Syrabit.ai — Syllabus-aligned study material for {html_mod.escape(board_label)} ({html_mod.escape(class_label)}) students</p>
<p>Content follows the official {html_mod.escape(board_label)} curriculum. For the latest syllabus, refer to your board/university website.</p>
<p class="geo-footer">Serving students across Assam, India — Guwahati, Jorhat, Dibrugarh, Dhemaji, Tezpur, Silchar, Nagaon, Barpeta, and more.</p>
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
    from starlette.responses import JSONResponse
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
    resp = JSONResponse(pages)
    resp.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400"
    return resp


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

    from starlette.responses import JSONResponse
    result = {
        "related": same_chapter + adjacent_topics,
        "prev": prev_topic,
        "next": next_topic,
    }
    resp = JSONResponse(result)
    resp.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400"
    return resp


@router.get("/page-bundle/{board}/{class_slug}/{subject_slug}/{topic_slug}")
async def get_seo_page_bundle(board: str, class_slug: str, subject_slug: str, topic_slug: str, pt: str = "notes"):
    from starlette.responses import JSONResponse
    page_type = pt if pt in ALL_PAGE_TYPES else "notes"
    page_q = _db.seo_pages.find_one(
        {"board_slug": board, "class_slug": class_slug, "subject_slug": subject_slug,
         "topic_slug": topic_slug, "page_type": page_type, "status": "published"},
        {"_id": 0},
    )
    types_q = _db.seo_pages.find(
        {"board_slug": board, "class_slug": class_slug, "subject_slug": subject_slug,
         "topic_slug": topic_slug, "status": "published"},
        {"_id": 0, "page_type": 1, "title": 1, "word_count": 1, "id": 1},
    ).to_list(10)
    import asyncio
    page_raw, types_raw = await asyncio.gather(page_q, types_q)
    if not page_raw:
        raise HTTPException(status_code=404, detail="Page not found")
    page = await _inject_qa(page_raw)
    iq_content = None
    if page_type == "notes" and any(t.get("page_type") == "important-questions" for t in types_raw):
        iq_page = await _db.seo_pages.find_one(
            {"board_slug": board, "class_slug": class_slug, "subject_slug": subject_slug,
             "topic_slug": topic_slug, "page_type": "important-questions", "status": "published"},
            {"_id": 0, "content": 1},
        )
        if iq_page:
            iq_content = iq_page.get("content")
    resp = JSONResponse({"page": page, "pageTypes": types_raw, "iqContent": iq_content})
    resp.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400"
    return resp


@router.get("/page/{board}/{class_slug}/{subject_slug}/{topic_slug}")
async def get_seo_page_default(board: str, class_slug: str, subject_slug: str, topic_slug: str):
    from starlette.responses import JSONResponse
    page = await _db.seo_pages.find_one(
        {"board_slug": board, "class_slug": class_slug, "subject_slug": subject_slug,
         "topic_slug": topic_slug, "page_type": "notes", "status": "published"},
        {"_id": 0},
    )
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    result = await _inject_qa(page)
    resp = JSONResponse(result)
    resp.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400"
    return resp


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
             "chapter_slug": 1, "topic_slug": 1, "page_type": 1, "updated_at": 1,
             "generated_at": 1, "created_at": 1},
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
        if not raw:
            raw = p.get("generated_at", "") or p.get("created_at", "")
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
    always_include = [
        "sitemap-pages.xml",
        "sitemap-subjects.xml",
        "sitemap-learn.xml",
        "sitemap-notes.xml",
    ]
    type_to_sitemap = {
        "mcqs": "sitemap-mcqs.xml",
        "important-questions": "sitemap-pyqs.xml",
        "examples": "sitemap-examples.xml",
        "definition": "sitemap-definitions.xml",
    }
    published_types = set()
    async for rec in _db.seo_pages.aggregate([
        {"$match": {"status": "published", "page_type": {"$in": list(type_to_sitemap.keys())}}},
        {"$group": {"_id": "$page_type"}},
    ]):
        published_types.add(rec["_id"])
    sitemap_names = list(always_include)
    for pt, sm_name in type_to_sitemap.items():
        if pt in published_types:
            sitemap_names.append(sm_name)
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
    seen_keys = set()
    entries = []
    for s in subjects:
        key = (s['_id']['board'], s['_id']['cls'], s['_id']['subj'])
        if key not in seen_keys:
            seen_keys.add(key)
            entries.append({
                "loc": f"{BASE_URL}/{key[0]}/{key[1]}/{key[2]}",
                "lastmod": today, "pri": "0.7", "freq": "weekly",
            })
    lib_subjects = await _db.subjects.find({}, {"_id": 0}).to_list(500)
    lib_streams = {s["id"]: s for s in await _db.streams.find({}, {"_id": 0}).to_list(500)}
    lib_classes = {c["id"]: c for c in await _db.classes.find({}, {"_id": 0}).to_list(500)}
    lib_boards = {b["id"]: b for b in await _db.boards.find({}, {"_id": 0}).to_list(500)}
    for sub in lib_subjects:
        stream = lib_streams.get(sub.get("stream_id", ""))
        cls = lib_classes.get(stream.get("class_id", "")) if stream else None
        board = lib_boards.get(cls.get("board_id", "")) if cls else None
        if board and cls and sub.get("slug"):
            key = (board.get("slug", ""), cls.get("slug", ""), sub["slug"])
            if key not in seen_keys:
                seen_keys.add(key)
                entries.append({
                    "loc": f"{BASE_URL}/{key[0]}/{key[1]}/{key[2]}",
                    "lastmod": today, "pri": "0.7", "freq": "weekly",
                })
    return _xml_response(_build_urlset(entries))


async def _fetch_learn_entries(today: str) -> list[dict]:
    try:
        docs = await _db.cms_documents.find(
            {"status": "published", "doc_type": {"$ne": "personalized"}},
            {"_id": 0, "seo_slug": 1, "id": 1, "updated_at": 1, "created_at": 1},
        ).to_list(5000)
        entries = []
        for doc in docs:
            slug = doc.get("seo_slug") or doc.get("id", "")
            if not slug:
                continue
            raw = doc.get("updated_at", "") or doc.get("created_at", "")
            lastmod = raw[:10] if raw else today
            entries.append({
                "loc": f"{BASE_URL}/learn/{slug}",
                "lastmod": lastmod,
                "pri": "0.8",
                "freq": "monthly",
            })
        return entries
    except Exception:
        return []


@router.get("/sitemap-learn.xml", response_class=Response)
async def get_sitemap_learn():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = await _fetch_learn_entries(today)
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
    learn_entries = await _fetch_learn_entries(today)
    entries.extend(learn_entries)
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
    min_score: int = _QUALITY_PUBLISH_THRESHOLD,
    _admin: dict = Depends(_require_admin),
):
    """Publish draft SEO pages that meet the quality threshold."""
    query: dict = {
        "status": {"$ne": "published"},
        "$or": [
            {"quality.score": {"$gte": min_score}},
            {"quality_score.score": {"$gte": min_score}},
        ],
    }
    if page_type:
        query["page_type"] = page_type
    if subject_id:
        query["subject_id"] = subject_id

    result = await _db.seo_pages.update_many(
        query,
        {"$set": {"status": "published", "in_sitemap": True, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {
        "published": result.modified_count,
        "message": f"Published {result.modified_count} pages (score ≥ {min_score})",
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
