# ADR: Remove Redis from the Python backend; replace with Cloudflare-native primitives

- **Status:** Proposed (user picked option **C — full removal** on 2026-04-25).
- **Owner:** main agent / backend
- **Supersedes:** ad-hoc decisions captured inline in `config.py:506-513`, `ai_cache.py:5-22`.
- **Implementation tasks:** see *Sequencing & rollout* — none of those tasks may start until this ADR is approved.

---

## 1. Context

Today the Python backend on Railway (`artifacts/syrabit-backend`) holds a soft dependency on Redis. The connection has already been demoted in two stages:

1. The Upstash REST client was deleted in the 2026-04 AI cache refactor (`ai_cache.py:151-156`).
2. `MEMORYSTORE_REDIS_URL` is currently pinned to `''` in `config.py:506-513` with a comment naming Cloudflare AI Gateway + edge KV as the intended replacements.

But the *code* that calls Redis is still in tree (13+ files, ~1,400 lines), guarded only by `if redis_client:` checks. Every one of those branches is currently dead code in production, which means:

- We pay maintenance cost (test stubs in `tests/_deps_stub.py`, the dual `_anon_redis_client()` late-binding accessor in `metrics.py:206-219`, the `_redis_*` helpers in `cache.py`, the Lua-script primitive in `db_ops.py:261-293`) for behaviour that never executes.
- Two security-critical primitives — *atomic credit deduction* and *anonymous chat history* — quietly fail back to behaviours we did not consciously choose:
  - `atomic_deduct_ip_credit` / `atomic_deduct_device_credit` return `False` immediately when `redis_client is None` (`db_ops.py:321-325, 368-373`), so credit checks **fail closed** (good — no double-spend) and pay no extra round-trip cost. The hidden cost is correctness, not latency: the moment we *do* re-enable a Redis-shaped client (any future operator who sets `MEMORYSTORE_REDIS_URL`), the Lua-script primitive becomes the path of record again — which means we cannot delete it unconditionally without a deliberate replacement first.
  - `redis_save_anon_conversation` no-ops silently — anonymous users currently have **no chat history at all**, despite the UI sidebar still being rendered.

This ADR locks down what replaces each of the six remaining Redis use-cases, in what order, and what we throw away when the migration completes.

## 2. Drivers and constraints

- **D1.** Single-region Railway → multi-region Cloudflare edge: Redis is region-pinned, KV/D1/DO live at the edge. We want the rate-limit / cache decision to be made at the POP serving the user, not 200 ms away in `us-west-1`.
- **D2.** Cost: Memorystore at the smallest size is ≈ $35/mo just to exist. Workers KV / D1 / Cache API are bundled into the existing Workers Paid plan ($5/mo) we already pay for the edge proxy.
- **D3.** Operational simplicity: one less stateful dependency on the platform we want to leave (Railway).
- **C1.** *Fail-closed* on credit deduction must be preserved. A wrong replacement = unlimited free anonymous credits.
- **C2.** Python ↔ Worker is **HTTP-only** (`fetch` over public internet). Every migrated use-case becomes one extra network hop from Railway → Cloudflare, typically 30–80 ms one way depending on the Railway region. Hot-path use-cases need an in-process L1 to mask that latency.
- **C3.** The Worker today exposes only HTTP routes. There is no RPC binding (no Service Bindings, no Queues consumer in the Python direction). Any "atomic" primitive must therefore live behind a regular HTTP endpoint that the Worker serves.
- **C4.** Existing Worker bindings: `RATE_LIMIT` (KV), `BOT_HTML_CACHE` (KV), `CONTENT_DB` (D1), `AI` (Workers AI). No Durable Objects yet; adding the first DO is a wrangler.toml + class export change, no new product.

## 3. Inventory snapshot (what Redis does today)

