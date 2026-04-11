# Workspace — Syrabit.ai

## Overview

Syrabit.ai is an AI-powered educational platform for AHSEC Class 11/12 and Degree students in Assam, India. It offers comprehensive, localized learning resources across 55 subjects, utilizing AI-driven content generation, syllabus management, and SEO optimization. The platform aims to personalize education, improve content delivery through chapter-level RAG chunks, and make high-quality educational content accessible and engaging via a robust admin panel.

## User Preferences

I prefer iterative development with clear communication on major changes. I value detailed explanations for complex features and architectural decisions. Please ensure that the development process prioritizes modularity and maintainability.

## System Architecture

The project is structured as a pnpm workspace monorepo, comprising a React + Vite frontend and a FastAPI Python backend.

**Backend Architecture:**
- **Modular Design:** Utilizes an app factory, shared modules, and route modules for clear separation of concerns.
- **On-Demand Embeddings:** Chapter embeddings are automatically generated and cleaned up.
- **Observability:** Tracks LLM provider metrics, vector search similarity, and pipeline runs.
- **Content Feedback Loop:** Features auto-detection of thin chapters, an auto-heal endpoint with version history, and quality gates for content generation.
- **Content Pipeline Batching:** Notes, MCQs, and flashcard generation run in parallel using `asyncio.gather` with a pipeline semaphore for concurrent LLM calls.
- **Content Generation Prompt:** Generates detailed exam-ready study notes (2500-4000+ words) with specific formatting.
- **Admin Analytics:** Dashboard displays RAG telemetry, chat latency, user counts, and content heatmaps.
- **AI Integration:** Integrates with Vertex AI / Gemini for text embeddings, translation, vision analysis, content enhancement, quality scoring, and SEO meta generation.
- **SEO & Content Quality:** Implements prompt variants, title diversification, content-derived meta descriptions, and a quality scoring system.
- **PYQ HTML Replica:** Processes PYQ PDFs via Gemini Vision OCR to create SEO-optimized, RAG-indexed HTML replicas.
- **Syllabus Embedder:** Generates chapter and topic-level embeddings, enriched with context and keywords.
- **Web Search Pipeline (RAG removed):** Uses DuckDuckGo web search with 3-layer architecture: `site:syrabit.ai` priority (3 results), scoped text search (8 results), news search (4 results). Stage 1 topic metadata (subject/chapter classification) is preserved for scoping web queries. Document uploads still use `resolve_rag_context` for document-only grounding. Library search endpoint (`/v1/search`) backed by web search.
- **Subject Linking for Syllabus:** A semantic router resolves subjects for syllabus queries without a `subject_id`.
- **Multi-LLM Pipeline:** Single-LLM with Stage 1 metadata for topic classification. Concise responses: 50-100 words default, max 300 words.
- **Monetization:** Supports free, starter, and pro plans with credit-based usage, integrating Razorpay and Stripe.
- **Optional Authentication:** Chat, History, and Profile pages are accessible to anonymous users via a `syrabit_anon_id`. Conversations are persisted in Redis and PostgreSQL.
- **Security:** Uses ASGI-native `SecurityHeadersMiddleware` and prompt safety guardrails.
- **Privacy:** Tracks DPDP Act consent per-user.
- **Performance Optimizations:** Includes bounded content caching, efficient JWT decoding, thread pooling, MongoDB indexing, hierarchy caching, AsyncOpenAI client pooling, instant fast-path responses for casual greetings, and fully parallelized chat pre-processing (Phase 0: subject context, stage1, followup, history all run concurrently via `asyncio.gather`; search_scope fires in parallel but is non-blocking — used if ready, dropped if not). RAG fast-skip: when no subject_id/subject_name and Stage 1's subject doesn't exist in DB, skips entire RAG pipeline (~0.8s saving).
- **Chat Latency:** Concept queries: TTFT ~0.7s, total ~0.9-1.1s (web search skipped). PYQ/current queries: TTFT ~1.5s, total ~1.8s (web search fires). Stage 1 timeout: 0.8s (max_tokens=150). Search scope timeout: 0.35s. Web search budget: 1.2s (DDG timeout: 1.0s). Default model: `meta-llama/llama-4-scout-17b-16e-instruct` (Groq). Max tokens: free=512, starter=768, pro=1024.
- **Smart Web Search Gating:** Stage 1 classifies `needs_web_search` (true/false). Heuristic fallback (`_SIMPLE_Q_RE`, `_WEB_NEEDED_RE`) handles Stage 1 timeouts. Safety net: pyq/important_questions/syllabus/chapter_meta intents always fire web search.
- **Response Length:** Concise by default (30-60 words). Hard limit 200 words. Prompts enforce: "what is X?" → 2-3 sentences, "explain X" → 3-5 sentences, "define X" → 1-2 sentences. System prompt ~1500 chars (down from 2800+).
- **GEO (Generative Engine Optimization):** Syllabi include `geo_phrases` for AI answer injection, and SEO prompts generate FAQ blocks and specific citations.

