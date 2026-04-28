/**
 * Task #708 — synthetic external probe for /api/admin/diagnostics.
 *
 * Why this exists
 * ---------------
 * Task #706 wired `/api/admin/diagnostics` into the alert pipeline so that
 * when Cloudflare Access enforcement flips off (or break-glass is left
 * active), a page fires through `metrics._dispatch_alert`. The catch:
 * that paging code path only runs when *something* actually calls
 * `/api/admin/diagnostics`. In a real outage no admin is going to be
 * browsing the dashboard, so the alert never fires and the team finds
 * out the next morning.
 *
 * This module is a 1-minute synthetic monitor that runs inside the
 * `syrabit-edge` Worker (cron trigger) and hits `/api/admin/diagnostics`
 * from outside the cluster using a Cloudflare Access service token + a
 * long-lived admin JWT. Every minute the diagnostics paging logic gets a
 * fresh chance to fire — `admin_enforced=false` and `break_glass_active=true`
 * are detected within ~60s instead of "whenever an admin happens to look".
 *
 * Watchdog: if the probe itself stops succeeding for >5 minutes (service
 * token expired, backend wedged, networking broken between the Worker and
 * the Cloud Run origin), we POST a separate alert to a webhook URL so we
 * know the *paging system* itself has gone dark. Without this, a silently
 * broken probe would look identical to "everything is healthy".
 *
 * State persistence
 * -----------------
 * The probe runs in a stateless Worker, so consecutive-failure tracking
 * needs out-of-process storage. We piggy-back on the existing RATE_LIMIT
 * KV namespace (1 read + 1 write per minute = 2880 ops/day, negligible
 * versus the 100k/day free-tier budget).
 *
 * Configuration
 * -------------
 * All knobs live in Worker secrets / vars (see wrangler.toml comments and
 * docs/CLOUDFLARE_ZERO_TRUST.md §7.1):
 *   - SYNTHETIC_PROBE_DISABLED            (var, "true" to skip)
 *   - SYNTHETIC_PROBE_TARGET_URL          (var, override target URL)
 *   - SYNTHETIC_PROBE_CF_ACCESS_CLIENT_ID (secret)
 *   - SYNTHETIC_PROBE_CF_ACCESS_CLIENT_SECRET (secret)
 *   - SYNTHETIC_PROBE_ADMIN_JWT           (secret)
 *   - SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL (secret, Slack/PagerDuty webhook)
 *   - SYNTHETIC_PROBE_WATCHDOG_THRESHOLD_MIN (var, default "5")
 *   - BACKEND_URL                         (var, used when TARGET_URL absent)
 *   - BACKEND_ORIGIN_SECRET               (secret, X-Origin-Auth shared secret)
 */

import { SYNTHETIC_PROBE_PATH } from "./monitored-urls";

const PROBE_STATE_KEY = "synthetic_probe:state";
const PROBE_TIMEOUT_MS = 10_000;
const DEFAULT_WATCHDOG_THRESHOLD_MIN = 5;

export interface SyntheticProbeEnv {
  RATE_LIMIT?: KVNamespace;
  BACKEND_URL?: string;
  BACKEND_ORIGIN_SECRET?: string;
  SYNTHETIC_PROBE_DISABLED?: string;
  SYNTHETIC_PROBE_TARGET_URL?: string;
  SYNTHETIC_PROBE_CF_ACCESS_CLIENT_ID?: string;
  SYNTHETIC_PROBE_CF_ACCESS_CLIENT_SECRET?: string;
  SYNTHETIC_PROBE_ADMIN_JWT?: string;
  SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL?: string;
  SYNTHETIC_PROBE_WATCHDOG_THRESHOLD_MIN?: string;
}

export interface SyntheticProbeState {
  /** ISO timestamp of the most recent successful probe. */
  last_success_at: string | null;
  /** ISO timestamp of the most recent attempt (success or failure). */
  last_attempt_at: string | null;
  /** Consecutive failure count since the last success. */
  consecutive_failures: number;
  /** ISO timestamp the watchdog alert was last fired (cooldown anchor). */
  watchdog_last_fired_at: string | null;
  /** Last error message, truncated. */
  last_error: string | null;
  /** Last HTTP status (0 for network errors). */
  last_status: number;
}

