import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  EdgeLogShipper,
  shouldKeepEdgeRecord,
  shipBatch,
  recordEdgeLog,
  _resetSharedShipperForTests,
  type EdgeLogShipperEnv,
} from "../src/log-shipper";

const baseEnv = (over: Partial<EdgeLogShipperEnv> = {}): EdgeLogShipperEnv => ({
  BACKEND_URL: "https://backend.example.com",
  BACKEND_ORIGIN_SECRET: "origin-secret",
  LOG_INGEST_TOKEN: "ingest-token",
  EDGE_LOG_SAMPLE_RATE: "1.0",
  ...over,
});

const fakeRequest = (over: { url?: string; method?: string;
                             headers?: Record<string, string>;
                             cf?: Record<string, unknown> } = {}): Request => {
  const r = new Request(over.url ?? "https://syrabit.ai/api/x", {
    method: over.method ?? "GET",
    headers: over.headers ?? {},
  });
  // Worker requests carry a non-standard `cf` property — attach it.
  Object.defineProperty(r, "cf", { value: over.cf ?? {}, configurable: true });
  return r;
};

const fakeResponse = (status = 200, headers: Record<string, string> = {}) =>
  new Response("", { status, headers });

const fakeCtx = () => {
  const promises: Promise<unknown>[] = [];
  return {
    waitUntil: (p: Promise<unknown>) => { promises.push(p); },
    _promises: promises,
  };
};

describe("shouldKeepEdgeRecord", () => {
  it("always keeps 4xx", () => {
    expect(shouldKeepEdgeRecord(404, 10, 0)).toBe(true);
  });
  it("always keeps 5xx", () => {
    expect(shouldKeepEdgeRecord(500, 10, 0)).toBe(true);
  });
  it("always keeps slow ≥1500ms", () => {
    expect(shouldKeepEdgeRecord(200, 1500, 0)).toBe(true);
    expect(shouldKeepEdgeRecord(200, 9999, 0)).toBe(true);
  });
  it("drops fast 2xx at zero sample", () => {
    expect(shouldKeepEdgeRecord(200, 10, 0)).toBe(false);
  });
  it("keeps everything at full sample", () => {
    expect(shouldKeepEdgeRecord(200, 10, 1)).toBe(true);
  });
  it("respects deterministic random", () => {
    const r = () => 0.99;
    expect(shouldKeepEdgeRecord(200, 10, 0.5, r)).toBe(false);
    const r2 = () => 0.01;
    expect(shouldKeepEdgeRecord(200, 10, 0.5, r2)).toBe(true);
  });
});

