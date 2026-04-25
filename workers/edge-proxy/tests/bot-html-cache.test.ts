import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import workerHandler, { handleBotContentRequest } from "../src/index";
import { _resetMonitorStateForTests } from "../src/kv-monitor";

const CONTENT_PATH = "/ahsec/class-12/physics/electric-field";
const BACKEND_LM = "Mon, 13 Apr 2026 09:00:00 GMT";
const RENDERED_HTML = "<html><body>" + "x".repeat(800) + "</body></html>";

interface KvEntry {
  value: string;
  expiresAt: number | null;
}

function makeExpiringKv() {
  const store = new Map<string, KvEntry>();
  const putSpy = vi.fn();
  const api = {
    store,
    putSpy,
    async get(k: string): Promise<string | null> {
      const e = store.get(k);
      if (!e) return null;
      if (e.expiresAt !== null && Date.now() >= e.expiresAt) {
        store.delete(k);
        return null;
      }
      return e.value;
    },
    async put(
      k: string,
      v: string,
      opts?: { expirationTtl?: number },
    ): Promise<void> {
      putSpy(k, v, opts);
      const ttlSec = opts?.expirationTtl;
      const expiresAt =
        typeof ttlSec === "number" && ttlSec > 0
          ? Date.now() + ttlSec * 1000
          : null;
      store.set(k, { value: v, expiresAt });
    },
    async delete(k: string): Promise<void> {
      store.delete(k);
    },
    async list() {
      return {
        keys: Array.from(store.keys()).map((name) => ({ name })),
        list_complete: true,
      };
    },
  };
  return api;
}

type Kv = ReturnType<typeof makeExpiringKv>;

function makeEnv(opts: { botCache?: Kv | null; rateLimit?: Kv } = {}) {
  const botCache =
    opts.botCache === null ? undefined : (opts.botCache ?? makeExpiringKv());
  const rateLimit = opts.rateLimit ?? makeExpiringKv();
  return {
    BACKEND_URL: "https://backend.test",
    PAGES_ORIGIN: "https://pages.test",
    RATE_LIMIT: rateLimit as unknown,
    BOT_HTML_CACHE: botCache as unknown,
    CONTENT_DB: undefined as unknown,
    D1_SYNC_SECRET: "secret",
  } as unknown as Parameters<typeof workerHandler.fetch>[1];
}

const ctxNoop = {
  waitUntil: (p: Promise<unknown>) => {
    void p;
  },
  passThroughOnException: () => {},
} as unknown as ExecutionContext;

/**
 * Build a Request that mocks past `verifySearchBot` by attaching
 * `cf.verifiedBot=true`. This is the in-isolate moral equivalent of
 * what the Cloudflare edge sets for a real, address-confirmed
 * Googlebot — without it, the bot branch would be skipped.
 */
function botRequest(
  path: string,
  extraHeaders: Record<string, string> = {},
  cfOverrides: Record<string, unknown> = {},
): Request {
  const req = new Request(`https://syrabit.ai${path}`, {
    headers: {
      "user-agent": "Googlebot/2.1",
      "CF-Connecting-IP": "66.249.66.1",
      ...extraHeaders,
    },
  });
  Object.defineProperty(req, "cf", {
    value: { verifiedBot: true, colo: "test", ...cfOverrides },
    configurable: true,
    writable: true,
  });
  return req;
}

function installRenderedFetch() {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation((async (input: RequestInfo | URL) => {
      const u = typeof input === "string" ? input : input.toString();
      if (u.startsWith("https://pages.test")) {
        return new Response(
          "<html><body>pages-spa-shell</body></html>",
          {
            status: 200,
            headers: { "Content-Type": "text/html; charset=utf-8" },
          },
        );
      }
      // Default: backend bot-render endpoint.
      return new Response(RENDERED_HTML, {
        status: 200,
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Last-Modified": BACKEND_LM,
        },
      });
    }) as typeof fetch);
}

