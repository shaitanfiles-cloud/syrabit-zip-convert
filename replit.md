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

### HTML edge-cache TTL vs trustpilot data freshness (Task #858)

The 1-hour HTML edge cache (`s-maxage=3600` on `/`, `/library`, `/browser`, `/pricing`, `/login`, `/signup`, `/exam-routine`, `/assamboard/*`, `/learn/*`, `/subject/*` in `artifacts/syrabit/public/_headers`) does **not** mask Trustpilot rating updates from end users. Three independent reasons, in order of importance:

1. **The visible Trustpilot widget is client-side fetched, not HTML-embedded.** `artifacts/syrabit/src/components/content/TrustpilotReviewsSection.jsx` calls `fetch(/api/config/trustpilot/aggregate)` from the browser after hydration. That response goes through the worker's API path; the route is **not** in `CACHEABLE_PREFIXES` in `workers/edge-proxy/src/index.ts`, so the worker doesn't cache it either. Freshness is bounded by the backend's in-process cache (`_TP_AGGREGATE_TTL_S`, default 6 h), which the refresh cron resets to age=0 via `POST /api/config/trustpilot/aggregate/refresh`. In a healthy steady state the user sees data at most that TTL old; under upstream Trustpilot failures the backend can serve stale-on-failure beyond that — but neither path routes through the HTML edge cache.

2. **The HTML's only Trustpilot payload is build-time-baked JSON-LD.** `artifacts/syrabit/scripts/inject-trustpilot-jsonld.mjs` runs as a build step (called from `scripts/build.mjs` between prerender and verify) and writes `<script type="application/ld+json" id="trustpilot-aggregaterating-static">` into every `dist/*.html`'s `<head>`. The values come from `artifacts/syrabit/scripts/.trustpilot-aggregate-cache.json`, which is committed to the repo and updated by the GitHub Actions refresh workflow. There is **no runtime path** that re-bakes JSON-LD into already-deployed HTML — the only way the JSON-LD changes is a fresh `pnpm deploy:pages` build, and Cloudflare Pages purges its own cache on every successful deploy.

3. **The actual Trustpilot refresh cron is daily.** `.github/workflows/trustpilot-aggregate-refresh.yml` runs at `30 4 * * *` (04:30 UTC daily) — not every 1 min / 6 h as the task description stated. The 1-min cadence in the task description matches the AdminHealth dashboard's `<CronHealthPill>` polling interval, but that pill only renders on `/admin/health` (not in `_headers`, not edge-cached). The 6-h cadence in the task description matches the worker's D1 content sync schedule (`crons = ["* * * * *", "0 */6 * * *"]` in `wrangler.toml`), which is unrelated to Trustpilot. Neither has anything to do with the public HTML cache.

Net effect: no actual misalignment exists, so neither lowering `s-maxage` (Option A) nor adding `Cache-Tag: trustpilot-pill` + cron-triggered purge-by-tag (Option B) was implemented. If a future change starts injecting Trustpilot data into HTML at request time (e.g. an SSR rewrite of the rating block), revisit Option B at that point — `CF_ZONE_ID` and `CLOUDFLARE_API_TOKEN` are already in env, so the wiring cost would be ~30 lines added to `routes/config.py::refresh_trustpilot_aggregate` (the `POST /api/config/trustpilot/aggregate/refresh` handler) plus a `Cache-Tag` header from the worker's HTML response path.

### OpenAPI schema is suppressed in prod by design (Task #857)

`/openapi.json` and `/docs` are intentionally NOT reachable from the public internet on `api.syrabit.ai` or directly on the Railway origin. Two stacked gates enforce this: (1) `OriginSharedSecretMiddleware` (`artifacts/syrabit-backend/middleware.py:79-93`) excludes `/openapi.json` + `/docs` from `_ORIGIN_AUTH_OPEN_PATHS`, so the Railway hostname returns `403 {"detail": "Direct origin access denied — must traverse the edge worker."}` for those paths even when traffic carries a valid UA; (2) the Cloudflare edge worker (`workers/edge-proxy/src/index.ts`) only proxies `/api/*` paths to the backend — `/openapi.json` falls through to PAGES_ORIGIN and serves the SPA HTML 200, so the schema is invisible from `api.syrabit.ai/openapi.json` too. Rationale: exposing every route shape is a low-cost reconnaissance vector, and we have no public SDK consumer that needs the live schema. To re-enable for a one-off (e.g. regenerating an internal client): add `/openapi.json` to `_ORIGIN_AUTH_OPEN_PATHS`, redeploy backend, then `curl https://<current-railway-backend-hostname>/openapi.json` (still gated by Railway-edge IP allowlist + Cloudflare WAF). The current hostname lives in `workers/edge-proxy/wrangler.toml` as the `BACKEND_URL` binding (or via `pnpm run railway:status`). Revert the middleware change after the regen run.

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

### Wrangler v4 in workers/edge-proxy (Task #859)

