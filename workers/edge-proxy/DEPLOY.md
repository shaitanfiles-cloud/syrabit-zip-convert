# Cloudflare Deployment Guide — syrabit.ai

## Architecture
- **Cloudflare Pages** → serves frontend at `syrabit.ai`
- **Cloudflare Worker** → edge API proxy at `api.syrabit.ai` (with D1 cache)
- **Replit Backend** → origin API server

---

## Part 1: Deploy Frontend on Cloudflare Pages

### Step 1: Push code to GitHub
Make sure your code is pushed to a GitHub repository.

### Step 2: Connect to Cloudflare Pages
1. Go to https://dash.cloudflare.com → **Workers & Pages** → **Create**
2. Select **Pages** → **Connect to Git**
3. Select your GitHub repo
4. Configure build settings:
   - **Project name**: `syrabit`
   - **Production branch**: `main`
   - **Framework preset**: None
   - **Build command**: `cd artifacts/syrabit && npm install && npm run build`
   - **Build output directory**: `artifacts/syrabit/dist`
5. Add environment variables:
   - `VITE_BACKEND_URL` = `https://api.syrabit.ai` (after Worker is deployed)
   - `VITE_WORKER_API_URL` = `https://api.syrabit.ai`
   - `VITE_GA4_ID` = your GA4 measurement ID
   - `NODE_VERSION` = `20`
6. Click **Save and Deploy**

### Step 3: Add custom domain
1. In Pages project → **Custom domains** → **Set up a custom domain**
2. Enter `syrabit.ai`
3. Cloudflare will auto-configure DNS (your domain must be on Cloudflare DNS)
4. Also add `www.syrabit.ai` and set up redirect to `syrabit.ai`

---

## Part 2: Deploy Edge Worker (api.syrabit.ai)

Run these commands from your local machine (not Replit):

### Step 1: Install and login
```bash
npm install -g wrangler
wrangler login
```

### Step 2: Create D1 database
```bash
cd workers/edge-proxy
npm install
wrangler d1 create syrabit-content
```
Copy the `database_id` from the output.

### Step 3: Create KV namespace
```bash
wrangler kv:namespace create RATE_LIMIT
# Copy the id from output

wrangler kv:namespace create RATE_LIMIT --preview
# Copy the preview_id from output
```

### Step 4: Generate sync secret
```bash
openssl rand -hex 32
```
Copy the output.

### Step 5: Update wrangler.toml
Replace the placeholder values in `workers/edge-proxy/wrangler.toml`:
- `REPLACE_WITH_D1_DATABASE_ID` → your D1 database ID
- `REPLACE_WITH_KV_NAMESPACE_ID` → your KV namespace ID
- `REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID` → your KV preview ID
- `REPLACE_WITH_SECURE_RANDOM_SECRET` → your generated secret
- `REPLIT_DEPLOY_URL` → your Replit published URL (e.g., `https://xxx.replit.app`)

### Step 6: Apply D1 migrations
```bash
wrangler d1 migrations apply syrabit-content --remote
```

### Step 7: Deploy
```bash
wrangler deploy
```

### Step 8: Set D1_SYNC_SECRET on backend
Add the same sync secret to your Replit backend as an environment variable:
- Key: `D1_SYNC_SECRET`
- Value: the same secret from Step 4

Also add:
- Key: `EDGE_WORKER_URL`
- Value: `https://api.syrabit.ai`

---

## Part 3: Verify

1. Visit `https://syrabit.ai` — frontend should load
2. Visit `https://api.syrabit.ai/api/health` — should proxy to backend
3. Trigger D1 sync: from admin, or POST to `/api/admin/d1-sync`
4. Content reads should now be served from D1 edge cache

---

## DNS Records (auto-configured if domain is on Cloudflare)
- `syrabit.ai` → Cloudflare Pages
- `api.syrabit.ai` → Cloudflare Worker (via route pattern)
