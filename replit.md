# Workspace — Syrabit.ai

## Overview

Syrabit.ai is an AI-powered educational platform designed for AHSEC Class 11/12 and Degree students in Assam, India. It provides comprehensive, localized learning resources across two educational boards and 55 subjects, utilizing chapter-level RAG chunks. The platform's core purpose is to personalize education and improve content delivery through AI-driven content generation, syllabus management, and SEO optimization, all managed via a robust admin panel. The project aims to make high-quality educational content accessible and engaging.

## User Preferences

I prefer iterative development with clear communication on major changes. I value detailed explanations for complex features and architectural decisions. Please ensure that the development process prioritizes modularity and maintainability.

## System Architecture

The project is structured as a pnpm workspace monorepo, comprising a React + Vite frontend and a FastAPI Python backend.

**Backend Architecture:**
- **Modular Design:** The backend uses an app factory, shared modules, and route modules for clear separation of concerns.
- **On-Demand Embeddings:** Chapter embeddings are generated automatically upon chapter creation or update, with cleanup on deletion. Topic fields serve as embedding content.
- **Observability:** Tracks LLM provider metrics, vector search similarity, and pipeline runs, consolidated in an Admin Intelligence endpoint.
- **Content Feedback Loop:** Features auto-detection of thin chapters, an auto-heal endpoint with version history, and quality gates for content generation.
- **Content Pipeline Batching:** Notes, MCQs, and flashcard generation run in parallel using `asyncio.gather` with a pipeline semaphore for concurrent LLM calls. Endpoints support generation for single chapters, entire subjects, and bulk regeneration of thin chapters or all notes.
- **Content Generation Prompt:** Generates 2500-4000+ word exam-ready study notes with specific formatting (definition, explanation, key points, example, exam tip). It aims for detailed, contextually rich output.
- **AI Integration:** Integrates with Vertex AI / Gemini for various tasks including text embeddings, translation, vision analysis, content enhancement, quality scoring, and SEO meta generation.
- **SEO & Content Quality:** Implements prompt variants, title diversification, content-derived meta descriptions, and a quality scoring system to prevent thin content.
- **PYQ HTML Replica:** Processes PYQ PDFs via Gemini Vision OCR to create SEO-optimized HTML replicas, stored in MongoDB and RAG-indexed.
- **Syllabus Embedder:** Generates chapter and topic-level embeddings, enriched with context and keywords for precise matching. AI notes generation automatically extracts topics from content and stores them as `seo_topics`.
- **RAG Pipeline:** Employs a 4-way parallel search (keyword chunks, chapter keywords, subject keywords, vector cosine similarity) with grounding citations. It runs RAG, web search, and conversation history fetches in parallel with graceful degradation. Optimizations include caching, parallel lookups, reduced vector search candidates, shared query embedding cache, and a high-confidence fast-path. It features intent-aware context filtering and a grounding budget system.
- **Subject Linking for Syllabus:** A semantic router resolves the subject when syllabus queries lack a `subject_id`, ensuring relevant content delivery and source attribution.
- **Multi-LLM Pipeline:** Designed with a multi-stage architecture (Topic Resolver, RAG Synthesizer, Response Polisher) using various LLMs, though some stages are temporarily disabled due to credit constraints.
- **Monetization:** Supports free, starter, and pro plans with credit-based usage and integrates Razorpay (INR) and Stripe (USD) for payments.
- **Optional Authentication:** Chat, History, and Profile pages are accessible to anonymous users via a `syrabit_anon_id` for conversation persistence in Upstash Redis.
- **Security:** Uses ASGI-native `SecurityHeadersMiddleware` with environment-toggleable headers and prompt safety guardrails to prevent injection/cheating/sensitive content.
- **Privacy:** Tracks DPDP Act consent per-user.
- **Performance Optimizations:** Includes bounded content caching, efficient JWT decoding, thread pooling for Supabase calls, MongoDB indexing, hierarchy caching, and AsyncOpenAI client pooling. Instant fast-path responses for casual greetings (hi/hello/thanks/bye) bypass all LLM/RAG processing. Stage 1 topic resolver skipped for high-confidence regex intents (casual, general, syllabus, chapter_meta) with 10-minute result caching (max 768 entries). Web search results discarded when RAG quality is "high". LLM TTFT timeout 2.0s / slot timeout 2.0s for faster provider failover. Sarvam input limit 12000 chars. RL cooldown 20s, error cooldown 7s. History prefetched in Phase 0+1 gather (parallel with context resolution). Mid-stream failover safety: once tokens are emitted, stream is committed — no provider switching mid-response. SyllabusEmbedder cache refreshes logged at DEBUG level (initial load stays INFO).
- **Observability:** Request-level tracing via `contextvars` request IDs (12-char hex) injected by middleware, threaded through all JSON log records. Per-request latency breakdown logs (`[TIMING][SUMMARY]`) in both streaming and non-streaming chat endpoints. `X-Request-Id` response header on all API responses. Slow request logging (>1s). Chat latency histogram (p50/p95/p99 + bucket distribution) exposed on `/health` endpoint.
- **GEO (Generative Engine Optimization):** Syllabi include `geo_phrases` for AI answer injection, and SEO prompts generate FAQ blocks and specific citations.