**Frontend Architecture:**
- **UI/UX:** Built with React, Vite, React Router, and Tailwind CSS, featuring a mobile-first responsive design and a light-only theme using CSS variables.
- **Admin Panel:** A comprehensive interface for content editing, CMS, blog publishing, SEO management, QA review, and system intelligence.
- **Bot-Aware Pre-Rendering:** `BotRenderMiddleware` serves cached pre-rendered HTML to search engine bots.
- **Bot Crawlability:** The backend serves `robots.txt`, `sitemap.xml`, and `sitemap-index.xml`.
- **Performance Optimizations:** Includes emergent badge suppression, PWA icon optimization, lazy-loading CMS sections, React Query for caching, CSS grid for content display, prefetching key pages, SSE metadata consolidation, and memoization. Third-party scripts (AdSense, Emergent) are deferred via `requestIdleCallback`. Build pipeline includes post-build steps for gzip/brotli pre-compression, modulepreload hint injection, and SW precache manifest generation (`scripts/compress-assets.mjs`, `scripts/inject-modulepreload.mjs`, `scripts/generate-precache-manifest.mjs`).
- **PWA:** Fully optimized with a multi-cache service worker (v9) featuring: Navigation Preload (~100ms saving on repeat visits), 3-tier caching (STATIC for hashed assets, RUNTIME for navigation/fonts/images, API_CACHE for read-only content endpoints with 1hr TTL + stale-while-revalidate), JSON Content-Type validation to prevent caching HTML fallbacks, bounded cache sizes (200 runtime, 100 API entries with automatic trimming), offline fallback page, build-generated precache manifest, and background API data precaching (boards/subjects) triggered on SW activation. `warmApiCache()` prefetches key API data using `requestIdleCallback` during idle time.
- **SEO Chapter Pages:** Chapter pages serve as single SEO landing pages with clean URLs, SERP preview modals, and deduplicated heading IDs.
- **Analytics:** Multi-source analytics merging Cloudflare Analytics API, GA4, server-side tracking, and JS-tracked data, with an admin dashboard picking the highest-confidence metric.
- **SEO Coverage:** All pages include `PageMeta` for title, description, OG, Twitter, canonical, and geo targeting, using JSON-LD structured data and a programmatic SEO engine.
- **Content Display:** Library page features subject cards; lesson pages have a blog-style layout with reading progress and sticky TOC.
- **Onboarding:** Streamlined onboarding for DEGREE and AHSEC/SEBA students.
- **Chat Interface:** Uses a standardized 0.1 temperature for LLMs and increased RAG chunk size for academic concepts.
- **Multi-Language Responses:** When an Indic language (Hindi, Assamese, etc.) is selected, optimized Sarvam routing is applied: model preference chain (sarvam-30b → sarvam-m) picks the fastest available model, a dedicated Indic-first bilingual system prompt replaces the English prompt, think budget injection and SARVAM_THINK_BUFFER are skipped to reduce TTFT, and `response_lang` is passed through to `call_llm_api_stream` for automatic Sarvam optimization. RAG context is preserved in the Indic prompt. Latency is logged with `[INDIC-PERF]` tags (TTFT + total time). Cache keys are language-aware (`msg::lang=hi`). Instant casual fast-path is skipped for non-English languages. `SARVAM_API_KEY_3` is the priority key for translation/Sarvam services.

## External Dependencies

