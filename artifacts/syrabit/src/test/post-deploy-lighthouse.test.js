/**
 * post-deploy-lighthouse.test.js
 *
 * Task #142 — Unit and integration-style tests for post-deploy-lighthouse.js.
 *
 * Covered:
 *   extractMetrics  — extracts LCP / CLS / INP from a Lighthouse report JSON
 *   checkThresholds — compares metrics to thresholds; returns { breached, results }
 *   deployMatchesCommit — SHA matching logic (full / prefix / reverse-prefix)
 *
 * Integration-style:
 *   Full pipeline (extractMetrics → checkThresholds) on a realistic LHR fixture,
 *   confirming the script would exit 0 (all pass) or exit 1 (any breach).
 *
 * The entry-point guard added in Task #142 (process.argv[1] === fileURLToPath(…))
 * ensures importing the module does NOT trigger main() / process.exit() during tests.
 *
 * @vitest-environment node
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  extractMetrics,
  checkThresholds,
  deployMatchesCommit,
  THRESHOLDS,
} from '../../scripts/post-deploy-lighthouse.js';

// Silence console output from checkThresholds (ok / fail / info / warn helpers)
// so test output stays clean. Restore after each test.
beforeEach(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
});
afterEach(() => {
  vi.restoreAllMocks();
});

// ── Shared LHR fixture helpers ─────────────────────────────────────────────────

/**
 * Build a minimal Lighthouse report (lhr) with the supplied metric values.
 * Pass undefined for a metric to simulate it being absent from the report.
 */
function makeLhr({ lcp, cls, inp } = {}) {
  const audits = {};
  if (lcp !== undefined) {
    audits['largest-contentful-paint'] = { numericValue: lcp };
  }
  if (cls !== undefined) {
    audits['cumulative-layout-shift'] = { numericValue: cls };
  }
  if (inp !== undefined) {
    audits['interaction-to-next-paint'] = { numericValue: inp };
  }
  return { audits };
}

// ═══════════════════════════════════════════════════════════════════════════════
// extractMetrics
// ═══════════════════════════════════════════════════════════════════════════════

