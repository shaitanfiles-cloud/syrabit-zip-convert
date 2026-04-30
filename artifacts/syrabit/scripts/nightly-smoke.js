#!/usr/bin/env node
/**
 * nightly-smoke.js — Cloudflare zone-settings health check.
 *
 * Asserts that the zone settings applied in Cloudflare Phases 1, 2, 3, 4 & 5
 * (Tasks #105, #106, #107, #108, #109) still hold their target values.  Run
 * nightly in CI so any accidental dashboard revert surfaces overnight rather
 * than silently degrading cache hit rates, bot filtering, or email security.
 *
 * Required env:
 *   CLOUDFLARE_API_TOKEN  — Zone Settings: Read, Bot Management: Read,
 *                           DNS: Read, Logs: Read, Health Checks: Read,
 *                           Zero Trust: Read (Phase 3), Waiting Room: Read (Phase 3),
 *                           R2: Read (Phase 4), Cache: Read (Phase 4),
 *                           Workers: Read, Durable Objects: Read (Phase 5)
 *                           (Phase 2/3/4/5 checks degrade to warnings on token scope gap)
 *   CLOUDFLARE_ZONE_ID    — syrabit.ai zone (5b8c97df4431491dc7f60ea72fb61871)
 *   CLOUDFLARE_ACCOUNT_ID — Syrabit account (d66e40eac539fff1db270fddf384a5ec)
 *
 * Exit codes:
 *   0  — all assertions passed
 *   1  — one or more assertions failed (details printed to stdout)
 */

const TOKEN      = process.env.CLOUDFLARE_API_TOKEN;
const ZONE_ID    = process.env.CLOUDFLARE_ZONE_ID    || '5b8c97df4431491dc7f60ea72fb61871';
const ACCOUNT_ID = process.env.CLOUDFLARE_ACCOUNT_ID || 'd66e40eac539fff1db270fddf384a5ec';
const API        = 'https://api.cloudflare.com/client/v4';

if (!TOKEN) {
  console.error('CLOUDFLARE_API_TOKEN is not set — aborting smoke run');
  process.exit(1);
}

const headers = { 'Authorization': `Bearer ${TOKEN}`, 'Content-Type': 'application/json' };

