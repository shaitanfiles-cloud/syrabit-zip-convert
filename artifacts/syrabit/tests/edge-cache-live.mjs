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
 * What counts as a pass?
 * ----------------------
 * By default ONLY `X-Cache: HIT` and `HIT-304` (the latter when an
 * If-None-Match header is replayed) on the second request count as a
 * pass. Every other outcome — `MISS`, `BYPASS`, or the worker's `D1`
 * fast-path — is a failure, because the explicit task contract is
 * "assert X-Cache: HIT on the second response".
 *
 * The worker also has a D1 fast-path (`X-Cache: D1`) that serves the
 * same routes directly from the D1 replica. That path is fast, but it
 * means the response did NOT go through CF's per-POP edge cache, so it
 * shouldn't make a regression-gating script pass. If the D1 fast-path
 * is intentionally preferred over CF cache for a route, remove that
 * route from the probe set.
 *
 * Diagnostic mode (non-gating)
 * ----------------------------
 * Set `EDGE_CACHE_LENIENT=1` to additionally treat `D1` as a pass and
 * `MISS`/`BYPASS` as soft warnings. Use this when investigating
 * production behavior interactively — never in CI, since it hides the
 * regressions this script exists to catch.
 *
 * Exit codes
 * ----------
 *   0 — every probed route served `HIT`/`HIT-304` on the 2nd request.
 *   1 — at least one route did not warm into the CF edge cache.
 *   2 — network/setup failure (all routes errored).
 *
 * Environment
 * -----------
 *   EDGE_CACHE_TEST_URL    Base URL to probe (default https://api.syrabit.ai)
 *   EDGE_CACHE_DELAY_MS    Gap between MISS and HIT request in ms (default 250)
 *   EDGE_CACHE_TIMEOUT_MS  Per-request timeout in ms (default 10000)
 *   EDGE_CACHE_VERBOSE     Set to "1" to print full per-request headers
 *   EDGE_CACHE_LENIENT     Set to "1" for diagnostic mode (NEVER in CI)
 *
 * CI usage
 * --------
 * Wired into .github/workflows/edge-cache-live.yml as a nightly cron +
 * workflow_dispatch job. The CI workflow explicitly clears
 * EDGE_CACHE_LENIENT and refuses to run if it leaks in from a parent
 * environment. Run locally with:
 *   pnpm --filter @workspace/syrabit run test:edge-cache
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

// Default = strict gating: only CF edge cache hits count as a pass.
// Lenient = diagnostic mode: also accept the worker's D1 fast-path
// (`X-Cache: D1`) and downgrade `MISS`/`BYPASS` to soft warnings.
// Lenient is for interactive investigation only; CI must stay strict
// so a missing CF cache write never silently passes.
const LENIENT = process.env.EDGE_CACHE_LENIENT === "1";
const HIT_VALUES = LENIENT
  ? new Set(["HIT", "HIT-304", "D1"])
  : new Set(["HIT", "HIT-304"]);
// In lenient mode, MISS/BYPASS become soft warnings (printed but
// non-gating). In strict mode (the default) they are hard failures.
const SOFT_BYPASS_VALUES = LENIENT
  ? new Set(["BYPASS", "MISS"])
  : new Set();

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
      note: "worker did not store this response; cache regression to investigate",
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
  console.log(
    `summary: ${hits.length} hit, ${softWarnings.length} bypass/warn, ${hardFailures.length} fail` +
      (LENIENT ? "  (LENIENT mode — diagnostic only)" : ""),
  );

  if (hardFailures.length === results.length) {
    console.error("\nALL routes failed — likely a network or DNS issue, not a cache regression.");
    process.exit(2);
  }
  if (hardFailures.length > 0) {
    console.error(`\n${hardFailures.length} route(s) did not warm into the edge cache:`);
    for (const f of hardFailures) {
      console.error(`  - ${f.route}: ${f.error || `expected X-Cache: HIT on second request, got ${f.secondCache}`}`);
    }
    process.exit(1);
  }
  if (softWarnings.length > 0) {
    console.log(
      `\n${hits.length} route(s) served HIT on the second request; ${softWarnings.length} returned BYPASS/MISS (soft warnings — re-run without EDGE_CACHE_LENIENT to gate on them).`,
    );
  } else {
    console.log("\nAll cacheable routes returned X-Cache: HIT on the second request. ✓");
  }
  process.exit(0);
}

main().catch((err) => {
  console.error("edge-cache-live crashed:", err);
  process.exit(2);
});
