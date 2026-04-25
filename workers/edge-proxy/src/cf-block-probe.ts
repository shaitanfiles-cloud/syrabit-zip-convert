/**
 * Task #817 — public-homepage Cloudflare-block detection probe.
 *
 * Why this exists
 * ---------------
 * Task #708's synthetic probe (`./synthetic-probe.ts`) hits the
 * authenticated `/api/admin/diagnostics` endpoint. It catches Cloudflare
 * Access regressions — but it does NOT catch a different class of
 * outage: the Cloudflare WAF managed ruleset, Bot Fight, or a custom
 * firewall rule starts blocking legitimate traffic on the public site.
 * To users it looks like a "Sorry, you have been blocked" page; to
 * existing alerting it looks like nothing, because the admin diagnostics
 * endpoint keeps returning 200.
 *
 * The trigger for this module was Ray `9f14bccc891a6ebf` — an OWASP CRS
 * 949110 "Inbound Anomaly Score Exceeded" false-positive on a plain
 * `GET /` from an Indian Airtel mobile IP. Without an external probe,
 * the only signal that real users were getting blocked was a manual
 * report from the affected user.
 *
 * What it does
 * ------------
 * Every minute (driven by the same cron as the existing synthetic
 * probe) it GETs the public homepage from outside the cluster and
 * detects a Cloudflare 1xxx interstitial via three independent signals:
 *
 *   1. HTTP status 403 / 503 with the `cf-mitigated` response header
 *      set (this is the canonical Cloudflare signal — block, challenge,
 *      ratelimit all surface here).
 *   2. Body contains one of the well-known CF interstitial markers
 *      ("Sorry, you have been blocked", "Cloudflare Ray ID",
 *      `id="cf-error-details"`, `Attention Required! | Cloudflare`).
 *   3. HTTP status 5xx in the 5xx range commonly associated with CF
 *      error pages (1xxx error codes are surfaced as 5xx HTTP statuses
 *      from the perspective of the worker — but only when accompanied
 *      by signal #2 above; a "real" backend 5xx is not a CF block).
 *
 * State persists in the same `RATE_LIMIT` KV namespace under a separate
 * key so it does not interfere with `synthetic_probe:state`. The
 * watchdog re-uses the existing webhook URL but tags the alert with
 * `alert_type: "cf_public_block_detected"` so the receiver can route it
 * differently if desired.
 *
 * Threshold default is **2** consecutive failures (≈2 minutes of public
 * blocks) — much faster than the admin probe's 5-minute threshold,
 * because a public-facing block is user-visible and needs a same-minute
 * page rather than a "did paging die?" reminder.
 */

const PROBE_STATE_KEY = "cf_block_probe:state";
const PROBE_TIMEOUT_MS = 10_000;
const DEFAULT_TARGET_URL = "https://syrabit.ai/";
const DEFAULT_THRESHOLD = 2;

// Body markers that are extremely unlikely to appear in a real Syrabit
// response. Match is case-insensitive. Keep this list short and
// specific — false positives here would page the on-call for nothing.
const BLOCK_MARKERS = [
  "sorry, you have been blocked",
  "cloudflare ray id",
  'id="cf-error-details"',
  "attention required! | cloudflare",
  "error code: 1020",
  "error code: 1015",
  "checking your browser before accessing",
];

export interface CfBlockProbeEnv {
  RATE_LIMIT?: KVNamespace;
  /** Override target URL. Defaults to `https://syrabit.ai/`. */
  CF_BLOCK_PROBE_TARGET_URL?: string;
  /** Set to "true" to pause the probe without redeploying. */
  CF_BLOCK_PROBE_DISABLED?: string;
  /** Override the consecutive-failure threshold (default 2). */
  CF_BLOCK_PROBE_THRESHOLD?: string;
  /** Reuse the existing watchdog webhook from the synthetic probe. */
  SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL?: string;
}

export interface CfBlockProbeState {
  last_success_at: string | null;
  last_attempt_at: string | null;
  consecutive_failures: number;
  watchdog_last_fired_at: string | null;
  last_signal: string | null;
  last_status: number;
  last_ray_id: string | null;
}

