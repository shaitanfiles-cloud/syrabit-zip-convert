# Workspace — Syrabit.ai

## Overview

Syrabit.ai is an AI-powered educational platform for AHSEC Class 11/12 and Degree students in Assam, India. It offers comprehensive learning resources across two boards and 55 subjects with chapter-level RAG chunks. The platform leverages AI for content generation, syllabus management, SEO optimization, and provides a robust admin panel. Its purpose is to personalize learning and enhance content delivery, making high-quality, localized educational content accessible.

## User Preferences

I prefer iterative development with clear communication on major changes. I value detailed explanations for complex features and architectural decisions. Please ensure that the development process prioritizes modularity and maintainability.

## System Architecture

The project is a pnpm workspace monorepo consisting of a React + Vite frontend and a FastAPI Python backend.

**Backend Architecture:**
- **Modular Design:** The backend uses an app factory, shared modules, and route modules for clear separation of concerns.
- **On-Demand Embeddings:** Chapter embeddings are generated automatically on chapter create/update via `_embed_chapter_bg()` background task. The chapter `topics` field serves as embedding content. Embedding cleanup happens on chapter/subject delete.
- **Observability Layer:** Tracks LLM provider metrics, vector search similarity, and pipeline runs, consolidated in an Admin Intelligence endpoint.
- **Content Feedback Loop:** Includes auto-detection of thin chapters, an auto-heal endpoint with version history, and quality gates for content generation.
- **Content Pipeline Batching:** Notes, MCQs, and flashcards generation runs in parallel via `asyncio.gather` with a pipeline semaphore (default 4 concurrent LLM calls). Endpoints: `POST /admin/content/chapters/{id}/generate-all` (single chapter, all assets in parallel), `POST /admin/content/subject/{id}/generate-all` (all chapters in a subject), `POST /admin/content/regenerate-thin` (parallel thin chapter regeneration).
- **Vertex AI / Gemini Integration:** Nine AI services are integrated for tasks like text embeddings, translation, vision analysis, content enhancement, quality scoring, and SEO meta generation.
- **SEO & Content Quality:** Implements prompt variants for content generation, title diversification, content-derived meta descriptions, and a quality scoring system to prevent thin content.
- **PYQ HTML Replica:** Processes PYQ PDFs using Gemini Vision OCR to create SEO-optimized HTML replicas, stored in MongoDB and RAG-indexed.
- **Syllabus Embedder:** Generates chapter and topic-level embeddings, enriched with context, for precise matching and classification.
- **RAG Pipeline:** Features a 4-way parallel search (keyword chunks, chapter keywords, subject keywords, vector cosine similarity) with grounding citations. It runs RAG search, web search, and conversation history fetch in parallel, with graceful degradation. Performance optimizations include caching, parallelized lookups, reduced vector search candidates, shared query embedding cache (eliminates duplicate embed calls between syllabus classify and vector search), high-confidence fast-path (skips keyword search when vector similarity >= 0.70), intent-aware context filtering (boosts/skips sections by intent type), and a grounding budget system (6000 char limit, 8000 for syllabus) that prioritizes content cards over vector hits over chunks.
- **Monetization:** Supports free, starter, and pro plans with daily-resetting credit-based usage. Integrates Razorpay (INR) and Stripe (USD) for payments.
- **Optional Authentication:** Chat, History, and Profile pages are accessible without login. Anonymous users get a `syrabit_anon_id` (128-bit random, stored in localStorage) for conversation persistence in Upstash Redis (7-day TTL, max 20 conversations). Conversations are sent via `x-anon-id` header. IP-based rate limiting applies to anon users.
- **Security:** Uses ASGI-native `SecurityHeadersMiddleware` with env-toggleable headers (`SEC_HSTS`, `SEC_XCTO`, `SEC_XFRAME`, `SEC_REFERRER`, `SEC_PERM`, `SEC_CSP_REPORT_ONLY`). CSP report-only mode available. Includes prompt safety guardrails module (`guardrails/prompt_safety.py`) for injection/cheating/sensitive content blocking.
- **Privacy:** DPDP Act consent tracked per-user (version + timestamp). `/api/privacy/consent` GET/POST for viewing/withdrawing consent. Consent checkbox on signup.
- **Performance Optimizations:** Implements bounded content caching, efficient JWT decoding, thread pooling (32 workers) for Supabase calls, MongoDB indexing, hierarchy cache (stream→class→board, 30min TTL), and AsyncOpenAI client pooling (SHA-256-keyed cache avoids per-request instantiation).
- **GEO (Generative Engine Optimization):** Syllabi include `geo_phrases` for AI answer injection, and SEO prompts generate FAQ blocks and specific citations.

