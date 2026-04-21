import {
  isD1Synced, resetD1SyncedCache, isTablePopulated,
  getBoards, getClasses, getStreams, getAllSubjects, getSubjectsByStream,
  getSubjectsByClassId, getSubjectById, getChaptersBySubject,
  getTopicsByChapter, getSitemapEntries, getLibraryBundle, getLibraryBundleSlim,
  getSeoPageBySlugs, getSeoPageTypes, getSeoPageBundle,
  getSeoPagesByType, getPublishedPageTypes,
  getSubjectSitemapEntries, getChapterSitemapEntries,
} from "./d1-queries";
import { syncFromPayload, getSyncStatus } from "./d1-sync";
import {
  wrapKvNamespace,
  getUsageSnapshot,
  getUsageSnapshotAggregated,
  type WrapKvOptions,
  type KvUsageQuota,
} from "./kv-monitor";

interface Env {
  BACKEND_URL: string;
  PAGES_ORIGIN?: string;
  RATE_LIMIT: KVNamespace;
  BOT_HTML_CACHE?: KVNamespace;
  CONTENT_DB: D1Database;
  D1_SYNC_SECRET: string;
  /** Secret shared with the FastAPI backend for /admin/kv-alerts. */
  KV_ALERT_SECRET?: string;
  /** Override warning threshold (percentage of quota). Defaults to 80. */
  KV_WARNING_PCT?: string;
  /** Override per-op daily quotas as a JSON string. */
  KV_QUOTA?: string;
  /**
   * Task #606: Shared secret injected as `X-Origin-Auth` on every backend
   * fetch when the worker is forwarding to a Cloud Run origin. The Cloud
   * Run service rejects requests without it (see
   * `OriginSharedSecretMiddleware` in artifacts/syrabit-backend/middleware.py).
   * Set via `wrangler secret put BACKEND_ORIGIN_SECRET`. Leave unset for
   * non-Cloud-Run backends — the worker just skips the header.
   */
  BACKEND_ORIGIN_SECRET?: string;
  /**
   * Task #636 — Workers AI binding for the auto-fallback fan-out. The
   * routes in `handleAiFallback` call `env.AI.run(model, payload)` only
   * after the FastAPI backend has decided its primary provider failed
   * with a retryable error. The binding is omitted in `wrangler dev`
   * unless --remote or [ai] is configured; routes return 503 in that
   * case so the backend just propagates the original primary error.
   */
  AI?: { run(model: string, payload: unknown): Promise<unknown> };
  /**
   * Shared secret with the FastAPI backend, sent as `X-Edge-AI-Secret`
   * on every /api/ai/fallback/* call. Without it the routes 401.
   */
  EDGE_AI_FALLBACK_SECRET?: string;
}

const KV_BINDINGS = ["RATE_LIMIT", "BOT_HTML_CACHE"] as const;

function buildKvMonitorOpts(env: Env, ctx: ExecutionContext): WrapKvOptions {
  let quota: Partial<KvUsageQuota> | undefined;
  if (env.KV_QUOTA) {
    try { quota = JSON.parse(env.KV_QUOTA); } catch { /* ignore malformed override */ }
  }
  let warningPct: number | undefined;
  if (env.KV_WARNING_PCT) {
    const n = Number(env.KV_WARNING_PCT);
    if (Number.isFinite(n) && n > 0 && n <= 100) warningPct = n;
  }
  return {
    backendUrl: env.BACKEND_URL,
    alertSecret: env.KV_ALERT_SECRET,
    warningPct,
    quota,
    ctx,
  };
}

function wrapEnvKv(env: Env, ctx: ExecutionContext): Env {
  const opts = buildKvMonitorOpts(env, ctx);
  // Idempotent: only wrap actual `KVNamespace` instances. The wrapper
  // uses module-scoped counters keyed by binding name, so re-wrapping
  // across requests is safe and cheap.
  const wrapped: Env = { ...env };
  if (env.RATE_LIMIT) {
    wrapped.RATE_LIMIT = wrapKvNamespace(env.RATE_LIMIT, "RATE_LIMIT", opts);
  }
  if (env.BOT_HTML_CACHE) {
    wrapped.BOT_HTML_CACHE = wrapKvNamespace(env.BOT_HTML_CACHE, "BOT_HTML_CACHE", opts);
  }
  return wrapped;
}

