#!/usr/bin/env node
/**
 * cloudflare-annual-review.js
 *
 * Read-only audit of syrabit.ai Cloudflare zone configuration.
 * Run before each annual review to surface gaps against the target state
 * established in Phase 1 (Task #105) and updated by later phases.
 *
 * Required env:
 *   CLOUDFLARE_API_TOKEN   — Zone Settings: Read, DNS: Read, Bot Management: Read,
 *                            Logs: Read (Phase 2 Logpush), Health Checks: Read,
 *                            R2: Read (Phase 2 bucket), Zero Trust: Read (Phase 3),
 *                            Waiting Room: Read (Phase 3)
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

  // ── Phase 2: R2 Logs Bucket ──────────────────────────────────────────
  console.log('\n── Phase 2: R2 Logs Bucket (Task #106) ──');
  const r2 = await cfGet(`/accounts/${ACCOUNT_ID}/r2/buckets`);
  if (!r2.success) {
    const authErr = r2.errors?.[0]?.code === 10000;
    console.log(`  ?  R2 bucket syrabit-logs${authErr ? '  [token lacks R2: Read]' : ': ' + JSON.stringify(r2.errors)}`);
  } else {
    const exists = (r2.result?.buckets || []).some(b => b.name === 'syrabit-logs');
    row('R2 bucket syrabit-logs exists', exists, true,
      exists ? 'Logpush destination' : 'run cloudflare-phase2-apply.js');
  }

  // ── Phase 2: Logpush jobs ─────────────────────────────────────────────
  console.log('\n── Phase 2: Logpush Jobs (Task #106) ──');
  console.log('  Target: 2 jobs (syrabit-http-requests, syrabit-firewall-events) → R2, enabled');
  const lp = await cfGet(`/zones/${ZONE_ID}/logpush/jobs`);
  if (!lp.success) {
    const authErr = lp.errors?.[0]?.code === 10000;
    console.log(`  ?  Logpush jobs${authErr
      ? '  [token lacks Logs: Read — add scope at dash.cloudflare.com/profile/api-tokens]'
      : ': ' + JSON.stringify(lp.errors)}`);
  } else {
    const httpJob  = lp.result.find(j => j.name === 'syrabit-http-requests');
    const fwJob    = lp.result.find(j => j.name === 'syrabit-firewall-events');
    if (httpJob) {
      row('syrabit-http-requests enabled', httpJob.enabled, true,
        `id=${httpJob.id} dataset=${httpJob.dataset}`);
    } else {
      row('syrabit-http-requests', 'NOT FOUND', 'EXISTS', 'run cloudflare-phase2-apply.js');
    }
    if (fwJob) {
      row('syrabit-firewall-events enabled', fwJob.enabled, true,
        `id=${fwJob.id} dataset=${fwJob.dataset}`);
    } else {
      row('syrabit-firewall-events', 'NOT FOUND', 'EXISTS', 'run cloudflare-phase2-apply.js');
    }
    if (lp.result.length > 2) {
      console.log(`  ℹ  ${lp.result.length - 2} additional job(s): ${lp.result.filter(j=>j.name!=='syrabit-http-requests'&&j.name!=='syrabit-firewall-events').map(j=>j.name).join(', ')}`);
    }
  }

  // ── Phase 2: Origin Healthcheck ───────────────────────────────────────
  console.log('\n── Phase 2: Origin Healthcheck (Task #106) ──');
  console.log('  Target: api-syrabit-ai-origin polls https://api.syrabit.ai/health every 60 s');
  const hc = await cfGet(`/zones/${ZONE_ID}/healthchecks`);
  if (!hc.success) {
    const authErr = hc.errors?.[0]?.code === 10000;
    console.log(`  ?  Healthcheck${authErr
      ? '  [token lacks Health Checks: Read — add scope at dash.cloudflare.com/profile/api-tokens]'
      : ': ' + JSON.stringify(hc.errors)}`);
  } else {
    const hcRecord = hc.result.find(h => h.name === 'api-syrabit-ai-origin');
    if (hcRecord) {
      row('api-syrabit-ai-origin exists', true, true,
        `id=${hcRecord.id} interval=${hcRecord.interval}s status=${hcRecord.status}`);
      row('  type', hcRecord.type, 'HTTPS');
      row('  path', hcRecord.path, '/health');
      row('  interval', hcRecord.interval, 60);
    } else {
      row('api-syrabit-ai-origin', 'NOT FOUND', 'EXISTS', 'run cloudflare-phase2-apply.js');
    }
  }

  // ── Phase 3: Zero Trust Access ────────────────────────────────────────
  console.log('\n── Phase 3: Zero Trust Access (Task #107) ──');
  console.log('  Target: Syrabit Admin app covers api.syrabit.ai/admin* (wildcard), session=8h');
  const zt = await cfGet(`/accounts/${ACCOUNT_ID}/access/apps`);
  if (!zt.success) {
    const authErr = zt.errors?.[0]?.code === 10000;
    console.log(`  ?  Access apps${authErr
      ? '  [token lacks Zero Trust: Read — add scope at dash.cloudflare.com/profile/api-tokens]'
      : ': ' + JSON.stringify(zt.errors)}`);
  } else {
    const adminApp = zt.result.find(a => a.name === 'Syrabit Admin');
    if (adminApp) {
      const hasWildcard = adminApp.domain && adminApp.domain.includes('admin*');
      row('Syrabit Admin app exists', true, true,
        `id=${adminApp.id} domain=${adminApp.domain}`);
      row('  domain covers admin/* (wildcard)', hasWildcard, true,
        hasWildcard ? '' : 'SECURITY: update domain to api.syrabit.ai/admin* to cover nested routes');
      row('  session_duration', adminApp.session_duration, '8h');
      // Check policy count
      const pol = await cfGet(`/accounts/${ACCOUNT_ID}/access/apps/${adminApp.id}/policies`);
      if (pol.success) {
        row('  policies', pol.result.length >= 1, true,
          `${pol.result.length} policy(ies): ${pol.result.map(p=>p.name).join(', ')}`);
      } else {
        console.log('  ?  Policy read error:', JSON.stringify(pol.errors));
      }
    } else {
      row('Syrabit Admin app', 'NOT FOUND', 'EXISTS', 'run cloudflare-phase3-apply.js');
    }
  }

  // ── Phase 3: Waiting Room ─────────────────────────────────────────────
  console.log('\n── Phase 3: Waiting Room (Task #107) ──');
  console.log('  Target: syrabit-exam-season-queue on syrabit.ai/*, 10-min session, enabled');
  const wr = await cfGet(`/zones/${ZONE_ID}/waiting_rooms`);
  if (!wr.success) {
    const authErr = wr.errors?.[0]?.code === 10000;
    console.log(`  ?  Waiting rooms${authErr
      ? '  [token lacks Waiting Room: Read — add scope at dash.cloudflare.com/profile/api-tokens]'
      : ': ' + JSON.stringify(wr.errors)}`);
  } else {
    const room = wr.result.find(r => r.name === 'syrabit-exam-season-queue');
    if (room) {
      row('syrabit-exam-season-queue exists', true, true,
        `id=${room.id} host=${room.host}`);
      row('  enabled', room.enabled, true);
      row('  session_duration', room.session_duration, 10);
      row('  new_users_per_minute', room.new_users_per_minute, undefined,
        'Railway plan capacity — increase on Pro plan');
      row('  total_active_users', room.total_active_users, undefined);
    } else {
      row('syrabit-exam-season-queue', 'NOT FOUND', 'EXISTS', 'run cloudflare-phase3-apply.js');
    }
  }

  console.log('\n────────────────────────────────────────');
  console.log('Review complete.');
}

main().catch((err) => {
  console.error('Review error:', err.message);
  process.exit(1);
});