`workers/edge-proxy/package.json` was bumped from `wrangler ^3.99.0` (was running 3.114.17) to `wrangler ^4.0.0` (resolves to 4.85.0 today). The companion `@cloudflare/workers-types` was bumped from `^4.20241205.0` to `^4.20260424.1` to satisfy v4's tightened peer range. **No `wrangler.toml` schema changes were required** — the file already conformed to v4 conventions: no `[assets]` block (so the v4 schema tightening is a non-issue), no `--node-compat` CLI flag, and the four bindings (`RATE_LIMIT` KV, `BOT_HTML_CACHE` KV, `CONTENT_DB` D1, `AI`) all use the v4-accepted standard format. Validation evidence: `tsc --noEmit` clean, `vitest run` green (156/156), `wrangler deploy --dry-run` lists all four bindings + 2 vars with no schema warnings, `wrangler dev` boots cleanly with all bindings (KV/D1 local-emulated, AI remote — same as v3 behaviour). Two informational warnings during `wrangler dev` are unchanged from v3 and are intentional: (a) cron triggers are not auto-fired in local dev (manually invoke via `curl http://127.0.0.1:8787/cdn-cgi/handler/scheduled`), and (b) the AI binding always hits remote even in local dev, which can incur charges — silence by adding `remote = true` under `[ai]` in `wrangler.toml` if desired (we don't, because the warning is the desired feedback).

**Rollback procedure if a v4 deploy misbehaves in production:**