| # | Use-case                        | File / lines                              | Failure mode today          | Engineer-days to migrate |
|---|---------------------------------|-------------------------------------------|------------------------------|--------------------------|
| 1 | User session cache              | `auth_deps.py:183-225`                    | Falls back to Postgres (slow but correct) | 0.5 |
| 2 | Per-user / per-IP rate limiting | `auth_deps.py:313-365` (`check_rate_limit`) | Fails open to in-memory per-worker | 1 |
| 3 | AI/LLM response cache           | `ai_cache.py:130-200`                     | Already L1-only in prod      | 0.5 |
| 4 | Generic / chat / search / content caches | `cache.py:1-380`, `web_content.py:50-67` | Silent no-op (cold path)     | 1 |
| 5 | Anonymous chat history          | `cache.py:386-493`                        | Silent no-op (no history at all) | 2–3 |
| 6 | Atomic credit deduction        | `db_ops.py:261-336`, `db_ops.py:339-440`, `auth_deps.py` rate-limit-chat-optional | Fails closed (refuses request) | 2 |
| – | Cross-restart metrics aggregates | `metrics.py:206-673`, `chat_speedup_metrics.py` | In-memory only; daily charts truncate at every deploy | folded into #4 |

Total ≈ **7–8 engineer-days** of implementation, plus this ADR.

---

## 4. Per-use-case decisions

Each subsection follows the same template: **Today → Constraint → Options → Decision → Migration order → Rollback.**

### 4.1 User session cache

- **Today.** `_redis_get_session(user_id)` / `_redis_cache_session(user_id, user)` cache the Supabase user blob for ~30 min so authenticated requests skip the Postgres round-trip on every call.
- **Constraint.** Sessions are read on every authenticated request — adding one Cloudflare round-trip per request (≈ 60 ms p50 from Railway) would be a regression versus today's in-process miss path (Postgres ≈ 10–20 ms over the Railway private network).
- **Options.**
  1. **Stateless JWT** — embed the user blob (id, role, status, plan) in the access token, drop the cache entirely.
  2. Postgres + per-worker LRU (`cachetools.TTLCache`) — same code shape, no Cloudflare hop.
  3. Worker-validated session — admit + re-mint at the edge, pass header to backend.
- **Decision.** **Option 1 — stateless JWT** with a 15-minute TTL on the access token (we already mint refresh tokens). Banned/suspended status is checked at JWT issuance and on refresh; revocation latency = access token TTL = 15 min, which we explicitly accept (the existing Redis cache already had a 30 min TTL, so this *improves* revocation latency).
  - Rationale: the only state that matters per request is `id`, `role`, `is_admin`, `status`, `plan`. All five are stable for ≥ 15 min in 99% of cases.
  - Option 2 would just trade Redis for in-memory LRU — same per-worker inconsistency we're trying to leave.
  - Option 3 is over-engineered for the size of the user table.
- **Migration order.** Implementation task **R-01** (see §6). No data migration; new tokens are stateless from cutover. Old Redis-cached sessions naturally expire within 30 min.
- **Rollback.** Single env flag `AUTH_USE_STATELESS_JWT=false` reverts to the existing Postgres lookup path (the `_redis_get_session` call becomes a no-op when `redis_client is None`, which it already is). No DB schema change to revert.

### 4.2 Rate limiting

- **Today.** `check_rate_limit(key, max, window)` does `INCR` + `EXPIRE` on a `rl2:{key}:{bucket}` key. **Fails open to in-memory** when Redis is down (`auth_deps.py:317-328`) — i.e. each gunicorn worker enforces the limit independently, multiplying the effective limit by the worker count. Under a real attack on the current `redis_client is None` setup, a 10 req/min limit becomes 10 × workers req/min.
- **Constraint.** Rate limiting is the most-frequently-called Redis op (every authenticated and anonymous request). It must (a) be cross-worker consistent under load, (b) survive a Worker outage by failing to a *safer* state, not a more-permissive one, and (c) cost <10 ms p50 per check.
- **Options.**
  1. Cloudflare Rate Limiting Rules (zone-level, declarative). Free tier is path-pattern based, no per-user-id keying.
  2. Worker + KV counter (the pattern already in `workers/edge-proxy/src/index.ts:482-500`, `checkRateLimitKey`). Eventual consistency window ≈ 60 s globally.
  3. Worker + Durable Object — strong per-key consistency, ~10–30 ms cold/warm.
