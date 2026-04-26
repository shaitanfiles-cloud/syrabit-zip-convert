/**
 * Task #944 — Edge worker side of the Unified Log Explorer.
 *
 * The edge worker handles every request before it reaches Cloud Run. We
 * want a single record per request in the admin "Logs" panel that
 * captures:
 *   - status / duration / cache disposition (hit | miss | bypass | dynamic)
 *   - the routing decision (which path the worker matched)
 *   - the CF cf-ray / colo / country
 *   - a correlation id we can chain to the backend's request id when the
 *     worker actually proxies the request
 *
 * Constraints
 * -----------
 * - **Cannot block the user response.** Every record is buffered and
 *   shipped via ``ctx.waitUntil`` so a slow Cloud Run never adds tail
 *   latency to the user.
 * - **Must respect the kill switch.** When ``LOG_INGEST_TOKEN`` is unset,
 *   the shipper is a no-op so a misconfigured deploy can never DOS the
 *   backend. The backend's own ``LOGS_PAUSED`` env var also returns 202
 *   ``paused: true`` so the buffer drains in one round-trip.
 * - **Must always keep errors.** 4xx/5xx and slow (≥1500ms) responses
 *   bypass the sample rate so a regression cannot be silently dropped.
 */

const SAMPLE_KEEP_THRESHOLD_MS = 1500;
const DEFAULT_FLUSH_BATCH = 50;
const DEFAULT_FLUSH_AGE_MS = 1500;
const DEFAULT_SAMPLE_RATE = 0.1;
const MAX_BUFFER = 500;

export type EdgeLogRecord = {
  source: "edge";
  level: "info" | "warn" | "error" | "debug";
  timestamp: string;
  status?: number;
  duration_ms?: number;
  method?: string;
  route?: string;
  country?: string | null;
  colo?: string | null;
  cache?: "hit" | "miss" | "bypass" | "dynamic" | null;
  ray_id?: string | null;
  correlation_id?: string | null;
  user_agent?: string | null;
  message?: string;
  extra?: Record<string, unknown>;
};

export interface EdgeLogShipperEnv {
  BACKEND_URL?: string;
  BACKEND_ORIGIN_SECRET?: string;
  LOG_INGEST_TOKEN?: string;
  EDGE_LOG_SAMPLE_RATE?: string;
  EDGE_LOG_FLUSH_BATCH?: string;
  EDGE_LOG_FLUSH_AGE_MS?: string;
}

export type EdgeLogMeta = {
  /** Wall-clock start of the fetch handler (Date.now()). */
  startMs: number;
  /** What the worker did with this request. */
  cache?: EdgeLogRecord["cache"];
  /** When the worker matched a known route family (e.g. "ai-fallback",
   *  "static", "proxy", "synthetic-probe"), include it so the admin
   *  filter can group requests by handler. */
  route?: string;
  /** Optional message. Defaults to "{method} {path} → {status}". */
  message?: string;
  /** Extra fields the caller wants persisted. */
  extra?: Record<string, unknown>;
  /** Override level (defaults to info / warn-on-4xx / error-on-5xx). */
  level?: EdgeLogRecord["level"];
};

function levelForStatus(status: number | undefined): EdgeLogRecord["level"] {
  if (status === undefined) return "info";
  if (status >= 500) return "error";
  if (status >= 400) return "warn";
  return "info";
}

function parseFloatEnv(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const n = Number.parseFloat(value);
  if (!Number.isFinite(n)) return fallback;
  return n;
}

function parseIntEnv(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n)) return fallback;
  return n;
}

export function shouldKeepEdgeRecord(
  status: number | undefined,
  durationMs: number | undefined,
  sampleRate: number,
  random: () => number = Math.random,
): boolean {
  if (status !== undefined && status >= 400) return true;
  if (durationMs !== undefined && durationMs >= SAMPLE_KEEP_THRESHOLD_MS) return true;
  const rate = Math.max(0, Math.min(1, sampleRate));
  if (rate >= 1) return true;
  if (rate <= 0) return false;
  return random() < rate;
}

/**
 * In-isolate buffer + flusher.
 *
 * A Cloudflare Worker isolate stays alive across many requests, so the
 * buffer is shared between concurrent handlers. We deliberately use a
 * single module-level singleton (``getSharedShipper``) so 50 inbound
 * requests share one outbound POST instead of fanning out one POST
 * per request.
 */
export class EdgeLogShipper {
  private buffer: EdgeLogRecord[] = [];
  private bufferStartedAt: number | null = null;
  private flushBatch: number;
  private flushAgeMs: number;
  /** Test seam — overridden in unit tests via a constructor option. */
  private random: () => number;

  constructor(opts?: { flushBatch?: number; flushAgeMs?: number; random?: () => number }) {
    this.flushBatch = opts?.flushBatch ?? DEFAULT_FLUSH_BATCH;
    this.flushAgeMs = opts?.flushAgeMs ?? DEFAULT_FLUSH_AGE_MS;
    this.random = opts?.random ?? Math.random;
  }

