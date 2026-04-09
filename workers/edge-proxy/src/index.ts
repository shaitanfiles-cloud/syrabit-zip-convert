import {
  isD1Synced, resetD1SyncedCache, isTablePopulated,
  getBoards, getClasses, getStreams, getAllSubjects, getSubjectsByStream,
  getSubjectsByClassId, getSubjectById, getChaptersBySubject,
  getTopicsByChapter, getSitemapEntries, getLibraryBundle,
  getSeoPageBySlugs, getSeoPageTypes, getSeoPageBundle,
  getSeoPagesByType, getPublishedPageTypes,
  getSubjectSitemapEntries, getChapterSitemapEntries,
} from "./d1-queries";
import { syncFromPayload, getSyncStatus } from "./d1-sync";

interface Env {
  BACKEND_URL: string;
  RATE_LIMIT: KVNamespace;
  CONTENT_DB: D1Database;
  D1_SYNC_SECRET: string;
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
];

const CACHE_TTL: Record<string, number> = {
  "/api/content/boards": 604800,
  "/api/content/classes": 604800,
  "/api/content/streams": 604800,
  "/api/content/subjects": 604800,
  "/api/content/chapters/": 604800,
  "/api/content/chunks/": 604800,
  "/api/content/library-bundle": 604800,
  "/api/content/chapter-by-slug/": 604800,
  "/api/content/topic/": 604800,
  "/api/content/syllabus/": 604800,
  "/api/seo/": 600,
  "/api/pyq/": 604800,
  "/api/notes/public": 604800,
  "/api/mcq/": 604800,
  "/api/user/stats": 900,
  "/api/cms/articles": 900,
  "/api/flashcards/": 604800,
  "/api/sitemap": 86400,
  "/api/robots.txt": 86400,
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
const RATE_LIMIT_WINDOW_S = 60;

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
const ALL_PAGE_TYPES = ["notes", "mcqs", "important-questions", "examples", "definition"];
const SITEMAP_TYPES = ["notes", "mcqs", "important-questions", "examples", "definition"];

function getCorsHeaders(origin: string | null): Record<string, string> | null {
  if (!origin || !ALLOWED_ORIGINS.includes(origin)) return null;
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept, Origin, X-Requested-With, x-anon-id",
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
  kv: KVNamespace
): Promise<{ allowed: boolean; remaining: number }> {
  const key = `rl:${ip}`;
  const now = Math.floor(Date.now() / 1000);
  const windowStart = now - RATE_LIMIT_WINDOW_S;

  try {
    const raw = await kv.get(key);
    let timestamps: number[] = raw ? JSON.parse(raw) : [];
    timestamps = timestamps.filter((t) => t > windowStart);

    if (timestamps.length >= RATE_LIMIT_RPM) {
      return { allowed: false, remaining: 0 };
    }

    timestamps.push(now);
    await kv.put(key, JSON.stringify(timestamps), {
      expirationTtl: RATE_LIMIT_WINDOW_S * 2,
    });

    return { allowed: true, remaining: RATE_LIMIT_RPM - timestamps.length };
  } catch {
    return { allowed: true, remaining: RATE_LIMIT_RPM };
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

function buildUrlset(entries: Array<{ loc: string; lastmod: string; pri: string; freq: string }>): string {
  const lines = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
  ];
  for (const e of entries) {
    lines.push(
      `  <url><loc>${e.loc}</loc><lastmod>${e.lastmod}</lastmod><changefreq>${e.freq}</changefreq><priority>${e.pri}</priority></url>`
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
    const requiredTables = ["boards", "classes", "streams", "subjects", "chapters"];
    for (const table of requiredTables) {
      if (!await isTablePopulated(db, table)) return null;
    }
    const data = await getLibraryBundle(db);
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
    const entries = STATIC_PAGES.map(([path, freq, pri]) => ({
      loc: `${BASE_URL}${path}`, lastmod: today, pri, freq,
    }));
    return { type: "xml", data: buildUrlset(entries) };
  }

  if (pathname === "/api/seo/sitemap-subjects.xml") {
    const subjectEntries = await getSubjectSitemapEntries(db);
    if (subjectEntries === null) return null;
    const entries = subjectEntries.map(e => ({
      loc: `${BASE_URL}/${e.board_slug}/${e.class_slug}/${e.subject_slug}`,
      lastmod: today, pri: "0.7", freq: "weekly",
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
    }));
    return { type: "xml", data: buildUrlset(entries) };
  }

  const seoTypeMap: Record<string, string> = {
    "/api/seo/sitemap-notes.xml": "notes",
    "/api/seo/sitemap-mcqs.xml": "mcqs",
    "/api/seo/sitemap-pyqs.xml": "important-questions",
    "/api/seo/sitemap-examples.xml": "examples",
    "/api/seo/sitemap-definitions.xml": "definition",
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

    if (pathname === "/api/edge/d1-sync" && request.method === "POST") {
      return handleSyncRequest(request, env, cors);
    }

    if (pathname === "/api/edge/d1-status" && request.method === "GET") {
      return handleSyncStatus(env, cors);
    }

    const clientIp =
      request.headers.get("CF-Connecting-IP") ||
      request.headers.get("X-Forwarded-For")?.split(",")[0]?.trim() ||
      "unknown";

    const { allowed, remaining } = await checkRateLimit(clientIp, env.RATE_LIMIT);
    if (!allowed) {
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

    if (request.method !== "GET" || isBypass(pathname)) {
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