- **Decision.** **Option 2 — Worker + KV counter** as the primary path for all *advisory* rate limits (chat-per-minute by plan, CMS write limits, admin endpoints, login-attempt limiter, password-reset limiter). The strict per-device free-tier budget (30/day) and the per-IP coarse abuse cap are covered by §4.6 and use Durable Objects there — those two **are not duplicated here**.
  - The KV path is already implemented in the Worker; we only need to (a) widen its key shape to accept user-id / IP / device-token-id, and (b) call it from Python via `POST /internal/rate-limit/check`.
  - **KV consistency caveat.** Workers KV is *eventually consistent* across regions with a typical convergence window of ≤ 60 s. For a 60 s rate-limit window this is acceptable in the worst case (an attacker hitting from two POPs can briefly burst at 2× the per-window limit). For per-minute or shorter windows the over-burst is bounded by `(num_active_pops × limit)`, which is the same multi-worker over-burst we have today. We accept this trade-off for advisory limits and route the strict ones to DOs in §4.6.
  - Fail mode: if the Worker fetch raises or returns 5xx, **fail closed** (HTTP 429 to the client). This is a deliberate change from today's "fail open to in-memory" — it matches what the security team has wanted since the Task #793 device-cap work. The change is gated on `RATE_LIMIT_VIA_EDGE=true` so we can revert if a Worker outage causes a global 429 storm.
- **Migration order.** Implementation task **R-02**. Roll out behind `RATE_LIMIT_VIA_EDGE=true`; the Python `check_rate_limit` becomes a thin HTTP client when the flag is on, falls back to the existing in-memory path when off.
- **Rollback.** `RATE_LIMIT_VIA_EDGE=false` reverts to today's behaviour (in-memory per-worker, no Redis). No KV cleanup needed — KV entries naturally expire.

### 4.3 AI / LLM response cache

