#!/usr/bin/env node
/**
 * cloudflare-annual-review.js
 *
 * Read-only audit of syrabit.ai Cloudflare zone configuration.
 * Run before each annual review to surface gaps against the target state
 * established in Phase 1 (Task #105) and updated by later phases.
 *
 * Required env:
 *   CLOUDFLARE_API_TOKEN   — Zone Settings: Read, DNS: Read, Bot Management: Read
 *   CLOUDFLARE_ZONE_ID     — optional, defaults to syrabit.ai zone
 *   CLOUDFLARE_ACCOUNT_ID  — optional, defaults to Syrabit account
 *
 * Usage:
 *   node artifacts/syrabit/scripts/cloudflare-annual-review.js
 *   CLOUDFLARE_API_TOKEN=<tok> node artifacts/syrabit/scripts/cloudflare-annual-review.js
 */

const TOKEN      = process.env.CLOUDFLARE_API_TOKEN;
const ZONE_ID    = process.env.CLOUDFLARE_ZONE_ID    || '5b8c97df4431491dc7f60ea72fb61871';
const ACCOUNT_ID = process.env.CLOUDFLARE_ACCOUNT_ID || 'd66e40eac539fff1db270fddf384a5ec';
const API        = 'https://api.cloudflare.com/client/v4';

if (!TOKEN) {
  console.error('CLOUDFLARE_API_TOKEN is not set');
  process.exit(1);
}

const headers = { 'Authorization': `Bearer ${TOKEN}`, 'Content-Type': 'application/json' };

async function cfGet(path) {
  const res = await fetch(`${API}${path}`, { headers });
  const j   = await res.json();
  return j;
}

function row(label, value, target, note = '') {
  const ok   = target !== undefined ? JSON.stringify(value) === JSON.stringify(target) : null;
  const mark = ok === null ? '  ' : ok ? '✓ ' : '✗ ';
  const exp  = target !== undefined && !ok ? `  (want: ${JSON.stringify(target)})` : '';
  const n    = note ? `  [${note}]` : '';
  console.log(`  ${mark}${label.padEnd(40)} ${JSON.stringify(value)}${exp}${n}`);
}

async function main() {
  console.log('════════════════════════════════════════');
  console.log(' Cloudflare Annual Review — syrabit.ai');
  console.log(`════════════════════════════════════════\n`);
  console.log(`Zone:    ${ZONE_ID}`);
  console.log(`Account: ${ACCOUNT_ID}\n`);

  // ── Phase 1: Zone settings ────────────────────────────────────────────
  console.log('── Phase 1: Zone Settings ──');
  const settingTargets = {
    sort_query_string_for_cache: 'on',
    true_client_ip_header:       'on',
    ech:                         'on',
    // minify: CF Enterprise API accepts PATCH but does not apply — use dashboard
    minify:                      { css: 'on', html: 'on', js: 'on' },
    http3:                       'on',
    brotli:                      'on',
    http2:                       'on',
    always_use_https:            'on',
    min_tls_version:             '1.2',
    // tls_1_3: "zrt" = TLS 1.3 + 0-RTT (correct; "on" is the legacy label)
    tls_1_3:                     'zrt',
    automatic_https_rewrites:    'on',
    // ssl: "strict" is better than "full" — validates origin cert
    ssl:                         'strict',
    // hsts: not a standalone zone settings endpoint — inspect via SSL tab
    security_level:              null,   // inspect only
  };

  for (const [setting, target] of Object.entries(settingTargets)) {
    const j = await cfGet(`/zones/${ZONE_ID}/settings/${setting}`);
    if (!j.success) {
      console.log(`  ?  ${setting.padEnd(40)} error: ${JSON.stringify(j.errors)}`);
    } else {
      const note = setting === 'minify' ? 'Enterprise API non-functional; use dashboard' : '';
      row(setting, j.result.value, target || undefined, note);
    }
  }

  // ── Phase 1: Bot Management ───────────────────────────────────────────
  console.log('\n── Phase 1: Bot Management ──');
  const bm = await cfGet(`/zones/${ZONE_ID}/bot_management`);
  if (bm.success) {
    row('sbfm_likely_automated',        bm.result.sbfm_likely_automated,        'managed_challenge');
    row('sbfm_definitely_automated',    bm.result.sbfm_definitely_automated,    'managed_challenge');
    row('sbfm_verified_bots',           bm.result.sbfm_verified_bots,           'allow');
    row('content_bots_protection',      bm.result.content_bots_protection,      'block');
    row('ai_bots_protection',           bm.result.ai_bots_protection,           'block');
    row('crawler_protection',           bm.result.crawler_protection,           'enabled');
    row('enable_js',                    bm.result.enable_js,                    true);
    row('using_latest_model',           bm.result.using_latest_model,           true);
    // sbfm_static_resource_protection: false = only check page requests (not static assets)
    row('sbfm_static_resource_protection', bm.result.sbfm_static_resource_protection, false);
    if (bm.result.stale_zone_configuration?.fight_mode) {
      console.log(`  ✗  stale_zone_configuration.fight_mode     true  (needs CF support ticket to clear)`);
    }
  } else {
    console.log('  ?  Bot Management read error:', JSON.stringify(bm.errors));
  }

  // ── Phase 1: DMARC ────────────────────────────────────────────────────
  console.log('\n── Phase 1: DNS & Email Security ──');
  const dmarc = await cfGet(`/zones/${ZONE_ID}/dns_records?name=_dmarc.syrabit.ai&type=TXT`);
  if (dmarc.success && dmarc.result.length) {
    const content = dmarc.result[0].content;
    const policy  = (content.match(/p=([^;]+)/) || ['', 'MISSING'])[1].trim();
    row('DMARC p= policy (_dmarc.syrabit.ai)', policy, 'quarantine');
    console.log(`    full record: ${content}`);
  } else {
    console.log('  ✗  _dmarc.syrabit.ai TXT record: NOT FOUND');
  }

  // ── Phase 2+ placeholders ─────────────────────────────────────────────
  console.log('\n── Phase 2: Logpush & Healthchecks (todo) ──');
  const lp = await cfGet(`/zones/${ZONE_ID}/logpush/jobs`);
  const lc = lp.success ? lp.result.length : '?';
  row('logpush jobs', lc, null, lc === 0 ? 'Phase 2 not yet applied' : '');

  const hc = await cfGet(`/zones/${ZONE_ID}/healthchecks`);
  const hcount = hc.success ? hc.result.length : '?';
  row('healthchecks', hcount, null, hcount === 0 ? 'Phase 2 not yet applied' : '');

  console.log('\n── Phase 3: Waiting Rooms (todo) ──');
  const wr = await cfGet(`/zones/${ZONE_ID}/waiting_rooms`);
  row('waiting_rooms', wr.success ? wr.result.length : '?', null);

  console.log('\n────────────────────────────────────────');
  console.log('Review complete.');
}

main().catch((err) => {
  console.error('Review error:', err.message);
  process.exit(1);
});
