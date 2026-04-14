# Syrabit.ai Backend — AWS App Runner Deployment Guide

## Architecture

```
Users
  │
  ├── https://syrabit.ai ──► Cloudflare Pages (frontend PWA)
  │                            • React + Vite build
  │                            • Global CDN, edge caching
  │
  └── API calls ──► AWS App Runner (backend API)
                     • FastAPI + Gunicorn
                     • Auto-scaling, HTTPS included
                     • Connects to: MongoDB Atlas, Supabase, Upstash Redis
```

## Prerequisites

- AWS Account with billing enabled
- GitHub repo with the backend code
- All external services already set up (MongoDB Atlas, Supabase, Upstash Redis)

---

## Step 1: Prepare Your GitHub Repo

Make sure your GitHub repo has the `artifacts/syrabit-backend/` directory with:
- `Dockerfile` (already exists)
- `requirements.txt` (already exists)
- `gunicorn.conf.py` (already exists)
- `server.py` (already exists)

---

## Step 2: Create AWS App Runner Service

1. Go to [AWS App Runner Console](https://console.aws.amazon.com/apprunner)
2. Click **"Create service"**

### Source Configuration
| Setting | Value |
|---------|-------|
| Repository type | **Source code repository** |
| Connect to | **GitHub** (authorize AWS to access your repo) |
| Repository | Select your Syrabit repo |
| Branch | `main` |
| Source directory | `artifacts/syrabit-backend` |
| Deployment trigger | **Automatic** (deploys on every push) |

### Build Configuration
Choose **"Use a configuration file"** and create `artifacts/syrabit-backend/apprunner.yaml`:

```yaml
version: 1.0
runtime: python311
build:
  commands:
    build:
      - pip install --no-cache-dir -r requirements.txt
run:
  command: gunicorn server:app -c gunicorn.conf.py
  network:
    port: 8000
  env:
    - name: PORT
      value: "8000"
```

**OR** choose **"Configure all settings here"** and enter:
| Setting | Value |
|---------|-------|
| Runtime | **Python 3.11** |
| Build command | `pip install --no-cache-dir -r requirements.txt` |
| Start command | `gunicorn server:app -c gunicorn.conf.py` |
| Port | `8000` |

### Instance Configuration
| Setting | Recommended Value |
|---------|-------------------|
| CPU | **1 vCPU** (start small) |
| Memory | **2 GB** (MongoDB + AI calls need memory) |
| Min instances | **1** (keeps one instance warm — no cold starts) |
| Max instances | **4** (scales with traffic) |

### Health Check
| Setting | Value |
|---------|-------|
| Protocol | **HTTP** |
| Path | `/api/health` |
| Interval | **20 seconds** |
| Timeout | **10 seconds** |
| Healthy threshold | **1** |
| Unhealthy threshold | **3** |

---

## Step 3: Add Environment Variables

In App Runner → **Configuration** → **Environment variables**, add ALL of these:

### Required (app won't start without these)

| Variable | Value | Where to find it |
|----------|-------|-------------------|
| `MONGO_URL` | `mongodb+srv://...` | MongoDB Atlas → Connect → Connection String |
| `DB_NAME` | `test_database` | Your MongoDB database name |
| `JWT_SECRET` | (generate a random 64-char string) | `openssl rand -hex 32` |
| `ADMIN_JWT_SECRET` | (generate a different random string) | `openssl rand -hex 32` |
| `ADMIN_PASSWORDS` | Your admin password(s) | Comma-separated |
| `ADMIN_EMAILS` | `admin@syrabit.ai` | Comma-separated |
| `ADMIN_NAMES` | `Administrator` | Comma-separated |

### Database & Cache

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | Your Supabase/PostgreSQL connection string |
| `SUPABASE_URL` | `https://czeznmqogtwecidhpysa.supabase.co` |
| `SUPABASE_SERVICE_KEY` | Your Supabase service key |
| `UPSTASH_REDIS_REST_URL` | Your Upstash Redis URL |
| `UPSTASH_REDIS_REST_TOKEN` | Your Upstash Redis token |

### AI Provider Keys

| Variable | Value |
|----------|-------|
| `GROQ_API_KEY` | Your Groq API key |
| `GROQ_API_KEY_2` | Second Groq key (if available) |
| `CEREBRAS_API_KEY` | Your Cerebras key |
| `GEMINI_API_KEY` | Your Gemini key |
| `GEMINI_API_KEY_2` | Second Gemini key (if available) |
| `SARVAM_API_KEY` | Your Sarvam key |
| `SARVAM_API_KEY_2` | Second Sarvam key |
| `FIREWORKS_API_KEY` | Your Fireworks key |
| `OPENROUTER_API_KEY` | Your OpenRouter key |
| `VOYAGE_API_KEY` | Your Voyage AI key |
| `EMERGENT_API_KEY` | Your Emergent key |

### Auth & Payments

| Variable | Value |
|----------|-------|
| `GOOGLE_CLIENT_ID` | Your Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Your Google OAuth secret |
| `RAZORPAY_KEY_ID` | Your Razorpay key |
| `RAZORPAY_KEY_SECRET` | Your Razorpay secret |
| `RAZORPAY_WEBHOOK_SECRET` | Your Razorpay webhook secret |
| `RESEND_API_KEY` | Your Resend email key |

### App Configuration

| Variable | Value |
|----------|-------|
| `FRONTEND_URL` | `https://syrabit.ai` |
| `CORS_ORIGINS` | `https://syrabit.ai,https://www.syrabit.ai` |
| `SECURE_COOKIES` | `true` |
| `LOG_LEVEL` | `info` |
| `GUNICORN_WORKERS` | `2` |

---

## Step 4: Deploy

1. Click **"Create & deploy"**
2. Wait 5-10 minutes for the first build
3. App Runner will show your service URL: `https://xxxxxxxx.us-east-1.awsapprunner.com`
4. Test it: visit `https://YOUR-URL/api/health` — should return `200 OK`

---

## Step 5: Update Cloudflare Pages

After your App Runner service is running:

1. Go to **Cloudflare Pages** → Your project → **Settings** → **Environment variables**
2. Update these variables:

| Variable | New Value |
|----------|-----------|
| `VITE_BACKEND_URL` | `https://YOUR-APPRUNNER-URL.awsapprunner.com` |
| `VITE_WORKER_API_URL` | `https://YOUR-APPRUNNER-URL.awsapprunner.com` |

3. Trigger a redeploy (push a commit or click "Retry deployment")

---

## Step 6: Custom Domain (Optional)

If you want `api.syrabit.ai` to point to App Runner:

1. In App Runner → **Custom domains** → **Link domain**
2. Enter `api.syrabit.ai`
3. AWS gives you a CNAME record to add
4. Go to **Cloudflare DNS** → Add CNAME record:
   - Name: `api`
   - Target: (the CNAME value AWS provides)
   - Proxy: **OFF** (DNS only — grey cloud)
5. Wait for validation (5-30 minutes)
6. Update CF Pages env vars to use `https://api.syrabit.ai`

---

## Estimated Costs

| Resource | Cost |
|----------|------|
| App Runner (1 vCPU, 2GB, 1 min instance) | ~$30-40/month |
| App Runner (auto-scale to 0, no min instance) | ~$5-15/month (but cold starts ~30s) |
| MongoDB Atlas (M0 free tier) | Free |
| Supabase (free tier) | Free |
| Upstash Redis (free tier) | Free |
| Cloudflare Pages | Free |

**Tip:** Start with 1 minimum instance to avoid cold starts. If costs are a concern, set min instances to 0 — the first request after idle takes ~30 seconds but subsequent requests are fast.

---

## Troubleshooting

### Build fails
- Check that `artifacts/syrabit-backend/` is set as the source directory
- Ensure `requirements.txt` has all dependencies

### Health check fails
- Verify port is `8000`
- Check the health check path is `/api/health`
- Increase the start period — the app needs ~30s to initialize MongoDB connections

### CORS errors
- Make sure `CORS_ORIGINS` includes `https://syrabit.ai`
- Make sure `FRONTEND_URL` is `https://syrabit.ai`

### MongoDB timeout
- MongoDB Atlas free tier (M0) can be slow on cold connections
- The app has built-in retry logic for the library bundle pre-warm
- Consider upgrading to M2/M5 for better performance ($9-25/month)
