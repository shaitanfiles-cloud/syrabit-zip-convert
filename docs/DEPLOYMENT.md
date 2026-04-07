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
                                  └──► Render (FastAPI backend)
                                        • https://syrabit-api.onrender.com
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

| Variable      | Value                                  |
| ------------- | -------------------------------------- |
| `BACKEND_URL` | `https://syrabit-api.onrender.com`     |

The `RATE_LIMIT` KV binding handles distributed rate limiting at the edge.

## Backend — Render (FastAPI)

The backend runs on Render (Starter plan, Singapore region). Configuration is in `artifacts/syrabit-backend/render.yaml`.

### Key Environment Variables (Render)

| Variable              | Value                                                               |
| --------------------- | ------------------------------------------------------------------- |
| `CORS_ORIGINS`        | `https://syrabit.ai,https://www.syrabit.ai,https://api.syrabit.ai` |
| `PRODUCTION_ORIGINS`  | `https://syrabit.ai,https://www.syrabit.ai,https://api.syrabit.ai` |
| `FRONTEND_URL`        | `https://syrabit.ai`                                                |
| `SECURE_COOKIES`      | `true`                                                              |
| `COOKIE_DOMAIN`       | `.syrabit.ai`                                                       |

### Redeploy Backend

Push to GitHub and trigger a manual deploy in the Render dashboard (auto-deploy is disabled).

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
