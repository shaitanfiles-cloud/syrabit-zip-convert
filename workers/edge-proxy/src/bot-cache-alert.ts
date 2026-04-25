/**
 * Task #898 — alert on-call when crawler cache hit rate suddenly drops.
 *
 * Why this exists
 * ---------------
 * Task #885 added the `bot_cache.{hit,miss,conditional_304,fallback}`
 * counters and surfaced them under `/api/edge/kv-usage` so a cache-key
 * regression (e.g. a deploy that silently pushes hit-rate from 95% → 5%)
 * is observable in the admin dashboard. The catch is the same one
 * Task #708 hit with `/api/admin/diagnostics`: the signal only fires
 * when someone happens to look. A regression introduced at 23:00 IST
 * is invisible until the morning — by which point we've burned a
 * full day of degraded crawler performance and missed the opportunity
 * to roll back inside the canary window.
 *
 * This module is a 1-minute monitor that runs inside the same
 * `syrabit-edge` Worker cron as the synthetic and CF-block probes. It
 * reads the bot-cache counters straight from `RATE_LIMIT` KV via
 * `getBotCacheStats` (no HTTP round-trip, no auth, no extra latency)
 * and compares two adjacent windows over the rolling hour:
 *
 *   - `recent`   = the most-recent N buckets (default N=3 → last 15 min)
 *   - `baseline` = the N buckets immediately preceding `recent`
 *                  (default → 15..30 min ago)
 *
 * Two independent failure modes are alerted on:
 *
 *   1. **Sudden hit-rate drop** — `baseline.hit_rate - recent.hit_rate`
 *      exceeds `BOT_CACHE_ALERT_DROP_PCT` (default 30 percentage
 *      points). This is the cache-key regression signal: a deploy lands
 *      that perturbs the cache key (User-Agent, Accept-Encoding, query
 *      string normalisation, etc.) and the hit-rate falls off a cliff
 *      within a single bucket window. The 30-pp default catches the
 *      "95% → 5%" failure mode in the task description without paging
 *      on the routine 5-10pp wobble that follows a sitemap publish.
 *
 *   2. **Sustained fallback rate** — `recent.fallback / recent.total`
 *      exceeds `BOT_CACHE_ALERT_FALLBACK_PCT` (default 10%). This is
 *      the degraded-prerender signal: the bot-HTML cache miss path is
 *      falling back to whatever Pages serves (often an empty SPA
 *      shell) instead of a freshly-rendered HTML response. A single
 *      bucket above 10% is allowed; we only page when the *aggregate*
 *      across the recent window crosses, which is naturally a
 *      "sustained" signal.
 *
 * Both signals share the same on-call webhook used by the synthetic
 * probe (`SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL`) but tag the alert
 * payload with distinct `alert_type` values so the receiver can route
 * each independently from the synthetic-probe and cf-block-probe pages
 * already wired into that webhook.
 *
 * Sample-size guard
 * -----------------
 * A 0-volume window has no meaningful hit-rate. To avoid paging on
 * noise (e.g. between Googlebot crawl bursts at 03:00 IST when the
 * bot cache sees 0 events for 15 minutes), we require both windows to
 * carry at least `BOT_CACHE_ALERT_MIN_SAMPLE` events (default 20)
 * before evaluating the drop signal. The fallback signal has its own
 * sample guard: at least `MIN_SAMPLE` events in the recent window
 * before we consider the rate meaningful.
 *
 * Cooldown
 * --------
 * After firing, each alert family enters a 15-minute cooldown so a
 * persistent regression doesn't spam the channel every minute. Both
 * families have independent cooldowns so a hit-rate alert doesn't
 * suppress a fallback alert (or vice versa).
 *
 * Configuration (all on the worker via `wrangler secret put` / vars):
 *   - BOT_CACHE_ALERT_DISABLED         (var, "true" to skip)
 *   - BOT_CACHE_ALERT_DROP_PCT         (var, default "30")
 *   - BOT_CACHE_ALERT_FALLBACK_PCT     (var, default "10")
 *   - BOT_CACHE_ALERT_MIN_SAMPLE       (var, default "20")
 *   - BOT_CACHE_ALERT_WINDOW_BUCKETS   (var, default "3" → 15 min)
 *   - SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL (secret, shared with probes)
 */

