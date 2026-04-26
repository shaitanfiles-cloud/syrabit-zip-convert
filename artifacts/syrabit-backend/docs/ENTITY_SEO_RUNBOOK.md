# Entity SEO + Knowledge Graph Runbook

Operational guide for the weekly Entity SEO health worker that powers the
admin "Entity SEO" panel (Task #940). Covers configuration, manual
operator actions (filing claims, pitching mentions), schedule details,
and incident response when the drift alerter pages.

---

## What this monitors

The worker (`entity_seo_health.aggregate_snapshot`) probes six off-site
signals every Monday at 04:30 UTC and persists the snapshot to the
`entity_seo_health` Mongo collection:

| Signal       | Source                                           | "Healthy" means                                   |
| ------------ | ------------------------------------------------ | ------------------------------------------------- |
| `wikidata`   | `Special:EntityData/{QID}.json`                  | QID resolves and has the desired claims filed.    |
| `wikipedia`  | `en.wikipedia.org/api/rest_v1/page/summary/...`  | Article exists and isn't blanked.                 |
| `crunchbase` | Public org page HTML                             | Page reachable; tracked fields detected.          |
| `sameas`     | HEAD-probe of every verified org/founder profile | Every URL returns 2xx and stays on its own host.  |
| `google_kg`  | Knowledge Graph Search API                       | Panel entry surfaces for **every** tracked query. |
| `mentions`   | GET each `MENTION_OPPORTUNITY_TARGETS` page      | The page body mentions "Syrabit" (case-insens.).  |

The aggregate panel status is `ok` only when every signal is `ok`;
`degraded` when any signal errors; otherwise `missing`.

---

## Environment variables

All collectors are gated by env so an admin can rotate identifiers
without a redeploy.

| Var                                | Purpose                                                                                              | Example                  |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------ |
| `ENTITY_SEO_WIKIDATA_QID`          | Syrabit.ai's Wikidata QID. Empty until the entity is approved — collector reports `missing` cleanly. | `Q123456789`             |
| `ENTITY_SEO_WIKIPEDIA_TITLE`       | Article title (URL-encoded form is fine).                                                            | `Syrabit.ai`             |
| `ENTITY_SEO_CRUNCHBASE_PERMALINK`  | The slug after `/organization/` on the Crunchbase URL.                                               | `syrabit-ai`             |
| `GOOGLE_KG_API_KEY`                | Free-tier Google Knowledge Graph Search API key. Without it the `google_kg` signal reports `error` (configured=false). | (set in admin secrets)   |

Stable, code-reviewed lists (kept in `entity_seo_health.py` rather than
env so changes are auditable):

* `SYRABIT_KG_QUERIES = ("Syrabit", "Syrabit.ai")` — the Knowledge Panel
  is monitored for *both* the brand short-name and the full domain.
* `VERIFIED_ORG_SAMEAS` / `VERIFIED_FOUNDER_SAMEAS` — the canonical
  social profile lists; also drives the founder `sameAs` JSON-LD
  emitted by `jsonld.js` (closes #558).
* `DESIRED_WIKIDATA_CLAIMS` — the property set the panel will surface
  as "file this claim" deep-link rows.
* `MENTION_OPPORTUNITY_TARGETS` — the third-party pages we want to
  surface a Syrabit mention on.

---

## Schedule + locking

* Target window: **Monday 04:30 UTC ± 15 minutes** (≈ 10:00 IST).
* Polling: the worker wakes every 5 minutes (`_LOOP_SLEEP_S`) after a
  15-minute warm-up (`_WARMUP_S`).
* Dedup: `db.job_locks[entity_seo_health_lock]` records the ISO week
  of the last successful run. If the service was down during the
  Monday window, a boot-time catch-up rerun is triggered the moment
  the worker comes back up — it will not silently skip a week.

---

## Drift alerter

* Compares the current snapshot vs the immediately previous one.
* A "regression" is a signal whose status moved backwards on the
  ranking `ok → missing → error`.
* Wikidata claim removals are suppressed when the current Wikidata
  signal is itself non-`ok` (otherwise a 404 on the QID would mass-page
  every claim disappearing).
* Pages via `metrics._dispatch_alert` with type `entity_seo_drift`,
  using a stable fingerprint (sorted regression names) so the same
  drift doesn't repage.
* **Debounce**: 24 h (`_ALERT_DEBOUNCE_S`). While the same drift
  persists, the alerter stays silent until the lock-doc clears.

---

## Operator playbook

### Filing a Wikidata claim

1. In the admin panel → SEO Manager → **Entity SEO** tab, find the
   "Wikidata claims to file" card.
2. Click **File on Wikidata** next to the missing property — it deep
   links into `https://www.wikidata.org/wiki/{QID}#{Pxxx}`.
3. Add the statement, save on Wikidata (you need a Wikidata account in
   good standing — COI rules apply, declare you're filing for
   Syrabit.ai if you're an employee).
4. Back in the panel, click **Re-probe now**. The worker bypasses the
   weekly window and fetches fresh data — the row should disappear and
   the `wikidata` signal pill should flip to `Healthy`.

### Creating the Wikidata QID (first time)

If `ENTITY_SEO_WIKIDATA_QID` is empty, the panel surfaces a
**Special:NewItem** deep link:

1. Click any "File on Wikidata" row → routes you to
   `Special:NewItem?label=Syrabit.ai`.
2. Create the entity with `instance of (educational technology
   company)` (P31 → Q1077366) as the bare minimum claim.
3. Once published, copy the resulting `Q…` id and set
   `ENTITY_SEO_WIKIDATA_QID` in admin secrets.
4. Restart the API workflow so the new env value is picked up.
5. Click **Re-probe now** — every desired claim that's still missing
   will now deep-link into the new QID.

### Updating the Crunchbase profile

1. The panel's Crunchbase card surfaces `completeness_pct` (a heuristic
   over the rendered HTML for description / founders / location /
   website strings).
2. Click **Open** to land on the public org page; sign in with a
   Crunchbase contributor account, hit *Edit*, fill the missing fields,
   and submit.
3. Re-probe. Score should rise.
4. If the org page slug ever changes, update
   `ENTITY_SEO_CRUNCHBASE_PERMALINK` in admin secrets and restart.

### Pitching a mention opportunity

1. The "Mention Opportunities" card lists Wikipedia pages where
   Syrabit *should* appear but doesn't yet.
2. Click **Open page** to read the article and identify a natural
   citation slot (an existing list, a "see also" section, etc.).
3. Either edit the article directly (must satisfy WP:RS / WP:NPOV),
   or post a `{{request edit}}` on the talk page if you have a COI.
4. Re-probe after the edit lands. The body regex is case-insensitive
   so any spelling of "Syrabit" anywhere on the page flips the row to
   `ok`.

### Verifying a sameAs profile after rebrand

1. The panel's sameAs card shows total probed and broken count.
2. If a profile is flagged `missing` because of an off-site redirect
   (e.g. a deleted LinkedIn company page), update the canonical URL
   list in `entity_seo_health.py` (`VERIFIED_ORG_SAMEAS` /
   `VERIFIED_FOUNDER_SAMEAS`).
3. Ship the change through code review — these lists are **not** env,
   so a redeploy is required.

---

## Incident response (drift page received)

When the alerter fires `entity_seo_drift`:

1. Open the admin panel → Entity SEO. The aggregate pill will be
   `degraded` and the **regression list** at the top names the broken
   signals.
2. Triage by signal:
   * `wikidata` → entity may have been deleted / vandalised. Check the
     QID's history page on Wikidata and revert if needed.
   * `wikipedia` → article blanked or AfD'd. Check the article history
     and the talk page.
   * `crunchbase` → profile suspended or merged. Log in and check.
   * `sameas` → a profile started 404ing or off-site redirecting.
     Confirm whether the underlying account was deleted / renamed.
   * `google_kg` → the panel stopped surfacing for a tracked query.
     Often transient (Google re-indexes); wait one week. If it
     persists, audit the entity's `wikidata` + `wikipedia` upstream
     signals first — those drive the panel.
3. After fixing the upstream issue, click **Re-probe now**. Once the
   regression clears, the `entity_seo_drift_alert_lock` doc is wiped
   on the next loop tick, re-arming the alerter.

---

## Manual probe (CLI / one-off)

```py
import asyncio
import entity_seo_health as esh
snap = asyncio.run(esh.aggregate_snapshot())
print(snap["aggregate_status"], snap["summary"])
```

This bypasses Mongo entirely and is safe to run from a Python REPL on
a debugging shell.

---

## Files

* `artifacts/syrabit-backend/entity_seo_health.py` — collectors, drift
  detector, weekly loop.
* `artifacts/syrabit-backend/routes/admin_entity_seo.py` — three admin
  endpoints (`/admin/seo/entity/{status,history,refresh}`).
* `artifacts/syrabit-backend/server.py` — wires the loop in
  `startup_event` and includes the admin router.
* `artifacts/syrabit/src/components/admin/seo-manager/EntitySeoTab.jsx`
  — the panel UI.
* `artifacts/syrabit/src/lib/jsonld.js` — emits the founder `sameAs`
  block (closes #558).
