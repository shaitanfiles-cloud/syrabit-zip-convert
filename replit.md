# Workspace — Syrabit.ai

## Overview

Syrabit.ai is an AI-powered educational platform designed for AHSEC Class 11/12 and Degree students in Assam, India. It offers comprehensive, localized learning resources across 55 subjects. The platform leverages AI for content generation, syllabus management, and SEO optimization, aiming to personalize education, enhance content delivery through chapter-level RAG chunks, and make high-quality educational content accessible and engaging via a robust admin panel. Its core mission is to provide an affordable, AI-first learning experience for students in the region.

## User Preferences

I prefer iterative development with clear communication on major changes. I value detailed explanations for complex features and architectural decisions. Please ensure that the development process prioritizes modularity and maintainability.

## System Architecture

The project is structured as a pnpm workspace monorepo, with a React + Vite frontend and a FastAPI Python backend.

**Frontend Architecture:**
- **UI/UX:** Built with React, Vite, React Router, and Tailwind CSS, featuring a mobile-first responsive design and a light-only theme.
- **Admin Panel:** A comprehensive interface for content editing, CMS, blog publishing, SEO management, QA review, and system intelligence.
- **Bot-Aware Pre-Rendering:** Utilizes `BotRenderMiddleware` to serve cached pre-rendered HTML to search engine bots. The backend manages `robots.txt`, `sitemap.xml`, and `sitemap-index.xml` for crawlability.
- **PWA:** Fully optimized with a multi-cache service worker (v9) for offline access, performance, and API data precaching.
- **SEO Chapter Pages:** Chapter pages serve as single SEO landing pages with clean URLs, SERP preview modals, and deduplicated heading IDs, supporting both 4-segment and 5-segment URL patterns.
- **Analytics:** Multi-source analytics merging Cloudflare Analytics API, GA4, server-side tracking, and JS-tracked data.
- **SEO Coverage:** All pages include `PageMeta` for title, description, OG, Twitter, canonical, and geo targeting, using JSON-LD structured data and a programmatic SEO engine.
- **Bilingual Content (EN/AS):** Supports English and Assamese content with a user-selectable language preference, independent content storage, and UI toggles.
- **Content Display:** Library page features subject cards; lesson pages have a blog-style layout with reading progress and sticky TOC.
- **Onboarding:** Streamlined onboarding for DEGREE and AHSEC/SEBA students.

**Backend Architecture:**
- **Modular Design:** Employs an app factory, shared modules, and route modules for clear separation of concerns.
- **On-Demand Embeddings:** Chapter embeddings are automatically generated and managed.
- **Observability:** Tracks LLM provider metrics, vector search similarity, and pipeline runs.
- **Content Feedback Loop:** Features auto-detection of thin chapters, an auto-heal endpoint with version history, and quality gates for content generation.
- **Content Pipeline Batching:** Notes, MCQs, and flashcard generation run in parallel using `asyncio.gather` with a pipeline semaphore.
- **Content Generation Prompt:** Generates detailed exam-ready study notes (2500-4000+ words) with specific formatting.
- **Admin Analytics:** Dashboard displays RAG telemetry, chat latency, user counts, and content heatmaps.
- **AI Integration:** Integrates with Vertex AI / Gemini for various AI tasks including embeddings, translation, vision analysis, content enhancement, quality scoring, and SEO meta generation.
- **SEO & Content Quality:** Implements prompt variants, title diversification, content-derived meta descriptions, and a quality scoring system, including Generative Engine Optimization (GEO) for AI answer injection and FAQ blocks.
- **PYQ HTML Replica:** Processes PYQ PDFs via Gemini Vision OCR to create SEO-optimized, RAG-indexed HTML replicas.
- **Syllabus Embedder:** Generates chapter and topic-level embeddings (768 dimensions via gemini-embedding-001), stored in Cloudflare Vectorize (`syllabus-index`).
- **Single-LLM Pipeline:** Direct LLM calls using training knowledge for concise responses (50-100 words default, max 300) in English and Assamese. Assamese routes through Sarvam LLM, English uses an SLM pool.
- **Monetization:** Supports free, starter, and pro plans with credit-based usage.
- **Optional Authentication:** Chat, History, and Profile pages are accessible to anonymous users, with conversations persisted in Redis and PostgreSQL.
- **Security:** Uses ASGI-native `SecurityHeadersMiddleware` and prompt safety guardrails.
- **Privacy:** Tracks DPDP Act consent per-user.
- **Performance Optimizations:** Includes bounded content caching (in-memory + Redis), efficient JWT decoding, thread pooling, MongoDB compound indexes, hierarchy caching, AsyncOpenAI client pooling, fully parallelized chat pre-processing, and throttled LLM health probes.
- **Chat Latency:** Achieves sub-1s TTFT for English queries via hedged requests (TTFT timeout: 0.35s, Phase 0 budget: 150ms). Casual queries skip Phase 0 entirely when no context is provided. Redis cache check is async (non-blocking via run_in_executor). Assamese queries around 1.4-2.1s.
- **Response Length:** Concise by default (30-60 words), hard limit 200 words, with specific prompt guidelines for various query types.

## External Dependencies

- **Databases:** PostgreSQL (users/auth), MongoDB (content/RAG), Cloudflare D1 (edge replica for read-heavy content catalog).
- **Authentication:** Supabase (mirror for PostgreSQL), JWT helpers, Google OAuth.
- **Caching:** Redis, in-memory caching, Cloudflare Worker edge caching.
- **LLM Providers:**
    - **Chat:** Groq, Cerebras, OpenRouter, Fireworks (SLM pool).
    - **Content Generation:** Cerebras (primary), Sarvam (fallback), Gemini 2.5-flash (last resort), Gemini Vision, gemini-embedding-001.
- **Cloudflare AI Gateway:** Routes LLM traffic, provides caching, analytics, and graceful degradation. Gateway 401 auth errors trigger automatic fallback to direct provider URLs with a 5-minute cooldown before retrying the gateway.
- **Payment Gateways:** Razorpay (INR), Stripe (USD).
- **Email Service:** Resend API.
- **UI/UX Frameworks:** React, Vite, React Router, Tailwind CSS.
- **ORM:** Drizzle ORM.
- **API Framework:** FastAPI.
- **Schema Validation:** Zod.
- **API Codegen:** Orval.
- **Build Tools:** esbuild, pnpm.
- **Containerization:** Docker.
- **Production Deployment:** Hybrid architecture — FastAPI backend deployable to Railway (Dockerfile + railway.toml ready) or Replit, Cloudflare Worker edge proxy (`api.syrabit.ai`), frontend on Cloudflare Pages (`syrabit.ai`). Railway deployment guide at `artifacts/syrabit-backend/RAILWAY-DEPLOY.md`.
- **Cloudflare Edge Cache Auto-Purge:** Utilizes Cloudflare Cache Purge API for invalidating cached content.