export interface SyntheticProbeResult {
  ok: boolean;
  skipped: boolean;
  status: number;
  duration_ms: number;
  consecutive_failures: number;
  watchdog_fired: boolean;
  reason?: string;
}

const EMPTY_STATE: SyntheticProbeState = {
  last_success_at: null,
  last_attempt_at: null,
  consecutive_failures: 0,
  watchdog_last_fired_at: null,
  last_error: null,
  last_status: 0,
};

async function readState(kv: KVNamespace): Promise<SyntheticProbeState> {
  try {
    const raw = await kv.get(PROBE_STATE_KEY);
    if (!raw) return { ...EMPTY_STATE };
    const parsed = JSON.parse(raw) as Partial<SyntheticProbeState>;
    return { ...EMPTY_STATE, ...parsed };
  } catch {
    return { ...EMPTY_STATE };
  }
}

async function writeState(kv: KVNamespace, state: SyntheticProbeState): Promise<void> {
  try {
    // 7-day TTL is generous: the probe writes every minute, so the key is
    // never actually expired in steady state. The TTL is a safety net so
    // a permanently-disabled probe doesn't leave a stale key forever.
    await kv.put(PROBE_STATE_KEY, JSON.stringify(state), { expirationTtl: 7 * 24 * 3600 });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "unknown";
    console.warn(`[synthetic-probe] state write failed: ${msg.slice(0, 200)}`);
  }
}

function resolveTargetUrl(env: SyntheticProbeEnv): string | null {
  if (env.SYNTHETIC_PROBE_TARGET_URL && env.SYNTHETIC_PROBE_TARGET_URL.trim()) {
    return env.SYNTHETIC_PROBE_TARGET_URL.trim();
  }
  if (env.BACKEND_URL && env.BACKEND_URL.trim()) {
    // The path comes from `monitored-urls.ts` (Task #887) so the value
    // we send and the value the drift test validates against the live
    // OpenAPI schema are the SAME constant — the Task #877 class of bug
    // (probe URL drifts away from the FastAPI router prefix and silently
    // 404s for hours) cannot recur without the CI gate failing first.
    // The FastAPI router is mounted under the `/api` prefix
    // (server.py: `api = APIRouter(prefix="/api")`); the canonical path
    // is therefore `/api/admin/diagnostics`. Do NOT inline a different
    // string here — the assertion lives in `monitored-urls.json`.
    return env.BACKEND_URL.trim().replace(/\/+$/, "") + SYNTHETIC_PROBE_PATH;
  }
  return null;
}

function thresholdMinutes(env: SyntheticProbeEnv): number {
  const raw = env.SYNTHETIC_PROBE_WATCHDOG_THRESHOLD_MIN;
  if (!raw) return DEFAULT_WATCHDOG_THRESHOLD_MIN;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_WATCHDOG_THRESHOLD_MIN;
  // Clamp to ≥1 so a stray fractional override (e.g. "0.5") cannot
  // collapse to 0 and turn the watchdog into a hair-trigger that fires
  // on the very first failed probe.
  return Math.max(1, Math.floor(n));
}

