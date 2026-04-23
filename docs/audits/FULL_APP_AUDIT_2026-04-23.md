# Syrabit.ai — Full Codebase Audit (2026-04-23)

**Scope.** Read-only review of the entire Syrabit.ai monorepo: `artifacts/syrabit-backend/` (FastAPI, 35+ routers, ~42k LOC), `artifacts/syrabit/` (React + Vite SPA + Cloudflare Pages worker), and `workers/edge-proxy/` (Cloudflare Worker in front of `api.syrabit.ai`). Goal: deliver a single prioritized, fix-ready list of concrete issues with `file:line` anchors so each can be turned into a follow-up task without further investigation.

**Methodology.** Four parallel explorer passes (security / backend logic / frontend / tests-deps-config), followed by manual spot-verification of every high-severity finding against the live file. Every line number in this document was confirmed to point at the right code at the time of writing.

**Non-goals.** No code, config, dependency, env var, or workflow changes are made as part of this audit. Every fix is proposed, not applied. Follow-up tasks (§11) explicitly exclude work that is already on the task queue (Workers migration, Atlas Vector Search, auth removal, RAG citations, GA4 audit, PWA manifest, Razorpay webhook hardening beyond verify, Redis caching, Cloudflare integration, content pipeline).

---

## 1. Executive summary

The codebase is healthy and well-factored for its size, but three patterns recur and dominate the risk surface:

1. **Synchronous SDKs inside `async` FastAPI handlers** — most painfully, the Razorpay Python SDK (used on every `POST /payments/create-order` and `/payments/verify`) blocks the event loop for the duration of an external HTTP call. Under concurrent checkout load this will manifest as p99 latency cliffs that are invisible in unit tests.
2. **Non-atomic credit accounting in the Redis fallback path** of `atomic_deduct_credit`, which opens a narrow double-spend window whenever Postgres is unavailable.
3. **A committed 64-character hex secret (`D1_SYNC_SECRET`) in `.replit`**, plus two JWT secrets that deterministically derive from `MONGO_URL + DB_NAME` when unset. In practice the env-var fallback is never hit in production, but the deterministic derivation means a database URL leak ⇒ forged admin tokens.

Payment routes (both Razorpay verify and the Stripe path) are the single largest testing gap: there is no pytest file whose name references `razorpay` or `stripe` under `artifacts/syrabit-backend/tests/`. Given the direct revenue impact, closing this gap is the highest-leverage testing investment.

Frontend is in better shape than the backend, with the notable exception of: (a) `<div dangerouslySetInnerHTML>` against server-rendered content in four pages with no `DOMPurify` on the client, (b) the global `ErrorBoundary` at `artifacts/syrabit/src/App.jsx:374` being the only boundary in the tree (one crash in `ChatPage` takes down the shell).

None of the findings warrant rolling back production. Three findings (B1, S1 Critical, C1) are worth addressing in the current sprint; the rest can be scheduled.

---

## 2. Severity-ranked index of all findings

