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
          if (id.includes("node_modules/react-dom")) return "react-dom";
          if (id.includes("node_modules/react/") || id.includes("node_modules/scheduler")) return "vendor";
          if (id.includes("node_modules/react-router-dom") || id.includes("node_modules/react-router/") || id.includes("node_modules/@remix-run")) return "router";
          if (id.includes("node_modules/@tanstack/react-query")) return "query";
          if (id.includes("node_modules/framer-motion")) return "framer";
          if (id.includes("node_modules/lucide-react")) return "icons";
          if (id.includes("node_modules/@radix-ui")) return "radix";
          if (id.includes("node_modules/react-markdown") || id.includes("node_modules/remark-") || id.includes("node_modules/rehype-") || id.includes("node_modules/unified") || id.includes("node_modules/mdast-") || id.includes("node_modules/hast-") || id.includes("node_modules/micromark") || id.includes("node_modules/devlop") || id.includes("node_modules/vfile")) return "markdown";
          if (id.includes("node_modules/recharts") || id.includes("node_modules/d3-") || id.includes("node_modules/victory-")) return "charts";
          if (id.includes("node_modules/react-helmet-async")) return "seo";
          if (id.includes("node_modules/sonner")) return "ui-extras";
          if (id.includes("node_modules/codemirror") || id.includes("node_modules/@codemirror") || id.includes("node_modules/@lezer")) return "codemirror";
          if (id.includes("node_modules/axios")) return "axios";
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
