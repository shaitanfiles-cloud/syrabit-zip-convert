import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App";
import ReactGA from "react-ga4";
import { log } from "@/utils/logger";

const _ga4Id = import.meta.env.VITE_GA4_ID;
if (_ga4Id) {
  ReactGA.initialize(_ga4Id);
} else if (import.meta.env.DEV) {
  log.warn("[GA4] VITE_GA4_ID not set — Google Analytics disabled", { hint: "Set VITE_GA4_ID in Replit secrets to activate" });
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/sw.js")
      .then((reg) => {
        log.info("[SW] Service worker registered", { scope: reg.scope });
        reg.addEventListener("updatefound", () => {
          const worker = reg.installing;
          if (worker) {
            worker.addEventListener("statechange", () => {
              if (worker.state === "installed" && navigator.serviceWorker.controller) {
                log.info("[SW] New version available — reloading", {});
                window.location.reload();
              }
            });
          }
        });
      })
      .catch((err) => log.warn("[SW] Registration failed", { error: err.message }));
  });
} else if ("serviceWorker" in navigator && !import.meta.env.PROD) {
  navigator.serviceWorker.getRegistrations().then((regs) => {
    regs.forEach((r) => r.unregister());
  });
}
