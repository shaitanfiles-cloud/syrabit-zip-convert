#!/usr/bin/env node
/**
 * setup-zaraz.mjs
 *
 * Activates Cloudflare Zaraz on the syrabit.ai zone and configures:
 *   1. Google Analytics 4 tool (G-CXJJPSV096)
 *   2. Consent management — GDPR/DPDP-aware mode
 *
 * Prerequisites:
 *   Zaraz must first be ENABLED in the Cloudflare dashboard:
 *     Speed → Zaraz → Enable Zaraz on this zone
 *   Then obtain a token with "Zaraz Edit" permission (account-level) and set:
 *     export CLOUDFLARE_ZARAZ_TOKEN=<value>
 *   Or, if your existing CLOUDFLARE_API_TOKEN already has Zaraz Edit scope,
 *   the script falls back to that.
 *
 *   Once Zaraz is enabled, the zone-level /zaraz/config endpoint becomes
 *   reachable and this script can apply the configuration.
 *
 * Usage:
 *   node workers/edge-proxy/scripts/setup-zaraz.mjs
 *   node workers/edge-proxy/scripts/setup-zaraz.mjs --dry-run
 *
 * What this configures:
 *   - GA4 tool: fires a "Pageview" trigger on every navigation using the
 *     built-in "Pageview" trigger type (matches Zaraz's SPA route-change
 *     events so single-page navigations are tracked correctly).
 *   - Consent: enabled in "informational" mode. A consent cookie
 *     (zaraz-consent) is written on first visit and persists for 365 days.
 *     Categories configured: analytics (GA4), advertising (reserved — empty).
 *     Consent banner wording is left as Zaraz defaults; override in the
 *     dashboard at Speed → Zaraz → Consent.
 *   - Zaraz Web API is enabled so the site can call zaraz.track() and
 *     zaraz.ecommerce() from JS if needed in future.
 *
 * GDPR / DPDP note:
 *   India's Digital Personal Data Protection Act (DPDP) 2023 requires
 *   informed consent before collecting personal data. Zaraz consent mode
 *   gates GA4 from firing until the visitor accepts. This script sets
 *   consent.enabled = true and maps GA4 to the "analytics" category.
 *   Review with your legal team before deploying to EU visitors.
 */

import https from 'https';

const ZONE_ID = process.env.CF_ZONE_ID;
const TOKEN   = process.env.CLOUDFLARE_ZARAZ_TOKEN || process.env.CLOUDFLARE_API_TOKEN;
const DRY_RUN = process.argv.includes('--dry-run');
const GA4_ID  = 'G-CXJJPSV096';

if (!ZONE_ID) { console.error('CF_ZONE_ID is not set'); process.exit(1); }
if (!TOKEN)   { console.error('CLOUDFLARE_ZARAZ_TOKEN (or CLOUDFLARE_API_TOKEN) is not set'); process.exit(1); }

function cfApi(method, path, body) {
  return new Promise((resolve, reject) => {
    const payload = body ? JSON.stringify(body) : undefined;
    const opts = {
      hostname: 'api.cloudflare.com',
      path,
      method,
      headers: {
        'Authorization': `Bearer ${TOKEN}`,
        'Content-Type': 'application/json',
        ...(payload ? { 'Content-Length': Buffer.byteLength(payload) } : {}),
      },
    };
    const req = https.request(opts, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(data) }); }
        catch { resolve({ status: res.statusCode, body: data }); }
      });
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

const GA4_TOOL_ID = 'ga4-syrabit';

const zarazConfig = {
  debugKey: '',
  tools: {
    [GA4_TOOL_ID]: {
      name: 'Google Analytics 4',
      libraryId: 'google-analytics',
      enabled: true,
      type: 'component',
      permissions: ['execute_unsafe_scripts'],
      settings: {
        trackingId: GA4_ID,
        sendPageViews: false,
      },
      actions: {
        pageview: {
          blockingTriggers: [],
          firingTrigger: [{ id: '__zarazPageview', system: true }],
          data: {
            type: 'event',
            name: 'page_view',
          },
        },
      },
    },
  },
  triggers: {},
  variables: {},
  consent: {
    enabled: true,
    cookieName: 'zaraz-consent',
    cookieExpiry: 365,
    modal: true,
    buttonTextAcceptAll: 'Accept all',
    buttonTextRejectAll: 'Reject all',
    buttonTextSavePartial: 'Confirm choices',
    companyName: 'Syrabit',
    companyEmail: 'privacy@syrabit.ai',
    consentModalTitle: 'We value your privacy',
    consentModalDescription: 'We use cookies to measure how you use the site (analytics) so we can improve it for students. No advertising cookies are used.',
    purposes: {
      analytics: {
        name: 'Analytics',
        description: 'Helps us understand how visitors use the site. No personal data is shared with advertisers.',
        order: 1,
      },
    },
    purposeToTools: {
      analytics: [GA4_TOOL_ID],
    },
  },
  historyChange: true,
  autoInjectScript: true,
  zcloudEnabled: true,
};

async function main() {
  console.log(`Setting up Zaraz on zone ${ZONE_ID}${DRY_RUN ? ' [DRY RUN]' : ''}...`);

  const existing = await cfApi('GET', `/client/v4/zones/${ZONE_ID}/zaraz/config`);
  if (!existing.body?.success) {
    console.error('');
    console.error('ERROR: Zaraz config endpoint returned an error:');
    console.error(JSON.stringify(existing.body?.errors, null, 2));
    console.error('');
    console.error('Zaraz must be enabled in the dashboard before this script can run:');
    console.error('  1. Go to https://dash.cloudflare.com → syrabit.ai zone');
    console.error('  2. Speed → Zaraz → Enable Zaraz');
    console.error('  3. Re-run this script once Zaraz is active.');
    process.exit(1);
  }

  const currentConfig = existing.body.result || {};
  console.log('[ok] Zaraz is enabled on this zone. Current tools:', Object.keys(currentConfig.tools || {}));

  if (DRY_RUN) {
    console.log('[dry-run] Would PUT the following Zaraz config:');
    console.log(JSON.stringify(zarazConfig, null, 2));
    return;
  }

  const putRes = await cfApi('PUT', `/client/v4/zones/${ZONE_ID}/zaraz/config`, zarazConfig);
  if (!putRes.body?.success) {
    console.error('[FAIL] Failed to update Zaraz config:', JSON.stringify(putRes.body?.errors));
    process.exit(1);
  }
  console.log('[ok] Zaraz config updated successfully.');
  console.log('');
  console.log('Configured:');
  console.log('  GA4 tool     : Google Analytics 4 (tracking ID:', GA4_ID, ')');
  console.log('  Consent mode : enabled — analytics category gates GA4');
  console.log('  Cookie       : zaraz-consent (365-day expiry)');
  console.log('  Pageviews    : fired via Zaraz built-in Pageview trigger (SPA-aware)');
  console.log('');
  console.log('Next steps:');
  console.log('  1. Remove the ga4Plugin() injection from vite.config.js — Zaraz now');
  console.log('     handles GA4 loading. The /gtag/js gateway in the edge worker can');
  console.log('     be kept as a fallback or removed.');
  console.log('  2. Customise the consent banner copy at Speed → Zaraz → Consent.');
  console.log('  3. Verify GA4 is receiving events in Realtime within 5 minutes.');
}

main().catch(e => { console.error(e); process.exit(1); });
