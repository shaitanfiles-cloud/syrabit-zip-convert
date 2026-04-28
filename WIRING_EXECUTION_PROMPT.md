# Master Prompt: Wire Cloudflare Deployments for Pydantic-Settings Configuration

## Objective

Wire all Cloudflare Pages, Edge Worker, and backend deployments to support the centralized pydantic-settings configuration system implemented in `config.py`. Ensure seamless configuration synchronization across all components with proper validation, security, and deployment workflows.

## Context

The backend has been migrated to use pydantic-settings for centralized, validated configuration (`artifacts/syrabit-backend/config.py`). This change requires:
1. Edge Worker secrets to align with backend shared secrets
2. Pages build variables to exclude sensitive data
3. Deployment workflows to validate configuration before deploy
4. Proper secret synchronization between components

## Current State Analysis

### Components Identified
- ✅ **Backend**: `/workspace/artifacts/syrabit-backend/` - FastAPI with pydantic-settings config
- ✅ **Edge Worker**: `/workspace/workers/edge-proxy/` - Wrangler-based proxy with `wrangler.toml`
- ✅ **Frontend Pages**: `/workspace/artifacts/syrabit/` - Vite app with Cloudflare Pages deployment
- ✅ **CI/CD**: `.github/workflows/edge-proxy-deploy.yml` - GitHub Actions pipeline
- ✅ **Pages Config**: `artifacts/syrabit/scripts/apply-pages-config.mjs` - Configuration script

### Existing Documentation
- ✅ `/workspace/CLOUDFLARE_DEPLOYMENT_WIRING.md` - Comprehensive wiring guide (created)
- ✅ `/workspace/ENVIRONMENT_VARIABLES.md` - Complete env var documentation
- ✅ `/workspace/workers/edge-proxy/wrangler.toml` - Edge Worker configuration
- ✅ `/workspace/artifacts/syrabit/CLOUDFLARE_PAGES.md` - Pages deployment docs

## Execution Plan

### Phase 1: Secret Alignment (Priority: CRITICAL)

**Task 1.1**: Synchronize shared secrets between Edge Worker and Backend

```bash
# Navigate to edge worker directory
cd /workspace/workers/edge-proxy

# Set production secrets (must match backend ORIGIN_SHARED_SECRET and WORKERS_AI_FALLBACK_SECRET)
echo "<32-char-secret>" | wrangler secret put BACKEND_ORIGIN_SECRET
echo "<32-char-secret>" | wrangler secret put EDGE_AI_FALLBACK_SECRET
echo "<32-char-secret>" | wrangler secret put D1_SYNC_SECRET

# Set preview secrets (separate from production)
echo "<preview-secret>" | wrangler secret put BACKEND_ORIGIN_SECRET --env preview
echo "<preview-secret>" | wrangler secret put EDGE_AI_FALLBACK_SECRET --env preview
echo "<preview-secret>" | wrangler secret put D1_SYNC_SECRET --env preview

# Set synthetic probe secrets (Task #708, #898)
echo "<client-id>" | wrangler secret put SYNTHETIC_PROBE_CF_ACCESS_CLIENT_ID
echo "<client-secret>" | wrangler secret put SYNTHETIC_PROBE_CF_ACCESS_CLIENT_SECRET
echo "<admin-jwt>" | wrangler secret put SYNTHETIC_PROBE_ADMIN_JWT
echo "<webhook-url>" | wrangler secret put SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL
```

**Validation Command**:
```bash
# Verify secrets are set (won't show values, but confirms existence)
wrangler secret list
wrangler secret list --env preview
```

### Phase 2: Backend Configuration Update (Priority: CRITICAL)

**Task 2.1**: Update backend environment to match Edge Worker secrets

