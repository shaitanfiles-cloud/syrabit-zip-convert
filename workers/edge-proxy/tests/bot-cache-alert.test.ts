import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  runBotCacheAlert,
  _readBotCacheAlertStateForTests,
  _BOT_CACHE_ALERT_STATE_KEY,
  _BOT_CACHE_ALERT_DEFAULTS,
  type BotCacheAlertEnv,
} from "../src/bot-cache-alert";
import {
  BOT_CACHE_BUCKET_MS,
  botCacheKey,
  currentBotCacheBucket,
  type BotCacheEvent,
} from "../src/bot-cache-stats";

class FakeKv {
  store = new Map<string, string>();
  async get(key: string): Promise<string | null> {
    return this.store.has(key) ? this.store.get(key)! : null;
  }
  async put(key: string, value: string, _opts?: unknown): Promise<void> {
    this.store.set(key, value);
  }
  async delete(key: string): Promise<void> {
    this.store.delete(key);
  }
  async list(): Promise<{ keys: { name: string }[]; list_complete: boolean }> {
    return { keys: [...this.store.keys()].map((name) => ({ name })), list_complete: true };
  }
}

interface BucketCounters {
  hit?: number;
  miss?: number;
  conditional_304?: number;
  fallback?: number;
}

/**
 * Seed the per-bucket counters in KV the same way `recordBotCacheEvent`
 * would. `offsetBuckets` is how many 5-min buckets back from `now` —
 * 0 = current bucket, 1 = previous bucket, …
 */
async function seedBucket(
  kv: FakeKv,
  now: number,
  offsetBuckets: number,
  counters: BucketCounters,
): Promise<void> {
  const bucket = currentBotCacheBucket(now) - offsetBuckets;
  for (const [k, v] of Object.entries(counters)) {
    if (typeof v === "number" && v > 0) {
      await kv.put(botCacheKey(k as BotCacheEvent, bucket), String(v));
    }
  }
}

function baseEnv(over: Partial<BotCacheAlertEnv> = {}): BotCacheAlertEnv & { RATE_LIMIT: FakeKv } {
  const kv = new FakeKv();
  return {
    RATE_LIMIT: kv as unknown as KVNamespace,
    SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL: "https://hooks.example.com/watchdog",
    ...over,
  } as BotCacheAlertEnv & { RATE_LIMIT: FakeKv };
}

const NOW_MS = Date.UTC(2026, 3, 24, 12, 0, 0);
const NOW = new Date(NOW_MS);

