# Syrabit.ai Backend — Ops Runbook

Operational notes for on-call engineers. Keep entries short and
tactical — link out to source for the gory details.

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