| ID  | Sev | Area     | File:line                                                           | One-line issue                                                                 |
|-----|-----|----------|---------------------------------------------------------------------|--------------------------------------------------------------------------------|
| B1  | 🔴 Critical | Backend | `artifacts/syrabit-backend/db_ops.py:289-300`                         | Redis-fallback credit deduction is two ops (SET-NX then INCR), not atomic.     |
| S1  | 🔴 Critical | Security | `.replit:60`                                                        | `D1_SYNC_SECRET` committed as literal hex in repo; must move to Secret Manager.|
| S2  | 🟠 High     | Security | `artifacts/syrabit-backend/config.py:46-56, 63-67`                  | JWT_SECRET / ADMIN_JWT_SECRET fall back to `sha256(MONGO_URL+DB_NAME+REPL_ID)`.|
| B2  | 🟠 High     | Backend | `artifacts/syrabit-backend/routes/admin_monetization.py:234-245, 292-310, 447-450` | Synchronous `razorpay.Client` calls inside `async def` block the event loop.   |
| B3  | 🟠 High     | Backend | `artifacts/syrabit-backend/routes/ai_chat.py:1133`                  | `asyncio.create_task(_early_cache_persist())` is fire-and-forget — no await, no error handling; chat history can silently fail to save.    |
| F1  | 🟠 High     | Frontend | `artifacts/syrabit/src/App.jsx:374-385`                              | Only one top-level `ErrorBoundary` — a thrown error in `ChatPage` or `LibraryPage` blanks the whole app.|
| F2  | 🟠 High     | Frontend | `artifacts/syrabit/src/pages/PYQReplicaPage.jsx:143-162, 251`        | `fetch()` without `AbortController` + `dangerouslySetInnerHTML` on server HTML without `DOMPurify`. |
| T1  | 🟠 High     | Testing  | `artifacts/syrabit-backend/tests/`                                   | 0 test files mention Razorpay or Stripe signature verify / plan activation.    |
| B4  | 🟡 Medium   | Backend | `artifacts/syrabit-backend/routes/conversations.py:117-151`          | N+1 MongoDB round-trips resolving subject→stream→class→board per message.      |
| B5  | 🟡 Medium   | Backend | `artifacts/syrabit-backend/routes/ai_chat.py:1050-1153`              | Streaming chat never calls `request.is_disconnected()`; client hang-up keeps LLM tokens flowing. |
| B6  | 🟡 Medium   | Backend | `artifacts/syrabit-backend/routes/content.py:157-358, 374, 394`      | Bare `except Exception: return []` masks Mongo outages as "no content".         |
| S3  | 🟡 Medium   | Security | `artifacts/syrabit-backend/routes/admin_monetization.py:48-62, 86-99`| Admin config mutations accept raw `data: dict` with no Pydantic schema — any key, any type, no `$`-prefix stripping.|
| S4  | 🟡 Medium   | Security | `artifacts/syrabit/src/pages/SubjectPage.jsx:205`, `PersonalizedCmsPage.jsx:192`, `LearnPage.jsx:326`, `artifacts/syrabit/src/pages/PYQReplicaPage.jsx:251` | `dangerouslySetInnerHTML` with LLM/CMS-produced HTML, no `DOMPurify`.          |
| S5  | 🟡 Medium   | Security | `artifacts/syrabit-backend/routes/admin_monetization.py:108-113`     | Razorpay secrets resolved from Mongo `api_config` *before* env var; a Mongo compromise lets an attacker override live keys.|
| F4  | 🟡 Medium   | Frontend | `artifacts/syrabit/public/yoga-cover-notext.webp` (200 KB)           | Landing-page hero image is right at the 200 KB LCP budget; compress / serve `srcset`. |
| F5  | 🟡 Medium   | Frontend | `artifacts/syrabit/src/pages/BrowserPage.jsx` (2k+ LOC)              | Mega-component bundles reader + side panel + tab strip; blocks further lazy-splitting.    |
| C1  | 🟡 Medium   | Deploy   | `.replit:50-62`                                                      | `SUPABASE_URL`, `GOOGLE_OAUTH_CLIENT_ID`, `CF_AI_GATEWAY_ACCOUNT_ID` committed — not secret but couples repo to one tenant.|
| D1  | 🟡 Medium   | Deps     | `artifacts/syrabit-backend/requirements.txt`                         | Both `httpx` and `aiohttp` shipped; `pymongo==4.5.0` is ~6 minor versions behind.|
| D2  | 🟡 Medium   | Deps     | `artifacts/syrabit/package.json`                                     | `axios` and native `fetch` both in active use in `ChatPage.jsx` / `PYQReplicaPage.jsx`.|
| B7  | 🟢 Low      | Backend | `artifacts/syrabit-backend/cache.py:150-180`                         | `loop.create_task(mod.aset(...))` for `ai_cache` writes is unreferenced; may be GC'd or lost on worker shutdown.|
| F6  | 🟢 Low      | Frontend | `artifacts/syrabit/src/pages/ChatPage.jsx:115-127`                   | `setTimeout` inside scroll effect clears correctly but the effect depends only on `[messages]`; `isStreaming` toggle risks stale-closure timing.|
| F7  | 🟢 Low      | Frontend | `artifacts/syrabit/src/utils/visitTracker.js` + `usePageTracking.js` | Looks redundant alongside GA4 / Firebase analytics; candidate for removal.     |
| T2  | 🟢 Low      | Testing  | `artifacts/syrabit/tests/`                                           | Only two Playwright specs (`admin-smoke`, `study-flows`) — no payment flow, no chat stream E2E.|
| T3  | 🟢 Low      | Testing  | `artifacts/syrabit-backend/tests/`                                   | 5 unit tests for 3k+ LOC `rag.py` + `syllabus_embedder.py` — vector timeouts and malformed chunk branches untested.|