export interface CfBlockProbeResult {
  ok: boolean;
  skipped: boolean;
  status: number;
  duration_ms: number;
  consecutive_failures: number;
  watchdog_fired: boolean;
  blocked: boolean;
  signal?: string;
  ray_id?: string | null;
  reason?: string;
}

const EMPTY_STATE: CfBlockProbeState = {
  last_success_at: null,
  last_attempt_at: null,
  consecutive_failures: 0,
  watchdog_last_fired_at: null,
  last_signal: null,
  last_status: 0,
  last_ray_id: null,
};

async function readState(kv: KVNamespace): Promise<CfBlockProbeState> {
  try {
    const raw = await kv.get(PROBE_STATE_KEY);
    if (!raw) return { ...EMPTY_STATE };
    const parsed = JSON.parse(raw) as Partial<CfBlockProbeState>;
    return { ...EMPTY_STATE, ...parsed };
  } catch {
    return { ...EMPTY_STATE };
  }
}

async function writeState(kv: KVNamespace, state: CfBlockProbeState): Promise<void> {
  try {
    await kv.put(PROBE_STATE_KEY, JSON.stringify(state), { expirationTtl: 7 * 24 * 3600 });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "unknown";
    console.warn(`[cf-block-probe] state write failed: ${msg.slice(0, 200)}`);
  }
}

function thresholdValue(env: CfBlockProbeEnv): number {
  const raw = env.CF_BLOCK_PROBE_THRESHOLD;
  if (!raw) return DEFAULT_THRESHOLD;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_THRESHOLD;
  return Math.max(1, Math.floor(n));
}

function detectCfBlock(status: number, headers: Headers, body: string): { blocked: boolean; signal: string | null } {
  // Signal 1: cf-mitigated header is the canonical Cloudflare flag.
  // Values seen in the wild: "block", "challenge", "ratelimit".
  // This is the strongest signal — accept it at any status.
  const mitigated = headers.get("cf-mitigated");
  if (mitigated) {
    return { blocked: true, signal: `cf-mitigated:${mitigated}` };
  }

  // Signal 2: body markers — case-insensitive substring match on a
  // bounded slice. To avoid false positives where the homepage HTML
  // legitimately contains a phrase like "Cloudflare Ray ID" (e.g. a
  // help-doc snippet, a marketing page that explains CF errors, etc.)
  // we only match body markers when EITHER the status is in the error
  // range (>=400) OR the response carries a cf-ray header that does
  // NOT match the headers we'd expect from a normal cached HTML
  // response. The `cf-ray` header alone is too weak — every CF
  // response has it — so we additionally require status >= 400.
  // Combined: marker matching is gated to "this is plausibly an error
  // page". A normal 200 OK never enters this branch.
  if (status >= 400) {
    const lower = body.slice(0, 16_000).toLowerCase();
    for (const m of BLOCK_MARKERS) {
      if (lower.includes(m)) {
        return { blocked: true, signal: `body:${m}` };
      }
    }
  }

  // Signal 3: defensive — a 403 with a ray header but empty body
  // (CF sometimes returns a bare interstitial). Strongest non-body
  // proxy for "this came from CF, not from our backend".
  if (status === 403 && headers.get("cf-ray") && !body.trim()) {
    return { blocked: true, signal: "status403:empty-body+cf-ray" };
  }

  return { blocked: false, signal: null };
}

/**
 * A signal is a "CF block" only when the detector identified a real
 * Cloudflare-side mitigation (cf-mitigated header, body marker, or the
 * 403+empty+cf-ray fallback). Any other failure (generic non-2xx,
 * network error, etc.) is a public-homepage outage of unknown cause —
 * we still page on it, but with a different alert_type and runbook
 * pointer so the on-call doesn't waste time chasing a WAF rule that
 * isn't firing.
 */
function isCfBlockSignal(signal: string | null): boolean {
  if (!signal) return false;
  return (
    signal.startsWith("cf-mitigated:") ||
    signal.startsWith("body:") ||
    signal.startsWith("status403:")
  );
}

