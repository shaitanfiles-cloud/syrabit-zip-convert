# Workspace — Syrabit.ai

## Overview

pnpm workspace monorepo. Primary artifact: **Syrabit.ai** — AI-powered educational platform for AHSEC Class 11/12 + Degree students in Assam.

### Vertex AI / Gemini Integration (vertex_services.py)
9 AI-powered services all driven by `GEMINI_API_KEY`:
1. **Text Embeddings** (`text-embedding-004`) — semantic topic search
2. **Translation** (Gemini multilingual) — Assamese, Hindi, Bengali, Bodo
3. **Vision Analysis** (Gemini Vision) — thumbnail analysis
4. **Content Enhancer** — improve generated notes/MCQs
5. **Quality Scorer** — score content before publishing
6. **Topic Suggester** — find missing high-value topics
7. **SEO Meta Generator** — title/description/keywords/OG tags
8. **Content Gap Finder** — cross-references searches vs published pages
9. **Long Doc Reader** (Gemini 1.5 Pro 1M ctx) — extract from AHSEC PDFs

Admin endpoints: `/api/admin/vertex/*`
Frontend panel: Admin → Gemini AI Studio (sidebar)
CMS Editor: Translate button + AI Write (Gemini palette) in toolbar

## Admin Panel — Upgrade Wave (All 12 + 5 Quick Wins COMPLETE)

| # | Feature | Component | Status |
|---|---------|-----------|--------|
| T001 | Internal Linking Engine | AdminSeoManager → "🔗 Int. Links" tab | ✅ Done |
| T002 | Quality Gate in Content Studio | AdminContentStudio → auto-score + warning banner | ✅ Done |
| T003 | FAQ Auto-Extractor | AdminConversations → Extract FAQs button | ✅ Done |
| T004 | Conversion Funnel + Drop-Off Rates | AdminMonetization → Funnel tab | ✅ Done |
| T005 | PDF-to-Syllabus Importer | AdminSyllabusManager → PDF Import panel | ✅ Done |
| T006 | Schema.org Auto-Injection | AdminSeoManager → "🧬 Schema" tab | ✅ Done |
| T007 | Inline Gemini Writing (AI Palette) | AdminCmsDocEditor → AI Write toolbar button + palette | ✅ Done |
| T008 | Dashboard Content Pipeline Tracker | AdminDashboard → Pipeline widget | ✅ Done |
| T009 | Page-Level Conversion Tracker | AdminAnalytics → "📄 Page Conversions" tab | ✅ Done |
| T010 | Churn Risk Scoring | AdminUsers → Risk badge on user rows | ✅ Done |
| T011 | LLM Cost Tracker | AdminHealth → "💸 LLM Costs" tab | ✅ Done |
| T012 | Notification Trigger Builder | AdminNotifications → Rule editor | ✅ Done |
| T013 | Sitemap Validator | AdminSeoManager → "🗺 Sitemap" tab | ✅ Done |

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)

## Structure

```text
artifacts-monorepo/
├── artifacts/              # Deployable applications
│   └── api-server/         # Express API server
├── lib/                    # Shared libraries
│   ├── api-spec/           # OpenAPI spec + Orval codegen config
│   ├── api-client-react/   # Generated React Query hooks
│   ├── api-zod/            # Generated Zod schemas from OpenAPI
│   └── db/                 # Drizzle ORM schema + DB connection
├── scripts/                # Utility scripts (single workspace package)
│   └── src/                # Individual .ts scripts, run via `pnpm --filter @workspace/scripts run <script>`
├── pnpm-workspace.yaml     # pnpm workspace (artifacts/*, lib/*, lib/integrations/*, scripts)
├── tsconfig.base.json      # Shared TS options (composite, bundler resolution, es2022)
├── tsconfig.json           # Root TS project references
└── package.json            # Root package with hoisted devDeps
```

## TypeScript & Composite Projects

Every package extends `tsconfig.base.json` which sets `composite: true`. The root `tsconfig.json` lists all packages as project references. This means:

- **Always typecheck from the root** — run `pnpm run typecheck` (which runs `tsc --build --emitDeclarationOnly`). This builds the full dependency graph so that cross-package imports resolve correctly. Running `tsc` inside a single package will fail if its dependencies haven't been built yet.
- **`emitDeclarationOnly`** — we only emit `.d.ts` files during typecheck; actual JS bundling is handled by esbuild/tsx/vite...etc, not `tsc`.
- **Project references** — when package A depends on package B, A's `tsconfig.json` must list B in its `references` array. `tsc --build` uses this to determine build order and skip up-to-date packages.