describe('extractMetrics', () => {
  it('extracts all three metrics from a complete LHR', () => {
    const lhr = makeLhr({ lcp: 1200, cls: 0.04, inp: 80 });
    const metrics = extractMetrics(lhr);
    expect(metrics.lcp).toBe(1200);
    expect(metrics.cls).toBe(0.04);
    expect(metrics.inp).toBe(80);
  });

  it('returns undefined for a metric absent from the LHR audits', () => {
    // INP is sometimes absent on pages without interactivity
    const lhr = makeLhr({ lcp: 1800, cls: 0.02 });
    const metrics = extractMetrics(lhr);
    expect(metrics.lcp).toBe(1800);
    expect(metrics.cls).toBe(0.02);
    expect(metrics.inp).toBeUndefined();
  });

  it('returns all undefined when passed a null / empty lhr', () => {
    expect(extractMetrics(null)).toEqual({ lcp: undefined, cls: undefined, inp: undefined });
    expect(extractMetrics({})).toEqual({ lcp: undefined, cls: undefined, inp: undefined });
    expect(extractMetrics({ audits: {} })).toEqual({ lcp: undefined, cls: undefined, inp: undefined });
  });

  it('uses the representative LHR fixture values correctly', () => {
    // Representative fixture: LCP 2 100 ms, CLS 0.08, INP 140 ms (all within thresholds)
    const lhr = makeLhr({ lcp: 2100, cls: 0.08, inp: 140 });
    const { lcp, cls, inp } = extractMetrics(lhr);
    expect(lcp).toBeLessThanOrEqual(THRESHOLDS.lcp.limit);
    expect(cls).toBeLessThanOrEqual(THRESHOLDS.cls.limit);
    expect(inp).toBeLessThanOrEqual(THRESHOLDS.inp.limit);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// checkThresholds
// ═══════════════════════════════════════════════════════════════════════════════

describe('checkThresholds', () => {
  const label = 'homepage';

  it('returns breached=false when all metrics are within thresholds', () => {
    const metrics = { lcp: 1000, cls: 0.05, inp: 100 };
    const { breached, results } = checkThresholds(label, metrics);

    expect(breached).toBe(false);
    expect(results.lcp.status).toBe('pass');
    expect(results.cls.status).toBe('pass');
    expect(results.inp.status).toBe('pass');
  });

  it('returns breached=true when LCP exceeds 2 500 ms', () => {
    const metrics = { lcp: 3200, cls: 0.05, inp: 100 };
    const { breached, results } = checkThresholds(label, metrics);

    expect(breached).toBe(true);
    expect(results.lcp.status).toBe('fail');
    expect(results.cls.status).toBe('pass');
    expect(results.inp.status).toBe('pass');
  });

  it('returns breached=true when CLS exceeds 0.1', () => {
    const metrics = { lcp: 1000, cls: 0.25, inp: 100 };
    const { breached, results } = checkThresholds(label, metrics);

    expect(breached).toBe(true);
    expect(results.lcp.status).toBe('pass');
    expect(results.cls.status).toBe('fail');
    expect(results.inp.status).toBe('pass');
  });

  it('returns breached=true when INP exceeds 200 ms', () => {
    const metrics = { lcp: 1000, cls: 0.05, inp: 350 };
    const { breached, results } = checkThresholds(label, metrics);

    expect(breached).toBe(true);
    expect(results.lcp.status).toBe('pass');
    expect(results.cls.status).toBe('pass');
    expect(results.inp.status).toBe('fail');
  });

  it('treats a missing (undefined) metric as "unavailable" and marks breached=true', () => {
    const metrics = { lcp: undefined, cls: 0.05, inp: 100 };
    const { breached, results } = checkThresholds(label, metrics);

    expect(breached).toBe(true);
    expect(results.lcp.status).toBe('unavailable');
    // Other metrics still evaluated normally
    expect(results.cls.status).toBe('pass');
    expect(results.inp.status).toBe('pass');
  });

  it('treats null metric value as "unavailable" and marks breached=true', () => {
    const metrics = { lcp: null, cls: 0.05, inp: 100 };
    const { breached, results } = checkThresholds(label, metrics);

    expect(breached).toBe(true);
    expect(results.lcp.status).toBe('unavailable');
  });

  it('returns breached=true and all metrics "fail" when all thresholds are breached', () => {
    const metrics = { lcp: 5000, cls: 0.5, inp: 600 };
    const { breached, results } = checkThresholds(label, metrics);

    expect(breached).toBe(true);
    expect(results.lcp.status).toBe('fail');
    expect(results.cls.status).toBe('fail');
    expect(results.inp.status).toBe('fail');
  });

  it('passes at exactly the threshold boundary (value === limit)', () => {
    // The check is value <= limit — exactly on the boundary should PASS.
    const metrics = { lcp: THRESHOLDS.lcp.limit, cls: THRESHOLDS.cls.limit, inp: THRESHOLDS.inp.limit };
    const { breached, results } = checkThresholds(label, metrics);

    expect(breached).toBe(false);
    expect(results.lcp.status).toBe('pass');
    expect(results.cls.status).toBe('pass');
    expect(results.inp.status).toBe('pass');
  });

  it('fails at one unit above the threshold boundary', () => {
    const metrics = {
      lcp: THRESHOLDS.lcp.limit + 1,
      cls: 0.05,
      inp: 100,
    };
    const { breached, results } = checkThresholds(label, metrics);
    expect(breached).toBe(true);
    expect(results.lcp.status).toBe('fail');
  });

  it('records the raw value and limit in each result entry', () => {
    const metrics = { lcp: 3000, cls: 0.05, inp: 100 };
    const { results } = checkThresholds(label, metrics);

    expect(results.lcp.value).toBe(3000);
    expect(results.lcp.limit).toBe(THRESHOLDS.lcp.limit);
    expect(results.cls.value).toBe(0.05);
    expect(results.cls.limit).toBe(THRESHOLDS.cls.limit);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// deployMatchesCommit
// ═══════════════════════════════════════════════════════════════════════════════

describe('deployMatchesCommit', () => {
  const FULL_SHA = 'abc1234567890def1234567890def1234567890aa';

  const makeDeployment = (hash) => ({
    deployment_trigger: { metadata: { commit_hash: hash } },
  });

  it('returns true on an exact full-SHA match', () => {
    expect(deployMatchesCommit(makeDeployment(FULL_SHA), FULL_SHA)).toBe(true);
  });

  it('returns true when Pages has a 12-char truncated SHA and CI has the full SHA', () => {
    const shortHash = FULL_SHA.slice(0, 12);
    expect(deployMatchesCommit(makeDeployment(shortHash), FULL_SHA)).toBe(true);
  });

  it('returns true when CI provides a short SHA prefix and Pages has the full SHA', () => {
    const shortCommitSha = FULL_SHA.slice(0, 12);
    expect(deployMatchesCommit(makeDeployment(FULL_SHA), shortCommitSha)).toBe(true);
  });

  it('returns false when the SHAs do not match', () => {
    const other = 'ffffffffffffffffffffffffffffffffffffffff';
    expect(deployMatchesCommit(makeDeployment(FULL_SHA), other)).toBe(false);
  });

  it('returns false when deployment has no commit_hash', () => {
    expect(deployMatchesCommit(makeDeployment(''), FULL_SHA)).toBe(false);
    expect(deployMatchesCommit(makeDeployment(undefined), FULL_SHA)).toBe(false);
    expect(deployMatchesCommit({}, FULL_SHA)).toBe(false);
    expect(deployMatchesCommit(null, FULL_SHA)).toBe(false);
  });

  it('returns false when commitSha is an empty string', () => {
    expect(deployMatchesCommit(makeDeployment(FULL_SHA), '')).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Integration-style: extractMetrics → checkThresholds pipeline
// Simulates the outcome the script would produce (exit 0 vs exit 1) on a
// realistic Observatory API result, without making any network calls.
// ═══════════════════════════════════════════════════════════════════════════════

describe('extractMetrics + checkThresholds pipeline (integration-style)', () => {
  it('produces exit-0 (all pass) for a healthy real-world LHR', () => {
    // Representative "good" Lighthouse result for a fast page
    const lhr = makeLhr({ lcp: 1850, cls: 0.06, inp: 112 });
    const metrics = extractMetrics(lhr);
    const { breached } = checkThresholds('homepage', metrics);

    // Script exits 0 when no page breaches → breached must be false
    expect(breached).toBe(false);
  });

  it('produces exit-1 (breach) when LCP regresses to > 2 500 ms', () => {
    const lhr = makeLhr({ lcp: 3800, cls: 0.06, inp: 112 });
    const metrics = extractMetrics(lhr);
    const { breached, results } = checkThresholds('chapter page', metrics);

    expect(breached).toBe(true);
    expect(results.lcp.status).toBe('fail');
    expect(results.cls.status).toBe('pass');
    expect(results.inp.status).toBe('pass');
  });

  it('produces exit-1 when a metric is absent from the LHR (Observatory capture failure)', () => {
    // INP not captured — the audit key is entirely absent from the report
    const lhr = makeLhr({ lcp: 1200, cls: 0.04 }); // no inp
    const metrics = extractMetrics(lhr);
    const { breached, results } = checkThresholds('homepage', metrics);

    expect(breached).toBe(true);
    expect(results.inp.status).toBe('unavailable');
  });

  it('produces exit-1 for a triple-breach regression', () => {
    const lhr = makeLhr({ lcp: 5000, cls: 0.35, inp: 450 });
    const metrics = extractMetrics(lhr);
    const { breached, results } = checkThresholds('homepage', metrics);

    expect(breached).toBe(true);
    expect(results.lcp.status).toBe('fail');
    expect(results.cls.status).toBe('fail');
    expect(results.inp.status).toBe('fail');
  });

  it('produces exit-0 for a page right at the "needs improvement" boundary', () => {
    // Exactly at the boundary — should still be treated as a pass (≤ limit)
    const lhr = makeLhr({
      lcp: THRESHOLDS.lcp.limit,     // 2500 ms
      cls: THRESHOLDS.cls.limit,     // 0.1
      inp: THRESHOLDS.inp.limit,     // 200 ms
    });
    const metrics = extractMetrics(lhr);
    const { breached } = checkThresholds('homepage', metrics);

    expect(breached).toBe(false);
  });
});
