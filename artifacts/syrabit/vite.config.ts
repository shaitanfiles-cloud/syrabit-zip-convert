import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { visualizer } from "rollup-plugin-visualizer";
const port = Number(process.env.PORT || 25144);
const basePath = process.env.BASE_PATH ?? "/";

export default defineConfig(({ mode }) => ({
  base: basePath,
  plugins: [
    react(),
    visualizer({
      filename: "dist/stats.html",
      open: false,
      gzipSize: true,
      brotliSize: true,
      template: "treemap",
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
    },
    extensions: [".jsx", ".js", ".tsx", ".ts"],
  },
  server: {
    port,
    host: "0.0.0.0",
    allowedHosts: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        cookieDomainRewrite: "",
        cookiePathRewrite: { "*": "/" },
      },
    },
  },
  build: {
    outDir: path.resolve(import.meta.dirname, "dist"),
    emptyOutDir: true,
    modulePreload: { polyfill: true },
    target: "esnext",
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Kept in lock-step with `vite.config.js` — see that file for the
          // detailed comment on why pnpm path-name peer-dep encoding makes
          // naive `id.includes('react-dom')` style matchers wrong.
          if (!id.includes("node_modules")) return;
          const has = (pkg: string) => id.includes(`/node_modules/${pkg}/`);

          if (has("recharts") || /\/node_modules\/d3-[^/]+\//.test(id) || /\/node_modules\/victory-[^/]+\//.test(id) || id.includes("/node_modules/d3/")) return "charts";
          if (
            has("react-markdown") ||
            /\/node_modules\/(remark|rehype|micromark|mdast-util|unist-util|hast-util)-[^/]+\//.test(id) ||
            has("unified") || has("vfile") || has("devlop") || has("bail") ||
            has("trough") || has("character-entities") || has("character-entities-html4") ||
            has("character-entities-legacy") || has("character-reference-invalid") ||
            has("decode-named-character-reference") || has("zwitch") ||
            has("property-information") || has("space-separated-tokens") ||
            has("comma-separated-tokens") || has("html-void-elements") ||
            has("ccount") || has("escape-string-regexp") || has("longest-streak") ||
            has("markdown-table") || has("html-url-attributes")
          ) return "markdown";
          if (has("lucide-react")) return "icons";
          if (has("framer-motion") || has("motion-dom") || has("motion-utils")) return "framer";
          if (has("react-syntax-highlighter") || has("refractor") || has("prismjs") || has("highlight.js")) return "syntax";
          // React runtime kept together to avoid `react-dom <-> vendor`
          // circular chunk warning.
          if (
            id.includes("/node_modules/react-dom/") &&
            !/\/node_modules\/react-dom\/(server|static|profiling)/.test(id)
          ) return "react-dom";
          if (id.includes("/node_modules/scheduler/")) return "react-dom";
          if (
            id.includes("/node_modules/react/") ||
            id.includes("/node_modules/react-is/")
          ) return "react-dom";
          if (
            has("react-helmet") || has("react-helmet-async") ||
            has("react-hot-toast") || has("sonner") || has("cmdk") ||
            has("class-variance-authority") || has("clsx") || has("tailwind-merge")
          ) return "ui-utils";
          if (
            has("react-router") || has("react-router-dom") ||
            id.includes("/node_modules/@remix-run/") ||
            id.includes("/node_modules/@tanstack/") ||
            id.includes("/node_modules/@radix-ui/")
          ) return "vendor";
          if (id.includes("/node_modules/codemirror/") || id.includes("/node_modules/@codemirror/") || id.includes("/node_modules/@lezer/")) return "codemirror";
          if (id.includes("/node_modules/axios/")) return "axios";
        },
      },
    },
  },
  esbuild: mode === "production"
    ? { drop: ["console", "debugger"], target: "esnext" }
    : { target: "esnext" },
  define: {
    "process.env.NODE_ENV": JSON.stringify(mode),
    "__TRUSTPILOT_BU_ID__": JSON.stringify(process.env.TRUSTPILOT_BUSINESS_UNIT_ID || ""),
  },
}));