## Root Scripts

- `pnpm run build` — runs `typecheck` first, then recursively runs `build` in all packages that define it
- `pnpm run typecheck` — runs `tsc --build --emitDeclarationOnly` using project references

## Packages

### `artifacts/api-server` (`@workspace/api-server`)

Express 5 API server. Routes live in `src/routes/` and use `@workspace/api-zod` for request and response validation and `@workspace/db` for persistence.

- Entry: `src/index.ts` — reads `PORT`, starts Express
- App setup: `src/app.ts` — mounts CORS, JSON/urlencoded parsing, routes at `/api`
- Routes: `src/routes/index.ts` mounts sub-routers; `src/routes/health.ts` exposes `GET /health` (full path: `/api/health`)
- Depends on: `@workspace/db`, `@workspace/api-zod`
- `pnpm --filter @workspace/api-server run dev` — run the dev server
- `pnpm --filter @workspace/api-server run build` — production esbuild bundle (`dist/index.cjs`)
- Build bundles an allowlist of deps (express, cors, pg, drizzle-orm, zod, etc.) and externalizes the rest

### `lib/db` (`@workspace/db`)

Database layer using Drizzle ORM with PostgreSQL. Exports a Drizzle client instance and schema models.

- `src/index.ts` — creates a `Pool` + Drizzle instance, exports schema
- `src/schema/index.ts` — barrel re-export of all models
- `src/schema/<modelname>.ts` — table definitions with `drizzle-zod` insert schemas (no models definitions exist right now)
- `drizzle.config.ts` — Drizzle Kit config (requires `DATABASE_URL`, automatically provided by Replit)
- Exports: `.` (pool, db, schema), `./schema` (schema only)

Production migrations are handled by Replit when publishing. In development, we just use `pnpm --filter @workspace/db run push`, and we fallback to `pnpm --filter @workspace/db run push-force`.

### `lib/api-spec` (`@workspace/api-spec`)

Owns the OpenAPI 3.1 spec (`openapi.yaml`) and the Orval config (`orval.config.ts`). Running codegen produces output into two sibling packages:

1. `lib/api-client-react/src/generated/` — React Query hooks + fetch client
2. `lib/api-zod/src/generated/` — Zod schemas

Run codegen: `pnpm --filter @workspace/api-spec run codegen`

### `lib/api-zod` (`@workspace/api-zod`)

Generated Zod schemas from the OpenAPI spec (e.g. `HealthCheckResponse`). Used by `api-server` for response validation.

### `lib/api-client-react` (`@workspace/api-client-react`)

Generated React Query hooks and fetch client from the OpenAPI spec (e.g. `useHealthCheck`, `healthCheck`).

### `artifacts/syrabit` (`@workspace/syrabit`) + `artifacts/syrabit-backend`

**Syrabit.ai** — AI-powered educational platform for AHSEC Class 11/12 and Degree students in Assam, India.

- **Scope**: 2 boards — AHSEC (HS 1st & 2nd Year) + DEGREE (2nd & 4th Sem)
- **Content**: 14 streams, **55 subjects** with chapter-level RAG chunks
- **AHSEC streams**: Science (PCM), Science (PCB), Arts, Commerce — for both HS 1st and 2nd Year
- **DEGREE streams**: B.Com, B.A, B.Sc — for 2nd Sem and 4th Sem
- **Chapter ID scheme**: DEGREE uses `ch_1..ch_N`, AHSEC uses `ach_5000..ach_N` (avoids collision)
- **Frontend**: React + Vite (JSX files, `.jsx` extension required), React Router, Tailwind CSS
- **Backend**: FastAPI (`server.py`) at port 8000; `emergentintegrations/` is a local module
- **Databases**: PostgreSQL (users/auth), Supabase (mirror), MongoDB `test_database` (content/RAG)
- **Auth**: `syrabit_session` httpOnly cookie OR Bearer token; admin uses `syrabit_admin_session`; admin credentials in `ADMIN_EMAILS`/`ADMIN_PASSWORDS`/`ADMIN_NAMES` env vars
- **Caches**: `_user_cache` (120s), `_conv_cache` (60s), `_rag_cache` (600s), `_ai_response_cache` (1h), `_syllabus_cache` (30min)
- **LLM SLM Pool (6 slots)**: gemini-2.5-flash-preview-05-20 (c6, PRIMARY), Gemini 2.0-flash (c6), Gemini flash-lite (c8), Groq llama-3.3-70b (c8), Groq llama-3.1-8b (c4), Fireworks deepseek-v3p2 (c8) — Bedrock skipped (no AWS creds)
- **Temperature**: ALL providers locked at 0.05 (deterministic, grounding-only mode) — `_stream_gemini`, `_stream_xai`, `_stream_bedrock`, `_call_sarvam_llm`
- **RAG**: 4-way parallel search — keyword chunks + chapter keyword + subject keyword + **vector cosine similarity** (`vector_rag_search`)
  - Chunk scoring: +5/match, chapter keyword +3, subject keyword +1, exact name +8
  - Vector tier: `embed_text(query, task_type="RETRIEVAL_QUERY")` → cosine similarity vs stored page/chapter embeddings → top-12 by score
  - Grounding now includes `[PAGE: slug]` citation headers on each vector hit block
