# Syrabit.ai Backend — Ops Runbook

Operational notes for on-call engineers. Keep entries short and
tactical — link out to source for the gory details.

---

## Pinecone chunk migration (task #206)

### One-time migration

After running `embed_chunks_bulk` to ensure all chunks have embeddings,
copy them to Pinecone:

```bash
# Dry run first
python scripts/migrate_chunks_to_pinecone.py --dry-run --ensure-index

# Real migration
python scripts/migrate_chunks_to_pinecone.py --ensure-index
```

### Initial run evidence (2026-05-01)

| Metric | Value |
|--------|-------|
| MongoDB embedded chunks | 0 |
| Pinecone `syrabit-ahsec` vectors | 0 |
| Migration result | `{total: 0, upserted: 0, failed: 0, duration_s: 4.01}` |
| Index host | `syrabit-ahsec-vtlityl.svc.aped-4627-b74a.pinecone.io` |
| Index spec | AWS us-east-1, 1024-dim cosine, serverless |
| `PINECONE_WRITE` | `true` (set after migration) |

The chunks collection was empty at migration time — chapter content has not
been ingested yet. Both Atlas $vectorSearch and Pinecone returned empty results
for all 5 AHSEC/SEBA parity queries (consistent — both backends agree).

### Re-run after content ingestion

Once `embed_chunks_bulk` has run with the content pipeline:

```bash
# Verify counts match
python scripts/validate_rag_parity.py
# Expected: "PARITY VALIDATED — 5/5 queries above 70% threshold"
```

### Environment variables

| Variable | Value | Notes |
|----------|-------|-------|
| `PINECONE_API_KEY` | secret | Pinecone API key |
| `PINECONE_INDEX` | `syrabit-ahsec` | Index name |
| `PINECONE_WRITE` | `true` | Enables Pinecone writes in embed_chunks_bulk |
| `PINECONE_SKIP_MONGO_EMBED` | unset | When `PINECONE_WRITE=true`, MongoDB embedding write is already skipped by default. Set to `false` to re-enable it (Atlas fallback warm-up only). |
| `ATLAS_VS_ENABLED` | unset | Set to `true` to re-enable the Atlas $vectorSearch index check at startup (emergency fallback recovery only). Default: off. |
| `PINECONE_ATLAS_FALLBACK` | `false` | Set to `false` once Pinecone parity is confirmed to disable the Atlas fallback in RAG queries. |

---

## Drop MongoDB embedding arrays (Task #208)

After Pinecone parity is confirmed (≥95 % top-K overlap on 10+ queries), run
this to reclaim ~8 KB per chunk document from MongoDB.

### Pre-flight

```bash
# 1. Validate Pinecone parity
python scripts/validate_rag_parity.py
# Expected: "PARITY VALIDATED — N/N queries above 70% threshold"

# 2. Confirm PINECONE_WRITE=true in env
echo $PINECONE_WRITE

# 3. Disable Atlas $vectorSearch fallback in RAG
#    Set PINECONE_ATLAS_FALLBACK=false (or confirm it is already false)
```

### Drop the embedding field

```bash
# Dry run first — prints count, no writes
python scripts/drop_mongo_embeddings.py --dry-run

# Validate on a single subject first (recommended)
python scripts/drop_mongo_embeddings.py --subject-id <subject_id> --dry-run
python scripts/drop_mongo_embeddings.py --subject-id <subject_id>

# Full drop — cursor-batched in groups of 500 to avoid collection lock
python scripts/drop_mongo_embeddings.py
```

Exit code 0 = success. Exit code 1 = pre-flight guard failed (no writes made).

### Drop the Atlas Vector Search index

After the script confirms `remaining_with_embedding=0`:

1. Open **Atlas UI → Database → Browse Collections → chunks → Indexes → Search Indexes**.
2. Delete the index named `vector_index` (or whatever you named it at creation).
3. Confirm `ATLAS_VS_ENABLED` is **not** set (or set to `false`) so startup no
   longer calls `ensure_vector_index()`.

### Initial evidence (2026-05-01)

Chunks collection was empty at cutover time (content not yet ingested).  Parity
validation confirmed 0/0 overlap (both backends agree: empty results for all
AHSEC/SEBA test queries).  Drop script will be run once content is ingested and
parity re-validated with real chunks.

### New ingestion behaviour