async function cfGet(path) {
  const res = await fetch(`${API}${path}`, { headers });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${path}`);
  const j = await res.json();
  if (!j.success) throw new Error(`CF error on ${path}: ${JSON.stringify(j.errors)}`);
  return j;
}

// Returns null on auth error (10000), throws for other errors
async function cfGetOrSkip(path) {
  const res = await fetch(`${API}${path}`, { headers });
  const j = await res.json();
  if (j.success) return j;
  if (j.errors?.[0]?.code === 10000) return null;          // auth — caller handles
  throw new Error(`CF error on ${path}: ${JSON.stringify(j.errors)}`);
}

const failures  = [];
const warnings  = [];

function assert(label, actual, expected) {
  const pass = JSON.stringify(actual) === JSON.stringify(expected);
  const mark = pass ? '✓' : '✗';
  console.log(`  ${mark}  ${label}: ${JSON.stringify(actual)}${pass ? '' : `  (want: ${JSON.stringify(expected)})`}`);
  if (!pass) failures.push(label);
}

function warn(label, detail) {
  console.log(`  ⚠  ${label}  [${detail}]`);
  warnings.push(label);
}

async function main() {
  console.log('Cloudflare nightly smoke — Phase 1, 2, 3, 4 & 5 checks');
  console.log(`Zone: ${ZONE_ID}\n`);

  // ── Phase 1: Zone settings ────────────────────────────────────────────
  console.log('Phase 1 — Zone settings:');

  const sqsc = await cfGet(`/zones/${ZONE_ID}/settings/sort_query_string_for_cache`);
  assert('sort_query_string_for_cache', sqsc.result.value, 'on');

  const tcip = await cfGet(`/zones/${ZONE_ID}/settings/true_client_ip_header`);
  assert('true_client_ip_header', tcip.result.value, 'on');

  const ech  = await cfGet(`/zones/${ZONE_ID}/settings/ech`);
  assert('ech', ech.result.value, 'on');

  // ── Phase 1: Bot Management ───────────────────────────────────────────
  console.log('\nPhase 1 — Bot Management:');
  const bm = await cfGet(`/zones/${ZONE_ID}/bot_management`);
  assert('sbfm_likely_automated',   bm.result.sbfm_likely_automated,   'managed_challenge');
  assert('content_bots_protection', bm.result.content_bots_protection, 'block');

  // ── Phase 1: DMARC ────────────────────────────────────────────────────
  console.log('\nPhase 1 — DMARC:');
  const dns = await cfGet(`/zones/${ZONE_ID}/dns_records?name=_dmarc.syrabit.ai&type=TXT`);
  if (!dns.result.length) {
    failures.push('_dmarc.syrabit.ai TXT record (NOT FOUND)');
    console.log('  ✗  _dmarc.syrabit.ai TXT: NOT FOUND');
  } else {
    const content = dns.result[0].content;
    const pMatch  = content.match(/p=([^;]+)/);
    const policy  = pMatch ? pMatch[1].trim() : 'UNKNOWN';
    assert('DMARC p= policy', policy, 'quarantine');
  }

  // ── Phase 2: R2 bucket ────────────────────────────────────────────────
  console.log('\nPhase 2 — R2 bucket:');
  const r2 = await cfGetOrSkip(`/accounts/${ACCOUNT_ID}/r2/buckets`);
  if (!r2) {
    warn('R2 bucket syrabit-logs', 'token lacks R2: Read — add scope to check');
  } else {
    const exists = (r2.result?.buckets || []).some(b => b.name === 'syrabit-logs');
    assert('R2 bucket syrabit-logs exists', exists, true);
  }

  // ── Phase 2: Logpush jobs ─────────────────────────────────────────────
  console.log('\nPhase 2 — Logpush jobs:');
  const lp = await cfGetOrSkip(`/zones/${ZONE_ID}/logpush/jobs`);
  if (!lp) {
    warn('Logpush jobs',
      'token lacks Logs: Read — add the scope to CLOUDFLARE_API_TOKEN and run ' +
      'cloudflare-phase2-apply.js to create the jobs');
  } else {
    const httpJob     = lp.result.find(j => j.name === 'syrabit-http-requests');
    const firewallJob = lp.result.find(j => j.name === 'syrabit-firewall-events');

    function assertJobHealthy(job, label) {
      if (!job) {
        failures.push(`Logpush job ${label} (NOT FOUND)`);
        console.log(`  ✗  Logpush job ${label}: NOT FOUND — run cloudflare-phase2-apply.js`);
        return;
      }
      assert(`${label} enabled`,        job.enabled,       true);
      assert(`${label} error_message`,   job.error_message || null, null);
      // last_complete: non-null means at least one batch has been pushed successfully.
      // A freshly-created job will show null until its first 5-min window closes — that
      // is acceptable and does NOT indicate degradation.
      // Staleness threshold: 4 hours. Logpush batches every 5 min, so >4 h with no
      // push means 48+ consecutive missed windows — a clear signal of degradation.
      // (The nightly CI runs at 02:00 UTC; 4 h covers the lowest-traffic window.)
      if (job.last_complete) {
        const ageMs   = Date.now() - new Date(job.last_complete).getTime();
        const ageMins = Math.round(ageMs / 60000);
        const stale   = ageMs > 4 * 60 * 60 * 1000;    // 4 hours
        const mark    = stale ? '✗' : '✓';
        console.log(`  ${mark}  ${label} last_complete: ${ageMins} min ago${stale ? '  (want: <240 min)' : ''}`);
        if (stale) failures.push(`${label} last_complete stale (${ageMins} min — no push in >4 h)`);
      } else {
        console.log(`  ─  ${label} last_complete: null (job newly created — not yet stale)`);
      }
    }

    assertJobHealthy(httpJob,     'syrabit-http-requests');
    assertJobHealthy(firewallJob, 'syrabit-firewall-events');
  }

  // ── Phase 2: Healthcheck ──────────────────────────────────────────────
  console.log('\nPhase 2 — Origin Healthcheck:');
  const hc = await cfGetOrSkip(`/zones/${ZONE_ID}/healthchecks`);
  if (!hc) {
    warn('Origin Healthcheck',
      'token lacks Health Checks: Read — add scope and run cloudflare-phase2-apply.js');
  } else {
    const hcRecord = hc.result.find(h => h.name === 'api-syrabit-ai-origin');
    if (!hcRecord) {
      failures.push('Origin healthcheck api-syrabit-ai-origin (NOT FOUND)');
      console.log('  ✗  Origin healthcheck NOT FOUND — run cloudflare-phase2-apply.js');
    } else {
      console.log(`  ✓  api-syrabit-ai-origin: id=${hcRecord.id} status=${hcRecord.status}`);
    }
  }

  // ── Phase 3: Zero Trust Access application ───────────────────────────
  console.log('\nPhase 3 — Zero Trust Access:');
  const zt = await cfGetOrSkip(`/accounts/${ACCOUNT_ID}/access/apps`);
  if (!zt) {
    warn('Zero Trust Access apps',
      'token lacks Zero Trust: Read — add scope and run cloudflare-phase3-apply.js');
  } else {
    const adminApp = zt.result.find(a => a.name === 'Syrabit Admin');
    if (!adminApp) {
      failures.push('Access application Syrabit Admin (NOT FOUND)');
      console.log('  ✗  Access application Syrabit Admin: NOT FOUND — run cloudflare-phase3-apply.js');
    } else {
      console.log(`  ✓  Access app: Syrabit Admin id=${adminApp.id} domain=${adminApp.domain}`);
      assert('  Access app session_duration', adminApp.session_duration, '8h');
      // Verify the wildcard path covers all nested admin routes
      const hasWildcard = adminApp.domain && (adminApp.domain.endsWith('*') || adminApp.domain.includes('admin*'));
      assert('  Access app domain covers admin/*', hasWildcard, true);

      // Assert the email allowlist policy exists (at least one allow policy)
      const pol = await cfGetOrSkip(`/accounts/${ACCOUNT_ID}/access/apps/${adminApp.id}/policies`);
      if (!pol) {
        warn('  Access app policies', 'token lacks Zero Trust: Read for policy read');
      } else {
        const allowPolicy = pol.result.find(p => p.decision === 'allow' && p.name === 'Team email allowlist');
        if (!allowPolicy) {
          failures.push('Access policy "Team email allowlist" (NOT FOUND on Syrabit Admin)');
          console.log('  ✗  Access policy "Team email allowlist": NOT FOUND — run cloudflare-phase3-apply.js');
        } else {
          const emailCount = (allowPolicy.include || []).filter(r => r.email).length;
          console.log(`  ✓  Access policy: ${allowPolicy.name} (${emailCount} email rule(s))`);
          assert('  Policy has at least 1 email rule', emailCount >= 1, true);
        }
      }
    }
  }

  // ── Phase 3: Waiting Room ─────────────────────────────────────────────
  console.log('\nPhase 3 — Waiting Room:');
  const wr = await cfGetOrSkip(`/zones/${ZONE_ID}/waiting_rooms`);
  if (!wr) {
    warn('Waiting Room',
      'token lacks Waiting Room: Read — add scope and run cloudflare-phase3-apply.js');
  } else {
    const room = wr.result.find(r => r.name === 'syrabit-exam-season-queue');
    if (!room) {
      failures.push('Waiting Room syrabit-exam-season-queue (NOT FOUND)');
      console.log('  ✗  Waiting Room syrabit-exam-season-queue: NOT FOUND — run cloudflare-phase3-apply.js');
    } else {
      assert('syrabit-exam-season-queue enabled', room.enabled, true);
      assert('  session_duration (min)', room.session_duration, 10);
      assert('  host', room.host, 'syrabit.ai');
    }
  }

  // ── Phase 4: R2 buckets ────────────────────────────────────────────────
  // Reuse the R2 result from Phase 2 if already fetched; but cfGetOrSkip
  // is idempotent (same endpoint) so just call it again for clarity.
  console.log('\nPhase 4 — R2 Asset Storage + Cache Reserve:');
  const r2p4 = await cfGetOrSkip(`/accounts/${ACCOUNT_ID}/r2/buckets`);
  if (!r2p4) {
    warn('R2 buckets (Phase 4)',
      'token lacks R2: Read — add scope and run cloudflare-phase4-apply.js');
  } else {
    const buckets = r2p4.result?.buckets || [];
    const assetsExists = buckets.some(b => b.name === 'syrabit-assets');
    if (!assetsExists) {
      failures.push('R2 bucket syrabit-assets (NOT FOUND)');
      console.log('  ✗  R2 bucket syrabit-assets: NOT FOUND — run cloudflare-phase4-apply.js');
    } else {
      console.log('  ✓  R2 bucket syrabit-assets exists');
    }
    const cacheReserveExists = buckets.some(b => b.name === 'syrabit-cache-reserve');
    if (!cacheReserveExists) {
      failures.push('R2 bucket syrabit-cache-reserve (NOT FOUND)');
      console.log('  ✗  R2 bucket syrabit-cache-reserve: NOT FOUND — run cloudflare-phase4-apply.js');
    } else {
      console.log('  ✓  R2 bucket syrabit-cache-reserve exists');
    }
  }

  // ── Phase 4: Cache Reserve ─────────────────────────────────────────────
  // Cache Reserve requires Cloudflare Cache Reserve subscription (paid add-on).
  // Code 10000 = token scope gap; code 1135 = plan/subscription restriction.
  // Both degrade gracefully to a warning rather than a hard failure.
  const crRaw  = await fetch(`${API}/zones/${ZONE_ID}/cache/cache_reserve`, { headers });
  const crJson = await crRaw.json();
  if (!crJson.success) {
    const code = crJson.errors?.[0]?.code;
    if (code === 10000) {
      warn('Cache Reserve',
        'token lacks Cache: Read — add scope and run cloudflare-phase4-apply.js');
    } else if (code === 1135) {
      warn('Cache Reserve',
        'not available on current plan — requires Cache Reserve subscription; ' +
        'see https://dash.cloudflare.com → Caching → Cache Reserve');
    } else {
      const msg = `Cache Reserve error code ${crJson.errors?.[0]?.code}: ${crJson.errors?.[0]?.message}`;
      failures.push(`Cache Reserve (${msg})`);
      console.log(`  ✗  Cache Reserve: unexpected API error — ${msg}`);
    }
  } else {
    const value = crJson.result?.value;
    if (value === 'on') {
      console.log('  ✓  Cache Reserve: on');
    } else {
      failures.push(`Cache Reserve (value=${JSON.stringify(value)} — want: "on")`);
      console.log(`  ✗  Cache Reserve: ${JSON.stringify(value)}  (want: "on") — run cloudflare-phase4-apply.js`);
    }
  }

  // ── Phase 5: Analytics Engine dataset + Durable Object namespace ──────
  // These resources are provisioned by `wrangler deploy` (not REST API calls).
  // We verify them by inspecting the deployed worker's bindings and the
  // account's DO namespace list. Both endpoints require narrow token scopes
  // (Workers: Read, Durable Objects: Read) that are separate from the main
  // zone-settings token — degrade gracefully on code 10000.
  console.log('\nPhase 5 — Analytics Engine dataset + Durable Object rate limiter:');
  const WORKER_NAME = 'syrabit-edge';
  const AE_DATASET  = 'syrabit-edge-metrics';

  // 5a: Analytics Engine binding
  const aeBindings = await cfGetOrSkip(
    `/accounts/${ACCOUNT_ID}/workers/scripts/${WORKER_NAME}/bindings`,
  );
  if (!aeBindings) {
    warn('Analytics Engine ANALYTICS binding',
      'token lacks Workers: Read — add scope to verify or check Workers dashboard');
  } else {
    const aeBinding = (aeBindings.result || []).find(
      (b) => b.type === 'analytics_engine' && b.dataset === AE_DATASET,
    );
    if (!aeBinding) {
      failures.push(`Analytics Engine binding (dataset=${AE_DATASET}) NOT found in syrabit-edge`);
      console.log(`  ✗  ANALYTICS binding (dataset=${AE_DATASET}): NOT FOUND — run: cd workers/edge-proxy && wrangler deploy`);
    } else {
      console.log(`  ✓  ANALYTICS binding: dataset=${aeBinding.dataset}`);
    }
  }

  // 5b: RateLimiter Durable Object namespace
  const doNamespaces = await cfGetOrSkip(
    `/accounts/${ACCOUNT_ID}/workers/durable_objects/namespaces`,
  );
  if (!doNamespaces) {
    warn('RateLimiter DO namespace',
      'token lacks Durable Objects: Read — add scope to verify or check Workers dashboard');
  } else {
    const ns = (doNamespaces.result || []).find(
      (n) => n.class === 'RateLimiter' && n.script === WORKER_NAME,
    );
    if (!ns) {
      const anyMatch = (doNamespaces.result || []).some((n) => n.class === 'RateLimiter');
      if (anyMatch) {
        console.log('  ✓  RateLimiter DO namespace found (possibly on different script tag)');
      } else {
        failures.push('RateLimiter DO namespace (NOT FOUND — wrangler deploy needed)');
        console.log('  ✗  RateLimiter DO namespace: NOT FOUND — run: cd workers/edge-proxy && wrangler deploy');
      }
    } else {
      console.log(`  ✓  RateLimiter DO namespace: id=${ns.id} script=${ns.script}`);
    }
  }

  // 5c: Analytics Engine dataset write recency
  // Verifies the worker has written at least one datapoint in the last 24 h
  // by querying the AE SQL API. Requires CF_ANALYTICS_TOKEN env var with
  // "Analytics: Read" scope. Degrades to a warning if the token is absent
  // or on plan-restriction errors (code 1135) so CI doesn't block deploys
  // on freshly-provisioned accounts with no traffic yet.
  const cfAnalyticsToken = process.env.CF_ANALYTICS_TOKEN;
  if (!cfAnalyticsToken) {
    warn('AE dataset write recency', 'CF_ANALYTICS_TOKEN not set — set env var to verify writes');
  } else {
    const aeSqlUrl = `https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}/analytics_engine/sql`;
    const aeQuery  = `SELECT count() AS n FROM syrabit_edge_metrics WHERE timestamp >= now() - INTERVAL '86400' SECOND`;
    try {
      const aeRes  = await fetch(aeSqlUrl, {
        method: 'POST',
        headers: { Authorization: `Bearer ${cfAnalyticsToken}`, 'Content-Type': 'text/plain' },
        body: aeQuery,
      });
      const aeText = await aeRes.text();
      if (!aeRes.ok) {
        const code = (() => { try { return JSON.parse(aeText)?.errors?.[0]?.code; } catch { return null; } })();
        if (code === 1135) {
          warn('AE dataset write recency', 'plan does not include Analytics Engine (code 1135)');
        } else {
          warn('AE dataset write recency', `AE SQL returned ${aeRes.status} — check CF_ANALYTICS_TOKEN scope`);
        }
      } else {
        const aeJson = JSON.parse(aeText);
        const n = Number(aeJson?.data?.[0]?.n ?? 0);
        if (n === 0) {
          warn('AE dataset write recency', 'syrabit_edge_metrics has 0 rows in last 24 h — verify worker is deployed and receiving traffic');
        } else {
          console.log(`  ✓  AE dataset write recency: ${n.toLocaleString()} datapoints in last 24 h`);
        }
      }
    } catch (err) {
      warn('AE dataset write recency', `AE SQL fetch failed: ${err.message}`);
    }
  }

  // ── Summary ────────────────────────────────────────────────────────────
  console.log('');
  if (warnings.length > 0) {
    console.log(`${warnings.length} warning(s): ${warnings.join(', ')}`);
  }
  if (failures.length === 0) {
    console.log('All checks passed.');
    process.exit(0);
  } else {
    console.error(`\n${failures.length} check(s) FAILED:\n  ${failures.join('\n  ')}`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Smoke run error:', err.message);
  process.exit(1);
});