- **Vector RAG pipeline**: `vector_rag_search()` in `server.py` — embeds query, fetches up to 200 seo_pages + 100 chapters with embeddings, ranks by `cosine_similarity`, returns top-12
- **Embed-on-publish**: `_embed_and_store_page()` called as `asyncio.create_task()` (non-blocking) on every Studio publish — stores 768-dim `embedding` + `embedding_model: text-embedding-004` in seo_pages
- **Admin vector endpoints**: `POST /admin/vector/batch-embed` (backfill all un-embedded pages+chapters), `GET /admin/vector/stats` (coverage %)
- **Citation format**: Answers end with `Sources: [PAGE: slug1], [PAGE: slug2]` from grounding slugs; fallback: "Not found in Syrabit library. Based on standard curriculum:"
- **Answer structure (prompts.py)**:
  - Concise mode: Direct Answer → Key Points → Example → Sources
  - Structured mode: Explanation → Key Points → Examples → PYQs Tip → Sources
  - "Not found in Syrabit library" is the explicit fallback (no silent hallucination)
- **Monetization**: Free (30 credits), Starter ₹99/US$1.99 (300 credits), Pro ₹999/US$12.99 (4000 credits) — Razorpay + Stripe dual gateway; webhook handlers at `/api/webhooks/razorpay` and `/api/webhooks/stripe`; credit top-up (100/500/1000); usage tracking at `/api/usage/me`
- **Email**: Resend API for password reset; set `RESEND_API_KEY`, `EMAIL_FROM`, `FRONTEND_URL` in env; falls back to log-only when key missing
- **Security**: ASGI-native `SecurityHeadersMiddleware` (not BaseHTTPMiddleware); HSTS, CSP, X-Frame-Options headers
- **Admin Panel (20 sections)**: Dashboard (live health + latency), Roadmap, Syllabus, Content Editor, **Content Studio** (AI parse/publish), SEO Manager, QA Review, **Automation** (content gap detection + auto-generate), Users, Conversations, Analytics (funnel/heatmap tabs), **Monetization** (revenue analytics, referral config, pricing), Plans & Credits, Notifications, API Config, Google Auth, Settings, Rate Limits, Activity Log, Health
- **Admin Endpoints (new)**: `/admin/dashboard/metrics`, `/admin/studio/parse`, `/admin/studio/publish`, `/admin/analytics/funnel`, `/admin/analytics/content-heatmap`, `/admin/analytics/revenue`, `/admin/analytics/predictor`, `/admin/automation/insights`, `/admin/automation/auto-generate`, `/admin/monetization/overview`, `/admin/monetization/referrals`, `/admin/monetization/referral-config`
- **Content Editor upgrades**: Chapters now have `slug` (auto-generated from title, unique per subject), `content_type` (notes/pyq/formula/summary/solution/reference); AI Parse button in toolbar sends content to `/admin/studio/parse` for auto-structuring; file attach uploads PDF/TXT/MD to chapters with text extraction and auto-rechunking; per-chapter stats panel shows chunk count, content length, slug status, and attached files; API endpoints: `GET /admin/content/chapters/{id}/stats`, `POST /admin/content/chapters/{id}/attach-file`
- **WordPress-parity admin upgrades (T001–T004)**:
  - `SharedMdxEditor.jsx` — forwardRef MDXEditor with `getMarkdown()`/`insertText()` + TEMPLATES re-export (from `src/utils/editorTemplates.js`)
  - `AdminContentEditor` — "Publish as Blog" button on subject cards (POST merge → `syrabit_cms_prefill` localStorage → navigate to CMS); inline MDXEditor (directly imported, no wrapper, avoids duplicate-React error); split blog-preview pane; Template Library shortcode row; bulk-select checkboxes + bulk merge action bar; Workflow Tracker strip (Chapters → Merged → Published)
  - `AdminCmsDocEditor` — full WordPress/Gutenberg-parity CMS editor: left-panel type filter (All/Live/Draft/Syllabus/Revisions); toolbar with Live Preview split-pane toggle (iframe → `/learn/{slug}`), Save as Revision button (`POST /admin/content/cms-documents/{id}/revisions`), Hand Off to Content Editor (seeds `syrabit_content_prefill` localStorage → navigates to content tab), Publish/Unpublish toggle; Content tab: 7 template insert buttons incl. Syllabus Intro + Chapter Link, expandable Insert Syllabus picker (cascading Board→Class→Stream→Subject fetched from public content API, inserts syllabus block into editor); SEO tab: Google SERP preview + Perplexity AI citation simulator (dark card with [1] badge), Canonical URL display with copy button, Auto-fill primary keyword (Zap button), 160-char meta progress bar; GEO tab: Link to Syllabus Scope picker (cascading selectors, calls `POST /admin/content/cms-documents/{id}/link-syllabus` to resolve names + set canonical_url + geo_tags), Auto-extract authority phrases, live GEO URL preview, preset quick-links; reads `syrabit_cms_prefill` localStorage prefill on mount (10-min expiry)
  - `AdminContentStudio` — full Studio→CMS→library pipeline: Board/Class dropdowns (dynamic, from `/api/content/boards` + `/api/content/classes`) → sets publish path `/{board_slug}/{class_slug}/{subject_slug}/{chapter_slug}`; "Load Subject Syllabus" picker (Board+Class+Stream+Subject cascade → fetches `/api/syllabi/…` → inserts `type:"syllabus"` block at position 0); Editor tab: raw text → `POST /admin/studio/parse` (GEO-aware LLM prompt with board exam citations + FAQ blocks) → typed block cards (summary/definition/example/pyq/formula/note/faq/syllabus) with inline edit+remove; Preview tab: live `/learn/{slug}` iframe + Google SERP card + Perplexity AI citation card + meta description editor with auto-fill-from-block; Gap Fill tab: subjects with <3 chapters grid, per-subject checkboxes for bulk select → Bulk Auto-Gen (parallel `Promise.allSettled` with syllabus context injection + progress bar), Load Editor, Auto-Gen (synthetic prompt → parse → chapter upsert), Merge to CMS Blog (→ localStorage prefill → navigate cms); Publish Pipeline: computed URL preview, Publish Page, Publish Revision (dated `seo_pages` revision with `parent_revision_id`), Save/Update Draft (`POST /admin/studio/drafts`); Drafts panel in header shows saved drafts → Load back into editor; backend auto-creates CMS syllabus stub in `cms_documents` when publish detects a `type:"syllabus"` block
  - MDX dark CSS moved to `src/index.css` (globally available, no per-component `<style>` injection needed)
