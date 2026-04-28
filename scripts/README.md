# Deployment Scripts

## 🔐 wire_cloudflare_secrets.sh

**Purpose**: Generate and deploy all secrets required for Cloudflare Workers, Pages, and Backend integration with pydantic-settings configuration.

### Usage

```bash
# Make executable (if not already)
chmod +x scripts/wire_cloudflare_secrets.sh

# Run the script
./scripts/wire_cloudflare_secrets.sh
```

### What It Does

1. **Generates 4 cryptographically secure secrets** (64 characters each):
   - `AI_FALLBACK_SECRET` - For Edge Worker AI fallback routes
   - `AI_FALLBACK_SECRET_PROD` - Production-specific AI fallback
   - `BACKEND_ORIGIN_SECRET` - Edge → Backend origin authentication
   - `D1_SYNC_SECRET` - D1 database sync authentication

2. **Identifies your Worker subdomain** automatically from `wrangler.toml`

3. **Creates local development files**:
   - `workers/edge-proxy/.dev.vars` - For local `wrangler dev`

4. **Deploys secrets to Cloudflare Workers**:
   - Production environment
   - Preview environment

5. **Outputs backend environment variables** for Google Cloud Run

### Output

The script will display:
- ✅ Confirmation of secret generation
- 🌐 Detected Worker subdomain
- ☁️ Secret deployment status
- 📋 Copy-paste ready environment variables for Cloud Run

### Next Steps After Running

1. **Save the generated secrets** to your password manager immediately
2. **Copy the environment variables block** to Google Cloud Run
3. **Redeploy your backend**:
   ```bash
   gcloud run deploy syrabit-backend --update-env-vars ...
   ```
4. **Verify deployment**:
   ```bash
   curl https://your-backend-url/api/health
   ```

### Troubleshooting

**Error: `wrangler: command not found`**
```bash
npm install -g wrangler
wrangler login
```

**Error: Failed to detect worker name**
- The script will prompt you to enter it manually
- Default fallback: `syrabit-edge`

**Secrets not appearing in Worker**
```bash
# List deployed secrets
wrangler secret list
wrangler secret list --env preview
```

### Security Notes

- ⚠️ **NEVER commit `.dev.vars` or `.pages-vars.json`** - they're in `.gitignore`
- 🔒 Secrets are generated using `openssl rand -hex 32` (cryptographically secure)
- 🔄 Re-run this script anytime you need to rotate secrets
- 📝 Always save generated secrets before closing the terminal

---

**See also**: [`../CLOUDFLARE_DEPLOYMENT_CHECKLIST.md`](../CLOUDFLARE_DEPLOYMENT_CHECKLIST.md)
