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

- `CF_ANALYTICS_API_TOKEN` — backend reads CF Analytics GraphQL with this
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
`CF_ANALYTICS_API_TOKEN`.

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
3. **Parallel prerender fan-out.** `scripts/prerender-all.mjs` pre-warms the shared cache then spawns the four prerender scripts via `Promise.all`. Each child has a per-step deadline (`PRERENDER_STEP_BUDGET_MS`, default 6 min).
4. **Single-pass verifier.** `scripts/verify-all.mjs` walks `dist/` once and runs every structural assertion the legacy `verify-prerender`, `verify-library-prerender`, and `verify-canonicals` scripts performed. Then runs `verify-hydration.mjs` (headless Chromium) in a child process.
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
