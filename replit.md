# Workspace — Syrabit.ai

## Overview

Syrabit.ai is an AI-powered educational platform designed for AHSEC Class 11/12 and Degree students in Assam, India. It offers comprehensive, localized learning resources across 55 subjects. The platform leverages AI for content generation, syllabus management, and SEO optimization, aiming to personalize education, enhance content delivery through chapter-level RAG chunks, and make high-quality educational content accessible and engaging via a robust admin panel. Its core mission is to provide an affordable, AI-first learning experience for students in the region.

## User Preferences

I prefer iterative development with clear communication on major changes. I value detailed explanations for complex features and architectural decisions. Please ensure that the development process prioritizes modularity and maintainability.

## System Architecture

The project is structured as a pnpm workspace monorepo, with a React + Vite frontend and a FastAPI Python backend.

**Frontend Architecture:**
- **UI/UX:** Built with React, Vite, React Router, and Tailwind CSS, featuring a mobile-first responsive design and a light-only theme.
- **Admin Panel:** A comprehensive interface for content editing, CMS, blog publishing, SEO management, QA review, and system intelligence. Admin notification preferences support custom alert sound file uploads (MP3/WAV, max 500KB) stored in Supabase object storage, with `Audio` element playback for custom chimes. The `AudioTrimPreview` component (`components/admin/AudioTrimPreview.jsx`) provides waveform visualization, playback preview, and draggable start/end trim handles (max 5s) before upload; trimmed audio is converted to WAV client-side.
- **Bot-Aware Pre-Rendering:** Utilizes `BotRenderMiddleware` to serve cached pre-rendered HTML to search engine bots. The backend manages `robots.txt`, `sitemap.xml`, and `sitemap-index.xml` for crawlability. Vite's `botRenderPlugin` only runs in dev mode; production relies on the edge proxy, `BotRenderMiddleware`, and `root_redirect`.
- **Bot Discovery Infrastructure:** RSS feeds at `/feed.xml`, `/feed/notes.xml`, `/feed/mcqs.xml`, `/feed/blog.xml`. Machine-readable manifests at `/llms.txt`, `/llms-full.txt`. AI plugin discovery at `/.well-known/ai-plugin.json`. IndexNow integration for instant URL indexing with auto-push on page generation/publish. All wired via `routes/bot_discovery.py`. Bot traffic split into search/answer bots (welcome, 1200 RPM), training scrapers (blocked via robots.txt), and abusive scrapers (low rate limit). Three separate UA regex patterns in `utils.py`: `_SEARCH_BOT_UA_RE`, `_TRAINING_SCRAPER_UA_RE`, `_ABUSIVE_SCRAPER_UA_RE`. Admin dashboard has dedicated Bot Traffic Analytics and IndexNow Push Status sections.
- **IndexNow Auto-Push:** `IndexNowBatcher` in `routes/bot_discovery.py` queues URLs during SEO page generation and flushes them in batches (max 500/batch, 5-min cooldown for rate-limited flush, force-flush available). Integrated at all content generation/publish points: `_generate_single_page`, `_batch_generate`, `_quality_regen_batch`, `bulk_publish_pages`, `bulk_review_action`, `run-subject`, `auto-run`, `expand-board`, and admin pipeline (`_pipeline_process_one_chapter`). Push history logged to `indexnow_push_log` MongoDB collection. Failed pushes requeue URLs. Cooldown-blocked flushes schedule deferred retries. Admin endpoints: `GET /admin/indexnow/stats`, `GET /admin/indexnow/history`.
- **PWA:** Fully optimized with a multi-cache service worker (v10) for offline access, performance, and API data precaching. Precache manifest covers critical chunks (react-dom, vendor, router, query, radix, framer).
- **SEO Chapter Pages:** Chapter pages serve as single SEO landing pages with clean URLs, SERP preview modals, and deduplicated heading IDs, supporting both 4-segment and 5-segment URL patterns.
- **Analytics:** Multi-source analytics merging Cloudflare Analytics API, GA4, server-side tracking, and JS-tracked data. Core Web Vitals (LCP, INP, CLS, FCP, TTFB) reported to PostHog/GA4 via `web-vitals` library. First-touch UTM attribution persisted in localStorage for cross-session conversion tracking.
- **SEO Coverage:** All pages include `PageMeta` for title, description, OG, Twitter, canonical, and geo targeting, using JSON-LD structured data and a programmatic SEO engine. Premium keyword expansion engine (`_build_expanded_keywords`) generates 80+ keyword variants per topic page including individual word fragments, board variants (AHSEC/SEBA/Degree alternatives), exam suffixes, and cross-references. Topic keyword index endpoints (`/api/seo/keyword-index` JSON and `/api/seo/keyword-index.txt` plain text) expose all topics with keywords for AI bot discovery. Schema.org `SpeakableSpecification` on all topic pages for voice search. `X-Topic-Keywords` HTTP header on all SEO responses.
- **Bilingual Content (EN/AS):** Supports English and Assamese content with a user-selectable language preference, independent content storage, and UI toggles.
- **Content Display:** Library page features subject cards; lesson pages have a blog-style layout with reading progress and sticky TOC.
- **Shared UI Components:** `components/ui/` contains extracted shared components including `StickyToc` (table-of-contents sidebar), `ModalOverlay` (backdrop + card dialog wrapper), `StatCard` (stat display card), and `LangToggle` (language switcher).
- **Onboarding:** Streamlined onboarding for DEGREE and AHSEC/SEBA students.

