#!/usr/bin/env node
/**
 * cloudflare-phase6-apply.js
 *
 * Task #110 — Cloudflare Phase 6: mTLS origin hardening, Zaraz analytics,
 * Cloudflare Images, and Observatory.
 *
 * Steps performed:
 *   1. Issue a Cloudflare mTLS client certificate for api.syrabit.ai.
 *   2. Enable Cloudflare Image Resizing on the zone.
 *   3. Configure Zaraz with a GA4 tool (page-view + click events).
 *   4. Schedule weekly Observatory Lighthouse runs for homepage + chapter page.
 *   5. Print post-apply instructions (wrangler secret, wrangler.toml update).
 *
 * Required env:
 *   CLOUDFLARE_API_TOKEN  — must have:
 *       SSL and Certificates: Edit  (mTLS cert issuance)
 *       Zone Settings: Edit         (Image Resizing enable)
 *       Zaraz: Edit                 (GA4 tool configuration)
 *       Speed (Observatory): Edit   (Lighthouse scheduling)
 *   CLOUDFLARE_ZONE_ID    — optional, defaults to syrabit.ai zone
 *   CLOUDFLARE_ACCOUNT_ID — optional, defaults to Syrabit account
 *   GA4_MEASUREMENT_ID    — GA4 Measurement ID (format G-XXXXXXXXXX)
 *
 * Usage:
 *   CLOUDFLARE_API_TOKEN=<tok> GA4_MEASUREMENT_ID=G-XXXXXXX \
 *     node artifacts/syrabit/scripts/cloudflare-phase6-apply.js
 *
 *   Dry-run (skip mutating calls, validate config only):
 *   DRY_RUN=1 CLOUDFLARE_API_TOKEN=<tok> \
 *     node artifacts/syrabit/scripts/cloudflare-phase6-apply.js
 */

const TOKEN      = process.env.CLOUDFLARE_API_TOKEN;
const ZONE_ID    = process.env.CLOUDFLARE_ZONE_ID    || '5b8c97df4431491dc7f60ea72fb61871';
const ACCOUNT_ID = process.env.CLOUDFLARE_ACCOUNT_ID || 'd66e40eac539fff1db270fddf384a5ec';
const GA4_ID     = process.env.GA4_MEASUREMENT_ID    || '';
const DRY_RUN    = process.env.DRY_RUN === '1';
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

async function cfPost(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  const j = await res.json();
  return j;
}

async function cfPut(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(body),
  });
  const j = await res.json();
  return j;
}

async function cfPatch(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify(body),
  });
  const j = await res.json();
  return j;
}

function ok(label)  { console.log(`  ✓  ${label}`); }
function err(label) { console.log(`  ✗  ${label}`); }
function info(msg)  { console.log(`  ℹ  ${msg}`); }
function dry(label) { console.log(`  ─  [DRY-RUN] would: ${label}`); }

