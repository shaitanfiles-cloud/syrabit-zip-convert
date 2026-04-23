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

## 0. Operator activation checklist (Task #705)

Task #702 shipped the *code-side* gate on `/api/admin/login` (fail-closed
503 if the env vars are partially set, 401 if the JWT is missing) plus
the regression tests. **Until an operator completes the steps below in
production, the protection is a no-op** — `/api/admin/login` is still
reachable on the bare Railway URL with only the origin shared secret.

This checklist must be executed by someone with **both** Cloudflare
dashboard access **and** Railway env access. The agent cannot perform
any of these steps. Tick each item in the rollout ticket:

- [ ] **Zero Trust team domain live.** Cloudflare dashboard → Zero Trust
  is enabled on the syrabit account and the team domain
  `https://syrabit.cloudflareaccess.com` resolves. (See §1.)
- [ ] **Google IdP confirmed.** Zero Trust → Settings → Authentication
  shows Google as a login method and a test login from an
  `@syrabit.ai` account succeeds end-to-end. (See §1.)
- [ ] **"Syrabit Admin" Access app exists.** Self-hosted Access app
  covers `syrabit.ai/admin*` **and** `api.syrabit.ai/api/admin*`,
  bound to the `syrabit-admins` group. (See §2.)
- [ ] **AUD tag copied.** From the Access app overview page, copy the
  Application Token AUD tag (sha256 hex). This is the value for
  `CF_ACCESS_AUD_ADMIN`.
- [ ] **(Optional) Internal Access app + AUD tag.** Only required once
  `/api/_internal/*` routes ship; the env var can be left unset
  until then (the dependency is a no-op when the AUD is empty).
- [ ] **All four env vars set on Railway production** (Project →
  syrabit-backend → Variables):
  ```
  CF_ACCESS_TEAM_DOMAIN=syrabit
  CF_ACCESS_AUD_ADMIN=<admin app AUD tag>
  CF_ACCESS_AUD_INTERNAL=<internal app AUD tag, or leave unset>
  CF_ACCESS_ENFORCE=true
  ```
  > Set `CF_ACCESS_ENFORCE=true` **last**, after the AUD tag is in
  > place. If `CF_ACCESS_ENFORCE=true` but `CF_ACCESS_AUD_ADMIN` is
  > empty, the backend fails closed with a 503 on every admin request
  > (intentional — see `cf_access._fail_closed_if_misconfigured`).
- [ ] **FastAPI restarted.** Railway → syrabit-backend → Deployments →
  Restart (or trigger a redeploy). Required because env vars are
  read at process start.
- [ ] **Diagnostics confirms enforcement is on.** From an authenticated
  admin browser session:
  ```
  GET https://api.syrabit.ai/admin/diagnostics
  ```
  Response must include `"admin_enforced": true` and
  `"admin_aud_configured": true`. If `admin_enforced` is `false`,
  one of the four env vars is missing or the service was not
  restarted.
- [ ] **Bare-origin bypass returns 401 on `/api/admin/login`.** Run the
  curl in §6 step 3 against the **bare Railway URL** (e.g.
  `https://syrabit-backend-production.up.railway.app`) with the
  `X-Origin-Auth` header set but **no** `Cf-Access-Jwt-Assertion`
  header. Expected status: `401`. This is the regression check that
  proves Task #702's gate on the login route is actually live in
  production — not just in the test suite.

Once every box is ticked, Task #705 is done. File the completed
checklist (with the diagnostics JSON and the curl output) in the
ops log so the next on-call can audit the rollout.

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

## 5. Backend env vars (Railway production — and `.env` for local)

Set on the FastAPI service in **Railway → syrabit-backend → Variables**
(or in `.env` for local development). **All four must be set before
flipping enforcement on**:

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
   returns 401 on `/api/admin/*` **including `/api/admin/login`**.
   Task #702 added the `require_cf_access_admin` dependency directly to
   the login handler so the credential check is unreachable without an
   Access JWT — closing the brute-force bypass that existed when only
   post-login admin routes were gated.

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

# 3. Origin bypass attempt → must be 401 (run against the BARE Railway
#    URL, not api.syrabit.ai, so you actually skip the Cloudflare edge)
RAILWAY_URL="https://syrabit-backend-production.up.railway.app"

curl -sS -X POST \
     -H "X-Origin-Auth: $ORIGIN_SHARED_SECRET" \
     -H "Content-Type: application/json" \
     -d '{"email":"x@x","password":"x"}' \
     "$RAILWAY_URL/api/admin/login" \
  -o /dev/null -w '%{http_code}\n'    # expected: 401 (Task #702 gate)

curl -sS -H "X-Origin-Auth: $ORIGIN_SHARED_SECRET" \
     "$RAILWAY_URL/api/admin/users" \
  -o /dev/null -w '%{http_code}\n'    # expected: 401

# 4. Enforcement state introspection (no auth required for the JSON
#    body itself; reachable through the Access challenge in a browser)
curl -sS https://api.syrabit.ai/admin/diagnostics | jq
# expected (post-rollout):
#   "admin_enforced": true,
#   "admin_aud_configured": true,
#   "team_domain": "syrabit"
```

If step 3 returns `200` or a credentials-error JSON instead of `401`,
**stop the rollout** — it means either `CF_ACCESS_ENFORCE` is not
`true` in the running process (env var not set, or the service was not
restarted after setting it) or the AUD env var is empty. Re-check §0
and §5 before continuing.

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
