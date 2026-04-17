# Syrabit.ai — Deployment Architecture

## Architecture Overview

```
Users
  │
  ├── https://syrabit.ai ──► Cloudflare Pages (frontend SPA)
  │                            • React + Vite build
  │                            • Global CDN, edge caching
  │                            • DDoS protection
  │
  └── https://api.syrabit.ai ──► Cloudflare Worker (edge proxy)
                                  • Rate limiting (KV-backed)
                                  • D1 edge cache for content reads
                                  • CORS enforcement
                                  │
                                  └──► Railway (FastAPI backend)
                                        • Docker-based deployment
                                        • MongoDB, PostgreSQL, Redis
                                        • AI chat, auth, payments, admin
```

## Frontend — Cloudflare Pages

| Setting           | Value                                                                          |
| ----------------- | ------------------------------------------------------------------------------ |
| Root directory    | _leave empty_ (use repo root)                                                  |
| Build command     | `pnpm install --frozen-lockfile && cd artifacts/syrabit && pnpm run build`     |
| Output directory  | `artifacts/syrabit/dist`                                                       |
| Deploy command    | _leave empty_ (Pages auto-uploads the build output)                            |
| Node version      | 20                                                                             |

> ⚠️ **Do NOT set the deploy command to `npx wrangler deploy`.** This monorepo's
> root contains a `pnpm-workspace.yaml`, which Wrangler 4 detects as a workspace
> and refuses to deploy from. With the deploy command empty, Cloudflare Pages
> uploads the configured output directory automatically. If you must run a
> deploy command (e.g. for a non–git-integrated deploy), use the
> `pnpm run deploy:pages` script defined in the root `package.json`, which
> calls `wrangler pages deploy artifacts/syrabit/dist --project-name=syrabit`.

### Environment Variables (Pages)

| Variable             | Value                        |
| -------------------- | ---------------------------- |
| `VITE_BACKEND_URL`   | `https://api.syrabit.ai`     |
| `VITE_WORKER_API_URL`| `https://api.syrabit.ai`     |
| `VITE_GA4_ID`        | GA4 Measurement ID (optional)|
| `NODE_VERSION`       | `20`                         |

### Notes

