# Workspace — Syrabit.ai

## Overview

Syrabit.ai is an AI-powered educational platform designed for AHSEC Class 11/12 and Degree students in Assam, India. The platform aims to provide comprehensive learning resources across 2 boards (AHSEC, Degree) and 55 subjects with chapter-level RAG chunks. Key capabilities include AI-driven content generation, syllabus management, SEO optimization, and a robust admin panel for managing content, users, and analytics. The project's vision is to make high-quality, localized educational content accessible, leveraging AI to personalize learning experiences and enhance content delivery.

## User Preferences

I prefer iterative development with clear communication on major changes. I value detailed explanations for complex features and architectural decisions. Please ensure that the development process prioritizes modularity and maintainability.

## System Architecture

The project is a pnpm workspace monorepo comprising a React + Vite frontend (`artifacts/syrabit`) and a FastAPI Python backend (`artifacts/syrabit-backend`).

**Backend Architecture:**
- **Modular Design:** The backend is organized into an app factory (`server.py`), shared modules (e.g., `config.py`, `deps.py`, `cache.py`, `db_ops.py`, `llm.py`, `rag.py`), and route modules for clear separation of concerns.
- **Dependency Hierarchy:** `config` → `deps` → `cache` → `auth_deps` → `db_ops` → `llm/rag/utils` → `routes` → `server.py`.
- **AI-Powered Syllabus Uploader:** An agentic pipeline handles PDF uploads, extracts syllabus information using Gemini Vision, generates board-aware LLM notes via `call_llm_api()`, chunks content for RAG, embeds chapters, creates CMS blog drafts, and performs SEO/GEO tagging. This process streams SSE events to the frontend for real-time progress. Content generation uses quality gates (retry once if <600 words, flag needs_review). Tested with MDC Arts PDF + AEC English PDF — 10 subjects, 30 chapters, 1,028 chunks. Syllabus linker reconciles denormalized fields (boardName, className, streamName) on re-import.
- **Observability Layer:** LLM provider metrics (`_record_llm_call`, `get_llm_provider_stats` in `llm.py`), vector search similarity tracking (`rag.py`), pipeline run tracking (`record_pipeline_run` in `rag.py`). Admin Intelligence endpoint at `/admin/intelligence/overview` consolidates all metrics.
- **Content Feedback Loop:** Auto-detection of thin chapters (<600 words), auto-heal endpoint at `/admin/content/auto-heal` with version history tracking in `content_version` field, version history endpoint at `/admin/content/version-history/{id}`.
- **Test Suite:** 121 pytest tests across 4 files in `artifacts/syrabit-backend/tests/` covering board normalization (35), chunking (16), prompts (29), and RAG pipeline (12), plus additional integration tests. Config in `pyproject.toml`.
- **Vertex AI / Gemini Integration:** Nine AI services are integrated via `vertex_services.py`, including text embeddings, translation, vision analysis, content enhancement, quality scoring, topic suggestion, SEO meta generation, content gap finding, and long document reading (Gemini 1.5 Pro).
- **SEO & Content Quality:** Implemented prompt variants for content generation, title diversification, and content-derived meta descriptions. A quality scoring system tracks word count, heading count, unique ratio, and feature presence (FAQ, PYQ, examples) to prevent thin content. Anti-thin-page gates enforce minimum word counts.
- **PYQ HTML Replica:** A backend endpoint processes PYQ PDFs, uses Gemini Vision OCR to build SEO-optimized HTML replicas, stores them in MongoDB, and serves them. These replicas are RAG-indexed with high priority.
- **Syllabus Embedder:** Chapter + topic-level embeddings in `syllabus_embeddings` collection. Enriched embed text includes title + description + full topic list + content keywords (capped at 2000 chars). Topic-level embeddings give one vector per subtopic for precise matching. Similarity thresholds configurable via `SYLLABUS_CLASSIFY_THRESHOLD` (default 0.65) and `RAG_RELEVANCE_GATE` (default 0.50) env vars. Admin endpoints: `POST /admin/syllabus/full-reseed`, `GET /admin/syllabus/test-classify?q=...`, `GET /admin/syllabus/embedding-stats` (enriched with chapter/topic counts, thin text stats, avg lengths). Top-3 match scores logged for every classify() call.
- **RAG Pipeline:** A 4-way parallel search mechanism combines keyword chunks, chapter keywords, subject keywords, and vector cosine similarity. Grounding now includes `[PAGE: slug]` citation headers. Embeddings are generated on content publish. RAG search, web search (DuckDuckGo dual-layer: base + polish), and conversation history fetch all run in parallel via `asyncio.gather` for both streaming and non-streaming endpoints. Web search failures degrade gracefully (return empty list) without killing the request. RAG is always the primary grounding source; web results supplement/enrich regardless of RAG quality. Performance optimizations: subject context resolution cached to avoid duplicate MongoDB lookups (4 sequential find_one calls saved), syllabus lookups parallelized via asyncio.gather (up to 4 queries run concurrently instead of sequentially), build_search_scope runs concurrently with Phase 1 doc+syllabus fetch, vector search candidates reduced (50+30+20 vs 200+100+100) with content excluded from projection, chunks use $text search with regex fallback, Voyage rerank timeout reduced from 3s to 1.5s, DuckDuckGo timeout reduced from 5s to 2s, embedding results independently cached (TTL 600s), cms_documents text index added, conversation history PG+MongoDB fetched in parallel.
- **Monetization:** Supports free, starter, and pro plans with daily-resetting credit-based usage. Plan limits: Free (30 credits/day, 5 req/min, 10K max tokens, 20 IP req/min), Starter (500/day, 10 req/min, 15K tokens, 30 IP req/min), Pro (4,000/day, 15 req/min, 20K tokens, 40 IP req/min). Credits reset at midnight UTC via `credits_used_today` and `credits_reset_date` DB columns. Integrates Razorpay (INR) and Stripe (USD) for payments, with webhook handlers for transaction verification.
- **Optional Auth:** Chat, History, and Profile pages are accessible without login. Backend endpoints (`/auth/me`, `/user/profile`, `/user/credits`, `/user/stats`, `/conversations`) use `get_current_user_optional` — returning graceful defaults for anonymous users. Anonymous chat uses IP-based rate limiting (5 req/min, free plan). Conversations are not persisted for anonymous users; credits are not deducted server-side. Frontend shows "Sign in" prompts on History/Profile pages when not logged in. Sidebar shows "Sign In" instead of "Logout" for anonymous users.
- **Security:** Utilizes ASGI-native `SecurityHeadersMiddleware` for HSTS, CSP, and X-Frame-Options.
- **GEO (Generative Engine Optimization):** Syllabi include `geo_phrases` for AI answer injection. SEO prompts include specific citations (AHSEC exam year, NCERT/SCERT) and generate FAQ blocks.

