#!/usr/bin/env node
/**
 * enforce-branch-protection.js
 *
 * Task #141 — Idempotently adds the post-deploy Lighthouse check as a
 * required status check on the master/main branch protection rule so that
 * any PR introducing an LCP / CLS / INP regression cannot be merged until
 * the performance issue is fixed.
 *
 * Required status check context (GitHub Actions format: workflow name / job name):
 *   "post-deploy-lighthouse / Lighthouse post-deploy check (LCP / CLS / INP)"
 *
 * The script:
 *   1. GETs the current branch protection rule (tolerates "no protection yet").
 *   2. Checks whether the Lighthouse context is already in required_status_checks.
 *   3. If present → reports "already configured" and exits 0.
 *   4. If absent → PUTs the updated rule preserving every existing setting
 *      (enforce_admins, required_pull_request_reviews, restrictions, strict).
 *
 * Required env vars:
 *   GITHUB_TOKEN       — PAT with `repo` scope; the token owner must have
 *                        admin permission on the repository.  The standard
 *                        Actions GITHUB_TOKEN does not have admin scope for
 *                        branch protection — store a PAT as a repo secret.
 *   GITHUB_REPOSITORY  — "owner/repo" — set automatically by GitHub Actions.
 *
 * Optional env vars:
 *   BRANCH             — branch to update (default: master)
 *   DRY_RUN            — set to "1" to print the payload without sending it
 */

'use strict';

const REQUIRED_CONTEXT =
  'post-deploy-lighthouse / Lighthouse post-deploy check (LCP / CLS / INP)';

function env(name, fallback) {
  const val = process.env[name];
  if (!val && fallback === undefined) {
    console.error(`Error: environment variable ${name} is not set.`);
    process.exit(1);
  }
  return val || fallback;
}

async function ghFetch(url, options = {}) {
  const token = env('GITHUB_TOKEN');
  const res = await fetch(url, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });
  return res;
}

async function main() {
  const repo   = env('GITHUB_REPOSITORY');
  const branch = env('BRANCH', 'master');
  const dryRun = process.env.DRY_RUN === '1';

  if (dryRun) console.log('DRY_RUN=1 — payload will be printed but not sent.\n');

  const baseUrl = `https://api.github.com/repos/${repo}/branches/${branch}/protection`;

  // ── Step 1: GET current protection ──────────────────────────────────────
  console.log(`Fetching branch protection for ${repo}@${branch} …`);
  const getRes = await ghFetch(baseUrl);

  let current = null;
  if (getRes.status === 404) {
    console.log('  No branch protection rule found — one will be created.');
  } else if (getRes.status === 403) {
    console.error(
      '  403 — the GITHUB_TOKEN lacks admin permission on this repository.\n' +
      '  Use a PAT (not the default Actions token) with `repo` scope stored\n' +
      '  as the GITHUB_TOKEN repo secret. The token owner must be a repo admin.',
    );
    process.exit(1);
  } else if (!getRes.ok) {
    const body = await getRes.text();
    throw new Error(`GET protection failed ${getRes.status}: ${body}`);
  } else {
    current = await getRes.json();
  }

  // ── Step 2: Check idempotency ────────────────────────────────────────────
  const existingContexts = current?.required_status_checks?.contexts ?? [];
  const strict           = current?.required_status_checks?.strict    ?? true;

  if (existingContexts.includes(REQUIRED_CONTEXT)) {
    console.log(
      `✓  Required status check is already present:\n   "${REQUIRED_CONTEXT}"\n` +
      '   Nothing to update.',
    );
    return;
  }

  console.log(
    `  Adding required context:\n   "${REQUIRED_CONTEXT}"\n` +
    `  Existing contexts (${existingContexts.length}): ${existingContexts.join(', ') || '(none)'}`,
  );

  // ── Step 3: Build PUT payload preserving existing settings ───────────────
  //
  // GitHub's PUT /branches/{branch}/protection is a full replacement — every
  // field must be supplied even if unchanged.  We reconstruct the put-friendly
  // shape from the get-response shape, which differs in several places.
  //
  const prReviews = current?.required_pull_request_reviews ?? null;
  const restrictions = current?.restrictions ?? null;

  const payload = {
    required_status_checks: {
      strict,
      contexts: [...existingContexts, REQUIRED_CONTEXT],
    },
    enforce_admins: current?.enforce_admins?.enabled ?? false,
    required_pull_request_reviews: prReviews
      ? {
          dismissal_restrictions: prReviews.dismissal_restrictions
            ? {
                users: (prReviews.dismissal_restrictions.users  || []).map(u => u.login),
                teams: (prReviews.dismissal_restrictions.teams  || []).map(t => t.slug),
                apps:  (prReviews.dismissal_restrictions.apps   || []).map(a => a.slug),
              }
            : undefined,
          dismiss_stale_reviews:          prReviews.dismiss_stale_reviews          ?? false,
          require_code_owner_reviews:     prReviews.require_code_owner_reviews     ?? false,
          required_approving_review_count: prReviews.required_approving_review_count ?? 1,
          require_last_push_approval:     prReviews.require_last_push_approval     ?? false,
        }
      : null,
    restrictions: restrictions
      ? {
          users: (restrictions.users || []).map(u => u.login),
          teams: (restrictions.teams || []).map(t => t.slug),
          apps:  (restrictions.apps  || []).map(a => a.slug),
        }
      : null,
  };

  if (dryRun) {
    console.log('\nDRY_RUN payload (PUT):\n', JSON.stringify(payload, null, 2));
    return;
  }

  // ── Step 4: PUT updated protection ──────────────────────────────────────
  console.log('\nApplying update …');
  const putRes = await ghFetch(baseUrl, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });

  if (putRes.status === 403) {
    console.error(
      '  403 — PUT protection failed: token lacks admin permission.\n' +
      '  See note above about GITHUB_TOKEN PAT requirements.',
    );
    process.exit(1);
  }
  if (!putRes.ok) {
    const body = await putRes.text();
    throw new Error(`PUT protection failed ${putRes.status}: ${body}`);
  }

  console.log(
    `✓  Branch protection updated on ${repo}@${branch}.\n` +
    `   "${REQUIRED_CONTEXT}" is now a required status check.\n` +
    '   PRs that breach LCP > 2.5 s / CLS > 0.1 / INP > 200 ms cannot merge\n' +
    '   until the regression is fixed or the check is bypassed via\n' +
    '   "Actions → post-deploy-lighthouse → Run workflow → skip_lighthouse: true".',
  );
}

main().catch(err => {
  console.error(err.message);
  process.exit(1);
});
