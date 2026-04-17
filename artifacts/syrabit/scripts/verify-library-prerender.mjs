// Post-build CI assertion for Task #382.
//
// Verifies that the deployed artifact (`dist/`) contains a real
// hydrated /library snapshot, not a JS-only shell. Fails the build
// hard if any check fails — guarantees the published Cloudflare
// Pages bundle ships prebuilt HTML for /library.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, "..", "dist");
const distSsrDir = path.resolve(__dirname, "..", "dist-ssr");
const libraryHtml = path.join(distDir, "library", "index.html");

function fail(msg) {
  console.error(`[verify-library-prerender] FAIL: ${msg}`);
  process.exit(1);
}

if (!fs.existsSync(libraryHtml)) {
  fail(`missing prerender output at ${path.relative(distDir, libraryHtml)}`);
}

const html = fs.readFileSync(libraryHtml, "utf-8");

// 1) data-hydrate marker present so the bootstrap calls hydrateRoot.
if (!html.includes('data-hydrate="library"')) {
  fail('missing data-hydrate="library" marker on #root');
}

// 1b) Reject React SSR abort signatures. renderToString aborts when
//     it encounters an unresolved Suspense/lazy boundary and emits
//     placeholder templates that switch the boundary to client-only
//     rendering — that violates the "hydrate without remount" task
//     contract. (Task #382 — architect re-review)
const abortSignatures = [
  "Switched to client rendering",
  'does not support Suspense',
  "<!--$!-->", // Suspense fallback / abort marker
];
for (const sig of abortSignatures) {
  if (html.includes(sig)) {
    fail(
      `prerender HTML contains React SSR abort signature ${JSON.stringify(sig)} — ` +
        `the SSR tree still has unresolved Suspense/lazy boundaries`,
    );
  }
}

// 2) #root has actual content (not <div id="root" data-hydrate="library"></div>).
const rootRe = /<div id="root" data-hydrate="library">([\s\S]*?)<\/div>\s*<script/;
const m = html.match(rootRe);
if (!m) {
  fail("could not locate #root container in /library/index.html");
}
const rootInner = m[1];
if (rootInner.trim().length < 500) {
  fail(`#root content is too small (${rootInner.length} bytes) — SSR likely produced no real markup`);
}

// 3) The inlined slim bundle must precede the main module script.
const bundleIdx = html.indexOf("window.__LIBRARY_BUNDLE__");
const moduleIdx = html.indexOf('<script type="module"');
if (bundleIdx === -1) {
  // Backend was unreachable at prerender time. The SSR still ran (the
  // skeleton hydrates correctly), so this is a soft warning, not a
  // hard fail — we don't want every build to require live backend.
  console.warn(
    "[verify-library-prerender] WARN: window.__LIBRARY_BUNDLE__ not inlined " +
      "(backend was unreachable at prerender time); /library will hydrate the skeleton",
  );
} else if (moduleIdx === -1 || bundleIdx > moduleIdx) {
  fail("window.__LIBRARY_BUNDLE__ must be inlined BEFORE the main module script");
}

// 4) Confirm the bootstrap is wired to hydrateRoot.
const indexJsxFiles = fs
  .readdirSync(path.join(distDir, "assets"))
  .filter((f) => /^index-[^.]+\.js$/.test(f))
  .map((f) => path.join(distDir, "assets", f));
let foundHydrate = false;
for (const f of indexJsxFiles) {
  const src = fs.readFileSync(f, "utf-8");
  // After minification, the source `rootEl.dataset.hydrate === "library"`
  // becomes a property access; the literal "data-hydrate" string is
  // not retained. We rely on `hydrateRoot(...)` (renamed but kept by
  // ReactDOM as an export) plus the literal "library" string used in
  // the equality check.
  if (src.includes("hydrateRoot") && src.includes('"library"')) {
    foundHydrate = true;
    break;
  }
}
if (!foundHydrate) {
  fail(
    "client bootstrap does not appear to call hydrateRoot for /library — " +
      "check src/index.jsx and ensure it survived minification",
  );
}

// 5) /library snapshot must NOT contain the legacy #__shell overlay
//    (it would visually layer on top of the hydrated tree).
if (/<div id="__shell"/.test(html)) {
  fail("/library/index.html still contains a #__shell overlay");
}

console.log(
  `[verify-library-prerender] OK: ${path.relative(distDir, libraryHtml)} ` +
    `(${html.length} bytes, ${rootInner.length} bytes inside #root)`,
);

// 6) Clean up the SSR build directory so it can't be confused with
//    the deploy directory. dist-ssr exists only as a build artifact
//    used by the prerender step — Cloudflare Pages serves `dist/`.
if (fs.existsSync(distSsrDir)) {
  fs.rmSync(distSsrDir, { recursive: true, force: true });
  console.log(
    `[verify-library-prerender] cleaned ${path.relative(path.dirname(distDir), distSsrDir)}`,
  );
}
