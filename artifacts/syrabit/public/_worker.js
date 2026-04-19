// Cloudflare Pages worker.
//
// Two responsibilities:
//
// 1) **Bot rendering.** Search engines (Googlebot, Bingbot, etc.) and AI
//    crawlers MUST receive the rich, server-rendered HTML for chapter /
//    subject / static pages — NOT the SPA shell. The shell is 27 KB of
//    `<div id="root"></div>` with title "Syrabit.ai" and almost zero
//    chapter-specific text, which Google labels "soft 404" and refuses
//    to index. Before this rewrite, 134 of 137 sitemap URLs were
//    "Discovered – currently not indexed" for exactly that reason.
//    For verified-bot UAs we proxy GET requests to the backend's
//    /html/<rest-of-path> endpoint and return its response (which is
//    syllabus-aligned content + JSON-LD). For HEAD we still return
//    200 cheaply without going to the backend.
//
// 2) **SPA fallback.** Any non-asset path that is not a bot request
//    falls through to /index.html so React Router can take over.
//    HEAD parity is preserved (Task #365).
//
// Static assets (/assets/*, /icons/*, sitemaps, feeds, etc.) are
// excluded in `_routes.json` and never reach this worker.

// Matches the SAME UA list the edge proxy at api.syrabit.ai uses
// (workers/edge-proxy/src/index.ts SEARCH_BOT_UA) so behaviour is
// consistent across both surfaces. AI-search crawlers are included
// because they ground their answers in the same HTML they fetch.
const SEARCH_BOT_UA = /googlebot|google-extended|googleother|google-inspectiontool|bingbot|yandexbot|duckduckbot|slurp|applebot|chatgpt-user|oai-searchbot|perplexitybot|claudebot|meta-externalagent|facebookexternalhit|twitterbot|linkedinbot|whatsapp|telegrambot|discordbot/i;

// Backend that serves bot-rendered HTML. Configured at build time via
// the BACKEND_BOT_URL env var on the Pages project; falls back to the
// public api.syrabit.ai hostname if unset.
const DEFAULT_BACKEND = "https://api.syrabit.ai";

// Paths that never need bot rendering — let them go straight to the
// SPA shell (auth flows, the /chat surface, internal admin, etc.).
// Anything not listed here gets the bot-render path for bots.
// Prefixes are stored WITHOUT trailing slashes so the matcher below
// can do an exact-match OR `path.startsWith(prefix + "/")` test
// uniformly. Adding a trailing slash here breaks the matcher:
// e.g. "/api/" + "/" → "/api//" which never matches "/api/users".
const BOT_RENDER_SKIP_PREFIXES = [
  "/login",
  "/signup",
  "/profile",
  "/admin",
  "/auth",
  "/api",
  "/cms",
  "/chat",
];

function shouldBotRender(pathname) {
  if (pathname === "/" || pathname === "") return true;
  for (const p of BOT_RENDER_SKIP_PREFIXES) {
    if (pathname === p || pathname.startsWith(p + "/")) return false;
  }
  return true;
}

async function botRender(request, env, url) {
  // Map / → /html/homepage, /home → /html/home, etc. The backend
  // exposes /html/<rest-of-path> for chapters and /html/homepage
  // for the root. We pass the path through unchanged for everything
  // except /, which the backend serves under /html/homepage.
  const backend = (env && env.BACKEND_BOT_URL) || DEFAULT_BACKEND;
  let backendPath;
  if (url.pathname === "/" || url.pathname === "") {
    backendPath = "/html/homepage";
  } else {
    backendPath = "/html" + url.pathname;
  }
  const backendUrl = backend + backendPath + url.search;
  try {
    const resp = await fetch(backendUrl, {
      method: "GET",
      headers: {
        "User-Agent": request.headers.get("User-Agent") || "",
        "Accept": "text/html",
        "X-Forwarded-For": request.headers.get("CF-Connecting-IP") || "",
        "X-Bot-Render": "1",
      },
      cf: { cacheTtl: 300, cacheEverything: true },
    });
    // Backend returns 200 with HTML on hit, non-200 on miss/error.
    if (resp.status === 200) {
      const ct = resp.headers.get("content-type") || "";
      if (ct.includes("text/html") || ct.includes("application/xhtml")) {
        const headers = new Headers(resp.headers);
        headers.set("X-Source", "bot-render");
        headers.set("Cache-Control", "public, max-age=300, s-maxage=300");
        return new Response(resp.body, { status: 200, headers });
      }
    }
  } catch {
    // Fall through to SPA shell on any backend error — better to
    // serve the shell than to 5xx Googlebot.
  }
  return null;
}

async function spaShellResponse(request, env, url, originalStatus) {
  const indexResponse = await env.ASSETS.fetch(new URL("/", url.origin));
  if (request.method === "HEAD") {
    return new Response(null, {
      headers: indexResponse.headers,
      status: 200,
    });
  }
  return new Response(indexResponse.body, {
    headers: indexResponse.headers,
    status: originalStatus === 404 ? 200 : (originalStatus || 200),
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const ua = request.headers.get("User-Agent") || "";
    const isBot = SEARCH_BOT_UA.test(ua);

    // Loop guard: if this request already carries the X-Bot-Render
    // tag (i.e. it's the backend fetching back through the Pages
    // host because BACKEND_BOT_URL was misconfigured), do NOT
    // recurse — fall through to the asset pipeline. Same for any
    // request whose target host literally equals the configured
    // backend host: that means someone pointed BACKEND_BOT_URL at
    // syrabit.ai itself.
    const backendHost = (() => {
      try { return new URL((env && env.BACKEND_BOT_URL) || DEFAULT_BACKEND).host; }
      catch { return ""; }
    })();
    const wouldLoop =
      request.headers.get("X-Bot-Render") === "1" ||
      (backendHost && backendHost === url.host);

    // Bot rendering: GET requests from search/AI bot UAs that hit a
    // non-skip path get the backend-rendered HTML. We do this BEFORE
    // the asset lookup so bots never see the SPA shell. UA-only
    // matching here (no IP verification) — the trade-off is some
    // false positives from spoofed UAs may hit the backend, but the
    // backend caches /html/* aggressively so the cost is minimal,
    // and any miss falls through gracefully below.
    if (
      isBot &&
      !wouldLoop &&
      request.method === "GET" &&
      shouldBotRender(url.pathname)
    ) {
      const rendered = await botRender(request, env, url);
      if (rendered) return rendered;
      // Backend miss → fall through to the asset pipeline so the bot
      // at least sees a valid 200 (rather than a 5xx).
    }

    try {
      const response = await env.ASSETS.fetch(request);
      if (response.status === 404) {
        const accept = request.headers.get("Accept") || "";
        // Same-as-before SPA fallback rules. Note that for bots we
        // already tried the backend above; if we land here it means
        // either the path is in BOT_RENDER_SKIP_PREFIXES (auth, admin,
        // chat — pages bots shouldn't index anyway) or the backend
        // missed and we want a graceful 200.
        const isGetNavigation =
          request.method === "GET" && accept.includes("text/html");
        const isHeadProbe =
          request.method === "HEAD" &&
          (accept === "" || accept.includes("text/html") || accept.includes("*/*"));
        const isBotGet = isBot && request.method === "GET";
        if (isGetNavigation || isHeadProbe || isBotGet) {
          return spaShellResponse(request, env, url, 404);
        }
        return response;
      }
      return response;
    } catch {
      return spaShellResponse(request, env, url, 200);
    }
  },
};
