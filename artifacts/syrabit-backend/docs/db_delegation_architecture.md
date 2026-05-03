# Syrabit.ai — Database & AI Provider Delegation Architecture

> Last updated: 2026-04-30
> Scope: Python backend (`artifacts/syrabit-backend/`)

---

## Overview

Syrabit.ai uses five distinct storage/compute layers. Each layer has a well-defined
responsibility and clear fallback strategy. **No single layer is authoritative for
everything** — they work together via delegation patterns in the application code.

```
User Request
     │
     ▼
[Upstash Redis]  ──  L1: response cache (full AI replies, translations, rate limits)
     │ miss
     ▼
[Pinecone Inference API]  ── semantic embed + multilingual rerank
     │
     ▼
[MongoDB Atlas]  ──  content store: chapters, QA pairs, keyword search, vector chunks
     │
     ▼
[Supabase / PostgreSQL]  ──  users, auth sessions, conversations, subscriptions
     │
[Cloudflare KV / D1]  ──  edge cache: feature flags, study-session sync
```

---

## Layer 1: Upstash Redis (L1 Cache + Rate Limits)

**Purpose:** Fastest possible reads — sub-5ms. In-memory key-value at the edge.

| Key Namespace | Content | TTL |
|---|---|---|
| `ai_cache:<hash>` | Full AI chat responses (identical prompts) | 2h |
| `tr:<md5>` | Assamese/Bengali/Hindi translation results | 30m |
| `rl:<user_id>` | Per-user request counters (rate limiting) | 1m rolling |
| `session:<id>` | Active websocket session metadata | 24h |
| `grounded:<lang>:<hash>` | Grounded-recall language-specific results | 6h |

**Code:** `deps.py` → `redis_client` (Upstash REST via `upstash_redis`).
**Hot path:** checked first in every `/api/chat` handler before any LLM call.

### Translation Cache (NEW — 2026-04-30)
`routes/ai_chat.py::_assamese_translate_gemini_main_sarvam_polish` now caches
every successful Gemini+Sarvam translation result:
- Key: `tr:<MD5(lang:src_text[:1000])>`
- Hit: returns immediately, skips 1-2s Gemini + 0.5-1.8s Sarvam round-trip
- Miss: translates, stores, returns

---

## Layer 2: Pinecone Inference API (Semantic + Reranking)

**Purpose:** Multilingual semantic understanding. Handles Assamese, Bengali, Hindi,
English natively without translating queries first.

**Provider:** `providers/pinecone_ai.py`

### Embedding
- Model: `multilingual-e5-large` (1024-dim — matches Atlas `vector_index`)
- Input types: `"query"` (search queries) / `"passage"` (document ingestion)
- Used for: semantic search over `chunks` collection in MongoDB Atlas

### Reranking
- Model: `bge-reranker-v2-m3` (multilingual — tested with Assamese queries)
- Warm latency: ~400ms for 5-20 documents
- Used in: `rag.py::_fetch_internal_chapters` — reranks keyword-matched candidates
- Fallback: keyword order if Pinecone call fails or times out (8s budget)

### RAG Integration Pattern (rag.py)
```
1. Keyword extraction (regex + NLP)            ~0ms
2. MongoDB keyword match (find + $or)          ~50ms (wider: limit×5 candidates)
3. Pinecone bge-reranker-v2-m3 rerank         ~400ms (warm) / ~2s (cold first call)
4. Return top-K by relevance score             ~0ms
```

**Fallback chain if Pinecone unavailable:** keyword order → limit to original `limit`.

---

## Layer 3: MongoDB Atlas (Primary Content Store)

**Purpose:** All educational content: chapters, QA pairs, subjects, syllabus,
vector chunks. The source of truth for RAG retrieval.

**Collections:**

| Collection | Contents | Indexes |
|---|---|---|
| `chapters` | Full chapter text (title, content, slug, subject_id) | `status`, `subject_id`, text regex |
| `chunks` | Split passage vectors (1024-dim) for Atlas Vector Search | `vector_index` (cosine, 1024-dim) |
| `qa_pairs` | Pre-generated Q&A for AHSEC topics | `subject_id`, `chapter_id` |
| `subjects` | Subject metadata (name, board, class) | `slug`, `board` |
| `syllabi` | Official AHSEC/SEBA syllabus structure | `board`, `class` |
| `sessions` | Chat session logs (messages, timestamps) | `user_id`, `created_at` |

**Key finding (2026-04):** AHSEC `sub1`, `sub2` chapters are empty stubs —
no ingested content. All usable chapter content lives in UUID-keyed CMS documents.
Do NOT filter RAG by `subject_name` until chapter content is ingested.

