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
| Need temporary bypass       | Use the break-glass paths in §7.1 (60-second recovery, no Railway access required). The Railway env-flip is the slow fallback. |

### 7.1 What to do if Cloudflare Access goes down (Task #706)

A Cloudflare Zero Trust outage, an IdP failure, or an AUD-tag misrotation
will lock every admin out of the dashboard at the exact moment they need
to react. The original "set `CF_ACCESS_ENFORCE=false` on Railway and
restart" recovery requires Railway access plus a service restart — that
can take 5–10 minutes during an active incident. The two break-glass
paths below cap recovery at **~60 seconds** and do **not** require a
FastAPI restart.

**Pre-staged inputs (one-time setup, must be done before the incident):**

1. **One-Time-PIN IdP enabled in Zero Trust** with a 2-email allowlist
   limited to founder personal email addresses (NOT `@syrabit.ai`,
   because Workspace itself may be the thing that's down). Test the OTP
   path end-to-end at provisioning time — log in once with each
   allowlisted email, confirm the inbox actually receives the code, and
   record the test in the ops log. Re-test quarterly.
2. **`CF_ACCESS_BREAK_GLASS_TOKEN`** secret set on the FastAPI service
   (one-time, never rotated mid-incident). A long random string;
   generate with `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
3. **Cloudflare Worker secret** with the same value, named e.g.
   `CF_ACCESS_BREAK_GLASS_TOKEN`. The Worker conditionally injects
   `X-Cf-Access-Break-Glass: <secret>` on `/api/admin/*` requests when
   another Worker secret (e.g. `CF_ACCESS_BREAK_GLASS_ENABLED=true`) is
   set. Both secrets are editable from the Cloudflare dashboard alone.

**Recovery path A — non-Railway (preferred, ~60s):**

1. Cloudflare dashboard → Workers & Pages → `syrabit-edge` → Settings →
   Variables and Secrets → set `CF_ACCESS_BREAK_GLASS_ENABLED=true`,
   Save and Deploy. (Worker rolls out globally in ~10s.)
2. From a **personal browser**, hit `/api/admin/login` with the normal
   admin password. The Access challenge is bypassed for the lifetime of
   the Worker flag; the admin JWT check still runs (so password and
   2FA still apply — break-glass is *not* an authentication bypass,
   only an *Access proxy* bypass).
3. Confirm via `GET /admin/diagnostics` that the response shows
   `"break_glass_active": true` and `"break_glass_source": "header"`.
   This object is the authoritative state — every CRITICAL log line
   tagged `BREAK-GLASS bypass active` is also the audit trail.
4. Once Cloudflare Access is healthy again, **flip
   `CF_ACCESS_BREAK_GLASS_ENABLED` back to `false`** on the Worker.
   Re-confirm `"break_glass_active": false`.

**Recovery path B — One-Time-PIN admin login (Railway untouchable):**

If both Workers and Railway are unreachable but the admin team domain is
still serving the OTP IdP, founders can log in via OTP (step 1 of §1)
and reach `/admin/*` directly. Use this when path A is also blocked.

**Recovery path C — Railway env-flip (legacy fallback, 5–10 min):**

1. Railway → syrabit-backend → Variables → set
   `CF_ACCESS_BREAK_GLASS=true`. Save (this triggers a redeploy).
2. After the new revision goes live, the bypass is active until the
   variable is unset. Same diagnostics signal as above.
3. Restore: delete `CF_ACCESS_BREAK_GLASS` and let the redeploy roll.

**Paging:** `/admin/diagnostics` fires the
`cf_access_break_glass_active` and `cf_access_admin_degraded` alert
types through the existing notification pipeline whenever the snapshot
is degraded on a production-provisioned environment. Subscribe the
on-call PagerDuty / Slack channel to both alert types — do **not**
silence them, since their entire purpose is to remind the team to
disable the bypass once the outage is over.

**Synthetic probe (Task #708 — required, ships in `syrabit-edge`):**
The paging rule above only runs when something actually calls
`/admin/diagnostics`. During a real outage no admin is browsing the
dashboard, so the alert never fires. The `syrabit-edge` Worker carries
a 1-minute cron (`* * * * *`) that hits the diagnostics endpoint from
outside the cluster using a CF Access service token + a long-lived
admin JWT. Implementation: `workers/edge-proxy/src/synthetic-probe.ts`.

Configuration (Cloudflare dashboard → Workers & Pages →
`syrabit-edge` → Settings → Variables and Secrets):

| Name                                       | Kind   | Purpose                                                                 |
| ------------------------------------------ | ------ | ----------------------------------------------------------------------- |
| `SYNTHETIC_PROBE_TARGET_URL`               | var    | Full URL to probe. Default: `${BACKEND_URL}/admin/diagnostics`.         |
| `SYNTHETIC_PROBE_CF_ACCESS_CLIENT_ID`      | secret | CF Access service token client id (`*.access`).                          |
| `SYNTHETIC_PROBE_CF_ACCESS_CLIENT_SECRET`  | secret | CF Access service token secret.                                          |
| `SYNTHETIC_PROBE_ADMIN_JWT`                | secret | Long-lived admin JWT signed with `ADMIN_JWT_SECRET` (1y exp, role=admin). |
| `SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL`     | secret | Slack/PagerDuty webhook fired when the probe itself dies for >5 min.    |
| `SYNTHETIC_PROBE_WATCHDOG_THRESHOLD_MIN`   | var    | Override watchdog threshold (default `5`, i.e. 5 consecutive failures). |
| `SYNTHETIC_PROBE_DISABLED`                 | var    | Set to `true` to pause the probe without redeploying.                   |

**Probe behaviour:**

- Every minute the worker GETs the target URL with `CF-Access-Client-Id`,
  `CF-Access-Client-Secret`, `Authorization: Bearer <admin JWT>`, and
  the `X-Origin-Auth` shared secret (auto-injected from
  `BACKEND_ORIGIN_SECRET`).
- A 2xx response means the diagnostics paging logic executed — the
  break-glass / `admin_enforced=false` alerts (above) will fire on
  their own through the FastAPI pipeline if the snapshot is degraded.
- A non-2xx response (or a network error) increments a consecutive-
  failure counter persisted in the `RATE_LIMIT` KV namespace under
  `synthetic_probe:state`.
- After **5 consecutive failures** (i.e. the probe has been dark for
  ≥5 minutes) the worker POSTs a JSON alert to
  `SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL` with `alert_type:
  "synthetic_probe_dark"`. This watchdog re-fires every 5 minutes
  while the probe stays dark — a deliberate forcing function so
  on-call cannot snooze the "paging is broken" signal.

**Verification (run after rolling out the secrets):**

```bash
# 1. Force a one-shot run by triggering the cron from wrangler.
pnpm --filter syrabit-edge dlx wrangler dev --test-scheduled
# in another shell:
curl 'http://localhost:8787/__scheduled?cron=*+*+*+*+*'
# Expect a [synthetic-probe] log line with status=200 ok=true.

# 2. From a personal laptop (NOT inside the worker), confirm the
#    service token can reach diagnostics:
curl -sS -i 'https://api.syrabit.ai/admin/diagnostics' \
  -H "CF-Access-Client-Id: $SYNTHETIC_PROBE_CF_ACCESS_CLIENT_ID" \
  -H "CF-Access-Client-Secret: $SYNTHETIC_PROBE_CF_ACCESS_CLIENT_SECRET" \
  -H "Authorization: Bearer $SYNTHETIC_PROBE_ADMIN_JWT"
# Expect HTTP/2 200 with a JSON body containing "cf_access" and "paging".

# 3. Simulate a probe failure: rotate the admin JWT to garbage in the
#    dashboard, wait 6 minutes, confirm the Slack/PagerDuty channel
#    received an `alert_type: "synthetic_probe_dark"` payload, then
#    restore the real JWT.
```

**Rotation procedure (run quarterly or on suspected leak):**

1. **CF Access service token** — Cloudflare Zero Trust →
   `Access → Service Auth → Service Tokens` → `syrabit-synthetic-probe`
   → *Refresh* (creates a new client secret; the client id is stable).
   Within the 24h overlap window, update both
   `SYNTHETIC_PROBE_CF_ACCESS_CLIENT_ID` and
   `SYNTHETIC_PROBE_CF_ACCESS_CLIENT_SECRET` on the worker. Confirm the
   probe still logs `status=200`. Then `Revoke` the old token.
2. **Admin JWT** — generate a new one with the existing helper
   (`pnpm --filter syrabit-backend python scripts/mint_admin_jwt.py
   --sub synthetic-probe --ttl 31536000`), update
   `SYNTHETIC_PROBE_ADMIN_JWT` on the worker, and revoke the previous
   `jti` via the admin sessions table. Note the rotation in the ops log.
3. **Watchdog webhook URL** — rotate via the Slack/PagerDuty UI and
   update `SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL` on the worker.

If the team needs to take the probe down (e.g. extended planned
maintenance), set `SYNTHETIC_PROBE_DISABLED=true` on the worker — this
pauses the probe within ~10s without deleting any secrets. **Do not
forget to flip it back**: a paused probe means `/admin/diagnostics`
paging is dark.

**What break-glass does NOT do:**

- It does **not** bypass the admin JWT check. A leaked break-glass
  token by itself cannot reach admin handlers — the attacker still
  needs valid admin credentials.
- It does **not** disable origin shared-secret enforcement. The Worker
  still injects `X-Origin-Auth`, so the bare Railway URL remains
  unreachable from arbitrary clients.
- It does **not** clear automatically. The on-call must explicitly
  flip the toggle off; the CRITICAL log line on every bypassed
  request and the persistent `cf_access_break_glass_active` alert are
  the forcing functions.

## 8. What is **not** in scope here

- WARP enrollment of every team device (separate task; required before
  enforcing device-posture rules in step 1).
- Replacing the admin login form with Sign-in-with-Cloudflare
  (planned follow-up — currently the admin password stays as a second
  factor behind Access).
- Migrating end-user student auth to Access (out of scope; students
  stay on the existing Google OAuth + JWT flow).