**Frontend Architecture:**
- **UI/UX:** React + Vite, React Router, and Tailwind CSS. Employs a mobile-first responsive design using `100svh` and safe-area insets.
- **Admin Panel:** A comprehensive admin interface with 21 sections, including Dashboard, Syllabus, Content Editor, Content Studio, SEO Manager, QA Review, Automation, Users, Conversations, Analytics, Monetization, Health, and Intelligence. Intelligence panel (`AdminIntelligence.jsx`) shows LLM provider health, RAG metrics, pipeline run stats, and content health with auto-heal button. Frontend includes `SectionErrorBoundary` per admin section and axios retry interceptor (max 2 retries on 5xx/429/408 GET requests).
- **Component Refactoring:** Large frontend files are split into sub-components for better maintainability (e.g., `admin/`, `pages/`, `utils/`).
- **Bot-Aware Pre-Rendering:** `BotRenderMiddleware` detects search engine bots and serves pre-rendered HTML for key pages (homepage, library, subject landings, topic pages, PYQ pages) with a 1-hour TTL cache, ensuring full content, meta tags, and Schema.org are available to crawlers.
- **Performance Optimizations:** Library-bundle query prefetched on app mount — immediately for logged-in users, on first user interaction for guests, with 3s fallback timer. CMS sections (CmsDocsSection, CmsPostsGrid) lazy-loaded via intersection observer + React.lazy(). CMS data uses React Query for cross-navigation caching. MasonryInfiniteGrid replaced with CSS grid + "Load more" button. Nav items preload page chunks on hover/touch via `pageImports` utility and `prefetchRoute` utility (`src/utils/prefetchRoute.js`). Vite manualChunks splits lucide-react and @radix-ui into separate chunks. Subject thumbnail images use `<img loading="lazy">`. Inline critical CSS in index.html for instant first paint. Preconnect/dns-prefetch hints for backend API, PostHog, Emergent, and Google Fonts origins. Font preload for primary Space Grotesk weight. CDN edge caching on library-bundle endpoint (s-maxage=3600, stale-while-revalidate=86400, CDN-Cache-Control header).
- **Content Display:** Library page features browser-window style subject cards with a "Your Syllabus" / "Explore Other Subjects" split view based on user's board. Cards show SEO content type badges (Notes, MCQs, Definitions, Important Questions, Examples) with counts. Chapters are expandable to reveal SEO topics with page-type pill links. The library page includes comprehensive SEO meta tags, keywords, and Schema.org structured data (ItemList with LearningResource items, WebPage, BreadcrumbList). Subject Landing Pages list chapters with search and topic chips. Lesson Pages (`SeoTopicPage`) have a blog-style layout with reading progress, sticky TOC, and improved typography.
- **Onboarding:** DEGREE students: Board → Semester (2 steps). AHSEC/SEBA: Board → Class → Stream (3 steps). No course type step in onboarding — course type selection is available in Profile page.
- **Profile Course Type Selector:** DEGREE students see an expandable `CourseTypeSelector` in AcademicDetails showing course types (Major/Minor/SEC/VAC/MDC/AEC) with subjects grouped under each, selectable via checkboxes. Persisted via `course_type` and `selected_subjects` fields on user profile.
- **Chat Interface:** Chat responses use a standardized 0.1 temperature for all LLMs. RAG chunk size is increased to 1,200 characters to preserve academic concepts.

