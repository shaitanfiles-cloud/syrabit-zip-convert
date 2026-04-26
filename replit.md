# Workspace — Syrabit.ai

## Overview

Syrabit.ai is an AI-powered educational platform for students in Assam, India (AHSEC Class 11/12 and Degree). It offers localized learning resources across 55 subjects, utilizing AI for content generation, syllabus management, and SEO. The platform aims to provide personalized, accessible, and high-quality educational content through chapter-level RAG chunks and a robust admin panel. The core mission is to deliver an affordable, AI-first learning experience with significant market potential in the regional education sector.

## User Preferences

I prefer iterative development with clear communication on major changes. I value detailed explanations for complex features and architectural decisions. Please ensure that the development process prioritizes modularity and maintainability.

## System Architecture

The project is built as a pnpm workspace monorepo, integrating a React + Vite frontend with a FastAPI Python backend.

**Frontend Architecture:**
- **UI/UX:** React, Vite, React Router, Tailwind CSS, mobile-first responsive design, light-only theme.
- **Admin Panel:** Comprehensive CMS for content, blog, SEO, QA, and system intelligence.
- **Bot-Aware Pre-Rendering:** `BotRenderMiddleware` for search engine optimization, managing `robots.txt`, `sitemap.xml`, and `sitemap-index.xml`.
- **Bot Discovery Infrastructure:** Includes RSS feeds, machine-readable manifests (`/llms.txt`, `/llms-full.txt`), AI plugin discovery (`/.well-known/ai-plugin.json`), and IndexNow integration.
- **PWA:** Multi-cache service worker for offline capabilities.
- **SEO Optimization:** Single SEO landing pages, SERP preview modals, `PageMeta`, JSON-LD, programmatic SEO engine, and `SpeakableSpecification`.
- **Analytics:** Multi-source analytics (Cloudflare, GA4, server-side, JS-tracked) with Core Web Vitals.
- **Bilingual Support:** English and Assamese content via UI toggles.
- **Content Display:** Library page with subject cards, lesson pages with blog-style layout, reading progress, and sticky TOC.

**Backend Architecture:**
- **Modular Design:** App factory pattern with shared modules and route modules.
- **AI Integration:** On-demand generation and management of chapter embeddings. Utilizes Vertex AI / Gemini for embeddings, translation, vision analysis, content enhancement, quality scoring, and SEO meta generation via a single-LLM pipeline.
- **Content Pipeline:** Parallel generation of notes, MCQs, and flashcards using `asyncio.gather` with detailed prompts for exam-ready study notes.
- **Content Feedback Loop:** Auto-detection of thin chapters, auto-healing with version history, and quality gates.
- **Admin Analytics:** Dashboard displaying RAG telemetry, chat latency, user counts, content heatmaps, and a historical alert log.
- **PYQ HTML Replica:** Processes PYQ PDFs via Gemini Vision OCR for SEO-optimized, RAG-indexed HTML.
- **Syllabus Embedder:** Generates 768-dimensional chapter/topic embeddings stored in Cloudflare Vectorize.
- **Monetization:** Supports free, starter, and pro plans with credit-based usage.
- **Security:** ASGI-native `SecurityHeadersMiddleware`, prompt safety, spoofed bot UA monitoring, and automated IP blocking. OpenAPI schema suppressed in production.
- **Privacy:** Tracks DPDP Act consent.
- **Performance Optimizations:** Bounded content caching, efficient JWT decoding, thread pooling, MongoDB compound indexes, hierarchy caching, AsyncOpenAI client pooling, parallelized chat pre-processing, and throttled LLM health probes.
- **Educational Browser Backend:** Infrastructure for an in-app educational browser with grounded AI chat, including domain allowlisting, content fetching, and kid-safe content filtering.
- **Unified Log Explorer:** Centralized logging system for frontend, edge-proxy, and backend logs into a single Mongo collection (`unified_logs`), with filtering, searching, export, and tracing capabilities for on-call administration. Includes Cloudflare pull loop and edge worker log shipper.
- **GitHub Actions Supply-Chain Hardening:** SHA-pinned actions, self-enforcing pin gate, least-privilege `GITHUB_TOKEN`, and workflow-security linter gate using `zizmor`.

## External Dependencies

- **Databases:** PostgreSQL, MongoDB, Cloudflare D1.
- **Authentication:** Supabase, JWT helpers, Google OAuth.
- **Caching:** Cloudflare AI Gateway (upstream LLM cache), Cloudflare edge worker KV bindings.
- **LLM Providers:** Cerebras, Groq, OpenRouter (general English chat); Cerebras (qwen-235b) and Gemini 2.5 Flash (admin content generation); Gemini for vision and embeddings; Sarvam (Assamese translation polishing and Assamese-only chat responses with Gemini fallback). All LLM traffic routed through Cloudflare AI Gateway.
- **Payment Gateways:** Razorpay (INR), Stripe (USD).
- **Email Service:** Resend API.
- **UI/UX Frameworks:** React, Vite, React Router, Tailwind CSS.
- **ORM:** Drizzle ORM.
- **API Framework:** FastAPI.
- **Schema Validation:** Zod.
- **API Codegen:** Orval.
- **Build Tools:** esbuild, pnpm, Docker.
- **Production Deployment:** Hybrid architecture with FastAPI on Railway, Cloudflare Worker edge proxy, and frontend on Cloudflare Pages.
- **Cloudflare Services:** Cloudflare Cache Purge API, Worker Cache API, IndexNow Integration.
- **Observability:** Firebase Performance Monitoring for RUM and Core Web Vitals. OpenTelemetry for distributed tracing to Cloud Trace.