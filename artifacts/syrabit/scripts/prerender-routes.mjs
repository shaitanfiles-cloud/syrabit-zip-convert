// Statically prerender top-N subject and chapter routes (Task #385).
//
// Builds on Task #382's /library prerender plumbing. For each
// prerendered route this script:
//   1. Fetches the data the page needs (resolve-subject + chapters
//      for subject pages; chapter-by-slug for chapter pages).
//   2. Imports the SSR build (`dist-ssr/entry-server.js`), seeds
//      React Query (subject pages) or globalThis (chapter pages, which
//      use local state), and renders the route to a string.
//   3. Injects the SSR markup into a copy of `dist/index.html`,
//      replaces #root with the rendered tree (tagged with
//      data-hydrate="subject" or "chapter"), inlines the seed payload
//      so the client can hydrate without flicker, rewrites SEO meta,
//      and writes `dist/<route-path>/index.html`.
//
// Cloudflare Pages serves the deepest static file match first, so the
// new HTML is returned instantly (no SPA boot) for crawlers and
// browsers alike. Falls back to the SPA shell when the backend is
// unreachable so the build never hard-fails on a transient network.
//
// Selection order (Task #388): the script asks the backend for the
// most-visited subject + chapter routes over the last
// PRERENDER_TRAFFIC_DAYS days (default 30) and uses that ranking to
// pick which routes to prerender. Routes not present in the analytics
// rollup fall back to bundle order, so a brand-new deployment with no
// traffic data still ships a sensible set of pages.
//
// Limits are env-tunable so we can scale up gradually:
//   PRERENDER_SUBJECTS_LIMIT          (default 50)
//   PRERENDER_CHAPTERS_PER_SUBJECT    (default 5)
//   PRERENDER_TRAFFIC_DAYS            (default 30)
//   PRERENDER_BACKEND_URL / VITE_BACKEND_URL  (default https://syrabit.ai)

import fs from "fs";
import path from "path";
import { fileURLToPath, pathToFileURL } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, "..", "dist");
const distSsrDir = path.resolve(__dirname, "..", "dist-ssr");
const srcHtml = path.join(distDir, "index.html");
const ssrEntry = path.join(distSsrDir, "entry-server.js");

const BACKEND =
  process.env.PRERENDER_BACKEND_URL ||
  process.env.VITE_BACKEND_URL ||
  "https://syrabit.ai";
const SUBJECTS_LIMIT = parseInt(
  process.env.PRERENDER_SUBJECTS_LIMIT || "50",
  10,
);
const CHAPTERS_PER_SUBJECT = parseInt(
  process.env.PRERENDER_CHAPTERS_PER_SUBJECT || "5",
  10,
);
const TRAFFIC_DAYS = parseInt(
  process.env.PRERENDER_TRAFFIC_DAYS || "30",
  10,
);
const FETCH_TIMEOUT_MS = 8000;

function escapeHtml(s = "") {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function fetchJson(url) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      signal: ctrl.signal,
      headers: { Accept: "application/json" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// React Query's setQueryData rejects undefined values, so strip them
// from inlined payloads. Keeps the wire format identical between SSR
// and client hydration.
function clean(obj) {
  if (Array.isArray(obj)) return obj.map(clean);
  if (obj && typeof obj === "object") {
    const out = {};
    for (const [k, v] of Object.entries(obj)) {
      if (v !== undefined) out[k] = clean(v);
    }
    return out;
  }
  return obj;
}

function rewriteHead(html, { title, description, canonical }) {
  html = html.replace(
    /<title>[^<]*<\/title>/,
    `<title>${escapeHtml(title)}</title>`,
  );
  html = html.replace(
    /<meta name="description" content="[^"]*"\s*\/?>(\n)?/,
    `<meta name="description" content="${escapeHtml(description)}" />\n    `,
  );
  // Task #494: the static template no longer ships a placeholder
  // <link rel="canonical">. Swap if one happens to exist (legacy
  // builds), otherwise inject before </head> so every prerendered
  // route ships its own canonical instead of inheriting the homepage.
  if (/<link rel="canonical" href="[^"]*"\s*\/?>(\n)?/.test(html)) {
    html = html.replace(
      /<link rel="canonical" href="[^"]*"\s*\/?>(\n)?/,
      `<link rel="canonical" href="${canonical}" />\n    `,
    );
  } else {
    html = html.replace(
      /<\/head>/,
      `    <link rel="canonical" href="${canonical}" />\n` +
      `    <link rel="alternate" hreflang="en-IN" href="${canonical}" />\n  </head>`,
    );
  }
  html = html.replace(
    /<meta property="og:url" content="[^"]*"\s*\/?>/,
    `<meta property="og:url" content="${canonical}" />`,
  );
  html = html.replace(
    /<meta property="og:title" content="[^"]*"\s*\/?>/,
    `<meta property="og:title" content="${escapeHtml(title)}" />`,
  );
  html = html.replace(
    /<meta property="og:description" content="[^"]*"\s*\/?>/,
    `<meta property="og:description" content="${escapeHtml(description)}" />`,
  );
  html = html.replace(
    /<meta name="twitter:title" content="[^"]*"\s*\/?>/,
    `<meta name="twitter:title" content="${escapeHtml(title)}" />`,
  );
  html = html.replace(
    /<meta name="twitter:description" content="[^"]*"\s*\/?>/,
    `<meta name="twitter:description" content="${escapeHtml(description)}" />`,
  );
  return html;
}