  /**
   * Drop a record into the buffer, applying sampling. Returns
   * ``"buffered" | "dropped" | "disabled"`` so tests can assert on
   * which branch fired.
   */
  record(
    request: Request,
    response: Response,
    meta: EdgeLogMeta,
    env: EdgeLogShipperEnv,
  ): "buffered" | "dropped" | "disabled" {
    if (!env.LOG_INGEST_TOKEN || !env.BACKEND_URL) {
      // Disabled in this environment — silently no-op so a fresh
      // wrangler dev session without secrets does not cascade-fail.
      return "disabled";
    }
    const status = response.status;
    const duration = Math.max(0, Date.now() - meta.startMs);
    const sampleRate = parseFloatEnv(env.EDGE_LOG_SAMPLE_RATE, DEFAULT_SAMPLE_RATE);
    if (!shouldKeepEdgeRecord(status, duration, sampleRate, this.random)) {
      return "dropped";
    }
    const url = new URL(request.url);
    const cf = (request as Request & { cf?: Record<string, unknown> }).cf || {};
    const ray =
      response.headers.get("cf-ray") ||
      request.headers.get("cf-ray") ||
      null;
    const correlation =
      ray ||
      // ``traceparent`` is "00-<trace-id>-<parent-id>-<flags>"; the
      // parent-id is the right id to thread through to the backend.
      ((): string | null => {
        const tp = request.headers.get("traceparent") || "";
        const parts = tp.split("-");
        return parts.length >= 4 ? parts[2] : null;
      })();

    const rec: EdgeLogRecord = {
      source: "edge",
      level: meta.level ?? levelForStatus(status),
      timestamp: new Date().toISOString(),
      status,
      duration_ms: duration,
      method: request.method,
      route: meta.route ?? url.pathname,
      country: (cf.country as string | undefined) ?? null,
      colo: (cf.colo as string | undefined) ?? null,
      cache: meta.cache ?? null,
      ray_id: ray,
      correlation_id: correlation,
      user_agent: (request.headers.get("user-agent") || "").slice(0, 200) || null,
      message:
        meta.message ?? `${request.method} ${url.pathname} → ${status}`,
      extra: meta.extra,
    };

    if (this.buffer.length >= MAX_BUFFER) {
      // Drop oldest to keep the buffer bounded — a runaway shipper
      // must never balloon isolate memory and OOM the worker.
      this.buffer.shift();
    }
    if (this.buffer.length === 0) {
      this.bufferStartedAt = Date.now();
    }
    this.buffer.push(rec);
    return "buffered";
  }

  shouldFlush(): boolean {
    if (this.buffer.length === 0) return false;
    if (this.buffer.length >= this.flushBatch) return true;
    if (this.bufferStartedAt !== null &&
        Date.now() - this.bufferStartedAt >= this.flushAgeMs) {
      return true;
    }
    return false;
  }

  /** Drain the buffer — returns the records the caller should ship. */
  drain(): EdgeLogRecord[] {
    if (this.buffer.length === 0) return [];
    const out = this.buffer;
    this.buffer = [];
    this.bufferStartedAt = null;
    return out;
  }

  /**
   * Convenience wrapper: drain + POST. Intended to be passed to
   * ``ctx.waitUntil`` so the user response is not blocked.
   */
  async flush(env: EdgeLogShipperEnv): Promise<{ shipped: number; ok: boolean }> {
    const batch = this.drain();
    if (batch.length === 0) return { shipped: 0, ok: true };
    return shipBatch(env, batch);
  }

  /** Test-only inspector. */
  _peek(): { buffered: number; startedAt: number | null } {
    return { buffered: this.buffer.length, startedAt: this.bufferStartedAt };
  }
}

let _SHARED: EdgeLogShipper | null = null;
export function getSharedShipper(): EdgeLogShipper {
  if (_SHARED === null) {
    _SHARED = new EdgeLogShipper();
  }
  return _SHARED;
}
export function _resetSharedShipperForTests(): void {
  _SHARED = null;
}

export async function shipBatch(
  env: EdgeLogShipperEnv,
  batch: EdgeLogRecord[],
): Promise<{ shipped: number; ok: boolean }> {
  if (!env.LOG_INGEST_TOKEN || !env.BACKEND_URL || batch.length === 0) {
    return { shipped: 0, ok: false };
  }
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Logs-Ingest-Token": env.LOG_INGEST_TOKEN,
  };
  if (env.BACKEND_ORIGIN_SECRET) {
    headers["X-Origin-Auth"] = env.BACKEND_ORIGIN_SECRET;
  }
  try {
    const resp = await fetch(`${env.BACKEND_URL}/api/logs/ingest`, {
      method: "POST",
      headers,
      body: JSON.stringify({ source: "edge", logs: batch }),
    });
    return { shipped: batch.length, ok: resp.ok };
  } catch {
    return { shipped: 0, ok: false };
  }
}

/**
 * One-shot helper used at every return path of the worker's ``fetch``
 * handler. Records the request + flushes when the buffer is ready —
 * both wrapped in ``ctx.waitUntil`` so neither the buffer write nor
 * the POST can extend user-perceived latency.
 */
export function recordEdgeLog(
  request: Request,
  response: Response,
  meta: EdgeLogMeta,
  env: EdgeLogShipperEnv,
  ctx: { waitUntil(promise: Promise<unknown>): void },
): void {
  try {
    const shipper = getSharedShipper();
    shipper.record(request, response, meta, env);
    if (shipper.shouldFlush()) {
      ctx.waitUntil(shipper.flush(env));
    }
  } catch {
    // Never let logging break the response.
  }
}