**Frontend Architecture:**
- **UI/UX:** React + Vite, React Router, and Tailwind CSS, with a mobile-first responsive design.
- **Admin Panel:** A comprehensive interface with Content Editor (default tab), CMS/Docs, Blog Publisher, SEO Manager, QA Review, and an Intelligence panel displaying system health and metrics. Content Editor includes a Topics input for AI embeddings. Content panel supports: inline subject edit/rename, bulk AI notes generation for all chapters without content, cascade deletes (board→class→stream→subject→chapters+assets), and chapter asset cards (PYQs, flashcards, blogs, SEO topics, coverage scores).
- **Component Refactoring:** Large files are split into sub-components for maintainability.
- **Bot-Aware Pre-Rendering:** `BotRenderMiddleware` serves cached pre-rendered HTML for search engine bots on key pages.
- **Bot Crawlability:** Backend serves `/robots.txt` (with rules for 16+ bot user-agents), `/sitemap.xml` (301→`/api/seo/sitemap.xml`), and `/sitemap-index.xml` (301→`/api/seo/sitemap-index.xml`) directly. `Allow: /api/seo/` ensures sitemap sub-files are crawlable despite `Disallow: /api/`. Vite `public/robots.txt` mirrors the backend version for consistency.
- **Performance Optimizations:** Includes emergent badge suppression, PWA icon optimization, lazy-loading CMS sections, React Query for caching, CSS grid for content display, prefetching for navigation, admin panel lazy-loaded sub-components (20 sections via React.lazy), CSS containment on chat bubbles, and `MarkdownContent`/`BottomNav` memoized with `memo()`.
- **SEO Chapter Pages:** Chapter pages (`ChapterPage.jsx`) serve as the single SEO landing pages at `/{board}/{class}/{subject}/{chapter}`. Old 5-segment topic URLs redirect to the parent chapter. Share button includes SERP preview modal. Sitemap includes `sitemap-chapters.xml` for all chapter URLs.
- **Content Display:** Library page features subject cards with chapter links to chapter pages. Lesson pages have a blog-style layout with reading progress and sticky TOC.
- **Onboarding:** Streamlined onboarding for DEGREE and AHSEC/SEBA students.
- **Profile Course Type Selector:** DEGREE students can select course types and subjects via an expandable selector.
- **Chat Interface:** Uses a standardized 0.1 temperature for LLMs and increased RAG chunk size for academic concepts.

**Monorepo Structure:**
- `artifacts/`: Deployable applications.
- `lib/`: Shared libraries (API spec, React Query hooks, Zod schemas, Drizzle ORM schema).
- `scripts/`: Utility scripts.

## External Dependencies

- **Databases:** PostgreSQL (for users/auth) and MongoDB (for content/RAG).
- **Authentication:** Supabase (mirror for PostgreSQL), JWT helpers, Google OAuth (Sign In with Google via GIS library, server-side ID token verification via `google-auth`).
- **Caching:** Redis (distributed cache) and in-memory caching.
- **LLM Providers (SLM pool):** Fireworks (deepseek-v3p2), Groq (llama-3.1-8b-instant, llama-3.3-70b-versatile), Cerebras (llama3.1-8b), Google Gemini (gemini-2.5-flash, Gemini Vision, gemini-embedding-001), Sarvam (sarvam-m), OpenRouter (deepseek-chat-v3-0324).
- **Cloudflare AI Gateway:** Routes LLM traffic, provides caching, analytics, and graceful degradation.
- **Voyage AI Rerank:** `rerank-2` model for re-scoring vector search results.
- **Payment Gateways:** Razorpay (INR) and Stripe (USD).
- **Email Service:** Resend API.
- **UI/UX Frameworks:** React, Vite, React Router, Tailwind CSS.
- **ORM:** Drizzle ORM.
- **API Framework:** FastAPI.
- **Schema Validation:** Zod.
- **API Codegen:** Orval.
- **Build Tools:** esbuild, pnpm.
- **Containerization:** Docker.

## Cloudflare Deployment Configuration

When deploying the frontend on Cloudflare Pages with the backend on Replit, set these environment variables on the backend:

- `COOKIE_DOMAIN` — e.g., `.syrabit.ai` (leading dot for subdomain sharing). Leave unset in dev.
- `PRODUCTION_ORIGINS` — e.g., `https://syrabit.ai,https://www.syrabit.ai`. Appended to CORS origins automatically.
- `VITE_BACKEND_URL` — Set on the frontend build to point to the Replit backend URL.
- `GOOGLE_CLIENT_ID` — Google OAuth Client ID (backend, required for Google sign-in).
- `GOOGLE_CLIENT_SECRET` — Google OAuth Client Secret (backend, optional — only needed if using authorization code flow).

All frontend files use a single centralized `API_BASE` from `utils/api.jsx`. No local API base definitions.

## Google OAuth

Google Sign-In is integrated on both Login and Signup pages. The frontend dynamically fetches the Google Client ID from `GET /api/auth/google/client-id`. If `GOOGLE_CLIENT_ID` is not set, the Google button is hidden. The backend endpoint `POST /api/auth/google` verifies the ID token server-side using `google.oauth2.id_token.verify_oauth2_token`, then finds or creates the user. Users who sign up via Google get `auth_provider: "google"` and `google_id` fields set on their user record. Existing email/password users who sign in with Google get their Google ID linked automatically. Google-only users (empty `password_hash`) can set a password via the "Forgot password" flow.