async function fireWatchdog(
  env: SyntheticProbeEnv,
  state: SyntheticProbeState,
  targetUrl: string,
  thresholdMin: number,
): Promise<boolean> {
  const webhook = env.SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL;
  if (!webhook) {
    // ESCALATED to console.error (Task #877) — this is the "paging is
    // dark" signal of last resort. If you are reading this in Workers
    // logs, the synthetic probe has been failing for ≥threshold minutes
    // AND the watchdog webhook is not configured, so nothing else is
    // going to wake anyone up. Fix in this order:
    //   1. Set the secret on the live worker:
    //        wrangler secret put SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL
    //      (Slack incoming-webhook URL or PagerDuty Events v2 endpoint.)
    //   2. Investigate the underlying probe failure — see
    //      docs/CLOUDFLARE_ZERO_TRUST.md §7.1 for the runbook.
    console.error(
      "[synthetic-probe] PAGING-DARK: watchdog threshold reached " +
      `(consecutive_failures=${state.consecutive_failures}, ` +
      `last_status=${state.last_status}, ` +
      `target=${targetUrl}) but SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL ` +
      "is NOT configured — no page will be sent. Fix: " +
      "`wrangler secret put SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL` " +
      "on the syrabit-edge worker. See docs/CLOUDFLARE_ZERO_TRUST.md §7.1.",
    );
    return false;
  }
  // Slack-compatible webhook payload. PagerDuty Events v2 also accepts
  // arbitrary JSON; we keep the payload generic so either endpoint works.
  const payload = {
    text:
      `:rotating_light: *Syrabit synthetic probe is failing* — the 1-minute ` +
      `external check on \`${targetUrl}\` has not succeeded for ` +
      `${state.consecutive_failures} consecutive minutes ` +
      `(threshold: ${thresholdMin}m). The Cloudflare Access paging ` +
      `pipeline (Task #706) is therefore dark. ` +
      `Last status: ${state.last_status}. Last error: ` +
      `${(state.last_error || "(none)").slice(0, 300)}. ` +
      `Last success: ${state.last_success_at || "never"}. ` +
      `See docs/CLOUDFLARE_ZERO_TRUST.md §7.1.`,
    severity: "critical",
    alert_type: "synthetic_probe_dark",
    target_url: targetUrl,
    consecutive_failures: state.consecutive_failures,
    last_success_at: state.last_success_at,
    last_status: state.last_status,
    last_error: (state.last_error || "").slice(0, 300),
  };
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
    const resp = await fetch(webhook, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    });
    clearTimeout(t);
    if (!resp.ok) {
      console.warn(
        `[synthetic-probe] watchdog webhook returned ${resp.status} — ` +
        `alert may not have been delivered`,
      );
      return false;
    }
    return true;
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "unknown";
    console.warn(`[synthetic-probe] watchdog webhook failed: ${msg.slice(0, 200)}`);
    return false;
  }
}

/**
 * Run one iteration of the synthetic probe. Idempotent and safe to call
 * from either a cron trigger or an ad-hoc fetch handler (used by tests).
 *
 * Returns the result of *this* iteration. Persistent state lives in KV.
 */