// Task #395: page-chunk preload helper, lazily resolved on first use
// so the import cost doesn't hit unrelated routes.
let _pageChunkHelper = null;
async function pageChunkHelper() {
  if (!_pageChunkHelper) {
    _pageChunkHelper = await import(
      pathToFileURL(path.join(__dirname, "_page-chunk-preload.mjs")).href
    );
  }
  return _pageChunkHelper;
}

const HYDRATE_KIND_TO_CHUNK_BASE = {
  subject: "SubjectLandingPage",
  chapter: "ChapterPage",
  library: "LibraryPage",
  chat: "ChatPage",
};

// Task #496: per-hydrate-kind modulepreload allow-list. Vite emits a
// `<link rel="modulepreload">` for every static dep of the entry chunk
// in dist/index.html. For prerendered subject + chapter snapshots,
// that pulls in 80-150 KB of JS the route never executes on the
// critical path (chat code playground, alternate page chunks, framer,
// etc.), inflating mobile TBT and the "Reduce unused JavaScript"
// Lighthouse opportunity (audited 2026-04-18: ~617 KB on chapter,
// ~646 KB on subject). The patterns below match
// prerender-library.mjs's NON_LIBRARY_PRELOAD_PATTERNS but tuned per
// route — chapter pages legitimately need markdown / syntax /
// StickyToc, subject landings do not.
const PRELOAD_STRIP_BY_KIND = {
  subject: [
    /sandpack/i,
    /^markdown-/i,
    /MarkdownC/i,
    /framer/i,
    /^syntax-/i,
    /ChatPa/,
    /ChapterPa/,
    /StickyToc/,
    /^badge-/,
    /^skeleton-/,
    /LibraryPa/,
  ],
  chapter: [
    /sandpack/i,
    /framer/i,
    /ChatPa/,
    /LibraryPa/,
    /^badge-/,
    /CmsDocsSection/,
    /CmsPostsGrid/,
  ],
};

function stripUnusedModulepreloads(html, hydrateKind) {
  const patterns = PRELOAD_STRIP_BY_KIND[hydrateKind];
  if (!patterns || !patterns.length) return html;
  return html.replace(
    /\s*<link rel="modulepreload"[^>]*href="\/assets\/([^"]+)"[^>]*>/g,
    (match, file) =>
      patterns.some((re) => re.test(file)) ? "" : match,
  );
}

// Task #496: inline the main app CSS the same way prerender-library.mjs
// does. Subject and chapter snapshots are fully prerendered (SSR
// markup inside #root), so the external CSS link is a hard
// render-blocking dependency on the critical path. Inlining cuts a
// ~300 ms round-trip on slow 3G mobile and removes the Lighthouse
// "Render blocking requests" finding for these routes. The cost is one
// extra HTML payload (~70 KB raw → ~14 KB gzipped) but it's cached by
// the page's edge SWR policy after the first hit.
function inlineMainCssOnce(html, distDir) {
  const cssLinkRe = /<link rel="stylesheet"[^>]*href="\/assets\/([^"]+\.css)"[^>]*>/;
  const m = html.match(cssLinkRe);
  if (!m) return html;
  const cssPath = path.join(distDir, "assets", m[1]);
  if (!fs.existsSync(cssPath)) return html;
  const cssContent = fs.readFileSync(cssPath, "utf-8");
  const out = html.replace(
    cssLinkRe,
    `<style data-inline-css="${m[1]}">${cssContent}</style>`,
  );
  console.log(
    `[prerender-routes] inlined ${m[1]} (${cssContent.length} bytes) — removed render-blocking CSS for subject + chapter snapshots`,
  );
  return out;
}