**Backend Architecture:**
- **Modular Design:** Employs an app factory, shared modules, and route modules for clear separation of concerns.
- **On-Demand Embeddings:** Chapter embeddings are automatically generated and managed.
- **Observability:** Tracks LLM provider metrics, vector search similarity, and pipeline runs.
- **Content Feedback Loop:** Features auto-detection of thin chapters, an auto-heal endpoint with version history, and quality gates for content generation.
- **Content Pipeline Batching:** Notes, MCQs, and flashcard generation run in parallel using `asyncio.gather` with a pipeline semaphore.
- **Content Generation Prompt:** Generates detailed exam-ready study notes (2500-4000+ words) with specific formatting.
- **Admin Analytics:** Dashboard displays RAG telemetry, chat latency, user counts, content heatmaps, and historical alert log. Alert history panel shows past bot/system alerts from `db.alerts` with timestamp, type, severity, message, threshold context (metric/value/actual via `threshold_snapshot`), and acknowledge/dismiss functionality. One-time migration script `migrate_alert_thresholds.py` backfills `threshold_snapshot` for historical alerts created before the field was added. Backend routes: `GET /admin/alerts`, `PATCH /admin/alerts/{id}/acknowledge`, `PATCH /admin/alerts/acknowledge-all`. Alert thresholds (error rate %, latency p95 ms, fallback rate %, spoof RPM) and auto-expiration settings are configurable from the admin UI via `GET/PUT /admin/alert-settings`, persisted in `db.api_config.alert_settings`, and reloaded every alerting loop cycle. Auto-expiration acknowledges unacknowledged alerts older than N days (runs every ~30 min). Real-time alert notifications: audio chime (Web Audio API, toggleable) plays when new unacknowledged alerts appear on dashboard poll; browser push notifications dispatched for critical (red-severity) alerts via `_dispatch_alert` → `_dispatch_push_to_all`; push subscription toggle in Alert History panel header. Per-admin notification preferences stored server-side in MongoDB (`admin_notification_prefs` collection) via `GET/PUT /admin/notification-prefs`. Configurable per-admin: sound on/off, push on/off, chime tone (default/soft/urgent/bell), and per-alert-type severity filters for both sound and push channels. Preferences persist across browsers/devices.
- **Push Delivery Tracking:** `_dispatch_push` persists per-subscription delivery results (sent/failed/expired) to `push_delivery_log` MongoDB collection. Admin API endpoints: `GET /admin/push/delivery-log` (paginated history), `GET /admin/push/delivery-log/{dispatch_id}` (per-subscription detail), `GET /admin/push/subscriptions` (active subscriptions list), `GET /admin/push/delivery-stats?days=N` (aggregated stats with daily breakdown). Admin Notifications page has a "Push Delivery" tab showing stats cards, daily breakdown table, expandable dispatch history with per-subscription results, and active subscriptions table. Dashboard notification preferences panel includes a 7-day push delivery summary widget.
- **AI Integration:** Integrates with Vertex AI / Gemini for various AI tasks including embeddings, translation, vision analysis, content enhancement, quality scoring, and SEO meta generation.
- **SEO & Content Quality:** Implements prompt variants, title diversification, content-derived meta descriptions, and a quality scoring system, including Generative Engine Optimization (GEO) for AI answer injection and FAQ blocks.
- **PYQ HTML Replica:** Processes PYQ PDFs via Gemini Vision OCR to create SEO-optimized, RAG-indexed HTML replicas.
- **Syllabus Embedder:** Generates chapter and topic-level embeddings (768 dimensions via gemini-embedding-001), stored in Cloudflare Vectorize (`syllabus-index`).
- **Single-LLM Pipeline:** Direct LLM calls using training knowledge for concise responses (50-100 words default, max 300) in English and Assamese. Assamese routes through Sarvam LLM, English uses an SLM pool.
- **Monetization:** Supports free, starter, and pro plans with credit-based usage.
- **Optional Authentication:** Chat, History, and Profile pages are accessible to anonymous users, with conversations persisted in Redis and PostgreSQL.
- **Security:** Uses ASGI-native `SecurityHeadersMiddleware` and prompt safety guardrails. Spoofed bot UA monitoring tracks failed bot verification attempts across both edge proxy (KV-based counters with `SPOOF_ALERT` console warnings at thresholds 50/200/500 per minute) and backend (MongoDB `bot_spoof_attempts` collection with in-memory metrics). Admin dashboard at `GET /api/admin/security/spoofed-bots` shows daily trends, top claimed bots, repeat offender IPs, and real-time RPM. Alerting via `_dispatch_alert("spoofed_bot_surge")` fires when spoof RPM exceeds threshold (default 50). Auto-block: IPs exceeding a configurable spoof threshold (default 100 attempts in 24h) are automatically added to `blocked_ips` with reason `auto_threshold` and `blocked_by: system/auto-block`. Threshold is configurable via admin alert settings (`auto_block_threshold` in `_ALERT_THRESHOLDS`). Auto-blocks trigger `_dispatch_alert("auto_block_ip")` notifications and are visually distinguished in the admin UI with an "Auto" badge.
- **Privacy:** Tracks DPDP Act consent per-user.
- **Performance Optimizations:** Includes bounded content caching (in-memory + Redis), efficient JWT decoding, thread pooling, MongoDB compound indexes, hierarchy caching, AsyncOpenAI client pooling, fully parallelized chat pre-processing, and throttled LLM health probes.
- **Chat Latency:** Achieves sub-1s TTFT for English queries via hedged requests (TTFT timeout: 0.35s, Phase 0 budget: 150ms). Casual queries skip Phase 0 entirely when no context is provided. Redis cache check is async (non-blocking via run_in_executor). Assamese queries around 1.4-2.1s.
- **Response Length:** Concise by default (30-60 words), hard limit 200 words, with specific prompt guidelines for various query types.

## External Dependencies

- **Databases:** PostgreSQL (users/auth), MongoDB (content/RAG), Cloudflare D1 (edge replica for read-heavy content catalog).
- **Authentication:** Supabase (mirror for PostgreSQL), JWT helpers, Google OAuth. E2e test admin account (`e2e-admin@syrabit.test` / `e2e-test-admin-2026`) enabled only when `ENABLE_E2E_ADMIN=true` env var is set (development only, never in production).
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