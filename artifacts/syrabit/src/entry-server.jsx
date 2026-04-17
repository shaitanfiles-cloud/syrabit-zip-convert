import React, { Suspense } from "react";
import { renderToString } from "react-dom/server";
import { StaticRouter } from "react-router-dom";
import { AppShell, AppRoutes, queryClient } from "./App";

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
export function renderRoute({ url, bundleSlim, seed } = {}) {
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