export async function runSyntheticProbe(
  env: SyntheticProbeEnv,
  now: Date = new Date(),
): Promise<SyntheticProbeResult> {
  const t0 = Date.now();

  if ((env.SYNTHETIC_PROBE_DISABLED || "").toLowerCase() === "true") {
    return {
      ok: false,
      skipped: true,
      status: 0,
      duration_ms: 0,
      consecutive_failures: 0,
      watchdog_fired: false,
      reason: "disabled_by_var",
    };
  }

  const targetUrl = resolveTargetUrl(env);
  if (!targetUrl) {
    console.warn("[synthetic-probe] no BACKEND_URL or SYNTHETIC_PROBE_TARGET_URL set — skipping");
    return {
      ok: false,
      skipped: true,
      status: 0,
      duration_ms: 0,
      consecutive_failures: 0,
      watchdog_fired: false,
      reason: "no_target_url",
    };
  }

  if (!env.RATE_LIMIT) {
    // Without KV we cannot track consecutive failures, which means we
    // cannot drive the watchdog. Fail loud so the misconfiguration is
    // visible in worker logs rather than silently degrading paging.
    console.warn("[synthetic-probe] RATE_LIMIT KV binding missing — skipping (cannot track state)");
    return {
      ok: false,
      skipped: true,
      status: 0,
      duration_ms: 0,
      consecutive_failures: 0,
      watchdog_fired: false,
      reason: "no_kv_binding",
    };
  }

  const headers: Record<string, string> = {
    "Accept": "application/json",
    "User-Agent": "syrabit-edge synthetic-probe/1.0",
  };
  if (env.SYNTHETIC_PROBE_CF_ACCESS_CLIENT_ID && env.SYNTHETIC_PROBE_CF_ACCESS_CLIENT_SECRET) {
    headers["CF-Access-Client-Id"] = env.SYNTHETIC_PROBE_CF_ACCESS_CLIENT_ID;
    headers["CF-Access-Client-Secret"] = env.SYNTHETIC_PROBE_CF_ACCESS_CLIENT_SECRET;
  }
  if (env.SYNTHETIC_PROBE_ADMIN_JWT) {
    headers["Authorization"] = `Bearer ${env.SYNTHETIC_PROBE_ADMIN_JWT}`;
  }
  if (env.BACKEND_ORIGIN_SECRET) {
    // Cloud Run origin guard expects this on every backend hit.
    headers["X-Origin-Auth"] = env.BACKEND_ORIGIN_SECRET;
  }

  const state = await readState(env.RATE_LIMIT);
  state.last_attempt_at = now.toISOString();

  let status = 0;
  let ok = false;
  let errMsg: string | null = null;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
    const resp = await fetch(targetUrl, {
      method: "GET",
      headers,
      signal: ctrl.signal,
      // No cache: every probe must hit the live origin.
      cf: { cacheTtl: 0, cacheEverything: false } as unknown as RequestInitCfProperties,
    });
    clearTimeout(timer);
    status = resp.status;
    // 2xx = endpoint returned and the diagnostics paging logic ran.
    // Any non-2xx (including 401 from Access denying our service token)
    // is a probe failure — the paging logic did NOT run.
    ok = resp.status >= 200 && resp.status < 300;
    if (!ok) {
      // Capture a small slice of the body for diagnostics.
      try {
        const txt = await resp.text();
        errMsg = `HTTP ${resp.status}: ${txt.slice(0, 200)}`;
      } catch {
        errMsg = `HTTP ${resp.status}`;
      }
    }
  } catch (e: unknown) {
    errMsg = e instanceof Error ? e.message : "unknown error";
    if (errMsg && errMsg.length > 300) errMsg = errMsg.slice(0, 300);
  }

  const duration_ms = Date.now() - t0;
  state.last_status = status;
  state.last_error = ok ? null : errMsg;

  let watchdogFired = false;
  if (ok) {
    state.last_success_at = now.toISOString();
    state.consecutive_failures = 0;
  } else {
    state.consecutive_failures = (state.consecutive_failures || 0) + 1;
    const threshold = thresholdMinutes(env);
    // Probe runs every minute, so consecutive_failures is roughly minutes
    // since last success. Cooldown the watchdog at the same threshold so
    // we re-page every `threshold` minutes the probe stays dark — this
    // matches the "is paging alive?" intent (one reminder per period)
    // without spamming the channel every 60s.
    if (state.consecutive_failures >= threshold) {
      const lastFiredMs = state.watchdog_last_fired_at
        ? Date.parse(state.watchdog_last_fired_at)
        : 0;
      const cooldownMs = threshold * 60 * 1000;
      if (!lastFiredMs || now.getTime() - lastFiredMs >= cooldownMs) {
        watchdogFired = await fireWatchdog(env, state, targetUrl, threshold);
        if (watchdogFired) {
          state.watchdog_last_fired_at = now.toISOString();
        }
      }
    }
  }

  await writeState(env.RATE_LIMIT, state);

  console.log(
    `[synthetic-probe] target=${targetUrl} status=${status} ok=${ok} ` +
    `duration_ms=${duration_ms} consecutive_failures=${state.consecutive_failures} ` +
    `watchdog_fired=${watchdogFired}`,
  );

  return {
    ok,
    skipped: false,
    status,
    duration_ms,
    consecutive_failures: state.consecutive_failures,
    watchdog_fired: watchdogFired,
    reason: ok ? undefined : (errMsg || "probe_failed"),
  };
}

/** Test-only: read the persisted probe state. */
export async function _readSyntheticProbeStateForTests(
  kv: KVNamespace,
): Promise<SyntheticProbeState> {
  return readState(kv);
}

/** Test-only: KV key the probe state is stored under. */
export const _SYNTHETIC_PROBE_STATE_KEY = PROBE_STATE_KEY;