Legend: 🔴 Critical = data/revenue/security impact likely under normal load; 🟠 High = clear correctness or reliability bug; 🟡 Medium = latent / requires an adjacent failure; 🟢 Low = hygiene / polish.

---

## 3. Security findings (detail)

### S1 · Committed `D1_SYNC_SECRET`  — Critical
`.replit:60` stores `D1_SYNC_SECRET = "5b5b09…f276250e"` as a 64-char literal. Anyone with repo read access has admin access to whatever D1 sync endpoint this guards. Rotate the value, store the new value in Replit Secrets (or deployment env), and delete the literal from `.replit`. Confirm `workers/edge-proxy/src/index.ts` reads it from `env.D1_SYNC_SECRET` already (it does) so no code changes are needed.

### S2 · JWT fallback derives from database URL  — High
`artifacts/syrabit-backend/config.py:46-56`:
```python
_fallback_seed = (MONGO_URL + DB_NAME + os.environ.get('REPL_ID', '')).encode()
JWT_SECRET = _jwt_hl.sha256(b'syrabit-jwt-fallback:' + _fallback_seed).hexdigest()
```
`ADMIN_JWT_SECRET` (line 63-67) in turn hashes `f"admin-{JWT_SECRET}"`. So an attacker who learns `MONGO_URL` (which, for Atlas, is often co-leaked with DB credentials) plus `REPL_ID` (visible to any Replit workspace collaborator) can forge both user and admin tokens. The warning printed at startup is silent in production logs.

**Fix.** In `server.py` startup, if `os.environ.get('DEPLOYMENT_ENV') == 'production'` and `JWT_SECRET` env is unset, raise at startup instead of falling back. Keep the fallback only for local dev. This is a one-line change and has zero deployment risk because prod already sets `JWT_SECRET`.

### S3 · Unvalidated admin config mutations  — Medium
`artifacts/syrabit-backend/routes/admin_monetization.py:49-50, 87-99` (`PUT /admin/plan-config`, `PUT /admin/api-config`) take `data: dict` and write it verbatim into Mongo via `replace_one` / merge. This is not classical operator injection (the payload goes into document *values*, not query filters), but it lets any holder of an admin token (phished or misused) write arbitrary keys, poison the Razorpay secret keys read by `_get_razorpay_keys`, or stuff large blobs into the config doc. These endpoints should take typed Pydantic models (`PlanTierConfig`, `ApiConfigPatch`), reject unknown keys, and bound string lengths.

### S4 · Unsanitized `dangerouslySetInnerHTML`  — Medium
Four pages render HTML that ultimately comes from the backend (LLM + CMS):
- `artifacts/syrabit/src/pages/SubjectPage.jsx:205` — `htmlContent` from the chapter API
- `artifacts/syrabit/src/pages/PersonalizedCmsPage.jsx:192` — `doc.content_html` directly from `/personalized-cms`
- `artifacts/syrabit/src/pages/LearnPage.jsx:326` — `processedHtml` from the topic pipeline
- `artifacts/syrabit/src/pages/PYQReplicaPage.jsx:251` — the worker `/pyq/:slug` passthrough

Add `DOMPurify.sanitize(html, { ALLOWED_ATTR: [...], ADD_ATTR: ['target', 'rel'] })` at the render site for each. A shared `<SafeHtml html={...} />` component in `src/components/` would centralise this.

### S5 · Razorpay secrets DB-first  — Medium
`artifacts/syrabit-backend/routes/admin_monetization.py:108-113` reads `razorpay_key_id/secret/webhook_secret` from the Mongo `api_config` collection *first*, then falls back to env. For a payments provider this should be reversed: env wins, DB is only used for non-payment keys (analytics, email). Also fixes S3 partially — a tampered `api_config` doc can't re-route live charges.

