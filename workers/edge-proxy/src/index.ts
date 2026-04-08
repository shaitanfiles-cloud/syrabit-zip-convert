interface Env {
  BACKEND_URL: string;
  RATE_LIMIT: KVNamespace;
}

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

function getCorsHeaders(origin: string | null): Record<string, string> | null {
  if (!origin || !ALLOWED_ORIGINS.includes(origin)) return null;
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, Accept, Origin, X-Requested-With, x-anon-id",
    "Access-Control-Expose-Headers": "X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After, X-Request-Id",
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

    return new Response(backendResp.body, {
      status: backendResp.status,
      headers: respHeaders,
    });
  } catch {
    return new Response(
      JSON.stringify({ detail: "Backend unavailable", edge: true }),
      {
        status: 502,
        headers: { ...cors, "Content-Type": "application/json" },
      }
    );
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
          region: request.cf?.colo || "unknown",
          timestamp: new Date().toISOString(),
        }),
        {
          status: 200,
          headers: {
            ...cors,
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=30, stale-while-revalidate=60",
          },
        }
      );
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
      const cache = caches.default;
      const cacheKey = new Request(url.toString(), { method: "GET" });

      const cachedResponse = await cache.match(cacheKey);
      if (cachedResponse) {
        const ttl = getCacheTtl(pathname);
        const resp = new Response(cachedResponse.body, cachedResponse);
        Object.entries(cors).forEach(([k, v]) => resp.headers.set(k, v));
        resp.headers.set("Cache-Control", `public, max-age=${ttl}, stale-while-revalidate=${ttl * 2}`);
        resp.headers.set("X-Cache", "HIT");
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
          },
        });
      } catch (err) {
        return new Response(
          JSON.stringify({ detail: "Backend unavailable", edge: true }),
          {
            status: 502,
            headers: { ...cors, "Content-Type": "application/json" },
          }
        );
      }
    }

    return proxyToBackend(request, env, pathname, url.search, clientIp, cors, remaining);
  },
};
