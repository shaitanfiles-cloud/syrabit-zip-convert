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
                                  └──► Replit (FastAPI backend)
                                        • Replit Deployments
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
| `BACKEND_URL` | `https://<your-repl-slug>.<your-username>.replit.app` (Replit deployment URL) |

The `RATE_LIMIT` KV binding handles distributed rate limiting at the edge.

## Backend — Replit Deployments

The backend is hosted on Replit. Use Replit's built-in Deployments feature to publish the FastAPI backend.

### Replit Project Setup

1. The backend lives in `artifacts/syrabit-backend`.
2. Configure the run command to start gunicorn/uvicorn.
3. Use Replit Deployments to publish the backend.
4. Health check endpoint: `GET /api/health`.

### Required Environment Variables (Replit)

| Variable              | Description                                                         |
| --------------------- | ------------------------------------------------------------------- |
| `PORT`                | Replit assigns automatically                                        |
| `MONGO_URL`           | MongoDB Atlas connection string                                     |
| `DB_NAME`             | MongoDB database name (e.g. `syrabit_prod`)                         |
| `JWT_SECRET`          | Random 96-char hex (`python3 -c "import secrets; print(secrets.token_hex(48))"`) |
| `ADMIN_JWT_SECRET`    | Different random 96-char hex                                        |
| `ADMIN_EMAILS`        | Comma-separated admin emails                                        |
| `ADMIN_PASSWORDS`     | Comma-separated admin passwords (matching order)                    |
| `ADMIN_NAMES`         | Comma-separated admin display names                                 |
| `CORS_ORIGINS`        | `https://syrabit.ai,https://www.syrabit.ai,https://api.syrabit.ai` |
| `PRODUCTION_ORIGINS`  | Same as CORS_ORIGINS                                                |
| `FRONTEND_URL`        | `https://syrabit.ai`                                                |
| `SECURE_COOKIES`      | `true`                                                              |
| `COOKIE_DOMAIN`       | `.syrabit.ai`                                                       |

### Optional Environment Variables

| Variable              | Description                                                         |
| --------------------- | ------------------------------------------------------------------- |
| `PG_URL` / `DATABASE_URL` | PostgreSQL connection string (Supabase)                         |
| `SUPABASE_URL`        | Supabase project URL                                                |
| `SUPABASE_SERVICE_KEY` | Supabase service role key                                          |
| `UPSTASH_REDIS_REST_URL` | Upstash Redis REST URL                                           |
| `UPSTASH_REDIS_REST_TOKEN` | Upstash Redis REST token                                      |
| `GUNICORN_WORKERS`    | Number of gunicorn workers (default: 4)                             |
| `GUNICORN_THREADS`    | Number of threads per worker (default: 4)                           |
| `LOG_LEVEL`           | Gunicorn log level (default: `warning`)                             |

### API Keys (Replit Secrets)

| Variable              | Provider               |
| --------------------- | ---------------------- |
| `GROQ_API_KEY`        | Groq (primary chat)    |
| `GROQ_API_KEY_2`      | Groq (fallback)        |
| `CEREBRAS_API_KEY`    | Cerebras               |
| `SARVAM_API_KEY`      | Sarvam AI              |
| `SARVAM_API_KEY_2`    | Sarvam AI (fallback)   |
| `GEMINI_API_KEY`      | Google Gemini          |
| `GEMINI_API_KEY_2`    | Google Gemini (backup) |
| `OPENROUTER_API_KEY`  | OpenRouter             |
| `FIREWORKS_API_KEY`   | Fireworks AI           |
| `XAI_API_KEY`         | xAI (Grok)             |
| `EMERGENT_API_KEY`    | Emergent AI            |
| `VOYAGE_API_KEY`      | Voyage AI (embeddings) |
| `RAZORPAY_KEY_ID`     | Razorpay payments      |
| `RAZORPAY_KEY_SECRET` | Razorpay secret        |
| `RAZORPAY_WEBHOOK_SECRET` | Razorpay webhook   |
| `RESEND_API_KEY`      | Resend (email)         |
| `GOOGLE_CLIENT_ID`    | Google OAuth           |
| `GOOGLE_CLIENT_SECRET`| Google OAuth           |

### Custom Domain (Optional)

The Cloudflare Worker proxies `api.syrabit.ai` to the Replit backend, so a custom domain on Replit is optional. If needed, configure a custom domain in Replit Deployments settings and add the CNAME in Cloudflare DNS.

### Redeploy Backend

Use Replit's Deployments feature to redeploy the backend after changes.

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