import {
  BOT_CACHE_BUCKETS_PER_WINDOW,
  BOT_CACHE_BUCKET_MS,
  BOT_CACHE_EVENTS,
  botCacheKey,
  currentBotCacheBucket,
  type BotCacheBucketStats,
  type BotCacheEvent,
} from "./bot-cache-stats";

const ALERT_STATE_KEY = "bot_cache_alert:state";
const WEBHOOK_TIMEOUT_MS = 10_000;
const DEFAULT_DROP_PCT = 30;
const DEFAULT_FALLBACK_PCT = 10;
const DEFAULT_MIN_SAMPLE = 20;
const DEFAULT_WINDOW_BUCKETS = 3;
const COOLDOWN_MS = 15 * 60 * 1000;

export interface BotCacheAlertEnv {
  RATE_LIMIT?: KVNamespace;
  BOT_CACHE_ALERT_DISABLED?: string;
  BOT_CACHE_ALERT_DROP_PCT?: string;
  BOT_CACHE_ALERT_FALLBACK_PCT?: string;
  BOT_CACHE_ALERT_MIN_SAMPLE?: string;
  BOT_CACHE_ALERT_WINDOW_BUCKETS?: string;
  /** Reused from the synthetic probe so on-call sees one consistent
   *  delivery channel for "the edge layer is degraded". */
  SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL?: string;
}

export interface BotCacheAlertState {
  /** ISO timestamp of the last evaluation (success or skip). */
  last_evaluated_at: string | null;
  /** ISO timestamp the hit-rate-drop alert last fired (cooldown anchor). */
  drop_last_fired_at: string | null;
  /** ISO timestamp the fallback-rate alert last fired. */
  fallback_last_fired_at: string | null;
  /** Most recent computed hit-rate over the recent window (0..1). */
  last_recent_hit_rate: number | null;
  /** Most recent computed hit-rate over the baseline window (0..1). */
  last_baseline_hit_rate: number | null;
  /** Most recent computed fallback rate over the recent window (0..1). */
  last_recent_fallback_rate: number | null;
}

export interface BotCacheAlertResult {
  ok: boolean;
  skipped: boolean;
  reason?: string;
  recent_hit_rate: number | null;
  baseline_hit_rate: number | null;
  recent_fallback_rate: number | null;
  recent_sample: number;
  baseline_sample: number;
  drop_pp: number | null;
  drop_alert_fired: boolean;
  fallback_alert_fired: boolean;
}

const EMPTY_STATE: BotCacheAlertState = {
  last_evaluated_at: null,
  drop_last_fired_at: null,
  fallback_last_fired_at: null,
  last_recent_hit_rate: null,
  last_baseline_hit_rate: null,
  last_recent_fallback_rate: null,
};

async function readState(kv: KVNamespace): Promise<BotCacheAlertState> {
  try {
    const raw = await kv.get(ALERT_STATE_KEY);
    if (!raw) return { ...EMPTY_STATE };
    const parsed = JSON.parse(raw) as Partial<BotCacheAlertState>;
    return { ...EMPTY_STATE, ...parsed };
  } catch {
    return { ...EMPTY_STATE };
  }
}

async function writeState(kv: KVNamespace, state: BotCacheAlertState): Promise<void> {
  try {
    await kv.put(ALERT_STATE_KEY, JSON.stringify(state), { expirationTtl: 7 * 24 * 3600 });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "unknown";
    console.warn(`[bot-cache-alert] state write failed: ${msg.slice(0, 200)}`);
  }
}

function readNumberVar(raw: string | undefined, fallback: number, min = 0): number {
  if (!raw) return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, n);
}