- **Today.** `ai_cache.aget(ns, key)` returns from L1 (`cachetools.TTLCache`, 2048 × 64 KB per worker) and would consult Memorystore if `MEMORYSTORE_REDIS_URL` were set (it isn't). The comment in `ai_cache.py:5-22` already names Cloudflare AI Gateway as the upstream LLM cache.
- **Constraint.** This is the biggest single cost saver in the system (Gemini/Sarvam responses can cost cents each). We need a global, multi-region cache that survives gunicorn restarts. p99 lookup must be ≤ 50 ms or it costs us more in latency than it saves in token spend.
- **Options.**
  1. Worker + Cloudflare Cache API (HTTP-shape: cache the `POST /api/ai/chat` response). Free, per-POP, automatic.
  2. Worker + D1 (SQL-shaped per-key lookup). Global, persistent, ≈ 5–10 ms.
  3. Keep L1-only — accept the per-worker hit rate.
  4. **Cloudflare AI Gateway** — caches the *upstream provider* call (Gemini, Sarvam) regardless of which Syrabit prompt produced it.
- **Decision.** **Two-tier: AI Gateway (option 4) for upstream LLM calls + L1 in-process (option 3) for hot-path dedupe.** This is what production already does — the migration is removing the dead `ai_cache.py` Memorystore branch and updating the docstrings to match reality.
  - Why not Cache API (option 1): our chat responses are SSE-streamed, which Cache API does not natively support. Caching the *final* assembled response would require an extra Worker route that re-buffers the stream — added complexity for negligible gain over what AI Gateway already provides at the upstream boundary.
  - Why not D1 (option 2): the unit of caching is "same prompt → same answer", which is exactly the AI Gateway shape (request hash → response). Reimplementing in D1 just moves the same lookup table to a less-purpose-built store.
- **Migration order.** Implementation task **R-03**. Mostly deletion: drop the Memorystore code path, simplify `init_async_client()` to always return `"L1_only"`, delete the `_breaker_*` and `_async_pool` symbols.
- **Rollback.** Trivial — restore the deleted `MEMORYSTORE_REDIS_URL` parsing in `config.py:480-503` and set the env var. AI Gateway stays on regardless (it's already serving production).

### 4.4 Generic / chat / search / content caches + cross-restart metrics aggregates

- **Today.** `cache.py:131-329` contains a grab-bag of `set_cache(key, val, ttl)` / `get_cache(key)` helpers used by the search route, chat route, content route, and the URL-content cache (`web_content.py:50-67`). Plus `metrics.py:251-309` writes per-day HASHes for the admin chart, and `chat_speedup_metrics.py` flushes per-day counters every 30 s for cross-restart durability.
- **Constraint.** None of these are hot-path enough to justify a Worker round-trip per call (cache miss is OK; we just lose the memo). But the per-day aggregates *must* survive gunicorn restarts or the admin charts truncate every deploy.
- **Options.**
  1. Fold both into the AI cache decision (Worker + Cache API).
  2. Worker + D1 — small, structured, per-day keys.
  3. Postgres — we already have it; one new `cache_kv` table.
- **Decision.** **Split.**
  - *Hot in-process caches* (search, chat, content, URL-content): **gate behind `LEGACY_CACHES_DISABLED=true`** to switch the runtime branches off, then delete the dead code 7 days later in R-08. The per-worker `cachetools.TTLCache` already used as the L1 is the new path of record. None of these need cross-worker visibility — a stale 30-second cache per worker is acceptable for everything except the admin metrics tile, and that tile moves to D1 below.
  - *Cross-restart metrics aggregates* (`metrics.py` daily hashes, `chat_speedup_metrics.py` per-day counters): **migrate to Worker + D1** (option 2 — Cloudflare-native primary, per task scope). The Worker exposes two endpoints:
    - `POST /internal/metrics/incr` — body `[{day, bucket, field, delta}]`, batched flush from Python every 30 s.
    - `GET  /internal/metrics/range?day_from=…&day_to=…&bucket=…` — returns rows for the admin chart endpoint.
    New D1 table (added to `workers/edge-proxy/migrations/`):
    ```sql
    CREATE TABLE metrics_daily_kv (
      day      TEXT NOT NULL,             -- YYYY-MM-DD
      bucket   TEXT NOT NULL,
      field    TEXT NOT NULL,
      value    REAL NOT NULL DEFAULT 0,
      PRIMARY KEY (day, bucket, field)
    );
    ```
    With `INSERT ... ON CONFLICT DO UPDATE SET value = value + excluded.value` for HINCRBY-shaped writes. Flush volume: ≈ 50 rows / 30 s = ~144 K writes/day, well inside the D1 5 M writes/day paid-plan quota. KV monitor in `workers/edge-proxy/src/kv-monitor.ts` should be extended to alert on D1 write volume too (R-05 sub-task).
    Postgres remains the documented **fallback** for §4.4 aggregates if D1 write quota becomes a concern at scale (one new table on the existing Supabase/Railway pg, same UPSERT shape).
  - *Why D1 over Postgres as primary:* task scope mandates Cloudflare-native primaries. D1 also keeps the admin chart read path at the edge (single CF round-trip from the Worker, no Railway hop), so the chart loads faster.
  - *Why not Cache API:* aggregates are *additive* writes (HINCRBY), not whole-blob replaces; Cache API is a blob store, not a counter store.
- **Migration order.** Implementation task **R-04** (gate hot-path Redis branches behind `LEGACY_CACHES_DISABLED`), **R-05** (D1-backed aggregates behind `METRICS_AGG_VIA_D1`).
- **Rollback.** R-04: flip `LEGACY_CACHES_DISABLED=false` to re-enable the Redis branches (which are still no-ops in production because `redis_client is None`, but the safety net exists for any future operator who re-enables Memorystore). R-05: flip `METRICS_AGG_VIA_D1=false` to revert to in-memory-only aggregates (charts truncate at restart again, but no incorrectness). D1 table is left in place; harmless if unused.

### 4.5 Anonymous chat history (highest design risk)

- **Today.** `cache.py:386-493` stores anonymous conversations as Redis ZSETs (`anon_idx:{anon_id}` → `{conv_id: timestamp}`) plus per-conv JSON blobs (`anon_conv:{anon_id}:{conv_id}`), capped at 20 conversations per `anon_id`. The Redis branch is dead in production today, so **anonymous users currently have no persisted chat history** despite the UI sidebar rendering one.
- **Constraint.** Two competing requirements:
  - Product: anon users see their last ~20 chats when they reload the page (this is a measurable conversion lift before the wall-hit).
  - Privacy / compliance: anon chats are personal data; if we store them server-side they enter our retention policy and DSAR scope.
- **Options.**
  1. **Client-side IndexedDB.** Lossy on device wipe / browser reset, but zero server-side state. No DSAR scope; no retention policy needed beyond "user's browser controls it".
  2. Worker + D1, keyed by stable anon-id cookie. Cross-device-but-same-cookie history; needs explicit retention (e.g. 30-day TTL via cron-driven `DELETE FROM anon_conv WHERE updated_at < now() - 30d`).
  3. "No history" UX — remove the sidebar for anonymous users.
- **Decision.** **Option 1 — IndexedDB on the client**, with a small backend escape hatch (option 2-lite) only for the *active* in-flight conversation.
  - Rationale: matches the privacy story we already tell anon users ("we don't keep your conversations") and sidesteps the DSAR/retention question entirely. The sidebar becomes "your chats on this device" — which is the truthful framing.
  - The backend still needs to assemble the anon conversation *during* the in-flight request (the chat route reads prior turns to build context), so we keep a 1-conversation, 30-minute Redis-replacement: a single `anon_active_conv:{anon_id}` key in Worker KV with a 30-minute TTL. Written by Python via `POST /internal/anon-conv/active`, read at the start of the next chat turn.
  - **POP-affinity caveat.** Cloudflare KV is eventually consistent across regions and there is **no guarantee** that the same anon-id cookie lands on the same POP between turns (Cloudflare routes by network proximity, not cookie identity). In practice the typical KV propagation window is ≤ 60 s, which means an anonymous user whose two consecutive chat turns happen to land on different POPs within that window may get an empty prior-turns context for the second turn — equivalent to starting a fresh conversation. We accept this trade-off because (a) anon turns are typically minutes apart, well outside the propagation window, and (b) the failure mode is "lose context", not "show wrong user's data". If the rate of cross-POP misses ever becomes user-visible (>1 % of anon turns), the fix is to switch the active-conv store from KV to a Durable Object keyed on the anon-id, same shape as §4.6.
  - Why not D1 (option 2): the cross-device promise is illusory. Anon-id cookies are per-browser; an anon user "switching devices" actually has no shared identity. Storing 30 days of every anon's history is data we'd have to defend in a breach.
  - Why not "no history" (option 3): the conversion lift from showing prior chats is real; we just want it stored client-side.
- **Migration order.** Implementation task **R-06** (frontend IndexedDB store + Python active-conv KV write). This is the only use-case that requires *frontend* work.
- **Rollback.** Two-stage: (a) frontend can fall back to "no history" (option 3) instantly via a feature flag if IndexedDB has a bug; (b) backend's KV active-conv is best-effort — if it fails, the chat route just gets an empty prior-turns context, which is the same behaviour as a brand-new conversation.
- **Open question for user:** the admin "Recent anonymous conversations" panel (`redis_list_all_anon_conversations`) goes away under this decision. We have not seen a compelling support workflow that depends on it (the support team uses the wall-hit metrics in `metrics.py`, not raw transcripts). **Confirm with user before R-06 starts.**

### 4.6 Atomic credit deduction (security-critical)

- **Today.** `db_ops.py:261-293` defines a Lua script (`_REDIS_DEDUCT_LUA`) that atomically seeds a counter, then `INCR`s only if the post-increment value is within the limit. Called by `atomic_deduct_ip_credit` (per-IP coarse abuse cap, `IP_COARSE_DAILY_CAP`) and `atomic_deduct_device_credit` (the per-device free-tier 30/day budget — Task #793). Both **fail closed** when `redis_client is None`. There's also a user-credit branch in `atomic_deduct_credit` (db_ops.py:439-523) with a Supabase fallback.
- **Constraint.** This is the only Redis use-case that today actually prevents a security regression: without atomic check-and-increment, two concurrent requests from the same anon IP/device could each see "29 used, 30 limit" and both deduct, ending at "31 used" with two free messages served against a 30/day budget. Replacement *must* preserve single-actor atomicity.
- **Options.**
  1. **Worker + Durable Object** — DOs are purpose-built single-actor counters; one DO per `(anon_id_or_device_id, day)` partition. Strong consistency, ≈ 10–30 ms per call from a nearby POP, ≈ 60–120 ms from Railway → POP → DO.
  2. **Postgres `SELECT ... FOR UPDATE`** — row-level lock on a `daily_credits(actor_id, day, used, limit)` table. No Worker dependency, ≈ 5–15 ms over the Railway private network. Already what `atomic_deduct_credit`'s last-resort branch does for *user* credits (`db_ops.py:510-523`).
  3. **Postgres advisory locks** (`pg_advisory_xact_lock(hashtext(actor_id))`) — lighter-weight than row locks, but harder to reason about across migrations.
- **Decision.** **Option 1 — Worker + Durable Object** as the Cloudflare-native primary (per task scope), with **Option 2 — Postgres `SELECT ... FOR UPDATE`** kept on as the documented and code-shipped fallback that activates whenever the DO call fails or its p99 latency goes above a configurable budget.
  - Why DO over Postgres as primary: task scope mandates Cloudflare-native primaries, and DOs are the *only* primitive in the Cloudflare stack with single-actor strong consistency — exactly the guarantee the Lua script provides today. KV is eventually consistent (wrong for a check-and-increment; lets two concurrent requests both see "29 used" briefly). D1 is eventually consistent across replicas. Cache API is a blob store. DO is the right tool.
  - Worker shape: one Durable Object class `AnonCreditDO` keyed by `${actor_kind}:${actor_id}:${day}` (e.g. `device:abcd…:2026-04-25`). Each DO instance holds `{used, day_limit}` in its transactional storage. The Worker exposes `POST /internal/anon-credits/charge` which forwards to the DO's `fetch("/charge")`, and the DO atomically: load → check `used < day_limit` → `used += 1` → persist → return `{ok: true, used}` (or `{ok: false}` if exhausted). Single-actor semantics are enforced by the DO runtime — no Lua needed.
  - Latency budget: Railway → POP → DO → POP → Railway is ≈ 80–150 ms p99. We accept this for a check that is already in the path of a 2–5 s LLM call. If Railway → Worker p99 exceeds 200 ms for ≥ 5 % of calls in a 10-minute window, the Python client trips an in-process circuit breaker and falls through to the Postgres path below.
  - Postgres fallback (always shipped, cold by default):
    ```sql
    CREATE TABLE anon_daily_credits (
      actor_kind TEXT NOT NULL CHECK (actor_kind IN ('ip','device')),
      actor_id   TEXT NOT NULL,
      day        DATE NOT NULL,
      used       INTEGER NOT NULL DEFAULT 0,
      day_limit  INTEGER NOT NULL,
      PRIMARY KEY (actor_kind, actor_id, day)
    );
    ```
    With a daily cron (or lazy `WHERE day < CURRENT_DATE - 7`) prune. The Lua script's "seed if absent + check + increment" maps to a single `INSERT ... ON CONFLICT (actor_kind, actor_id, day) DO UPDATE SET used = anon_daily_credits.used + 1 WHERE anon_daily_credits.used < anon_daily_credits.day_limit RETURNING used` — atomicity comes from the row-level lock taken by `ON CONFLICT DO UPDATE`. **Deadlock risk:** none, because each transaction touches exactly one row identified by the full primary key, so the lock-acquisition order is total. We do not take any explicit `FOR UPDATE` — the implicit upsert lock is enough and is held for sub-millisecond windows.
  - Fail mode: if both DO and Postgres are unreachable, `atomic_deduct_*` returns `False` (fail closed) — preserves today's "no double-spend on outage" guarantee, with the new property that an outage no longer = "all anonymous chat blocked" because Postgres is independent of the Worker.
- **Migration order.** Implementation task **R-07**. Roll out behind `ANON_CREDITS_VIA_DO=true` (DO + Postgres fallback both active); the old Redis path stays compiled but unreachable for one deploy cycle. After 7 stable days, R-08 removes the Redis branch.
- **Rollback.** Two-stage:
  - Stage 1 (fast): `ANON_CREDITS_VIA_DO=false` — Python falls through to the Postgres path directly, skipping the Worker. This is the same code path the runtime circuit breaker uses, so it has continuous test coverage.
  - Stage 2 (slow): if both DO and Postgres prove unworkable, restoring Redis is a documented operation (re-set `MEMORYSTORE_REDIS_URL` and `git revert` R-08's deletion of the Lua script).

---

## 5. Cross-cutting concern: Worker-from-Python boundary

For the use-cases that *do* migrate to the Worker (rate limiting §4.2, anon active-conv §4.5), every check is now a `POST` from Railway → `api.syrabit.ai/internal/*`. The existing `BACKEND_ORIGIN_SECRET` pattern (Worker → Railway) needs an inverse: a `WORKER_INTERNAL_SECRET` that Railway sends in `X-Internal-Auth` so the Worker can reject random callers.

| Use-case            | Failure path when Worker is unreachable |
|---------------------|------------------------------------------|
| §4.1 sessions       | n/a — no Worker call                     |
| §4.2 rate limit     | **fail closed (429)**                    |
| §4.3 AI cache       | n/a — L1 only                            |
| §4.4 generic caches | n/a — per-worker L1 only                 |
| §4.4 metrics aggregates | n/a — Postgres                       |
| §4.5 anon active-conv | empty prior context (correctness preserved, lose ~1 turn of memory) |
| §4.6 credit deduct  | n/a — Postgres                           |

Net new HTTP calls per chat request: **2** (rate-limit check + anon-active-conv read), both ≤ 80 ms p99. We will instrument both with the existing `chat_speedup_metrics.record_provider_call` helper to keep eyes on regression.

## 6. Sequencing & rollout

Tasks listed in dependency order. Each ships behind one Railway env flag so rollback = one variable flip + `railway up`.

| Task | Title | Depends on | Flag                       | Risk  | Days |
|------|-------|------------|----------------------------|-------|------|
| R-01 | Stateless JWT for sessions               | —    | `AUTH_USE_STATELESS_JWT`   | Low   | 0.5  |
| R-02 | Worker KV rate-limit + Python HTTP client | —   | `RATE_LIMIT_VIA_EDGE`      | Med   | 1    |
| R-03 | Gate `ai_cache.py` Memorystore branch off (Phase A — switch path, keep code) | — | `AI_CACHE_L1_ONLY`     | Low | 0.25 |
| R-04 | Gate generic / search / chat / content / URL cache Redis branches off  | R-03 | `LEGACY_CACHES_DISABLED` | Low | 0.5 |
| R-05 | `metrics_daily_kv` D1 table + Worker incr/range endpoints + Python flush rewrite | R-04 | `METRICS_AGG_VIA_D1`     | Med   | 1.5  |
| R-06 | Anonymous chat history → IndexedDB + KV active-conv | (frontend coordination) | `ANON_HISTORY_INDEXEDDB` | High | 2–3 |
| R-07 | `AnonCreditDO` Durable Object + Worker `/internal/anon-credits/charge` + Python client + Postgres fallback table | R-04 | `ANON_CREDITS_VIA_DO`   | High  | 2.5  |
| R-08 | Phase B cleanup — delete the gated-off Redis branches, `redis_client`, `deps.py:36`, `cache.py`, test stubs, Railway env vars (`MEMORYSTORE_REDIS_URL`, `UPSTASH_REDIS_REST_*`) | R-01..R-07 all live ≥ 7 days | (none — pure deletion of code already proven cold) | Low | 0.5 |

Cutover protocol per task:
1. Land code with flag default = OFF.
2. Flip flag in Railway, watch `/admin/diagnostics` and the relevant counter for 24 h.
3. If green for 24 h, leave on. If red, flip flag back, no code revert needed.
4. After all flags have been ON for 7 days continuously, R-08 deletes the flag-checks and the Redis client.

## 7. What we throw away

After R-08 lands, the following code becomes deletable:

- `artifacts/syrabit-backend/cache.py` — entire file (495 lines).
- `artifacts/syrabit-backend/ai_cache.py` — Memorystore + circuit breaker (≈ 200 of 478 lines); keep the L1 helpers and stats.
- `artifacts/syrabit-backend/deps.py:36` — `redis_client = …` initialisation.
- `artifacts/syrabit-backend/config.py:465-513` — entire `MEMORYSTORE_REDIS_URL` block, all `REDIS_*_TTL` constants except those still used by per-worker L1.
- `artifacts/syrabit-backend/db_ops.py:256-293` — `_REDIS_DEDUCT_LUA`, `_REDIS_DEDUCT_SCRIPT_CACHE`, `_redis_atomic_deduct`.
- `artifacts/syrabit-backend/db_ops.py:439-509` — Redis branches inside `atomic_deduct_credit`; keep the Postgres+Supabase fallback as the primary.
- `artifacts/syrabit-backend/web_content.py:50-67` — Redis URL-content cache.
- `artifacts/syrabit-backend/metrics.py:206-309` — `_anon_redis_client`, `_persist_anon_exhaust_daily_agg`, `_read_anon_exhaust_daily_agg` (replaced by D1 `metrics_daily_kv` writes via the Worker, see §4.4).
- `artifacts/syrabit-backend/metrics.py:459-485, 525-560` — Redis push branches inside `record_anon_quota_exhausted` / `record_signup_with_device`.
- `artifacts/syrabit-backend/chat_speedup_metrics.py:41-57, ~load_from_store/flush_to_store internals` — Redis HASH layout (replaced by D1 UPSERT via the Worker, see §4.4).
- `artifacts/syrabit-backend/auth_deps.py:183, 218` — `_redis_get_session` / `_redis_cache_session` calls (functions themselves can be deleted from `cache.py`).
- `artifacts/syrabit-backend/auth_deps.py:317-328` — Redis branch inside `check_rate_limit`; the in-memory fallback also goes if R-02 ships its own client.
- `artifacts/syrabit-backend/server.py:1108-1119` — `chat_speedup_metrics.load_from_store` if R-05 moves the rehydrate to a D1-backed initializer (read via the Worker `/internal/metrics/range` endpoint at startup).
- `tests/_deps_stub.py` — fakeredis install branch.
- `tests/test_atomic_deduct_ip_race.py`, `tests/test_atomic_deduct_device_credit.py` — rewritten against the Postgres path (do not delete; the regression coverage is too valuable).
- `requirements.txt` — `redis`, `fakeredis` (only `redis.asyncio` was imported; both can go).
- Railway env vars: `MEMORYSTORE_REDIS_URL`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`.

Estimated net deletion: ≈ **1,400 lines** of Python + 2 dependencies + 3 env vars.

---

## 8. Open questions for the user before implementation starts

1. **Anonymous chat history admin view (§4.5).** Confirm we can drop the `redis_list_all_anon_conversations` admin panel — no support workflow currently depends on raw anon transcripts (the wall-hit metrics in `metrics.py` are unaffected).
2. **Workers Paid plan ceiling.** R-02 will push KV writes from ≈ 1 K/day (current bot-spoof counter) to ≈ 50–100 K/day. Still well inside the 1 M/day Workers Paid quota, but we should confirm before R-02 ships.
3. **DO future-proofing.** §4.6 picks Postgres; if we later change platform off Railway and lose the private-network Postgres path, R-07 should be re-evaluated against the DO option.
