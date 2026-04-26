/**
 * Task #885 — Bot HTML cache hit/miss observability.
 *
 * The integration test added in Task #876 already proves the
 * `BOT_HTML_CACHE` hit/miss/304 paths fire correctly under unit
 * conditions, but production has no aggregated visibility into how
 * often each branch fires for real Googlebot/Bingbot traffic. The
 * `X-Cache: BOT-KV-HIT|BOT-KV-MISS` header is observable per-request
 * in raw logs only — there's no rolling counter to detect a cache-key
 * regression (which would silently push hit-rate from ~95% to 0%) or
 * a crawler burst that exhausts the daily KV write quota.
 *
 * This module persists per-event counters in the existing `RATE_LIMIT`
 * KV namespace (same store used for `spoof:count:*` in `logSpoofedBot`)
 * bucketed in 5-minute UTC windows over a rolling hour. Counters carry
 * a 3600-second TTL so they survive a worker eviction but auto-expire
 * once they leave the rolling window.
 *
 * The aggregated snapshot is surfaced under
 * `bot_cache: { hit, miss, conditional_304, fallback, legacy_upgrade }` in
 * the `/api/edge/kv-usage` admin response (handleKvUsage in src/index.ts).
 *
 * Task #908 — `legacy_upgrade` tracks how often the bot HTML cache reads
 * a legacy plain-string KV entry (pre Task #896) and rewrites it to the
 * JSON wrapper in the background. It is a SUB-event of a `hit`: the
 * legacy branch only fires from inside a successful KV read. We count
 * it separately so the dashboard can watch the migration burn-down and
 * decide when it's safe to delete the legacy branch from the code path.
 * Because every legacy_upgrade is also a hit, it is intentionally
 * EXCLUDED from `hit_rate` / fallback-rate denominators — including it
 * would double-count the request.
 */

export type BotCacheEvent =
  | "hit"
  | "miss"
  | "conditional_304"
  | "fallback"
  | "legacy_upgrade";

export const BOT_CACHE_EVENTS: BotCacheEvent[] = [
  "hit",
  "miss",
  "conditional_304",
  "fallback",
  "legacy_upgrade",
];

/** 5-minute buckets over a rolling hour = 12 buckets. */
export const BOT_CACHE_BUCKET_MS = 5 * 60 * 1000;
export const BOT_CACHE_BUCKETS_PER_WINDOW = 12;
export const BOT_CACHE_TTL_S = 3600;

/** KV key for a single (kind, bucket) counter. Namespaced under
 *  `bot_cache:` so it never collides with the `spoof:count:*`,
 *  rate-limit window, or `__kv_usage:*` namespaces in `RATE_LIMIT`. */
export function botCacheKey(kind: BotCacheEvent, bucket: number): string {
  return `bot_cache:count:${kind}:${bucket}`;
}

export function currentBotCacheBucket(now: number = Date.now()): number {
  return Math.floor(now / BOT_CACHE_BUCKET_MS);
}

interface WaitUntilCtx {
  waitUntil(p: Promise<unknown>): void;
}

/** Increment the counter for `kind` in the current 5-minute bucket.
 *  Best-effort: the work is scheduled via `ctx.waitUntil` so the
 *  caller never waits on KV. KV failures are swallowed (the kv-monitor
 *  wrapper already converts them to a no-op via the cache fallback). */
export function recordBotCacheEvent(
  kv: KVNamespace | undefined,
  kind: BotCacheEvent,
  ctx: WaitUntilCtx,
): void {
  if (!kv) return;
  const key = botCacheKey(kind, currentBotCacheBucket());
  const op = (async () => {
    try {
      const raw = await kv.get(key);
      const next = raw ? (parseInt(raw, 10) || 0) + 1 : 1;
      await kv.put(key, String(next), { expirationTtl: BOT_CACHE_TTL_S });
    } catch {
      /* best-effort: see kv-monitor wrapper for graceful handling */
    }
  })();
  ctx.waitUntil(op);
}