async function handleKvUsage(env: Env, request: Request, cors: Record<string, string>): Promise<Response> {
  const provided = request.headers.get("X-Edge-Admin-Secret") || "";
  if (!env.D1_SYNC_SECRET || provided !== env.D1_SYNC_SECRET) {
    return new Response(JSON.stringify({ detail: "Unauthorized" }), {
      status: 401,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }
  // Use the aggregated snapshot so the dashboard shows global Worker
  // usage (sum across all isolates that have flushed to the shared
  // `__kv_usage:*` keys), not just this isolate's slice.
  const opts = buildKvMonitorOpts(env, {
    waitUntil: () => undefined,
    passThroughOnException: () => undefined,
  } as unknown as ExecutionContext);
  const bindingArgs: Array<{ binding: string; kv: KVNamespace }> = [];
  // NOTE: env was already wrapped by `wrapEnvKv` for the request, but
  // the underlying KV bindings on the original env object are what we
  // want for the shared-store reads/writes (so they don't recurse
  // through the monitor wrapper). The wrapper does not mutate the
  // original env, so we'd have to access the raw bindings — but here
  // env is the WRAPPED env. Calling list/get on the wrapper still
  // works; the wrapper just counts them too (a small, predictable
  // overhead for the snapshot endpoint).
  if (env.RATE_LIMIT) bindingArgs.push({ binding: "RATE_LIMIT", kv: env.RATE_LIMIT });
  if (env.BOT_HTML_CACHE) bindingArgs.push({ binding: "BOT_HTML_CACHE", kv: env.BOT_HTML_CACHE });
  let snapshot;
  try {
    snapshot = await getUsageSnapshotAggregated(bindingArgs, opts);
  } catch {
    snapshot = getUsageSnapshot([...KV_BINDINGS], opts);
  }
  return new Response(JSON.stringify(snapshot), {
    status: 200,
    headers: {
      ...cors,
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "X-Source": "edge-kv-monitor",
    },
  });
}

interface D1Database {
  prepare(query: string): D1PreparedStatement;
  batch<T = unknown>(statements: D1PreparedStatement[]): Promise<D1Result<T>[]>;
  exec(query: string): Promise<D1ExecResult>;
}
interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  first<T = unknown>(colName?: string): Promise<T | null>;
  run<T = unknown>(): Promise<D1Result<T>>;
  all<T = unknown>(): Promise<D1Result<T>>;
  raw<T = unknown[]>(options?: { columnNames?: boolean }): Promise<T[]>;
}
interface D1Result<T = unknown> { results: T[]; success: boolean; meta: object }
interface D1ExecResult { count: number; duration: number }


const ALLOWED_ORIGINS = [
  "https://syrabit.ai",
  "https://www.syrabit.ai",
  "https://api.syrabit.ai",
];

const CACHEABLE_PREFIXES = [
  "/api/content/boards",
  "/api/content/classes",
  "/api/content/streams",
  "/api/content/subjects",
  "/api/content/chapters/",
  "/api/content/chunks/",
  "/api/content/chapter-by-slug/",
  "/api/content/library-bundle",
  "/api/content/topic/",
  "/api/seo/",
  "/api/pyq/",
  "/api/sitemap",
  "/api/robots.txt",
  "/api/notes/public",
  "/api/mcq/",
  "/api/user/stats",
  "/api/cms/articles",
  "/api/flashcards/",
  "/api/content/syllabus/",
  "/api/edu/allowlist",
];

const CACHE_TTL: Record<string, number> = {
  "/api/content/boards": 3600,
  "/api/content/classes": 3600,
  "/api/content/streams": 3600,
  "/api/content/subjects": 3600,
  "/api/content/chapters/": 3600,
  "/api/content/chunks/": 3600,
  "/api/content/library-bundle": 300,
  "/api/content/chapter-by-slug/": 3600,
  "/api/content/topic/": 3600,
  "/api/content/syllabus/": 3600,
  "/api/seo/keyword-index": 3600,
  "/api/seo/": 600,
  "/api/pyq/": 3600,
  "/api/notes/public": 3600,
  "/api/mcq/": 3600,
  "/api/user/stats": 900,
  "/api/cms/articles": 900,
  "/api/flashcards/": 3600,
  "/api/sitemap": 86400,
  "/api/robots.txt": 86400,
  "/api/edu/allowlist": 86400,
};

const USER_SPECIFIC_PREFIXES = [
  "/api/user/stats",
];

const BYPASS_PREFIXES = [
  "/api/ai/chat",
  "/api/webhooks",
  "/api/auth",
];

const RATE_LIMIT_RPM = 120;
const BOT_RATE_LIMIT_RPM = 1200;
const RATE_LIMIT_WINDOW_S = 60;

const SEARCH_BOT_UA = /googlebot|google-extended|bingbot|yandexbot|duckduckbot|slurp|applebot|chatgpt-user|oai-searchbot|perplexitybot|claudebot|meta-externalagent/i;

interface CidrRange { network: number; mask: number }

function parseCidr(cidr: string): CidrRange {
  const [ip, bits] = cidr.split("/");
  const p = ip.split(".").map(Number);
  const net = ((p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]) >>> 0;
  const m = bits === "0" ? 0 : (~((1 << (32 - Number(bits))) - 1)) >>> 0;
  return { network: net & m, mask: m };
}

function parseCidrs(cidrs: string[]): CidrRange[] {
  return cidrs.map(parseCidr);
}

function ipInRanges(ip: string, ranges: CidrRange[]): boolean {
  if (ip.includes(":")) return false;
  const p = ip.split(".").map(Number);
  if (p.length !== 4 || p.some((n) => isNaN(n) || n < 0 || n > 255)) return false;
  const ipNum = ((p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3]) >>> 0;
  for (const r of ranges) {
    if ((ipNum & r.mask) === r.network) return true;
  }
  return false;
}

const GOOGLE_BOT_RANGES = parseCidrs([
  "66.249.64.0/19", "66.249.96.0/20",
  "34.100.182.96/28", "34.101.50.144/28", "34.118.254.0/28",
  "34.118.66.0/28", "34.126.178.96/28", "34.146.150.144/28",
  "34.147.110.160/28", "34.151.74.144/28", "34.152.50.64/28",
  "34.154.114.144/28", "34.155.98.32/28", "34.165.18.176/28",
  "34.175.160.64/28", "34.176.130.16/28", "34.22.85.0/27",
  "34.64.82.64/28", "34.65.242.112/28", "34.80.50.80/28",
  "34.88.194.0/28", "34.89.10.80/28", "34.89.198.80/28",
  "34.96.162.48/28", "35.247.243.240/28",
]);

const BING_BOT_RANGES = parseCidrs([
  "157.55.39.0/24", "207.46.13.0/24", "40.77.167.0/24",
  "52.167.144.0/24", "13.66.139.0/24", "13.67.8.0/24",
  "131.253.24.0/22", "131.253.46.0/23", "157.55.16.0/23",
  "157.56.92.0/24", "199.30.24.0/23",
]);

const OPENAI_BOT_RANGES = parseCidrs([
  "23.98.142.176/28", "40.84.180.224/28",
  "20.15.240.64/28", "20.15.240.80/28", "20.15.240.96/28",
  "20.15.240.176/28", "20.15.241.0/28",
  "20.169.232.0/28", "20.171.206.0/28",
  "52.230.152.0/24", "52.233.106.0/24",
]);

const YANDEX_BOT_RANGES = parseCidrs([
  "5.255.253.0/24", "77.88.5.0/24", "77.88.47.0/24",
  "87.250.224.0/19", "93.158.161.0/24", "95.108.128.0/17",
  "100.43.80.0/24", "141.8.153.0/24", "178.154.128.0/17",
  "199.21.99.0/24", "213.180.192.0/19",
]);

const APPLE_BOT_RANGES = parseCidrs([
  "17.0.0.0/8",
]);

const BOT_UA_RANGES: Array<[RegExp, CidrRange[]]> = [
  [/googlebot|google-extended|googleother/i, GOOGLE_BOT_RANGES],
  [/bingbot/i, BING_BOT_RANGES],
  [/duckduckbot/i, BING_BOT_RANGES],
  [/chatgpt-user|oai-searchbot/i, OPENAI_BOT_RANGES],
  [/yandexbot/i, YANDEX_BOT_RANGES],
  [/applebot/i, APPLE_BOT_RANGES],
];

interface BotVerifyResult {
  verified: boolean;
  claimsBot: boolean;
  spoofed: boolean;
}

function hashIp(ip: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < ip.length; i++) {
    h ^= ip.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(16).padStart(8, "0");
}

function verifySearchBot(ua: string, request: Request, clientIp: string): BotVerifyResult {
  if (!SEARCH_BOT_UA.test(ua)) return { verified: false, claimsBot: false, spoofed: false };
  const cf = (request as unknown as { cf?: { verifiedBot?: boolean } }).cf;
  if (cf && cf.verifiedBot === true) return { verified: true, claimsBot: true, spoofed: false };
  for (const [pattern, ranges] of BOT_UA_RANGES) {
    if (pattern.test(ua)) {
      const matched = ipInRanges(clientIp, ranges);
      return { verified: matched, claimsBot: true, spoofed: !matched };
    }
  }
  return { verified: false, claimsBot: true, spoofed: true };
}

async function logSpoofedBot(
  kv: KVNamespace,
  ipHash: string,
  ua: string,
  clientIp: string,
  colo: string,
): Promise<void> {
  const now = Date.now();
  const windowKey = `spoof:count:${Math.floor(now / 60000)}`;
  try {
    const raw = await kv.get(windowKey);
    const count = raw ? parseInt(raw, 10) + 1 : 1;
    await kv.put(windowKey, String(count), { expirationTtl: 3600 });

    if (count === 50 || count === 200 || count === 500) {
      console.warn(
        `SPOOF_ALERT threshold=${count}/min | ` +
        `window=${new Date(Math.floor(now / 60000) * 60000).toISOString()}`
      );
    }
  } catch {}

  const botMatch = ua.match(SEARCH_BOT_UA);
  const claimedBot = botMatch ? botMatch[0].toLowerCase() : "unknown";
  console.log(
    `SPOOFED_BOT ip_hash=${ipHash} claimed=${claimedBot} ` +
    `ua="${ua.slice(0, 150)}" colo=${colo} ts=${new Date(now).toISOString()}`
  );
}

function isVerifiedSearchBot(ua: string, request: Request, clientIp: string): boolean {
  return verifySearchBot(ua, request, clientIp).verified;
}

const BASE_URL = "https://syrabit.ai";
const STATIC_PAGES: Array<[string, string, string]> = [
  ["/home", "weekly", "1.0"],
  ["/about", "monthly", "0.9"],
  ["/pricing", "monthly", "0.8"],
  ["/library", "weekly", "0.9"],
  ["/curriculum", "weekly", "0.8"],
  ["/exam-routine", "weekly", "0.8"],
  ["/terms", "yearly", "0.3"],
  ["/privacy", "yearly", "0.3"],
];
const ALL_PAGE_TYPES = ["notes", "mcqs", "important-questions", "examples", "definition", "faq"];
const SITEMAP_TYPES = ["notes", "mcqs", "important-questions", "examples", "definition", "faq"];

function getCorsHeaders(origin: string | null): Record<string, string> | null {
  if (!origin || !ALLOWED_ORIGINS.includes(origin)) return null;
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept, Origin, X-Requested-With, x-anon-id, x-turnstile-token, traceparent, tracestate, baggage",
    "Access-Control-Expose-Headers": "X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After, X-Request-Id, X-Source",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Max-Age": "600",
  };
}

function safeCorsHeaders(origin: string | null): Record<string, string> {
  return getCorsHeaders(origin) || {};
}

function getCacheTtl(pathname: string): number {
  for (const [prefix, ttl] of Object.entries(CACHE_TTL)) {
    if (pathname.startsWith(prefix)) return ttl;
  }
  return 300;
}

function isCacheable(pathname: string): boolean {
  return CACHEABLE_PREFIXES.some((p) => pathname.startsWith(p));
}

function isBypass(pathname: string): boolean {
  return BYPASS_PREFIXES.some((p) => pathname.startsWith(p));
}

function isUserSpecific(pathname: string): boolean {
  return USER_SPECIFIC_PREFIXES.some((p) => pathname.startsWith(p));
}

