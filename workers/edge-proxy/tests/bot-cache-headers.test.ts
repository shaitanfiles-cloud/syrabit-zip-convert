import { describe, it, expect } from "vitest";
import {
  formatRfc7231,
  parseHttpDate,
  computeEtag,
  parseBotCacheEntry,
  ifNoneMatchMatches,
  shouldReturn304,
} from "../src/index";

describe("formatRfc7231", () => {
  it("formats a UTC date as RFC 7231 GMT string", () => {
    const d = new Date(Date.UTC(2026, 3, 16, 12, 30, 45));
    const s = formatRfc7231(d);
    expect(s).toBe("Thu, 16 Apr 2026 12:30:45 GMT");
  });
});

describe("parseHttpDate", () => {
  it("parses RFC 7231 GMT dates Googlebot uses", () => {
    const ms = parseHttpDate("Thu, 16 Apr 2026 12:30:45 GMT");
    expect(ms).toBe(Date.UTC(2026, 3, 16, 12, 30, 45));
  });
  it("returns null for null/empty/garbage", () => {
    expect(parseHttpDate(null)).toBeNull();
    expect(parseHttpDate("")).toBeNull();
    expect(parseHttpDate("   ")).toBeNull();
    expect(parseHttpDate("not-a-date")).toBeNull();
  });
  it("trims surrounding whitespace", () => {
    expect(parseHttpDate("  Thu, 16 Apr 2026 12:30:45 GMT  "))
      .toBe(Date.UTC(2026, 3, 16, 12, 30, 45));
  });
});

describe("computeEtag", () => {
  it("returns 12-hex-char sha256 prefix", async () => {
    const tag = await computeEtag("hello world");
    expect(tag).toMatch(/^[0-9a-f]{12}$/);
  });
  it("is stable for identical inputs", async () => {
    const a = await computeEtag("the quick brown fox");
    const b = await computeEtag("the quick brown fox");
    expect(a).toBe(b);
  });
  it("differs for different inputs", async () => {
    const a = await computeEtag("body one");
    const b = await computeEtag("body two");
    expect(a).not.toBe(b);
  });
});

describe("parseBotCacheEntry", () => {
  it("parses a well-formed JSON wrapper", () => {
    const raw = JSON.stringify({ body: "<html/>", lastmod: "now", etag: "abc" });
    const out = parseBotCacheEntry(raw);
    expect(out).toEqual({ body: "<html/>", lastmod: "now", etag: "abc" });
  });
  it("returns null for plain HTML strings (legacy entries)", () => {
    expect(parseBotCacheEntry("<html><body>hi</body></html>")).toBeNull();
  });
  it("returns null for JSON missing required keys", () => {
    expect(parseBotCacheEntry(JSON.stringify({ body: "x" }))).toBeNull();
    expect(parseBotCacheEntry(JSON.stringify({ etag: "x", lastmod: "y" }))).toBeNull();
  });
  it("returns null for null/empty input", () => {
    expect(parseBotCacheEntry(null)).toBeNull();
    expect(parseBotCacheEntry("")).toBeNull();
  });
});

describe("ifNoneMatchMatches", () => {
  it("matches a single quoted etag", () => {
    expect(ifNoneMatchMatches('"abc123def456"', "abc123def456")).toBe(true);
  });
  it("matches a weak (W/) etag", () => {
    expect(ifNoneMatchMatches('W/"abc123def456"', "abc123def456")).toBe(true);
  });
  it("matches inside a comma-separated list", () => {
    expect(ifNoneMatchMatches('"deadbeef", "abc123def456", "feedface"', "abc123def456"))
      .toBe(true);
  });
  it('matches the wildcard "*"', () => {
    expect(ifNoneMatchMatches("*", "abc123def456")).toBe(true);
  });
  it("returns false on mismatch / null / empty", () => {
    expect(ifNoneMatchMatches('"other"', "abc123def456")).toBe(false);
    expect(ifNoneMatchMatches(null, "abc")).toBe(false);
    expect(ifNoneMatchMatches("", "abc")).toBe(false);
  });
});

