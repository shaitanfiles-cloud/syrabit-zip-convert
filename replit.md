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
- **AI-Powered Syllabus Uploader:** An agentic pipeline handles PDF uploads, extracts syllabus information using Gemini Vision, generates board-aware LLM notes, chunks content for RAG, embeds chapters, creates CMS blog drafts, and performs SEO/GEO tagging. This process streams SSE events to the frontend for real-time progress.
- **Vertex AI / Gemini Integration:** Nine AI services are integrated via `vertex_services.py`, including text embeddings, translation, vision analysis, content enhancement, quality scoring, topic suggestion, SEO meta generation, content gap finding, and long document reading (Gemini 1.5 Pro).
- **SEO & Content Quality:** Implemented prompt variants for content generation, title diversification, and content-derived meta descriptions. A quality scoring system tracks word count, heading count, unique ratio, and feature presence (FAQ, PYQ, examples) to prevent thin content. Anti-thin-page gates enforce minimum word counts.
- **PYQ HTML Replica:** A backend endpoint processes PYQ PDFs, uses Gemini Vision OCR to build SEO-optimized HTML replicas, stores them in MongoDB, and serves them. These replicas are RAG-indexed with high priority.
- **RAG Pipeline:** A 4-way parallel search mechanism combines keyword chunks, chapter keywords, subject keywords, and vector cosine similarity. Grounding now includes `[PAGE: slug]` citation headers. Embeddings are generated on content publish.
- **Monetization:** Supports free, starter, and pro plans with credit-based usage. Integrates Razorpay (INR) and Stripe (USD) for payments, with webhook handlers for transaction verification.
- **Security:** Utilizes ASGI-native `SecurityHeadersMiddleware` for HSTS, CSP, and X-Frame-Options.
- **GEO (Generative Engine Optimization):** Syllabi include `geo_phrases` for AI answer injection. SEO prompts include specific citations (AHSEC exam year, NCERT/SCERT) and generate FAQ blocks.

**Frontend Architecture:**
- **UI/UX:** React + Vite, React Router, and Tailwind CSS. Employs a mobile-first responsive design using `100svh` and safe-area insets.
- **Admin Panel:** A comprehensive admin interface with 20 sections, including Dashboard, Syllabus, Content Editor, Content Studio, SEO Manager, QA Review, Automation, Users, Conversations, Analytics, Monetization, and Health. Significant upgrades include internal linking engines, quality gates, FAQ auto-extraction, conversion funnels, and schema.org auto-injection.
- **Component Refactoring:** Large frontend files are split into sub-components for better maintainability (e.g., `admin/`, `pages/`, `utils/`).
- **Bot-Aware Pre-Rendering:** `BotRenderMiddleware` detects search engine bots and serves pre-rendered HTML for key pages (homepage, library, subject landings, topic pages, PYQ pages) with a 1-hour TTL cache, ensuring full content, meta tags, and Schema.org are available to crawlers.
- **Content Display:** Library page features browser-window style subject cards. Subject Landing Pages list chapters with search and topic chips. Lesson Pages (`SeoTopicPage`) have a blog-style layout with reading progress, sticky TOC, and improved typography.
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
- **LLM Providers:**
    - Google Gemini (gemini-2.5-flash, Gemini Vision, gemini-embedding-001) - primary.
    - Groq (llama-3.3-70b, llama-3.1-8b).
    - Fireworks (deepseek-v3p2).
    - Sarvam clients.
- **Payment Gateways:** Razorpay (INR) and Stripe (USD).
- **Email Service:** Resend API (for password resets).
- **UI/UX Frameworks:** React, Vite, React Router, Tailwind CSS.
- **ORM:** Drizzle ORM (for PostgreSQL).
- **API Framework:** FastAPI (Python backend), Express 5 (Node.js for some utilities).
- **Schema Validation:** Zod.
- **API Codegen:** Orval (from OpenAPI spec).
- **Build Tools:** esbuild, pnpm.
- **Containerization:** Docker.