1. **Fast revert (preferred, no rebuild):** `cd workers/edge-proxy && wrangler rollback` — Cloudflare keeps the previous version of every Worker deploy and `rollback` re-points the route at the prior version-id in seconds. Confirm with `wrangler deployments list`. **Note (Task #878):** the wall-clock duration of this rollback has not yet been measured against prod from a real workstation — Task #871 explicitly deferred the live `wrangler rollback` drill (and Task #878 chose not to rehearse it) because flipping the prod version-id from Replit unattended is the wrong place to learn the timing. The "in seconds" qualifier above is Cloudflare's documented behaviour and matches every dev-env rollback we've observed, but if an incident-grade SLA number is needed, run the four-step drill below from a workstation with deploy creds and replace this paragraph with the measured times. Drill: (a) `wrangler deployments list` to confirm the active version-id, (b) `time wrangler rollback <prior-version-id>` and `curl https://api.syrabit.ai/api/health` (expect 200), (c) `time wrangler rollback <restore-version-id>` and re-curl `/api/health` to restore. As of 2026-04-25, the relevant version-ids are `7d3786ee-1b73-4cc6-b848-88703fee0e51` (current, Wrangler v4-built, deployed during Task #871) and `6230eb9b-2d0f-45da-9b98-089c61482a41` (prior, deployed 2026-04-24 18:12 UTC) — but always re-check `wrangler deployments list` first because newer deploys shift the "prior" target.
2. **Source-level revert (if rollback is not enough):** revert this commit (`git revert <sha>`), `pnpm --filter syrabit-edge install` (re-resolves to wrangler 3.114.x), then `wrangler deploy` from `workers/edge-proxy`. The pnpm-lock change is the only artefact — no `wrangler.toml` was modified, so a downgrade does not require config edits.
3. **Smoke checks after rollback:** `curl https://api.syrabit.ai/api/health` (200), `curl -I https://syrabit.ai/` (Worker hits PAGES_ORIGIN), and tail `wrangler tail` for ~2 min to confirm no spike in 5xx/exception-class log lines. If the issue was binding-shaped, also `wrangler kv key list --binding=RATE_LIMIT --preview false | head` to confirm KV reads work.

**Promote workflow (Task #875 — CI-driven; was four manual steps in Task #872 + #873):** the preview deploy + smoke and the prod promote are now wired into `.github/workflows/edge-proxy-deploy.yml` so an operator no longer has to remember step 3 of a four-step runbook. Default flow:

1. **Push to `master` (or `main`) with any change under `workers/edge-proxy/**`.** This triggers the `edge-proxy-deploy` workflow.
2. **CI runs `deploy-preview` then `smoke-preview` automatically.** `deploy-preview` runs `pnpm --filter syrabit-edge run deploy:preview` against `syrabit-edge-preview.<account>.workers.dev` using the `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` repo secrets. `smoke-preview` then runs `pnpm --filter syrabit-edge run smoke -- <preview-url>` (the URL is built from the `CF_WORKERS_SUBDOMAIN` repo variable, falling back to `wrangler deployments list --env preview`). The smoke step exports `D1_SYNC_SECRET` and `AI_FALLBACK_SECRET` (preview-env values) from repo secrets so all five binding checks run, not just the three that work secret-less; the script's final pass/fail line is mirrored into the run summary via `::notice::`. A red smoke aborts the pipeline before prod is touched.
3. **Approve the `production` environment in GitHub Actions to promote.** The third job (`deploy-prod`) is pinned to a `production` GitHub environment with required reviewers, so GitHub blocks the live `wrangler deploy` (no `--env`, lands on `syrabit.ai/*`) until a human clicks Approve. Once approved, prod ships and the job emits a reminder to tail with `wrangler tail --format=pretty` for ~10 min per the Task #859 spec. Rollback per the procedure above (`wrangler rollback` for prod, `wrangler rollback --env preview` for preview — the two envs keep independent version histories).

**Required GitHub config** (one-time, see comment block at the top of `.github/workflows/edge-proxy-deploy.yml` for the exact scope strings): repo secrets `CLOUDFLARE_API_TOKEN` (Workers Scripts:Edit + Workers KV Storage:Edit + D1:Edit), `CLOUDFLARE_ACCOUNT_ID`, `D1_SYNC_SECRET` (preview value), `AI_FALLBACK_SECRET` (preview value); repo variable `CF_WORKERS_SUBDOMAIN`; environment `production` with required reviewers configured.

**Documented manual fallback** (use only when CI is unavailable, e.g. an emergency cherry-pick from a non-default branch or a credential outage on the GitHub side): the four scripts in `workers/edge-proxy/package.json` are still wired and documented:

1. `pnpm --filter syrabit-edge run deploy:preview:dry` — schema check the preview env (no upload, no API call).
2. `pnpm --filter syrabit-edge run deploy:preview` — publish to `syrabit-edge-preview.<account>.workers.dev` (separate Worker, no `syrabit.ai/*` routes, crons cleared, KV/D1 bindings isolated to the preview-tier IDs lifted from the prior `preview_id` fields).
3. Smoke-test the preview hostname with `pnpm --filter syrabit-edge run smoke:preview` (Task #873). The wrapper resolves the preview URL automatically — first from `$EDGE_PREVIEW_URL` if set, else `https://syrabit-edge-preview.${CF_WORKERS_SUBDOMAIN}.workers.dev`, else by parsing `wrangler deployments list --env preview` — so step 2 → step 3 is a one-liner instead of "remember the workers.dev subdomain". Underneath it calls `scripts/smoke-test.sh`, which exercises every binding declared in `wrangler.toml`: `/api/health` (worker up + CONTENT_DB binding state), `/api/edge/kv-usage` (enumerates RATE_LIMIT + BOT_HTML_CACHE — gated by `D1_SYNC_SECRET`, set the env var with the same value before running for full coverage), `/api/content/subjects` (D1 read with row-count assertion), a 130-request burst against `/api/content/boards` (expects 429 at #121, proves RATE_LIMIT KV is counting), the `/api/ai/fallback/chat` gate (set `AI_FALLBACK_SECRET` to upgrade from gate-only to Workers-AI-end-to-end), and a two-call Googlebot flow on `/` that asserts warm BOT_HTML_CACHE (`X-Source: bot-cache`) on the second call when run from a verified CF/Google source IP — degrades to an INFO note (not a failure) on a non-CF caller because the worker filters spoofed bot UAs before the KV lookup; the binding is still verified by the `kv-usage` step in that case. Set per-env secrets on the worker first if missing — `wrangler secret put D1_SYNC_SECRET --env preview` etc., per the comment block in `workers/edge-proxy/wrangler.toml` § `[env.preview]`. The script exits non-zero on the first failure. Manual override: `pnpm --filter syrabit-edge run smoke -- <url>` is still available for ad-hoc targets.
4. `pnpm --filter syrabit-edge run deploy` — promote to prod (no `--env`, lands on the live routes), then `wrangler tail --format=pretty` for 10 min per the task #859 spec. Rollback per the procedure above (`wrangler rollback` for prod, `wrangler rollback --env preview` for preview — the two envs keep independent version histories).

The preview Worker is bound to a dedicated D1 (`syrabit-content-preview`, id `35e59391-218e-4e94-bbf5-972baa0d0b30`, provisioned in Task #874 and migrated from the same `workers/edge-proxy/migrations/` directory as prod) so that `POST /api/d1/sync` and any future D1 write path can be exercised end-to-end on preview without risk of polluting the prod `syrabit-content` database. KV bindings use the previously-unused `preview_id` namespaces (physically separate from prod KV, so preview rate-limit / BOT_HTML_CACHE writes cannot pollute prod state). Crons are explicitly disabled on preview (`[env.preview.triggers] crons = []`) so the synthetic probe and 6-hourly D1 sync only run from prod.

**Preview D1 auto-populate (Task #879):** the Railway-side `d1_sync.py` now fans every sync (CRUD-driven, manual `POST /api/admin/d1-sync`, or 6-hourly worker cron) out to BOTH the prod and the preview Workers in parallel, so preview boots with a fresh mirror of prod content after each deploy. To enable, set both `EDGE_WORKER_PREVIEW_URL=https://syrabit-edge-preview.<account>.workers.dev` and `D1_SYNC_SECRET_PREVIEW=<value>` on the Railway service (where the secret matches `wrangler secret put D1_SYNC_SECRET --env preview`); leave either blank to disable. Preview-target failures are logged but never block prod (best-effort by design). The smoke test `pnpm --filter syrabit-edge run smoke:preview` now includes `[3b/7] d1-counts` which calls `/api/edge/d1-status` and asserts non-zero rows for boards/subjects/chapters — a red `[d1-counts]` is the canonical signal that the fan-out broke. Full on-call procedure (cadence, secret rotation, manual replay) lives in `artifacts/syrabit-backend/docs/D1_PREVIEW_BACKFILL.md`.

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