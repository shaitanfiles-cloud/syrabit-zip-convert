#!/usr/bin/env node
/**
 * setup-load-balancer.mjs
 *
 * Creates the Cloudflare Load Balancer for api.syrabit.ai.
 *
 * Architecture:
 *   Browser → api.syrabit.ai (CF LB) → Railway backend
 *                                     → (future: Cloud Run fallback)
 *
 * The load balancer sits in front of the Railway origin so Cloudflare can:
 *   - Detect origin outages via health checks and fail over automatically.
 *   - Route requests to the PoP geographically closest to the Railway region
 *     (Mumbai ap-south-1) via Smart Routing.
 *   - Surface per-origin latency / health in the CF dashboard.
 *
 * Prerequisites:
 *   - CLOUDFLARE_LB_TOKEN: a Cloudflare API token with the following permissions:
 *       Account → Load Balancers → Edit
 *       Zone    → Load Balancers → Edit
 *       Zone    → DNS             → Edit
 *     The existing CLOUDFLARE_API_TOKEN lacks these scopes. Create a new token at
 *     https://dash.cloudflare.com/profile/api-tokens with the template
 *     "Load Balancer Management" and scope it to account d66e40eac539fff1db270fddf384a5ec
 *     and zone syrabit.ai. Then: export CLOUDFLARE_LB_TOKEN=<value>
 *   - CF_ZONE_ID: already set in the Replit secrets.
 *
 * Usage:
 *   node workers/edge-proxy/scripts/setup-load-balancer.mjs
 *   node workers/edge-proxy/scripts/setup-load-balancer.mjs --dry-run
 *
 * The script is idempotent: it checks whether each resource already exists
 * (by name) and skips creation if it does.
 */

import https from 'https';

const ACCOUNT_ID = 'd66e40eac539fff1db270fddf384a5ec';
const ZONE_ID    = process.env.CF_ZONE_ID;
const TOKEN      = process.env.CLOUDFLARE_LB_TOKEN || process.env.CLOUDFLARE_API_TOKEN;
const DRY_RUN    = process.argv.includes('--dry-run');

const RAILWAY_ORIGIN = 'workspacemockup-sandbox-production-df37.up.railway.app';

if (!ZONE_ID) { console.error('CF_ZONE_ID is not set'); process.exit(1); }
if (!TOKEN)   { console.error('CLOUDFLARE_LB_TOKEN (or CLOUDFLARE_API_TOKEN) is not set'); process.exit(1); }

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

function ok(r, label) {
  if (!r.body?.success) {
    console.error(`[FAIL] ${label}:`, JSON.stringify(r.body?.errors));
    process.exit(1);
  }
  return r.body.result;
}

async function findOrCreate(listPath, createPath, name, createBody, label) {
  const list = await cfApi('GET', listPath);
  if (list.body?.success) {
    const existing = (list.body.result || []).find(x => x.name === name || x.description === name);
    if (existing) {
      console.log(`[skip] ${label} already exists: ${existing.id}`);
      return existing;
    }
  }
  if (DRY_RUN) {
    console.log(`[dry-run] Would create ${label}:`, JSON.stringify(createBody, null, 2));
    return { id: `dry-run-${label}` };
  }
  const r = await cfApi('POST', createPath, createBody);
  const result = ok(r, `create ${label}`);
  console.log(`[created] ${label}: ${result.id}`);
  return result;
}

async function main() {
  console.log(`Setting up Cloudflare Load Balancer for api.syrabit.ai${DRY_RUN ? ' [DRY RUN]' : ''}...`);

  // ── Step 1: Health check monitor ──────────────────────────────────────────
  const monitor = await findOrCreate(
    `/client/v4/accounts/${ACCOUNT_ID}/load_balancers/monitors`,
    `/client/v4/accounts/${ACCOUNT_ID}/load_balancers/monitors`,
    'syrabit-api-health',
    {
      description: 'syrabit-api-health',
      type: 'https',
      path: '/api/health',
      interval: 60,
      retries: 2,
      timeout: 10,
      expected_codes: '200',
      follow_redirects: false,
      allow_insecure: false,
      header: {
        'Host': ['api.syrabit.ai'],
      },
    },
    'monitor',
  );

  // ── Step 2: Origin pool (Railway) ─────────────────────────────────────────
  const pool = await findOrCreate(
    `/client/v4/accounts/${ACCOUNT_ID}/load_balancers/pools`,
    `/client/v4/accounts/${ACCOUNT_ID}/load_balancers/pools`,
    'syrabit-railway-primary',
    {
      name: 'syrabit-railway-primary',
      description: 'Primary Railway backend — ap-south-1 (Mumbai)',
      enabled: true,
      minimum_origins: 1,
      monitor: monitor.id,
      notification_email: '',
      origins: [
        {
          name: 'railway-ap-south-1',
          address: RAILWAY_ORIGIN,
          enabled: true,
          weight: 1,
          header: {
            Host: ['api.syrabit.ai'],
          },
        },
      ],
    },
    'pool',
  );

  // ── Step 3: Load Balancer on the zone ────────────────────────────────────
  const lbListRes = await cfApi('GET', `/client/v4/zones/${ZONE_ID}/load_balancers`);
  const existingLb = (lbListRes.body?.result || []).find(lb => lb.name === 'api.syrabit.ai');
  if (existingLb) {
    console.log(`[skip] Load Balancer already exists: ${existingLb.id}`);
  } else {
    if (DRY_RUN) {
      console.log('[dry-run] Would create Load Balancer for api.syrabit.ai');
    } else {
      const lbRes = await cfApi('POST', `/client/v4/zones/${ZONE_ID}/load_balancers`, {
        name: 'api.syrabit.ai',
        description: 'api.syrabit.ai → Railway primary (+ future Cloud Run fallback)',
        enabled: true,
        proxied: true,
        ttl: 30,
        steering_policy: 'off',
        session_affinity: 'none',
        fallback_pool: pool.id,
        default_pools: [pool.id],
      });
      ok(lbRes, 'create load balancer');
      console.log(`[created] Load Balancer: ${lbRes.body.result.id}`);
      console.log('[note] The existing AAAA 100:: DNS record for api.syrabit.ai will be');
      console.log('       superseded by the LB. Verify in the Cloudflare dashboard.');
    }
  }

  console.log('');
  console.log('Done. Summary:');
  console.log('  Monitor ID :', monitor.id);
  console.log('  Pool ID    :', pool.id);
  console.log('  LB hostname: api.syrabit.ai (proxied: true)');
  console.log('');
  console.log('Next steps:');
  console.log('  1. Add a Cloud Run origin to the pool once it is provisioned.');
  console.log('  2. Optionally change steering_policy to "proximity" or "geo" once');
  console.log('     multiple pools exist.');
  console.log('  3. Verify health in: CF Dashboard → Traffic → Load Balancing');
}

main().catch(e => { console.error(e); process.exit(1); });
