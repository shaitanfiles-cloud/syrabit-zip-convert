# Workspace — Syrabit.ai

## Overview

Syrabit.ai is an AI-powered educational platform designed for students in Assam, India (AHSEC Class 11/12 and Degree). It offers localized learning resources across 55 subjects, leveraging AI for content generation, syllabus management, and SEO. The platform aims to provide personalized education, enhance content delivery through chapter-level RAG chunks, and ensure accessible, engaging, and high-quality educational content via a robust admin panel. The core mission is to deliver an affordable, AI-first learning experience with significant market potential in the regional education sector.

## User Preferences

I prefer iterative development with clear communication on major changes. I value detailed explanations for complex features and architectural decisions. Please ensure that the development process prioritizes modularity and maintainability.

## System Architecture

The project utilizes a pnpm workspace monorepo, featuring a React + Vite frontend and a FastAPI Python backend.

**Frontend Architecture:**
- **UI/UX:** React, Vite, React Router, Tailwind CSS, mobile-first responsive design, light-only theme.
- **Admin Panel:** Comprehensive content management system for editing, CMS, blog publishing, SEO management, QA review, and system intelligence, including custom alert sound uploads and an audio trimming component.
- **Bot-Aware Pre-Rendering:** `BotRenderMiddleware` provides pre-rendered HTML to search engines and manages `robots.txt`, `sitemap.xml`, and `sitemap-index.xml`.
- **Bot Discovery Infrastructure:** Includes RSS feeds, machine-readable manifests (`/llms.txt`, `/llms-full.txt`), AI plugin discovery (`/.well-known/ai-plugin.json`), and IndexNow integration for instant URL indexing.
- **PWA:** Multi-cache service worker for offline capabilities and performance.
- **SEO Optimization:** Single SEO landing pages with clean URLs, SERP preview modals, deduplicated heading IDs, `PageMeta` for all pages, JSON-LD, programmatic SEO engine, premium keyword expansion, topic keyword index, and `SpeakableSpecification`.
- **Analytics:** Multi-source analytics (Cloudflare, GA4, server-side, JS-tracked) with Core Web Vitals.
- **Bilingual Support:** Content available in English and Assamese, independently stored and accessible via UI toggles.
- **Content Display:** Library page with subject cards, lesson pages with blog-style layout, reading progress, and sticky TOC.
- **Onboarding:** Streamlined processes for DEGREE and AHSEC/SEBA students.

**Backend Architecture:**
- **Modular Design:** App factory pattern with shared modules and route modules, enforcing explicit API surfaces via `__all__`.
- **AI Integration:** On-demand generation and management of chapter embeddings. Utilizes Vertex AI / Gemini for embeddings, translation, vision analysis, content enhancement, quality scoring, and SEO meta generation. Single-LLM pipeline for concise responses.
- **Content Pipeline:** Parallel generation of notes, MCQs, and flashcards using `asyncio.gather`. Features a detailed content generation prompt for exam-ready study notes.
- **Content Feedback Loop:** Auto-detection of thin chapters, auto-healing with version history, and quality gates.
- **Admin Analytics:** Dashboard displaying RAG telemetry, chat latency, user counts, content heatmaps, and a historical alert log with real-time notifications.
- **PYQ HTML Replica:** Processes PYQ PDFs via Gemini Vision OCR for SEO-optimized, RAG-indexed HTML.
- **Syllabus Embedder:** Generates 768-dimensional chapter/topic embeddings stored in Cloudflare Vectorize.
- **Monetization:** Supports free, starter, and pro plans with credit-based usage.
- **Security:** ASGI-native `SecurityHeadersMiddleware`, prompt safety, spoofed bot UA monitoring, and automated IP blocking. OpenAPI schema is suppressed in production for security.
- **Privacy:** Tracks DPDP Act consent.
- **Performance Optimizations:** Bounded content caching, efficient JWT decoding, thread pooling, MongoDB compound indexes, hierarchy caching, AsyncOpenAI client pooling, parallelized chat pre-processing, and throttled LLM health probes. Achieves sub-1s chat latency for English queries.
- **Educational Browser Backend:** Infrastructure for an in-app educational browser with grounded AI chat, including domain allowlisting, content fetching, and kid-safe content filtering.

## GitHub Actions supply-chain hardening

- **SHA-pinned actions (Task #883):** every `uses:` reference under `.github/workflows/*.yml` is pinned to a full 40-char commit SHA with a trailing `# vX.Y.Z` tag comment. Float tags like `actions/checkout@v4` are forbidden because a compromise of the upstream tag — as with `tj-actions/changed-files` in 2025 — would silently exfiltrate repo secrets on the next push.
- **Self-enforcing pin gate (Task #895):** `.github/workflows/pinned-actions-check.yml` greps every `uses:` line on each PR and fails the merge unless the ref matches `@[a-f0-9]{40}`. Wired as a required check on master branch protection. Dependabot's weekly bumps update the SHA and trailing comment in lockstep.
- **Least-privilege `GITHUB_TOKEN` (Task #905):** every workflow declares an explicit top-level `permissions:` block (or per-job blocks) granting only the scopes its jobs actually need — `contents: read` by default. Without an explicit block the repo default (`contents: write`) applies, which would let a hypothetically-compromised pinned action push commits, open PRs, or write packages from inside any job. Today only two workflows escalate: `backend-tests.yml` (`pull-requests: write` for the PR-coverage comment, downgraded to read-only on forked PRs) and `trustpilot-aggregate-refresh.yml` (`contents: write` for its auto-commit of the Trustpilot cache file). The convention is documented in the supply-chain header comment block at the top of every workflow file; new workflows MUST set `permissions:`.
- **Workflow-security linter gate (Task #906):** `.github/workflows/workflow-security-scan.yml` runs Trail of Bits' `zizmor` against every file in `.github/workflows/` on each PR to `master` and fails the merge on any finding of severity HIGH or above. Required-check name is **`zizmor — workflow-security scan (HIGH+ blocks merge)`**. Catches the classes of GitHub-Actions footguns the SHA-pin gate is silent on: `pull_request_target` / `workflow_run` token exposure to forked-PR code, `${{ ... }}` script injection into `run:` blocks, cache-poisoning patterns, `actions/checkout` leaving the `GITHUB_TOKEN` in `.git/config` for a later `upload-artifact` step to glob in (`artipacked`), unredacted secrets in logs, and known-vulnerable third-party action versions. zizmor itself is hash-pinned (`zizmor==1.24.1` with sha256s of both the manylinux wheel and the sdist) and installed via `pip install --require-hashes --no-deps`, so the gate's own supply chain is locked. The whole workflow tree is currently clean at default severity (zero suppressions in `.github/zizmor.yml`); informational findings still print in the run log for triage but do not block. To bump zizmor: update the version + both sha256s on the pinned-requirements heredoc inside `workflow-security-scan.yml` (look them up at `https://pypi.org/project/zizmor/<version>/#files`).

## External Dependencies

- **Databases:** PostgreSQL, MongoDB, Cloudflare D1.
- **Authentication:** Supabase, JWT helpers, Google OAuth.
- **Caching:** Cloudflare AI Gateway (upstream LLM cache), Cloudflare edge worker KV bindings (rate limiting, bot HTML cache).
- **LLM Providers:** Groq, Cerebras, OpenRouter (for chat); Cerebras, Sarvam, Gemini (for content generation, vision, embeddings). All LLM traffic is routed through Cloudflare AI Gateway.
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
- **Observability:** Firebase Performance Monitoring for RUM and Core Web Vitals. OpenTelemetry on the backend for distributed tracing to Cloud Trace.