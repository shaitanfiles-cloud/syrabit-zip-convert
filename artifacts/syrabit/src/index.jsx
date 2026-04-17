import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App, { preloadPageForKind } from "./App";
import { initWebVitals } from "./utils/webVitals";
import Analytics from "./utils/analytics";

const rootEl = document.getElementById("root");
const tree = (
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Prerendered routes (/library, /chat, /:board/:class/:subject,
// /:board/:class/:subject/:chapter) ship a fully prerendered React
// tree inside #root tagged with `data-hydrate="<kind>"`. Hydrate in
// place so React adopts the existing DOM — no remount, no flash.
// Every other route still mounts the SPA via createRoot.
// (Tasks #382, #385, #387, #395)
const PRERENDER_KINDS = new Set(["library", "chat", "subject", "chapter"]);
const hasPrerender =
  rootEl &&
  rootEl.firstElementChild != null &&
  PRERENDER_KINDS.has(rootEl.dataset.hydrate);

if (hasPrerender) {
  // Task #395: Each prerendered page is now its own JS chunk
  // (LibraryPage, ChatPage, SubjectLandingPage, ChapterPage). We MUST
  // wait for the matching chunk to load + prime React.lazy's payload
  // BEFORE invoking hydrateRoot — otherwise React renders a Suspense
  // fallback into #root, blowing away the SSR snapshot and producing
  // a hydration mismatch. The prerendered HTML emits a
  // `<link rel="modulepreload">` for the page chunk so it fetches in
  // parallel with this entry chunk; the await below is just the
  // join point.
  const kind = rootEl.dataset.hydrate;
  // Task #405: when the page-chunk preload import() rejects (chunk
  // 404 from a stale build, network blip, integrity mismatch), don't
  // swallow it. We still proceed to hydrateRoot — React.lazy will
  // fall back to its Suspense boundary, and DeferredFallback's
  // recovery hint will surface a refresh prompt after a few seconds.
  // We also report the failure so we can spot regressions in
  // production.
  function reportPreloadFailure(err) {
    try {
      const detail = {
        kind,
        path: window.location.pathname,
        message: err?.message || String(err),
        name: err?.name || "Error",
      };
      // Mark for the recovery hint + any e2e harness.
      window.__SYRABIT_HYDRATE_PRELOAD_FAILED__ = detail;
      try {
        window.dispatchEvent(
          new CustomEvent("syrabit:hydrate-preload-failed", { detail }),
        );
      } catch {}
      try { Analytics.hydratePreloadFailed?.(detail); } catch {}
      // Always log — preload failures are actionable for ops.
       
      console.warn("[hydrate] page-chunk preload failed", detail);
    } catch {
      /* never let reporting itself break hydration */
    }
  }

  Promise.resolve(preloadPageForKind(kind))
    .catch((err) => reportPreloadFailure(err))
    .then(() => {
      ReactDOM.hydrateRoot(rootEl, tree);
      if (typeof window !== "undefined") {
        window.__SYRABIT_HYDRATED__ = true;
      }
    });
} else {
  ReactDOM.createRoot(rootEl).render(tree);
}

// Remove the pre-hydration shell once React has painted its first frame.
// This only runs for routes that did not get a real prerendered tree
// (i.e. everything except /library on the static build).
function removeShell() {
  const shell = document.getElementById("__shell");
  if (shell && shell.parentNode) shell.parentNode.removeChild(shell);
}

if (!hasPrerender) {
  requestAnimationFrame(() => {
    requestAnimationFrame(removeShell);
  });
} else {
  // Belt & braces: a stale build of /library could still have a shell
  // sibling around #root — drop it on the next frame.
  requestAnimationFrame(removeShell);
}


if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/sw.js", { updateViaCache: "none" })
      .then((reg) => {
        reg.update();
        setInterval(() => reg.update(), 60 * 60 * 1000);

        if (navigator.serviceWorker.controller) {
          navigator.serviceWorker.controller.postMessage("precacheApi");
        }

        reg.addEventListener("updatefound", () => {
          const worker = reg.installing;
          if (worker) {
            worker.addEventListener("statechange", () => {
              if (worker.state === "installed" && navigator.serviceWorker.controller) {
                worker.postMessage("skipWaiting");
              }
              if (worker.state === "activated") {
                worker.postMessage("precacheApi");
              }
            });
          }
        });
      })
      .catch(() => {});

    let refreshing = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (!refreshing) {
        refreshing = true;
        window.location.reload();
      }
    });
  });
} else if ("serviceWorker" in navigator && !import.meta.env.PROD) {
  navigator.serviceWorker.getRegistrations().then((regs) => {
    regs.forEach((r) => r.unregister());
  });
}

initWebVitals();