export interface BotCacheBucketStats {
  /** ISO timestamp at the start of the 5-minute bucket. */
  ts: string;
  hit: number;
  miss: number;
  conditional_304: number;
  fallback: number;
  /** Task #908 — count of legacy plain-string KV entries that were
   *  served from a hit AND rewritten to the JSON wrapper in the
   *  background. A sub-counter of `hit`, NOT additive to it. */
  legacy_upgrade: number;
}

export interface BotCacheStats {
  /** Aggregated totals across the rolling hour. */
  hit: number;
  miss: number;
  conditional_304: number;
  fallback: number;
  /** Task #908 — rolling-hour total of legacy KV entries upgraded to
   *  the JSON wrapper. Watch this trend toward zero to know when the
   *  Task #896 migration is effectively complete and the legacy branch
   *  in `handleBotContentRequest` can be deleted. */
  legacy_upgrade: number;
  /** Hit rate over the window (0..1) computed as
   *  `hit / (hit + miss + fallback)`. 304s are excluded from the
   *  denominator because they're a successful cache outcome from a
   *  freshness-revalidation perspective, not a separate render.
   *  `legacy_upgrade` is also excluded — it is a sub-event of `hit`,
   *  so adding it would double-count the request. The numerator is
   *  `hit` only — a value below ~0.6 in production indicates either a
   *  cache-key drift, a very high churn rate of freshly-published
   *  pages, or an aggressive crawler hitting cold URLs. The dashboard
   *  should alarm on a sudden drop. */
  hit_rate: number;
  /** Per-bucket breakdown, oldest → newest, length = 12. */
  buckets: BotCacheBucketStats[];
}

/** Read the last `BOT_CACHE_BUCKETS_PER_WINDOW` buckets from KV and
 *  return a totalled snapshot. Reads are issued concurrently because
 *  Cloudflare KV `.get()` is a network call and serializing 48 of them
 *  on the admin route would add ~2s latency on a cold POP. */
export async function getBotCacheStats(
  kv: KVNamespace,
  now: number = Date.now(),
): Promise<BotCacheStats> {
  const currentBucket = currentBotCacheBucket(now);
  const buckets: BotCacheBucketStats[] = [];
  const totals: Record<BotCacheEvent, number> = {
    hit: 0,
    miss: 0,
    conditional_304: 0,
    fallback: 0,
    legacy_upgrade: 0,
  };

  // Build the bucket index list oldest → newest so the response array
  // reads naturally in time order.
  const bucketIndices: number[] = [];
  for (let i = BOT_CACHE_BUCKETS_PER_WINDOW - 1; i >= 0; i--) {
    bucketIndices.push(currentBucket - i);
  }

  await Promise.all(
    bucketIndices.map(async (b) => {
      const reads = await Promise.all(
        BOT_CACHE_EVENTS.map(async (kind) => {
          try {
            const raw = await kv.get(botCacheKey(kind, b));
            return raw ? parseInt(raw, 10) || 0 : 0;
          } catch {
            return 0;
          }
        }),
      );
      const [hit, miss, conditional_304, fallback, legacy_upgrade] = reads;
      buckets.push({
        ts: new Date(b * BOT_CACHE_BUCKET_MS).toISOString(),
        hit,
        miss,
        conditional_304,
        fallback,
        legacy_upgrade,
      });
      totals.hit += hit;
      totals.miss += miss;
      totals.conditional_304 += conditional_304;
      totals.fallback += fallback;
      totals.legacy_upgrade += legacy_upgrade;
    }),
  );

  // Promise.all preserves input order, but the per-bucket pushes above
  // race — re-sort by bucket index so the array is deterministic.
  buckets.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));

  const denom = totals.hit + totals.miss + totals.fallback;
  const hit_rate = denom > 0 ? Math.round((totals.hit / denom) * 1000) / 1000 : 0;

  return { ...totals, hit_rate, buckets };
}
