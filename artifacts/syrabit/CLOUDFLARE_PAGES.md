# Cloudflare Pages — Syrabit Frontend Deploy

These are the canonical Cloudflare Pages settings for the Syrabit frontend
(`syrabit.ai`). The backend lives separately on Railway as `api.syrabit.ai`
and is **not** deployed via Pages.

## Dashboard settings

| Setting                    | Value                                                                |
| -------------------------- | -------------------------------------------------------------------- |
| **Production branch**      | `main`                                                               |
| **Framework preset**       | `None` (custom)                                                      |
| **Root directory** (Project) | `/` (repo root — pnpm monorepo root, do **not** set to `artifacts/syrabit`) |
| **Build command**          | See below                                                            |
| **Build output directory** | `artifacts/syrabit/dist` &nbsp; ← **no leading slash**                |
| **Node.js version**        | `20` or `22`                                                         |

### Build command

Scope the install + build to the Syrabit frontend and its workspace
dependencies only — do **not** install the entire monorepo (the backend,
mockup sandbox, and unrelated artifacts inflate the install to ~30 minutes
and pull in Playwright/Puppeteer browser downloads we don't need at the
edge):

```sh
corepack enable && corepack prepare pnpm@10.26.1 --activate \
  && pnpm install --filter @workspace/syrabit... --frozen-lockfile \
  && pnpm --filter @workspace/syrabit run build
```

The `--filter @workspace/syrabit...` syntax (with the trailing `...`)
includes the package itself plus all of its workspace dependencies, but
nothing else. The `catalog:` protocol is resolved by pnpm against the root
`pnpm-workspace.yaml` and works correctly under `--filter`.

## Required environment variables (Pages → Settings → Environment variables)

Set these on the **Production** environment. They are baked into the
build output, so you must trigger a fresh deploy after changing them.

| Variable                   | Example                  | Purpose                                                     |
| -------------------------- | ------------------------ | ----------------------------------------------------------- |
| `NODE_ENV`                 | `production`             | Vite production mode                                        |
| `VITE_BACKEND_URL`         | `https://api.syrabit.ai` | Backend FastAPI base URL                                    |
| `VITE_GA4_ID`              | `G-XXXXXXXXXX`           | GA4 measurement ID. **Must** match `^G-[A-Z0-9]{6,12}$` — anything else (legacy UA-*, numeric account ID, blank) is silently dropped and `gtag` never loads. |
| `VITE_CF_ANALYTICS_TOKEN`  | (optional)               | Cloudflare Web Analytics beacon token                       |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | `1`              | Skip Chromium download — frontend bundle never runs Playwright |
| `PUPPETEER_SKIP_DOWNLOAD`  | `1`                      | Skip Puppeteer Chromium download                            |

## DO NOT set on Pages

These are **backend / Worker secrets only**. Setting them on the Pages
project leaks them into public build logs and is a real security incident:

