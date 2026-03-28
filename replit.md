# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Each package manages its own dependencies.

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
- **LLM SLM Pool (6 slots)**: Groq llama-3.3-70b (c8, PRIMARY), Groq llama-3.1-8b (c4), Gemini flash-lite (c10), Gemini flash (c5), Fireworks deepseek-v3p2 (c8), Bedrock nova-micro (c2)
- **RAG**: 3-way parallel search; scoring: chunks +5/match, chapter keyword +3, subject keyword +1, exact name +8
- **Monetization**: Free (30 credits), Starter ₹99/US$1.99 (300 credits), Pro ₹999/US$12.99 (4000 credits) — Razorpay + Stripe dual gateway; webhook handlers at `/api/webhooks/razorpay` and `/api/webhooks/stripe`; credit top-up (100/500/1000); usage tracking at `/api/usage/me`
- **Email**: Resend API for password reset; set `RESEND_API_KEY`, `EMAIL_FROM`, `FRONTEND_URL` in env; falls back to log-only when key missing
- **Security**: ASGI-native `SecurityHeadersMiddleware` (not BaseHTTPMiddleware); HSTS, CSP, X-Frame-Options headers
- **Admin Panel (20 sections)**: Dashboard (live health + latency), Roadmap, Syllabus, Content Editor, **Content Studio** (AI parse/publish), SEO Manager, QA Review, **Automation** (content gap detection + auto-generate), Users, Conversations, Analytics (funnel/heatmap tabs), **Monetization** (revenue analytics, referral config, pricing), Plans & Credits, Notifications, API Config, Google Auth, Settings, Rate Limits, Activity Log, Health
- **Admin Endpoints (new)**: `/admin/dashboard/metrics`, `/admin/studio/parse`, `/admin/studio/publish`, `/admin/analytics/funnel`, `/admin/analytics/content-heatmap`, `/admin/analytics/revenue`, `/admin/analytics/predictor`, `/admin/automation/insights`, `/admin/automation/auto-generate`, `/admin/monetization/overview`, `/admin/monetization/referrals`, `/admin/monetization/referral-config`
- **Content Editor upgrades**: Chapters now have `slug` (auto-generated from title, unique per subject), `content_type` (notes/pyq/formula/summary/solution/reference); AI Parse button in toolbar sends content to `/admin/studio/parse` for auto-structuring; file attach uploads PDF/TXT/MD to chapters with text extraction and auto-rechunking; per-chapter stats panel shows chunk count, content length, slug status, and attached files; API endpoints: `GET /admin/content/chapters/{id}/stats`, `POST /admin/content/chapters/{id}/attach-file`
- **WordPress-parity admin upgrades (T001–T004)**:
  - `SharedMdxEditor.jsx` — forwardRef MDXEditor with `getMarkdown()`/`insertText()` + TEMPLATES re-export (from `src/utils/editorTemplates.js`)
  - `AdminContentEditor` — "Publish as Blog" button on subject cards (POST merge → `syrabit_cms_prefill` localStorage → navigate to CMS); inline MDXEditor (directly imported, no wrapper, avoids duplicate-React error); split blog-preview pane; Template Library shortcode row; bulk-select checkboxes + bulk merge action bar; Workflow Tracker strip (Chapters → Merged → Published)
  - `AdminCmsDocEditor` — reads `syrabit_cms_prefill` localStorage prefill on mount (10-min expiry, auto-populates title/content/slug/meta); Google Snippet Preview in SEO tab (live title/URL/meta with 160-char progress bar); template shortcode insert buttons
  - `AdminContentStudio` — Gap Fill Mode tab (subjects with <3 chapters → Load in Editor or Auto-Generate); Auto-Publish Pipeline (Merge to Blog button when subject has a linked blog doc)
  - MDX dark CSS moved to `src/index.css` (globally available, no per-component `<style>` injection needed)