function readWindowBuckets(env: BotCacheAlertEnv): number {
  const n = Math.floor(readNumberVar(env.BOT_CACHE_ALERT_WINDOW_BUCKETS, DEFAULT_WINDOW_BUCKETS, 1));
  // Two adjacent windows of size N must fit inside the rolling hour
  // (12 buckets). Clamp so a stray override (e.g. "20") cannot make
  // the comparison silently degenerate to "compare against itself".
  const max = Math.floor(BOT_CACHE_BUCKETS_PER_WINDOW / 2);
  return Math.min(Math.max(1, n), max);
}

interface WindowAggregate {
  hit: number;
  miss: number;
  conditional_304: number;
  fallback: number;
  /** hit + miss + fallback — denominator of hit_rate / fallback_rate. */
  total: number;
}

function aggregateBuckets(buckets: BotCacheBucketStats[]): WindowAggregate {
  const agg: WindowAggregate = { hit: 0, miss: 0, conditional_304: 0, fallback: 0, total: 0 };
  for (const b of buckets) {
    agg.hit += b.hit;
    agg.miss += b.miss;
    agg.conditional_304 += b.conditional_304;
    agg.fallback += b.fallback;
  }
  // 304s are excluded from the denominator for the same reason the
  // dashboard hit_rate excludes them: they're a successful cache
  // outcome from a freshness-revalidation perspective, not a separate
  // render. Keep this in sync with the formula in bot-cache-stats.ts.
  agg.total = agg.hit + agg.miss + agg.fallback;
  return agg;
}

/** Read the per-bucket counters for the most-recent
 *  `recentN + baselineN` buckets in a single batch of KV reads. */
async function readBuckets(
  kv: KVNamespace,
  count: number,
  now: number,
): Promise<BotCacheBucketStats[]> {
  const currentBucket = currentBotCacheBucket(now);
  const indices: number[] = [];
  // Oldest → newest so the caller can slice baseline/recent without
  // reversing.
  for (let i = count - 1; i >= 0; i--) indices.push(currentBucket - i);

  const reads = await Promise.all(
    indices.map(async (b) => {
      const counters: Record<BotCacheEvent, number> = {
        hit: 0,
        miss: 0,
        conditional_304: 0,
        fallback: 0,
      };
      await Promise.all(
        BOT_CACHE_EVENTS.map(async (kind) => {
          try {
            const raw = await kv.get(botCacheKey(kind, b));
            counters[kind] = raw ? parseInt(raw, 10) || 0 : 0;
          } catch {
            counters[kind] = 0;
          }
        }),
      );
      return {
        ts: new Date(b * BOT_CACHE_BUCKET_MS).toISOString(),
        ...counters,
      };
    }),
  );
  return reads;
}

function rateOf(numer: number, denom: number): number {
  return denom > 0 ? numer / denom : 0;
}

async function fireWebhook(
  env: BotCacheAlertEnv,
  payload: Record<string, unknown>,
): Promise<boolean> {
  const webhook = env.SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL;
  if (!webhook) {
    console.error(
      "[bot-cache-alert] threshold reached but " +
      "SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL is not configured — " +
      "no page will be sent. Fix: " +
      "`wrangler secret put SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL` on " +
      "the syrabit-edge worker. Alert payload: " +
      JSON.stringify(payload).slice(0, 500),
    );
    return false;
  }
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), WEBHOOK_TIMEOUT_MS);
    const resp = await fetch(webhook, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl.signal,
    });
    clearTimeout(t);
    if (!resp.ok) {
      console.warn(
        `[bot-cache-alert] watchdog webhook returned ${resp.status} — ` +
        `alert may not have been delivered`,
      );
      return false;
    }
    return true;
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "unknown";
    console.warn(`[bot-cache-alert] watchdog webhook failed: ${msg.slice(0, 200)}`);
    return false;
  }
}

function pct(rate: number): string {
  return (rate * 100).toFixed(1) + "%";
}

/**
 * Run one iteration of the bot-cache hit-rate / fallback-rate watchdog.
 * Idempotent and safe to call from either a cron trigger or an ad-hoc
 * fetch handler (the test suite exercises both).
 */
