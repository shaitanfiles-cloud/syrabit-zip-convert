// Task #856 — Critical-CSS extraction for Syrabit web.
//
// Runs after the prerender stage and walks every emitted HTML file in
// dist/. For each one, Beasties (the actively-maintained Google fork of
// critters) parses the document, scans for the class names actually
// referenced in the markup, inlines the matching CSS rules into a new
// <style> block in <head>, and rewrites the original render-blocking
// <link rel="stylesheet"> into a non-blocking preload+swap pair.
//
// Why this matters
// ----------------
// The audit at task time showed the initial paint of syrabit.ai was
// gated on a single 141 KB stylesheet (assets/index-*.css). The browser
// could not start rendering until that file finished downloading,
// adding 200–500 ms to FCP on mobile (3G/4G CGNAT — our typical
// AHSEC/SEBA student's network). After this step, only the ~10–14 KB
// of critical above-the-fold rules ship inline; the full stylesheet
// downloads asynchronously and applies once it's ready.
//
// Notes
// -----
//   * pruneSource: false — the full stylesheet stays on disk so other
//     routes (admin, library, chat) can still reuse it from cache.
//   * mergeStylesheets: false — preserves the existing inline <style>
//     blocks (pre-hydration shell, Emergent badge hider, critical CSS
//     stub from index.html) verbatim.
//   * preload: 'swap-high' — emits the high-priority preload + swap
//     pattern (Filament Group's loadCSS recipe), with a <noscript>
//     fallback for clients with JS disabled.
//   * Errors are downgraded to warnings: a parser failure on one
//     prerendered HTML must not fail the Pages build, since the only
//     consequence is that one page goes back to its pre-fix CSS load
//     pattern. The build's own verifier covers correctness.
//
// Idempotent — safe to run twice on the same dist/.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Beasties from "beasties";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const DIST = path.join(repoRoot, "dist");

if (!fs.existsSync(DIST)) {
  console.error(`[critical-css] dist/ not found at ${DIST}; skipping.`);
  process.exit(0);
}

function walkHtml(dir, files = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkHtml(p, files);
    } else if (entry.isFile() && entry.name.endsWith(".html")) {
      files.push(p);
    }
  }
  return files;
}

// Skip files that are not really part of the SPA shell — keeping them
// in the candidate list would just spend time parsing markup that has
// no <link rel="stylesheet"> for Beasties to act on.
const SKIP_NAMES = new Set([
  "googlefbe0a804ad7e5fdd.html", // Google Search Console verification stub
  "stats.html",                   // rollup-plugin-visualizer report
  "offline.html",                 // SW offline shell — already self-contained
]);

// Strip <noscript>…</noscript> bodies before scanning so the noscript
// fallback link Beasties writes on its first pass cannot fool a re-run
// into thinking there is still a render-blocking link to rewrite. Makes
// the script truly idempotent.
function htmlWithoutNoscript(html) {
  return html.replace(/<noscript\b[^>]*>[\s\S]*?<\/noscript>/gi, "");
}

function hasActiveBlockingLink(html) {
  const stripped = htmlWithoutNoscript(html);
  return /\<link[^>]+rel=["']stylesheet["'][^>]+\/assets\/index-[A-Za-z0-9_-]+\.css/.test(
    stripped,
  );
}

function shouldProcess(htmlPath) {
  const name = path.basename(htmlPath);
  if (SKIP_NAMES.has(name)) return false;
  const html = fs.readFileSync(htmlPath, "utf-8");
  return hasActiveBlockingLink(html);
}

const beasties = new Beasties({
  path: DIST,
  publicPath: "/",
  preload: "swap-high",
  pruneSource: false,
  mergeStylesheets: false,
  inlineFonts: false,
  reduceInlineStyles: false,
  fonts: false,
  logLevel: "silent",
});

const htmls = walkHtml(DIST);
let processed = 0;
let skipped = 0;
const failures = [];
let bytesInlinedTotal = 0;

const start = Date.now();

for (const htmlPath of htmls) {
  if (!shouldProcess(htmlPath)) {
    skipped++;
    continue;
  }
  const original = fs.readFileSync(htmlPath, "utf-8");
  try {
    const transformed = await beasties.process(original);
    if (typeof transformed === "string" && transformed.length > 0) {
      // Approximation: anything Beasties added between the <!-- inline
      // critical CSS for above-the-fold rendering --> sentinel and
      // </head> is the new critical-CSS payload it inlined. We measure
      // total head growth as a coarse proxy and report it for visibility.
      const beforeHead = original.indexOf("</head>");
      const afterHead = transformed.indexOf("</head>");
      const delta = afterHead - beforeHead;
      if (delta > 0) bytesInlinedTotal += delta;
      fs.writeFileSync(htmlPath, transformed);
      processed++;
    } else {
      skipped++;
    }
  } catch (err) {
    failures.push({ path: htmlPath, err: String(err && err.message || err) });
  }
}

const elapsed = Date.now() - start;
const rel = (p) => path.relative(repoRoot, p);
console.log(
  `[critical-css] processed ${processed}, skipped ${skipped}, ` +
  `failures ${failures.length}, ~${Math.round(bytesInlinedTotal / 1024)} KB ` +
  `inlined across all HTMLs (${elapsed}ms)`,
);
if (failures.length) {
  for (const f of failures) {
    console.warn(`[critical-css] WARN ${rel(f.path)}: ${f.err}`);
  }
}

// Hard-fail guards (Task #856 review feedback). A green build that
// silently shipped render-blocking CSS again would defeat the entire
// task, so we fail loudly when the entry point breaks or when a high
// fraction of pages broke at once (typical signature of a Beasties
// upgrade gone wrong, or a Vite asset-name change Beasties can't
// resolve). Per-file failures below the threshold remain soft so a
// single oddball prerender can't block deploys.
const ROOT_INDEX = path.join(DIST, "index.html");
const rootFailed = failures.some((f) => path.resolve(f.path) === ROOT_INDEX);
if (rootFailed) {
  console.error(
    `[critical-css] FATAL: dist/index.html (the SPA entry point) failed to ` +
    `inline. Refusing to ship a build that loses critical-CSS coverage on ` +
    `the route every cold visit lands on.`,
  );
  process.exit(1);
}
// Failure ratio guard: if more than 1/3 of the candidate HTMLs broke,
// something systemic is wrong (Beasties version drift, dist/ layout
// change, etc.) and the build should not proceed. processed + failures
// = the candidate set we actually attempted.
const attempted = processed + failures.length;
if (attempted > 0 && failures.length / attempted > 1 / 3) {
  console.error(
    `[critical-css] FATAL: ${failures.length}/${attempted} HTMLs failed to ` +
    `inline (>33% threshold) — investigate Beasties + dist/ before shipping.`,
  );
  process.exit(1);
}

// Postcondition: the root index MUST end up in the non-blocking
// pattern. This catches the silent case where Beasties returns a
// string but does not actually rewrite the link (e.g., it could not
// resolve the stylesheet on disk).
if (fs.existsSync(ROOT_INDEX)) {
  const rootHtml = fs.readFileSync(ROOT_INDEX, "utf-8");
  if (hasActiveBlockingLink(rootHtml)) {
    console.error(
      `[critical-css] FATAL: dist/index.html still has an active ` +
      `<link rel="stylesheet" href="/assets/index-*.css"> after Beasties ran. ` +
      `Critical-CSS extraction did not take effect on the SPA entry point.`,
    );
    process.exit(1);
  }
}
