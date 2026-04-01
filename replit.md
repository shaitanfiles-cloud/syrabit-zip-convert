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
- **AI-Powered Syllabus Uploader:** An agentic pipeline handles PDF uploads, extracts syllabus information using Gemini Vision, generates board-aware LLM notes via `call_llm_api()`, chunks content for RAG, embeds chapters, creates CMS blog drafts, and performs SEO/GEO tagging. This process streams SSE events to the frontend for real-time progress. Content generation uses quality gates (retry once if <600 words, flag needs_review). Tested with MDC Arts PDF — 6 subjects, 22 chapters, 780 chunks, 22 embeddings (100% coverage).
- **Observability Layer:** LLM provider metrics (`_record_llm_call`, `get_llm_provider_stats` in `llm.py`), vector search similarity tracking (`rag.py`), pipeline run tracking (`record_pipeline_run` in `rag.py`). Admin Intelligence endpoint at `/admin/intelligence/overview` consolidates all metrics.
- **Content Feedback Loop:** Auto-detection of thin chapters (<600 words), auto-heal endpoint at `/admin/content/auto-heal` with version history tracking in `content_version` field, version history endpoint at `/admin/content/version-history/{id}`.
- **Test Suite:** 121 pytest tests across 4 files in `artifacts/syrabit-backend/tests/` covering board normalization (35), chunking (16), prompts (29), and RAG pipeline (12), plus additional integration tests. Config in `pyproject.toml`.
- **Vertex AI / Gemini Integration:** Nine AI services are integrated via `vertex_services.py`, including text embeddings, translation, vision analysis, content enhancement, quality scoring, topic suggestion, SEO meta generation, content gap finding, and long document reading (Gemini 1.5 Pro).
- **SEO & Content Quality:** Implemented prompt variants for content generation, title diversification, and content-derived meta descriptions. A quality scoring system tracks word count, heading count, unique ratio, and feature presence (FAQ, PYQ, examples) to prevent thin content. Anti-thin-page gates enforce minimum word counts.
- **PYQ HTML Replica:** A backend endpoint processes PYQ PDFs, uses Gemini Vision OCR to build SEO-optimized HTML replicas, stores them in MongoDB, and serves them. These replicas are RAG-indexed with high priority.
- **RAG Pipeline:** A 4-way parallel search mechanism combines keyword chunks, chapter keywords, subject keywords, and vector cosine similarity. Grounding now includes `[PAGE: slug]` citation headers. Embeddings are generated on content publish.
- **Monetization:** Supports free, starter, and pro plans with credit-based usage. Integrates Razorpay (INR) and Stripe (USD) for payments, with webhook handlers for transaction verification.
- **Security:** Utilizes ASGI-native `SecurityHeadersMiddleware` for HSTS, CSP, and X-Frame-Options.
- **GEO (Generative Engine Optimization):** Syllabi include `geo_phrases` for AI answer injection. SEO prompts include specific citations (AHSEC exam year, NCERT/SCERT) and generate FAQ blocks.

**Frontend Architecture:**
- **UI/UX:** React + Vite, React Router, and Tailwind CSS. Employs a mobile-first responsive design using `100svh` and safe-area insets.
- **Admin Panel:** A comprehensive admin interface with 21 sections, including Dashboard, Syllabus, Content Editor, Content Studio, SEO Manager, QA Review, Automation, Users, Conversations, Analytics, Monetization, Health, and Intelligence. Intelligence panel (`AdminIntelligence.jsx`) shows LLM provider health, RAG metrics, pipeline run stats, and content health with auto-heal button. Frontend includes `SectionErrorBoundary` per admin section and axios retry interceptor (max 2 retries on 5xx/429/408 GET requests).
- **Component Refactoring:** Large frontend files are split into sub-components for better maintainability (e.g., `admin/`, `pages/`, `utils/`).
- **Bot-Aware Pre-Rendering:** `BotRenderMiddleware` detects search engine bots and serves pre-rendered HTML for key pages (homepage, library, subject landings, topic pages, PYQ pages) with a 1-hour TTL cache, ensuring full content, meta tags, and Schema.org are available to crawlers.
- **Content Display:** Library page features browser-window style subject cards with a "Your Syllabus" / "Explore Other Subjects" split view based on user's board. Subject Landing Pages list chapters with search and topic chips. Lesson Pages (`SeoTopicPage`) have a blog-style layout with reading progress, sticky TOC, and improved typography.
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
- **Caching:** Redis (distributed cache) and in-memory caching.
- **LLM Providers (fallback chain: Gemini → Groq → Emergent → Sarvam):**
    - Google Gemini (gemini-2.5-flash, Gemini Vision, gemini-embedding-001) - primary.
    - Groq x2 keys (llama-3.3-70b, llama-3.1-8b) — doubled rate limit via `GROQ_API_KEY` + `GROQ_API_KEY_2`.
    - Emergent universal gateway (fallback, `EMERGENT_API_KEY`).
    - Fireworks (deepseek-v3p2, currently suspended).
    - Sarvam (sarvam-m, last-resort fallback).
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