// ────────────────────────────────────────────────────────────────────────────
// Step 1: Issue mTLS client certificate
// ────────────────────────────────────────────────────────────────────────────
async function stepMtlsCert() {
  console.log('\n── Step 1: Issue mTLS client certificate ──');
  console.log('  Target: Cloudflare-issued client certificate for api.syrabit.ai');

  // Check if a certificate named "syrabit-railway-mtls" already exists.
  const existing = await cfGet(`/accounts/${ACCOUNT_ID}/mtls_certificates`);
  if (existing.success) {
    const found = (existing.result || []).find(c => c.name === 'syrabit-railway-mtls');
    if (found) {
      ok(`mTLS certificate already exists: id=${found.id} expires=${found.expires_on}`);
      info(`Fill this certificate_id into workers/edge-proxy/wrangler.toml [[mtls_certificates]].`);
      return found.id;
    }
  }

  if (DRY_RUN) {
    dry('POST /accounts/{id}/mtls_certificates — issue syrabit-railway-mtls');
    info('After dry-run: fill the returned certificate_id into wrangler.toml and run wrangler deploy.');
    return null;
  }

  // Issue the certificate — Cloudflare generates the keypair server-side.
  // The private key is returned ONCE in the response; store it immediately.
  const body = {
    name:             'syrabit-railway-mtls',
    certificates:     '',          // empty = Cloudflare-generated keypair
    validity_period:  3650,        // 10 years
    associated_hostnames: ['api.syrabit.ai'],
  };

  const r = await cfPost(`/accounts/${ACCOUNT_ID}/mtls_certificates`, body);
  if (!r.success) {
    err(`mTLS certificate issuance failed: ${JSON.stringify(r.errors)}`);
    console.log('');
    console.log('  Possible causes:');
    console.log('  • API token lacks "SSL and Certificates: Edit" scope.');
    console.log('  • Account is not on a plan that supports client certificates.');
    console.log('  • Use dash.cloudflare.com → SSL/TLS → Client Certificates → Create.');
    return null;
  }

  const cert = r.result;
  ok(`mTLS certificate issued: id=${cert.id} expires=${cert.expires_on}`);
  console.log('');
  console.log('  ══════════════════════════════════════════════════════════════');
  console.log('  SAVE THE PRIVATE KEY — it is shown only once:');
  console.log('  ══════════════════════════════════════════════════════════════');
  console.log(cert.private_key || '  (private_key not returned — use dashboard)');
  console.log('  ══════════════════════════════════════════════════════════════');
  console.log('');
  info(`Certificate ID: ${cert.id}`);
  info('Next steps:');
  info('  1. Copy the private key above and run:');
  info('       echo "<pem>" | wrangler secret put MTLS_PRIVATE_KEY --name syrabit-edge');
  info(`  2. Set certificate_id = "${cert.id}" in workers/edge-proxy/wrangler.toml [[mtls_certificates]].`);
  info('  3. Run: cd workers/edge-proxy && wrangler deploy');
  info('  4. Configure Railway to require mTLS (see docs/CLOUDFLARE_MTLS.md).');

  return cert.id;
}

// ────────────────────────────────────────────────────────────────────────────
// Step 2: Enable Cloudflare Image Resizing on the zone
// ────────────────────────────────────────────────────────────────────────────
async function stepImageResizing() {
  console.log('\n── Step 2: Enable Cloudflare Image Resizing ──');
  console.log('  Target: zone setting image_resizing = "on"');

  const current = await cfGet(`/zones/${ZONE_ID}/settings/image_resizing`);
  if (current.success && current.result?.value === 'on') {
    ok('image_resizing is already on');
    return;
  }

  if (DRY_RUN) {
    dry('PATCH /zones/{id}/settings/image_resizing — set value: "on"');
    return;
  }

  const r = await cfPatch(`/zones/${ZONE_ID}/settings/image_resizing`, { value: 'on' });
  if (r.success) {
    ok('image_resizing enabled (value: "on")');
    info('The frontend imageCdn.js helper already routes thumbnails through');
    info('/cdn-cgi/image/{opts}/{src}; this setting enables the transformer.');
  } else {
    const code = r.errors?.[0]?.code;
    if (code === 1135) {
      err('image_resizing: not available on current plan');
      info('Requires "Image Resizing" add-on: dash.cloudflare.com → Speed → Optimization.');
    } else {
      err(`image_resizing failed: ${JSON.stringify(r.errors)}`);
    }
  }
}

