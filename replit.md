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
- **Vertex AI Gemini Flash chat (Task #607):** English chat can stream through Vertex AI's `streamGenerateContent` SSE endpoint via `vertex_chat.py` (google-auth + httpx) for lowest TTFT. Activated when the resolved model is `vertex/gemini-flash`; resolution order is request-pinned `msg.model` → admin override (`db.api_config.chat_model.default`) → env `CHAT_DEFAULT_MODEL`. Triggered inside `call_llm_api_stream` (llm.py) before the legacy SLM hedged pool. If Vertex fails before the first token, the stream silently falls back to `openai/gpt-oss-20b` and the legacy provider list; mid-stream errors emit a normal `error` event. Indic/Assamese requests bypass Vertex entirely so the existing Sarvam path keeps owning translation. Admin panel → API Config → "Chat Model" section toggles the active provider; Cloudflare worker passes the SSE body through unchanged.
- **Educational Browser Backend (Task #576):** Backend infrastructure for an in-app educational browser + grounded AI chat. Lives in `edu_allowlist.py` (DB-driven domain allowlist with hard denylist + `.edu/.ac.in/.gov.in` shortcut + admin CRUD), `edu_reader.py` (allowlisted URL fetch with robots.txt cache, SSRF guard, per-host concurrency, Readability-lite extraction via `lxml`, language detection, 24h Redis cache), `guardrails/web_safety.py` (kid-safe content filter applied to web grounding & reader output), `grounded_answer.py` (RAG + web grounding + page-context fusion → numbered, deduped citation list → SSE stream with cancellation, idempotent message IDs, output-safety break, response cache), `routes/edu_browser.py` (mounts `/api/edu/reader/fetch`, `/api/edu/grounded-answer`, `/api/edu/health`, plus admin allowlist/blocked-log endpoints with per-IP rate limits). Smoke tests in `artifacts/syrabit-backend/tests/test_edu_browser.py`. Browser shell UI is intentionally Phase 2.

## Verify Pipeline

Run `pnpm verify` from the repo root to execute the full pre-merge gate. This runs `typecheck` across all artifacts and shared libs, then runs `verify:jsonld` for every package that defines it (currently `@workspace/syrabit`), which validates structured-data builders (Article, LearningResource, WebPage, Breadcrumb, FAQ, HowTo, LocalBusiness, PYQ Dataset, Quiz). To run the JSON-LD validator alone: `pnpm --filter @workspace/syrabit verify:jsonld`.

### Critical-CSS extraction (Task #856)

`artifacts/syrabit/scripts/inline-critical-css.mjs` runs `beasties` (Google's maintained fork of `critters`) as a build step after prerender and before verify-all. It walks every `dist/*.html`, inlines ~7–16 KB of above-the-fold CSS into `<style>` in `<head>`, and rewrites the 141 KB main stylesheet `<link>` to a non-blocking preload+swap with a `<noscript>` fallback. Also un-wraps the legacy full-sheet `<style data-inline-css>` block on prerendered routes (`/library`, `/browser`) so Beasties can extract their critical subset — cuts those HTMLs from 189 KB to ~59 KB each. Estimated FCP win: ~265 ms on Slow 4G (Lighthouse Simulated Throttling math vs measured asset sizes); see `artifacts/syrabit/docs/perf/lighthouse-{baseline,postfix}-2026-04-25.html`. Real Chrome Lighthouse on the deployed CDN URL is tracked as follow-up #865.

### OpenAPI schema is suppressed in prod by design (Task #857)

`/openapi.json` and `/docs` are intentionally NOT reachable from the public internet on `api.syrabit.ai` or directly on the Railway origin. Two stacked gates enforce this: (1) `OriginSharedSecretMiddleware` (`artifacts/syrabit-backend/middleware.py:79-93`) excludes `/openapi.json` + `/docs` from `_ORIGIN_AUTH_OPEN_PATHS`, so the Railway hostname returns `403 {"detail": "Direct origin access denied — must traverse the edge worker."}` for those paths even when traffic carries a valid UA; (2) the Cloudflare edge worker (`workers/edge-proxy/src/index.ts`) only proxies `/api/*` paths to the backend — `/openapi.json` falls through to PAGES_ORIGIN and serves the SPA HTML 200, so the schema is invisible from `api.syrabit.ai/openapi.json` too. Rationale: exposing every route shape is a low-cost reconnaissance vector, and we have no public SDK consumer that needs the live schema. To re-enable for a one-off (e.g. regenerating an internal client): add `/openapi.json` to `_ORIGIN_AUTH_OPEN_PATHS`, redeploy backend, then `curl https://workspacemockup-sandbox-production-df37.up.railway.app/openapi.json` (still gated by Railway-edge IP allowlist + Cloudflare WAF). Revert the middleware change after the regen run.

## Deploy — Cloudflare Pages

Run `pnpm deploy:pages` from the repo root to publish `artifacts/syrabit/dist` to Cloudflare Pages. Defaults are now correct out of the box: `--project-name=syrabit-analytics --branch=master` (the public hostname is `syrabit-zip-convert.pages.dev`, referenced as `PAGES_ORIGIN` in `workers/edge-proxy/wrangler.toml`). Override only if you are deploying to a different Pages project: `CF_PAGES_PROJECT_NAME=<project> CF_PAGES_BRANCH=<branch> pnpm deploy:pages`. Requires `CLOUDFLARE_API_TOKEN` (and `CLOUDFLARE_ACCOUNT_ID` if your token is scoped to multiple accounts) in the environment.

## Deploy — Railway (backend)

Drive the syrabit-backend Railway service from this workspace via `pnpm run railway:*` (Task #846). The dispatcher is `scripts/railway.sh`; subcommands include `redeploy` (re-run the latest built image, polls until SUCCESS), `deploy` (`railway up`-style upload of `artifacts/syrabit-backend/`), `status`, `logs [-b]`, `vars`, `var-set`, and `var-unset`. All read paths and `redeploy`/`var-*` use the Railway GraphQL API directly (no CLI needed); `deploy` shells out to the `railway` CLI. Production project / service / `production` environment are baked in as defaults — override with `RAILWAY_PROJECT_ID` / `RAILWAY_SERVICE_ID` / `RAILWAY_ENVIRONMENT` for staging. Auth via `RAILWAY_API_TOKEN` (Replit Secret). The same flow runs from CI via `.github/workflows/railway-deploy.yml` (`workflow_dispatch` only, gated to master). Full reference: `docs/RAILWAY-DEPLOYMENT.md` ("Driving deploys from Replit / CI").

## External Dependencies

- **Databases:** PostgreSQL, MongoDB, Cloudflare D1.
- **Authentication:** Supabase, JWT helpers, Google OAuth.
- **Caching:** Cloudflare AI Gateway (upstream LLM cache, 3600s TTL), edge worker KV bindings (`RATE_LIMIT`, `BOT_HTML_CACHE`), per-worker in-memory L1 cache. Upstash Redis was removed 2026-04 — `redis_client` is now permanently `None` and call sites fall through to non-cached paths. To re-enable a managed L2 (e.g. GCP Memorystore on Cloud Run), un-pin `MEMORYSTORE_REDIS_URL` in `config.py:472`.
- **LLM Providers:** Groq, Cerebras, OpenRouter (for chat); Cerebras, Sarvam, Gemini (for content generation, vision, embeddings).
- **Cloudflare AI Gateway (BYOK):** All LLM traffic is routed through the `syrabit` AI Gateway. Provider keys are stored in the Cloudflare dashboard (BYOK — Bring Your Own Key). The backend sends a dummy `api_key='x'` + `Authorization: ''` + `cf-aig-byok-key: true` headers; CF Gateway substitutes its stored provider key before forwarding upstream. This lets `GROQ_API_KEY`, `GEMINI_API_KEY`, `CEREBRAS_API_KEY`, and `OPENROUTER_API_KEY` be removed from the backend environment entirely. **Exception — Sarvam:** CF does not support BYOK for custom providers, so `SARVAM_API_KEY` / `SARVAM_TRANSLATE_KEY` must remain in env; traffic still routes through `custom-sarvam` gateway slug for caching/analytics.
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
- **Observability — RUM + Distributed Tracing (Task #610):** Firebase Performance Monitoring captures Core Web Vitals (LCP / INP / CLS / TTFB / FCP) and custom chat traces (`chat_send_first_token`, `chat_send_total`) from production browsers. OpenTelemetry on the backend exports sampled (~10%) Cloud Trace spans for `/api/ai/chat/stream` with `syrabit.chat.*` attributes (intent, model, path, first_token_ms, total_ms). W3C `traceparent` header is generated client-side and propagated edge → backend → Vertex. All gated behind env vars (`TRACING_ENABLED`, `VITE_FIREBASE_*`) so dev / unconfigured deploys see zero overhead. Dashboards & starter alerts documented in `artifacts/syrabit-backend/docs/PERFORMANCE_MONITORING.md`.

## Operational Notes

### AdminHealth cron-pill testId convention

The cron-health pills rendered in the AdminHealth dashboard follow a uniform `<cron-name>-cron-*` data-testid namespace so monitoring/Playwright surfaces can target each pill consistently. The hooks emitted by the shared `<CronHealthPill>` are: `<prefix>-tile`, `<prefix>-status`, `<prefix>-pill`, `<prefix>-run-link`, `<prefix>-refresh`. Current pills:

- **Trustpilot refresh cron** — prefix `trustpilot-refresh-cron` (wrapper: `TrustpilotRefreshCronPill.jsx`, endpoint: `/admin/health/trustpilot/refresh-cron`).
- **Cloudflare WAF drift cron** — prefix `cf-waf-drift-cron` (wrapper: `CfWafDriftCronPill.jsx`, endpoint: `/admin/health/cf-waf-drift/cron`).

**Task #838 rename (2026-04-24):** the Trustpilot pill's testId moved from `trustpilot-cron-*` to `trustpilot-refresh-cron-*` so it lines up with the cf-waf-drift pill's naming convention. Task #843 swept the entire repository for stale **runtime DOM selectors** (i.e. anything that calls `getByTestId`, `querySelector('[data-testid="…"]')`, `locator('[data-testid="…"]')`, or equivalent) referencing the old prefix and confirmed there are none:

- The in-repo Playwright suite (`artifacts/syrabit/tests/`) selects `data-testid="admin-dashboard"` only — no cron-pill selectors.
- The Cloudflare edge-proxy synthetic probes (`workers/edge-proxy/src/synthetic-probe.ts`, `cf-block-probe.ts`) GET endpoints (`/admin/diagnostics`, public homepage), not DOM testIds.
- Hydration verification scripts (`artifacts/syrabit/scripts/verify-hydration.mjs`) and PageSpeed audit JSON snapshots do not reference cron-pill testIds.
- The only remaining trace is a stale prebuilt chunk in `artifacts/syrabit/dist/assets/AdminHealth-*.js` from before the rename — regenerated on every `pnpm deploy:pages` build, so the next deploy purges it.

(Note: incidental *text* mentions of `trustpilot-cron-*` exist in comments, this Operational Notes section, and the wrapper file's documentation. Those are historical context, not runtime selectors, and do not affect the audit.)

**Backwards-compat alias (Task #843):** `<TrustpilotRefreshCronPill>` also emits a `hidden`/`aria-hidden` sibling block carrying the legacy `trustpilot-cron-{tile,status,pill,run-link,refresh}` testIds. This protects out-of-repo surfaces — an external Playwright suite kept in another repo, a Cloudflare Browser Rendering uptime probe, a Sentry visual-regression baseline, an admin runbook screenshot — that cannot be inspected from this repository. Selector-existence assertions on the old prefix keep passing; visibility-strict assertions (`toBeVisible()`, pixel-diff) are *not* preserved because the alias element is hidden, so any consumer relying on those semantics still needs to migrate. The alias has a delete-by date of **2026-07-24** (90 days from the rename) noted in the wrapper file's comment.

### Vertex AI / Cloudflare AI Gateway credential & probe configuration

**Credential resolution order** (`artifacts/syrabit-backend/vertex_services.py`):

1. `VERTEX_SERVICE_ACCOUNT` — explicit Syrabit-side service-account JSON (highest priority).
2. `GOOGLE_APPLICATION_CREDENTIALS_JSON` — canonical Google env var, also used by other GCP integrations on the box. Added 2026-04-25 so a single Google secret can power both Vertex and any future GCS / Vertex Search / Document AI client without a duplicated `VERTEX_SERVICE_ACCOUNT`.
3. `GEMINI_API_KEY` — accepts either an `AIza…` direct AI Studio key OR a JSON SA blob if someone parked it here historically. Also acts as a runtime rescue when the SA path returns 403 (`_attempt_auth_rescue`).

When all three are absent the module sets `_AUTH_MODE = "disabled"` and emits a single `ERROR` log line listing every accepted source. Set `VERTEX_REQUIRED=1` to make boot hard-fail in that case instead of starting in degraded mode.

**Startup-probe budget** (`artifacts/syrabit-backend/server.py:_vertex_startup_probe`):

- Timeout is configurable via `VERTEX_STARTUP_PROBE_TIMEOUT_S` (default **15s**, was 5s pre-2026-04-25). The legacy 5s budget was insufficient for the cold-start path because `vertex_services.health_check()` does TWO sequential HTTPS calls (embed + generate), each requiring DNS + TLS + (for SA mode) an OAuth2 token exchange against `oauth2.googleapis.com`. A cold container in a region with elevated baseline latency to `*-aiplatform.googleapis.com` regularly exceeded 5s and booted into a permanent `unhealthy` cache state on otherwise-working deploys (root cause discovered in the 2026-04-25 production audit when `/healthz/ai` showed `auth_mode: null`).
- Both failure paths (timeout + generic exception) now look up `_AUTH_MODE` and `_CF_GW_ENABLED` from the `vertex_services` module-level state and forward them into `vertex_health_cache.record(...)`. Without this the cache stayed at `auth_mode: null` on every failure — operators couldn't distinguish a no-credentials deploy from a slow upstream. Both behaviours are pinned by tests in `tests/test_vertex_startup_probe.py::test_timeout_path_captures_auth_mode_and_gateway` and `…::test_exception_path_captures_auth_mode_and_gateway`.