function injectShell(htmlTemplate, { ssrHtml, hydrateKind, inlineScripts, pageChunkPreload }) {
  const startMarker =
    `<noscript><style>#__shell{display:none!important}</style></noscript>`;
  const startIdx = htmlTemplate.indexOf(startMarker);
  const rootRe = /<div id="root"[^>]*><\/div>/;
  const rootMatch = htmlTemplate.match(rootRe);
  if (startIdx === -1 || !rootMatch) {
    throw new Error(
      "[prerender-routes] could not locate shell markers in dist/index.html — structure changed?",
    );
  }
  let html =
    htmlTemplate.slice(0, startIdx) +
    htmlTemplate.slice(rootMatch.index).replace(
      rootRe,
      `<div id="root" data-hydrate="${hydrateKind}">${ssrHtml}</div>`,
    );

  if (inlineScripts && inlineScripts.length) {
    const blob = inlineScripts.join("\n    ");
    html = html.replace(
      /<script type="module"/,
      `${blob}\n    <script type="module"`,
    );
  }

  if (pageChunkPreload && pageChunkPreload.injectFn && pageChunkPreload.chunkFile) {
    html = pageChunkPreload.injectFn(html, pageChunkPreload.chunkFile);
  }
  return html;
}

function writeRoute(routePath, html) {
  const outDir = path.join(distDir, routePath.replace(/^\//, ""));
  fs.mkdirSync(outDir, { recursive: true });
  const outHtml = path.join(outDir, "index.html");
  fs.writeFileSync(outHtml, html);
  return outHtml;
}

function pickSubjectFields(subject) {
  const keys = [
    "id", "_id", "name", "slug", "description", "icon", "color",
    "stream_id", "class_id", "board_id",
    "board_name", "class_name", "stream_name",
    "board_slug", "class_slug", "stream_slug",
    "chapter_count", "tags",
  ];
  const out = {};
  for (const k of keys) if (subject[k] !== undefined) out[k] = subject[k];
  return out;
}

function pickChapterListFields(ch) {
  const keys = [
    "id", "_id", "title", "slug", "description",
    "content_type", "order", "chapter_id",
  ];
  const out = {};
  for (const k of keys) if (ch[k] !== undefined) out[k] = ch[k];
  return out;
}

// Trim chapter payload to the fields ChapterPage actually reads, so
// the inlined script stays small (LCP-critical).
function pickChapterPayload(c) {
  const keys = [
    "chapter_id", "title", "topic_title", "chapter_title",
    "subject_name", "board_name", "class_name", "stream_name",
    "subject_slug", "board_slug", "class_slug", "stream_slug",
    "chapter_slug", "content", "content_as", "content_type",
    "has_assamese", "meta_description", "word_count",
    "generated_at", "updated_at", "bing_keywords",
  ];
  const out = {};
  for (const k of keys) if (c[k] !== undefined) out[k] = c[k];
  return out;
}

function enumerateSubjectRoutes(bundle) {
  const boards = new Map((bundle.boards || []).map((b) => [b.id, b]));
  const classes = new Map((bundle.classes || []).map((c) => [c.id, c]));
  const streams = new Map((bundle.streams || []).map((s) => [s.id, s]));
  const routes = [];
  for (const subject of bundle.subjects || []) {
    const stream = streams.get(subject.stream_id);
    if (!stream) continue;
    const cls = classes.get(stream.class_id);
    if (!cls) continue;
    const board = boards.get(cls.board_id);
    if (!board) continue;
    if (!subject.slug || !cls.slug || !board.slug) continue;
    routes.push({
      board: board.slug,
      classSlug: cls.slug,
      streamSlug: stream.slug || null,
      subjectSlug: subject.slug,
      subject,
    });
  }
  return routes;
}

async function resolvePageChunkPreload(hydrateKind) {
  const baseName = HYDRATE_KIND_TO_CHUNK_BASE[hydrateKind];
  if (!baseName) return null;
  const helper = await pageChunkHelper();
  const chunkFile = helper.findPageChunk(distDir, baseName);
  if (!chunkFile) {
    throw new Error(
      `[prerender-routes] no ${baseName}-*.js chunk found in dist/assets — ` +
        `Task #395 contract requires a per-page chunk (hydrateKind=${hydrateKind})`,
    );
  }
  return { injectFn: helper.injectPageChunkPreload, chunkFile };
}

async function renderOne(renderRoute, htmlTemplate, opts) {
  const out = await renderRoute({
    url: opts.url,
    seed: opts.seed,
  });
  if (Array.isArray(out?.errors) && out.errors.length) {
    for (const e of out.errors) {
      console.warn(
        `[prerender-routes] SSR onError (${opts.url}):`,
        e?.stack || e?.message || e,
      );
    }
  }
  const ssrHtml = out?.html;
  if (typeof ssrHtml !== "string" || ssrHtml.length === 0) {
    throw new Error(
      `[prerender-routes] renderRoute(${opts.url}) returned empty html`,
    );
  }
  const pageChunkPreload = await resolvePageChunkPreload(opts.hydrateKind);
  const trimmedTemplate = stripUnusedModulepreloads(
    htmlTemplate,
    opts.hydrateKind,
  );
  const html = injectShell(trimmedTemplate, {
    ssrHtml,
    hydrateKind: opts.hydrateKind,
    inlineScripts: opts.inlineScripts,
    pageChunkPreload,
  });
  return rewriteHead(html, opts.head);
}

async function main() {
  if (!fs.existsSync(srcHtml)) {
    console.warn(
      `[prerender-routes] dist/index.html not found at ${srcHtml}; skipping`,
    );
    return;
  }
  if (!fs.existsSync(ssrEntry)) {
    throw new Error(
      `[prerender-routes] required SSR build missing at ${ssrEntry}; ` +
        `build pipeline must run "vite build --ssr src/entry-server.jsx --outDir dist-ssr" first`,
    );
  }

  // Browser-API polyfills mirroring scripts/prerender-library.mjs.
  if (typeof globalThis.localStorage === "undefined") {
    const noop = () => null;
    globalThis.localStorage = {
      getItem: noop, setItem: () => {}, removeItem: () => {},
      clear: () => {}, key: noop, length: 0,
    };
    globalThis.sessionStorage = globalThis.localStorage;
  }

  // Pull the slim library bundle to enumerate subject routes. If the
  // backend is unreachable we soft-fail (logged) instead of breaking
  // the build — Task #382 already ships the SPA shell as a safety net.
  let bundle = null;
  try {
    bundle = await fetchJson(
      `${BACKEND.replace(/\/$/, "")}/api/content/library-bundle?slim=1`,
    );
  } catch (err) {
    console.warn(
      `[prerender-routes] library bundle fetch failed (${err.message}); ` +
        `skipping subject + chapter prerender`,
    );
    return;
  }

  const allSubjectRoutes = enumerateSubjectRoutes(bundle);

  // Pull traffic ranking (Task #388). Each entry is `{ path, views }`
  // for the most-visited subject + chapter routes over the last
  // TRAFFIC_DAYS days. We build path → views maps for both subject
  // (3-segment) and chapter (4-segment) routes, then derive a subject
  // priority that combines the subject landing-page views with the
  // sum of all chapter views under that prefix. This means a subject
  // whose chapters are popular gets prerendered even when the bare
  // landing URL is rarely visited directly.
  // Anything missing from analytics keeps its bundle-order position so
  // a cold start still produces sensible output.
  const subjectViews = new Map();
  const chapterViews = new Map();
  try {
    const trafficPayload = await fetchJson(
      `${BACKEND.replace(/\/$/, "")}/api/analytics/top-routes?days=${TRAFFIC_DAYS}&limit=1000`,
    );
    const list = Array.isArray(trafficPayload?.routes) ? trafficPayload.routes : [];
    for (const row of list) {
      if (!row || typeof row.path !== "string") continue;
      const views = Number(row.views) || 0;
      const segs = row.path.replace(/^\//, "").split("/");
      if (segs.length === 3) {
        subjectViews.set(row.path, views);
      } else if (segs.length === 4) {
        chapterViews.set(row.path, views);
        const subjectPath = `/${segs[0]}/${segs[1]}/${segs[2]}`;
        subjectViews.set(
          subjectPath,
          (subjectViews.get(subjectPath) || 0) + views,
        );
      }
    }
    console.log(
      `[prerender-routes] traffic ranking: ${list.length} routes from last ${TRAFFIC_DAYS}d ` +
        `(${subjectViews.size} subject prefixes, ${chapterViews.size} chapters)`,
    );
  } catch (err) {
    console.warn(
      `[prerender-routes] traffic ranking unavailable (${err.message}); ` +
        `falling back to bundle order`,
    );
  }

  const haveTraffic = subjectViews.size > 0 || chapterViews.size > 0;
  const subjectScore = (route) => {
    const url = `/${route.board}/${route.classSlug}/${route.subjectSlug}`;
    return subjectViews.get(url) || 0;
  };
  const rankedSubjectRoutes = haveTraffic
    ? [...allSubjectRoutes].sort((a, b) => {
        const sa = subjectScore(a);
        const sb = subjectScore(b);
        if (sb !== sa) return sb - sa; // higher views first
        return allSubjectRoutes.indexOf(a) - allSubjectRoutes.indexOf(b);
      })
    : allSubjectRoutes;
  const subjectRoutes = rankedSubjectRoutes.slice(0, SUBJECTS_LIMIT);
  console.log(
    `[prerender-routes] ${subjectRoutes.length}/${allSubjectRoutes.length} subjects in scope ` +
      `(limit=${SUBJECTS_LIMIT}, chapters per subject=${CHAPTERS_PER_SUBJECT}, ` +
      `selection=${haveTraffic ? "traffic" : "bundle-order"})`,
  );

  const mod = await import(pathToFileURL(ssrEntry).href);
  const renderRoute = mod.renderRoute || mod.default;
  if (typeof renderRoute !== "function") {
    throw new Error(
      "[prerender-routes] entry-server.js did not export renderRoute()",
    );
  }

  let htmlTemplate = fs.readFileSync(srcHtml, "utf-8");
  // Task #496: inline CSS once on the shared template — both subject
  // and chapter snapshots inherit the non-render-blocking CSS load.
  htmlTemplate = inlineMainCssOnce(htmlTemplate, distDir);

  let subjectsWritten = 0;
  let chaptersWritten = 0;
  let subjectsFailed = 0;
  let chaptersFailed = 0;

  for (const route of subjectRoutes) {
    const { board, classSlug, subjectSlug, subject } = route;
    const url = `/${board}/${classSlug}/${subjectSlug}`;
    const canonical = `https://syrabit.ai${url}`;

    let resolved;
    let chapters;
    try {
      resolved = await fetchJson(
        `${BACKEND.replace(/\/$/, "")}/api/content/resolve-subject/${board}/${classSlug}/${subjectSlug}`,
      );
      const subjectId = resolved?.id || resolved?._id || subject.id;
      chapters = await fetchJson(
        `${BACKEND.replace(/\/$/, "")}/api/content/chapters/${subjectId}`,
      );
    } catch (err) {
      console.warn(
        `[prerender-routes] subject data fetch failed for ${url}: ${err.message}`,
      );
      subjectsFailed++;
      continue;
    }

    const subjectName = resolved.name || subject.name || subjectSlug;
    const className = resolved.class_name || classSlug;
    const boardName = resolved.board_name || board;
    const subjectDataClean = clean(pickSubjectFields(resolved));
    const chaptersClean = clean(
      (chapters || []).map(pickChapterListFields),
    );

    const queries = [
      { key: ["resolve-subject", board, classSlug, subjectSlug], data: subjectDataClean },
    ];
    const subjectIdForKey = subjectDataClean.id || subjectDataClean._id;
    if (subjectIdForKey) {
      queries.push({ key: ["chapters", subjectIdForKey], data: chaptersClean });
    }

    const inlineScripts = [
      `<script>window.__SSR_QUERIES__=${JSON.stringify(queries).replace(/</g, "\\u003c")};</script>`,
    ];

    try {
      const html = await renderOne(renderRoute, htmlTemplate, {
        url,
        seed: { queries },
        hydrateKind: "subject",
        inlineScripts,
        head: {
          title:
            `${subjectName} — ${boardName} ${className} Notes & Study Material | Syrabit.ai`,
          description:
            resolved.description ||
            `Complete ${subjectName} study material for ${boardName} ${className}. ` +
              `AI-powered notes, MCQs, important questions, and exam preparation.`,
          canonical,
        },
      });
      const out = writeRoute(url, html);
      subjectsWritten++;
      console.log(
        `[prerender-routes] subject ${url} → ${path.relative(distDir, out)} ` +
          `(${chaptersClean.length} chapters)`,
      );
    } catch (err) {
      console.warn(
        `[prerender-routes] subject render failed for ${url}: ${err.message}`,
      );
      subjectsFailed++;
      continue;
    }

    // ── Chapter prerender for the same subject ────────────────────
    // Re-rank chapter candidates by real traffic (Task #388). Chapters
    // missing from the analytics rollup keep their bundle-order
    // position so we still prerender something useful for new
    // subjects with no recorded views yet.
    const chapterCandidates = (chapters || []).filter((c) => c.slug);
    const rankedChapters = haveTraffic
      ? [...chapterCandidates].sort((a, b) => {
          const va = chapterViews.get(`${url}/${a.slug}`) || 0;
          const vb = chapterViews.get(`${url}/${b.slug}`) || 0;
          if (vb !== va) return vb - va; // higher views first
          return chapterCandidates.indexOf(a) - chapterCandidates.indexOf(b);
        })
      : chapterCandidates;
    const candidateChapters = rankedChapters.slice(0, CHAPTERS_PER_SUBJECT);

    for (const ch of candidateChapters) {
      const chapterSlug = ch.slug;
      const chapterUrl = `${url}/${chapterSlug}`;
      const chapterCanonical = `https://syrabit.ai${chapterUrl}`;

      let chapterPayload;
      try {
        chapterPayload = await fetchJson(
          `${BACKEND.replace(/\/$/, "")}/api/content/chapter-by-slug/${board}/${classSlug}/${subjectSlug}/${chapterSlug}`,
        );
      } catch (err) {
        console.warn(
          `[prerender-routes] chapter data fetch failed for ${chapterUrl}: ${err.message}`,
        );
        chaptersFailed++;
        continue;
      }
      if (!chapterPayload || typeof chapterPayload !== "object") {
        chaptersFailed++;
        continue;
      }

      const chapterData = clean(pickChapterPayload(chapterPayload));
      const preload = {
        board, classSlug, subjectSlug, chapterSlug,
        data: chapterData,
      };

      const chapterTitle =
        chapterPayload.topic_title ||
        chapterPayload.chapter_title ||
        ch.title ||
        chapterSlug;
      const subjName = chapterPayload.subject_name || subjectName;
      const bName = chapterPayload.board_name || boardName;
      const cName = chapterPayload.class_name || className;

      const inlineChapterScripts = [
        `<script>window.__CHAPTER_PRELOAD__=${JSON.stringify(preload).replace(/</g, "\\u003c")};</script>`,
      ];

      try {
        const html = await renderOne(renderRoute, htmlTemplate, {
          url: chapterUrl,
          seed: { chapterPreload: preload },
          hydrateKind: "chapter",
          inlineScripts: inlineChapterScripts,
          head: {
            title: `${chapterTitle} — ${subjName} | ${bName} ${cName} Notes`,
            description:
              chapterPayload.meta_description ||
              `${chapterTitle} notes for ${subjName}. Complete study material for ${bName} ${cName} students.`,
            canonical: chapterCanonical,
          },
        });
        const out = writeRoute(chapterUrl, html);
        chaptersWritten++;
        console.log(
          `[prerender-routes] chapter ${chapterUrl} → ${path.relative(distDir, out)}`,
        );
      } catch (err) {
        console.warn(
          `[prerender-routes] chapter render failed for ${chapterUrl}: ${err.message}`,
        );
        chaptersFailed++;
      }
    }
  }

  console.log(
    `[prerender-routes] done — subjects=${subjectsWritten} ok / ${subjectsFailed} failed; ` +
      `chapters=${chaptersWritten} ok / ${chaptersFailed} failed`,
  );

  // Persist the manifest so the verify script (and future audits) can
  // walk the prerendered surface area without re-enumerating.
  const manifest = {
    generated_at: new Date().toISOString(),
    backend: BACKEND,
    limits: {
      subjects: SUBJECTS_LIMIT,
      chaptersPerSubject: CHAPTERS_PER_SUBJECT,
    },
    selection: {
      mode: haveTraffic ? "traffic" : "bundle-order",
      traffic_days: TRAFFIC_DAYS,
      ranked_subjects: subjectViews.size,
      ranked_chapters: chapterViews.size,
    },
    counts: {
      subjects_written: subjectsWritten,
      subjects_failed: subjectsFailed,
      chapters_written: chaptersWritten,
      chapters_failed: chaptersFailed,
    },
  };
  fs.writeFileSync(
    path.join(distDir, "prerender-manifest.json"),
    JSON.stringify(manifest, null, 2),
  );
}

main().catch((err) => {
  // Soft-fail: a transient network blip on the build host should not
  // break the whole deployment. Subject + chapter routes will fall
  // back to the SPA shell on Cloudflare Pages, exactly as they did
  // before this script existed. (Task #385 — architect review)
  console.error("[prerender-routes] non-fatal failure:", err?.stack || err);
  process.exit(0);
});
