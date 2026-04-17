import React, { Suspense } from "react";
import { renderToString } from "react-dom/server";
import { StaticRouter } from "react-router-dom";
import { AppShell, AppRoutes, queryClient } from "./App";

// Render the real React tree for a given URL into a string. Used at
// build time by scripts/prerender-library.mjs to produce the static
// HTML snapshot served by Cloudflare Pages for /library. (Task #382)
//
// The same provider stack (`AppShell`) is used in both client and
// server so the prerendered DOM is byte-identical to React's first
// client render after `hydrateRoot` adopts it.
export function renderRoute({ url, bundleSlim } = {}) {
  if (bundleSlim) {
    queryClient.setQueryData(["library-bundle-slim"], bundleSlim);
  }

  const errors = [];
  const html = renderToString(
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

  return { html, errors };
}

export default renderRoute;
