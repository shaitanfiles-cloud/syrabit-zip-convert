// Post-build CI assertion for Task #385.
//
// When `dist/prerender-manifest.json` reports any subject or chapter
// routes were written, walk the prerendered surface area and confirm
// each `dist/<route>/index.html` is structurally sound:
//   * non-empty SSR markup inside `<div id="root" data-hydrate="…">`
//   * data-hydrate marker matches the route kind (subject|chapter)
//   * the inlined seed payload (`__SSR_QUERIES__` for subjects,
//     `__CHAPTER_PRELOAD__` for chapters) is present BEFORE the main
//     module script so the client can hydrate without a flash
//   * the legacy `#__shell` overlay is gone for prerendered routes
//
// Soft-fails (warns) when no routes were prerendered (e.g. backend
// unreachable on the build host) — matches the soft-fail philosophy
// in scripts/prerender-routes.mjs.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, "..", "dist");
const manifestPath = path.join(distDir, "prerender-manifest.json");

function fail(msg) {
  console.error(`[verify-prerender] FAIL: ${msg}`);
  process.exit(1);
}

if (!fs.existsSync(manifestPath)) {
  console.warn(
    "[verify-prerender] no prerender-manifest.json — prerender step likely soft-failed; skipping verification",
  );
  process.exit(0);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf-8"));
const subjectsWritten = manifest?.counts?.subjects_written ?? 0;
const chaptersWritten = manifest?.counts?.chapters_written ?? 0;
if (subjectsWritten === 0 && chaptersWritten === 0) {
  console.warn(
    "[verify-prerender] manifest reports zero prerendered routes; nothing to verify",
  );
  process.exit(0);
}

// Walk dist/ and collect every prerendered index.html (other than the
// root and /library, which are covered by their own verify scripts).
function* walk(dir, prefix = "") {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      if (rel === "assets" || rel === "icons" || rel === "fonts") continue;
      yield* walk(full, rel);
    } else if (entry.name === "index.html") {
      yield { full, rel };
    }
  }
}

const checked = [];
for (const { full, rel } of walk(distDir)) {
  // rel = `<segments>/index.html` — the leading directory is the route.
  if (rel === "index.html") continue;
  const route = "/" + rel.replace(/\/index\.html$/, "");
  if (route === "/library") continue;

  const html = fs.readFileSync(full, "utf-8");
  const m = html.match(/<div id="root" data-hydrate="([a-z]+)">([\s\S]*?)<\/div>\s*<script/);
  if (!m) {
    // Not a prerendered route — likely a copied static .html. Skip.
    continue;
  }
  const kind = m[1];
  const inner = m[2];
  if (!["subject", "chapter"].includes(kind)) {
    continue;
  }

  if (inner.trim().length < 400) {
    fail(`${route}: #root inner too small (${inner.length} bytes)`);
  }

  const seedKey = kind === "chapter" ? "__CHAPTER_PRELOAD__" : "__SSR_QUERIES__";
  const seedIdx = html.indexOf(`window.${seedKey}`);
  const moduleIdx = html.indexOf('<script type="module"');
  if (seedIdx === -1) {
    fail(`${route}: missing inlined window.${seedKey} payload`);
  }
  if (moduleIdx === -1 || seedIdx > moduleIdx) {
    fail(
      `${route}: window.${seedKey} must be inlined BEFORE the main module script`,
    );
  }

  if (/<div id="__shell"/.test(html)) {
    fail(`${route}: legacy #__shell overlay still present`);
  }

  // Task #395: each prerendered route must include a modulepreload
  // hint for its own page chunk so the browser fetches the route's
  // JS in parallel with the entry chunk (no extra hydration RTT).
  const pageChunkBase =
    kind === "subject" ? "SubjectLandingPage" : "ChapterPage";
  const preloadRe = new RegExp(
    `<link rel="modulepreload"[^>]*href="/assets/${pageChunkBase}-[^"]+\\.js"`,
  );
  if (!preloadRe.test(html)) {
    fail(
      `${route}: missing <link rel="modulepreload"> for ${pageChunkBase}-*.js (Task #395 contract)`,
    );
  }

  checked.push({ route, kind, bytes: html.length, rootBytes: inner.length });
}

const subjectsChecked = checked.filter((c) => c.kind === "subject").length;
const chaptersChecked = checked.filter((c) => c.kind === "chapter").length;

if (subjectsChecked === 0 && subjectsWritten > 0) {
  fail(`manifest claimed ${subjectsWritten} subjects written but verify found 0`);
}
if (chaptersChecked === 0 && chaptersWritten > 0) {
  fail(`manifest claimed ${chaptersWritten} chapters written but verify found 0`);
}

console.log(
  `[verify-prerender] OK — ${subjectsChecked} subject + ${chaptersChecked} chapter routes verified`,
);
