/**
 * rate-limiter-do.ts — Task #109 Phase 5: Durable Object rate limiter.
 *
 * Replaces the KV-based sliding-window rate limiter with strongly-consistent
 * per-key counters. Each DO instance owns a single rate-limit key, so the
 * atomicity guarantee is per-DO — no races between isolates for the same key.
 *
 * API (internal Worker-to-DO):
 *   POST https://rate-limiter/check
 *   Body: { key: string; limit: number; windowMs: number }
 *   Response: { allowed: boolean; remaining: number; retryAfterMs: number }
 *
 * Usage in the edge Worker:
 *   const doId  = env.RATE_LIMITER_DO.idFromName(rateLimitKey);
 *   const stub  = env.RATE_LIMITER_DO.get(doId);
 *   const result = await stub.fetch('https://rate-limiter/check', {
 *     method: 'POST',
 *     body: JSON.stringify({ key, limit, windowMs }),
 *   });
 *   const { allowed, remaining } = await result.json();
 *
 * One DO instance per unique key (e.g. "rl:203.0.113.1", "rl:ai:203.0.113.1").
 * DO instances sleep when idle and wake in ~1 ms — no cold-start latency penalty
 * under prod traffic because the key is hot.
 *
 * Strongly-consistent guarantee:
 *   The transaction() call on DO storage is serialized within a single isolate.
 *   Two concurrent requests to the SAME IP get the SAME DO instance (because
 *   idFromName is deterministic) and their storage.transaction() calls are
 *   serialized by the DO runtime — no double-grant under burst.
 *
 * KV fallback:
 *   The edge Worker's checkRateLimitKey() falls back to KV when RATE_LIMITER_DO
 *   is unbound (i.e. before the bucket is provisioned or during local dev).
 *   This is handled in src/index.ts, not here.
 */

export interface RateLimitRequest {
  key: string;
  limit: number;
  windowMs: number;
}

export interface RateLimitResponse {
  allowed: boolean;
  remaining: number;
  /** milliseconds until the oldest in-window timestamp expires */
  retryAfterMs: number;
}

export class RateLimiter implements DurableObject {
  private readonly state: DurableObjectState;

  constructor(state: DurableObjectState) {
    this.state = state;
  }

  async fetch(request: Request): Promise<Response> {
    if (request.method !== "POST") {
      return new Response(JSON.stringify({ error: "POST only" }), { status: 405 });
    }

    let body: RateLimitRequest;
    try {
      body = await request.json<RateLimitRequest>();
    } catch {
      return new Response(JSON.stringify({ error: "invalid JSON body" }), { status: 400 });
    }

    const { key, limit, windowMs } = body;
    if (!key || !limit || !windowMs) {
      return new Response(
        JSON.stringify({ error: "key, limit, and windowMs are required" }),
        { status: 400 },
      );
    }

    const result = await this.state.storage.transaction<RateLimitResponse>(async (txn) => {
      const now        = Date.now();
      const windowStart = now - windowMs;
      const stored     = (await txn.get<number[]>(`ts:${key}`)) ?? [];
      // Prune timestamps outside the current window
      const valid      = stored.filter((t) => t > windowStart);

      if (valid.length >= limit) {
        // Oldest timestamp drives the retry-after
        const retryAfterMs = valid.length > 0 ? windowMs - (now - valid[0]) : windowMs;
        return { allowed: false, remaining: 0, retryAfterMs: Math.max(0, retryAfterMs) };
      }

      valid.push(now);
      // No TTL option on DO storage transactions — expiry is handled by the
      // timestamp pruning on every read (timestamps outside the window are
      // filtered out). The storage key is bounded to at most `limit` entries
      // because we cap at `limit` before pushing. No unbounded growth.
      await txn.put(`ts:${key}`, valid);

      return { allowed: true, remaining: limit - valid.length, retryAfterMs: 0 };
    });

    return new Response(JSON.stringify(result), {
      headers: { "Content-Type": "application/json" },
    });
  }
}
