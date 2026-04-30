#!/usr/bin/env node
/**
 * nightly-smoke.js — Cloudflare zone-settings health check.
 *
 * Asserts that the zone settings applied in Cloudflare Phases 1, 2 & 3
 * (Tasks #105, #106, #107) still hold their target values.  Run nightly in CI
 * so any accidental dashboard revert surfaces overnight rather than
 * silently degrading cache hit rates, bot filtering, or email security.
 *
 * Required env:
 *   CLOUDFLARE_API_TOKEN  — Zone Settings: Read, Bot Management: Read,
 *                           DNS: Read, Logs: Read, Health Checks: Read,
 *                           Zero Trust: Read (Phase 3), Waiting Room: Read (Phase 3)
 *                           (Phase 2/3 checks degrade to warnings on token scope gap)
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
  console.log('Cloudflare nightly smoke — Phase 1, 2 & 3 checks');
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
