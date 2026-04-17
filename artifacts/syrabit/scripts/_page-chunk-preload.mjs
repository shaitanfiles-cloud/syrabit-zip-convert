// Shared helper for prerender-library.mjs / prerender-routes.mjs /
// prerender-chat.mjs (Task #395).
//
// Each prerendered page (LibraryPage / ChatPage / SubjectLandingPage /
// ChapterPage) is now its own JS chunk (`PageBasename-<hash>.js`) — the
// entry chunk no longer statically imports them, so Vite no longer
// emits an automatic `<link rel="modulepreload">` for them in
// dist/index.html. Without a preload, the browser only discovers the
// page chunk after it parses + executes the entry chunk and resolves
// the dynamic `import()` in `index.jsx`'s `preloadPageForKind()` call,
// adding ~1 RTT to first-paint hydration.
//
// `findPageChunk()` walks dist/assets/ for a chunk whose filename
// starts with the page's source-file basename, and
// `injectPageChunkPreload()` rewrites the HTML to insert a
// `<link rel="modulepreload" crossorigin>` so the chunk fetches in
// parallel with the entry chunk.

import fs from "fs";
import path from "path";

export function findPageChunk(distDir, pageBasename) {
  const assetsDir = path.join(distDir, "assets");
  if (!fs.existsSync(assetsDir)) return null;
  const prefix = `${pageBasename}-`;
  for (const file of fs.readdirSync(assetsDir)) {
    if (file.startsWith(prefix) && file.endsWith(".js")) {
      return file;
    }
  }
  return null;
}

export function injectPageChunkPreload(html, chunkFile) {
  if (!chunkFile) return html;
  const href = `/assets/${chunkFile}`;
  if (html.includes(`href="${href}"`)) return html; // already present
  const link = `<link rel="modulepreload" crossorigin href="${href}">`;

  // Prefer to slot in next to the existing modulepreload block so the
  // browser sees all critical-path chunks together.
  const lastPreloadRe = /(<link rel="modulepreload"[^>]*>)(?![\s\S]*<link rel="modulepreload")/;
  if (lastPreloadRe.test(html)) {
    return html.replace(lastPreloadRe, `$1\n    ${link}`);
  }
  // Fall back to injecting immediately before the entry <script type="module">.
  return html.replace(
    /<script type="module"/,
    `${link}\n    <script type="module"`,
  );
}