For **Railway**:
```bash
# Set via Railway CLI or Dashboard
railway variables set \
  ORIGIN_SHARED_SECRET="<same-as-BACKEND_ORIGIN_SECRET>" \
  WORKERS_AI_FALLBACK_SECRET="<same-as-EDGE_AI_FALLBACK_SECRET>" \
  D1_SYNC_SECRET="<same-as-D1_SYNC_SECRET>" \
  D1_SYNC_SECRET_PREVIEW="<same-as-preview-D1_SYNC_SECRET>" \
  EDGE_WORKER_URL="https://syrabit-edge.<account>.workers.dev" \
  EDGE_WORKER_PREVIEW_URL="https://syrabit-edge-preview.<account>.workers.dev"
```

For **Cloud Run**:
```bash
# Create/update secrets in Secret Manager
echo -n "<secret-value>" | gcloud secrets create origin-shared-secret --data-file=- --replication-policy="automatic" || gcloud secrets versions add origin-shared-secret --data-file=-

# Deploy with secret bindings
gcloud run deploy syrabit-api \
  --set-env-vars="ORIGIN_SHARED_SECRET=$(gcloud secrets versions access latest --secret=origin-shared-secret)" \
  --set-env-vars="WORKERS_AI_FALLBACK_SECRET=$(gcloud secrets versions access latest --secret=workers-ai-fallback-secret)" \
  --set-env-vars="D1_SYNC_SECRET=$(gcloud secrets versions access latest --secret=d1-sync-secret)" \
  --set-env-vars="EDGE_WORKER_URL=https://syrabit-edge.<account>.workers.dev" \
  --set-env-vars="EDGE_WORKER_PREVIEW_URL=https://syrabit-edge-preview.<account>.workers.dev" \
  --set-env-vars="D1_SYNC_SECRET_PREVIEW=$(gcloud secrets versions access latest --secret=d1-sync-secret-preview)"
```

**Task 2.2**: Validate pydantic-settings configuration loads correctly

```bash
cd /workspace/artifacts/syrabit-backend

# Test configuration loading
python -c "from config import env; print('✅ Config loaded successfully'); print(f'JWT_SECRET length: {len(env.JWT_SECRET)}'); print(f'MONGO_URL present: {bool(env.MONGO_URL)}')"

# Run validation tests
python -m pytest tests/test_config_validation.py -v
```

### Phase 3: Pages Configuration Hardening (Priority: HIGH)

**Task 3.1**: Apply Pages build configuration with proper variable separation

```bash
cd /workspace/artifacts/syrabit

# Set required environment variables
export CLOUDFLARE_ACCOUNT_ID="<your-account-id>"
export CF_PAGES_API_TOKEN="<pages-edit-token>"
export VITE_BACKEND_URL="https://api.syrabit.ai"
export VITE_GA4_ID="G-XXXXXXXXXX"  # Must match /^G-[A-Z0-9]{6,12}$/

# Dry run first (see planned changes)
node scripts/apply-pages-config.mjs

# Apply configuration (strips dangerous secrets, sets safe build vars)
node scripts/apply-pages-config.mjs --apply

# Optional: Apply + trigger deployment
node scripts/apply-pages-config.mjs --deploy
```

**Task 3.2**: Verify no sensitive variables are exposed on Pages

```bash
# Check current Pages env vars via API
curl -X GET "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/pages/projects/syrabit-analytics" \
  -H "Authorization: Bearer ${CF_PAGES_API_TOKEN}" \
  -H "Content-Type: application/json" | jq '.result.deployment_configs.production.env_vars | keys'

# Should NOT include: CF_ANALYTICS_API_TOKEN, D1_SYNC_SECRET, JWT_SECRET, etc.
# SHOULD include: NODE_ENV, VITE_BACKEND_URL, VITE_GA4_ID, etc.
```

### Phase 4: Deployment Workflow Integration (Priority: HIGH)

**Task 4.1**: Verify GitHub Actions pipeline has required secrets

Required **GitHub Repo Secrets** (`Settings → Secrets and variables → Actions → Secrets`):
- `CLOUDFLARE_API_TOKEN` - Workers Scripts:Edit, KV:Edit, D1:Edit, AI:Edit
- `CLOUDFLARE_ACCOUNT_ID` - Account ID
- `D1_SYNC_SECRET` - Preview environment value
- `AI_FALLBACK_SECRET` - Preview environment value
- `D1_SYNC_SECRET_PROD` - Production environment value
- `AI_FALLBACK_SECRET_PROD` - Production environment value

