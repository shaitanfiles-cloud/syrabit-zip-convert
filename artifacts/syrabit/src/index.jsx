import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App";
import { initWebVitals } from "./utils/webVitals";

const rootEl = document.getElementById("root");
const tree = (
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// /library and /chat ship a fully prerendered React tree inside #root.
// Hydrate in place so React adopts the existing DOM (no remount, no flash).
// Every other route still mounts the SPA via createRoot.
// (Task #382 for /library, Task #387 for /chat.)
const hasPrerender =
  rootEl &&
  rootEl.firstElementChild != null &&
  (rootEl.dataset.hydrate === "library" ||
    rootEl.dataset.hydrate === "chat");

if (hasPrerender) {
  ReactDOM.hydrateRoot(rootEl, tree);
  if (typeof window !== "undefined") {
    window.__SYRABIT_HYDRATED__ = true;
  }
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