- **Payment workflow**: Razorpay (INR) + Stripe (USD) dual gateway; server-side order validation (amount, plan/credits, user ownership) in both verify endpoints; HMAC signature verification; idempotency via `razorpay_payment_id`/`stripe_session_id` unique indexes; session cache invalidation after payment; credit top-up flow (100/500/1000 packs) with dedicated create+verify endpoints; Stripe checkout redirects to `/payment/success` and `/payment/cancel` pages; `get_user_credits` uses actual DB `credits_limit` (supports top-ups + admin adjustments)
- **Payment endpoints**: `POST /payments/create-order`, `POST /payments/verify`, `POST /payments/stripe/create-checkout`, `POST /payments/credit-topup`, `POST /payments/credit-topup/verify`, `POST /webhooks/razorpay`, `POST /webhooks/stripe`
- **Admin**: `ADMIN_EMAILS=admin@syrabit.ai`; watchfiles watches `/artifacts/syrabit` — server.py edits require workflow restart
- **Form accessibility**: All inputs have proper `autocomplete` attributes (email, current-password, new-password, name)
- **SEO & GEO**: `seo_engine.py` handles SEO routes; bot-readable HTML endpoints at `/api/seo/html/{board}/{class}/{subject}/{topic}` serve pre-rendered HTML with JSON-LD (Article, Course, BreadcrumbList, FAQPage), Dublin Core, and citation meta tags; `robots.txt` allows all major AI crawlers; sitemap includes both SPA and HTML bot URLs; `llms.txt` endpoint at `/api/llms.txt` describes site structure for LLM crawlers
- **GEO (Generative Engine Optimization)**: Syllabi have `geo_phrases` field (authority phrases injected into AI answers); SEO prompts include FAQ sections, AHSEC exam year citations, and NCERT/SCERT references; automation auto-generate attaches `geo_meta` with suggested GEO sections; studio/parse prompt generates FAQ blocks and board exam frequency citations; chunks store `syllabus_id` and `geo_tags` metadata
- **Library Page**: Browser-window style subject cards with colored dots + monospace URL bar, always-visible chapter lesson links (up to 6), Ask AI / Save / Browse action buttons, 3-column grid; Board/Class dropdown filters + dynamic stream chips; search autocomplete across name/tags/class/stream/board
- **Subject Landing Page**: `/:board/:classSlug/:subjectSlug` shows all chapters with search, topic chips, AI CTA; uses `resolve-subject` endpoint (no stream_slug needed)
- **Lesson Pages (SeoTopicPage)**: Blog-style layout with reading progress bar, sticky sidebar TOC on xl screens (IntersectionObserver active-heading tracking), mobile collapsible TOC, improved typography (`text-[15px] leading-[1.8]`); breadcrumb, content type tabs, related topics, prev/next navigation; fallback to chapter content when no SEO page exists
- **Content Fallback**: `GET /content/chapter-by-slug/{board}/{class}/{subject}/{chapter}` resolves chapters by slug or auto-generated slug from title; returns assembled chunk content with `is_fallback: true` flag; chapters without explicit slugs get auto-generated slugs from title (via regex slugify)
- **Testing**: pytest suite in `tests/` (17 tests: health, auth, API, security headers); run `cd artifacts/syrabit-backend && python3 -m pytest tests/ -v`
- **Docker**: `Dockerfile` (Python 3.11-slim, non-root user, healthcheck) + `docker-compose.yml` with resource limits
- **Endpoints**: 139 API endpoints total (as of Phase 8 completion)
- **Deployment**: Root `pyproject.toml` and `uv.lock` removed entirely to prevent platform auto-detection from running `uv sync`; Python deps installed via `PIP_USER=0 pip3 install --target=.python-deps` (avoids Nix pip `user=yes` config that breaks virtualenvs); run uses `PYTHONPATH=.python-deps`; `path-to-regexp` pinned to 8.4.0 via pnpm override

### `scripts` (`@workspace/scripts`)

Utility scripts package. Each script is a `.ts` file in `src/` with a corresponding npm script in `package.json`. Run scripts via `pnpm --filter @workspace/scripts run <script>`. Scripts can import any workspace package (e.g., `@workspace/db`) by adding it as a dependency in `scripts/package.json`.