**Atlas Vector Search index:** `vector_index` on `chunks.embedding`
- Dimensions: 1024
- Similarity: cosine
- Compatible with: `multilingual-e5-large` (Pinecone) + `bge-large-en-v1.5` (CF Workers AI)

---

## Layer 4: Supabase / PostgreSQL (Relational / Auth)

**Purpose:** User accounts, auth sessions, subscriptions, structured conversation
history (for export, search, history UI).

**Tables:**

| Table | Contents |
|---|---|
| `users` | Account data, plan, created_at |
| `auth_sessions` | JWT sessions, refresh tokens |
| `conversations` | Chat conversation records (user_id, created_at, title) |
| `messages` | Conversation messages (role, content, conversation_id) |
| `subscriptions` | Razorpay subscription status, plan tier |

**Code:** `deps.py` → `pg_pool` (asyncpg connection pool).
**Auth:** JWT signed with `JWT_SECRET` / `ADMIN_JWT_SECRET`, verified in `auth.py`.

---

## Layer 5: Cloudflare KV + D1 (Edge Cache / Flags)

**Purpose:** Edge-resident data for ultra-low-latency reads at CF PoPs,
and feature flags without round-tripping to the origin.

| Store | Contents | TTL / Retention |
|---|---|---|
| KV: `SYRABIT_FLAGS` | Feature flags (`rerank_enabled`, `asm_pipeline_v2`) | 5m cache |
| KV: `SYRABIT_SESSIONS` | Study session cross-device sync (last position) | 7 days |
| D1: `syrabit_edge` | Lightweight user preferences served from edge | permanent |

**Code:** CF Workers (`workers/` directory) call KV/D1 directly.
Python backend syncs via `cloudflare_ai.py` on significant state changes.

---

## AI Provider Delegation Matrix

| Task | Primary | Fallback | Notes |
|---|---|---|---|
| LLM chat (English) | Gemini 2.0 Flash (Google AI Studio) | Gemini via Vertex | Via CF AI Gateway |
| LLM chat (Assamese) | Sarvam-m | Gemini 2.0 Flash | Sarvam for Indic fluency |
| Translation (→ Assamese) | Gemini translate | — | Polish via Sarvam-m |
| Embedding (semantic search) | Pinecone `multilingual-e5-large` | CF Workers AI `bge-large-en-v1.5` | Both 1024-dim |
| Reranking (RAG) | Pinecone `bge-reranker-v2-m3` | Keyword order | Multilingual, ~400ms warm |
| Image/OCR | Gemini Vision | — | Question paper parsing |

---

## Request Latency Budget

Target: **p50 < 500ms** to first token (streaming), **p99 < 2s**.

| Phase | Budget | Implementation |
|---|---|---|
| Redis L1 hit | < 10ms | Full response served, no LLM |
| Translation cache hit | < 10ms | Skip Gemini+Sarvam |
| Redis miss → RAG fetch | 100-600ms | MongoDB keyword + Pinecone rerank |
| RAG miss → LLM | 400-1200ms | Streaming, first token |
| Translation (cold) | 1500-3000ms | Gemini ~1s + Sarvam ~1.5s |
| Translation (warm) | < 10ms | Redis cache hit |

---

## Ingestion Pipeline (Admin)

**Endpoint:** `POST /admin/vector/batch-embed`

```
Chapter text (MongoDB)
  → Split into 512-token passages
  → Embed via Pinecone multilingual-e5-large (passage mode)
  → Store in MongoDB chunks collection (with embedding vector)
  → Atlas Vector Search index auto-updates
```

**Priority:** Ingest AHSEC subject chapters (sub1–sub18) to unlock
subject-filtered RAG retrieval. Currently all content is UUID-keyed CMS docs.

---

## Fallback Strategies

### If Pinecone is down
- `providers/pinecone_ai.py::ENABLED = False` (no API key or import error)
- `_fetch_internal_chapters` falls back to keyword-order results (no reranking)
- Embedding falls back to CF Workers AI `bge-large-en-v1.5`

### If Upstash Redis is down
- `deps.py::redis_client = None`
- All Redis reads return `None` (cache miss path)
- Rate limiting falls back to in-process `cachetools.TTLCache`

### If MongoDB is down
- `rag.py::is_mongo_available()` → `False`
- `_fetch_internal_chapters` returns `[]`
- Chat continues without internal RAG context

### If Sarvam is down
- Translation falls back to Gemini-only output (un-polished but correct)
- Assamese chat falls back to English response with note to user