describe("bot-cache alert", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("skips with disabled_by_var when BOT_CACHE_ALERT_DISABLED=true", async () => {
    const env = baseEnv({ BOT_CACHE_ALERT_DISABLED: "true" });
    const res = await runBotCacheAlert(env, NOW);
    expect(res.skipped).toBe(true);
    expect(res.reason).toBe("disabled_by_var");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("skips with no_kv_binding when RATE_LIMIT is absent", async () => {
    const env = baseEnv();
    delete (env as Partial<BotCacheAlertEnv>).RATE_LIMIT;
    const res = await runBotCacheAlert(env, NOW);
    expect(res.skipped).toBe(true);
    expect(res.reason).toBe("no_kv_binding");
  });

  it("does not page when both windows are empty (no traffic)", async () => {
    const env = baseEnv();
    const res = await runBotCacheAlert(env, NOW);
    expect(res.ok).toBe(true);
    expect(res.skipped).toBe(false);
    expect(res.recent_sample).toBe(0);
    expect(res.baseline_sample).toBe(0);
    expect(res.drop_alert_fired).toBe(false);
    expect(res.fallback_alert_fired).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("does not page when the recent window is below the sample-size guard", async () => {
    const env = baseEnv();
    // Baseline (offsets 3-5): healthy 95% hit rate, plenty of volume.
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 95, miss: 5 });
    }
    // Recent (offsets 0-2): only 5 events total — under MIN_SAMPLE (20).
    await seedBucket(env.RATE_LIMIT, NOW_MS, 0, { hit: 0, miss: 5 });

    const res = await runBotCacheAlert(env, NOW);
    expect(res.recent_sample).toBeLessThan(_BOT_CACHE_ALERT_DEFAULTS.MIN_SAMPLE);
    expect(res.drop_alert_fired).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("pages on a sudden hit-rate drop ≥30pp with sufficient sample", async () => {
    const env = baseEnv();
    // Baseline 15-30m ago: 95% hit rate (95 hits, 5 misses per bucket).
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 95, miss: 5 });
    }
    // Recent 0-15m: 5% hit rate (5 hits, 95 misses per bucket) —
    // simulates the "deploy regressed the cache key" failure mode.
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 5, miss: 95 });
    }
    const res = await runBotCacheAlert(env, NOW);
    expect(res.ok).toBe(true);
    expect(res.recent_hit_rate).toBeCloseTo(0.05, 2);
    expect(res.baseline_hit_rate).toBeCloseTo(0.95, 2);
    expect(res.drop_pp).toBeGreaterThanOrEqual(30);
    expect(res.drop_alert_fired).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://hooks.example.com/watchdog");
    const payload = JSON.parse((init as RequestInit).body as string);
    expect(payload.alert_type).toBe("bot_cache_hit_rate_drop");
    expect(payload.severity).toBe("critical");
    expect(payload.recent_hit_rate).toBeCloseTo(0.05, 2);
    expect(payload.baseline_hit_rate).toBeCloseTo(0.95, 2);
    expect(payload.drop_threshold_pp).toBe(30);
    expect(payload.recent_window_minutes).toBe(15);
    expect(payload.recent_breakdown.hit).toBe(15);
    expect(payload.baseline_breakdown.hit).toBe(285);
  });

  it("does NOT page on a hit-rate wobble below the configured threshold", async () => {
    const env = baseEnv();
    // Baseline: 90% hit rate.
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 90, miss: 10 });
    }
    // Recent: 70% hit rate — a 20pp drop, below the 30pp default.
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 70, miss: 30 });
    }
    const res = await runBotCacheAlert(env, NOW);
    expect(res.drop_pp).toBeGreaterThan(0);
    expect(res.drop_pp).toBeLessThan(30);
    expect(res.drop_alert_fired).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("respects BOT_CACHE_ALERT_DROP_PCT override", async () => {
    const env = baseEnv({ BOT_CACHE_ALERT_DROP_PCT: "10" });
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 90, miss: 10 });
    }
    // Recent: 70% — a 20pp drop, now over the lowered 10pp threshold.
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 70, miss: 30 });
    }
    const res = await runBotCacheAlert(env, NOW);
    expect(res.drop_alert_fired).toBe(true);
    const payload = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(payload.drop_threshold_pp).toBe(10);
  });

  it("pages on a sustained fallback rate above 10%", async () => {
    const env = baseEnv();
    // Baseline doesn't matter for the fallback signal — make it healthy.
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 100 });
    }
    // Recent: ~20% fallback rate sustained across all 3 buckets.
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 80, fallback: 20 });
    }
    const res = await runBotCacheAlert(env, NOW);
    expect(res.recent_fallback_rate).toBeCloseTo(0.2, 2);
    expect(res.fallback_alert_fired).toBe(true);
    // Only the fallback alert should fire here — the hit-rate is
    // 80% recent vs 100% baseline (20pp drop, under 30pp default).
    expect(res.drop_alert_fired).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const payload = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(payload.alert_type).toBe("bot_cache_fallback_elevated");
    expect(payload.recent_fallback_rate).toBeCloseTo(0.2, 2);
    expect(payload.fallback_threshold_pct).toBe(10);
  });

  it("can fire BOTH the drop and fallback alerts in the same evaluation", async () => {
    const env = baseEnv();
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 95, miss: 5 });
    }
    // Recent: hit-rate 5%, fallback 50% → both signals.
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 5, miss: 45, fallback: 50 });
    }
    const res = await runBotCacheAlert(env, NOW);
    expect(res.drop_alert_fired).toBe(true);
    expect(res.fallback_alert_fired).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const types = fetchMock.mock.calls
      .map((c) => JSON.parse((c[1] as RequestInit).body as string).alert_type)
      .sort();
    expect(types).toEqual(["bot_cache_fallback_elevated", "bot_cache_hit_rate_drop"]);
  });

  it("respects independent cooldowns for drop vs fallback alerts", async () => {
    const env = baseEnv();
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 95, miss: 5 });
    }
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 5, miss: 95 });
    }
    // First evaluation fires drop alert.
    const r1 = await runBotCacheAlert(env, NOW);
    expect(r1.drop_alert_fired).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // 5 minutes later, drop persists — should NOT page again (cooldown
    // 15m). A NEW fallback signal also appears — that has its own
    // independent cooldown so it should fire.
    const t2 = new Date(NOW_MS + 5 * 60 * 1000);
    // Add fresh buckets so the rolling window still shows the drop
    // AND now also has a fallback signal in the recent window.
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, t2.getTime(), off, { hit: 0, miss: 50, fallback: 50 });
    }
    const r2 = await runBotCacheAlert(env, t2);
    expect(r2.drop_alert_fired).toBe(false); // suppressed by cooldown
    expect(r2.fallback_alert_fired).toBe(true); // independent cooldown
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(
      JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string).alert_type,
    ).toBe("bot_cache_fallback_elevated");
  });

  it("re-fires the drop alert after the 15-minute cooldown elapses", async () => {
    const env = baseEnv();
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 95, miss: 5 });
    }
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 5, miss: 95 });
    }
    await runBotCacheAlert(env, NOW);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Exactly at cooldown boundary — should re-fire.
    const t2 = new Date(NOW_MS + _BOT_CACHE_ALERT_DEFAULTS.COOLDOWN_MS);
    // Re-seed buckets so the rolling window centred on t2 shows the
    // same regression pattern.
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, t2.getTime(), off, { hit: 95, miss: 5 });
    }
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, t2.getTime(), off, { hit: 5, miss: 95 });
    }
    const r2 = await runBotCacheAlert(env, t2);
    expect(r2.drop_alert_fired).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("excludes conditional_304 from the hit_rate denominator (matches dashboard formula)", async () => {
    const env = baseEnv();
    // Baseline 95% hit rate.
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 95, miss: 5 });
    }
    // Recent: 50 hits, 50 misses, but ALSO 1000 304s. If 304s leaked
    // into the denominator, the recent hit_rate would collapse to
    // ~5%. The formula in bot-cache-stats.ts excludes them, so the
    // recent hit_rate must be 50% — a 45pp drop, which still pages.
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, {
        hit: 50,
        miss: 50,
        conditional_304: 1000,
      });
    }
    const res = await runBotCacheAlert(env, NOW);
    expect(res.recent_hit_rate).toBeCloseTo(0.5, 2);
    expect(res.drop_pp).toBeCloseTo(45, 0);
  });

  it("logs but does not crash when watchdog webhook is unset", async () => {
    const warn = vi.spyOn(console, "error").mockImplementation(() => {});
    const env = baseEnv({ SYNTHETIC_PROBE_WATCHDOG_WEBHOOK_URL: "" });
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 95, miss: 5 });
    }
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 5, miss: 95 });
    }
    const res = await runBotCacheAlert(env, NOW);
    expect(res.drop_alert_fired).toBe(false);
    // No fetch attempted; the warning is the only outward signal.
    expect(fetchMock).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("survives a webhook failure without throwing", async () => {
    fetchMock.mockReset();
    fetchMock.mockRejectedValue(new Error("ECONNRESET"));
    const env = baseEnv();
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 95, miss: 5 });
    }
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 5, miss: 95 });
    }
    const res = await runBotCacheAlert(env, NOW);
    expect(res.drop_alert_fired).toBe(false);
    // State should not record drop_last_fired_at since the webhook failed —
    // a future minute can re-attempt without waiting out a cooldown.
    const state = await _readBotCacheAlertStateForTests(env.RATE_LIMIT as unknown as KVNamespace);
    expect(state.drop_last_fired_at).toBeNull();
  });

  it("persists computed rates into state for diagnostics", async () => {
    const env = baseEnv();
    for (const off of [3, 4, 5]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 80, miss: 20 });
    }
    for (const off of [0, 1, 2]) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 60, miss: 30, fallback: 10 });
    }
    await runBotCacheAlert(env, NOW);
    const state = await _readBotCacheAlertStateForTests(env.RATE_LIMIT as unknown as KVNamespace);
    expect(state.last_evaluated_at).toBe(NOW.toISOString());
    expect(state.last_baseline_hit_rate).toBeCloseTo(0.8, 2);
    expect(state.last_recent_hit_rate).toBeCloseTo(0.6, 2);
    expect(state.last_recent_fallback_rate).toBeCloseTo(0.1, 2);
  });

  it("clamps BOT_CACHE_ALERT_WINDOW_BUCKETS so two adjacent windows fit in the rolling hour", async () => {
    // The rolling hour is 12 buckets; max valid window is 6. Setting 20
    // would silently make baseline and recent overlap. We clamp to 6.
    const env = baseEnv({ BOT_CACHE_ALERT_WINDOW_BUCKETS: "20" });
    for (let off = 0; off < 12; off++) {
      await seedBucket(env.RATE_LIMIT, NOW_MS, off, { hit: 100 });
    }
    const res = await runBotCacheAlert(env, NOW);
    // 6 buckets * 100 hits = 600 sample on each side.
    expect(res.recent_sample).toBe(600);
    expect(res.baseline_sample).toBe(600);
  });

  it("uses the documented defaults", () => {
    expect(_BOT_CACHE_ALERT_DEFAULTS.DROP_PCT).toBe(30);
    expect(_BOT_CACHE_ALERT_DEFAULTS.FALLBACK_PCT).toBe(10);
    expect(_BOT_CACHE_ALERT_DEFAULTS.MIN_SAMPLE).toBe(20);
    expect(_BOT_CACHE_ALERT_DEFAULTS.WINDOW_BUCKETS).toBe(3);
    expect(_BOT_CACHE_ALERT_DEFAULTS.COOLDOWN_MS).toBe(15 * 60 * 1000);
    // Sanity: window default × bucket size = 15 min as documented.
    expect(_BOT_CACHE_ALERT_DEFAULTS.WINDOW_BUCKETS * BOT_CACHE_BUCKET_MS / 60_000).toBe(15);
    // Use _BOT_CACHE_ALERT_STATE_KEY so unused-export lints don't trip.
    expect(_BOT_CACHE_ALERT_STATE_KEY).toBe("bot_cache_alert:state");
  });
});
