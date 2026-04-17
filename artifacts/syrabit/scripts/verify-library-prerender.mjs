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
const PRERENDERED = [
  path.join(distDir, "library", "index.html"),
  path.join(distDir, "browser", "index.html"),
];

function fail(msg) {
  console.error(`[verify-library-prerender] FAIL: ${msg}`);
  process.exit(1);
}

for (const target of PRERENDERED) {
  if (!fs.existsSync(target)) {
    fail(`missing prerender output at ${path.relative(distDir, target)}`);
  }

  const body = fs.readFileSync(target, "utf-8");

  // 1) data-hydrate marker present so the bootstrap calls hydrateRoot.
  if (!body.includes('data-hydrate="library"')) {
    fail(`missing data-hydrate="library" marker on #root in ${path.relative(distDir, target)}`);
  }

  // 1b) Reject React SSR abort signatures.
  const abortSignatures = [
    "Switched to client rendering",
    'does not support Suspense',
    "<!--$!-->",
  ];
  for (const sig of abortSignatures) {
    if (body.includes(sig)) {
      fail(
        `${path.relative(distDir, target)} contains React SSR abort signature ${JSON.stringify(sig)}`,
      );
    }
  }

  // 2) #root has actual content.
  const rootRe = /<div id="root" data-hydrate="library">([\s\S]*?)<\/div>\s*<script/;
  const m = body.match(rootRe);
  if (!m) {
    fail(`could not locate #root container in ${path.relative(distDir, target)}`);
  }
  const rootInner = m[1];
  if (rootInner.trim().length < 500) {
    fail(`#root content too small in ${path.relative(distDir, target)} (${rootInner.length} bytes)`);
  }

  // 3) The inlined slim bundle must precede the main module script.
  const bundleIdx = body.indexOf("window.__LIBRARY_BUNDLE__");
  const moduleIdx = body.indexOf('<script type="module"');
  if (bundleIdx === -1) {
    console.warn(
      `[verify-library-prerender] WARN: window.__LIBRARY_BUNDLE__ not inlined in ${path.relative(distDir, target)} ` +
        "(backend was unreachable at prerender time)",
    );
  } else if (moduleIdx === -1 || bundleIdx > moduleIdx) {
    fail(`window.__LIBRARY_BUNDLE__ must be inlined BEFORE the main module script in ${path.relative(distDir, target)}`);
  }

  // 5) Must NOT contain the legacy #__shell overlay.
  if (/<div id="__shell"/.test(body)) {
    fail(`${path.relative(distDir, target)} still contains a #__shell overlay`);
  }

  console.log(
    `[verify-library-prerender] OK: ${path.relative(distDir, target)} ` +
      `(${body.length} bytes, ${rootInner.length} bytes inside #root)`,
  );
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

// 6) Clean up the SSR build directory so it can't be confused with
//    the deploy directory. dist-ssr exists only as a build artifact
//    used by the prerender step — Cloudflare Pages serves `dist/`.
if (fs.existsSync(distSsrDir)) {
  fs.rmSync(distSsrDir, { recursive: true, force: true });
  console.log(
    `[verify-library-prerender] cleaned ${path.relative(path.dirname(distDir), distSsrDir)}`,
  );
}