async function fireWatchdog(
  env: CfBlockProbeEnv,
  state: CfBlockProbeState,
  targetUrl: string,
  threshold: number,
): Promise<boolean> {
  const webhook = env.SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL;
  if (!webhook) {
    console.warn(
      "[cf-block-probe] threshold reached but " +
      "SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL is not configured — alert " +
      "would have fired. consecutive_failures=" + state.consecutive_failures,
    );
    return false;
  }
  const isCfBlock = isCfBlockSignal(state.last_signal);
  const alertType = isCfBlock ? "cf_public_block_detected" : "public_homepage_probe_failed";
  const text = isCfBlock
    ? `:no_entry_sign: *Syrabit public homepage is being blocked by Cloudflare* — ` +
      `\`${targetUrl}\` has returned a CF block / challenge for ` +
      `${state.consecutive_failures} consecutive minutes ` +
      `(threshold: ${threshold}). Real users are seeing the ` +
      `"Sorry, you have been blocked" interstitial. ` +
      `Last signal: ${state.last_signal}. ` +
      `Last Ray ID: ${state.last_ray_id || "(unknown)"}. ` +
      `Last status: ${state.last_status}. ` +
      `Run: \`python artifacts/syrabit-backend/scripts/cf_ray_lookup.py ` +
      `${state.last_ray_id || "<ray>"}\` to identify the firing rule. ` +
      `See docs/CLOUDFLARE_ZERO_TRUST.md §8.4.`
    : `:warning: *Syrabit public homepage probe failing (non-CF signal)* — ` +
      `\`${targetUrl}\` has been unreachable / returning errors for ` +
      `${state.consecutive_failures} consecutive minutes ` +
      `(threshold: ${threshold}). This does NOT match a Cloudflare ` +
      `block / challenge pattern — likely an origin (Railway / Pages) ` +
      `outage, DNS issue, or Cloudflare network event. ` +
      `Last signal: ${state.last_signal}. ` +
      `Last status: ${state.last_status}. ` +
      `Last Ray ID: ${state.last_ray_id || "(none)"}. ` +
      `See docs/CLOUDFLARE_ZERO_TRUST.md §8.1 for the signal-first ` +
      `triage decision tree.`;
  // Emit both the full URL and the path independently so a future
  // multi-leg probe (e.g. homepage + chat-submit) can be triaged
  // quickly: an on-call sees `endpoint_path: "/"` vs
  // `endpoint_path: "/api/ai/chat"` in the alert without needing to
  // parse the URL. Tracked in
  // .local/follow_up_tasks/cf-block-probe-chat-smoke.md.
  let endpointPath = "/";
  try {
    endpointPath = new URL(targetUrl).pathname || "/";
  } catch {
    endpointPath = "/";
  }
  const payload = {
    text,
    severity: "critical",
    alert_type: alertType,
    cf_block_signal: isCfBlock,
    target_url: targetUrl,
    endpoint_path: endpointPath,
    probe_leg: "homepage",
    consecutive_failures: state.consecutive_failures,
    last_signal: state.last_signal,
    last_status: state.last_status,
    last_ray_id: state.last_ray_id,
    last_success_at: state.last_success_at,
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
        `[cf-block-probe] watchdog webhook returned ${resp.status} — ` +
        `alert may not have been delivered`,
      );
      return false;
    }
    return true;
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "unknown";
    console.warn(`[cf-block-probe] watchdog webhook failed: ${msg.slice(0, 200)}`);
    return false;
  }
}

/**
 * Run one iteration of the public-homepage probe.
 */
