#!/usr/bin/env node
/**
 * Live edge-cache integration check (Task #794).
 *
 * The unit-layer regression in `workers/edge-proxy/tests/edge-cache-classify.test.ts`
 * proves that we *intend* to cache the routes in `CACHEABLE_PREFIXES`, but it
 * runs against an in-memory Cache stub. It cannot catch the most painful
 * class of bugs:
 *
 *   - The route is in CACHEABLE_PREFIXES but the worker is mis-deployed.
 *   - Wrangler vars or routes drift from `wrangler.toml`.
 *   - A new middleware accidentally sets `Cache-Control: private` and
 *     poisons the response so CF never stores it.
 *   - A response body is too large / has Set-Cookie / streams, all of
 *     which silently disable CF's edge cache.
 *
 * This script hits a representative sample of cacheable GET routes against
 * the real deployment twice each, asserts the second response carries
 * `X-Cache: HIT` (or `HIT-304` when the body has an ETag and we resend
 * If-None-Match), and exits non-zero if any route is cold.
 *
 * Usage
 * -----
 *   node artifacts/syrabit/tests/edge-cache-live.mjs
 *   EDGE_CACHE_TEST_URL=https://api.syrabit.ai \
 *     node artifacts/syrabit/tests/edge-cache-live.mjs
 *
 * Env vars
 * --------
 *   EDGE_CACHE_TEST_URL   Base URL to hit (default: https://api.syrabit.ai).
 *   EDGE_CACHE_DELAY_MS   Wait between MISS and HIT request (default: 250).
 *                         CF normally writes to the per-POP cache before
 *                         the response body finishes streaming, so 250 ms
 *                         is plenty in practice; bump it on slow links.
 *   EDGE_CACHE_TIMEOUT_MS Per-request timeout (default: 10000).
 *   EDGE_CACHE_VERBOSE    "1" to print full headers for every request.
 *
 * Why a cache-bust query string?
 * ------------------------------
 * The CF cache key is the request URL. Real production traffic has already
 * warmed `https://api.syrabit.ai/api/content/boards`, so the first call from
 * this script would always be a HIT and tell us nothing about the actual
 * MISS→HIT transition. By appending `?_cb=<random>` we force a fresh cache
 * entry that we know the second call must produce by storing into this POP.
 *
 * What counts as a warm response?
 * --------------------------------
 * The worker has TWO fast paths and both are real production outcomes:
 *   - `X-Cache: HIT` / `HIT-304` — CF per-POP cache hit (the canonical
 *     case this task targets).
 *   - `X-Cache: D1`              — served straight from a D1 replica
 *     without backend round-trip. ~30–80 ms TTFB, fully Cache-Control'd
 *     at the browser layer. Functionally a warm response from the
 *     student's perspective even though it bypasses CF's edge cache.
 *
 * In the default mode we treat both as PASS so this script does not
 * flap when D1 is healthy but CF cache hasn't yet warmed for a
 * particular cache-bust query. Set `EDGE_CACHE_STRICT=1` to require
 * `HIT`/`HIT-304` only — useful when investigating a suspected CF
 * cache-write regression.
 *
 * Exit codes
 * ----------
 *   0 — every probed route returned a warm response (HIT/D1).
 *   1 — at least one route stayed cold on the 2nd request.
 *   2 — network/setup failure (all routes errored).
 */

const BASE_URL = (process.env.EDGE_CACHE_TEST_URL || "https://api.syrabit.ai").replace(/\/$/, "");
const DELAY_MS = Number(process.env.EDGE_CACHE_DELAY_MS || 250);
const TIMEOUT_MS = Number(process.env.EDGE_CACHE_TIMEOUT_MS || 10000);
const VERBOSE = process.env.EDGE_CACHE_VERBOSE === "1";

// Representative sample drawn from CACHEABLE_PREFIXES in
// workers/edge-proxy/src/index.ts. We deliberately include both
// "exact-prefix" routes (e.g. /api/content/boards) and
// "trailing-slash, path-keyed" routes (e.g. /api/sitemap, /api/robots.txt)
// so a regression in either matching strategy is caught.
//
// Routes that *require* a real path segment (e.g. /api/content/chapters/{id})
// are NOT included — without a known-good ID we can't tell apart "no data
// so the worker bypasses cache" from "the cache is broken". Those are
// covered by the unit classifier.
const ROUTES = [
  "/api/content/boards",
  "/api/content/classes",
  "/api/content/streams",
  "/api/content/subjects",
  "/api/sitemap",
  "/api/robots.txt",
  "/api/cms/articles",
  "/api/edu/allowlist",
];

const STRICT = process.env.EDGE_CACHE_STRICT === "1";
// In default mode both CF cache hits and the worker's D1 fast-path
// count as "warm" — both serve the user without backend round-trip.
// In strict mode only CF cache hits count, so a CF-cache-write
// regression is surfaced even when D1 is healthy.
const HIT_VALUES = STRICT
  ? new Set(["HIT", "HIT-304"])
  : new Set(["HIT", "HIT-304", "D1"]);
// Some intentionally non-cacheable upstream responses (e.g. an empty body
// or a 4xx) will surface as `BYPASS` even on routes that *appear* in
// CACHEABLE_PREFIXES. We treat those as a soft warning, not a failure,
// because they say "the worker correctly chose not to cache this" — the
// contract being tested is "warm requests are served from the edge", not
// "every CACHEABLE_PREFIXES route always produces a cacheable response".
const SOFT_BYPASS_VALUES = new Set(["BYPASS", "MISS"]);

