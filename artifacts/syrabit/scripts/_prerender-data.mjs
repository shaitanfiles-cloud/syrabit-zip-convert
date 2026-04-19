// Task #535: shared backend bundle + traffic fetcher.
//
// All four prerender scripts (prerender-library, prerender-chat,
// prerender-routes, prerender-static-routes) need the same library
// bundle and (in the case of prerender-routes) the traffic ranking.
// Before this module they each issued their own fetch, which on a
// slow / cold Railway backend doubled or tripled the build time.
//
// This module fetches once and caches the JSON on disk under
// node_modules/.cache/prerender/ so a second invocation in the same
// build is a synchronous file read. Cache is process-global too — if
// the orchestrator (scripts/build.mjs) calls warmCache() before
// spawning the per-page scripts, the on-disk file is the only network
// hop the build pipeline pays.
//
// Soft-fails: if the backend is unreachable, the helper returns null
// and callers should fall back to whatever they did before (SPA shell,
// bundle-order ranking, etc). The build never hard-fails on a
// transient network blip.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoCacheDir = path.resolve(
  __dirname,
  "..",
  "node_modules",
  ".cache",
  "prerender",
);

export const BACKEND = (
  process.env.PRERENDER_BACKEND_URL ||
  process.env.VITE_BACKEND_URL ||
  "https://syrabit.ai"
).replace(/\/$/, "");

export const FETCH_TIMEOUT_MS = (() => {
  const raw = process.env.PRERENDER_FETCH_TIMEOUT_MS;
  const n = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isFinite(n) && n >= 500 && n <= 60_000 ? n : 3000;
})();

// Cache TTL — anything younger than this is reused without re-fetching.
// Default 10 minutes covers a single build comfortably; old entries
// are ignored automatically so cross-build staleness is bounded.
const CACHE_TTL_MS = 10 * 60 * 1000;

function ensureCacheDir() {
  try {
    fs.mkdirSync(repoCacheDir, { recursive: true });
  } catch {
    // ignore — we'll fall back to network only.
  }
}

function cachePath(name) {
  return path.join(repoCacheDir, `${name}.json`);
}

function readCache(name) {
  try {
    const file = cachePath(name);
    const stat = fs.statSync(file);
    if (Date.now() - stat.mtimeMs > CACHE_TTL_MS) return null;
    return JSON.parse(fs.readFileSync(file, "utf-8"));
  } catch {
    return null;
  }
}

function writeCache(name, value) {
  ensureCacheDir();
  try {
    fs.writeFileSync(cachePath(name), JSON.stringify(value));
  } catch {
    // best-effort
  }
}

async function fetchJson(url, timeoutMs = FETCH_TIMEOUT_MS) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      signal: ctrl.signal,
      headers: { Accept: "application/json" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// In-memory promise cache so concurrent callers in the same process
// share a single in-flight fetch (the disk cache covers cross-process).
const inflight = new Map();

async function fetchOnce(name, url) {
  const cached = readCache(name);
  if (cached !== null) return cached;
  if (inflight.has(name)) return inflight.get(name);
  const p = (async () => {
    try {
      const data = await fetchJson(url);
      writeCache(name, data);
      return data;
    } catch (err) {
      console.warn(
        `[prerender-data] ${name} fetch failed (${err.message}); returning null`,
      );
      return null;
    } finally {
      inflight.delete(name);
    }
  })();
  inflight.set(name, p);
  return p;
}

export async function loadLibraryBundle() {
  return fetchOnce(
    "library-bundle",
    `${BACKEND}/api/content/library-bundle?slim=1`,
  );
}

export async function loadTopRoutes(days = 30, limit = 1000) {
  return fetchOnce(
    `top-routes-${days}-${limit}`,
    `${BACKEND}/api/analytics/top-routes?days=${days}&limit=${limit}`,
  );
}

// Convenience for the orchestrator: pre-warm both caches in parallel.
// Returns an object with whichever fetches succeeded.
export async function warmCache({ days = 30 } = {}) {
  const [bundle, traffic] = await Promise.all([
    loadLibraryBundle(),
    loadTopRoutes(days),
  ]);
  return { bundle, traffic };
}

export function clearCache() {
  try {
    fs.rmSync(repoCacheDir, { recursive: true, force: true });
  } catch {
    // ignore
  }
}
