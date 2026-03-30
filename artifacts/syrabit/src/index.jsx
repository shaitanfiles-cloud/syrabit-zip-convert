import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App";
import ReactGA from "react-ga4";

const _ga4Id = import.meta.env.VITE_GA4_ID;
if (_ga4Id) {
  ReactGA.initialize(_ga4Id);
} else if (import.meta.env.DEV) {
  console.warn("[GA4] VITE_GA4_ID not set — Google Analytics disabled");
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/sw.js")
      .then((reg) => {
        console.log("[SW] Registered:", reg.scope);
        reg.addEventListener("updatefound", () => {
          const worker = reg.installing;
          if (worker) {
            worker.addEventListener("statechange", () => {
              if (worker.state === "installed" && navigator.serviceWorker.controller) {
                console.log("[SW] New version available — reloading");
                window.location.reload();
              }
            });
          }
        });
      })
      .catch((err) => console.warn("[SW] Registration failed:", err));
  });
} else if ("serviceWorker" in navigator && process.env.NODE_ENV !== "production") {
  navigator.serviceWorker.getRegistrations().then((regs) => {
    regs.forEach((r) => r.unregister());
  });
}
