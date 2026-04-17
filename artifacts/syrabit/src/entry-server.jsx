import React, { Suspense } from "react";
import { renderToString } from "react-dom/server";
import { StaticRouter } from "react-router-dom";
import { AppShell, AppRoutes, queryClient, preloadPageForKind } from "./App";

// Map a request URL to the prerendered route's hydration kind so we
// can pre-await the matching page chunk BEFORE renderToString runs.
// (Task #395 — the four prerendered pages are now React.lazy()d, and
// renderToString synchronously throws on suspended children.)
function kindFromUrl(url) {
  const p = (url || "/").split("?")[0];
  if (p === "/library" || p === "/browser") return "library";
  if (p === "/chat") return "chat";
  const segs = p.split("/").filter(Boolean);
  if (segs.length === 3) return "subject";
  if (segs.length >= 4) return "chapter";
  return null;
}

// Render the real React tree for a given URL into a string. Used at
// build time by scripts/prerender-library.mjs and
// scripts/prerender-routes.mjs to produce static HTML snapshots
// served by Cloudflare Pages. (Tasks #382, #385)
//
// `seed.queries`        — array of `{ key, data }` to prime React Query
//                         so useQuery hooks render their data on the
//                         first SSR pass (no skeleton).
// `seed.chapterPreload` — single chapter payload mirrored into a
//                         server-only global so ChapterPage's local-
//                         state initializer picks it up without going
//                         through React Query (ChapterPage uses
//                         useState + useEffect, not useQuery).
//
// `bundleSlim` is kept as a back-compat shortcut for
// scripts/prerender-library.mjs.
export async function renderRoute({ url, bundleSlim, seed } = {}) {
  if (bundleSlim) {
    queryClient.setQueryData(["library-bundle-slim"], bundleSlim);
  }
  if (seed?.queries) {
    for (const { key, data } of seed.queries) {
      try { queryClient.setQueryData(key, data); } catch {}
    }
  }
  if (seed?.chapterPreload) {
    globalThis.__SSR_CHAPTER_PRELOAD__ = seed.chapterPreload;
  }

  // Pre-await the page chunk so React.lazy() resolves synchronously
  // inside renderToString — otherwise SSR aborts with
  // "A component suspended while responding to synchronous input."
  const kind = kindFromUrl(url);
  if (kind) {
    try { await preloadPageForKind(kind); } catch {}
  }

  const errors = [];
  let html = "";
  try {
    html = renderToString(
      <AppShell ssr>
        <StaticRouter location={url || "/library"}>
          <AppRoutes />
        </StaticRouter>
      </AppShell>,
      {
        onError(err) {
          errors.push(err);
        },
      },
    );
  } finally {
    if (seed?.chapterPreload) delete globalThis.__SSR_CHAPTER_PRELOAD__;
  }

  return { html, errors };
}

export default renderRoute;
