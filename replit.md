# Workspace — Syrabit.ai

## Overview

Syrabit.ai is an AI-powered educational platform for students in Assam, India (AHSEC Class 11/12 and Degree). It provides localized learning resources across 55 subjects, utilizing AI for content generation, syllabus management, and SEO. The platform aims to personalize education, enhance content delivery via chapter-level RAG chunks, and make high-quality educational content accessible and engaging through a robust admin panel. Its core mission is to deliver an affordable, AI-first learning experience.

## User Preferences

I prefer iterative development with clear communication on major changes. I value detailed explanations for complex features and architectural decisions. Please ensure that the development process prioritizes modularity and maintainability.

## System Architecture

The project is a pnpm workspace monorepo, with a React + Vite frontend and a FastAPI Python backend.

**Frontend Architecture:**
- **UI/UX:** React, Vite, React Router, Tailwind CSS, mobile-first responsive design, light-only theme.
- **Admin Panel:** Content editing, CMS, blog publishing, SEO management, QA review, and system intelligence. Includes custom alert sound uploads and an audio trimming component.
- **Bot-Aware Pre-Rendering:** `BotRenderMiddleware` serves cached pre-rendered HTML to search engines. Manages `robots.txt`, `sitemap.xml`, and `sitemap-index.xml`.
- **Bot Discovery Infrastructure:** RSS feeds, machine-readable manifests (`/llms.txt`, `/llms-full.txt`), AI plugin discovery (`/.well-known/ai-plugin.json`), and IndexNow integration for instant URL indexing.
- **IndexNow Auto-Push:** Queues and flushes URLs for immediate indexing on content generation/publish, with logging and retry mechanisms.
- **PWA:** Multi-cache service worker for offline access and performance, including critical chunk precaching.
- **SEO Chapter Pages:** Single SEO landing pages with clean URLs, SERP preview modals, and deduplicated heading IDs.
- **Analytics:** Multi-source analytics (Cloudflare, GA4, server-side, JS-tracked) including Core Web Vitals.
- **SEO Coverage:** `PageMeta` for all pages, JSON-LD, programmatic SEO engine, premium keyword expansion, topic keyword index, and `SpeakableSpecification`.
- **Bilingual Content:** Supports English and Assamese content with independent storage and UI toggles.
- **Content Display:** Library page with subject cards, lesson pages with blog-style layout, reading progress, and sticky TOC.
- **Onboarding:** Streamlined for DEGREE and AHSEC/SEBA students.

**Backend Architecture:**
- **Modular Design:** App factory, shared modules, route modules.
- **Shared API Surface (`__all__`):** The seven shared backend modules — `config`, `deps`, `cache`, `db_ops`, `rag`, `utils`, `analytics_helpers` (under `artifacts/syrabit-backend/`) — are the project's declared cross-module API. Each one exposes its public surface via an explicit `__all__` list at the top of the file. When adding a new symbol that other modules will import, you must add its name to that module's `__all__`. The test `tests/test_shared_module_all.py` enforces that every name in `__all__` resolves and that none of these modules use `from X import *` (which caused the Task #443 outage by re-exporting `pathlib.Path` into a route).
- **On-Demand Embeddings:** Automatic generation and management of chapter embeddings.
- **Observability:** Tracks LLM provider metrics, vector search similarity, and pipeline runs.
- **Content Feedback Loop:** Auto-detection of thin chapters, auto-heal with version history, and quality gates.
- **Content Pipeline Batching:** Parallel generation of notes, MCQs, and flashcards using `asyncio.gather`.
- **Content Generation Prompt:** Generates detailed, exam-ready study notes (2500-4000+ words) with specific formatting.
- **Admin Analytics:** Dashboard displays RAG telemetry, chat latency, user counts, content heatmaps, and historical alert log with configurable thresholds and real-time notifications.
- **Push Delivery Tracking:** Persists delivery results for web push notifications, with admin logging and stats.
- **AI Integration:** Vertex AI / Gemini for embeddings, translation, vision analysis, content enhancement, quality scoring, and SEO meta generation.
- **SEO & Content Quality:** Prompt variants, title diversification, content-derived meta descriptions, quality scoring, and Generative Engine Optimization (GEO).
- **PYQ HTML Replica:** Processes PYQ PDFs via Gemini Vision OCR for SEO-optimized, RAG-indexed HTML.
- **Syllabus Embedder:** Generates 768-dimensional chapter/topic embeddings stored in Cloudflare Vectorize.
- **Single-LLM Pipeline:** Direct LLM calls for concise responses (50-100 words), supporting English (SLM pool) and Assamese (Sarvam LLM).
- **Monetization:** Free, starter, and pro plans with credit-based usage.
- **Optional Authentication:** Chat, History, Profile pages accessible to anonymous users.
- **Security:** ASGI-native `SecurityHeadersMiddleware`, prompt safety, spoofed bot UA monitoring, and automated IP blocking.
- **Privacy:** Tracks DPDP Act consent.
- **Performance Optimizations:** Bounded content caching, efficient JWT decoding, thread pooling, MongoDB compound indexes, hierarchy caching, AsyncOpenAI client pooling, parallelized chat pre-processing, throttled LLM health probes.
- **Chat Latency:** Sub-1s TTFT for English queries via hedged requests, 1.4-2.1s for Assamese.

## Verify Pipeline

Run `pnpm verify` from the repo root to execute the full pre-merge gate. This runs `typecheck` across all artifacts and shared libs, then runs `verify:jsonld` for every package that defines it (currently `@workspace/syrabit`), which validates structured-data builders (Article, LearningResource, WebPage, Breadcrumb, FAQ, HowTo, LocalBusiness, PYQ Dataset, Quiz). To run the JSON-LD validator alone: `pnpm --filter @workspace/syrabit verify:jsonld`.

## External Dependencies

- **Databases:** PostgreSQL, MongoDB, Cloudflare D1.
- **Authentication:** Supabase, JWT helpers, Google OAuth.
- **Caching:** Redis, in-memory caching, Cloudflare Worker edge caching.
- **LLM Providers:** Groq, Cerebras, OpenRouter (for chat); Cerebras, Sarvam, Gemini (for content generation, vision, embeddings).
- **Cloudflare AI Gateway:** LLM traffic routing, caching, analytics, fallback.
- **Payment Gateways:** Razorpay (INR), Stripe (USD).
- **Email Service:** Resend API.
- **UI/UX Frameworks:** React, Vite, React Router, Tailwind CSS.
- **ORM:** Drizzle ORM.
- **API Framework:** FastAPI.
- **Schema Validation:** Zod.
- **API Codegen:** Orval.
- **Build Tools:** esbuild, pnpm.
- **Containerization:** Docker.
- **Production Deployment:** Hybrid architecture with FastAPI on Railway/Replit, Cloudflare Worker edge proxy, frontend on Cloudflare Pages.
- **Cloudflare Edge Cache Auto-Purge:** Utilizes Cloudflare Cache Purge API and Worker Cache API.
- **IndexNow Integration:** Backend endpoints for instant URL submission to search engines.