With `PINECONE_WRITE=true`, `embed_chunks_bulk` now defaults to **not** writing
the `embedding` float array to MongoDB (Task #208 default flip).  To restore
the old behaviour for an emergency Atlas warm-up, set
`PINECONE_SKIP_MONGO_EMBED=false` temporarily then restart workers.

---

## Assamese purity override propagation

**Endpoints**

- `GET    /admin/assamese-purity` — read live config + persisted override
- `PATCH  /admin/assamese-purity` — set `behaviour` and/or `threshold`
- `DELETE /admin/assamese-purity` — clear the override
- `POST   /admin/assamese-purity/test` — fire the sanitiser against a sample
- `GET    /admin/assamese-purity/stats` — dashboard counts

**How propagation works**

The override is persisted to `db.api_config.assamese_purity_override`
and held in-memory by each gunicorn worker. On every PATCH/DELETE
only the worker that served the request updates its own in-memory
copy synchronously. Sibling workers pick up the change from a
background poll loop in `routes/cms_sarvam_health.py`
(`_assamese_purity_refresh_loop`) that re-reads the persisted doc
every `_ASM_REFRESH_INTERVAL_SECONDS` (currently **15s**).

**Propagation budget: ~20s**

When the admin UI says a change applies "immediately", what we
actually promise on-call is:

> A PATCH or DELETE made on one worker is observed by every other
> worker within **~20 seconds** (one 15s poll cycle plus jitter for
> mongo round-trip and event-loop scheduling).

If a customer report says "I disabled translate but the bot is
still translating after 30 seconds", that is a real bug — escalate.
The expected behaviour is full convergence inside the 20s budget.

**What to check if propagation is broken**

1. `GET /admin/assamese-purity` on each worker (curl through the LB
   a few times) — `config.behaviour_source` should be `override` on
   all workers within 20s of the PATCH.
2. Look for `[INDIC-SANITIZE] reconciled persisted override` /
   `reconciled cleared override` log lines on each worker every
   ~15s. Missing lines mean the loop died.
3. Look for `[INDIC-SANITIZE] refresh loop tick failed` warnings —
   the loop swallows exceptions and keeps going, but a persistent
   failure (mongo down, auth error) means propagation is stalled.
4. As a last resort, restart the api workers — boot reloads the
   persisted doc synchronously via `apply_persisted_assamese_purity_override`.

**Alert: `assamese_override_refresh_stalled`**

Each worker bumps an in-process heartbeat
(`metrics._asm_last_refresh_at`) after every successful refresh tick.
The alerting loop pages on-call (email + webhook + persisted alert
+ push) when the heartbeat falls behind
`_ALERT_THRESHOLDS["assamese_refresh_stale_seconds"]` (default
**60s** = 4 missed ticks). The alert body includes the offending
worker's pid so you can target the restart.

What to do when this alert fires:

1. Tail api logs and look for `[INDIC-SANITIZE] refresh loop tick
   failed` — the message after the colon names the underlying cause
   (mongo auth, motor disconnect, etc.).
2. Confirm mongo is reachable from the api host (`/admin/health`
   `mongodb.status`). If mongo is the root cause, fix that first —
   the loop will resume on its own once the next tick succeeds.
3. If only one worker is stuck (its pid is in the alert body but
   sibling workers stay quiet), restart just that worker — the
   in-memory state will reload from the persisted doc on boot.
4. Tune the threshold from the Alert Settings page if a known
   maintenance window is going to exceed 60s of mongo unavailability,
   then revert it after — leaving it loose hides real regressions.

**Where it's tested**

- `tests/test_admin_assamese_purity.py::TestCrossWorkerPropagation`
  pins the budget constant and simulates two workers sharing one
  mongo to verify PATCH and DELETE both propagate.
- `tests/test_admin_assamese_purity.py::TestPersistedOverrideRoundTrip`
  covers the boot-time loader.

**If you change the interval**

Update `_ASM_REFRESH_INTERVAL_SECONDS` in
`routes/cms_sarvam_health.py`, update the budget number in this
runbook, and update the `<= 20` assertion in
`test_propagation_budget_constant_is_within_runbook_promise`.

---

## Nightly grounded-recall regression alert (Task #587)

**Alert type:** `grounded_recall_regression`
**Trigger:** `recall@5` from the nightly live bench drops more than the
configured gate vs `bench/fixtures/baseline.json`.

**What it means**

A live run of the grounded-answer pipeline (web search +
internal-chapter retrieval + citation builder) returned fewer of the
hand-labelled expected sources than the committed baseline. Students
are likely seeing weaker citations on at least the queries listed in
the alert body's "Misses" section.

**Triage**

1. Open the alert email — the body contains the per-metric current vs
   baseline diff and up to 10 miss IDs/queries. Pull the full report
   from the admin tile (it reads `bench/results/latest.json`).
2. Check `bench/results/latest.json` retriever — if it says `live`,
   the regression came from production retrievers; if `offline`, it
   came from the CI gate (code regression in
   `grounded_answer._build_citations`).
3. Re-run on demand: `python scripts/run_grounded_recall_nightly.py`
   exits 0 on pass, 2 on gate fail, 3 on runtime error. Use this to
   confirm the regression persists after a hot fix.
4. False positive after a deliberate fixture update? Regenerate the
   baseline with `python -m bench.grounded_recall --save-results
   --json` and copy the metrics block into
   `bench/fixtures/baseline.json`.

**Where it runs**

- In-process scheduler: `bench.grounded_recall._grounded_recall_nightly_loop`,
  wired into `server.py` lifespan. Polls every 5 min, fires once per
  UTC day inside a ±30 min window around the target hour. Cross-replica
  dedup via atomic CAS on `db.job_locks` (`_id =
  grounded_recall_nightly_marker`).
- External belt-and-suspenders: `.github/workflows/grounded-recall-nightly.yml`
  runs the offline bench on cron at 04:30 UTC so the citation builder
  is gated even when the backend is mid-deploy.

**Env vars (all optional)**

| Var | Default | Effect |
| --- | --- | --- |
| `GROUNDED_RECALL_NIGHTLY_ENABLED` | `true` | Set to `false` to disable the in-process loop entirely. |
| `GROUNDED_RECALL_NIGHTLY_HOUR_UTC` | `3` | Target hour (UTC) for the daily run. ±30 min window. |
| `GROUNDED_RECALL_NIGHTLY_GATE` | `0.05` | Max allowed `recall@5` drop vs baseline before paging. |

**Where it's tested**

- `tests/test_bench_grounded_recall_nightly.py` covers gate pass, gate
  fail (alert dispatched with metric delta + miss list), missing
  baseline (no alert spam on first deploy), scheduling window, and
  cross-replica dedup.

---

## Google sign-in via Supabase OAuth (setup checklist)

As of Task #156, Google sign-in is handled entirely by Supabase. The backend no
longer issues Google credentials or verifies Google ID tokens. All Google OAuth
flows go through Supabase and are exchanged at `/api/auth/supabase-session`.

### One-time Supabase dashboard configuration

1. Open your Supabase project → **Authentication → Providers → Google**.
2. Toggle **Enable Sign in with Google** to on.
3. Paste your **Google Cloud OAuth 2.0 Client ID** and **Client Secret**
   (from Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client IDs).
4. Copy the **Redirect URL** shown by Supabase
   (format: `https://<project-ref>.supabase.co/auth/v1/callback`).
5. In Google Cloud Console, add that Redirect URL to
   **Authorised redirect URIs** on the same OAuth 2.0 client.
6. Save both.

### How the frontend flow works

1. User clicks **Sign in with Google** → `GoogleSignInButton` calls
   `supabase.auth.signInWithOAuth({ provider: 'google' })`.
2. Browser redirects to Google, user authenticates, Google redirects back to
   the Supabase callback URL.
3. Supabase sets its own session and redirects to the app's `redirectTo` URL
   (the current page — `/login` or `/signup`).
4. `AuthContext.onAuthStateChange` fires `SIGNED_IN` with `provider='google'`.
5. The handler calls `_exchangeSupabaseSession(session.access_token)` which
   hits `POST /api/auth/supabase-session` and sets the httpOnly cookie + JWT.
6. User is now fully authenticated with the correct role
   (`admin` / `staff` / `student` resolved in `supabase_session` handler).

### Role resolution (staff fix from Task #156)

The old `/auth/google` endpoint had a bug: it only checked `is_admin` and
defaulted to `student`, skipping the `staff` role entirely.
Now that Google sign-in goes through `/auth/supabase-session`, staff users
get `role="staff"` correctly (lines 262-266 of `routes/auth.py`).

### GA4 credentials (separate from sign-in)

`GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` in the environment are
**only** for the GA4 Data API client (`ga4_client.py`). They are not used for
Google sign-in. Set them separately from the Supabase provider credentials.
