// Statically prerender the /library page (Task #382).
//
// Build the slim library bundle into a real React SSR snapshot of the
// /library route, then write `dist/library/index.html` so Cloudflare
// Pages serves it directly. The shipped HTML contains the full React
// tree inside `#root` (with `data-hydrate="library"`), and the
// browser bundle calls `hydrateRoot` on it instead of `createRoot` —
// React adopts the existing DOM, no remount, no flash.
//
// Steps:
//   1. Read the post-build `dist/index.html` (already has CSS/JS asset
//      refs and modulepreload hints injected).
//   2. Fetch the slim library bundle from the backend so the SSR
//      render produces real subject cards, not a loading skeleton.
//      Falls back to the legacy data-less shell on failure so the
//      build never breaks.
//   3. Import the SSR build output (`dist-ssr/entry-server.js`),
//      render the /library route to a string, and inject it into
//      `#root` (replacing the empty placeholder div that the SPA
//      bootstrap uses).
//   4. Inject `<script>window.__LIBRARY_BUNDLE__=…</script>` BEFORE
//      the main module script so React Query is seeded with the same
//      data the SSR used — guarantees first client render matches the
//      prerendered DOM and hydrateRoot succeeds without a mismatch.
//   5. Update <title>, <meta description>, OG/Twitter tags, and
//      <link rel=canonical> for /library.

import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, "..", "dist");
const distSsrDir = path.resolve(__dirname, "..", "dist-ssr");
const srcHtml = path.join(distDir, "index.html");
const outDir = path.join(distDir, "library");
const outHtml = path.join(outDir, "index.html");
const ssrEntry = path.join(distSsrDir, "entry-server.js");

const BACKEND =
  process.env.PRERENDER_BACKEND_URL ||
  process.env.VITE_BACKEND_URL ||
  "https://syrabit.ai";

const FETCH_TIMEOUT_MS = 8000;
const MAX_PRERENDER_CARDS = 12;

const TITLE =
  "Assamboard Subject Library — Notes, MCQs, Definitions & Exam Prep";
const CANONICAL = "https://syrabit.ai/library";
const DESCRIPTION =
  "Explore Assam Board Class 11-12 and Degree subjects. AI-powered notes, MCQs, definitions, and exam preparation for Assam students.";

function escapeHtml(s = "") {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function fetchBundle() {
  const url = `${BACKEND.replace(/\/$/, "")}/api/content/library-bundle?slim=1`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      signal: ctrl.signal,
      headers: { Accept: "application/json" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(
      `[prerender-library] backend fetch failed (${err.message}); falling back to data-less shell`,
    );
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function rewriteHead(html) {
  html = html.replace(
    /<title>[^<]*<\/title>/,
    `<title>${escapeHtml(TITLE)}</title>`,
  );
  html = html.replace(
    /<meta name="description" content="[^"]*"\s*\/?>(\n)?/,
    `<meta name="description" content="${escapeHtml(DESCRIPTION)}" />\n    `,
  );
  html = html.replace(
    /<link rel="canonical" href="[^"]*"\s*\/?>(\n)?/,
    `<link rel="canonical" href="${CANONICAL}" />\n    `,
  );
  html = html.replace(
    /<meta property="og:url" content="[^"]*"\s*\/?>/,
    `<meta property="og:url" content="${CANONICAL}" />`,
  );
  html = html.replace(
    /<meta property="og:title" content="[^"]*"\s*\/?>/,
    `<meta property="og:title" content="${escapeHtml(TITLE)}" />`,
  );
  html = html.replace(
    /<meta property="og:description" content="[^"]*"\s*\/?>/,
    `<meta property="og:description" content="${escapeHtml(DESCRIPTION)}" />`,
  );
  html = html.replace(
    /<meta name="twitter:title" content="[^"]*"\s*\/?>/,
    `<meta name="twitter:title" content="${escapeHtml(TITLE)}" />`,
  );
  html = html.replace(
    /<meta name="twitter:description" content="[^"]*"\s*\/?>/,
    `<meta name="twitter:description" content="${escapeHtml(DESCRIPTION)}" />`,
  );
  return html;
}

// Trim the bundle to only fields LibraryPage actually reads, so the
// inlined <script> stays small (every byte hurts mobile LCP).
function slimBundleForClient(bundle) {
  if (!bundle) return null;
  const pick = (obj, keys) => {
    const out = {};
    for (const k of keys) if (obj[k] !== undefined) out[k] = obj[k];
    return out;
  };
  return {
    boards: (bundle.boards || []).map((b) => pick(b, ["id", "name", "slug"])),
    classes: (bundle.classes || []).map((c) =>
      pick(c, ["id", "name", "slug", "board_id"]),
    ),
    streams: (bundle.streams || []).map((s) =>
      pick(s, ["id", "name", "slug", "class_id"]),
    ),
    subjects: (bundle.subjects || []).map((s) =>
      pick(s, [
        "id",
        "name",
        "slug",
        "description",
        "stream_id",
        "icon",
        "color",
        "chapter_count",
      ]),
    ),
    chapter_count: bundle.chapter_count ?? bundle.chapters?.length ?? 0,
  };
}

