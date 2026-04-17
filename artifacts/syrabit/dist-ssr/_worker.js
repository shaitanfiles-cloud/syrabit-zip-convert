// Cloudflare Pages worker: SPA fallback + HEAD parity (Task #365).
//
// The previous implementation only served index.html for navigation
// requests where ``method === 'GET' && Accept includes 'text/html'``.
// HEAD requests fell through with the original 404 from ASSETS, which
// search engines and our internal SEO health probe (which uses HEAD as
// a cheap pre-check) recorded as broken URLs — clearing all 35 spot-
// checks to 0/35 and firing the SEO health CRITICAL alert hourly.
//
// The fix: treat HEAD the same as GET for SPA fallback. We still hand
// off true static assets, sitemaps, feeds, etc. to the asset pipeline
// (those paths are listed in ``_routes.json`` excludes so the Pages
// proxy forwards them to the backend / static assets directly).
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      const response = await env.ASSETS.fetch(request);
      if (response.status === 404) {
        const accept = request.headers.get("Accept") || "";
        // GET keeps the original strict navigation check (text/html in
        // Accept) so non-browser GET probes (e.g. JSON fetches that
        // legitimately 404) aren't masked. HEAD is broadened to also
        // accept */* and missing Accept — most crawlers and our own
        // SEO health probe send HEAD with no Accept header at all,
        // and pre-fix every one of those was being recorded as broken.
        const isGetNavigation =
          request.method === "GET" && accept.includes("text/html");
        const isHeadProbe =
          request.method === "HEAD" &&
          (accept === "" || accept.includes("text/html") || accept.includes("*/*"));
        if (isGetNavigation || isHeadProbe) {
          const indexResponse = await env.ASSETS.fetch(
            new URL("/", url.origin),
          );
          // For HEAD, return headers only with empty body so crawlers
          // see ``200 text/html`` instead of the original 404. Cloudflare
          // strips the body automatically when method is HEAD, but we
          // construct the response explicitly to keep behaviour
          // deterministic across runtimes.
          if (request.method === "HEAD") {
            return new Response(null, {
              headers: indexResponse.headers,
              status: 200,
            });
          }
          return new Response(indexResponse.body, {
            headers: indexResponse.headers,
            status: 200,
          });
        }
        return response;
      }
      return response;
    } catch {
      const indexResponse = await env.ASSETS.fetch(new URL("/", url.origin));
      if (request.method === "HEAD") {
        return new Response(null, {
          headers: indexResponse.headers,
          status: 200,
        });
      }
      return new Response(indexResponse.body, {
        headers: indexResponse.headers,
        status: 200,
      });
    }
  },
};