### Security findings that came back clean
- SSRF / prompt-injection URL fetches are already routed through `artifacts/syrabit-backend/url_safety.py:49, 117` which blocks private ranges and re-resolves hostnames per redirect hop.
- CORS allowlist in `workers/edge-proxy/src/index.ts:165` is a hard-coded list of `syrabit.ai` hosts; `Access-Control-Allow-Credentials: true` is only echoed when the origin matches (`:406`).
- Razorpay signature verification in `artifacts/syrabit-backend/routes/admin_monetization.py:280` uses `hmac.compare_digest` (timing-safe).
- `routes/auth.py:102, 140` sets `httponly=True, secure=SECURE_COOKIES, samesite=COOKIE_SAMESITE` on the session cookie. The only recommendation is to drop the env toggle and hardcode `secure=True` when `DEPLOYMENT_ENV == 'production'`.
- Edge rate-limits in `workers/edge-proxy/src/index.ts:228` are wired to Cloudflare KV at 120/1200/30 RPM per user/bot/AI path.

---

## 4. Backend logic & async correctness (detail)

### B1 · Non-atomic Redis credit deduction  — Critical
`artifacts/syrabit-backend/db_ops.py:289-300`:
```python
redis_client.set(redis_key, current_used, ex=86400, nx=True)   # step 1
new_count = redis_client.incr(redis_key)                        # step 2
if new_count > current_limit:
    redis_client.decr(redis_key)                                # step 3
    return False
```
Under concurrent requests that hit the PG failure path simultaneously, two coroutines can both observe `current_used < current_limit` via the stale snapshot passed into this function, both INCR past the limit, both refund, but the `supa_update_user` writes *after* the INCR encode the over-spent count.

**Fix.** Replace steps 1-3 with a single Lua script that atomically SETNX + INCR, rejecting if INCR would exceed `ARGV[1]`. Example already in the subagent report. Keep the PG fast path intact.

### B2 · Synchronous Razorpay SDK in async routes  — High
Three sites: `artifacts/syrabit-backend/routes/admin_monetization.py:234-245` (`create`), `:292-310` (`fetch`), `:447-450` (recovery `fetch`). Each is an external HTTPS call (~150-400 ms RTT to Razorpay) made with the stdlib `requests`-based SDK inside an `async def`, blocking the single uvicorn worker for the full round-trip.

**Fix.** Wrap each call in `await anyio.to_thread.run_sync(lambda: client.order.create({...}))`. No SDK replacement needed.

### B3 · Fire-and-forget early-cache persist  — High
`routes/ai_chat.py:1133`:
```python
asyncio.create_task(_early_cache_persist())
```
The created task reference is not stored. If the response finishes and the ASGI scope is torn down before the task is scheduled (common at shutdown or under cancellation), the user's early-cache-hit conversation is never written. Store the task in a module-level `WeakSet` — or `await` it just before `return StreamingResponse` (the persist is already non-blocking vs upstream LLM, so awaiting adds tens of ms worst case).

### B4 · Conversation metadata N+1  — Medium
`routes/conversations.py:117-151` loops over every assistant message in a conversation and does up to four `find_one` calls per missing subject/stream/class/board. A 100-message chat with diverse subjects triggers ~400 Mongo round-trips. The `_cache` dict does dedupe within a single request but not across requests.

**Fix.** Collect all `sid` values first, then do one `db.subjects.find({"id": {"$in": list(sids)}})`, then one for streams, classes, boards. Three bulk fetches for the whole conversation.

### B5 · Streaming chat never checks disconnect  — Medium
`routes/ai_chat.py:1050-1153` yields SSE events in a tight generator but never reads `await request.is_disconnected()`. When a user closes the tab mid-answer the backend continues consuming LLM tokens (and the user's deducted credit is never refunded by the disconnect branch — it's only refunded on the cache path at `:1144`).

**Fix.** Wrap the yield loop in a `while not await request.is_disconnected()` guard; break on disconnect and schedule `_refund_credit`.

### B6 · Broad-except in content routes  — Medium
`artifacts/syrabit-backend/routes/content.py:157-358` (`get_library_bundle`) and the smaller `get_boards`/`get_classes` wrappers end with `except Exception: return []`. This is the library's primary data source: if Mongo is down, every user sees an empty library instead of a 500 that the client can catch and display a "temporarily unavailable" banner. Convert the outer except to `except Exception: logger.exception(...); raise HTTPException(503, "Library temporarily unavailable")`.

