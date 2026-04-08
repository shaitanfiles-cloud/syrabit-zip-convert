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
                                  • Edge caching for content/SEO routes
                                  • CORS enforcement
                                  │
                                  └──► Railway (FastAPI backend)
                                        • https://syrabit-api.up.railway.app
                                        • MongoDB, PostgreSQL, Redis
                                        • AI chat, auth, payments, admin
```

## Frontend — Cloudflare Pages

| Setting           | Value                                        |
| ----------------- | -------------------------------------------- |
| Root directory    | `artifacts/syrabit`                          |
| Build command     | `npm install && npm run build`               |
| Output directory  | `dist`                                       |
| Node version      | 20                                           |

### Environment Variables (Pages)

| Variable           | Value                        |
| ------------------ | ---------------------------- |
| `VITE_BACKEND_URL` | `https://api.syrabit.ai`     |
| `NODE_ENV`         | `production`                 |

### Redeploy Frontend

Push to the connected GitHub branch. Cloudflare Pages auto-deploys on push.

## Edge Proxy — Cloudflare Worker

The Worker lives in `workers/edge-proxy/` and is deployed via Wrangler.

### Prerequisites

1. Create a KV namespace in the Cloudflare dashboard:
   ```
   wrangler kv:namespace create RATE_LIMIT
   wrangler kv:namespace create RATE_LIMIT --preview
   ```
2. Copy the returned namespace IDs into `wrangler.toml` replacing the placeholder values.

### Redeploy Worker

```bash
cd workers/edge-proxy
wrangler deploy
```

### Environment Variables (Worker)

| Variable      | Value                                    |
| ------------- | ---------------------------------------- |
| `BACKEND_URL` | `https://syrabit-api.up.railway.app`     |

The `RATE_LIMIT` KV binding handles distributed rate limiting at the edge.

## Backend — Railway (FastAPI)

The backend runs on Railway. Configuration is in `artifacts/syrabit-backend/railway.json`.

### Railway Project Setup

1. Create a new Railway project and link the GitHub repo.
2. Set the root directory to `artifacts/syrabit-backend`.
3. Railway auto-detects `requirements.txt` and uses Nixpacks to build.
4. The start command is defined in `railway.json`: `gunicorn server:app -c gunicorn.conf.py`.
5. Health check endpoint: `/api/health`.

### Key Environment Variables (Railway)

| Variable              | Value                                                               |
| --------------------- | ------------------------------------------------------------------- |
| `PORT`                | Railway assigns automatically                                       |
| `CORS_ORIGINS`        | `https://syrabit.ai,https://www.syrabit.ai,https://api.syrabit.ai` |
| `PRODUCTION_ORIGINS`  | `https://syrabit.ai,https://www.syrabit.ai,https://api.syrabit.ai` |
| `FRONTEND_URL`        | `https://syrabit.ai`                                                |
| `SECURE_COOKIES`      | `true`                                                              |
| `COOKIE_DOMAIN`       | `.syrabit.ai`                                                       |
| `MONGO_URL`           | (your MongoDB connection string)                                    |
| `DB_NAME`             | (your MongoDB database name)                                        |
| `JWT_SECRET`          | (your JWT secret)                                                   |
| `ADMIN_JWT_SECRET`    | (your admin JWT secret)                                             |
| `PG_URL`              | (your PostgreSQL connection string)                                 |
| `UPSTASH_REDIS_URL`   | (your Upstash Redis URL)                                            |
| `UPSTASH_REDIS_TOKEN` | (your Upstash Redis token)                                          |

Plus all LLM provider API keys (GROQ, GEMINI, CEREBRAS, OPENROUTER, FIREWORKS, SARVAM, VOYAGE, EMERGENT, XAI) and payment keys (RAZORPAY, STRIPE, RESEND).

### Custom Domain (Optional)

To use a custom domain like `api-backend.syrabit.ai` directly on Railway:
1. Go to Railway project → Settings → Networking → Custom Domain.
2. Add your domain and configure the CNAME in Cloudflare DNS.

Note: The Cloudflare Worker already proxies `api.syrabit.ai` to the Railway backend, so a custom Railway domain is optional.

### Redeploy Backend

Push to GitHub. Railway auto-deploys on push (can be toggled in project settings).

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

Both endpoints verify signatures using their respective secrets (`RAZORPAY_WEBHOOK_SECRET`, `STRIPE_WEBHOOK_SECRET`).
