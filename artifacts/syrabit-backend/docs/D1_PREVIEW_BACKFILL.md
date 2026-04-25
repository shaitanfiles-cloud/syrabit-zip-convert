# Preview D1 backfill — Railway → Cloudflare D1 fan-out

Task #879. The preview Worker (`syrabit-edge-preview`) is bound to a
dedicated D1 database (`syrabit-content-preview`,
id `35e59391-218e-4e94-bbf5-972baa0d0b30`) that starts empty after every
deploy. Until it is populated, every preview-tier smoke test that hits a
content endpoint (`/api/content/subjects`, `/api/content/boards`,
`/api/edge/d1-status`) returns zero rows — masking real regressions.

We solve this with a Railway-side fan-out. Whenever the prod backend runs
a D1 sync (CRUD-driven, manual via `POST /api/admin/d1-sync`, or the
6-hourly worker cron pulling `/api/admin/d1-export`), the same payload is
ALSO POSTed to the preview hostname when the env vars below are set.

## Cadence

- **CRUD writes (per change):** every admin write to boards / classes /
  streams / subjects / chapters / topics / `seo_pages` calls
  `_schedule_d1_sync_fire(...)` which fans out to prod and (when
  configured) preview within seconds.
- **Manual full backfill:**
  `curl -X POST "$BACKEND/api/admin/d1-sync" -H "Authorization: Bearer <admin-jwt>"`.
- **Scheduled (every 6 h):** the prod worker cron
  (`0 */6 * * *`) pulls `/api/admin/d1-export` from Railway and writes
  prod D1; the same Railway export is what the fan-out re-uses, so a
  CRUD-quiet day still keeps preview within 6 hours of prod.

The preview cron itself is **intentionally disabled**
(`[env.preview.triggers] crons = []`) — the Railway fan-out is the only
sync path into preview.

## One-time enable (~5 min)

```bash
# 1. Generate + bind the preview-side secret on the worker
SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')
echo "$SECRET" | pnpm --filter syrabit-edge dlx wrangler \
  secret put D1_SYNC_SECRET --env preview

# 2. Add to Railway service env (same value as step 1)
#    EDGE_WORKER_PREVIEW_URL=https://syrabit-edge-preview.<account>.workers.dev
#    D1_SYNC_SECRET_PREVIEW=<paste $SECRET>

# 3. Trigger one full sync to backfill preview from prod
curl -X POST "https://api.syrabit.ai/api/admin/d1-sync" \
  -H "Authorization: Bearer $ADMIN_JWT"

# 4. Verify
pnpm --filter syrabit-edge run smoke:preview
# step [3b/7] d1-counts must report non-zero boards / subjects / chapters
```

## On-call procedure when preview rows go to zero

Symptom: `pnpm --filter syrabit-edge run smoke:preview` fails at
`[3b/7] d1-counts` with `boards=0 subjects=0 chapters=0`.

Diagnosis (top → bottom; stop at the first hit):

1. **Confirm fan-out is wired:** on the Railway backend, run
   `python -c "from d1_sync import is_preview_fanout_configured; print(is_preview_fanout_configured())"`.
   Must print `True`. If `False`, check that BOTH `EDGE_WORKER_PREVIEW_URL`
   and `D1_SYNC_SECRET_PREVIEW` are set and the secret is not the
   placeholder string from `.env.example`.
2. **Confirm the preview Worker accepts the secret:**
   `curl -i -X POST "$EDGE_WORKER_PREVIEW_URL/api/edge/d1-sync" -H "Authorization: Bearer $D1_SYNC_SECRET_PREVIEW" -H "Content-Type: application/json" -d '{"boards":[]}'`.
   Expect `200` (it accepts the empty payload). `401` means the secret
   bound on the worker (`wrangler secret put D1_SYNC_SECRET --env preview`)
   does not match what Railway is sending.
3. **Tail Railway logs** for `D1 sync (preview)` lines. A recurring
   `WARNING D1 sync (preview) HTTP 5xx` means the preview Worker is
   crashing on the payload — usually a schema drift after a new migration
   was applied to prod but not to preview. Re-apply with
   `pnpm dlx wrangler d1 migrations apply syrabit-content-preview --remote`.
4. **One-shot replay:** any time after diagnosis, the same manual full
   backfill above (`POST /api/admin/d1-sync`) re-pushes the entire catalog
   to both targets. Safe to re-run; the worker's `replaceTable` is a
   `DELETE FROM <t>` + `INSERT` transaction, so partial writes cannot
   leave the table in an inconsistent state.

## Failure semantics

Preview-target failures are **logged at WARNING and never block the prod
sync**. The fan-out runs preview and prod concurrently
(`asyncio.gather(...)` over secondary targets), so a slow or failing
preview cannot add latency or error pressure to the prod write path.
This is the right tradeoff: preview is a convenience for testers, prod
is the user-visible source of truth.