**Monorepo Structure:**
- `artifacts/`: Deployable applications (syrabit frontend, syrabit-backend, mockup-sandbox).
- `lib/`: Shared libraries (API spec, React Query hooks, Zod schemas, Drizzle ORM schema).
- `scripts/`: Utility scripts.
- `pnpm-workspace.yaml`, `tsconfig.base.json`, `tsconfig.json`, `package.json` for pnpm workspace management.

## External Dependencies

- **Database:** PostgreSQL (for users/auth) and MongoDB (for content/RAG).
- **Authentication:** Supabase (mirror for PostgreSQL), JWT helpers.
- **Caching:** Redis (distributed cache) and in-memory caching. User cache invalidation clears both in-memory TTL cache AND Redis session cache to prevent stale reads after profile/onboarding updates.
- **LLM Providers (SLM pool `openai/gpt-oss-20b`: Fireworks → Groq → Cerebras → Gemini → Sarvam):**
    - Fireworks (deepseek-v3p2) — primary SLM pool provider, 8 concurrent slots.
    - Groq x2 keys (llama-3.1-8b-instant 8 slots, llama-3.3-70b-versatile 4 slots) via `GROQ_API_KEY` + `GROQ_API_KEY_2`.
    - Cerebras (llama-3.3-70b, 6 slots) — also primary for admin content generation.
    - Google Gemini (gemini-2.5-flash 6 slots, Gemini Vision, gemini-embedding-001).
    - Sarvam (sarvam-m, 4 slots, reliable fallback).
    - OpenRouter (deepseek-chat-v3-0324 default) — access to 200+ models via single API key.
    - Model aliases: `openai/gpt-oss-20b` → SLM pool, `openai/gpt-oss-120b` → Cerebras qwen-3-235b (coming soon).
- **Cloudflare AI Gateway (free tier):** Routes OpenAI, Groq, Gemini, xAI, Fireworks, and Sarvam through `CF_AI_GATEWAY_ACCOUNT_ID`/`CF_AI_GATEWAY_ID`. Provides response caching (`cf-aig-cache-ttl`, default 3600s for non-streaming), unified analytics, and request logging. Gateway health auto-tracked: marks down on connection errors, auto-recovers after 5 min. In-request graceful degradation: on gateway connection failure, retries same request with direct provider URL. Bedrock stays direct (boto3, not OpenAI-compatible). Fireworks and Sarvam require custom provider setup in CF dashboard. Emergent gateway removed (replaced by CF AI Gateway).
- **Voyage AI Rerank:** `rerank-2` model re-scores vector search results for higher relevance. 3s timeout with cosine fallback. `VOYAGE_API_KEY`.
- **Payment Gateways:** Razorpay (INR) and Stripe (USD).
- **Email Service:** Resend API (for password resets).
- **UI/UX Frameworks:** React, Vite, React Router, Tailwind CSS.
- **ORM:** Drizzle ORM (for PostgreSQL).
- **API Framework:** FastAPI (Python backend), Express 5 (Node.js for some utilities).
- **Schema Validation:** Zod.
- **API Codegen:** Orval (from OpenAPI spec).
- **Build Tools:** esbuild, pnpm.
- **Containerization:** Docker.

## Cloudflare Deployment Configuration

When deploying the frontend on Cloudflare Pages with the backend on Replit, set these environment variables on the backend:

- `COOKIE_DOMAIN` — e.g., `.syrabit.ai` (leading dot for subdomain sharing). Leave unset in dev.
- `PRODUCTION_ORIGINS` — e.g., `https://syrabit.ai,https://www.syrabit.ai`. Appended to CORS origins automatically.
- `VITE_BACKEND_URL` — Set on the frontend build to point to the Replit backend URL.

All frontend files use a single centralized `API_BASE` from `utils/api.jsx`. No local API base definitions.