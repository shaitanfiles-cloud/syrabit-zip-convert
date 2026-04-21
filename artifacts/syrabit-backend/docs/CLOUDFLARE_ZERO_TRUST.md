# Cloudflare Zero Trust for Syrabit (Task #637)

This runbook covers the operator-side provisioning of Cloudflare Zero
Trust for the admin / internal surface area, paired with the in-repo
JWT enforcement that defends the origin even if someone learns the
direct Cloud Run / Railway URL.

```
admin user
   │  (Google SSO via Access)
   ▼
team domain (syrabit.cloudflareaccess.com)
   │  ← Access Application: "Syrabit Admin" (Self-hosted, syrabit.ai/admin/*)
   │  injects: Cf-Access-Jwt-Assertion: <RS256 JWT, AUD = aud-admin-tag>
   ▼
api.syrabit.ai  (Cloudflare Worker)
   │  + X-Origin-Auth: <ORIGIN_SHARED_SECRET>
   │  + Cf-Access-Jwt-Assertion forwarded
   ▼
syrabit-backend  (FastAPI on Cloud Run)
   │
   ├── OriginSharedSecretMiddleware  → 403 if X-Origin-Auth missing
   └── get_admin_user dependency      → 401 if Cf-Access-Jwt-Assertion missing/invalid
```

The code-side enforcement is implemented in
[`cf_access.py`](../cf_access.py) and is wired into
[`auth_deps.get_admin_user`](../auth_deps.py). Tests:
[`tests/test_cf_access.py`](../tests/test_cf_access.py).

---

## 1. One-time Zero Trust setup (Cloudflare dashboard)

1. **Enable Zero Trust** on the Cloudflare account (free tier covers up
   to 50 seats — enough for the founding team plus operations partners).
   Pick a team domain such as `syrabit` →
   `https://syrabit.cloudflareaccess.com`.

2. **Add identity providers**:
   - **Google** (primary, for `@syrabit.ai` Workspace accounts): create
     OAuth credentials in Google Cloud, paste client id + secret into
     Zero Trust → Settings → Authentication → Login methods → Google.
   - **One-time PIN** (break-glass): leave enabled, restricted to a
     short allowlist of personal email addresses (founders only). This
     is the recovery path if Google SSO breaks.

3. **Define groups** (Zero Trust → Access → Access Groups):
   - `syrabit-admins` → emails ending in `@syrabit.ai` AND in the
     explicit allowlist of admin emails.
   - `syrabit-internal-ops` → superset including contractors granted
     ops access; require WARP device posture once WARP is rolled out.

## 2. Access applications

Create two **Self-hosted** Access apps:

| App name           | Hostname / Path                  | Allowed groups          | AUD env var               |
| ------------------ | -------------------------------- | ----------------------- | ------------------------- |
| Syrabit Admin      | `syrabit.ai/admin*`, `api.syrabit.ai/api/admin*` | `syrabit-admins`        | `CF_ACCESS_AUD_ADMIN`     |
| Syrabit Internal   | `api.syrabit.ai/api/_internal*` *(reserved — no routes mounted yet; see note below)* | `syrabit-internal-ops`  | `CF_ACCESS_AUD_INTERNAL`  |

> **Note on the Internal tier.** No `/api/_internal/*` routes are mounted
> in the backend at the time this task ships. The dependency
> `require_cf_access_internal` and the `CF_ACCESS_AUD_INTERNAL` env var
> are forward-looking hooks for the upcoming ops/feature-flag/kill-switch
> surface. The Access app can be created now (so the AUD tag is stable
> when the routes land) or deferred — both paths are safe.

For each app:

- **Session duration**: 8 hours (admin), 1 hour (internal).
- **Identity providers**: Google primary, OTP allowed only for break-glass.
- **Application Token AUD tag**: copy the value (a sha256 hex string)
  shown in the app's overview; this is the value you set in the
  backend env.
- **Service tokens**: create one named `syrabit-ci` for the GitHub
  Actions workflow that hits `/api/_internal/deploy-status` so CI can
  authenticate without an interactive browser session.

## 3. Cloudflare Tunnel (origin → CF, replaces public ingress)

Goal: stop publishing the Cloud Run URL altogether. Cloud Run only
accepts traffic from the tunnel.