// ────────────────────────────────────────────────────────────────────────────
// Step 3: Configure Zaraz with GA4 tool
// ────────────────────────────────────────────────────────────────────────────
async function stepZaraz() {
  console.log('\n── Step 3: Configure Zaraz with GA4 ──');

  if (!GA4_ID || !/^G-[A-Z0-9]{6,12}$/.test(GA4_ID)) {
    err(`GA4_MEASUREMENT_ID not set or invalid (got: "${GA4_ID}")`);
    info('Set GA4_MEASUREMENT_ID=G-XXXXXXXXXX and re-run this script.');
    info('The Measurement ID is at analytics.google.com → Admin → Data Streams.');
    return;
  }

  console.log(`  GA4 Measurement ID: ${GA4_ID}`);

  // Read current Zaraz config
  const current = await cfGet(`/zones/${ZONE_ID}/zaraz/config`);
  if (!current.success) {
    const code = current.errors?.[0]?.code;
    if (code === 10000) {
      err('Zaraz: token lacks Zaraz: Edit scope — add it to the API token and re-run.');
    } else {
      err(`Zaraz config read failed: ${JSON.stringify(current.errors)}`);
    }
    info('Alternative: configure GA4 in Zaraz via dash.cloudflare.com → Zaraz → Tools → Add tool → Google Analytics.');
    return;
  }

  // Check if a GA4 tool is already configured
  const tools = current.result?.tools || {};
  const ga4Tool = Object.values(tools).find(
    t => t.type === 'GA4' || (t.name && t.name.toLowerCase().includes('ga4')),
  );

  if (ga4Tool) {
    ok(`Zaraz GA4 tool already configured: "${ga4Tool.name}"`);
    return;
  }

  if (DRY_RUN) {
    dry(`PUT /zones/{id}/zaraz/config — add GA4 tool (measurementId=${GA4_ID})`);
    return;
  }

  // Build the updated Zaraz config with a GA4 tool.
  // Zaraz config is a full-document PUT — we merge our tool into the existing config.
  const toolId   = `ga4-${Date.now()}`;
  const newTool  = {
    name:    'Google Analytics 4',
    type:    'GA4',
    enabled: true,
    settings: {
      measurementId: GA4_ID,
    },
    // Standard triggers: page view on every navigation, click on interactive elements.
    rules: [
      {
        match:  { type: 'pageview' },
        action: { type: 'pageview' },
      },
      {
        match:  { type: 'click', selector: 'a, button' },
        action: { type: 'event', value: 'click' },
      },
    ],
    // Zaraz server-side mode — GA4 events are sent from Cloudflare edge, not
    // student devices. No GA4 JavaScript loads on the client.
    permissions: ['server'],
  };

  const updatedConfig = {
    ...current.result,
    tools: { ...tools, [toolId]: newTool },
  };

  const r = await cfPut(`/zones/${ZONE_ID}/zaraz/config`, updatedConfig);
  if (r.success) {
    ok(`Zaraz GA4 tool added: toolId=${toolId} measurementId=${GA4_ID}`);
    info('GA4 events now fire server-side from the Cloudflare edge — no gtag.js on student devices.');
    info('The existing window.gtag() calls in usePageTracking.js are forwarded via the Zaraz compatibility layer.');
  } else {
    err(`Zaraz config update failed: ${JSON.stringify(r.errors)}`);
    info('Fallback: add the GA4 tool manually at dash.cloudflare.com → Zaraz → Tools → Add → Google Analytics.');
  }
}

// ────────────────────────────────────────────────────────────────────────────
// Step 4: Schedule Observatory (Lighthouse) runs
// ────────────────────────────────────────────────────────────────────────────
async function stepObservatory() {
  console.log('\n── Step 4: Schedule Observatory Lighthouse runs ──');
  console.log('  Target: weekly Lighthouse for homepage + a chapter page, region us-central1');

  const targets = [
    { label: 'homepage',     url: 'https://syrabit.ai/' },
    { label: 'chapter page', url: 'https://syrabit.ai/ahsec/class-12/physics' },
  ];

  for (const target of targets) {
    // Check if a schedule already exists for this URL
    const existing = await cfGet(`/zones/${ZONE_ID}/speed/schedule?url=${encodeURIComponent(target.url)}`);
    if (existing.success && existing.result?.schedule) {
      ok(`Observatory schedule already exists for ${target.label}: frequency=${existing.result.schedule.frequency}`);
      continue;
    }

    if (DRY_RUN) {
      dry(`POST /zones/{id}/speed/schedule — ${target.label} (${target.url}), weekly`);
      continue;
    }

    const r = await cfPost(`/zones/${ZONE_ID}/speed/schedule`, {
      url:                target.url,
      region:             'us-central1',
      schedule_frequency: 'weekly',
    });

    if (r.success) {
      ok(`Observatory scheduled: ${target.label} — weekly from us-central1`);
    } else {
      const code = r.errors?.[0]?.code;
      if (code === 1135) {
        err(`Observatory: not available on current plan for ${target.label}`);
        info('Requires Workers Paid or Enterprise plan with Observatory access.');
      } else {
        err(`Observatory schedule failed for ${target.label}: ${JSON.stringify(r.errors)}`);
      }
    }
  }

  info('Alert thresholds (LCP>2.5 s, CLS>0.1, INP>200 ms) must be set via the Cloudflare');
  info('dashboard: Speed → Observatory → Scheduled reports → Alert settings.');
  info('Cloudflare does not currently expose alert thresholds via the REST API.');
}