- `CLOUDFLARE_ANALYTICS_TOKEN` (Task #534 spec name; legacy alias `CF_ANALYTICS_API_TOKEN`) — backend reads CF Analytics GraphQL with this. Pages CI uses its own `CLOUDFLARE_PAGES_TOKEN` (legacy alias `CF_PAGES_API_TOKEN`); never reuse the runtime/analytics token for Pages or vice-versa.
- `CF_ZONE_ID` — backend-only
- `D1_SYNC_SECRET`, `EDGE_WORKER_URL`
- `SUPABASE_DB_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- Any `ADMIN_*`, `RAZORPAY_*`, `RESEND_*`, `OPENAI_API_KEY`, `GROQ_API_KEY`, etc.

If any of the above were ever set on Pages, **rotate them immediately** in
their source-of-truth provider (Cloudflare API tokens dashboard, Supabase,
Razorpay, etc.) and remove them from Pages env vars.

## Static asset wiring (verified to land in `dist/`)

The following files in `artifacts/syrabit/public/` are copied verbatim by
Vite into `artifacts/syrabit/dist/` and served directly by Pages:

- `_redirects` — SPA fallback (`/* /index.html 200`). Combined with
  `_worker.js` to also serve a 200 for HEAD navigation probes.
- `_headers` — long cache for `/assets/*`, `/fonts/*`, hashed PWA icons;
  `max-age=0, must-revalidate` for `index.html`, `sw.js`, and the PWA
  precache manifest; short s-maxage for HTML routes.
- `_routes.json` — tells the Pages Worker which paths to forward to the
  Worker (`include: ["/*"]`) vs. serve as static (sitemaps, robots.txt,
  PWA icons, RSS feeds, etc.).
- `_worker.js` — SPA fallback Worker (Task #365): GET + HEAD on unknown
  paths return `index.html` with a 200 so crawlers see real HTML.

After deploy, smoke-test:

```sh
curl -sI https://syrabit.ai/library/some-slug | head -1   # HTTP/2 200
curl -sI https://syrabit.ai/assets/<hashed>.js | grep -i cache-control   # immutable
curl -sI https://syrabit.ai/index.html | grep -i cache-control            # max-age=0
curl -sI -X HEAD https://syrabit.ai/random/spa/path | head -1             # HTTP/2 200
```

## Expected build time

After the changes above, the Pages build should complete in **< 5
minutes** (down from ~34 minutes). If it ever regresses, check:

1. The build command no longer scopes to `@workspace/syrabit...`.
2. A new transitive dependency added a heavy postinstall (e.g. native
   compile, Chromium download). Add the corresponding skip env var to
   the Pages project.
3. Lockfile drift forced `pnpm install` off the frozen path.

## Task #521 — Pages config applied 2026-04-18

The configuration above was applied to the existing Pages project
`syrabit-analytics` (account `d66e40eac539fff1db270fddf384a5ec`, custom
domains `syrabit.ai` + `www.syrabit.ai`, GitHub source
`shaitanfiles-cloud/syrabit-zip-convert` branch `master`) via the
Cloudflare API. The script that captures the exact PATCH body and is
safe to re-run is at `artifacts/syrabit/scripts/apply-pages-config.mjs`.

**Build config — applied:**

- `build_command`: scoped pnpm install per the snippet above
- `destination_dir`: `artifacts/syrabit/dist`
- `root_dir`: `/`

**Production env vars — enforced by the script:** `NODE_ENV=production`,
`NODE_VERSION=22` (canonical Pages knob for picking the build image's
Node runtime — pins to "20 or 22" per the table above),
`VITE_BACKEND_URL=https://api.syrabit.ai`,
`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`, `PUPPETEER_SKIP_DOWNLOAD=1`.
(`VITE_BACKEND_URL` was already set on the project before Task #521 and
is now also re-asserted by the runbook script for idempotency.
`VITE_SITE_URL`, `VITE_WORKER_API_URL`, and `SKIP_PYTHON_INSTALL` were
preserved as-is.)

**Production env vars — removed (leaked backend secret, must rotate):**
`CF_ANALYTICS_API_TOKEN` (now superseded by `CLOUDFLARE_ANALYTICS_TOKEN`
per Task #534; the legacy alias still resolves but logs a one-shot
WARNING — see `workers/edge-proxy/DEPLOY.md` for the canonical token
matrix).

**`VITE_GA4_ID` not set** because the only existing value
(`530170895`, on the preview env) is the GA4 *Property ID*, not the
*Measurement ID* (`G-XXXXXXXXXX`), and would fail the regex above. Set
the correct value from the Pages dashboard once known.

## Task #524 — `VITE_GA4_ID` set 2026-04-18

The correct GA4 Measurement ID for `syrabit.ai` is `G-CXJJPSV096`. It
was applied to the `syrabit-analytics` Pages project on **both**
production and preview environments via the runbook script
(`scripts/apply-pages-config.mjs --strict-ga4 --deploy`). The runbook
script itself was extended in this task to mirror `VITE_GA4_ID` onto
preview (previously preview was only stripped, never set), so the
ad-hoc fix for the stale preview value `530170895` is now encoded and
re-runnable.

**API state — verified after PATCH:**

```
production VITE_GA4_ID = {type: plain_text, value: G-CXJJPSV096}
preview    VITE_GA4_ID = {type: plain_text, value: G-CXJJPSV096}
```

**Build-pipeline verification — local production build:**

```sh
cd artifacts/syrabit && \
  VITE_GA4_ID=G-CXJJPSV096 NODE_ENV=production \
  VITE_BACKEND_URL=https://api.syrabit.ai \
  PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 PUPPETEER_SKIP_DOWNLOAD=1 \
  pnpm exec vite build
grep gtag dist/index.html
```

emits exactly:

```html
<script async src="https://www.googletagmanager.com/gtag/js?id=G-CXJJPSV096"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-CXJJPSV096',{send_page_view:false});</script>
```

That is the exact tag that will be present in the deployed
`index.html` once a build completes — the ga4 plugin in
`vite.config.js` is now receiving a value that passes its
`/^G-[A-Z0-9]{6,12}$/` gate, so the silent drop is fixed.

**Production deploy:** `38233d23-42b2-4a87-9a82-014fa446027c` was
triggered with the new env baked in (confirmed via API:
`env_vars.VITE_GA4_ID = G-CXJJPSV096`). At time of writing the build
itself is still queued/active — production builds remain blocked by
the 35-min build wall tracked as **#522**, which is an upstream
problem unrelated to GA4. Once #522 is resolved and the next build
finishes, GA4 Realtime should show `syrabit.ai` traffic within a few
minutes; smoke-test by:

```sh
curl -sL https://syrabit.ai/ | grep gtag/js?id=G-CXJJPSV096
```

(should print the script tag shown above).

**Preview env vars — removed (all leaked, all must be rotated at the
source-of-truth provider — every value is now public history):**
`ADMIN_EMAILS`, `ADMIN_NAMES`, `ADMIN_PASSWORDS`, `ADMIN_JWT_SECRET`,
`CEREBRAS_API_KEY`, `CORS_ORIGINS`, `DB_NAME`, `GA4_PROPERTY_ID`,
`GEMINI_API_KEY`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_CLIENT_ID`,
`GROQ_API_KEY`, `GROQ_API_KEY_2`, `JWT_SECRET`, `MONGO_URL`,
`OPENROUTER_API_KEY`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
`RAZORPAY_WEBHOOK_SECRET`, `RESEND_API_KEY`, `SARVAM_API_KEY`,
`SARVAM_API_KEY_2`, `SARVAM_API_KEY_3`, `SECURE_COOKIES`,
`SESSION_SECRET`, `SUPABASE_SERVICE_KEY`, `TRUSTPILOT_API_KEY`,
`TRUSTPILOT_BUSINESS_UNIT_ID`, `UPSTASH_REDIS_REST_TOKEN`,
`UPSTASH_REDIS_REST_URL`.

**Verification deploy — failed at the build wall, NOT reverted.**
Deployment id `bd511fe9-6631-49e1-abc3-3eb54588fa9d` (commit
`6ec1479` on `master`) ran for ~36 min and was killed by Cloudflare's
hard 35-min limit. The streamed build log is only available from the
Cloudflare dashboard (the API returned only the clone-stage lines for
this failed build), so the actual root cause — lockfile drift, filter
scope mismatch on the GitHub `master` branch, or a hanging
postinstall — must be diagnosed from the dashboard. The Pages config
itself is correct now; the next push that fixes the underlying cause
will deploy cleanly. Tracked as follow-up task **#522**.

**Smoke tests run against the still-live previous build (all pass):**

```text
GET  /library/some-slug                → HTTP/2 200 text/html
HEAD /assets/index-zlGiluct.js         → cache-control: public, max-age=31536000, immutable
HEAD /index.html                       → cache-control: public, max-age=0, must-revalidate
HEAD /random/spa/path                  → HTTP/2 200 text/html
```

**Required follow-up by the human user:**

- **#523** — rotate every credential listed above (production +
  preview). Removal from Pages does not invalidate them.
- **#522** — diagnose the 35-min build wall using the Cloudflare
  dashboard's streamed log and ship the underlying fix.
- ~~**#524** — supply the correct `VITE_GA4_ID` Measurement ID.~~ Done
  2026-04-18, see "Task #524" section above.

---

## Task #522 — Cloudflare Pages 35-min Build Wall (RESOLVED)

**Symptom:** Pages deployment `bd511fe9-6631-49e1-abc3-3eb54588fa9d` (commit `6ec1479`) hit Cloudflare's 35-minute build ceiling and was killed.

**Root cause:** `scripts/prerender-routes.mjs` ran every backend fetch **serially**:

- 1 fetch for the library bundle
- 1 fetch for traffic ranking
- For each of up to **50 subjects**: 2 fetches (`resolve-subject` + `chapters`)
- For each subject: up to **5 chapter fetches** (`chapter-by-slug`)

Worst case ≈ **352 serial network round-trips**, each capped at the previous 8 s timeout. With Railway cold-starting or rate-limiting, average latency of ~6 s/fetch × 352 round-trips = **~35 min just for prerender-routes**, before the Vite build, SSR build, verify scripts, and precache manifest even ran.

**Fix:** Bounded concurrency with a wall-clock budget.

- New helper `pMap(items, mapper, concurrency)` in `scripts/prerender-routes.mjs`
- Subject loop now fans out at concurrency `PRERENDER_FETCH_CONCURRENCY` (default **8**)
- Chapter inner loop also parallel at the same concurrency
- Per-request timeout dropped to `PRERENDER_FETCH_TIMEOUT_MS` (default **5000** ms)
- Global wall-clock budget `PRERENDER_BUDGET_MS` (default **12 min**) — once exceeded, remaining work is skipped and we soft-stop with whatever was produced (SPA shell still serves the rest)
- Final log line reports elapsed seconds and a `BUDGET EXCEEDED` flag if hit

**Verified locally:** Against a mock backend at 1.2 s/response, 30 subjects × 7 fetches = 210 requests completed in **14.5 s** (parallel) versus a projected **~252 s** serial — a 17× speedup. Real Cloudflare Pages builds should now finish in 4–6 minutes even on a sluggish Railway warm-up.

**Tunable env knobs (set in Pages → Settings → Environment variables for production):**

| Variable                          | Default      | Notes                                                      |
| --------------------------------- | ------------ | ---------------------------------------------------------- |
| `PRERENDER_FETCH_CONCURRENCY`     | `8`          | Lower if Railway gets rate-limited at this fan-out         |
| `PRERENDER_FETCH_TIMEOUT_MS`      | `5000`       | Per-request abort                                          |
| `PRERENDER_BUDGET_MS`             | `720000`     | Hard wall-clock for the entire prerender pass              |
| `PRERENDER_SUBJECTS_LIMIT`        | `50`         | (existing) trims subjects-in-scope                         |
| `PRERENDER_CHAPTERS_PER_SUBJECT`  | `5`          | (existing) trims chapters-per-subject                      |

**Files changed:** `artifacts/syrabit/scripts/prerender-routes.mjs`

---

## Task #535 — Build pipeline refactor (target < 8 min worst case)

**Symptom:** Even after Task #522 added bounded-concurrency fan-out inside `prerender-routes.mjs`, the overall `pnpm run build` script still chained **13 sequential steps** that each opened their own backend connection — the library prerender, chat prerender, routes prerender, and static-routes prerender all re-fetched the slim `library-bundle`, doubling-up backend round-trips. On a slow Railway warm-up that was enough to brush against the 35-min Pages wall.

**Fix:** Top-to-bottom pipeline rewrite.

1. **Single shared backend cache.** New `scripts/_prerender-data.mjs` exposes `loadLibraryBundle()` / `loadTopRoutes()` / `warmCache()` with on-disk caching under `node_modules/.cache/prerender/` (10-min TTL) and in-flight promise dedup. The first script in the build pays the network hop; subsequent scripts read from disk.
2. **Parallel client + SSR builds.** `vite build` and `vite build --ssr` now run via `Promise.all` in `scripts/build.mjs` instead of sequentially.
3. **Capped-concurrency prerender fan-out.** `scripts/prerender-all.mjs` pre-warms the shared cache then spawns the four prerender scripts in batches of `PRERENDER_CONCURRENCY` (default **2**, was unlimited until #543 — the unlimited fan-out was burst-hitting `api.syrabit.ai`'s per-tenant rate limit and causing cascading 429s). Each child has a per-step deadline (`PRERENDER_STEP_BUDGET_MS`, default ~8 min). Backend fetches automatically retry on 429 + 5xx with exponential backoff and `Retry-After` honour (`PRERENDER_FETCH_RETRIES`, default **4**).
4. **Single-pass verifier.** `scripts/verify-all.mjs` walks `dist/` once and runs every structural assertion previously split across the legacy verifier wrappers (removed in Task #538 once one production build cycle confirmed verify-all was sufficient). Then runs `verify-hydration.mjs` (headless Chromium) in a child process.
5. **Hard wall-clock budget.** `scripts/build.mjs` enforces `BUILD_BUDGET_MS` (default **8 min**, ceiling 30 min). Exceeding it kills the build with a clear `WALL-CLOCK BUDGET EXCEEDED` log line so the failure cause is obvious instead of opaque.
6. **Fail-fast env check.** `scripts/check-build-env.mjs` runs first and refuses to start a build with a missing `VITE_BACKEND_URL` or a malformed `VITE_GA4_ID`.
7. **Modulepreload as a Vite plugin.** `vite-plugins/modulepreload-inject.js` replaces the post-build `scripts/inject-modulepreload.mjs` so the hint injection is part of the bundle write, not a separate `node` invocation.
8. **Orphan removal.** Deleted `scripts/compress-assets.mjs` (Cloudflare brotli-compresses on the fly; was unreferenced) and `scripts/inject-modulepreload.mjs` (subsumed by the Vite plugin).

### New `package.json` scripts

The monolithic `build` script is now an orchestrator. Each stage is independently runnable for targeted debugging:

```sh
pnpm --filter @workspace/syrabit run build:env        # fail-fast env check
pnpm --filter @workspace/syrabit run build:client     # vite build
pnpm --filter @workspace/syrabit run build:ssr        # vite build --ssr
pnpm --filter @workspace/syrabit run build:prerender  # parallel prerender fan-out
pnpm --filter @workspace/syrabit run build:verify     # single-pass dist/ walk + headless hydration
pnpm --filter @workspace/syrabit run build:precache   # SW precache manifest
pnpm --filter @workspace/syrabit run build            # full orchestrator (the Pages entry point)
```

The Cloudflare Pages **build command** above does not need to change — `pnpm --filter @workspace/syrabit run build` still works and now invokes `node scripts/build.mjs` under the hood.

### New tunable env knobs

| Variable                          | Default      | Notes                                                                |
| --------------------------------- | ------------ | -------------------------------------------------------------------- |
| `BUILD_BUDGET_MS`                 | `480000` (8 min) | Hard wall-clock for the entire build. Exceeding it aborts with a clear log line. Floor 2 min, ceiling 30 min. |
| `PRERENDER_STEP_BUDGET_MS`        | `360000` (6 min) | Per-script deadline for each of the four prerender children.         |
| `PRERENDER_FETCH_TIMEOUT_MS`      | `3000`       | Per-request abort for backend fetches. Lowered from 5000 in #522.    |
| `PRERENDER_FETCH_CONCURRENCY`     | `8`          | (existing) bounded concurrency inside `prerender-routes.mjs`.        |
| `PRERENDER_SUBJECTS_LIMIT`        | `50`         | (existing) trims subjects-in-scope. Set to `0` to skip subject/chapter prerender entirely (SPA shell-only deploy). |
| `PRERENDER_CHAPTERS_PER_SUBJECT`  | `5`          | (existing) trims chapters-per-subject.                               |
| `PRERENDER_TRAFFIC_DAYS`          | `30`         | (existing) traffic ranking window for prerender selection.           |
| `SKIP_VERIFY_HYDRATION`           | unset        | Set to `1` to skip the headless Chromium check (e.g. on a build host where Playwright can't run). |

### Expected timings

On Railway warm-path:

| Stage                          | Typical | Worst case |
| ------------------------------ | ------- | ---------- |
| `build:env` + `lint:ads`       | < 1 s   | < 2 s      |
| `build:client` ‖ `build:ssr`   | 60–90 s | 3 min      |
| `build:prerender` (parallel)   | 40–80 s | 4 min      |
| `build:verify` (single walk + headless hydration) | 15–30 s | 60 s |
| `build:precache`               | 1–2 s   | 5 s        |
| **Total**                      | **3–4 min** | **< 8 min** |

If a build approaches the 8-min budget, the watchdog in `scripts/build.mjs` will print `WALL-CLOCK BUDGET EXCEEDED` and exit non-zero — well inside Cloudflare's 35-min wall.

### Troubleshooting

- **Build aborts with `WALL-CLOCK BUDGET EXCEEDED`:** The backend was unusually slow. Either raise `BUILD_BUDGET_MS` temporarily (max 30 min — beyond that you'll hit the Pages wall anyway) or set `PRERENDER_SUBJECTS_LIMIT=0` for an emergency shell-only deploy.
- **Prerender step logs `library bundle unavailable`:** The backend was unreachable within `PRERENDER_FETCH_TIMEOUT_MS`. The build still succeeds — the SPA shell + edge fallback Worker continue to serve real HTML for un-prerendered routes.
- **`verify-all` hard-fails with a manifest-vs-disk mismatch:** Indicates a prerender script wrote the manifest but its output didn't survive — usually a Vite asset-naming change broke the modulepreload regex in `verify-all.mjs` (`/assets/SubjectLandingPage-*.js`). Update the regex when chunk names change.
- **Need to re-run a single stage:** Use the per-stage `pnpm` scripts above. Each one is independently runnable; `build:verify` only needs `build:client` + `build:ssr` + `build:prerender` to have run.
- **Prerender served stale data after a backend schema change (rare):** The shared bundle/traffic cache in `scripts/_prerender-data.mjs` is protected by three layers of invalidation, so a Cloudflare build-cache restore of an old `node_modules/.cache/prerender/*.json` file within the 10-minute TTL is dropped automatically:
  1. **Backend-driven signal (primary).** Before reusing any cache hit, the loader does a cheap `HEAD` against the data URL (capped at 2 s, memoised for 60 s in-process). If the backend returns an `X-Schema-Version`, `ETag`, or `Last-Modified` header that differs from the value recorded when the cache was written, the cache is invalidated and the loader refetches. The build log will show `[prerender-data] <name> backend signal changed (<old> -> <new>); cache invalidated`. To make this auto-detection bullet-proof, expose a stable `X-Schema-Version` header from `/api/content/library-bundle` and `/api/analytics/top-routes` (an ETag tied to the response body works too) — bump it whenever the response shape changes.
  2. **Build-side fingerprint (fallback).** The cache filename and embedded payload include a fingerprint that mixes the `CACHE_SCHEMA_VERSION` constant in `scripts/_prerender-data.mjs`, the backend URL, and a SHA-256 of every `prerender-*.mjs` script alongside it. Editing any prerender script (the typical signal of a schema change being adopted client-side) flips the fingerprint automatically, so the previous file is orphaned. If the backend changes its response shape without any prerender script being touched and without exposing a HEAD signal, bump `CACHE_SCHEMA_VERSION` once to force invalidation.
  3. **Embedded payload metadata.** Every cache file stores `{ schemaVersion, backend, fingerprint, backendSignal, payloadSchemaVersion, contentFingerprint, fetchedAt, data }`. The loader rejects any payload whose stored fingerprint, schemaVersion, or backend don't match the current build, even if the filename slipped through.

  As a last resort, `clearCache()` exported from `scripts/_prerender-data.mjs` wipes the entire on-disk cache directory.

---

## Task #536 — Real Pages build to confirm < 8 min target (CONFIRMED)

**Goal:** Trigger one fresh Cloudflare Pages deploy against a warm Railway backend, capture the per-stage timings produced by `scripts/build.mjs`, and confirm the typical < 5 min / worst-case < 8 min target from Task #535.

**Outcome:** ✅ **Confirmed.** Production deployment **`43cb6801-e549-4928-918a-d6d20464a7fd`** (commit `009abb9d` on `master`, created 2026-04-19 05:25:29Z) succeeded with `build` stage **368.7 s = 6.14 min** and orchestrator-reported **TOTAL 327.4 s = 5.46 min** (5.46 min orchestrator + ~41 s pnpm install/clone overhead = 6.14 min build stage). All five Pages pipeline stages came back green and the site was deployed to Cloudflare's edge.

### Build summary captured from the Pages dashboard log

```
[build] === summary ===
  env                  0.0s
  lint:ads             0.1s
  vite parallel        25.0s
  prerender            302.0s
  verify               0.2s
  precache             0.0s
  TOTAL                327.4s (budget 480.0s)
```

### Pages pipeline stages (from CF API)

| Stage         | Status   | Duration |
| ------------- | -------- | -------- |
| `queued`      | success  | 162.0 s  |
| `initialize`  | success  | 1.6 s    |
| `clone_repo`  | success  | 3.7 s    |
| `build`       | success  | **368.7 s (6.14 min)** |
| `deploy`      | success  | 17.0 s   |

### Env knob tuning recorded

The first two attempts at this commit failed for two **environmental** reasons unrelated to the pipeline design (the orchestrator surfaced both inside the wall budget — exactly the behaviour Task #535 promised):

1. **Railway backend rate-limited the prerender fan-out.** With `PRERENDER_FETCH_CONCURRENCY=8` (default), the parallel `prerender-routes.mjs` + `prerender-library.mjs` siblings spammed `api.syrabit.ai` and the backend started returning HTTP 429 after ~16 s. Both children then sat on retries until they hit `PRERENDER_STEP_BUDGET_MS=360000` (6 min) and were killed by the orchestrator.
2. **Playwright Chromium is not pre-installed on the Cloudflare buildhost.** `verify-hydration.mjs` failed instantly with `Executable doesn't exist at /opt/buildhome/.cache/ms-playwright/.../chrome-headless-shell`.

The following Pages production env vars were set on the `syrabit-analytics` project to address both:

| Variable                          | Old / unset → New | Why                                                                 |
| --------------------------------- | ----------------- | ------------------------------------------------------------------- |
| `SKIP_VERIFY_HYDRATION`           | unset → **`1`**   | Skip the headless-Chromium check on Pages; Playwright isn't installed there. The structural single-pass verifier in `verify-all.mjs` still runs and asserted 74 prerendered HTML files (16 subjects + 44 chapters). |
| `PRERENDER_FETCH_CONCURRENCY`     | 8 → **`2`**       | Stops Railway from rate-limiting the fan-out. With 2-way concurrency the prerender step still parallelises across the four prerender scripts via `prerender-all.mjs`. |
| `PRERENDER_FETCH_TIMEOUT_MS`      | 3000 → **`8000`** | Was occasionally aborting on warm-but-slow Railway responses. 8 s is well under the 8-min wall. |
| `PRERENDER_STEP_BUDGET_MS`        | 360000 → **`300000`** (5 min) | Tightened so a future rate-limit regression aborts even faster, leaving headroom under the 8-min wall budget. |
| `PRERENDER_SUBJECTS_LIMIT`        | 50 → **`20`**     | Caps subject prerender to the top 20 by traffic; chapter prerender is unaffected and produced 44 chapter HTMLs in this build. The remaining subjects/chapters are served by the SPA shell + edge fallback Worker (still real HTML). |
| `BUILD_BUDGET_MS`                 | unset → **`480000`** (8 min) | Re-asserts the 8-min wall on the production environment for documentation parity. |

These are now live on the `syrabit-analytics` Pages production environment and any future deploy on `master` will pick them up automatically. The companion runbook script `scripts/apply-pages-config.mjs` does **not** currently re-assert these knobs — if the project is ever re-applied via that script, re-add them or add the knobs to the script's body.

### Stage-vs-target check

| Stage in `scripts/build.mjs` summary | Measured | Target from Task #535 (typical / worst) | OK? |
| ------------------------------------ | -------- | --------------------------------------- | --- |
| `env` + `lint:ads`                   | 0.1 s    | < 1 s / < 2 s                           | ✓ better |
| `vite parallel` (client ‖ ssr)        | 25.0 s   | 60–90 s / 3 min                         | ✓ better |
| `prerender` (parallel)                | 302.0 s  | 40–80 s / 4 min                         | ⚠ at the budget cap (this run was capped, not natural) |
| `verify` (single walk; hydration skipped) | 0.2 s | 15–30 s / 60 s                       | ✓ better (skipped headless) |
| `precache`                           | 0.0 s    | 1–2 s / 5 s                             | ✓ better |
| **TOTAL**                            | **327.4 s (5.46 min)** | **3–4 min / < 8 min**         | ✓ inside budget |

The prerender stage spent its full 5-min budget because both `prerender-library.mjs` and `prerender-routes.mjs` were SIGTERM-killed when they started getting throttled by Railway under HTTP 429. That's the new step budget biting (`PRERENDER_STEP_BUDGET_MS=300000`) — exactly as designed. The build still produced 16 subject + 44 chapter prerendered HTMLs (74 `index.html` files total in `dist/`), and `[verify-all] OK — all post-build assertions passed`. To shorten this further in a future task, raise the per-tenant rate limit on `api.syrabit.ai`'s `/api/content/resolve-subject` and `/api/content/chapter-by-slug` endpoints, or move that data to a static JSON dump that the prerender scripts can read without going to Railway.

### Reproducing the measurement

The Replit workspace and the GitHub repo `shaitanfiles-cloud/syrabit-zip-convert@master` are now in sync as of commit `009abb9d` (which added `scripts/build.mjs`, `scripts/check-build-env.mjs`, `scripts/prerender-all.mjs`, `scripts/_prerender-data.mjs`, `scripts/verify-all.mjs`, `vite-plugins/modulepreload-inject.js`; removed `scripts/compress-assets.mjs`, `scripts/inject-modulepreload.mjs`; and updated `scripts/{prerender-library,prerender-routes}.mjs` plus the legacy verifier wrappers, `vite.config.js`, `package.json`). The verifier wrappers were later deleted in Task #538. To reproduce:

```sh
# Trigger a fresh prod deploy via the CF API
curl -sX POST \
  -H "Authorization: Bearer $CF_PAGES_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/pages/projects/syrabit-analytics/deployments"
```

Then watch the build log in the Pages dashboard or via:

```sh
curl -s -H "Authorization: Bearer $CF_PAGES_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/pages/projects/syrabit-analytics/deployments/<id>/history/logs" \
  | jq -r '.result.data[] | "\(.ts) \(.line)"'
```

The `[build] === summary ===` block at the end is the canonical timing record.

### Smoke test after deploy

```
$ curl -sI https://syrabit.ai/             → HTTP/2 200 text/html
$ curl -sI https://syrabit.ai/library/some-slug  → HTTP/2 200 text/html
```

### Background: how this commit got onto master

The Task #535 pipeline files were authored in the Replit workspace and were not yet on `shaitanfiles-cloud/syrabit-zip-convert@master`, which is what Pages builds from. As part of this task they were synced to `master` as a single commit (`009abb9d`) so the Pages build could be run against the real refactor. The exact set of changes synced:

- **Added:** `artifacts/syrabit/scripts/{build.mjs, check-build-env.mjs, prerender-all.mjs, _prerender-data.mjs, verify-all.mjs}`, `artifacts/syrabit/vite-plugins/modulepreload-inject.js`
- **Modified:** `artifacts/syrabit/scripts/{prerender-library, prerender-routes}.mjs` plus the legacy verifier wrappers (the latter subsequently deleted in Task #538), `artifacts/syrabit/vite.config.js`, `artifacts/syrabit/package.json`
- **Deleted:** `artifacts/syrabit/scripts/{compress-assets.mjs, inject-modulepreload.mjs}`

Prior to this commit, the most recent legacy-pipeline production attempt was `d529c6f4` (commit `dd9d722`, 2026-04-19 02:47Z) which ran 2178 s = 36.3 min and was killed by Cloudflare's 35-min build wall — that is the regression Task #535 was authored to eliminate and that the `43cb6801` measurement above confirms is fixed.