function _req(headers: Record<string, string>): Request {
  return new Request("https://syrabit.ai/", { headers });
}

describe("shouldReturn304", () => {
  const lastmod = Date.UTC(2026, 3, 10, 0, 0, 0); // Apr 10 2026

  it("returns 304 when If-None-Match matches our etag", () => {
    const req = _req({ "If-None-Match": '"abc123def456"' });
    expect(shouldReturn304(req, "abc123def456", lastmod)).toBe(true);
  });

  it("returns 304 when If-Modified-Since is at or after lastmod", () => {
    const req = _req({ "If-Modified-Since": "Sat, 11 Apr 2026 00:00:00 GMT" });
    expect(shouldReturn304(req, "abc", lastmod)).toBe(true);
    const req2 = _req({ "If-Modified-Since": "Fri, 10 Apr 2026 00:00:00 GMT" });
    expect(shouldReturn304(req2, "abc", lastmod)).toBe(true);
  });

  it("returns 200 when If-Modified-Since is older than lastmod", () => {
    const req = _req({ "If-Modified-Since": "Wed, 08 Apr 2026 00:00:00 GMT" });
    expect(shouldReturn304(req, "abc", lastmod)).toBe(false);
  });

  it("never returns 304 if If-Modified-Since cannot be parsed", () => {
    const req = _req({ "If-Modified-Since": "this is garbage" });
    expect(shouldReturn304(req, "abc", lastmod)).toBe(false);
  });

  it("If-None-Match takes precedence over If-Modified-Since (RFC 7232)", () => {
    // INM does not match → must NOT 304 even though IMS would.
    const req = _req({
      "If-None-Match": '"different"',
      "If-Modified-Since": "Sat, 11 Apr 2026 00:00:00 GMT",
    });
    expect(shouldReturn304(req, "abc123def456", lastmod)).toBe(false);
  });

  it("returns false when neither conditional header is present", () => {
    const req = _req({});
    expect(shouldReturn304(req, "abc", lastmod)).toBe(false);
  });
});

import { handleBotContentRequest } from "../src/index";

function makeKv() {
  const store = new Map<string, string>();
  return {
    store,
    async get(k: string) { return store.get(k) ?? null; },
    async put(k: string, v: string, _opts?: unknown) { store.set(k, v); },
    async delete(k: string) { store.delete(k); },
  };
}

function makeEnv(kv: ReturnType<typeof makeKv>) {
  return {
    BACKEND_URL: "https://backend.test",
    RATE_LIMIT: makeKv() as unknown,
    BOT_HTML_CACHE: kv as unknown,
    CONTENT_DB: {} as unknown,
    D1_SYNC_SECRET: "x",
  } as unknown as Parameters<typeof handleBotContentRequest>[0];
}

const ctxNoop = { waitUntil: (p: Promise<unknown>) => { void p; }, passThroughOnException: () => {} } as unknown as ExecutionContext;