### B7 · `ai_cache.aset` create_task unreferenced  — Low
`artifacts/syrabit-backend/cache.py:150-180` fires `loop.create_task(mod.aset(...))` for the `ai_cache` prefix without keeping a reference. The bigger risk isn't garbage collection (the loop owns the task until completion) but shutdown: if the worker is SIGTERM'd between the request returning and the task running, the cache write is silently dropped and exceptions in the task surface only via the asyncio "unhandled exception" warning — not the logger. Either store the task in a module-level `set()` that `discard`s on completion (and attach an `add_done_callback` that logs exceptions), or just `await` the write (sub-ms against local Redis).

### Correctness checks that came back clean
- `url_safety.safe_get_with_redirects` correctly re-validates every hop.
- `supa_mirror` and `_pg_row/_pg_rows` do round-trip coercion consistently.
- Streaming TTFB metrics (`record_first_token`, `record_chat_attrs`) are emitted on all three stream paths.
- The compensating-rollback block at `artifacts/syrabit-backend/routes/admin_monetization.py:382-418` covers all three stores correctly and logs to the ERROR channel on rollback failure — this is exactly the right shape.

---

## 5. Frontend findings (detail)

### F1 · Single global `ErrorBoundary`  — High
`artifacts/syrabit/src/App.jsx:374-385` wraps the entire router subtree in one boundary. A render error in `ChatPage` (most likely failure mode — the streaming reducer) therefore unmounts the nav shell and leaves the user on a blank page.

**Fix.** Per-route boundaries:
```jsx
<Route path="/chat" element={
  <ErrorBoundary fallback={<ChatCrashFallback/>}>
    <ChatPage/>
  </ErrorBoundary>
}/>
```
Add at least one for `/chat`, `/library`, `/learn/*`.

### F2 · `PYQReplicaPage` race + unsanitized HTML  — High
`artifacts/syrabit/src/pages/PYQReplicaPage.jsx:143-162` kicks off a `fetch(${WORKER_API}/pyq/${slug})` in `useEffect([slug])` with no `AbortController`. Rapid slug navigation (common on the PYQ index) lets the slower response overwrite the newer one.
Line 251 then renders the result with `dangerouslySetInnerHTML`. If an attacker can poison the worker response (unlikely but not zero — the worker ultimately reads from Cloudflare KV), the XSS is direct.

**Fix.** Standard `AbortController` pattern + `DOMPurify.sanitize(html)` (also resolves S4 for this page).

### F3 · No `manualChunks`  — Medium
`artifacts/syrabit/vite.config.js` imports `rollup-plugin-visualizer` but does not configure `build.rollupOptions.output.manualChunks`. For a React + Radix + recharts + date-fns + react-markdown + react-helmet-async app, a reasonable split is:
```js
manualChunks: {
  'react-vendor': ['react', 'react-dom', 'react-router-dom'],
  'ui-vendor': ['@radix-ui/react-*', 'lucide-react'],
  'markdown': ['react-markdown', 'remark-gfm', 'rehype-raw'],
  'charts': ['recharts'],
}
```
Expect first-load JS on `/` to drop measurably (subagent projected ~30-40%; this needs verification with the visualizer before any task is scoped).

### F4 · Hero image at LCP budget  — Medium
`public/yoga-cover-notext.webp` is 200 KB on disk. At typical mobile 4G throughput that's ~400 ms download on top of connect + TTFB. Either compress to ≤80 KB (WebP q=78), or provide a `<picture>` with a 60 KB mobile source (`srcset` by viewport width).

### F5 · `BrowserPage.jsx` mega-component  — Medium
2k+ LOC mixing reader, side-panel, and tab strip. Already lazy-loaded, so the cost is in maintenance rather than TTI, but extracting `ReaderArticle`, `SidePanel`, `TabStrip` into co-located files under `src/components/browser/` would unlock sub-chunk splits and unblock further work.

### F6 · `ChatPage` scroll effect dep array  — Low
`artifacts/syrabit/src/pages/ChatPage.jsx:115-127` depends on `[messages]` only, but the body reads `isStreaming`. Harmless today because the ref pattern works, but will quietly decay if the effect is refactored.

