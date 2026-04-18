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
`UPSTASH_REDIS_REST_URL`, `VOYAGE_API_KEY`.

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
- **#524** — supply the correct `VITE_GA4_ID` Measurement ID.

---

## Task #523 — Credential rotation runbook

Every value below was set on the public Pages project at some point and
must therefore be treated as fully compromised. Removing it from Pages
(done in #521) does **not** invalidate the leaked value. Each one must
be regenerated at the provider's dashboard and the new value pushed to
the legitimate consumer (Railway backend env, Cloudflare Worker secrets,
or Replit secrets) — never back to Pages.

### How to use this checklist

For each row:

1. Open the provider dashboard, generate a new credential, and **revoke
   the old one** (this is what actually closes the leak — generation
   alone is not enough).
2. Update the new value at every consumer listed in the "Update at"
   column.
3. Tick the box and write the rotation date in the "Rotated on" column.
4. If a rotation is impossible (e.g. provider doesn't allow rotating a
   given key without breaking live traffic), record that in
   `Notes` and open a follow-up so it isn't silently skipped.

> All consumer updates must be done via the provider's secrets UI — do
> not paste any of these values into a code file, a `.env` committed to
> git, or back onto the Pages project.

### Production env — leaked

| Done | Credential                    | Rotate at                                         | Update at                          | Rotated on |
| :--: | ----------------------------- | ------------------------------------------------- | ---------------------------------- | ---------- |
|  ☐   | `CF_ANALYTICS_API_TOKEN`      | Cloudflare → My Profile → API Tokens              | Railway backend env                |            |

### Preview env — leaked

| Done | Credential                       | Rotate at                                            | Update at                                | Rotated on |
| :--: | -------------------------------- | ---------------------------------------------------- | ---------------------------------------- | ---------- |
|  ☐   | `RAZORPAY_KEY_ID`                | Razorpay Dashboard → Settings → API Keys             | Railway backend env                      |            |
|  ☐   | `RAZORPAY_KEY_SECRET`            | Razorpay Dashboard → Settings → API Keys             | Railway backend env                      |            |
|  ☐   | `RAZORPAY_WEBHOOK_SECRET`        | Razorpay Dashboard → Settings → Webhooks             | Railway backend env (verify slot — was URL?) |        |
|  ☐   | `JWT_SECRET`                     | Generate fresh 64-byte random (e.g. `openssl rand -hex 32`) | Railway backend env               |            |
|  ☐   | `SESSION_SECRET`                 | Generate fresh 64-byte random                        | Railway backend env                      |            |
|  ☐   | `ADMIN_JWT_SECRET`               | Generate fresh 64-byte random                        | Railway backend env                      |            |
|  ☐   | `ADMIN_PASSWORDS`                | Generate fresh strong passwords for every admin     | Railway backend env + notify each admin   |            |
|  ☐   | `GOOGLE_CLIENT_SECRET`           | Google Cloud Console → APIs & Services → Credentials | Railway backend env                      |            |
|  ☐   | `GROQ_API_KEY`                   | console.groq.com → API Keys                          | Railway backend env + Replit secret      |            |
|  ☐   | `GROQ_API_KEY_2`                 | console.groq.com → API Keys                          | Railway backend env + Replit secret      |            |
|  ☐   | `GEMINI_API_KEY`                 | aistudio.google.com → API keys                       | Railway backend env + Replit secret      |            |
|  ☐   | `OPENROUTER_API_KEY`             | openrouter.ai → Keys                                 | Railway backend env + Replit secret      |            |
|  ☐   | `CEREBRAS_API_KEY`               | cloud.cerebras.ai → API Keys                         | Railway backend env + Replit secret      |            |
|  ☐   | `SARVAM_API_KEY`                 | dashboard.sarvam.ai → API Keys                       | Railway backend env + Replit secret      |            |
|  ☐   | `SARVAM_API_KEY_2`               | dashboard.sarvam.ai → API Keys                       | Railway backend env + Replit secret      |            |
|  ☐   | `SARVAM_API_KEY_3`               | dashboard.sarvam.ai → API Keys                       | Railway backend env + Replit secret      |            |
|  ☐   | `VOYAGE_API_KEY`                 | dash.voyageai.com → API Keys                         | Railway backend env + Replit secret      |            |
|  ☐   | `MONGO_URL`                      | MongoDB Atlas → Database Access → rotate user pwd    | Railway backend env                      |            |
|  ☐   | `SUPABASE_SERVICE_KEY`           | Supabase → Project Settings → API → reset service role key | Railway backend env + Replit secret |        |
|  ☐   | `UPSTASH_REDIS_REST_TOKEN`       | console.upstash.com → DB → REST API → Reset token    | Railway backend env + Worker secret      |            |
|  ☐   | `UPSTASH_REDIS_REST_URL`         | (URL itself isn't secret, but rotating the token may change it — verify) | Railway backend env + Worker secret |  |
|  ☐   | `RESEND_API_KEY`                 | resend.com → API Keys                                | Railway backend env + Replit secret      |            |
|  ☐   | `TRUSTPILOT_API_KEY`             | business.trustpilot.com → Integrations → API         | Railway backend env + Replit secret      |            |

### After every row above is ticked

1. Restart the Railway backend service so all new values are picked up.
2. Redeploy the edge proxy Worker (`wrangler deploy`) if any Worker
   secret changed.
3. Run the full smoke set against `https://api.syrabit.ai` (auth, chat,
   payment webhook test event, Resend test email, Trustpilot fetch).
4. Record the completion date here:

> **Rotation completed on:** ____________________ (fill in once the
> last row above is ticked)