export async function runBotCacheAlert(
  env: BotCacheAlertEnv,
  now: Date = new Date(),
): Promise<BotCacheAlertResult> {
  const skipResult = (reason: string): BotCacheAlertResult => ({
    ok: false,
    skipped: true,
    reason,
    recent_hit_rate: null,
    baseline_hit_rate: null,
    recent_fallback_rate: null,
    recent_sample: 0,
    baseline_sample: 0,
    drop_pp: null,
    drop_alert_fired: false,
    fallback_alert_fired: false,
  });

  if ((env.BOT_CACHE_ALERT_DISABLED || "").toLowerCase() === "true") {
    return skipResult("disabled_by_var");
  }
  if (!env.RATE_LIMIT) {
    console.warn("[bot-cache-alert] RATE_LIMIT KV binding missing — skipping");
    return skipResult("no_kv_binding");
  }

  const windowBuckets = readWindowBuckets(env);
  const dropPct = readNumberVar(env.BOT_CACHE_ALERT_DROP_PCT, DEFAULT_DROP_PCT, 0);
  const fallbackPct = readNumberVar(env.BOT_CACHE_ALERT_FALLBACK_PCT, DEFAULT_FALLBACK_PCT, 0);
  const minSample = Math.floor(readNumberVar(env.BOT_CACHE_ALERT_MIN_SAMPLE, DEFAULT_MIN_SAMPLE, 0));

  const buckets = await readBuckets(env.RATE_LIMIT, windowBuckets * 2, now.getTime());
  // First half = baseline (older), second half = recent (newer).
  const baselineBuckets = buckets.slice(0, windowBuckets);
  const recentBuckets = buckets.slice(windowBuckets);
  const baseline = aggregateBuckets(baselineBuckets);
  const recent = aggregateBuckets(recentBuckets);

  const recentHitRate = rateOf(recent.hit, recent.total);
  const baselineHitRate = rateOf(baseline.hit, baseline.total);
  const recentFallbackRate = rateOf(recent.fallback, recent.total);
  const dropPp = (baselineHitRate - recentHitRate) * 100;

  const state = await readState(env.RATE_LIMIT);
  state.last_evaluated_at = now.toISOString();
  state.last_recent_hit_rate = recentHitRate;
  state.last_baseline_hit_rate = baselineHitRate;
  state.last_recent_fallback_rate = recentFallbackRate;

  let dropAlertFired = false;
  let fallbackAlertFired = false;

  // ── Drop signal ────────────────────────────────────────────────────
  // Require BOTH windows to have crossed the sample-size guard. A
  // "0 → 0" or "0 → 5" comparison is meaningless and would page on
  // noise during a low-traffic window.
  if (recent.total >= minSample && baseline.total >= minSample) {
    if (dropPp >= dropPct) {
      const lastFiredMs = state.drop_last_fired_at
        ? Date.parse(state.drop_last_fired_at)
        : 0;
      if (!lastFiredMs || now.getTime() - lastFiredMs >= COOLDOWN_MS) {
        const payload = {
          text:
            `:rotating_light: *Syrabit bot-cache hit-rate has dropped sharply* — ` +
            `last ${windowBuckets * 5}m at ${pct(recentHitRate)} vs prior ` +
            `${windowBuckets * 5}m at ${pct(baselineHitRate)} ` +
            `(drop: ${dropPp.toFixed(1)}pp; threshold ${dropPct}pp). ` +
            `This is the Task #885 cache-key-regression signal — usually ` +
            `caused by a deploy that perturbed the BOT_HTML_CACHE key ` +
            `(User-Agent, Accept-Encoding, or query-string normalisation). ` +
            `Investigate: \`/api/edge/kv-usage\` → \`bot_cache.buckets\` ` +
            `for the per-5m breakdown, then check the most-recent deploy.`,
          severity: "critical",
          alert_type: "bot_cache_hit_rate_drop",
          recent_hit_rate: recentHitRate,
          baseline_hit_rate: baselineHitRate,
          drop_pp: Number(dropPp.toFixed(2)),
          drop_threshold_pp: dropPct,
          recent_window_minutes: windowBuckets * 5,
          recent_sample: recent.total,
          baseline_sample: baseline.total,
          recent_breakdown: { ...recent },
          baseline_breakdown: { ...baseline },
        };
        dropAlertFired = await fireWebhook(env, payload);
        if (dropAlertFired) state.drop_last_fired_at = now.toISOString();
      }
    }
  }

  // ── Fallback signal ────────────────────────────────────────────────
  // Sample guard on the recent window only — we don't compare against
  // baseline here; "10% of the prerender pipeline is degraded" stands
  // on its own as a paging-worthy signal regardless of yesterday's
  // rate.
  if (recent.total >= minSample) {
    if (recentFallbackRate * 100 >= fallbackPct) {
      const lastFiredMs = state.fallback_last_fired_at
        ? Date.parse(state.fallback_last_fired_at)
        : 0;
      if (!lastFiredMs || now.getTime() - lastFiredMs >= COOLDOWN_MS) {
        const payload = {
          text:
            `:warning: *Syrabit bot-cache fallback rate elevated* — ` +
            `last ${windowBuckets * 5}m at ${pct(recentFallbackRate)} ` +
            `(threshold ${fallbackPct}%). The bot-HTML prerender pipeline ` +
            `is degraded: cache misses are falling back to the Pages SPA ` +
            `shell instead of fresh server-rendered HTML. Crawler ` +
            `indexing quality is at risk. ` +
            `Investigate: \`/api/edge/kv-usage\` → \`bot_cache.fallback\` ` +
            `for the per-5m breakdown, then check the prerender service ` +
            `health (Cloud Run / Railway).`,
          severity: "warning",
          alert_type: "bot_cache_fallback_elevated",
          recent_fallback_rate: recentFallbackRate,
          fallback_threshold_pct: fallbackPct,
          recent_window_minutes: windowBuckets * 5,
          recent_sample: recent.total,
          recent_breakdown: { ...recent },
        };
        fallbackAlertFired = await fireWebhook(env, payload);
        if (fallbackAlertFired) state.fallback_last_fired_at = now.toISOString();
      }
    }
  }

  await writeState(env.RATE_LIMIT, state);

  console.log(
    `[bot-cache-alert] recent_hit_rate=${recentHitRate.toFixed(3)} ` +
    `baseline_hit_rate=${baselineHitRate.toFixed(3)} ` +
    `drop_pp=${dropPp.toFixed(2)} ` +
    `recent_fallback_rate=${recentFallbackRate.toFixed(3)} ` +
    `recent_sample=${recent.total} baseline_sample=${baseline.total} ` +
    `drop_alert_fired=${dropAlertFired} fallback_alert_fired=${fallbackAlertFired}`,
  );

  return {
    ok: true,
    skipped: false,
    recent_hit_rate: recentHitRate,
    baseline_hit_rate: baselineHitRate,
    recent_fallback_rate: recentFallbackRate,
    recent_sample: recent.total,
    baseline_sample: baseline.total,
    drop_pp: Number(dropPp.toFixed(2)),
    drop_alert_fired: dropAlertFired,
    fallback_alert_fired: fallbackAlertFired,
  };
}

/** Test-only: read the persisted alert state. */
export async function _readBotCacheAlertStateForTests(
  kv: KVNamespace,
): Promise<BotCacheAlertState> {
  return readState(kv);
}

/** Test-only: KV key the alert state is stored under. */
export const _BOT_CACHE_ALERT_STATE_KEY = ALERT_STATE_KEY;

/** Test-only: defaults exposed so tests can assert the configured
 *  thresholds match the documentation in this file's header. */
export const _BOT_CACHE_ALERT_DEFAULTS = {
  DROP_PCT: DEFAULT_DROP_PCT,
  FALLBACK_PCT: DEFAULT_FALLBACK_PCT,
  MIN_SAMPLE: DEFAULT_MIN_SAMPLE,
  WINDOW_BUCKETS: DEFAULT_WINDOW_BUCKETS,
  COOLDOWN_MS,
} as const;
