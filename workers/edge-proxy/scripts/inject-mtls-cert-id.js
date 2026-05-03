#!/usr/bin/env node
// Task #110 — Phase 6: mTLS CI deployment gate.
//
// Called by edge-proxy-deploy.yml BEFORE `wrangler deploy` to replace the
// sentinel value "PENDING_CERT_PROVISIONING" in wrangler.toml with the real
// Cloudflare mTLS certificate UUID stored in the CF_MTLS_CERT_ID CI secret.
//
// BEHAVIOUR:
//   CF_MTLS_CERT_ID set, valid UUID → rewrites wrangler.toml in-place, exits 0
//   CF_MTLS_CERT_ID unset           → exits 1 (aborts the deploy)
//   CF_MTLS_CERT_ID is the sentinel → exits 1 (safety guard)
//   wrangler.toml sentinel not found → exits 1 (idempotency guard — already injected)
//
// The script is idempotent: running it twice with the same UUID is a no-op
// (the second run finds the sentinel already replaced and exits safely).
//
// To provision CF_MTLS_CERT_ID:
//   1. Run cloudflare-phase6-apply.js → note the printed certificate_id UUID.
//   2. Add it to GitHub repo secrets:
//        Settings → Secrets and variables → Actions → New repository secret
//        Name: CF_MTLS_CERT_ID   Value: <uuid>

const fs   = require('fs');
const path = require('path');

const SENTINEL     = 'PENDING_CERT_PROVISIONING';
const WRANGLER_TOML = path.resolve(__dirname, '..', 'wrangler.toml');
const UUID_RE       = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function fail(msg) {
  process.stderr.write(`[inject-mtls] ERROR: ${msg}\n`);
  process.exit(1);
}

const certId = (process.env.CF_MTLS_CERT_ID || '').trim();

if (!certId) {
  fail(
    'CF_MTLS_CERT_ID is not set.\n' +
    '  Add it to GitHub repo secrets (Settings → Secrets → Actions → CF_MTLS_CERT_ID).\n' +
    '  Value: the UUID printed by cloudflare-phase6-apply.js step 1.\n' +
    '  Deploy is blocked until the certificate is provisioned.',
  );
}

if (certId === SENTINEL) {
  fail(
    `CF_MTLS_CERT_ID is still the sentinel value "${SENTINEL}".\n` +
    '  Set it to the real certificate UUID from cloudflare-phase6-apply.js.',
  );
}

if (!UUID_RE.test(certId)) {
  fail(
    `CF_MTLS_CERT_ID "${certId}" is not a valid UUID.\n` +
    '  Expected format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx\n' +
    '  Find the UUID at dash.cloudflare.com → SSL/TLS → Client Certificates.',
  );
}

const original = fs.readFileSync(WRANGLER_TOML, 'utf8');

if (!original.includes(SENTINEL)) {
  // Sentinel already replaced — check if current value matches (idempotent).
  if (original.includes(`certificate_id = "${certId}"`)) {
    process.stdout.write(`[inject-mtls] wrangler.toml already contains certificate_id="${certId}" — no change needed.\n`);
    process.exit(0);
  }
  fail(
    `Sentinel "${SENTINEL}" not found in wrangler.toml and current certificate_id does not match.\n` +
    '  If you recently changed the cert, update the [[mtls_certificates]] block manually\n' +
    '  and ensure certificate_id matches CF_MTLS_CERT_ID.',
  );
}

const updated = original.replace(
  `certificate_id = "${SENTINEL}"`,
  `certificate_id = "${certId}"`,
);

fs.writeFileSync(WRANGLER_TOML, updated, 'utf8');
process.stdout.write(`[inject-mtls] wrangler.toml updated: certificate_id = "${certId}"\n`);
process.stdout.write('[inject-mtls] [[mtls_certificates]] binding is now active for this deploy.\n');
