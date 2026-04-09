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
- **RAG Pipeline:** Employs a 4-way parallel search (keyword chunks, chapter keywords, subject keywords, chunk-level vector search) with grounding citations, using MongoDB Atlas `$vectorSearch` with app-side cosine similarity fallback and Voyage AI reranker.
- **Subject Linking for Syllabus:** A semantic router resolves subjects for syllabus queries without a `subject_id`.
- **Multi-LLM Pipeline:** Designed with a multi-stage architecture (Topic Resolver, RAG Synthesizer, Response Polisher) using various LLMs.
- **Monetization:** Supports free, starter, and pro plans with credit-based usage, integrating Razorpay and Stripe.
- **Optional Authentication:** Chat, History, and Profile pages are accessible to anonymous users via a `syrabit_anon_id`. Conversations are persisted in Redis and PostgreSQL.
- **Security:** Uses ASGI-native `SecurityHeadersMiddleware` and prompt safety guardrails.
- **Privacy:** Tracks DPDP Act consent per-user.
- **Performance Optimizations:** Includes bounded content caching, efficient JWT decoding, thread pooling, MongoDB indexing, hierarchy caching, AsyncOpenAI client pooling, and instant fast-path responses for casual greetings.
- **GEO (Generative Engine Optimization):** Syllabi include `geo_phrases` for AI answer injection, and SEO prompts generate FAQ blocks and specific citations.

**Frontend Architecture:**
- **UI/UX:** Built with React, Vite, React Router, and Tailwind CSS, featuring a mobile-first responsive design and a light-only theme using CSS variables.
- **Admin Panel:** A comprehensive interface for content editing, CMS, blog publishing, SEO management, QA review, and system intelligence.
- **Bot-Aware Pre-Rendering:** `BotRenderMiddleware` serves cached pre-rendered HTML to search engine bots.
- **Bot Crawlability:** The backend serves `robots.txt`, `sitemap.xml`, and `sitemap-index.xml`.
- **Performance Optimizations:** Includes emergent badge suppression, PWA icon optimization, lazy-loading CMS sections, React Query for caching, CSS grid for content display, prefetching key pages, SSE metadata consolidation, and memoization. Third-party scripts (AdSense, Emergent) are deferred via `requestIdleCallback`. Build pipeline includes post-build steps for gzip/brotli pre-compression, modulepreload hint injection, and SW precache manifest generation (`scripts/compress-assets.mjs`, `scripts/inject-modulepreload.mjs`, `scripts/generate-precache-manifest.mjs`).
- **PWA:** Fully optimized with a multi-cache service worker (v8), precached icons, cache trimming, offline fallback, and build-generated precache manifest for critical app shell chunks.
- **SEO Chapter Pages:** Chapter pages serve as single SEO landing pages with clean URLs, SERP preview modals, and deduplicated heading IDs.
- **Analytics:** Multi-source analytics merging Cloudflare Analytics API, GA4, server-side tracking, and JS-tracked data, with an admin dashboard picking the highest-confidence metric.
- **SEO Coverage:** All pages include `PageMeta` for title, description, OG, Twitter, canonical, and geo targeting, using JSON-LD structured data and a programmatic SEO engine.
- **Content Display:** Library page features subject cards; lesson pages have a blog-style layout with reading progress and sticky TOC.
- **Onboarding:** Streamlined onboarding for DEGREE and AHSEC/SEBA students.
- **Chat Interface:** Uses a standardized 0.1 temperature for LLMs and increased RAG chunk size for academic concepts.

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