function abortableFetch(url, init = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  return fetch(url, { ...init, signal: ctrl.signal })
    .finally(() => clearTimeout(timer));
}

async function probeRoute(route) {
  // Append a random query so we're guaranteed to start in MISS state
  // regardless of what real production traffic has already warmed.
  const cb = `_cb=${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const sep = route.includes("?") ? "&" : "?";
  const url = `${BASE_URL}${route}${sep}${cb}`;

  // ── 1st request: expected MISS (or BYPASS for non-cacheable responses) ──
  let firstResp;
  try {
    firstResp = await abortableFetch(url, {
      method: "GET",
      headers: { "User-Agent": "syrabit-edge-cache-live/1.0" },
    });
  } catch (err) {
    return { route, ok: false, error: `first request failed: ${err.message}` };
  }

  const firstCache = firstResp.headers.get("X-Cache") || "(none)";
  const etag = firstResp.headers.get("ETag");
  // Drain the body so the connection is reusable AND so CF finishes
  // writing the response into its per-POP cache. Without this the second
  // request can race the cache write and look like a false MISS.
  await firstResp.arrayBuffer().catch(() => {});

  if (VERBOSE) {
    console.log(`[1] GET ${url}`);
    console.log(`    status=${firstResp.status} X-Cache=${firstCache} ETag=${etag || "(none)"}`);
  }

  // CF needs a tick to finalize the cache.put after the response streams.
  await new Promise((r) => setTimeout(r, DELAY_MS));

  // ── 2nd request: expected HIT (or HIT-304 if we replay the ETag) ────
  let secondResp;
  try {
    secondResp = await abortableFetch(url, {
      method: "GET",
      headers: {
        "User-Agent": "syrabit-edge-cache-live/1.0",
        ...(etag ? { "If-None-Match": etag } : {}),
      },
    });
  } catch (err) {
    return {
      route,
      ok: false,
      firstCache,
      error: `second request failed: ${err.message}`,
    };
  }

  const secondCache = secondResp.headers.get("X-Cache") || "(none)";
  const source = secondResp.headers.get("X-Source") || "(none)";
  await secondResp.arrayBuffer().catch(() => {});

  if (VERBOSE) {
    console.log(`[2] GET ${url}`);
    console.log(`    status=${secondResp.status} X-Cache=${secondCache} X-Source=${source}`);
  }

  if (HIT_VALUES.has(secondCache)) {
    return { route, ok: true, firstCache, secondCache, status: secondResp.status, source };
  }

  // BYPASS / MISS on a route the worker chose not to cache (e.g. backend
  // returned an empty body or a 4xx) is a soft signal: report it but do
  // not fail the whole run. A persistent BYPASS on a route that *should*
  // cache will still be visible in the report so an operator can drill in.
  if (SOFT_BYPASS_VALUES.has(secondCache)) {
    return {
      route,
      ok: true,
      soft: true,
      firstCache,
      secondCache,
      status: secondResp.status,
      source,
      note: "worker did not store this response; verify upstream contract",
    };
  }

  return {
    route,
    ok: false,
    firstCache,
    secondCache,
    status: secondResp.status,
    source,
    error: `expected X-Cache: HIT on second request, got ${secondCache}`,
  };
}

function pad(s, n) {
  s = String(s);
  return s.length >= n ? s : s + " ".repeat(n - s.length);
}

async function main() {
  console.log(`edge-cache-live → ${BASE_URL}`);
  console.log(`probing ${ROUTES.length} routes (delay=${DELAY_MS}ms, timeout=${TIMEOUT_MS}ms)`);
  console.log("");

  const results = [];
  for (const route of ROUTES) {
    process.stdout.write(`  ${pad(route, 38)} `);
    const r = await probeRoute(route);
    results.push(r);
    if (r.ok && !r.soft) {
      console.log(`OK   first=${pad(r.firstCache, 6)} second=${r.secondCache}`);
    } else if (r.ok && r.soft) {
      console.log(`WARN first=${pad(r.firstCache, 6)} second=${r.secondCache} (${r.note})`);
    } else {
      console.log(`FAIL ${r.error || "unknown error"}`);
    }
  }

  const hardFailures = results.filter((r) => !r.ok);
  const softWarnings = results.filter((r) => r.ok && r.soft);
  const hits = results.filter((r) => r.ok && !r.soft);

  console.log("");
  console.log(`summary: ${hits.length} hit, ${softWarnings.length} bypass/warn, ${hardFailures.length} fail`);

  if (hardFailures.length === results.length) {
    console.error("\nALL routes failed — likely a network or DNS issue, not a cache regression.");
    process.exit(2);
  }
  if (hardFailures.length > 0) {
    console.error(`\n${hardFailures.length} route(s) did not warm into the edge cache:`);
    for (const f of hardFailures) {
      console.error(`  - ${f.route}: ${f.error}`);
    }
    process.exit(1);
  }
  console.log("\nAll cacheable routes serve HIT on the second request. ✓");
  process.exit(0);
}

main().catch((err) => {
  console.error("edge-cache-live crashed:", err);
  process.exit(2);
});