async function main() {
  if (!fs.existsSync(srcHtml)) {
    console.warn(
      `[prerender-library] dist/index.html not found at ${srcHtml}; skipping`,
    );
    return;
  }

  const bundle = await fetchBundle();
  const slim = slimBundleForClient(bundle);

  let html = fs.readFileSync(srcHtml, "utf-8");

  // Locate the boundary between the pre-hydration shell block and #root.
  const startMarker =
    `<noscript><style>#__shell{display:none!important}</style></noscript>`;
  const startIdx = html.indexOf(startMarker);
  const rootRe = /<div id="root"[^>]*><\/div>/;
  const rootMatch = html.match(rootRe);
  if (startIdx === -1 || !rootMatch) {
    throw new Error(
      "[prerender-library] could not locate shell markers in dist/index.html — structure changed?",
    );
  }

  // Real SSR is mandatory. A bundle fetch failure is recoverable —
  // we still SSR with empty data and ship the React skeleton (which
  // hydrates correctly). But a missing/broken SSR build is a HARD
  // failure: the task contract is that /library ships as prebuilt
  // hydrated HTML, not a JS-only shell. (Task #382 — architect review)
  if (!fs.existsSync(ssrEntry)) {
    throw new Error(
      `[prerender-library] required SSR build missing at ${ssrEntry}; ` +
        `build pipeline must run "vite build --ssr src/entry-server.jsx --outDir dist-ssr" first`,
    );
  }

  // Minimal browser-API polyfills so the bundled SSR module can boot
  // in Node — the app guards most window/document access behind
  // useEffect, but a handful of helpers (anon-id init in utils/api,
  // language context init, etc.) call localStorage at module load.
  if (typeof globalThis.localStorage === "undefined") {
    const noop = () => null;
    globalThis.localStorage = {
      getItem: noop, setItem: () => {}, removeItem: () => {},
      clear: () => {}, key: noop, length: 0,
    };
    globalThis.sessionStorage = globalThis.localStorage;
  }

  const mod = await import(pathToFileURL(ssrEntry).href);
  const renderRoute = mod.renderRoute || mod.default;
  if (typeof renderRoute !== "function") {
    throw new Error(
      "[prerender-library] entry-server.js did not export renderRoute()",
    );
  }
  const out = renderRoute({ url: "/library", bundleSlim: slim });
  if (Array.isArray(out?.errors) && out.errors.length) {
    for (const e of out.errors) {
      console.warn(
        "[prerender-library] SSR onError:",
        e?.stack || e?.message || e,
      );
    }
  }
  const ssrHtml = out?.html;
  if (typeof ssrHtml !== "string" || ssrHtml.length === 0) {
    throw new Error("[prerender-library] renderRoute() returned empty html");
  }

  // Replace the legacy pre-hydration shell block AND the empty #root
  // with the SSR output. Mark with data-hydrate so the bootstrap
  // calls hydrateRoot instead of createRoot.
  html =
    html.slice(0, startIdx) +
    html.slice(rootMatch.index).replace(
      rootRe,
      `<div id="root" data-hydrate="library">${ssrHtml}</div>`,
    );

  // Inline the slim bundle BEFORE the main module script so React
  // Query is seeded synchronously and the first client render matches
  // the SSR output. (Skipped only when the backend was unreachable —
  // in that case the SSR rendered the skeleton, which still hydrates
  // correctly because the client also starts with empty data.)
  if (slim) {
    const json = JSON.stringify(slim).replace(/</g, "\\u003c");
    const inlineScript = `<script>window.__LIBRARY_BUNDLE__=${json};</script>`;
    html = html.replace(
      /<script type="module"/,
      `${inlineScript}\n    <script type="module"`,
    );
  }

  html = rewriteHead(html);

  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(outHtml, html);

  // Hard assertion: the generated file must contain `data-hydrate=
  // "library"` and a non-empty #root.
  const written = fs.readFileSync(outHtml, "utf-8");
  if (
    !written.includes('data-hydrate="library"') ||
    /<div id="root" data-hydrate="library"><\/div>/.test(written)
  ) {
    throw new Error(
      "[prerender-library] hydration assertion failed: #root is empty or missing data-hydrate marker",
    );
  }

  console.log(
    `[prerender-library] wrote ${path.relative(distDir, outHtml)} ` +
      `(${(bundle?.subjects || []).length} subjects, ${html.length} bytes, SSR+hydrate)`,
  );
}

main().catch((err) => {
  console.error(err?.stack || err);
  // Hard fail — the deployed artifact must contain a hydrated
  // /library snapshot. (Task #382 — architect review)
  process.exit(1);
});
