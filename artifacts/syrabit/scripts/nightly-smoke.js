#!/usr/bin/env node
/**
 * nightly-smoke.js — Cloudflare zone-settings health check.
 *
 * Asserts that the zone settings applied in Cloudflare Phase 1 (Task #105)
 * still hold their target values.  Run this nightly in CI so any accidental
 * dashboard revert surfaces overnight rather than silently degrading cache
 * hit rates, bot filtering, or email security.
 *
 * Required env:
 *   CLOUDFLARE_API_TOKEN  — must have Zone Settings: Read and DNS: Read scopes
 *   CLOUDFLARE_ZONE_ID    — syrabit.ai zone (5b8c97df4431491dc7f60ea72fb61871)
 *
 * Exit codes:
 *   0  — all assertions passed
 *   1  — one or more assertions failed (details printed to stdout)
 */

const TOKEN   = process.env.CLOUDFLARE_API_TOKEN;
const ZONE_ID = process.env.CLOUDFLARE_ZONE_ID || '5b8c97df4431491dc7f60ea72fb61871';
const API     = 'https://api.cloudflare.com/client/v4';

if (!TOKEN) {
  console.error('CLOUDFLARE_API_TOKEN is not set — aborting smoke run');
  process.exit(1);
}

const headers = {
  'Authorization': `Bearer ${TOKEN}`,
  'Content-Type':  'application/json',
};

async function cfGet(path) {
  const res = await fetch(`${API}${path}`, { headers });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${path}`);
  const j = await res.json();
  if (!j.success) throw new Error(`CF error on ${path}: ${JSON.stringify(j.errors)}`);
  return j;
}

const failures = [];

function assert(label, actual, expected) {
  const pass = JSON.stringify(actual) === JSON.stringify(expected);
  const mark = pass ? '✓' : '✗';
  console.log(`  ${mark}  ${label}: ${JSON.stringify(actual)}${pass ? '' : `  (want: ${JSON.stringify(expected)})`}`);
  if (!pass) failures.push(label);
}

async function main() {
  console.log('Cloudflare nightly smoke — zone settings check');
  console.log(`Zone: ${ZONE_ID}\n`);

  // ── Zone settings ──────────────────────────────────────────────────────
  console.log('Zone settings:');

  const sqsc = await cfGet(`/zones/${ZONE_ID}/settings/sort_query_string_for_cache`);
  assert('sort_query_string_for_cache', sqsc.result.value, 'on');

  const tcip = await cfGet(`/zones/${ZONE_ID}/settings/true_client_ip_header`);
  assert('true_client_ip_header', tcip.result.value, 'on');

  const ech  = await cfGet(`/zones/${ZONE_ID}/settings/ech`);
  assert('ech', ech.result.value, 'on');

  // ── Bot Management ─────────────────────────────────────────────────────
  console.log('\nBot Management:');
  const bm = await cfGet(`/zones/${ZONE_ID}/bot_management`);
  assert('sbfm_likely_automated',   bm.result.sbfm_likely_automated,   'managed_challenge');
  // content_bots_protection: managed_challenge not supported by CF API — block is the enforced value
  assert('content_bots_protection', bm.result.content_bots_protection, 'block');

  // ── DMARC ─────────────────────────────────────────────────────────────
  console.log('\nDMARC:');
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

  // ── Summary ────────────────────────────────────────────────────────────
  console.log('');
  if (failures.length === 0) {
    console.log('All checks passed.');
    process.exit(0);
  } else {
    console.error(`${failures.length} check(s) FAILED:\n  ${failures.join('\n  ')}`);
    console.error('\nRevert detected — check the Cloudflare dashboard and re-apply phase-1 settings.');
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Smoke run error:', err.message);
  process.exit(1);
});