1. In Zero Trust → Networks → Tunnels, create `syrabit-backend`.
2. Install `cloudflared` on the Cloud Run side car (or run as a
   separate Cloud Run job). Recommended: deploy the cloudflared
   container alongside the FastAPI container in the same revision
   using a sidecar. The Cloud Run service stops needing
   `--ingress=all`; switch it to `--ingress=internal` and let the
   tunnel be the only public path.
3. In the tunnel config, point `api.syrabit.ai` →
   `http://localhost:8080`.
4. Update the Cloudflare worker so it routes through the tunnel hostname
   (no change required if it already targets `api.syrabit.ai`).

## 4. Gateway DNS policy & CASB

- Gateway → Policies → DNS: block known phishing, malware, and
  cryptomining categories for any device that runs WARP under the
  syrabit team. Add an allow rule for `*.syrabit.ai`,
  `*.cloudflareaccess.com`, and the Google Workspace login hosts so
  the team isn't blocked from their own dashboard.
- CASB → Integrations: connect Google Workspace (org admin OAuth) and
  GitHub. Enable the "shadow IT" finding and route Critical/High
  findings into the existing notification pipeline using the webhook
  in admin/notifications.

## 5. Backend env vars (Railway / Cloud Run / `.env`)

Set on the FastAPI service. **All four must be set before flipping
enforcement on**:

```
CF_ACCESS_TEAM_DOMAIN=syrabit            # without the .cloudflareaccess.com suffix
CF_ACCESS_AUD_ADMIN=<admin app AUD tag>
CF_ACCESS_AUD_INTERNAL=<internal app AUD tag>
CF_ACCESS_ENFORCE=true
```

Until `CF_ACCESS_ENFORCE` is `true`, the dependency is a no-op so
existing admin sessions keep working. This is the safe rollout order:

1. Provision the team domain, IdP, Access apps (steps 1–2).
2. Roll out the backend with the env vars set but `CF_ACCESS_ENFORCE`
   unset → CF Access is live in front of the admin URL but the origin
   does **not** require it yet.
3. Confirm admins can still log in through the Access challenge.
4. Flip `CF_ACCESS_ENFORCE=true` and restart the FastAPI service.
5. Verify a curl to the bare Cloud Run URL with the
   `X-Origin-Auth` secret but **no** `Cf-Access-Jwt-Assertion` header
   returns 401 on `/api/admin/*`.

## 6. Verification (post-rollout smoke tests)

```bash
TEAM=syrabit
ADMIN_URL="https://syrabit.ai/admin/dashboard"

# 1. Unauthenticated browser hit → CF Access login challenge (302)
curl -sI "$ADMIN_URL" | head -1

# 2. Authenticated CLI access via service token (CI path)
cloudflared access curl \
  --service-token-id "$CF_SERVICE_TOKEN_ID" \
  --service-token-secret "$CF_SERVICE_TOKEN_SECRET" \
  https://api.syrabit.ai/api/_internal/health

# 3. Origin bypass attempt → must be 401
curl -sS -H "X-Origin-Auth: $ORIGIN_SHARED_SECRET" \
     https://syrabit-backend-xxx.a.run.app/api/admin/users \
  -o /dev/null -w '%{http_code}\n'    # expected: 401
```

## 7. Operational runbook

| Event                       | Action                                             |
| --------------------------- | -------------------------------------------------- |
| Admin offboarded            | Remove email from `syrabit-admins` group; their next request is 401. |
| AUD tag rotated             | Update `CF_ACCESS_AUD_ADMIN` env, restart service. |
| Team domain renamed         | Update `CF_ACCESS_TEAM_DOMAIN`, restart service.   |
| JWKS rotation               | No action — `cf_access.py` refetches on KID miss.  |
| Suspected token leak        | Revoke the user's session in Zero Trust → Sessions; revoke the matching service token if CI was the source. |
| Need temporary bypass       | Set `CF_ACCESS_ENFORCE=false`, restart, fix, restore. Document in incident log. |

## 8. What is **not** in scope here

- WARP enrollment of every team device (separate task; required before
  enforcing device-posture rules in step 1).
- Replacing the admin login form with Sign-in-with-Cloudflare
  (planned follow-up — currently the admin password stays as a second
  factor behind Access).
- Migrating end-user student auth to Access (out of scope; students
  stay on the existing Google OAuth + JWT flow).
