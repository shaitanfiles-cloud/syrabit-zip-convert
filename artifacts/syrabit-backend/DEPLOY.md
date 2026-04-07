# Deploying Syrabit Backend on Hostinger VPS

## Prerequisites

- Hostinger VPS (India DC, KVM plan)
- Domain `api.syrabit.ai` managed in Cloudflare
- MongoDB Atlas cluster (managed, not on VPS)
- Upstash Redis (managed, not on VPS)

---

## 1. VPS Initial Setup

SSH into the VPS and run:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose plugin
sudo apt install -y docker-compose-plugin

# Reboot to apply group changes
sudo reboot
```

After reboot, verify:

```bash
docker --version
docker compose version
```

### Firewall

Only ports 80 and 443 need to be open (Cloudflare connects on these).
SSH (22) should remain open for management.

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

> The docker-compose.yml maps host port 80 to container port 8000
> (`"80:8000"`). Cloudflare proxies HTTPS traffic to port 80 and
> terminates SSL on its edge, so no TLS cert is needed on the VPS.

---

## 2. Cloudflare DNS

In the Cloudflare dashboard for `syrabit.ai`:

1. Add an **A record**:
   - Name: `api`
   - Content: `<VPS_IP_ADDRESS>`
   - Proxy status: **Proxied** (orange cloud)
   - TTL: Auto

2. SSL/TLS settings:
   - Encryption mode: **Full (Strict)** is recommended if you add an origin
     cert via Cloudflare Origin CA. Otherwise use **Full**.
   - Edge Certificates → Always Use HTTPS: **On**
   - Edge Certificates → Minimum TLS Version: **1.2**

3. Caching:
   - Page Rule for `api.syrabit.ai/*` → Cache Level: **Bypass**
     (API responses should not be cached at Cloudflare edge)

---

## 3. Deploy the Application

```bash
# Clone or copy the backend code to the VPS
mkdir -p ~/syrabit && cd ~/syrabit

# Copy .env.example and fill in real values
cp .env.example .env
nano .env  # fill in all CHANGE_ME values

# Build and start
docker compose up -d --build

# Verify health
curl http://localhost:8000/api/health
```

---

## 4. Update / Redeploy

```bash
cd ~/syrabit

# Pull latest code (git pull, scp, rsync — your choice)
git pull origin main

# Rebuild and restart (zero-downtime with health checks)
docker compose up -d --build

# Or if using a pre-built image from a registry:
# docker compose pull && docker compose up -d
```

---

## 5. Logs & Debugging

```bash
# Follow live logs
docker compose logs -f web

# Last 200 lines
docker compose logs --tail 200 web

# Check container status
docker compose ps

# Restart
docker compose restart web

# Full teardown and rebuild
docker compose down && docker compose up -d --build
```

---

## 6. Production Checklist

- [ ] `.env` has real values (no `CHANGE_ME` remaining)
- [ ] `COOKIE_DOMAIN` is set to `.syrabit.ai`
- [ ] `CORS_ORIGINS` includes `https://syrabit.ai,https://www.syrabit.ai,https://api.syrabit.ai`
- [ ] `FRONTEND_URL` is `https://syrabit.ai`
- [ ] Razorpay webhook URL updated to `https://api.syrabit.ai/api/webhooks/razorpay`
- [ ] Stripe webhook URL updated to `https://api.syrabit.ai/api/webhooks/stripe`
- [ ] Cloudflare A record for `api` points to VPS IP (orange-clouded)
- [ ] `curl https://api.syrabit.ai/api/health` returns `{"status":"ok"}`
- [ ] Frontend `VITE_BACKEND_URL` env var in Cloudflare Pages set to `https://api.syrabit.ai`

---

## 7. Webhook URLs

After switching to `api.syrabit.ai`, update webhook endpoints in payment provider dashboards:

| Provider | Webhook URL |
|----------|-------------|
| Razorpay | `https://api.syrabit.ai/api/webhooks/razorpay` |
| Stripe   | `https://api.syrabit.ai/api/webhooks/stripe` |

These are relative API routes — no code change is needed. Just update the
URLs in each provider's dashboard settings.

---

## Architecture

```
User → Cloudflare (SSL + DDoS) → VPS:80 → Docker:8000 (uvicorn)
                                              ↓
                                   MongoDB Atlas (managed)
                                   Upstash Redis  (managed)
                                   Supabase PG    (managed)
```

Frontend: Cloudflare Pages (`syrabit.ai`)
Backend:  Hostinger VPS via Cloudflare proxy (`api.syrabit.ai`)