- **Databases:** PostgreSQL (users/auth) and MongoDB (content/RAG).
- **Authentication:** Supabase (mirror for PostgreSQL), JWT helpers, Google OAuth.
- **Caching:** Redis, in-memory caching.
- **LLM Providers:**
    - **Chat:** Groq, Cerebras, OpenRouter, Fireworks (SLM pool).
    - **Content Generation:** Cerebras (primary), Sarvam (fallback), Gemini 2.5-flash (last resort). Gemini Vision and gemini-embedding-001.
- **Cloudflare AI Gateway:** Routes LLM traffic, provides caching, analytics, and graceful degradation.
- **Voyage AI Rerank:** `rerank-2` model for re-scoring vector search results.
- **Payment Gateways:** Razorpay (INR), Stripe (USD).
- **Email Service:** Resend API.
- **UI/UX Frameworks:** React, Vite, React Router, Tailwind CSS.
- **ORM:** Drizzle ORM.
- **API Framework:** FastAPI.
- **Schema Validation:** Zod.
- **API Codegen:** Orval.
- **Build Tools:** esbuild, pnpm.
- **Containerization:** Docker.
- **Production Deployment:** Hybrid architecture with FastAPI backend on Replit, Cloudflare Worker edge proxy (`api.syrabit.ai`), and frontend on Cloudflare Pages (`syrabit.ai`).
- **Edge Caching Strategy:** Cloudflare Worker caches 20+ public/read-only GET routes (content, notes, MCQs, flashcards, CMS articles, sitemaps) with long-lived TTLs (1 week / 604800s for content, shorter for SEO/user-stats). Content routes are cached even when `Authorization`/`Cookie`/`x-anon-id` headers are present (only user-specific routes like `/api/user/stats` bypass cache with auth). Dynamic routes (`/api/ai/chat/*`, `/api/webhooks/*`, `/api/auth/*`) and all non-GET methods bypass cache and proxy directly to the Replit backend. SSE streaming for AI chat passes through untouched.
- **Cloudflare Edge Cache Auto-Purge:** When admin edits/deletes content via `_invalidate_content_cache()`, a fire-and-forget async task purges the corresponding Cloudflare edge cache URLs via the Cloudflare Cache Purge API (`CF_API_TOKEN` + `CF_ZONE_ID`). A "Purge All Content Cache" button in Admin Settings clears both backend and Cloudflare edge caches. Purge utility is in `cloudflare_client.py`.
- **Cloudflare D1 Edge Database:** Read-heavy content catalog data (boards, classes, streams, subjects, chapters, topics, SEO pages) is replicated to a Cloudflare D1 (SQLite) database at the edge. The edge proxy queries D1 first for content and SEO routes; if D1 has data, it responds directly without hitting the backend. D1-backed routes include all content catalog endpoints, SEO page routes (`/api/seo/page/{board}/{class}/{subject}/{topic}[/{page_type}]`, `/api/seo/page-bundle/*`, `/api/seo/page-types/*`), sitemap XML endpoints (`sitemap-index.xml`, `sitemap-pages.xml`, `sitemap-subjects.xml`, `sitemap-chapters.xml`, `sitemap-notes.xml`, `sitemap-mcqs.xml`, `sitemap-pyqs.xml`, `sitemap-examples.xml`, `sitemap-definitions.xml`, `sitemap.xml`), and sitemap-entries JSON. Fallback: if D1 is not synced, returns null/errors, or a table is completely empty (via `isTablePopulated()` guard), the worker falls through to the existing CF cache → backend proxy chain. SEO pages store hierarchical slug fields (`board_slug`, `class_slug`, `subject_slug`, `chapter_slug`, `topic_slug`) for direct edge lookup. Sync mechanism: a scheduled cron worker (every 6 hours) pulls `/api/admin/d1-export` and upserts into D1, plus admin content mutations fire `_schedule_d1_sync_fire()` for real-time sync. Manual sync via `POST /api/admin/d1-sync`. D1 status: `GET /api/edge/d1-status`. Observability: `X-Source` header (`d1`, `cf-cache`, `backend`, `edge`). Schema: `workers/edge-proxy/migrations/`. D1 queries: `workers/edge-proxy/src/d1-queries.ts`. Sync logic: `workers/edge-proxy/src/d1-sync.ts` (edge) and `artifacts/syrabit-backend/d1_sync.py` (backend). Environment variables: `D1_SYNC_SECRET`, `EDGE_WORKER_URL`.