describe("handleBotContentRequest end-to-end", () => {
  const PATH = "/ahsec/class-12/physics/electric-field";
  const FAKE_HTML = "<html>" + "x".repeat(500) + "</html>";
  const BACKEND_LM = "Mon, 13 Apr 2026 09:00:00 GMT";

  function installFetchMock() {
    const orig = globalThis.fetch;
    (globalThis as unknown as { fetch: typeof fetch }).fetch = (async (_url: string) => {
      return new Response(FAKE_HTML, {
        status: 200,
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Last-Modified": BACKEND_LM,
        },
      });
    }) as typeof fetch;
    return () => { (globalThis as unknown as { fetch: typeof fetch }).fetch = orig; };
  }

  it("first request: 200 with backend Last-Modified + ETag, populates KV", async () => {
    const kv = makeKv();
    const env = makeEnv(kv);
    const restore = installFetchMock();
    try {
      const req = new Request(`https://syrabit.ai${PATH}`, { headers: { "user-agent": "Googlebot" } });
      const resp = await handleBotContentRequest(env, PATH, "1.2.3.4", req, ctxNoop);
      expect(resp).not.toBeNull();
      expect(resp!.status).toBe(200);
      expect(resp!.headers.get("Last-Modified")).toBe(BACKEND_LM);
      const etag = resp!.headers.get("ETag");
      expect(etag).toMatch(/^"[0-9a-f]{12}"$/);
      const body = await resp!.text();
      expect(body).toBe(FAKE_HTML);
      // KV populated with the JSON wrapper carrying backend lastmod.
      const kvKeys = Array.from(kv.store.keys());
      expect(kvKeys.length).toBe(1);
      const stored = JSON.parse(kv.store.get(kvKeys[0])!);
      expect(stored.lastmod).toBe(BACKEND_LM);
      expect(stored.body).toBe(FAKE_HTML);
    } finally { restore(); }
  });

  it("repeat request with matching If-None-Match returns 304 with no body", async () => {
    const kv = makeKv();
    const env = makeEnv(kv);
    const restore = installFetchMock();
    try {
      const req1 = new Request(`https://syrabit.ai${PATH}`, { headers: { "user-agent": "Googlebot" } });
      const r1 = await handleBotContentRequest(env, PATH, "1.2.3.4", req1, ctxNoop);
      const etag = r1!.headers.get("ETag")!;

      const req2 = new Request(`https://syrabit.ai${PATH}`, {
        headers: { "user-agent": "Googlebot", "If-None-Match": etag },
      });
      const r2 = await handleBotContentRequest(env, PATH, "1.2.3.4", req2, ctxNoop);
      expect(r2!.status).toBe(304);
      expect(r2!.headers.get("Last-Modified")).toBe(BACKEND_LM);
      expect(r2!.headers.get("ETag")).toBe(etag);
      const body = await r2!.text();
      expect(body).toBe("");
    } finally { restore(); }
  });

  it("repeat request with non-matching If-None-Match returns 200 with body", async () => {
    const kv = makeKv();
    const env = makeEnv(kv);
    const restore = installFetchMock();
    try {
      const req1 = new Request(`https://syrabit.ai${PATH}`, { headers: { "user-agent": "Googlebot" } });
      await handleBotContentRequest(env, PATH, "1.2.3.4", req1, ctxNoop);

      const req2 = new Request(`https://syrabit.ai${PATH}`, {
        headers: { "user-agent": "Googlebot", "If-None-Match": '"deadbeef0000"' },
      });
      const r2 = await handleBotContentRequest(env, PATH, "1.2.3.4", req2, ctxNoop);
      expect(r2!.status).toBe(200);
      const body = await r2!.text();
      expect(body).toBe(FAKE_HTML);
    } finally { restore(); }
  });

  it("If-Modified-Since after backend lastmod returns 304", async () => {
    const kv = makeKv();
    const env = makeEnv(kv);
    const restore = installFetchMock();
    try {
      const req1 = new Request(`https://syrabit.ai${PATH}`, { headers: { "user-agent": "Googlebot" } });
      await handleBotContentRequest(env, PATH, "1.2.3.4", req1, ctxNoop);

      // BACKEND_LM = Mon, 13 Apr 2026 09:00:00 GMT — give IMS one day later.
      const req2 = new Request(`https://syrabit.ai${PATH}`, {
        headers: { "user-agent": "Googlebot", "If-Modified-Since": "Tue, 14 Apr 2026 09:00:00 GMT" },
      });
      const r2 = await handleBotContentRequest(env, PATH, "1.2.3.4", req2, ctxNoop);
      expect(r2!.status).toBe(304);
    } finally { restore(); }
  });
});