- **Payment workflow**: Razorpay (INR) + Stripe (USD) dual gateway; server-side order validation (amount, plan/credits, user ownership) in both verify endpoints; HMAC signature verification; idempotency via `razorpay_payment_id`/`stripe_session_id` unique indexes; session cache invalidation after payment; credit top-up flow (100/500/1000 packs) with dedicated create+verify endpoints; Stripe checkout redirects to `/payment/success` and `/payment/cancel` pages; `get_user_credits` uses actual DB `credits_limit` (supports top-ups + admin adjustments)
- **Payment endpoints**: `POST /payments/create-order`, `POST /payments/verify`, `POST /payments/stripe/create-checkout`, `POST /payments/credit-topup`, `POST /payments/credit-topup/verify`, `POST /webhooks/razorpay`, `POST /webhooks/stripe`
- **Admin**: `ADMIN_EMAILS=admin@syrabit.ai`; watchfiles watches `/artifacts/syrabit` — server.py edits require workflow restart
- **Form accessibility**: All inputs have proper `autocomplete` attributes (email, current-password, new-password, name)
- **SEO & GEO**: `seo_engine.py` handles SEO routes; bot-readable HTML endpoints at `/api/seo/html/{board}/{class}/{subject}/{topic}` serve pre-rendered HTML with JSON-LD (Article, Course, BreadcrumbList, FAQPage), Dublin Core, and citation meta tags; `robots.txt` allows all major AI crawlers; sitemap includes both SPA and HTML bot URLs; `llms.txt` endpoint at `/api/llms.txt` describes site structure for LLM crawlers
- **GEO (Generative Engine Optimization)**: Syllabi have `geo_phrases` field (authority phrases injected into AI answers); SEO prompts include FAQ sections, AHSEC exam year citations, and NCERT/SCERT references; automation auto-generate attaches `geo_meta` with suggested GEO sections; studio/parse prompt generates FAQ blocks and board exam frequency citations; chunks store `syllabus_id` and `geo_tags` metadata
- **Mobile Responsiveness (COMPLETE)**: Full mobile-first responsive layout across all breakpoints:
  - `AppLayout` main uses `.app-main-scroll` CSS class — adds `max(4rem, calc(4rem + env(safe-area-inset-bottom, 0px)))` bottom padding on mobile (0 on md+)
  - `BottomNav` has `paddingBottom: env(safe-area-inset-bottom, 0px)` for iPhone home-indicator clearance
  - `ChatPage` uses `.chat-viewport-height` CSS class with `100svh` (dynamic viewport units for iOS Safari toolbar) and safe-area inset bottom
  - `HistoryPage` `⋯` action button: `opacity-100 md:opacity-0 md:group-hover:opacity-100` — always visible on touch, hover-only on desktop
  - `SubjectPage` article padding: `clamp(1.25rem, 5vw, 2.5rem)` — responsive, not hardcoded
  - `LibraryPage` masonry helper `.masonry-grid-mobile` added to `index.css`; card grid already responsive
  - CSS helpers in `src/index.css`: `.app-main-scroll`, `.chat-viewport-height` use `@media` breakpoints + CSS env() for iOS safe area
