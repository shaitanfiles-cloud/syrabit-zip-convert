# Syrabit.ai Backend — Railway Deployment Guide

## Prerequisites
- Railway account (https://railway.app)
- GitHub repo connected to Railway (recommended) OR Railway CLI
- All environment variables from `.env.example` ready

## Step 1: Create Railway Project (Dashboard — Recommended)

1. Go to https://railway.app/new
2. Click **"Deploy from GitHub repo"**
3. Select your Syrabit repository
4. **CRITICAL**: After the service is created, go to **Settings > Source**:
   - Set **Root Directory** to: `artifacts/syrabit-backend`
   - This ensures Railway finds the Dockerfile and Python code (not the root package.json)
5. Railway will auto-detect the Dockerfile and start building

### Alternative: Railway CLI

```bash
railway login
railway init
# Select "Empty Project", name: syrabit-backend

cd artifacts/syrabit-backend
railway link
railway up
```

> **If the CLI deploy fails with `pnpm: not found`**: Railway is reading the
> root `package.json` instead of the backend's `Dockerfile`. You MUST set
> the Root Directory to `artifacts/syrabit-backend` in the Railway dashboard
> under **Settings > Source > Root Directory**.

## Step 3: Set Environment Variables

### Option A: Railway Dashboard (Recommended)
1. Go to https://railway.app/dashboard
2. Click your `syrabit-backend` service
3. Go to **Variables** tab
4. Click **RAW Editor** and paste all variables from `.env.example` with real values

### Option B: Railway CLI
```bash
# Core databases
railway variables set MONGO_URL="mongodb+srv://..."
railway variables set DB_NAME="test_database"
railway variables set DATABASE_URL="postgresql://..."
railway variables set UPSTASH_REDIS_REST_URL="https://..."
railway variables set UPSTASH_REDIS_REST_TOKEN="AXxx..."
railway variables set SUPABASE_URL="https://xxx.supabase.co"
railway variables set SUPABASE_SERVICE_KEY="eyJ..."
railway variables set SUPABASE_ANON_KEY="eyJ..."

# Security
railway variables set JWT_SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(48))')"
railway variables set ADMIN_JWT_SECRET="$(python3 -c 'import secrets;print(secrets.token_hex(48))')"
railway variables set ADMIN_EMAILS="admin@syrabit.ai"
railway variables set ADMIN_PASSWORDS="your-secure-password"
railway variables set ADMIN_NAMES="Admin"
railway variables set GOOGLE_CLIENT_ID="xxx.apps.googleusercontent.com"
railway variables set GOOGLE_CLIENT_SECRET="GOCSPx-xxx"

# CORS & Cookies
railway variables set CORS_ORIGINS="https://syrabit.ai,https://www.syrabit.ai,https://api.syrabit.ai"
railway variables set SECURE_COOKIES="true"
railway variables set COOKIE_DOMAIN=".syrabit.ai"
railway variables set FRONTEND_URL="https://syrabit.ai"

# AI Providers
railway variables set GROQ_API_KEY="gsk_xxx"
railway variables set GROQ_API_KEY_2="gsk_xxx"
railway variables set GEMINI_API_KEY="AIza..."
railway variables set CEREBRAS_API_KEY="csk-xxx"
railway variables set SARVAM_API_KEY="xxx"
railway variables set SARVAM_API_KEY_2="xxx"
railway variables set OPENROUTER_API_KEY="sk-or-xxx"

# Vertex AI Gemini Flash chat (Task #607) — recommended for low TTFT.
# Auth on Railway is via the inline JSON blob below (raw service-account
# key, single-line). Once VERTEX_PROJECT_ID is set the chat stream uses
# Vertex by default; the legacy SLM pool above is the automatic fallback.
railway variables set VERTEX_PROJECT_ID="your-gcp-project"
railway variables set VERTEX_LOCATION="us-central1"
railway variables set VERTEX_GEMINI_MODEL="gemini-2.5-flash"
railway variables set VERTEX_SERVICE_ACCOUNT_JSON='{"type":"service_account",...}'
railway variables set CHAT_DEFAULT_MODEL="vertex/gemini-flash"

# Payments & Email
railway variables set RAZORPAY_KEY_ID="rzp_live_xxx"
railway variables set RAZORPAY_KEY_SECRET="xxx"
railway variables set RAZORPAY_WEBHOOK_SECRET="xxx"
railway variables set RESEND_API_KEY="re_xxx"
railway variables set EMAIL_FROM="noreply@syrabit.ai"

# Edge Worker
railway variables set D1_SYNC_SECRET="your-sync-secret"
railway variables set EDGE_WORKER_URL="https://api.syrabit.ai"

# Server Tuning
railway variables set PORT="8000"
railway variables set GUNICORN_WORKERS="2"
railway variables set LOG_LEVEL="warning"
railway variables set LLM_MAX_CONCURRENT="40"
```

## Step 4: Generate a Public Domain

```bash
# Generate a Railway domain
railway domain
# Output: syrabit-backend-production.up.railway.app
```

Or in the dashboard: **Settings > Networking > Generate Domain**

### Custom Domain (Optional)
1. In Railway dashboard: **Settings > Networking > Custom Domain**
2. Add: `backend.syrabit.ai`
3. Add the CNAME record to your DNS:
   - Type: CNAME
   - Name: backend
   - Value: (Railway provides this)

## Step 5: Update Cloudflare Edge Worker

After Railway is deployed, update the Worker's `BACKEND_URL` to point to Railway:

```bash
cd workers/edge-proxy

# Update wrangler.toml BACKEND_URL
# Set to your Railway URL, e.g.:
# BACKEND_URL = "https://workspacesyrabit-production-0ddc.up.railway.app"

# Redeploy the worker
npx wrangler deploy
```

## Step 6: Verify Deployment

```bash
# Health check
curl https://syrabit-backend-production.up.railway.app/api/health

# Expected response:
# {"status":"ok","mongo":"connected","redis":"connected","pg":"connected"}

# Test through edge worker
curl https://api.syrabit.ai/api/health
```

## Resource Recommendations

### Starter Plan (~$5/month at low traffic)
- 8 GB RAM, shared vCPU
- 512 MB disk
- Railway Hobby plan ($5/month includes $5 usage credit)

### Production Plan (~$20-50/month)
- 8 GB RAM, 2 vCPU
- `GUNICORN_WORKERS=2`
- `LLM_MAX_CONCURRENT=40`

### Cost Optimization
- The Edge Worker (Cloudflare) caches 80-90% of content reads
- Railway only handles: AI chat, auth, admin, webhooks, D1 sync
- At low traffic (<1000 DAU): expect ~$5-15/month
- At moderate traffic (1000-10000 DAU): expect ~$20-50/month

## Architecture After Deployment

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

## Troubleshooting

### Build Fails
- Check Railway build logs for pip install errors
- Ensure `requirements.txt` is in the same directory as `Dockerfile`

### Health Check Fails
- Railway start period is 300s (5 min) — startup takes ~30-60s
- Check logs: `railway logs`
- Verify all required env vars are set

### Cookies Not Working
- Ensure `COOKIE_DOMAIN=.syrabit.ai`
- Ensure `SECURE_COOKIES=true`
- Ensure Railway domain is HTTPS (it is by default)

### CORS Errors
- Add Railway domain to `CORS_ORIGINS`
- Ensure `https://syrabit.ai` and `https://api.syrabit.ai` are included