async function checkRateLimit(
  ip: string,
  kv: KVNamespace,
  limit: number = RATE_LIMIT_RPM
): Promise<{ allowed: boolean; remaining: number }> {
  const key = `rl:${ip}`;
  const now = Math.floor(Date.now() / 1000);
  const windowStart = now - RATE_LIMIT_WINDOW_S;

  try {
    const raw = await kv.get(key);
    let timestamps: number[] = raw ? JSON.parse(raw) : [];
    timestamps = timestamps.filter((t) => t > windowStart);

    if (timestamps.length >= limit) {
      return { allowed: false, remaining: 0 };
    }

    timestamps.push(now);
    await kv.put(key, JSON.stringify(timestamps), {
      expirationTtl: RATE_LIMIT_WINDOW_S * 2,
    });

    return { allowed: true, remaining: limit - timestamps.length };
  } catch {
    return { allowed: true, remaining: limit };
  }
}

function buildProxyHeaders(request: Request, clientIp: string): Headers {
  const headers = new Headers();
  for (const [key, value] of request.headers.entries()) {
    if (
      key.toLowerCase() === "host" ||
      key.toLowerCase() === "cf-connecting-ip"
    )
      continue;
    headers.set(key, value);
  }
  headers.set("X-Forwarded-For", clientIp);
  return headers;
}

async function proxyToBackend(
  request: Request,
  env: Env,
  pathname: string,
  search: string,
  clientIp: string,
  cors: Record<string, string>,
  remaining: number,
): Promise<Response> {
  const backendUrl = `${env.BACKEND_URL}${pathname}${search}`;
  const proxyHeaders = buildProxyHeaders(request, clientIp);
  // Task #606: Authenticated origin pull for the Cloud Run backend.
  // Without this header, the FastAPI `OriginSharedSecretMiddleware`
  // returns 403 — which is what stops anyone from bypassing
  // Cloudflare's WAF / rate limit / cache by hitting the
  // `*.run.app` URL directly. No-op if the secret isn't bound.
  if (env.BACKEND_ORIGIN_SECRET) {
    proxyHeaders.set("X-Origin-Auth", env.BACKEND_ORIGIN_SECRET);
  }

  try {
    const backendResp = await fetch(backendUrl, {
      method: request.method,
      headers: proxyHeaders,
      body:
        request.method !== "GET" && request.method !== "HEAD"
          ? request.body
          : undefined,
    });

    const respHeaders = new Headers(cors);
    for (const [key, value] of backendResp.headers.entries()) {
      if (
        key.toLowerCase() !== "access-control-allow-origin" &&
        key.toLowerCase() !== "access-control-allow-credentials" &&
        key.toLowerCase() !== "access-control-allow-methods" &&
        key.toLowerCase() !== "access-control-allow-headers"
      ) {
        respHeaders.set(key, value);
      }
    }
    respHeaders.set("X-RateLimit-Remaining", String(remaining));
    respHeaders.set("X-Cache", "BYPASS");
    respHeaders.set("X-Source", "backend");

    return new Response(backendResp.body, {
      status: backendResp.status,
      headers: respHeaders,
    });
  } catch {
    return new Response(
      JSON.stringify({ detail: "Backend unavailable", edge: true }),
      {
        status: 502,
        headers: { ...cors, "Content-Type": "application/json", "X-Source": "backend" },
      }
    );
  }
}

function d1JsonResponse(
  data: unknown,
  cors: Record<string, string>,
  remaining: number,
  pathname: string,
): Response {
  const ttl = getCacheTtl(pathname);
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: {
      ...cors,
      "Content-Type": "application/json",
      "Cache-Control": `public, max-age=${ttl}, stale-while-revalidate=${ttl * 2}`,
      "X-Cache": "D1",
      "X-Source": "d1",
      "X-RateLimit-Remaining": String(remaining),
    },
  });
}

function d1XmlResponse(
  xml: string,
  cors: Record<string, string>,
  remaining: number,
): Response {
  return new Response(xml, {
    status: 200,
    headers: {
      ...cors,
      "Content-Type": "application/xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600, stale-while-revalidate=7200",
      "X-Cache": "D1",
      "X-Source": "d1",
      "X-RateLimit-Remaining": String(remaining),
    },
  });
}

function buildUrlset(entries: Array<{ loc: string; lastmod: string; pri: string; freq: string; has_assamese?: boolean }>): string {
  const anyAlt = entries.some(e => e.has_assamese);
  const opener = anyAlt
    ? '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
    : '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">';
  const lines = ['<?xml version="1.0" encoding="UTF-8"?>', opener];
  for (const e of entries) {
    let alt = "";
    if (e.has_assamese) {
      const sep = e.loc.includes("?") ? "&amp;" : "?";
      const asLoc = `${e.loc}${sep}lang=as`;
      alt =
        `<xhtml:link rel="alternate" hreflang="en" href="${e.loc}"/>` +
        `<xhtml:link rel="alternate" hreflang="as" href="${asLoc}"/>` +
        `<xhtml:link rel="alternate" hreflang="x-default" href="${e.loc}"/>`;
    }
    lines.push(
      `  <url><loc>${e.loc}</loc><lastmod>${e.lastmod}</lastmod><changefreq>${e.freq}</changefreq><priority>${e.pri}</priority>${alt}</url>`
    );
  }
  lines.push("</urlset>");
  return lines.join("\n");
}

function seoPageToSitemapEntry(
  p: { board_slug: string; class_slug: string; subject_slug: string; topic_slug: string; page_type: string; updated_at?: string; created_at?: string },
  today: string,
): { loc: string; lastmod: string; pri: string; freq: string; page_type: string } | null {
  if (!p.board_slug || !p.class_slug || !p.subject_slug || !p.topic_slug) return null;
  if (!SITEMAP_TYPES.includes(p.page_type)) return null;
  const basePath = `/${p.board_slug}/${p.class_slug}/${p.subject_slug}/${p.topic_slug}`;
  const path = p.page_type === "notes" ? basePath : `${basePath}/${p.page_type}`;
  const raw = p.updated_at || p.created_at || "";
  const lastmod = raw && raw.length >= 10 ? raw.slice(0, 10) : today;
  return {
    loc: `${BASE_URL}${path}`,
    lastmod,
    pri: p.page_type === "notes" ? "0.8" : "0.7",
    freq: "monthly",
    page_type: p.page_type,
  };
}

type D1RouteResult =
  | { type: "json"; data: unknown }
  | { type: "xml"; data: string }
  | null;

async function tryD1Route(
  env: Env,
  pathname: string,
  searchParams: URLSearchParams,
): Promise<D1RouteResult> {
  const db = env.CONTENT_DB;
  if (!db) return null;

  if (!await isD1Synced(db)) return null;

  if (pathname === "/api/content/library-bundle") {
    const slim = searchParams.get("slim") === "1";
    const requiredTables = slim
      ? ["boards", "classes", "streams", "subjects"]
      : ["boards", "classes", "streams", "subjects", "chapters"];
    for (const table of requiredTables) {
      if (!await isTablePopulated(db, table)) return null;
    }
    const data = slim ? await getLibraryBundleSlim(db) : await getLibraryBundle(db);
    if (data === null) return null;
    return { type: "json", data };
  }

  if (pathname === "/api/content/boards") {
    const data = await getBoards(db);
    if (data === null) return null;
    if (data.length === 0 && !await isTablePopulated(db, "boards")) return null;
    return { type: "json", data };
  }

  if (pathname === "/api/content/classes") {
    const boardId = searchParams.get("board_id") || undefined;
    const data = await getClasses(db, boardId);
    if (data === null) return null;
    if (data.length === 0 && !await isTablePopulated(db, "classes")) return null;
    return { type: "json", data };
  }

  if (pathname === "/api/content/streams") {
    const classId = searchParams.get("class_id") || undefined;
    const data = await getStreams(db, classId);
    if (data === null) return null;
    if (data.length === 0 && !await isTablePopulated(db, "streams")) return null;
    return { type: "json", data };
  }

  if (pathname === "/api/content/subjects") {
    const streamId = searchParams.get("stream_id");
    const classId = searchParams.get("class_id");
    let data: Record<string, unknown>[] | null;
    if (streamId) data = await getSubjectsByStream(db, streamId);
    else if (classId) data = await getSubjectsByClassId(db, classId);
    else data = await getAllSubjects(db);
    if (data === null) return null;
    if (data.length === 0 && !await isTablePopulated(db, "subjects")) return null;
    return { type: "json", data };
  }

  const subjectMatch = pathname.match(/^\/api\/content\/subjects\/([^/]+)$/);
  if (subjectMatch) {
    const data = await getSubjectById(db, subjectMatch[1]);
    return data !== null ? { type: "json", data } : null;
  }

  const chaptersMatch = pathname.match(/^\/api\/content\/chapters\/([^/]+)$/);
  if (chaptersMatch) {
    const data = await getChaptersBySubject(db, chaptersMatch[1]);
    if (data === null) return null;
    if (data.length === 0 && !await isTablePopulated(db, "chapters")) return null;
    return { type: "json", data };
  }

  const topicMatch = pathname.match(/^\/api\/content\/topic\/([^/]+)$/);
  if (topicMatch) {
    const data = await getTopicsByChapter(db, topicMatch[1]);
    if (data === null) return null;
    if (data.length === 0 && !await isTablePopulated(db, "topics")) return null;
    return { type: "json", data };
  }

  const seoResult = await trySeoD1Route(db, pathname, searchParams);
  if (seoResult !== null) return seoResult;

  return null;
}