describe("BOT_HTML_CACHE end-to-end via worker.fetch (verifiedBot=true)", () => {
  let fetchSpy: ReturnType<typeof installRenderedFetch>;

  beforeEach(() => {
    // Each test starts with a clean kv-monitor isolate state so the
    // module-level counters from earlier tests can't push us across the
    // proactive-fallback threshold and short-circuit a real KV write.
    _resetMonitorStateForTests();
    fetchSpy = installRenderedFetch();
  });

  afterEach(() => {
    fetchSpy.mockRestore();
    vi.useRealTimers();
  });

  it("cold request: 200 with X-Source bot-prerender(-fallback) and X-Cache BOT-KV-MISS, KV populated", async () => {
    const kv = makeExpiringKv();
    const env = makeEnv({ botCache: kv });

    const resp = await workerHandler.fetch(
      botRequest(CONTENT_PATH),
      env,
      ctxNoop,
    );
    expect(resp.status).toBe(200);
    expect(resp.headers.get("X-Cache")).toBe("BOT-KV-MISS");
    expect(resp.headers.get("X-Source")).toMatch(
      /^bot-prerender(?:-fallback)?$/,
    );
    expect(resp.headers.get("Last-Modified")).toBe(BACKEND_LM);
    expect(resp.headers.get("ETag")).toMatch(/^"[0-9a-f]{12}"$/);
    expect(await resp.text()).toBe(RENDERED_HTML);

    expect(kv.putSpy).toHaveBeenCalledTimes(1);
    const [storedKey, storedValue, storedOpts] = kv.putSpy.mock.calls[0];
    expect(storedKey).toBe(`bot:content:${CONTENT_PATH}`);
    expect(storedOpts?.expirationTtl).toBe(3600);
    const wrapper = JSON.parse(storedValue);
    expect(wrapper.body).toBe(RENDERED_HTML);
    expect(wrapper.lastmod).toBe(BACKEND_LM);
    expect(wrapper.etag).toMatch(/^[0-9a-f]{12}$/);
  });

  it("warm request: identical follow-up returns 200 with X-Source bot-cache and X-Cache BOT-KV-HIT", async () => {
    const kv = makeExpiringKv();
    const env = makeEnv({ botCache: kv });

    const r1 = await workerHandler.fetch(botRequest(CONTENT_PATH), env, ctxNoop);
    expect(r1.headers.get("X-Cache")).toBe("BOT-KV-MISS");
    const coldEtag = r1.headers.get("ETag");
    await r1.text(); // drain body so the spy snapshot below is stable

    const callsBefore = fetchSpy.mock.calls.length;

    const r2 = await workerHandler.fetch(botRequest(CONTENT_PATH), env, ctxNoop);
    expect(r2.status).toBe(200);
    expect(r2.headers.get("X-Source")).toBe("bot-cache");
    expect(r2.headers.get("X-Cache")).toBe("BOT-KV-HIT");
    expect(r2.headers.get("ETag")).toBe(coldEtag);
    expect(r2.headers.get("Last-Modified")).toBe(BACKEND_LM);
    expect(await r2.text()).toBe(RENDERED_HTML);

    // Warm path must not re-fetch from the backend.
    expect(fetchSpy.mock.calls.length).toBe(callsBefore);
    // Warm path must not re-write KV (only the cold request did).
    expect(kv.putSpy).toHaveBeenCalledTimes(1);
  });

  it("conditional GET: matching If-None-Match against the cached etag returns 304 with no body", async () => {
    const kv = makeExpiringKv();
    const env = makeEnv({ botCache: kv });

    const r1 = await workerHandler.fetch(botRequest(CONTENT_PATH), env, ctxNoop);
    const etag = r1.headers.get("ETag")!;
    expect(etag).toMatch(/^"[0-9a-f]{12}"$/);
    await r1.text();

    const r2 = await workerHandler.fetch(
      botRequest(CONTENT_PATH, { "If-None-Match": etag }),
      env,
      ctxNoop,
    );
    expect(r2.status).toBe(304);
    expect(r2.headers.get("ETag")).toBe(etag);
    expect(r2.headers.get("Last-Modified")).toBe(BACKEND_LM);
    expect(r2.headers.get("X-Source")).toBe("bot-cache");
    expect(await r2.text()).toBe("");
  });

  it("non-verified Googlebot UA falls through to Pages-origin proxy without writing BOT_HTML_CACHE", async () => {
    const kv = makeExpiringKv();
    const env = makeEnv({ botCache: kv });

    // Construct a request WITHOUT cf.verifiedBot. clientIp ("9.9.9.9")
    // is not in any verified-bot CIDR range, so verifySearchBot must
    // mark this as spoofed and the worker must skip the bot-cache path.
    const req = new Request(`https://syrabit.ai/about`, {
      headers: {
        "user-agent": "Googlebot/2.1",
        "CF-Connecting-IP": "9.9.9.9",
      },
    });

    const resp = await workerHandler.fetch(req, env, ctxNoop);

    expect(resp.status).toBe(200);
    expect(await resp.text()).toBe("<html><body>pages-spa-shell</body></html>");
    // Worker's own marker must be present (proves it went through the
    // proxy branch, not the bot-cache branch).
    expect(resp.headers.get("X-Edge-Worker")).toBe("syrabit-edge");
    // Critical: the spoofed bot must not have populated BOT_HTML_CACHE.
    expect(kv.putSpy).not.toHaveBeenCalled();
    expect(kv.store.size).toBe(0);
  });

  it("KV entry expires after expirationTtl seconds: a later request misses and re-renders", async () => {
    const kv = makeExpiringKv();
    const env = makeEnv({ botCache: kv });
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-13T09:00:00Z"));

    // The fetch handler's bot path doesn't await ctx.waitUntil, so the
    // KV write is deferred. For deterministic TTL math we drive the
    // KV write directly here via handleBotContentRequest with a ctx
    // that awaits waitUntil promises. The handler is the same code
    // exercised by the worker.fetch path above (cases 1–3) — we're
    // just sequencing the writes synchronously to apply fake timers.
    const writes: Promise<unknown>[] = [];
    const ctxAwait = {
      waitUntil: (p: Promise<unknown>) => {
        writes.push(p);
      },
      passThroughOnException: () => {},
    } as unknown as ExecutionContext;

    const r1 = await handleBotContentRequest(
      env as unknown as Parameters<typeof handleBotContentRequest>[0],
      CONTENT_PATH,
      "66.249.66.1",
      botRequest(CONTENT_PATH),
      ctxAwait,
    );
    await Promise.all(writes.splice(0));
    expect(r1!.headers.get("X-Cache")).toBe("BOT-KV-MISS");
    expect(kv.putSpy).toHaveBeenCalledTimes(1);
    const ttlSec = kv.putSpy.mock.calls[0][2]!.expirationTtl as number;
    expect(ttlSec).toBe(3600);

    // Just before the TTL elapses we still get a hit.
    vi.setSystemTime(Date.now() + (ttlSec - 1) * 1000);
    const r2 = await handleBotContentRequest(
      env as unknown as Parameters<typeof handleBotContentRequest>[0],
      CONTENT_PATH,
      "66.249.66.1",
      botRequest(CONTENT_PATH),
      ctxAwait,
    );
    await Promise.all(writes.splice(0));
    expect(r2!.headers.get("X-Cache")).toBe("BOT-KV-HIT");
    expect(kv.putSpy).toHaveBeenCalledTimes(1);

    // Step past the expiry window — KV mock evicts the entry, so the
    // request must miss and re-render through the backend.
    vi.setSystemTime(Date.now() + 2 * 1000);
    const r3 = await handleBotContentRequest(
      env as unknown as Parameters<typeof handleBotContentRequest>[0],
      CONTENT_PATH,
      "66.249.66.1",
      botRequest(CONTENT_PATH),
      ctxAwait,
    );
    await Promise.all(writes.splice(0));
    expect(r3!.headers.get("X-Cache")).toBe("BOT-KV-MISS");
    expect(r3!.headers.get("X-Source")).toMatch(
      /^bot-prerender(?:-fallback)?$/,
    );
    expect(kv.putSpy).toHaveBeenCalledTimes(2);
  });
});
