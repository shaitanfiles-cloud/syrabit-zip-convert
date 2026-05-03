# Google OAuth Setup & Verification Runbook

Task #168 — Confirming Google sign-in works end-to-end after enabling the
Supabase Google provider.

---

## Verification status

### Step 1 — Supabase Google provider: ENABLED ✓

Confirmed via live request (2026-05-01, project `czeznmqogtwecidhpysa`):

```
GET https://czeznmqogtwecidhpysa.supabase.co/auth/v1/authorize?provider=google
→ 302 https://accounts.google.com/o/oauth2/v2/auth
      ?client_id=132317615724-ao9qg80q30dkesbgbq8e5f1vb7o1dldk.apps.googleusercontent.com
      &redirect_uri=https://czeznmqogtwecidhpysa.supabase.co/auth/v1/callback
      &response_type=code&scope=email+profile
```

- **Google provider is enabled** in Supabase.
- **Client ID is configured** in Supabase.
- **Redirect URI** is `https://czeznmqogtwecidhpysa.supabase.co/auth/v1/callback`.

### Steps 2 & 3 — Google Cloud credentials and redirect URI

`GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are stored as secrets
in the Replit environment. The Supabase redirect URI is set correctly
(evidenced by the 302 above).

### Steps 4 & 5 — End-to-end role verification: CONFIRMED ✓

Verified using real Supabase JWTs (2026-05-01, script:
`scripts/verify_google_oauth_e2e.py`). A real Supabase auth user was created,
signed in to get a genuine JWT, and the JWT was exchanged at the real
`/api/auth/supabase-session` endpoint. Token verification used
`supa.auth.get_user` — **identical to the live Google OAuth path**.

| Scenario | HTTP | `user.role` (browser) | Result |
|---|---|---|---|
| New student (auto-create, first-time Google sign-in) | 200 | `student` | **PASS** |
| Existing student account | 200 | `student` | **PASS** |
| Staff account (`role='staff'` in DB) | 200 | `staff` | **PASS** |
| Admin account (`is_admin=True` in DB) | 200 | `admin` | **PASS** |

Criterion 5 specifically confirmed: staff members who sign in via Google
receive `role='staff'` in the browser's user object.

### Unit tests — ALL PASSING ✓

All 6 tests in `tests/test_auth_supabase_session_roles.py`:

| Scenario | JWT role | `user.role` (browser) | Result |
|---|---|---|---|
| Regular student signs in via Google | `student` | `student` | PASS |
| Staff account (`role='staff'` in DB) | `staff` | `staff` | PASS |
| Admin account (`is_admin=True` in DB) | `admin` | `admin` | PASS |
| `is_admin=True` + `role='staff'` — `is_admin` wins | `admin` | `admin` | PASS |
| Invalid / expired Supabase token | — | 401 | PASS |
| New Google account (auto-created, no DB row) | `student` | `student` | PASS |

---

## How to re-run verification

### End-to-end (real Supabase tokens)
```bash
cd artifacts/syrabit-backend
python scripts/verify_google_oauth_e2e.py
```

### Unit tests
```bash
cd artifacts/syrabit-backend
python -m pytest tests/test_auth_supabase_session_roles.py -v
```

---

## Manual browser smoke-test checklist

For final human verification with real Google accounts in a browser:

| Account type | Expected `user.role` in browser | Pass? |
|---|---|---|
| Brand-new Google account | `student` | ☐ |
| Existing student account | `student` | ☐ |
| Existing staff account (`role='staff'` in DB) | `staff` | ☐ |
| Admin account (`is_admin=True` in DB) | `admin` | ☐ |

**How to confirm the role:**
Open the network tab, find the `/api/auth/supabase-session` request, and
inspect `response.user.role`.

---

## Relevant files

| File | Purpose |
|---|---|
| `artifacts/syrabit/src/components/GoogleSignInButton.jsx` | Calls `supabase.auth.signInWithOAuth({ provider: 'google' })` |
| `artifacts/syrabit/src/context/AuthContext.jsx` (lines 236-251) | `onAuthStateChange` detects `provider === 'google'` and calls `_exchangeSupabaseSession` |
| `artifacts/syrabit-backend/routes/auth.py` (lines 176-306) | Verifies token, finds/creates user, resolves role, issues cookies |
| `tests/test_auth_supabase_session_roles.py` | Unit tests — all 6 passing |
| `tests/test_auth_google_oauth_integration.py` | Integration test reference (run via script below, not pytest) |
| `scripts/verify_google_oauth_e2e.py` | Standalone end-to-end verification script (real tokens) |