async function trySeoD1Route(
  db: D1Database,
  pathname: string,
  searchParams: URLSearchParams,
): Promise<D1RouteResult> {
  if (pathname === "/api/seo/sitemap-entries" || pathname.startsWith("/api/seo/sitemap-entries")) {
    const pageType = searchParams.get("page_type") || undefined;
    const data = await getSitemapEntries(db, pageType);
    if (data === null) return null;
    if (data.length === 0 && !await isTablePopulated(db, "seo_pages")) return null;
    const entries = data as Array<{ board_slug: string; class_slug: string; subject_slug: string; topic_slug: string; page_type: string; updated_at: string }>;
    const result = [];
    for (const p of entries) {
      const path = `/${p.board_slug}/${p.class_slug}/${p.subject_slug}/${p.topic_slug}`;
      const url = p.page_type !== "notes" ? `${path}/${p.page_type}` : path;
      result.push({
        url,
        lastmod: p.updated_at || "",
        priority: p.page_type !== "notes" ? "0.7" : "0.8",
      });
    }
    return { type: "json", data: { entries: result, total: result.length } };
  }

  const pageTypedMatch = pathname.match(/^\/api\/seo\/page\/([^/]+)\/([^/]+)\/([^/]+)\/([^/]+)\/([^/]+)$/);
  if (pageTypedMatch) {
    const [, board, cls, subject, topic, pageType] = pageTypedMatch;
    if (!ALL_PAGE_TYPES.includes(pageType)) return null;
    const data = await getSeoPageBySlugs(db, board, cls, subject, topic, pageType);
    return data !== null ? { type: "json", data } : null;
  }

  const pageDefaultMatch = pathname.match(/^\/api\/seo\/page\/([^/]+)\/([^/]+)\/([^/]+)\/([^/]+)$/);
  if (pageDefaultMatch) {
    const [, board, cls, subject, topic] = pageDefaultMatch;
    const data = await getSeoPageBySlugs(db, board, cls, subject, topic, "notes");
    return data !== null ? { type: "json", data } : null;
  }

  const pageBundleMatch = pathname.match(/^\/api\/seo\/page-bundle\/([^/]+)\/([^/]+)\/([^/]+)\/([^/]+)$/);
  if (pageBundleMatch) {
    const [, board, cls, subject, topic] = pageBundleMatch;
    const pt = searchParams.get("pt") || "notes";
    const pageType = ALL_PAGE_TYPES.includes(pt) ? pt : "notes";
    const data = await getSeoPageBundle(db, board, cls, subject, topic, pageType);
    return data !== null ? { type: "json", data } : null;
  }

  const pageTypesMatch = pathname.match(/^\/api\/seo\/page-types\/([^/]+)\/([^/]+)\/([^/]+)\/([^/]+)$/);
  if (pageTypesMatch) {
    const [, board, cls, subject, topic] = pageTypesMatch;
    const data = await getSeoPageTypes(db, board, cls, subject, topic);
    if (data === null) return null;
    if (data.length === 0 && !await isTablePopulated(db, "seo_pages")) return null;
    return { type: "json", data };
  }

  const sitemapResult = await trySitemapD1Route(db, pathname);
  if (sitemapResult !== null) return sitemapResult;

  return null;
}