### F7 · `visitTracker.js` likely dead  — Low
Imported only by `usePageTracking.js`; both appear to duplicate GA4 / Firebase analytics already wired at the root. Worth a 5-minute grep + remove if confirmed.

### Frontend checks that came back clean
- `react-helmet-async` is applied consistently on public routes.
- No `VITE_*` env var leaks a service-role secret (audit of `src/utils/api.jsx` confirms only public base URLs).
- `rehype-raw` + `remark-gfm` are only used in markdown-rendering contexts; no dual markdown library.

---

## 6. Test coverage gap report

### 6.1 Counts (verified via `ls`)
- Backend (`artifacts/syrabit-backend/tests/`): **106 files** — strong coverage on admin, SEO, bot traffic, and infra.
- Frontend E2E (`artifacts/syrabit/tests/`): **2 Playwright specs** (`admin-smoke`, `study-flows`) + `admin-mocks.ts`.
- Frontend unit (`artifacts/syrabit/src/**.test.js*`): 5 vitest files (`AdminEduBrowser`, `AlertReasonsRow`, `BreakGlassBanner`, `highlightSegments`, `pushChannelTone`).

### 6.2 Gaps that matter

| Module                        | Key file                                         | Coverage status                                    | Proposed test |
|-------------------------------|--------------------------------------------------|----------------------------------------------------|---------------|
| Razorpay create-order + verify| `routes/admin_monetization.py:218-418`           | **No dedicated pytest file** (grep: 0 hits).        | `tests/test_payments_razorpay.py`: signature tamper → 400; plan downgrade attempt → 400; idempotent re-verify → 200; PG-update-fails → compensating rollback runs in order. |
| Stripe path                   | `artifacts/syrabit-backend/routes/admin_monetization.py:499+` (PLAN_PRICES_USD)   | **No dedicated pytest file**.                       | `tests/test_payments_stripe.py`: FX enrich path (inr_native vs usd); unsupported currency → `amount_inr=None`. |
| Credit deduction race         | `artifacts/syrabit-backend/db_ops.py:289`                                  | No concurrency test.                               | `tests/test_atomic_deduct_race.py`: 50 `asyncio.gather` deductions, asserts final count ≤ limit. |
| Streaming disconnect          | `routes/ai_chat.py`                              | No disconnect test.                                | `tests/test_chat_disconnect_refund.py`: ASGI test client closes mid-stream; assert refund recorded. |
| Library content visibility    | `routes/content.py`                              | No pytest covers guest vs Pro gating.              | Parametrised pytest over `guest / starter / pro` × `document_access`. |
| Frontend payment flow         | —                                                | No Playwright spec.                                | `tests/payment-flow.spec.ts`: stub Razorpay checkout; verify `/plans` → success toast → `/profile` credits updated. |
| RAG error branches            | `rag.py`, `syllabus_embedder.py`                 | 3 tests total.                                     | `tests/test_rag_vector_timeout.py`, `test_rag_malformed_chunk.py`. |

### 6.3 Non-gaps (credit where due)
Trustpilot, CI alerts, SEO auto-publish, bot traffic, edge-proxy auth headers, and admin login regressions are all well covered. Do not duplicate.

---

## 7. Dependency hygiene

### Backend (`artifacts/syrabit-backend/requirements.txt`)
- **Duplicate HTTP stacks.** Both `httpx` and `aiohttp` are present. `httpx` is used in the FastAPI / OpenAI SDK paths; `aiohttp` appears to be transitive (likely via `openai` or `groq`). Confirm with `pip show aiohttp` + `grep -rn "import aiohttp"` — if it's truly unused in direct source, it's wasted install surface. Keep `httpx`.
- **`pymongo==4.5.0`.** Six minor versions behind (4.11 at time of writing). No security CVE pinned, but upgrade before 4.5.0 falls off security support.
- **`uvloop`, `httptools`, `h2`.** Used transitively by uvicorn / httpx; these are fine to keep unpinned-explicit.