// ────────────────────────────────────────────────────────────────────────────
// Step 5: Post-apply summary
// ────────────────────────────────────────────────────────────────────────────
function printSummary(certId) {
  console.log('\n── Phase 6 Post-Apply Checklist ──');
  console.log('');
  if (certId) {
    console.log('  mTLS certificate provisioned. Complete the setup:');
    console.log(`  ① Store the private key:     echo "<pem>" | wrangler secret put MTLS_PRIVATE_KEY --name syrabit-edge`);
    console.log(`  ② Update wrangler.toml:      set certificate_id = "${certId}" in [[mtls_certificates]]`);
    console.log('  ③ Deploy the worker:         cd workers/edge-proxy && wrangler deploy');
    console.log('  ④ Configure Railway mTLS:    add the certificate to the Railway service (see docs/CLOUDFLARE_MTLS.md)');
    console.log('');
  } else {
    console.log('  mTLS certificate was not issued (already exists, dry-run, or error above).');
    console.log('  If not yet done, issue it manually at dash.cloudflare.com → SSL/TLS → Client Certificates.');
    console.log('');
  }
  console.log('  Zaraz + GA4:');
  console.log('  • Verify GA4 events at dash.cloudflare.com → Zaraz → Tools');
  console.log('  • Check realtime GA4 reports at analytics.google.com');
  console.log('  • Ensure VITE_GA4_ID is NOT set in the production build env');
  console.log('    (client-side gtag.js is disabled — Zaraz handles all tracking)');
  console.log('');
  console.log('  Observatory:');
  console.log('  • Set Core Web Vitals alert thresholds at dash.cloudflare.com → Speed → Observatory');
  console.log('    (LCP > 2.5 s, CLS > 0.1, INP > 200 ms → alert admin@syrabit.ai)');
  console.log('');
  console.log('  Nightly smoke:');
  console.log('  • Phase 6 assertions are added to nightly-smoke.js and will run in the next CI cycle.');
  console.log('  • Run manually: CLOUDFLARE_API_TOKEN=<tok> node artifacts/syrabit/scripts/nightly-smoke.js');
}

// ────────────────────────────────────────────────────────────────────────────
// Main
// ────────────────────────────────────────────────────────────────────────────
async function main() {
  console.log('════════════════════════════════════════════════════════════════');
  console.log(' Cloudflare Phase 6 Apply — syrabit.ai');
  if (DRY_RUN) console.log(' *** DRY-RUN MODE — no mutating API calls will be made ***');
  console.log('════════════════════════════════════════════════════════════════');
  console.log(`Zone:    ${ZONE_ID}`);
  console.log(`Account: ${ACCOUNT_ID}`);
  console.log(`GA4 ID:  ${GA4_ID || '(not set — Zaraz step will be skipped)'}`);
  console.log('');

  const certId = await stepMtlsCert();
  await stepImageResizing();
  await stepZaraz();
  await stepObservatory();
  printSummary(certId);
}

main().catch((err) => {
  console.error('Phase 6 apply error:', err.message);
  process.exit(1);
});