export async function runCfBlockProbe(
  env: CfBlockProbeEnv,
  now: Date = new Date(),
): Promise<CfBlockProbeResult> {
  const t0 = Date.now();

  if ((env.CF_BLOCK_PROBE_DISABLED || "").toLowerCase() === "true") {
    return {
      ok: false,
      skipped: true,
      status: 0,
      duration_ms: 0,
      consecutive_failures: 0,
      watchdog_fired: false,
      blocked: false,
      reason: "disabled_by_var",
    };
  }

  if (!env.RATE_LIMIT) {
    console.warn("[cf-block-probe] RATE_LIMIT KV binding missing — skipping");
    return {
      ok: false,
      skipped: true,
      status: 0,
      duration_ms: 0,
      consecutive_failures: 0,
      watchdog_fired: false,
      blocked: false,
      reason: "no_kv_binding",
    };
  }

  const targetUrl = (env.CF_BLOCK_PROBE_TARGET_URL || DEFAULT_TARGET_URL).trim();

  const state = await readState(env.RATE_LIMIT);
  state.last_attempt_at = now.toISOString();

  let status = 0;
  let blocked = false;
  let signal: string | null = null;
  let rayId: string | null = null;
  let errMsg: string | null = null;
  // Use a realistic browser User-Agent. Many CF bot rules block the
  // generic "edge worker" UA wholesale, which would generate false
  // positives that have nothing to do with what real users see.
  const headers: Record<string, string> = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "User-Agent":
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " +
      "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 " +
      "syrabit-edge cf-block-probe/1.0",
    // Identify the probe to the origin via a header that survives the
    // CF edge, so we can grep production logs for it without leaking
    // it to real users.
    "X-Syrabit-Probe": "cf-block-probe",
  };
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
    const resp = await fetch(targetUrl, {
      method: "GET",
      headers,
      signal: ctrl.signal,
      // Bypass CF's caching so every probe hits the live edge ruleset.
      cf: { cacheTtl: 0, cacheEverything: false } as unknown as RequestInitCfProperties,
    });
    clearTimeout(timer);
    status = resp.status;
    rayId = resp.headers.get("cf-ray") || null;
    if (rayId) {
      // The cf-ray header is `<16-hex>-<POP>`; strip the POP for the
      // canonical name that matches firewallEventsAdaptive.rayName.
      rayId = rayId.split("-", 1)[0].trim() || rayId;
    }
    let body = "";
    try {
      body = await resp.text();
    } catch {
      body = "";
    }
    const detection = detectCfBlock(status, resp.headers, body);
    blocked = detection.blocked;
    signal = detection.signal;
    if (!blocked && (status < 200 || status >= 300)) {
      // A non-2xx that doesn't look like a CF block is still a probe
      // failure (the public site is broken in some other way) — but
      // we tag the signal with a NON-CF prefix so the watchdog text
      // and alert_type accurately describe the failure as an origin
      // / network outage rather than a WAF rule. The on-call won't
      // waste time chasing a rule that isn't firing.
      blocked = true;
      signal = `non-cf:non-2xx-status:${status}`;
    }
    if (blocked) {
      errMsg = `${signal} status=${status} ray=${rayId || "?"}`;
    }
  } catch (e: unknown) {
    errMsg = e instanceof Error ? e.message : "unknown error";
    if (errMsg && errMsg.length > 300) errMsg = errMsg.slice(0, 300);
    blocked = true;
    // Network-level failure — explicitly tagged non-CF.
    signal = "non-cf:fetch-error";
  }

  const duration_ms = Date.now() - t0;
  const ok = !blocked;
  state.last_status = status;
  state.last_signal = ok ? null : signal;
  state.last_ray_id = rayId;

  let watchdogFired = false;
  if (ok) {
    state.last_success_at = now.toISOString();
    state.consecutive_failures = 0;
  } else {
    state.consecutive_failures = (state.consecutive_failures || 0) + 1;
    const threshold = thresholdValue(env);
    if (state.consecutive_failures >= threshold) {
      const lastFiredMs = state.watchdog_last_fired_at
        ? Date.parse(state.watchdog_last_fired_at)
        : 0;
      // Cooldown matches threshold — same heuristic as the synthetic
      // probe: re-fire every `threshold` minutes the block persists,
      // not every minute.
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
    `[cf-block-probe] target=${targetUrl} status=${status} ok=${ok} ` +
    `blocked=${blocked} signal=${signal || "-"} ray=${rayId || "-"} ` +
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
    blocked,
    signal: signal || undefined,
    ray_id: rayId,
    reason: ok ? undefined : (errMsg || "blocked"),
  };
}

/** Test-only: read the persisted probe state. */
export async function _readCfBlockProbeStateForTests(
  kv: KVNamespace,
): Promise<CfBlockProbeState> {
  return readState(kv);
}

/** Test-only: KV key the probe state is stored under. */
export const _CF_BLOCK_PROBE_STATE_KEY = PROBE_STATE_KEY;

/** Test-only: the canonical block-marker list (kept in sync with prod). */
export const _CF_BLOCK_MARKERS = BLOCK_MARKERS;