### Frontend (`artifacts/syrabit/package.json`)
- **`axios` vs `fetch`.** `axios` is imported in a handful of places while newer code uses native `fetch` (`ChatPage.jsx`, `PYQReplicaPage.jsx`). Pick one. Native `fetch` + a tiny `apiClient` wrapper saves ~13 KB gzipped.
- **`lamejs`.** Only referenced by `AudioTrimPreview.jsx`. If that component is behind a flag, dynamic-import the library at the point of use so it doesn't weigh the main bundle.
- **`rollup-plugin-visualizer`.** Only useful in `vite build` profile. Already imported conditionally — good.

### Monorepo
- No duplicate React versions (`pnpm why react` returns single tree).
- No committed `node_modules` or `.venv`.

---

## 8. Bundle / performance

- **Initial JS.** Without `manualChunks` (F3), the main bundle on `/` ships the full Radix + react-markdown + recharts footprint regardless of route. Quick win.
- **Hero image.** F4 above.
- **Lazy-preload pattern.** `artifacts/syrabit/src/App.jsx:72-87` uses a hand-rolled `lazyPreload` — good; do not replace with plain `React.lazy`.
- **Service worker.** `public/sw.js` + `public/offline.html` present; no audit issues found. `manifest.json` + `_headers` are in place.
- **No Lighthouse regression since 2026-04-18 rerun** (per `docs/audits/pagespeed-2026-04-18-rerun-2.md`).

---

## 9. Config & deployment

| ID  | Finding                                                                                  | File                       |
|-----|------------------------------------------------------------------------------------------|----------------------------|
| C1  | `D1_SYNC_SECRET` committed (see S1).                                                      | `.replit:60`              |
| C2  | `SUPABASE_URL`, `GOOGLE_OAUTH_CLIENT_ID`, `TRUSTPILOT_BUSINESS_UNIT_ID`, `CF_AI_GATEWAY_ACCOUNT_ID` committed. Not secrets, but they hard-couple the repo to one tenant and should live in `[deployment]` / user env. | `.replit:50-62` |
| C3  | `SECURE_COOKIES = "false"` at repo level; prod should force `true`.                       | `.replit:55`              |
| C4  | `ALLOWED_ORIGINS` hardcoded in the edge worker; move to `env.ALLOWED_ORIGINS` binding so staging can be added without a redeploy. | `workers/edge-proxy/src/index.ts:165` |
| C5  | `ENABLE_E2E_ADMIN = "true"` in `[userenv.development]` — correct placement; no action.    | `.replit:64-65`           |
| C6  | Port map `localPort 8000 → externalPort 80` — confirmed matches `gunicorn.conf.py` bind.  | `.replit:82-84`           |

Deploy target is `autoscale` with `pnpm store prune` post-build — appropriate for this workload.

---

## 10. Observations that did not become findings