Required **GitHub Variables** (`Settings → Secrets and variables → Actions → Variables`):
- `CF_WORKERS_SUBDOMAIN` - e.g., "syrabit-edge"

Required **GitHub Environment** (`Settings → Environments`):
- `production` - Configure with required reviewers for manual approval gate

**Task 4.2**: Test the complete deployment pipeline

```bash
# Trigger preview deployment manually
cd /workspace/workers/edge-proxy
pnpm run deploy:preview:dry  # Dry run first

# Deploy preview
pnpm run deploy:preview

# Run smoke tests against preview
pnpm run smoke:preview

# If green, deploy production (or let CI handle it)
pnpm run deploy
```

### Phase 5: D1 Sync Fan-Out Configuration (Priority: MEDIUM)

**Task 5.1**: Enable automatic D1 sync to both prod and preview

Backend will automatically fan out if these vars are set:

```bash
# On Railway/Cloud Run backend
EDGE_WORKER_URL=https://syrabit-edge.<account>.workers.dev
EDGE_WORKER_PREVIEW_URL=https://syrabit-edge-preview.<account>.workers.dev
D1_SYNC_SECRET=<prod-secret>
D1_SYNC_SECRET_PREVIEW=<preview-secret>
```

**Task 5.2**: Verify D1 drift check passes

```bash
cd /workspace/workers/edge-proxy

# Check for migration drift between prod and preview
pnpm run d1:check-drift

# If drift detected, apply migrations
pnpm dlx wrangler d1 migrations apply syrabit-content --remote
pnpm dlx wrangler d1 migrations apply syrabit-content-preview --remote

# Re-check
pnpm run d1:check-drift
```

### Phase 6: End-to-End Validation (Priority: CRITICAL)

**Task 6.1**: Run comprehensive smoke tests

```bash
# Edge Worker health checks
curl -sI https://api.syrabit.ai/api/health | grep "200 OK" && echo "✅ Health endpoint OK"
curl -sI https://api.syrabit.ai/api/content/boards | grep "200 OK" && echo "✅ Content API OK"

# Test D1 sync authentication
curl -s https://api.syrabit.ai/api/edge/kv-usage \
  -H "X-D1-Sync-Secret: <D1_SYNC_SECRET>" | jq '.success' && echo "✅ D1 sync auth OK"

# Test AI fallback authentication
curl -s -X POST https://api.syrabit.ai/api/ai/fallback/chat \
  -H "Content-Type: application/json" \
  -H "X-Edge-AI-Secret: <EDGE_AI_FALLBACK_SECRET>" \
  -d '{"messages":[{"role":"user","content":"test"}]}' | jq '.success' && echo "✅ AI fallback auth OK"

# Pages deployment check
curl -sI https://syrabit-zip-convert.pages.dev | grep "200 OK" && echo "✅ Pages deployment OK"
```

**Task 6.2**: Verify configuration validation on startup

```bash
cd /workspace/artifacts/syrabit-backend

# Restart backend and check logs for config validation
# Should see: "Configuration loaded successfully" without errors
# Should NOT see: "Missing required environment variable" errors

# Test missing variable detection (temporarily unset one)
unset ORIGIN_SHARED_SECRET
python -c "from config import EnvSettings; EnvSettings()" 2>&1 | grep -i "error\|missing" && echo "✅ Validation working"
# Restore
export ORIGIN_SHARED_SECRET="<value>"
```