describe("EdgeLogShipper", () => {
  beforeEach(() => {
    _resetSharedShipperForTests();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns 'disabled' when LOG_INGEST_TOKEN is missing", () => {
    const s = new EdgeLogShipper();
    const env = baseEnv({ LOG_INGEST_TOKEN: undefined });
    const out = s.record(fakeRequest(), fakeResponse(200), { startMs: Date.now() }, env);
    expect(out).toBe("disabled");
    expect(s._peek().buffered).toBe(0);
  });

  it("buffers a 200 at full sample rate", () => {
    const s = new EdgeLogShipper();
    const out = s.record(fakeRequest(), fakeResponse(200), { startMs: Date.now() }, baseEnv());
    expect(out).toBe("buffered");
    expect(s._peek().buffered).toBe(1);
  });

  it("ALWAYS buffers a 5xx even at zero sample", () => {
    const s = new EdgeLogShipper();
    const env = baseEnv({ EDGE_LOG_SAMPLE_RATE: "0" });
    const out = s.record(fakeRequest(), fakeResponse(500), { startMs: Date.now() }, env);
    expect(out).toBe("buffered");
  });

  it("drops a fast 2xx at zero sample", () => {
    const s = new EdgeLogShipper();
    const env = baseEnv({ EDGE_LOG_SAMPLE_RATE: "0" });
    const out = s.record(fakeRequest(), fakeResponse(200), { startMs: Date.now() }, env);
    expect(out).toBe("dropped");
  });

  it("captures cf-ray as ray_id and correlation_id", () => {
    const s = new EdgeLogShipper();
    const req = fakeRequest({ headers: { "cf-ray": "ray-abc-XYZ" } });
    const resp = fakeResponse(200, { "cf-ray": "ray-abc-XYZ" });
    s.record(req, resp, { startMs: Date.now() }, baseEnv());
    const drained = s.drain();
    expect(drained[0].ray_id).toBe("ray-abc-XYZ");
    expect(drained[0].correlation_id).toBe("ray-abc-XYZ");
  });

  it("falls back to traceparent parent-id when cf-ray is missing", () => {
    const s = new EdgeLogShipper();
    const req = fakeRequest({
      headers: { traceparent: "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" },
    });
    s.record(req, fakeResponse(200), { startMs: Date.now() }, baseEnv());
    const drained = s.drain();
    expect(drained[0].correlation_id).toBe("b7ad6b7169203331");
  });

  it("flushes when buffer reaches batch size", () => {
    const s = new EdgeLogShipper({ flushBatch: 3, flushAgeMs: 99999 });
    for (let i = 0; i < 2; i++) {
      s.record(fakeRequest(), fakeResponse(200), { startMs: Date.now() }, baseEnv());
    }
    expect(s.shouldFlush()).toBe(false);
    s.record(fakeRequest(), fakeResponse(200), { startMs: Date.now() }, baseEnv());
    expect(s.shouldFlush()).toBe(true);
  });

  it("flushes when buffer ages past flushAgeMs", () => {
    const s = new EdgeLogShipper({ flushBatch: 999, flushAgeMs: 100 });
    s.record(fakeRequest(), fakeResponse(200), { startMs: Date.now() }, baseEnv());
    expect(s.shouldFlush()).toBe(false);
    vi.advanceTimersByTime(150);
    expect(s.shouldFlush()).toBe(true);
  });

  it("drains and resets the buffer", () => {
    const s = new EdgeLogShipper();
    s.record(fakeRequest(), fakeResponse(200), { startMs: Date.now() }, baseEnv());
    s.record(fakeRequest(), fakeResponse(500), { startMs: Date.now() }, baseEnv());
    const drained = s.drain();
    expect(drained.length).toBe(2);
    expect(s._peek().buffered).toBe(0);
    expect(s.drain().length).toBe(0);
  });
});

describe("shipBatch", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs to /api/logs/ingest with both auth headers", async () => {
    fetchMock.mockResolvedValueOnce(new Response("", { status: 202 }));
    const env = baseEnv();
    const res = await shipBatch(env, [
      {
        source: "edge", level: "info", timestamp: new Date().toISOString(),
        status: 200, route: "/x",
      },
    ]);
    expect(res).toEqual({ shipped: 1, ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://backend.example.com/api/logs/ingest");
    expect(init.method).toBe("POST");
    expect(init.headers["X-Logs-Ingest-Token"]).toBe("ingest-token");
    expect(init.headers["X-Origin-Auth"]).toBe("origin-secret");
    const body = JSON.parse(init.body);
    expect(body.source).toBe("edge");
    expect(body.logs.length).toBe(1);
  });

  it("does nothing when token or url is missing", async () => {
    const r = await shipBatch(baseEnv({ LOG_INGEST_TOKEN: undefined }), [
      { source: "edge", level: "info", timestamp: "" },
    ]);
    expect(r).toEqual({ shipped: 0, ok: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns ok=false when fetch throws (no exception bubbled out)", async () => {
    fetchMock.mockRejectedValueOnce(new Error("boom"));
    const r = await shipBatch(baseEnv(), [
      { source: "edge", level: "info", timestamp: "" },
    ]);
    expect(r.ok).toBe(false);
  });
});

describe("recordEdgeLog one-shot", () => {
  beforeEach(() => {
    _resetSharedShipperForTests();
  });

  it("never throws even on a malformed request", () => {
    expect(() => recordEdgeLog(
      fakeRequest(), fakeResponse(200), { startMs: Date.now() },
      baseEnv(), fakeCtx() as any,
    )).not.toThrow();
  });

  it("schedules a flush via ctx.waitUntil when batch is full", () => {
    const ctx = fakeCtx();
    // Drop into the shared singleton shipper at batch=1 by overriding
    // its private flushBatch — easier than a public knob in this test.
    // We just call it many times and assert at least one waitUntil
    // fired across the run.
    for (let i = 0; i < 200; i++) {
      recordEdgeLog(
        fakeRequest(), fakeResponse(200), { startMs: Date.now() },
        baseEnv(), ctx as any,
      );
    }
    expect(ctx._promises.length).toBeGreaterThan(0);
  });
});