- **Library Page**: Browser-window style subject cards with colored dots + monospace URL bar, always-visible chapter lesson links (up to 6), Ask AI / Save / Browse action buttons, 3-column grid; Board/Class dropdown filters + dynamic stream chips; search autocomplete across name/tags/class/stream/board
- **Subject Landing Page**: `/:board/:classSlug/:subjectSlug` shows all chapters with search, topic chips, AI CTA; uses `resolve-subject` endpoint (no stream_slug needed)
- **Lesson Pages (SeoTopicPage)**: Blog-style layout with reading progress bar, sticky sidebar TOC on xl screens (IntersectionObserver active-heading tracking), mobile collapsible TOC, improved typography (`text-[15px] leading-[1.8]`); breadcrumb, content type tabs, related topics, prev/next navigation; fallback to chapter content when no SEO page exists
- **Content Fallback**: `GET /content/chapter-by-slug/{board}/{class}/{subject}/{chapter}` resolves chapters by slug or auto-generated slug from title; returns assembled chunk content with `is_fallback: true` flag; chapters without explicit slugs get auto-generated slugs from title (via regex slugify)
- **Token spend tracking**: `record_llm_cost()` called in both `chat` and `chat_stream` endpoints (~4 chars/token estimation; provider hardcoded to `"gemini"`, refine later to detect actual slot)
- **RAG latency tracking**: `rag_search()` uses `_rag_t0 = time.time()` at function entry; `_record_rag_event(quality, round((time.time()-_rag_t0)*1000,1), query)` on cache-miss exit — actual ms now recorded instead of hardcoded 0
- **Admin dashboard auth**: `/admin/dashboard/metrics` uses `adminHdr(adminToken)` (JWT Bearer) — fixed from bare `headers` (withCredentials-only) which caused 401 when cookie not set
- **Dashboard UX fixes**: Latency bar threshold 100ms→300ms (remote APIs); MRR formatted with `Math.round().toLocaleString('en-IN')`; alert states distinguish API failure (yellow) from data alerts; fallback rate shows "Could not load" on error vs "no data" on empty; vector coverage widget shows VERTEX_SERVICE_ACCOUNT guidance when 0 items embedded
- **Testing**: pytest suite in `tests/` (17 tests: health, auth, API, security headers); run `cd artifacts/syrabit-backend && python3 -m pytest tests/ -v`
- **Docker**: `Dockerfile` (Python 3.11-slim, non-root user, healthcheck) + `docker-compose.yml` with resource limits
- **Endpoints**: 139 API endpoints total (as of Phase 8 completion)
- **Deployment**: Root `pyproject.toml` and `uv.lock` removed entirely to prevent platform auto-detection from running `uv sync`; Python deps installed via `PIP_USER=0 pip3 install --target=.python-deps` (avoids Nix pip `user=yes` config that breaks virtualenvs); run uses `PYTHONPATH=.python-deps`; `path-to-regexp` pinned to 8.4.0 via pnpm override

### `scripts` (`@workspace/scripts`)

Utility scripts package. Each script is a `.ts` file in `src/` with a corresponding npm script in `package.json`. Run scripts via `pnpm --filter @workspace/scripts run <script>`. Scripts can import any workspace package (e.g., `@workspace/db`) by adding it as a dependency in `scripts/package.json`.
