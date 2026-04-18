// Task #494: post-build CI assertion — every route required by the
// PageSpeed audit must ship exactly one <link rel="canonical"> in its
// static HTML, and that canonical must point at the route's own URL
// (not the homepage). Catches regressions where:
//   * the static index.html re-introduces a hard-coded canonical
//   * a prerender script's rewriteHead stops matching after a template
//     change
//   * a new high-impact route is added without a corresponding
//     prerender stub
//
// Hard-fails the build on any violation so a regression cannot reach
// production silently.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, "..", "dist");

const SITE = "https://syrabit.ai";

// Routes the audit explicitly checks. Each entry is the route path and
// the file that should exist in dist/. The expected canonical is
// always `${SITE}${route}`.
const REQUIRED_ROUTES = [
  { route: "/library",  file: "library/index.html" },
  { route: "/chat",     file: "chat/index.html" },
  { route: "/home",     file: "home/index.html" },
  { route: "/pricing",  file: "pricing/index.html" },
  { route: "/login",    file: "login/index.html" },
  { route: "/signup",   file: "signup/index.html" },
  { route: "/terms",    file: "terms/index.html" },
  { route: "/privacy",  file: "privacy/index.html" },
];

function fail(msg) {
  console.error(`[verify-canonicals] FAIL: ${msg}`);
  process.exit(1);
}

const failures = [];

// Root index.html must NOT carry a hard-coded canonical anymore — it
// becomes the SPA fallback for every non-prerendered route, and a
// hard-coded canonical there would re-introduce the homepage-bleeds-
// everywhere bug Task #494 fixed.
const rootHtmlPath = path.join(distDir, "index.html");
if (fs.existsSync(rootHtmlPath)) {
  const root = fs.readFileSync(rootHtmlPath, "utf-8");
  const rootCanonicalTags =
    root.match(/<link\s+rel="canonical"\s+href="[^"]*"[^>]*>/g) || [];
  if (rootCanonicalTags.length > 0) {
    failures.push(
      `dist/index.html must not ship a static canonical (found ${rootCanonicalTags.length}): ` +
        rootCanonicalTags.join(" | "),
    );
  }
}

for (const { route, file } of REQUIRED_ROUTES) {
  const full = path.join(distDir, file);
  if (!fs.existsSync(full)) {
    failures.push(`${route}: missing ${file}`);
    continue;
  }

  const html = fs.readFileSync(full, "utf-8");
  const canonicalTags =
    html.match(/<link\s+rel="canonical"\s+href="[^"]*"[^>]*>/g) || [];
  if (canonicalTags.length !== 1) {
    failures.push(
      `${route}: expected exactly 1 canonical tag, found ${canonicalTags.length} ` +
        `(${canonicalTags.join(" | ") || "<none>"})`,
    );
    continue;
  }

  const expected = `${SITE}${route}`;
  const hrefMatch = canonicalTags[0].match(/href="([^"]*)"/);
  const actual = hrefMatch ? hrefMatch[1] : null;
  if (actual !== expected) {
    failures.push(
      `${route}: canonical href mismatch — expected ${expected}, got ${actual}`,
    );
  }
}

// Spot-check subject + chapter canonicals from the dynamic prerender
// manifest (Task #494 — architect review). The manifest doesn't list
// the routes individually, so we walk dist/ for index.html files that
// match the subject (3 segments) or chapter (4 segments) shape and
// sample up to N of each. Each sampled file must contain exactly one
// canonical pointing at its own URL.
function* walkDist(dir, prefix = "") {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      if (rel === "assets" || rel === "icons" || rel === "fonts") continue;
      yield* walkDist(full, rel);
    } else if (entry.name === "index.html") {
      yield { full, rel };
    }
  }
}

const REQUIRED_FILES = new Set(REQUIRED_ROUTES.map((r) => r.file));
const SAMPLE_LIMIT = 5;
const subjectSamples = [];
const chapterSamples = [];
for (const { full, rel } of walkDist(distDir)) {
  if (rel === "index.html") continue;
  if (REQUIRED_FILES.has(rel)) continue; // already validated above
  const route = "/" + rel.replace(/\/index\.html$/, "");
  const segs = route.replace(/^\//, "").split("/");
  if (segs.length === 3 && subjectSamples.length < SAMPLE_LIMIT) {
    subjectSamples.push({ route, full });
  } else if (segs.length === 4 && chapterSamples.length < SAMPLE_LIMIT) {
    chapterSamples.push({ route, full });
  }
}

function checkCanonical(route, full) {
  const html = fs.readFileSync(full, "utf-8");
  const tags =
    html.match(/<link\s+rel="canonical"\s+href="[^"]*"[^>]*>/g) || [];
  if (tags.length !== 1) {
    failures.push(
      `${route}: expected exactly 1 canonical tag, found ${tags.length} ` +
        `(${tags.join(" | ") || "<none>"})`,
    );
    return;
  }
  const expected = `${SITE}${route}`;
  const m = tags[0].match(/href="([^"]*)"/);
  if (!m || m[1] !== expected) {
    failures.push(
      `${route}: canonical href mismatch — expected ${expected}, got ${m && m[1]}`,
    );
  }
}

for (const s of subjectSamples) checkCanonical(s.route, s.full);
for (const c of chapterSamples) checkCanonical(c.route, c.full);

if (failures.length) {
  fail(
    `${failures.length} canonical violation(s):\n  - ` +
      failures.join("\n  - "),
  );
}

console.log(
  `[verify-canonicals] OK — ${REQUIRED_ROUTES.length} required routes + ` +
    `${subjectSamples.length} subject + ${chapterSamples.length} chapter sample(s) ` +
    `ship the correct per-route canonical, dist/index.html has no static canonical (Task #494)`,
);