async function trySitemapD1Route(
  db: D1Database,
  pathname: string,
): Promise<D1RouteResult> {
  const today = new Date().toISOString().slice(0, 10);

  if (pathname === "/api/seo/sitemap-index.xml") {
    const publishedTypes = await getPublishedPageTypes(db);
    if (publishedTypes === null) return null;

    const alwaysInclude = [
      "sitemap-pages.xml",
      "sitemap-subjects.xml",
      "sitemap-chapters.xml",
      "sitemap-learn.xml",
      "sitemap-notes.xml",
    ];
    const typeToSitemap: Record<string, string> = {
      "mcqs": "sitemap-mcqs.xml",
      "important-questions": "sitemap-pyqs.xml",
      "examples": "sitemap-examples.xml",
      "definition": "sitemap-definitions.xml",
      "faq": "sitemap-faq.xml",
    };
    const sitemapNames = [...alwaysInclude];
    for (const [pt, smName] of Object.entries(typeToSitemap)) {
      if (publishedTypes.includes(pt)) {
        sitemapNames.push(smName);
      }
    }

    const lines = [
      '<?xml version="1.0" encoding="UTF-8"?>',
      '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ];
    for (const name of sitemapNames) {
      lines.push(`  <sitemap><loc>${BASE_URL}/api/seo/${name}</loc><lastmod>${today}</lastmod></sitemap>`);
    }
    lines.push("</sitemapindex>");
    return { type: "xml", data: lines.join("\n") };
  }

  if (pathname === "/api/seo/sitemap-pages.xml") {
    const stableDate = "2026-04-01";
    const entries = STATIC_PAGES.map(([path, freq, pri]) => ({
      loc: `${BASE_URL}${path}`, lastmod: stableDate, pri, freq,
    }));
    return { type: "xml", data: buildUrlset(entries) };
  }

  if (pathname === "/api/seo/sitemap-subjects.xml") {
    const subjectEntries = await getSubjectSitemapEntries(db);
    if (subjectEntries === null) return null;
    const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
    const entries = subjectEntries.map(e => ({
      loc: `${BASE_URL}/${e.board_slug}/${e.class_slug}/${e.subject_slug}`,
      lastmod: weekAgo, pri: "0.7", freq: "weekly",
    }));
    return { type: "xml", data: buildUrlset(entries) };
  }

  if (pathname === "/api/seo/sitemap-chapters.xml") {
    const chapterEntries = await getChapterSitemapEntries(db);
    if (chapterEntries === null) return null;
    const entries = chapterEntries.map(e => ({
      loc: `${BASE_URL}/${e.board_slug}/${e.class_slug}/${e.subject_slug}/${e.chapter_slug}`,
      lastmod: e.updated_at && e.updated_at.length >= 10 ? e.updated_at.slice(0, 10) : today,
      pri: "0.8", freq: "monthly",
      has_assamese: e.has_assamese,
    }));
    return { type: "xml", data: buildUrlset(entries) };
  }

  const seoTypeMap: Record<string, string> = {
    "/api/seo/sitemap-notes.xml": "notes",
    "/api/seo/sitemap-mcqs.xml": "mcqs",
    "/api/seo/sitemap-pyqs.xml": "important-questions",
    "/api/seo/sitemap-examples.xml": "examples",
    "/api/seo/sitemap-definitions.xml": "definition",
    "/api/seo/sitemap-faq.xml": "faq",
  };

  const seoPageType = seoTypeMap[pathname];
  if (seoPageType) {
    const pages = await getSeoPagesByType(db, seoPageType);
    if (pages === null) return null;
    const entries: Array<{ loc: string; lastmod: string; pri: string; freq: string }> = [];
    for (const p of pages) {
      const entry = seoPageToSitemapEntry(p, today);
      if (entry && entry.page_type === seoPageType) {
        entries.push({ loc: entry.loc, lastmod: entry.lastmod, pri: entry.pri, freq: entry.freq });
      }
    }
    return { type: "xml", data: buildUrlset(entries) };
  }

  if (pathname === "/api/seo/sitemap.xml") {
    const pages = await getSeoPagesByType(db, "");
    if (pages !== null) {
      const allPages = await getSitemapEntries(db);
      if (allPages === null) return null;
      const seoEntries: Array<{ loc: string; lastmod: string; pri: string; freq: string }> = [];
      const staticEntries = STATIC_PAGES.map(([path, freq, pri]) => ({
        loc: `${BASE_URL}${path}`, lastmod: today, pri, freq,
      }));
      for (const p of allPages as Array<{ board_slug: string; class_slug: string; subject_slug: string; topic_slug: string; page_type: string; updated_at: string }>) {
        const entry = seoPageToSitemapEntry(p, today);
        if (entry) {
          seoEntries.push({ loc: entry.loc, lastmod: entry.lastmod, pri: entry.pri, freq: entry.freq });
        }
      }
      return { type: "xml", data: buildUrlset([...staticEntries, ...seoEntries]) };
    }
    return null;
  }

  return null;
}

async function handleSyncRequest(
  request: Request,
  env: Env,
  cors: Record<string, string>,
): Promise<Response> {
  const authHeader = request.headers.get("Authorization");
  const expectedToken = env.D1_SYNC_SECRET;
  if (!expectedToken || expectedToken === "REPLACE_WITH_SECURE_RANDOM_SECRET") {
    return new Response(JSON.stringify({ error: "D1 sync secret not configured" }), {
      status: 500,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  if (!authHeader || authHeader !== `Bearer ${expectedToken}`) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  try {
    const payload = await request.json() as Record<string, unknown>;
    const result = await syncFromPayload(env.CONTENT_DB, payload);
    resetD1SyncedCache();
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "Unknown error";
    return new Response(JSON.stringify({ error: message }), {
      status: 500,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }
}

async function handleSyncStatus(
  env: Env,
  cors: Record<string, string>,
): Promise<Response> {
  const status = await getSyncStatus(env.CONTENT_DB);
  return new Response(JSON.stringify(status), {
    status: 200,
    headers: { ...cors, "Content-Type": "application/json" },
  });
}

async function handleEdgePurge(
  request: Request,
  env: Env,
  cors: Record<string, string>,
  ctx: ExecutionContext,
): Promise<Response> {
  const authHeader = request.headers.get("Authorization");
  const expectedToken = env.D1_SYNC_SECRET;
  if (!expectedToken || !authHeader || authHeader !== `Bearer ${expectedToken}`) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }

  try {
    const body = await request.json() as { prefixes?: string[]; purge_all?: boolean; urls?: string[] };
    const cache = caches.default;
    let purgedCount = 0;
    const baseUrl = new URL(request.url).origin;

    if (body.purge_all) {
      const purgeKeys: string[] = [];
      for (const prefix of CACHEABLE_PREFIXES) {
        purgeKeys.push(prefix);
      }
      purgeKeys.push("/api/content/library-bundle?slim=1");
      for (const key of purgeKeys) {
        const cacheKey = new Request(`${baseUrl}${key}`, { method: "GET" });
        const deleted = await cache.delete(cacheKey);
        if (deleted) purgedCount++;
      }
    }

    if (body.prefixes && Array.isArray(body.prefixes)) {
      for (const prefix of body.prefixes) {
        const cacheKey = new Request(`${baseUrl}${prefix}`, { method: "GET" });
        const deleted = await cache.delete(cacheKey);
        if (deleted) purgedCount++;
      }
    }

    if (body.urls && Array.isArray(body.urls)) {
      for (const url of body.urls) {
        const fullUrl = url.startsWith("http") ? url : `${baseUrl}${url}`;
        const cacheKey = new Request(fullUrl, { method: "GET" });
        const deleted = await cache.delete(cacheKey);
        if (deleted) purgedCount++;
      }
    }

    return new Response(
      JSON.stringify({ ok: true, purged: purgedCount }),
      { status: 200, headers: { ...cors, "Content-Type": "application/json" } },
    );
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "Unknown error";
    return new Response(JSON.stringify({ error: message }), {
      status: 500,
      headers: { ...cors, "Content-Type": "application/json" },
    });
  }
}

const _KNOWN_BOARDS = new Set(["ahsec", "seba", "degree", "cbse", "nep"]);

const BOT_CONTENT_PATTERNS: Array<{ regex: RegExp; type: string; test?: (p: string) => boolean }> = [
  { regex: /^\/([a-z0-9-]+)\/([a-z0-9-]+)\/([a-z0-9-]+)\/([a-z0-9-]+)\/(notes|mcqs|important-questions|examples|definition|faq)$/, type: "topic-typed" },
  { regex: /^\/([a-z0-9-]+)\/([a-z0-9-]+)\/([a-z0-9-]+)\/([a-z0-9-]+)$/, type: "topic" },
  { regex: /^\/([a-z0-9-]+)\/([a-z0-9-]+)\/([a-z0-9-]+)$/, type: "subject" },
  { regex: /^\/([a-z0-9-]+)\/([a-z0-9-]+)$/, type: "board-class", test: (p: string) => _KNOWN_BOARDS.has(p.split("/").filter(Boolean)[0]) },
  { regex: /^\/([a-z0-9-]+)$/, type: "board", test: (p: string) => _KNOWN_BOARDS.has(p.split("/").filter(Boolean)[0]) },
  { regex: /^\/learn\/([a-z0-9-]+)$/, type: "learn" },
  { regex: /^\/pyq\/([a-z0-9-]+)$/, type: "pyq" },
];

// Task #499: every entry here is a route the origin's BotRenderMiddleware
// returns a route-specific <link rel="canonical"> for. Adding a path here
// gives it its own bot-render cache slot at the edge — without that, two
// distinct URLs (e.g. /technology and /about) would collide on the same
// cache key and one of them would inherit the other's canonical, failing
// the Lighthouse `canonical` SEO audit. Auth-shell routes (/login,
// /signup, /profile, /admin/login) are noindex,follow but still need a
// self-referential canonical to pass the audit.
const BOT_STATIC_PAGES = new Set([
  "/", "/home", "/library", "/pricing", "/terms", "/privacy",
  "/about", "/technology", "/curriculum", "/exam-routine", "/chat",
  "/login", "/signup", "/profile", "/admin/login",
]);

const BOT_SKIP_EXTENSIONS = /\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot|map|json|webp|avif|mp4|webm)$/i;

const BOT_CACHE_TTL_CONTENT = 3600;
const BOT_CACHE_TTL_STATIC = 86400;

export function getBotPageCacheKey(pathname: string): string | null {
  const clean = pathname.replace(/\/+$/, "") || "/";

  if (BOT_SKIP_EXTENSIONS.test(clean)) return null;
  // Task #499: an audited route in BOT_STATIC_PAGES (e.g. /profile,
  // /admin/login) MUST be allowed through the bot path so the origin
  // can return its route-specific canonical. We therefore short-circuit
  // the skip-prefix check below for any path explicitly listed as a
  // static bot page. Real admin surfaces (/admin/api, /admin/console)
  // are not listed and continue to be skipped.
  if (BOT_STATIC_PAGES.has(clean)) return `bot:static:${clean}`;
  if (clean.startsWith("/api/") ||
      clean.startsWith("/admin/api") || clean.startsWith("/admin/console") ||
      clean.startsWith("/static/") || clean.startsWith("/assets/") ||
      clean.startsWith("/icons/") || clean.startsWith("/fonts/") ||
      clean.startsWith("/history")) {
    return null;
  }

  for (const pat of BOT_CONTENT_PATTERNS) {
    if (pat.regex.test(clean)) {
      if (pat.test && !pat.test(clean)) continue;
      return `bot:content:${clean}`;
    }
  }
  return null;
}

export function getBotCacheTtl(cacheKey: string): number {
  return cacheKey.startsWith("bot:static:") ? BOT_CACHE_TTL_STATIC : BOT_CACHE_TTL_CONTENT;
}

function _botResponseCacheTtl(pathname: string): number {
  const clean = pathname.replace(/\/+$/, "") || "/";
  if (BOT_STATIC_PAGES.has(clean)) return BOT_CACHE_TTL_STATIC;
  return BOT_CACHE_TTL_CONTENT;
}

async function fetchBotRenderedHtml(
  env: Env,
  pathname: string,
  clientIp: string,
  request: Request,
): Promise<Response | null> {
  const clean = pathname.replace(/\/+$/, "") || "/";
  const seoBase = `${env.BACKEND_URL}/api/seo`;
  let apiUrl: string;

  if (clean === "/" || clean === "/library") {
    apiUrl = `${seoBase}/html/homepage`;
  } else if (clean === "/about") {
    apiUrl = `${seoBase}/html/about`;
  } else if (
    // Task #499: route every audited public/auth-shell page directly
    // to the origin so BotRenderMiddleware emits its route-specific
    // canonical (https://syrabit.ai/<path>) — including /home, which
    // must NOT alias the homepage canonical, plus /technology, /login,
    // /signup, /profile, /admin/login.
    clean === "/home" || clean === "/technology" ||
    clean === "/pricing" || clean === "/terms" || clean === "/privacy" ||
    clean === "/curriculum" || clean === "/exam-routine" || clean === "/chat" ||
    clean === "/login" || clean === "/signup" || clean === "/profile" ||
    clean === "/admin/login"
  ) {
    apiUrl = `${env.BACKEND_URL}${clean}`;
  } else if (clean.startsWith("/learn/")) {
    apiUrl = `${env.BACKEND_URL}${clean}`;
  } else if (clean.startsWith("/pyq/")) {
    apiUrl = `${env.BACKEND_URL}${clean}`;
  } else {
    const parts = clean.split("/").filter(Boolean);
    if (parts.length === 1 && _KNOWN_BOARDS.has(parts[0])) {
      apiUrl = `${env.BACKEND_URL}${clean}`;
    } else if (parts.length === 2 && _KNOWN_BOARDS.has(parts[0])) {
      apiUrl = `${env.BACKEND_URL}${clean}`;
    } else if (parts.length === 3) {
      apiUrl = `${seoBase}/html/subject/${parts[0]}/${parts[1]}/${parts[2]}`;
    } else if (parts.length === 4) {
      apiUrl = `${seoBase}/html/${parts[0]}/${parts[1]}/${parts[2]}/${parts[3]}`;
    } else if (parts.length === 5) {
      apiUrl = `${seoBase}/html/${parts[0]}/${parts[1]}/${parts[2]}/${parts[3]}/${parts[4]}`;
    } else {
      return null;
    }
  }

  try {
    const proxyHeaders = buildProxyHeaders(request, clientIp);
    proxyHeaders.set("X-Bot-Request", "1");
    const resp = await fetch(apiUrl, {
      method: "GET",
      headers: proxyHeaders,
    });

    if (!resp.ok) {
      const parts = clean.split("/").filter(Boolean);
      if (parts.length >= 3 && parts.length <= 5) {
        const fallbackUrl = `${env.BACKEND_URL}${clean}`;
        const fallbackResp = await fetch(fallbackUrl, {
          method: "GET",
          headers: proxyHeaders,
        });
        if (fallbackResp.ok) {
          const fct = fallbackResp.headers.get("Content-Type") || "";
          if (fct.includes("text/html")) {
            const fbody = await fallbackResp.text();
            if (fbody && fbody.length >= 100) {
              const fbTtl = _botResponseCacheTtl(pathname);
              const fbHeaders: Record<string, string> = {
                "Content-Type": "text/html; charset=utf-8",
                "Cache-Control": `public, max-age=${fbTtl}, s-maxage=${fbTtl * 2}`,
                "X-Bot-Rendered": "1",
                "X-Source": "bot-prerender-fallback",
                "Vary": "User-Agent",
                "X-Robots-Tag": "index, follow",
                "Content-Language": "en-IN",
              };
              const fbLm = fallbackResp.headers.get("Last-Modified");
              if (fbLm) fbHeaders["Last-Modified"] = fbLm;
              return new Response(fbody, { status: 200, headers: fbHeaders });
            }
          }
        }
      }
      return null;
    }

    const ct = resp.headers.get("Content-Type") || "";
    if (!ct.includes("text/html") && !ct.includes("text/xml")) {
      return null;
    }

    const body = await resp.text();
    if (!body || body.length < 100) return null;

    const respTtl = _botResponseCacheTtl(pathname);
    const respHeaders: Record<string, string> = {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": `public, max-age=${respTtl}, s-maxage=${respTtl * 2}`,
      "X-Bot-Rendered": "1",
      "X-Source": "bot-prerender",
      "Vary": "User-Agent",
      "X-Robots-Tag": "index, follow",
      "Content-Language": "en-IN",
    };
    // Carry the backend's authoritative Last-Modified (sourced from
    // seo_pages.updated_at) up to the bot-cache layer so it can store it
    // in KV and emit it to crawlers — this is what makes 304s correct.
    const upstreamLm = resp.headers.get("Last-Modified");
    if (upstreamLm) respHeaders["Last-Modified"] = upstreamLm;
    return new Response(body, { status: 200, headers: respHeaders });
  } catch {
    return null;
  }
}

export interface BotCacheEntry {
  body: string;
  lastmod: string;
  etag: string;
}

export function formatRfc7231(d: Date): string {
  return d.toUTCString();
}

export function parseHttpDate(value: string | null | undefined): number | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Date.parse(trimmed);
  if (Number.isNaN(parsed)) return null;
  return parsed;
}

export async function computeEtag(body: string): Promise<string> {
  const enc = new TextEncoder().encode(body);
  const buf = await crypto.subtle.digest("SHA-256", enc);
  const arr = Array.from(new Uint8Array(buf));
  return arr.slice(0, 6).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function parseBotCacheEntry(raw: string | null | undefined): BotCacheEntry | null {
  if (!raw) return null;
  try {
    const obj = JSON.parse(raw);
    if (
      obj && typeof obj.body === "string" &&
      typeof obj.lastmod === "string" && typeof obj.etag === "string"
    ) {
      return obj as BotCacheEntry;
    }
  } catch { /* fall through */ }
  return null;
}

export function ifNoneMatchMatches(header: string | null | undefined, etag: string): boolean {
  if (!header) return false;
  const trimmed = header.trim();
  if (!trimmed) return false;
  if (trimmed === "*") return true;
  return trimmed.split(",").some((tok) => {
    let v = tok.trim();
    if (!v) return false;
    if (v.startsWith("W/")) v = v.slice(2);
    if (v.length >= 2 && v.startsWith('"') && v.endsWith('"')) v = v.slice(1, -1);
    return v === etag;
  });
}

export function shouldReturn304(
  request: Request,
  etag: string,
  lastmodMs: number,
): boolean {
  const inm = request.headers.get("If-None-Match");
  if (inm) return ifNoneMatchMatches(inm, etag);
  const ims = request.headers.get("If-Modified-Since");
  if (!ims) return false;
  const parsed = parseHttpDate(ims);
  if (parsed === null) return false; // never 304 on parse failure
  // Drop sub-second precision on the cache side too — RFC 7232 Last-Modified
  // resolution is one second.
  return Math.floor(lastmodMs / 1000) <= Math.floor(parsed / 1000);
}

function buildBotCacheHeaders(
  cacheTtl: number,
  lastmod: string,
  etag: string,
  source: string,
): Record<string, string> {
  return {
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": `public, max-age=${cacheTtl}, s-maxage=${cacheTtl * 2}`,
    "X-Bot-Rendered": "1",
    "X-Cache": source === "bot-cache" ? "BOT-KV-HIT" : "BOT-KV-MISS",
    "X-Source": source,
    "Vary": "User-Agent",
    "X-Robots-Tag": "index, follow",
    "Content-Language": "en-IN",
    "Last-Modified": lastmod,
    "ETag": `"${etag}"`,
  };
}

export async function handleBotContentRequest(
  env: Env,
  pathname: string,
  clientIp: string,
  request: Request,
  ctx: ExecutionContext,
): Promise<Response | null> {
  const cacheKey = getBotPageCacheKey(pathname);
  if (!cacheKey) return null;

  const cacheTtl = getBotCacheTtl(cacheKey);

  if (env.BOT_HTML_CACHE) {
    try {
      const raw = await env.BOT_HTML_CACHE.get(cacheKey);
      if (raw) {
        let entry = parseBotCacheEntry(raw);
        if (!entry) {
          // Legacy entry written as a plain HTML string before this header
          // wrapper landed. Synthesize lastmod=now and a body-derived etag
          // so we still emit conditional headers — the worst case is a
          // single full-body response per legacy entry until it expires.
          const etag = await computeEtag(raw);
          entry = { body: raw, lastmod: formatRfc7231(new Date()), etag };
        }
        const lastmodMs = parseHttpDate(entry.lastmod) ?? Date.now();
        const headers = buildBotCacheHeaders(cacheTtl, entry.lastmod, entry.etag, "bot-cache");
        if (shouldReturn304(request, entry.etag, lastmodMs)) {
          return new Response(null, { status: 304, headers });
        }
        return new Response(entry.body, { status: 200, headers });
      }
    } catch { /* fall through */ }
  }

  const rendered = await fetchBotRenderedHtml(env, pathname, clientIp, request);
  if (!rendered) return null;

  const htmlBody = await rendered.clone().text();
  const etag = await computeEtag(htmlBody);
  // Prefer the page's authoritative `updated_at` carried by the backend in
  // the upstream `Last-Modified` header (RFC 7231). Only fall back to "now"
  // if the upstream omits it or the value can't be parsed — in which case
  // the timestamp is still monotonic across the page's lifetime within KV.
  const upstreamLm = rendered.headers.get("Last-Modified");
  const lastmod = upstreamLm && parseHttpDate(upstreamLm) !== null
    ? upstreamLm
    : formatRfc7231(new Date());

  if (env.BOT_HTML_CACHE) {
    const entry: BotCacheEntry = { body: htmlBody, lastmod, etag };
    ctx.waitUntil(
      env.BOT_HTML_CACHE.put(cacheKey, JSON.stringify(entry), { expirationTtl: cacheTtl })
        .catch(() => {})
    );
  }

  const headers = buildBotCacheHeaders(cacheTtl, lastmod, etag, "bot-prerender");
  // Preserve any explicit X-Source set by the renderer (e.g.
  // bot-prerender-fallback) so observability stays accurate.
  const renderedSource = rendered.headers.get("X-Source");
  if (renderedSource) headers["X-Source"] = renderedSource;
  if (shouldReturn304(request, etag, parseHttpDate(lastmod) ?? Date.now())) {
    return new Response(null, { status: 304, headers });
  }
  return new Response(htmlBody, { status: 200, headers });
}

// ─── Task #636: Workers AI fallback fan-out ────────────────────────────────
// The FastAPI backend posts here only after its primary provider has
// failed with a retryable error (timeout / 5xx / 429 / quota). The
// shapes are normalised so the backend can call a single client and
// not care about Workers AI's per-model quirks.
const WORKERS_AI_MODELS = {
  chat: "@cf/meta/llama-3.1-8b-instruct",
  embed: "@cf/baai/bge-base-en-v1.5",
  stt: "@cf/openai/whisper",
  tts: "@cf/myshell-ai/melotts",
} as const;
type AiCapability = keyof typeof WORKERS_AI_MODELS;

interface AiFallbackResultMeta {
  capability: AiCapability;
  model: string;
  duration_ms: number;
  edge_colo: string;
}

function aiFallbackResponse(
  body: Record<string, unknown>,
  cors: Record<string, string>,
  status = 200,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...cors,
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "X-Source": "workers-ai-fallback",
    },
  });
}

async function handleAiFallback(
  request: Request,
  env: Env,
  cors: Record<string, string>,
  capability: AiCapability,
): Promise<Response> {
  const provided = request.headers.get("X-Edge-AI-Secret") || "";
  if (
    !env.EDGE_AI_FALLBACK_SECRET ||
    provided !== env.EDGE_AI_FALLBACK_SECRET
  ) {
    return aiFallbackResponse(
      { ok: false, error: "unauthorized", capability },
      cors,
      401,
    );
  }
  if (!env.AI || typeof env.AI.run !== "function") {
    return aiFallbackResponse(
      { ok: false, error: "ai_binding_missing", capability },
      cors,
      503,
    );
  }

  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return aiFallbackResponse(
      { ok: false, error: "invalid_json", capability },
      cors,
      400,
    );
  }

  const model = WORKERS_AI_MODELS[capability];
  const colo =
    (request as unknown as { cf?: { colo?: string } }).cf?.colo || "unknown";
  const t0 = Date.now();

  try {
    let payload: Record<string, unknown>;
    if (capability === "chat") {
      const messages = Array.isArray(body.messages) ? body.messages : null;
      if (!messages || messages.length === 0) {
        return aiFallbackResponse(
          { ok: false, error: "messages_required", capability },
          cors,
          400,
        );
      }
      payload = {
        messages,
        max_tokens: typeof body.max_tokens === "number" ? body.max_tokens : 1024,
        temperature:
          typeof body.temperature === "number" ? body.temperature : 0.3,
      };
    } else if (capability === "embed") {
      const text = body.text;
      if (!text || (typeof text !== "string" && !Array.isArray(text))) {
        return aiFallbackResponse(
          { ok: false, error: "text_required", capability },
          cors,
          400,
        );
      }
      payload = { text };
    } else if (capability === "tts") {
      const prompt =
        typeof body.text === "string"
          ? (body.text as string)
          : typeof body.prompt === "string"
            ? (body.prompt as string)
            : "";
      if (!prompt) {
        return aiFallbackResponse(
          { ok: false, error: "text_required", capability },
          cors,
          400,
        );
      }
      payload = {
        prompt: prompt.slice(0, 1000),
        lang: typeof body.lang === "string" ? body.lang : "en",
      };
    } else {
      // stt
      const audioB64 = typeof body.audio_base64 === "string" ? body.audio_base64 : "";
      if (!audioB64) {
        return aiFallbackResponse(
          { ok: false, error: "audio_base64_required", capability },
          cors,
          400,
        );
      }
      // Workers AI whisper expects a Uint8Array.
      const binary = atob(audioB64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      payload = { audio: Array.from(bytes) };
    }

    const out = (await env.AI.run(model, payload)) as Record<string, unknown> &
      { response?: string; data?: number[][] };

    const meta: AiFallbackResultMeta = {
      capability,
      model,
      duration_ms: Date.now() - t0,
      edge_colo: colo,
    };

    let normalised: Record<string, unknown>;
    if (capability === "chat") {
      normalised = { text: typeof out.response === "string" ? out.response : "" };
    } else if (capability === "embed") {
      normalised = { vectors: Array.isArray(out.data) ? out.data : [] };
    } else if (capability === "tts") {
      // melotts returns { audio: number[] } in its WAV bytes form.
      const audio = (out as { audio?: number[] }).audio || [];
      const buf = new Uint8Array(audio);
      let bin = "";
      for (let i = 0; i < buf.length; i++) bin += String.fromCharCode(buf[i]);
      normalised = { audio_base64: btoa(bin), format: "wav" };
    } else {
      normalised = { text: typeof out.text === "string" ? out.text : "" };
    }

    console.log(
      `[workers-ai-fallback] capability=${capability} model=${model} ` +
      `duration_ms=${meta.duration_ms} colo=${colo} ok=true`,
    );
    return aiFallbackResponse(
      { ok: true, provider: "workers-ai", meta, ...normalised },
      cors,
    );
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "unknown";
    const dur = Date.now() - t0;
    console.warn(
      `[workers-ai-fallback] capability=${capability} model=${model} ` +
      `duration_ms=${dur} colo=${colo} ok=false err=${msg.slice(0, 200)}`,
    );
    return aiFallbackResponse(
      { ok: false, provider: "workers-ai", error: msg.slice(0, 300), capability },
      cors,
      502,
    );
  }
}

async function handleScheduledSync(env: Env): Promise<void> {
  if (!env.CONTENT_DB || !env.BACKEND_URL) return;

  try {
    const resp = await fetch(`${env.BACKEND_URL}/api/admin/d1-export`, {
      method: "GET",
      headers: {
        "Authorization": `Bearer ${env.D1_SYNC_SECRET}`,
        "Content-Type": "application/json",
      },
    });

    if (!resp.ok) {
      console.error(`D1 scheduled sync failed: backend returned ${resp.status}`);
      return;
    }

    const payload = await resp.json() as Record<string, unknown>;
    const result = await syncFromPayload(env.CONTENT_DB, payload);
    console.log(`D1 scheduled sync complete:`, JSON.stringify(result));
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "Unknown error";
    console.error(`D1 scheduled sync error: ${message}`);
  }
}

export default {
  async fetch(
    request: Request,
    env: Env,
    ctx: ExecutionContext
  ): Promise<Response> {
    const url = new URL(request.url);
    const { pathname } = url;
    const origin = request.headers.get("Origin");
    const cors = safeCorsHeaders(origin);

    if (request.method === "OPTIONS") {
      const preflight = getCorsHeaders(origin);
      if (!preflight) {
        return new Response(null, { status: 403 });
      }
      return new Response(null, { status: 204, headers: preflight });
    }

    // From here on, all KV access goes through the monitored wrapper so
    // counters are accurate and graceful fallback kicks in on quota
    // exhaustion. The wrappers are cheap closures — re-creating them
    // per-request keeps the binding instances `const` and lets the
    // monitor module share state across requests via its own Map.
    env = wrapEnvKv(env, ctx);

    if (pathname === "/api/edge/kv-usage" && request.method === "GET") {
      return handleKvUsage(env, request, cors);
    }

    if (pathname === "/api/health" || pathname === "/health") {
      return new Response(
        JSON.stringify({
          status: "ok",
          edge: true,
          region: (request as unknown as { cf?: { colo?: string } }).cf?.colo || "unknown",
          timestamp: new Date().toISOString(),
          d1: !!env.CONTENT_DB,
        }),
        {
          status: 200,
          headers: {
            ...cors,
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=30, stale-while-revalidate=60",
            "X-Source": "edge",
          },
        }
      );
    }

    // Task #636 — Workers AI fallback fan-out. Backend POSTs here only
    // after a primary-provider failure. POST-only; CORS preflight is
    // handled above by the OPTIONS branch.
    if (request.method === "POST" && pathname.startsWith("/api/ai/fallback/")) {
      const cap = pathname.slice("/api/ai/fallback/".length);
      if (cap === "chat" || cap === "embed" || cap === "tts" || cap === "stt") {
        return handleAiFallback(request, env, cors, cap);
      }
      return new Response(
        JSON.stringify({ ok: false, error: "unknown_capability" }),
        { status: 404, headers: { ...cors, "Content-Type": "application/json" } },
      );
    }

    if (pathname === "/api/edge/d1-sync" && request.method === "POST") {
      return handleSyncRequest(request, env, cors);
    }

    if (pathname === "/api/edge/d1-status" && request.method === "GET") {
      return handleSyncStatus(env, cors);
    }

    if (pathname === "/api/edge/purge" && request.method === "POST") {
      return handleEdgePurge(request, env, cors, ctx);
    }

    const clientIp =
      request.headers.get("CF-Connecting-IP") ||
      request.headers.get("X-Forwarded-For")?.split(",")[0]?.trim() ||
      "unknown";

    const ua = request.headers.get("User-Agent") || "";
    const botResult = verifySearchBot(ua, request, clientIp);
    const isSearchBot = botResult.verified;
    let remaining = 999999;

    if (botResult.spoofed) {
      const ipH = hashIp(clientIp);
      const colo = (request as unknown as { cf?: { colo?: string } }).cf?.colo || "unknown";
      ctx.waitUntil(logSpoofedBot(env.RATE_LIMIT, ipH, ua, clientIp, colo));
    }

    const isApiRoute = pathname.startsWith("/api/");

    if (!isSearchBot && isApiRoute) {
      const rl = await checkRateLimit(clientIp, env.RATE_LIMIT, RATE_LIMIT_RPM);
      remaining = rl.remaining;
      if (!rl.allowed) {
        return new Response(
          JSON.stringify({ detail: "Rate limit exceeded. Try again shortly." }),
          {
            status: 429,
            headers: {
              ...cors,
              "Content-Type": "application/json",
              "Retry-After": String(RATE_LIMIT_WINDOW_S),
              "X-RateLimit-Limit": String(RATE_LIMIT_RPM),
              "X-RateLimit-Remaining": "0",
            },
          }
        );
      }
    }

    if (!isApiRoute && (request.method === "GET" || request.method === "HEAD")) {
      if (isSearchBot && request.method === "GET") {
        const botResp = await handleBotContentRequest(env, pathname, clientIp, request, ctx);
        if (botResp) return botResp;
      }
      // CRITICAL: do NOT call fetch(request) — this worker is bound to
      // syrabit.ai/* and www.syrabit.ai/*, and fetch(request) re-enters
      // the same worker route causing recursion that resolves to garbage
      // (Pages HTML body + backend 404 headers). Always proxy to the
      // Pages origin by its workers.dev hostname so the worker route is
      // bypassed cleanly. HEAD must be handled here too — the SEO health
      // checker probes URLs with HEAD and would otherwise fall through to
      // Railway and get 404.
      const pagesOrigin = env.PAGES_ORIGIN || "https://syrabit-zip-convert.pages.dev";
      const pagesUrl = `${pagesOrigin}${url.pathname}${url.search}`;
      return fetch(pagesUrl, {
        method: request.method,
        headers: request.headers,
        redirect: "manual",
      });
    }

    if ((request.method !== "GET" && request.method !== "HEAD") || isBypass(pathname)) {
      return proxyToBackend(request, env, pathname, url.search, clientIp, cors, remaining);
    }

    const hasAuth =
      request.headers.has("Authorization") ||
      request.headers.has("Cookie") ||
      request.headers.has("x-anon-id");

    if (isCacheable(pathname) && (!hasAuth || !isUserSpecific(pathname))) {
      const nocache = url.searchParams.get("nocache");

      if (!nocache && env.CONTENT_DB) {
        try {
          const d1Result = await tryD1Route(env, pathname, url.searchParams);
          if (d1Result !== null) {
            if (d1Result.type === "xml") {
              return d1XmlResponse(d1Result.data, cors, remaining);
            }
            return d1JsonResponse(d1Result.data, cors, remaining, pathname);
          }
        } catch { /* fall through to cache/backend */ }
      }

      const cache = caches.default;
      const cacheKey = new Request(url.toString(), { method: "GET" });

      const cachedResponse = await cache.match(cacheKey);
      if (cachedResponse) {
        const ttl = getCacheTtl(pathname);
        const resp = new Response(cachedResponse.body, cachedResponse);
        Object.entries(cors).forEach(([k, v]) => resp.headers.set(k, v));
        resp.headers.set("Cache-Control", `public, max-age=${ttl}, stale-while-revalidate=${ttl * 2}`);
        resp.headers.set("X-Cache", "HIT");
        resp.headers.set("X-Source", "cf-cache");
        resp.headers.set("X-RateLimit-Remaining", String(remaining));
        return resp;
      }

      const backendUrl = `${env.BACKEND_URL}${pathname}${url.search}`;
      const backendHeaders = buildProxyHeaders(request, clientIp);

      try {
        const backendResp = await fetch(backendUrl, {
          method: "GET",
          headers: backendHeaders,
        });

        if (backendResp.ok) {
          const ttl = getCacheTtl(pathname);
          const respBody = await backendResp.arrayBuffer();

          const cachedResp = new Response(respBody, {
            status: backendResp.status,
            headers: {
              "Content-Type":
                backendResp.headers.get("Content-Type") || "application/json",
              "Cache-Control": `public, s-maxage=${ttl}, stale-while-revalidate=${ttl * 2}`,
            },
          });
          ctx.waitUntil(cache.put(cacheKey, cachedResp.clone()));

          const clientResp = new Response(respBody, {
            status: backendResp.status,
            headers: {
              ...cors,
              "Content-Type":
                backendResp.headers.get("Content-Type") || "application/json",
              "Cache-Control": `public, max-age=${ttl}, stale-while-revalidate=${ttl * 2}`,
              "X-Cache": "MISS",
              "X-Source": "backend",
              "X-RateLimit-Remaining": String(remaining),
            },
          });
          return clientResp;
        }

        const body = await backendResp.text();
        return new Response(body, {
          status: backendResp.status,
          headers: {
            ...cors,
            "Content-Type":
              backendResp.headers.get("Content-Type") || "application/json",
            "X-Cache": "BYPASS",
            "X-Source": "backend",
          },
        });
      } catch (err) {
        return new Response(
          JSON.stringify({ detail: "Backend unavailable", edge: true }),
          {
            status: 502,
            headers: { ...cors, "Content-Type": "application/json", "X-Source": "backend" },
          }
        );
      }
    }

    return proxyToBackend(request, env, pathname, url.search, clientIp, cors, remaining);
  },

  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(handleScheduledSync(env));
  },
};
