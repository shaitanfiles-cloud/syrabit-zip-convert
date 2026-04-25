/**
 * Task #887 — typed view of `monitored-urls.json`, the canonical registry
 * of every backend URL/path the worker (or its companion deploy infra)
 * hard-codes outside the FastAPI app.
 *
 * Why this exists
 * ---------------
 * Task #877 was a 56-hour outage caused by `synthetic-probe.ts` hard-coding
 * `/admin/diagnostics` (no `/api` prefix) while the FastAPI router was
 * mounted under `prefix="/api"`. Every probe 404'd, the watchdog stayed
 * dark, and nobody noticed until someone scrolled production logs.
 *
 * The fix surface (Task #887) is the JSON manifest at
 * `workers/edge-proxy/monitored-urls.json` plus the pytest drift check
 * at `artifacts/syrabit-backend/tests/test_monitoring_url_drift.py` that
 * iterates the manifest and asserts every backend path resolves to a
 * real route in the live FastAPI OpenAPI schema. This module is the
 * runtime side: probes import the canonical strings from here so that
 * the value the test validates is *literally the same value* the worker
 * sends — no transcription drift between the manifest and the code.
 *
 * If you add a new probe / healthcheck / hard-coded backend URL anywhere
 * in this worker, register it in `monitored-urls.json` and reference it
 * from this module (or via `getBackendPath()` below). The drift test
 * gates merges; you cannot merge a hard-coded URL that is not in the
 * manifest if it ships through this module.
 */

import manifest from "../monitored-urls.json";

export interface MonitoredBackendPath {
  path: string;
  match: "exact" | "prefix";
  rationale: string;
  registered_in: string[];
}

export interface MonitoredExternalUrl {
  url: string;
  rationale: string;
  registered_in: string[];
}

export interface MonitoredUrlsManifest {
  $schema_version: number;
  backend_paths: MonitoredBackendPath[];
  intentionally_external: MonitoredExternalUrl[];
}

const MANIFEST = manifest as unknown as MonitoredUrlsManifest;

export const MONITORED_URLS: MonitoredUrlsManifest = MANIFEST;

/**
 * Look up a backend path by its canonical string. Throws if the path is
 * not registered in the manifest — this turns "I forgot to update the
 * manifest" into a startup error instead of a silent 404 in production.
 *
 * Use this from probe modules so the value they fetch and the value the
 * drift test validates are the same Object reference.
 */
export function getBackendPath(path: string): MonitoredBackendPath {
  const found = MANIFEST.backend_paths.find((p) => p.path === path);
  if (!found) {
    throw new Error(
      `[monitored-urls] backend path ${JSON.stringify(path)} is not registered in ` +
      `workers/edge-proxy/monitored-urls.json. Add it (with a one-line rationale) ` +
      `before hard-coding it in the worker — the Task #887 drift check requires it.`,
    );
  }
  return found;
}

/**
 * Look up an intentionally-external URL by its canonical string. Throws
 * if the URL is not registered. Same rationale as `getBackendPath`.
 */
export function getExternalUrl(url: string): MonitoredExternalUrl {
  const found = MANIFEST.intentionally_external.find((u) => u.url === url);
  if (!found) {
    throw new Error(
      `[monitored-urls] external URL ${JSON.stringify(url)} is not registered in ` +
      `workers/edge-proxy/monitored-urls.json. Add it (with a one-line rationale ` +
      `explaining why it is NOT a FastAPI route) before hard-coding it in the ` +
      `worker — the Task #887 drift check requires it.`,
    );
  }
  return found;
}

// ─── Convenience re-exports for the well-known monitored paths ─────────
//
// Probe modules import these constants directly so the worker and the
// drift test cannot disagree about the canonical string. Add a constant
// here whenever you register a new entry in `monitored-urls.json`.

/** Synthetic-probe target — see `synthetic-probe.ts`. */
export const SYNTHETIC_PROBE_PATH = getBackendPath("/api/admin/diagnostics").path;

/** cf-block-probe target — see `cf-block-probe.ts`. */
export const CF_BLOCK_PROBE_DEFAULT_URL = getExternalUrl("https://syrabit.ai/").url;