- **SPA routing**: Primarily handled by `_worker.js` (Advanced Mode) + `_routes.json`, which also gives HEAD-probe parity (Task #365). A standard `public/_redirects` (`/* /index.html 200`) is also emitted as a fallback so deep links still resolve if `_worker.js` is ever removed.
- **Compression**: Cloudflare Pages applies brotli/gzip at the edge automatically.
- **Cache headers**: `public/_headers` configures immutable caching for hashed `/assets/*` files and must-revalidate for `index.html` and `sw.js`.
- **Production env**: `.env.production` bakes in the API URL at build time.

### Custom Domains

- `syrabit.ai` → Cloudflare Pages (apex domain)
- `www.syrabit.ai` → redirect to `syrabit.ai`

### Redeploy Frontend

Push to the connected GitHub branch. Cloudflare Pages auto-deploys on push.

## Edge Proxy — Cloudflare Worker

The Worker lives in `workers/edge-proxy/` and is deployed via Wrangler.

### Bindings

| Binding       | Type | Purpose                        |
| ------------- | ---- | ------------------------------ |
| `CONTENT_DB`  | D1   | Edge content cache             |
| `RATE_LIMIT`  | KV   | Distributed rate limiting      |

### Environment Variables (Worker)

| Variable         | Value                                                      |
| ---------------- | ---------------------------------------------------------- |
| `BACKEND_URL`    | `https://workspacesyrabit-production-0ddc.up.railway.app`  |
| `D1_SYNC_SECRET` | Shared secret with backend for D1 sync                     |

### Redeploy Worker

```bash
cd workers/edge-proxy
wrangler deploy
```

## Backend — Railway (Docker)

The backend is hosted on Railway using the Dockerfile in `artifacts/syrabit-backend`.

### Railway Configuration

| Setting            | Value                                |
| ------------------ | ------------------------------------ |
| Root Directory     | `artifacts/syrabit-backend`          |
| Builder            | Dockerfile (auto-detected)           |
| Health Check Path  | `/api/health`                        |
| Health Check Timeout | 300s                               |
| Restart Policy     | On failure (max 5 retries)           |
| Replicas           | 1                                    |

### Required Environment Variables (Railway)

| Variable              | Description                                                         |
| --------------------- | ------------------------------------------------------------------- |
| `MONGO_URL`           | MongoDB Atlas connection string                                     |
| `DB_NAME`             | MongoDB database name (e.g. `test_database`)                        |
| `JWT_SECRET`          | Random secret (`openssl rand -hex 48`)                              |
| `ADMIN_JWT_SECRET`    | Different random secret                                             |
| `ADMIN_EMAILS`        | Comma-separated admin emails                                        |
| `ADMIN_PASSWORDS`     | Comma-separated admin passwords (matching order)                    |
| `ADMIN_NAMES`         | Comma-separated admin display names                                 |
| `CORS_ORIGINS`        | `https://syrabit.ai,https://www.syrabit.ai,https://api.syrabit.ai` |
| `FRONTEND_URL`        | `https://syrabit.ai`                                                |
| `SECURE_COOKIES`      | `true`                                                              |
| `COOKIE_DOMAIN`       | `.syrabit.ai`                                                       |

### Database & Cache Variables

| Variable                   | Description                        |
| -------------------------- | ---------------------------------- |
| `DATABASE_URL`             | PostgreSQL connection string       |
| `SUPABASE_URL`             | Supabase project URL               |
| `SUPABASE_SERVICE_KEY`     | Supabase service role key          |
| `SUPABASE_ANON_KEY`        | Supabase anonymous key             |
| `UPSTASH_REDIS_REST_URL`   | Upstash Redis REST URL             |
| `UPSTASH_REDIS_REST_TOKEN` | Upstash Redis REST token           |

### Edge Sync Variables

| Variable           | Description                                      |
| ------------------ | ------------------------------------------------ |
| `D1_SYNC_SECRET`   | Same secret as in the Worker's `wrangler.toml`   |
| `EDGE_WORKER_URL`  | `https://api.syrabit.ai`                         |

### AI Provider Keys

| Variable              | Provider               |
| --------------------- | ---------------------- |
| `GROQ_API_KEY`        | Groq (primary chat)    |
| `GROQ_API_KEY_2`      | Groq (fallback)        |
| `CEREBRAS_API_KEY`    | Cerebras               |
| `SARVAM_API_KEY`      | Sarvam AI              |
| `SARVAM_API_KEY_2`    | Sarvam AI (fallback)   |
| `GEMINI_API_KEY`      | Google Gemini          |
| `OPENROUTER_API_KEY`  | OpenRouter             |
| `XAI_API_KEY`         | xAI (Grok)             |
| `VOYAGE_API_KEY`      | Voyage AI (embeddings) |

### Auth, Payments & Email

| Variable                  | Provider               |
| ------------------------- | ---------------------- |
| `GOOGLE_CLIENT_ID`        | Google OAuth           |
| `GOOGLE_CLIENT_SECRET`    | Google OAuth           |
| `RAZORPAY_KEY_ID`         | Razorpay payments      |
| `RAZORPAY_KEY_SECRET`     | Razorpay secret        |
| `RAZORPAY_WEBHOOK_SECRET` | Razorpay webhook       |
| `RESEND_API_KEY`          | Resend (email)         |

### Server Tuning

| Variable             | Default   | Description                    |
| -------------------- | --------- | ------------------------------ |
| `PORT`               | `8000`    | Server port (Railway injects)  |
| `GUNICORN_WORKERS`   | auto      | Gunicorn worker count          |
| `GUNICORN_THREADS`   | `2`       | Threads per worker             |
| `LOG_LEVEL`          | `warning` | Gunicorn log level             |
| `LLM_MAX_CONCURRENT` | `40`     | Max concurrent LLM requests    |

### Redeploy Backend

Push to the connected GitHub branch. Railway auto-deploys on push.
Or manually: Railway dashboard → Deployments → Redeploy.

## DNS — Cloudflare

All DNS is managed via Cloudflare (the domain's nameservers point to Cloudflare).

| Record | Name              | Target / Value                              | Proxy |
| ------ | ----------------- | ------------------------------------------- | ----- |
| CNAME  | `syrabit.ai`      | `<your-pages-project>.pages.dev`            | Yes   |
| CNAME  | `www`              | `syrabit.ai`                                | Yes   |
| Worker | `api.syrabit.ai/*` | Route to `syrabit-edge` Worker              | —     |

The Worker route for `api.syrabit.ai/*` is configured in `wrangler.toml`.

## Streaming (SSE)

The edge proxy passes SSE responses from `/api/ai/chat/stream` (and all non-cached routes) straight through without buffering. The Worker returns `backendResp.body` as a `ReadableStream` directly, preserving the `text/event-stream` content type from the backend.

## Webhook URLs

Configure these callback URLs in the respective payment provider dashboards:

| Provider | Webhook URL                                    |
| -------- | ---------------------------------------------- |
| Razorpay | `https://api.syrabit.ai/api/webhooks/razorpay` |
| Stripe   | `https://api.syrabit.ai/api/webhooks/stripe`   |

Both endpoints verify signatures using their respective secrets.

## Verification Checklist

- [ ] `https://syrabit.ai` loads the React SPA
- [ ] `https://api.syrabit.ai/api/health` returns `{"status":"ok"}`
- [ ] `https://api.syrabit.ai/api/content/boards` returns content data
- [ ] Browser console shows no CORS errors
- [ ] AI chat streaming works end-to-end
- [ ] Login/signup flows work (cookies set correctly)
- [ ] D1 sync succeeds from admin panel
