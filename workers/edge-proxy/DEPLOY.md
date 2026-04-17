# Cloudflare Edge Proxy Worker — Deployment Guide

## Architecture

```
Browser → api.syrabit.ai (Cloudflare Worker)
              ├─ D1 database (content cache — edge-fast reads)
              ├─ KV namespace (rate limiting)
              └─ Backend proxy → Railway backend
```

- **Cloudflare Worker** (`syrabit-edge`) → edge API proxy at `api.syrabit.ai`
- **D1 Database** (`syrabit-content`) → edge-replicated content catalog
- **KV Namespace** (`RATE_LIMIT`) → per-IP rate limiting (120 req/min)
- **Cron Trigger** → every 6 hours, auto-syncs content from backend to D1
- **Backend** → Railway origin server for auth, AI chat, and admin

> **Note on legacy `syrabit-zip-convert` worker:** The `api.syrabit.ai/*` route
> was previously assigned to a worker named `syrabit-zip-convert` (named after
> the GitHub repo `shaitanfiles-cloud/syrabit-zip-convert`, which actually
> hosts the Railway FastAPI backend code, not a separate ZIP-conversion
> service). Audit on 2026-04-17 confirmed the live backend OpenAPI exposes
> 347 routes and **zero** of them match `zip|convert|epub`, so no
> ZIP-specific functionality was lost when the route was reassigned to
> `syrabit-edge`. All previously-served endpoints continue to be reachable
> via the edge worker's backend proxy.
>
> **Verification commands (run 2026-04-17):**
>
> ```bash
> # 1. Edge health (should report x-source: edge)
> curl -sI https://api.syrabit.ai/api/health | grep -i 'x-source\|HTTP'
> #   HTTP/2 200
> #   x-source: edge
>
> # 2. Proxied content route (should report x-source: backend)
> curl -sI https://api.syrabit.ai/api/content/boards | grep -i 'x-source\|HTTP'
> #   HTTP/2 200
> #   x-source: backend
>
> # 3. Smoke other proxied/D1 routes
> for p in /api/content/library-bundle /api/seo/sitemap-index.xml \
>          /api/admin/pyq/upload; do
>   echo "$(curl -s -o /dev/null -w '%{http_code}' https://api.syrabit.ai$p) $p"
> done
> # Expected: 200, 200, 405 (405 = POST-only handler reachable)
>
> # 4. Confirm backend exposes no zip/convert/epub endpoints
> curl -s https://workspacesyrabit-production-0ddc.up.railway.app/openapi.json \
>   | python3 -c "import sys,json; d=json.load(sys.stdin); \
>     paths=list(d.get('paths',{}).keys()); \
>     print('total:', len(paths)); \
>     print('zip/convert/epub:', [p for p in paths \
>       if any(k in p.lower() for k in ['zip','convert','epub'])])"
> # Expected: total: 347 (or similar, refresh if backend grows)
> #           zip/convert/epub: []
> ```
>
> If any of these probes regress (especially #4 returning a non-empty list
> or #1/#2 returning non-200/wrong `x-source`), re-run this audit before
> shipping further route changes.

---

## Prerequisites

Before deploying, confirm you have:

1. **Cloudflare account** with `syrabit.ai` domain on Cloudflare DNS
2. **Node.js 18+** installed locally
3. **Backend already deployed** — you need the live backend URL (e.g., `https://xxx.up.railway.app`)
4. **Git clone** of the repository on your local machine

---

## Step 1: Install Wrangler & Authenticate

```bash
npm install -g wrangler
wrangler login
```

This opens a browser window for Cloudflare OAuth. Confirm access.

---

## Step 2: Create D1 Database

```bash
cd workers/edge-proxy
wrangler d1 create syrabit-content
```

**Copy the `database_id`** from the output. It looks like:
```
✅ Successfully created DB 'syrabit-content'
database_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

---

## Step 3: Create KV Namespaces

```bash
wrangler kv:namespace create RATE_LIMIT
```
Copy the `id` from the output.

```bash
wrangler kv:namespace create RATE_LIMIT --preview
```
Copy the `preview_id` from the output.

> **Note:** Wrangler v3+ also accepts `wrangler kv namespace create` (without the colon). Use whichever your version supports.

---

## Step 4: Generate D1 Sync Secret

```bash
openssl rand -hex 32
# Copy the output, then set it as a Wrangler secret (never commit to wrangler.toml):
wrangler secret put D1_SYNC_SECRET
# Paste the generated secret when prompted
```

Copy the output — this 64-character hex string is shared between the Worker and the backend. **Save it securely; you'll need it in two places.**

---

## Step 5: Update `wrangler.toml` and Set Secrets

Open `workers/edge-proxy/wrangler.toml` and update:

| Field | Replace with | Source |
|---|---|---|
| `database_id` under `[[d1_databases]]` | D1 database ID | Step 2 |
| `id` under `[[kv_namespaces]]` | KV namespace ID | Step 3 |
| `preview_id` under `[[kv_namespaces]]` | KV preview namespace ID | Step 3 |
| `BACKEND_URL` under `[vars]` | Your deployed backend URL | e.g., `https://xxx.up.railway.app` |

> **Note:** The current `wrangler.toml` in the repo already has production values filled in. If they match your Cloudflare account, you only need to set the secret below.

**Set the sync secret as a Wrangler secret** (do NOT put it in `wrangler.toml`):

```bash
wrangler secret put D1_SYNC_SECRET
```

When prompted, paste the 64-character hex string from Step 4. Wrangler secrets are encrypted and never committed to source control.

The final `wrangler.toml` should look like:

```toml
name = "syrabit-edge"
main = "src/index.ts"
compatibility_date = "2024-12-01"

routes = [
  { pattern = "api.syrabit.ai/*", zone_name = "syrabit.ai" }
]

[vars]
BACKEND_URL = "https://your-backend.up.railway.app"

[[kv_namespaces]]
binding = "RATE_LIMIT"
id = "your-kv-namespace-id"
preview_id = "your-kv-preview-id"

[[d1_databases]]
binding = "CONTENT_DB"
database_name = "syrabit-content"
database_id = "your-d1-database-id"
migrations_dir = "migrations"

[triggers]
crons = ["0 */6 * * *"]
```

---

## Step 6: Apply D1 Migrations

```bash
wrangler d1 migrations apply syrabit-content --remote
```

This creates 8 tables with indexes:
- `boards`, `classes`, `streams`, `subjects`, `chapters`, `topics`, `seo_pages`, `sync_meta`

Verify with:
```bash
wrangler d1 execute syrabit-content --remote --command "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
```

---

## Step 7: Install Dependencies & Deploy

```bash
npm install
wrangler deploy
```

Expected output:
```
Published syrabit-edge (x.xx sec)
  api.syrabit.ai/* (zone: syrabit.ai)
  schedule: 0 */6 * * *
```

Confirm the route `api.syrabit.ai/*` appears in the output.

---

## Step 8: Set Backend Environment Variables

On your Railway backend deployment (Railway dashboard → Variables), add:

| Variable | Value |
|---|---|
| `D1_SYNC_SECRET` | Same 64-char hex secret from Step 4 |
| `EDGE_WORKER_URL` | `https://api.syrabit.ai` |

The backend uses these to push content updates to the Worker's D1 database.

---

## Step 9: Verify Deployment

### 9a. Health Check
```bash
curl -s https://api.syrabit.ai/api/health | jq .
```
Expected:
```json
{
  "status": "ok",
  "edge": true,
  "region": "SIN",
  "timestamp": "2026-04-15T...",
  "d1": true
}
```

### 9b. Backend Proxy (Content)
```bash
curl -s https://api.syrabit.ai/api/content/boards | jq .
```
Should return content data. Check headers:
```bash
curl -sI https://api.syrabit.ai/api/content/boards | grep X-Source
```
Before D1 sync: `X-Source: backend`
After D1 sync: `X-Source: d1`

### 9b2. Backend Proxy (Auth & AI)
Auth and AI routes bypass caching and proxy directly to the backend:
```bash
curl -s -o /dev/null -w "%{http_code}" https://api.syrabit.ai/api/auth/me
```
Should return `401` (unauthorized, but proves the proxy reaches the backend auth route).

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST https://api.syrabit.ai/api/ai/chat \
  -H "Content-Type: application/json" -d '{}'
```
Should return `401` or `422` (not `502`), confirming the backend is reachable for AI chat.

### 9c. Rate Limiting
Make 120+ requests in 60 seconds:
```bash
for i in $(seq 1 125); do
  code=$(curl -s -o /dev/null -w "%{http_code}" https://api.syrabit.ai/api/health)
  echo "Request $i: $code"
done
```
Requests beyond 120 should return `429`.

### 9d. Trigger D1 Sync
Option A — Full sync via backend admin API (recommended):
```bash
curl -X POST https://your-backend-url/api/admin/d1-sync \
  -H "Authorization: Bearer YOUR_ADMIN_JWT"
```
This exports all content from MongoDB and pushes it to D1.

Option B — From the admin panel:
- Log into the admin dashboard and use the "D1 Sync" button

Option C — Auth test only (verify the sync endpoint accepts credentials):
```bash
curl -s -o /dev/null -w "%{http_code}" -X POST https://api.syrabit.ai/api/edge/d1-sync \
  -H "Authorization: Bearer YOUR_D1_SYNC_SECRET" \
  -H "Content-Type: application/json" \
  -d '{}'
```
Should return `200` (not `401`), confirming the secret is correctly configured.

> **Warning:** Do not POST partial payloads (e.g., `{"boards":[]}`) to `/api/edge/d1-sync` — the sync uses replace semantics and will clear tables included in the payload. Always use Option A for production syncs.

### 9e. D1 Status
```bash
curl -s https://api.syrabit.ai/api/edge/d1-status | jq .
```
Expected (after sync):
```json
{
  "counts": {
    "boards": 2,
    "classes": 10,
    "streams": 53,
    "subjects": 55,
    "chapters": 500,
    "topics": 2000,
    "seo_pages": 1500
  },
  "last_sync": "2026-04-15T12:00:00.000Z",
  "last_sync_at": "2026-04-15T12:00:00.000Z"
}
```

### 9f. Verify D1 Serving
After a successful sync, content routes should return with `X-Source: d1`:
```bash
curl -sI https://api.syrabit.ai/api/content/boards | grep -E "X-Source|X-Cache"
```
Expected: `X-Source: d1` and `X-Cache: D1`

---

## Step 10: DNS Verification

If `api.syrabit.ai` doesn't resolve, check Cloudflare DNS:

1. Go to Cloudflare Dashboard → your zone (`syrabit.ai`) → DNS
2. The Worker route `api.syrabit.ai/*` should auto-configure when deployed
3. If needed, add a CNAME or A record for `api` (proxied through Cloudflare)

---

## Deploy Backend on Railway

See `artifacts/syrabit-backend/RAILWAY-DEPLOY.md` for the full Railway deployment guide.

**Quick summary:**
1. Go to https://railway.app/new → Deploy from GitHub repo
2. Set root directory to `artifacts/syrabit-backend`
3. Railway auto-detects the Dockerfile
4. Set all environment variables (see `.env.example`)
5. Generate a public domain under Settings → Networking
6. Update `BACKEND_URL` in `wrangler.toml` to the Railway URL

---

## Traffic Flow

```
User → syrabit.ai (CF Pages)
         │
         ▼
    api.syrabit.ai (CF Worker)
         │
         ├─ Content reads → D1 (edge, sub-ms)
         ├─ Cache hits → CF Cache API
         └─ AI chat / auth / admin → Railway backend
                                        │
                                        ├─ MongoDB Atlas
                                        ├─ Supabase (PostgreSQL)
                                        └─ Upstash Redis
```

## DNS Records (auto-configured if domain is on Cloudflare)
- `syrabit.ai` → Cloudflare Pages
- `www.syrabit.ai` → Cloudflare Pages (redirect to apex)
- `api.syrabit.ai` → Cloudflare Worker (via route pattern)

---

## Cron Schedule

The Worker has a cron trigger (`0 */6 * * *`) that runs every 6 hours. On each run it:

1. Calls `GET {BACKEND_URL}/api/admin/d1-export` with the sync secret
2. Receives the full content catalog as JSON
3. Replaces all D1 tables with fresh data
4. Updates `sync_meta.last_sync` timestamp

You can check cron execution in Cloudflare Dashboard → Workers → syrabit-edge → Triggers.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `502 Backend unavailable` | Check BACKEND_URL in wrangler.toml points to a running backend |
| `403` on CORS preflight | Origin must be in ALLOWED_ORIGINS list in `src/index.ts` |
| D1 sync returns empty | Backend must have `D1_SYNC_SECRET` env var set to the same secret |
| `429` too quickly | Rate limit is 120 req/min per IP — adjust `RATE_LIMIT_RPM` if needed |
| Cron not firing | Check Cloudflare Dashboard → Workers → Triggers tab |
| Health shows `"d1": false` | D1 binding may be misconfigured in wrangler.toml |

---

## Security Notes

- **`D1_SYNC_SECRET` must be stored as a Wrangler secret** (via `wrangler secret put D1_SYNC_SECRET`), not in `wrangler.toml`. This prevents the secret from being committed to source control.
- **Secret rotation required:** If a `D1_SYNC_SECRET` was previously committed in plaintext to `wrangler.toml` or any git history, generate a new secret (`openssl rand -hex 32`), update it in both the Wrangler secret and the backend environment, and verify the old secret no longer works.
- The sync endpoint (`/api/edge/d1-sync`) requires `Authorization: Bearer {secret}` — it cannot be called without the secret.
- Rate limiting uses KV with auto-expiring keys (TTL = 120s).

---

## Updating the Worker

After code changes:
```bash
cd workers/edge-proxy
wrangler deploy
```

After schema changes (new migration files in `migrations/`):
```bash
wrangler d1 migrations apply syrabit-content --remote
wrangler deploy
```

---

## Deploying via Cloudflare's "Workers Builds" (GitHub auto-deploy)

If the worker is connected to a GitHub repo and Cloudflare auto-builds on push
(Dashboard → Workers → `syrabit-edge` → Settings → Build), use these EXACT
settings. The default values Cloudflare suggests will fail.

| Field | Correct value | Why |
|---|---|---|
| **Root directory** | `/` (if repo only contains the worker) **OR** `workers/edge-proxy` (if pushing this whole monorepo) | Wrangler must run where `wrangler.toml` lives. |
| **Build command** | *(leave empty)* — or `pnpm install --frozen-lockfile` | Wrangler bundles `src/index.ts` itself via esbuild. There is no separate build step. A no-op `"build": "echo …"` script is in `package.json` so `pnpm run build` will also succeed if Cloudflare insists on a value. |
| **Deploy command** | `npx wrangler@3 deploy` | Pin to Wrangler 3. Wrangler 4 refuses to deploy from any folder containing `pnpm-workspace.yaml` ("workspace detection" error). The local `package.json` already pins `wrangler@^3.99.0` as a devDep. |
| **Version command** | `npx wrangler@3 versions upload` | Same reason — pin to v3. |
| **Production branch** | `master` (or whatever you push to) | Must match the branch you deploy from. |

### Common failure → fix

| Build log says | Real cause | Fix |
|---|---|---|
| `pnpm: command not found` or `Missing script: "build"` | Cloudflare ran `pnpm run build` but the repo had no build script | Either clear the build command, or pull this commit (adds a no-op `build` script). |
| `The Wrangler application detection logic has been run in the root of a workspace…` | Wrangler 4 saw a `pnpm-workspace.yaml` at root | Change Deploy command to `npx wrangler@3 deploy`, **or** set Root directory to `workers/edge-proxy`. |
| `Authentication error [code: 10000]` | The build-token API key lacks Workers Edit + D1 Edit + KV Edit permissions | Recreate "API token" under Build settings with: Workers Scripts:Edit, D1:Edit, Workers KV Storage:Edit, Account Settings:Read for your account. |
| `Could not find zone for syrabit.ai` | Token missing Zone:Read for syrabit.ai | Add Zone:Read for the `syrabit.ai` zone to the build token. |
| `KV namespace … not found` / `D1 database … not found` | The IDs in `wrangler.toml` don't exist in this CF account | Either create them with `wrangler kv namespace create …` / `wrangler d1 create …` and update IDs, or point the worker at the correct account. |

### After fixing the dashboard

Trigger a redeploy by pushing any commit (or click "Retry deploy" on the
failed build). Then verify with the smoke commands at the top of this file
(`x-source: edge` + `x-source: backend`).
