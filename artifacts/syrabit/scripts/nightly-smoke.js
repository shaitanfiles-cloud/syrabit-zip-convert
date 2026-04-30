#!/usr/bin/env node
/**
 * nightly-smoke.js — Cloudflare zone-settings health check.
 *
 * Asserts that the zone settings applied in Cloudflare Phases 1 & 2
 * (Tasks #105 and #106) still hold their target values.  Run nightly in CI
 * so any accidental dashboard revert surfaces overnight rather than
 * silently degrading cache hit rates, bot filtering, or email security.
 *
 * Required env:
 *   CLOUDFLARE_API_TOKEN  — Zone Settings: Read, Bot Management: Read,
 *                           DNS: Read, Logs: Read, Health Checks: Read
 *                           (Phase 2 checks are skipped with a warning if
 *                           the token lacks Logs: Read or Health Checks: Read)
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
  console.log('Cloudflare nightly smoke — Phase 1 & 2 checks');
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
    const httpJob  = lp.result.find(j => j.name === 'syrabit-http-requests');
    const firewallJob = lp.result.find(j => j.name === 'syrabit-firewall-events');

    if (!httpJob) {
      failures.push('Logpush job syrabit-http-requests (NOT FOUND)');
      console.log('  ✗  Logpush job syrabit-http-requests: NOT FOUND — run cloudflare-phase2-apply.js');
    } else {
      assert('syrabit-http-requests enabled', httpJob.enabled, true);
    }

    if (!firewallJob) {
      failures.push('Logpush job syrabit-firewall-events (NOT FOUND)');
      console.log('  ✗  Logpush job syrabit-firewall-events: NOT FOUND — run cloudflare-phase2-apply.js');
    } else {
      assert('syrabit-firewall-events enabled', firewallJob.enabled, true);
    }
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
