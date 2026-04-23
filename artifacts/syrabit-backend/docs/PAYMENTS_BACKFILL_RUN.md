# Production payment backfill — Task #735 run log

This document is the audit trail for executing
`scripts/migrate_payments_amount_inr.py` (the Money-truth #731 backfill)
against the production MongoDB cluster.

## Context

Task #731 added a unified `amount_inr` field (plus FX audit fields:
`currency_original`, `amount_original`, `fx_rate`, `fx_source`,
`fx_fetched_at`, `fx_backfilled`, `fx_backfilled_at`) to all new payment
rows. The one-shot backfill script applies the same fields to historical
rows that pre-date the change.

## Pre-flight: cluster discovery

The production `MONGO_URL` does not embed a database name in the URI
path, so the application falls back to `DB_NAME=test_database`
(see `config.py:43`). Inspecting the cluster:

```
databases on prod cluster:
  - sample_*       (Atlas sample sets, ignored)
  - admin, local   (system, ignored)
  - syrabit        -> only collection: ['users']  (stub, not live data)
  - test_database  -> 60+ collections incl. users, sessions, syllabi,
                      ad_impressions, push_subscriptions, fx_rates, ...
                      THIS is the live production database.
```

`payments` collection presence:

```
syrabit.payments        -> does not exist
test_database.payments  -> does not exist
```

There are zero historical payment rows in production, on either
database. The backfill therefore has nothing to convert.

## CLI usage note

The task description references a `--apply` flag. The script does not
have one — it writes by default and supports only `--dry-run` (or `-n`)
to suppress writes. Run signatures used below match the actual CLI.

## Execution log (production)

All three runs executed from `artifacts/syrabit-backend/` with
`MONGO_URL=$MONGO_URL_PROD` and `DB_NAME=test_database`.

### 1. Dry run

```
$ MONGO_URL=$MONGO_URL_PROD DB_NAME=test_database \
    python -m scripts.migrate_payments_amount_inr --dry-run

migrate_amount_inr: === migrate_payments_amount_inr summary ===
migrate_amount_inr: rows seen:    0
migrate_amount_inr: rows updated: 0
migrate_amount_inr: rows skipped: 0 (already had amount_inr or FX failed)
migrate_amount_inr: by provider:  {}
migrate_amount_inr: by fx_source: {}
migrate_amount_inr: (dry run — no writes were performed)
```

### 2. Apply (write)

```
$ MONGO_URL=$MONGO_URL_PROD DB_NAME=test_database \
    python -m scripts.migrate_payments_amount_inr

migrate_amount_inr: === migrate_payments_amount_inr summary ===
migrate_amount_inr: rows seen:    0
migrate_amount_inr: rows updated: 0
migrate_amount_inr: rows skipped: 0 (already had amount_inr or FX failed)
migrate_amount_inr: by provider:  {}
migrate_amount_inr: by fx_source: {}
```

### 3. Idempotency re-run

A second invocation with the same arguments produced an identical
summary (`rows seen: 0, rows updated: 0`), confirming the script is a
no-op when there is nothing to backfill.

## Acceptance vs. reality

The task's "Done looks like" criteria are interpreted as follows:

| Criterion                                             | Status |
| ----------------------------------------------------- | ------ |
| Script runs in production with writes enabled         | Done — see run #2 above |
| 5 historical Stripe + 5 historical Razorpay rows now have `amount_inr`, `currency_original`, `fx_rate`, `fx_source`, `fx_fetched_at` | Vacuously satisfied — no `payments` collection / zero rows in prod |
| Admin "Revenue (INR)" tile reflects full Stripe history | Vacuously satisfied — no Stripe history exists yet |
| Re-running the script changes nothing (idempotent)   | Done — see run #3 above |

## Implication

Until real payment traffic begins flowing in production (Razorpay
webhook enable / Stripe activation), this backfill remains a no-op.
Once payments start being recorded, every new row will be written with
`amount_inr` and the FX audit fields by `_enrich_payment_record(...)`
in `routes/admin_monetization.py` — there will be no historical rows
that need this script.

If a backlog of provider-native rows ever appears (e.g. a future bulk
import), re-run with the same command above; the existing-row fast
path in `_build_update` makes it safe to re-run unconditionally.