**Task 6.3**: Monitor synthetic probes (Task #708, #898)

```bash
# Check watchdog webhook received alerts
# Visit your Slack/PagerDuty webhook destination and verify:
# - Synthetic probe pings arriving every 60 seconds
# - Bot cache hit-rate alerts (if configured)
# - No false positives from preview environment

# Manually trigger probe test
cd /workspace/workers/edge-proxy
pnpm run test-fire:watchdog
```

## Success Criteria

✅ **All phases complete when**:

1. **Secret Alignment**: All shared secrets match between Edge Worker and Backend
   - `BACKEND_ORIGIN_SECRET` = `ORIGIN_SHARED_SECRET`
   - `EDGE_AI_FALLBACK_SECRET` = `WORKERS_AI_FALLBACK_SECRET`
   - `D1_SYNC_SECRET` synchronized

2. **Configuration Validation**: Backend starts without config errors
   - Pydantic validation passes on startup
   - All required fields present and valid format
   - No fallback to unsafe defaults

3. **Pages Security**: No sensitive data in Pages build logs
   - `apply-pages-config.mjs` strips all dangerous vars
   - Build logs show only public VITE_* variables
   - GA4 ID properly formatted and applied

4. **Deployment Pipeline**: CI/CD runs end-to-end successfully
   - Preview deploy + smoke test passes automatically
   - Production deploy waits for manual approval
   - Auto-rollback armed if smoke-prod fails

5. **D1 Sync**: Both prod and preview databases stay in sync
   - No drift detected by `d1:check-drift`
   - Backend CRUD operations fan out to both environments
   - Preview smoke tests show non-zero content counts

6. **Monitoring Active**: Synthetic probes firing and alerting
   - Watchdog webhook receiving pings every 60 seconds
   - Bot cache hit-rate monitoring active
   - Alerts route to correct Slack/PagerDuty channel

## Rollback Plan

If any phase fails:

### Edge Worker Rollback
```bash
cd /workspace/workers/edge-proxy
wrangler rollback --message "Rollback: configuration alignment failed"
wrangler rollback --env preview --message "Rollback: preview config failed"
```

### Backend Rollback
```bash
# Railway: Dashboard → Deployments → Select previous → Promote
# Cloud Run: 
gcloud run services update-traffic syrabit-api \
  --to-revisions=<previous-revision-name>=100
```

### Pages Rollback
```bash
# Dashboard: https://dash.cloudflare.com/<account>/pages/view/syrabit-analytics/deployments
# Select previous successful deployment → "Rollback to this version"
```

### Configuration Emergency Override
```bash
# Skip D1 drift check if blocking critical deploy
export SKIP_D1_DRIFT_CHECK=1
pnpm run deploy

# Disable strict GA4 validation
node scripts/apply-pages-config.mjs --apply  # Without --strict-ga4
```

## Follow-Up Tasks

After successful wiring:

1. [ ] **Rotate all shared secrets** (now that alignment is verified)
2. [ ] **Enable branch previews** for PRs (separate from main preview env)
3. [ ] **Add configuration drift alerting** (Slack notification if secrets diverge)
4. [ ] **Document secret rotation procedure** in runbook
5. [ ] **Set up automated quarterly secret rotation** workflow
6. [ ] **Add integration tests** for cross-component auth
7. [ ] **Create dashboard** showing config sync status across components

## Reference Files

- `/workspace/CLOUDFLARE_DEPLOYMENT_WIRING.md` - Full wiring documentation
- `/workspace/ENVIRONMENT_VARIABLES.md` - Complete env var reference
- `/workspace/workers/edge-proxy/wrangler.toml` - Edge Worker config
- `/workspace/artifacts/syrabit/scripts/apply-pages-config.mjs` - Pages config script
- `/workspace/.github/workflows/edge-proxy-deploy.yml` - CI/CD pipeline
- `/workspace/artifacts/syrabit-backend/config.py` - Pydantic settings schema

## Support

If issues arise during execution:

1. Check `/workspace/CLOUDFLARE_DEPLOYMENT_WIRING.md` Section 7 (Troubleshooting)
2. Review Cloudflare Worker logs: `wrangler tail --format=pretty`
3. Check backend logs for config validation errors
4. Verify GitHub Actions run logs for pipeline failures
5. Consult pydantic-settings docs: https://docs.pydantic.dev/latest/concepts/pydantic_settings/

---

**Execution Time Estimate**: 2-4 hours  
**Risk Level**: Medium (requires coordination, reversible)  
**Best Time to Execute**: Low-traffic period (evening/weekend)  
**Required Personnel**: 1 DevOps engineer, 1 backend engineer (on-call)