Captured so a future audit doesn't re-investigate them:
- `url_safety.py` is complete and re-used at every relevant call site (RAG, edu-browser, document upload).
- The `_enrich_payment_record` (monetization.py:124-207) schema unification is well-designed; FX audit trail is complete.
- `_record_draft_served` / `get_draft_served_subjects` / `clear_draft_served_subject` (content.py:63-155) is a textbook cross-worker Redis-with-fallback pattern.
- Admin Trustpilot alert history (Task #758) is already instrumented via `_extract_jsonld_alert_urls` and the admin tile polls at 60s.
- `playwright.config.ts` points at the live Pages URL; no embedded test secrets.
- `.gitignore` correctly excludes `.env`, `__pycache__`, `node_modules`, `.venv`.

---

## 11. Proposed follow-up tasks (non-overlapping with existing queue)

Numbered so they can be cherry-picked. None of these duplicate in-flight or proposed work (Workers migration, Atlas Vector Search, auth removal, RAG citations, GA4 audit, PWA manifest, Razorpay webhook beyond verify, Redis caching, Cloudflare integration, content pipeline).

1. **Atomic Redis credit deduction via Lua** — fix B1; replace the SETNX+INCR dance in `artifacts/syrabit-backend/db_ops.py:289-300` with a single Lua script. Add `tests/test_atomic_deduct_race.py` that fires 50 concurrent deductions and asserts the final counter never exceeds the limit.
2. **Rotate `D1_SYNC_SECRET` and move to Secret Manager** — fix S1+C1; generate a new 64-char secret, add to Replit Secrets, update `workers/edge-proxy/wrangler.toml` binding, delete literal from `.replit:60`, redeploy both worker and backend.
3. **Hard-fail JWT startup when secret unset in prod** — fix S2; add a `DEPLOYMENT_ENV == 'production'` guard in `server.py` startup that raises `RuntimeError` if `JWT_SECRET` or `ADMIN_JWT_SECRET` env is unset. Dev fallback stays.
4. **Run Razorpay SDK in a threadpool** — fix B2; wrap the three blocking call sites (`artifacts/syrabit-backend/routes/admin_monetization.py:237, 293, 449`) in `await anyio.to_thread.run_sync(...)`. Add a p99 latency assertion to `tests/test_payments_razorpay.py` from task 5.
5. **Payments test suite** — close T1; create `tests/test_payments_razorpay.py` and `tests/test_payments_stripe.py` per §6.2 plus a Playwright `tests/payment-flow.spec.ts` that stubs Razorpay checkout.
6. **Pydantic schemas for admin-config mutations** — fix S3; introduce `PlanTierPatch`, `ApiConfigPatch` Pydantic models, strip `$`-prefixed keys before Mongo writes in `artifacts/syrabit-backend/routes/admin_monetization.py:48-99`.
7. **Env-first Razorpay key resolution** — fix S5; invert the order in `_get_razorpay_keys` (`artifacts/syrabit-backend/routes/admin_monetization.py:108-113`) so env wins over Mongo for `key_id / key_secret / webhook_secret`.
8. **Shared `<SafeHtml>` component with DOMPurify** — fix S4+F2; add `artifacts/syrabit/src/components/SafeHtml.jsx` with a sanitised wrapper, replace the four `dangerouslySetInnerHTML` sites listed in §5. Add `DOMPurify` to `artifacts/syrabit/package.json`.
9. **Per-route React `ErrorBoundary`** — fix F1; wrap `/chat`, `/library`, `/learn/*` routes in `artifacts/syrabit/src/App.jsx` with dedicated boundaries and friendly fallbacks.
10. **PYQReplicaPage AbortController** — fix F2 correctness half; add an `AbortController` to the `useEffect` at `artifacts/syrabit/src/pages/PYQReplicaPage.jsx:143-162` and call `abort()` on cleanup.
11. **Bulk-fetch conversation metadata** — fix B4; rewrite the `_cache`-building loop in `artifacts/syrabit-backend/routes/conversations.py:117-151` as three bulk `find({"id": {"$in": ...}})` queries.
12. **Streaming chat disconnect + refund** — fix B5; add `request.is_disconnected()` polling in `artifacts/syrabit-backend/routes/ai_chat.py` stream generators and wire disconnect → `_refund_credit`.
13. **Raise instead of swallow in content routes** — fix B6; convert the outer `except Exception: return []` in `artifacts/syrabit-backend/routes/content.py:157-358, 374, 394` to raise `HTTPException(503)` with a logged stack trace.
14. **Hero image compression pass** — fix F4; recompress `artifacts/syrabit/public/yoga-cover-notext.webp` to ≤80 KB and add a mobile `<picture>` source ≤50 KB.
15. **Break up `BrowserPage.jsx`** — fix F5; extract `ReaderArticle`, `SidePanel`, `TabStrip` under `artifacts/syrabit/src/components/browser/` with co-located tests.
16. **Drop `axios` in favour of `fetch` + thin wrapper** — fix D2; migrate the remaining `axios` imports to the existing `apiClient()` and remove `axios` from `artifacts/syrabit/package.json`.
17. **Upgrade `pymongo` and prune `aiohttp`** — fix D1; bump `pymongo` to the latest 4.x, remove `aiohttp` if no direct imports remain in `artifacts/syrabit-backend/`.
18. **Track `ai_cache.aset` tasks and surface failures** — fix B7; keep the spawned tasks in a module-level `set()` with an `add_done_callback` that logs exceptions, or just `await` the write in `artifacts/syrabit-backend/cache.py`.
19. **Force `SECURE_COOKIES=true` in production** — fix C3; hard-override in `artifacts/syrabit-backend/routes/auth.py:102, 140` when `DEPLOYMENT_ENV == 'production'`, ignoring the env toggle.

---

*End of report. Every `file:line` reference above was hand-verified against the current main branch on 2026-04-23.*