**Frontend Architecture:**
- **UI/UX:** Built with React, Vite, React Router, and Tailwind CSS, featuring a mobile-first responsive design. Light mode is the default theme; all UI components use CSS variables and `hsl(var(...))` tokens for theme-aware styling. Dark mode is available via the theme toggle on the library page.
- **Admin Panel:** A comprehensive interface for content editing, CMS, blog publishing, SEO management, QA review, and system intelligence. Includes tools for inline editing, bulk AI generation, and cascade deletes.
- **Component Refactoring:** Large files are split into sub-components for maintainability.
- **Bot-Aware Pre-Rendering:** `BotRenderMiddleware` serves cached pre-rendered HTML to search engine bots for key pages.
- **Bot Crawlability:** The backend serves `robots.txt`, `sitemap.xml`, and `sitemap-index.xml` directly to ensure proper indexing.
- **Performance Optimizations:** Includes emergent badge suppression (script loaded async), PWA icon optimization, lazy-loading CMS sections + PWAInstallPrompt, React Query for caching, CSS grid for content display, prefetching chat/library/chapter pages (500ms idle delay), library-bundle prefetch deferred to 5s for anon users, SSE metadata consolidated into single object to reduce GC pressure during streaming, and memoization of key components.
- **PWA:** Fully optimized with a multi-cache service worker, precached icons, cache trimming, and offline fallback. Tracks installations via MongoDB.
- **SEO Chapter Pages:** Chapter pages serve as single SEO landing pages with a clean URL structure. Includes SERP preview modals and deduplicated heading IDs.
- **Analytics:** Multi-source analytics merging Cloudflare Analytics API, GA4, server-side tracking, and JS-tracked data. The admin dashboard picks the highest-confidence number per metric per day across all sources (Cloudflare > GA4 > Server > JS-tracked) with clear source attribution labels. Cloudflare Analytics uses the GraphQL API (`CF_ANALYTICS_API_TOKEN` + `CF_ZONE_ID` env vars). Historical data sync endpoint stores daily totals from Cloudflare and GA4 into MongoDB `analytics_daily_totals` collection. Server-side `ServerSideTrackingMiddleware` logs every non-asset page request to MongoDB `server_hits` collection with hashed IP (daily + stable), user-agent, bot detection, and country. IP deduplication uses SHA-256 hashed IPs with a configurable salt (`IP_HASH_SALT` env var).
- **SEO Coverage:** All pages include `PageMeta` for title, description, OG, Twitter, canonical, and geo targeting. Uses JSON-LD structured data and a programmatic SEO engine to generate thousands of pages with segmented sitemaps.
- **Content Display:** Library page features subject cards. Lesson pages have a blog-style layout with reading progress and sticky TOC.
- **Onboarding:** Streamlined onboarding for DEGREE and AHSEC/SEBA students.
- **Profile Course Type Selector:** DEGREE students can select course types and subjects.
- **Chat Interface:** Uses a standardized 0.1 temperature for LLMs and increased RAG chunk size for academic concepts.

## External Dependencies

- **Databases:** PostgreSQL (for users/auth) and MongoDB (for content/RAG).
- **Authentication:** Supabase (mirror for PostgreSQL), JWT helpers, Google OAuth (Sign In with Google).
- **Caching:** Redis (distributed cache) and in-memory caching.
- **LLM Providers (SLM pool):** Sarvam, Groq, Gemini, OpenRouter, Cerebras, Fireworks. Also Gemini Vision and gemini-embedding-001.
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