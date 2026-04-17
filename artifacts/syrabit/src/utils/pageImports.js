export const pageImports = {
  library: () => import("@/pages/LibraryPage"),
  chat: () => import("@/pages/ChatPage"),
  history: () => import("@/pages/HistoryPage"),
  profile: () => import("@/pages/ProfilePage"),
  chapter: () => import("@/pages/ChapterPage"),
};

function warmApiCache(paths) {
  const backendUrl = import.meta.env.VITE_BACKEND_URL || '';
  paths.forEach((p) => {
    fetch(backendUrl + p, { priority: 'low' }).catch(() => {});
  });
}

export function prefetchCriticalRoutes() {
  const schedule = (fn, delay) => {
    if (typeof requestIdleCallback === 'function') {
      setTimeout(() => requestIdleCallback(fn, { timeout: 3000 }), delay);
    } else {
      setTimeout(fn, delay);
    }
  };

  const afterInteractive = () => {
    const path = window.location.pathname;
    // Landing/chat: defer aggressively so prefetch never competes with hydration
    // (was: 200ms library + 800ms chapter — caused TBT 1.8s and TTI 14s on slow devices).
    if (path === '/' || path === '/chat') {
      schedule(() => pageImports.library(), 4000);
      schedule(() => warmApiCache(['/api/content/boards']), 2500);
      // Drop chapter prefetch on landing — most landing visitors never reach a chapter,
      // and the chapter chunk transitively pulls the heavy markdown bundle (~458KB).
    } else if (path === '/library' || path.match(/^\/[a-z]+\/[a-z]/)) {
      schedule(() => pageImports.chat(), 1500);
      schedule(() => pageImports.chapter(), 2500);
      schedule(() => warmApiCache(['/api/content/boards']), 1500);
    } else {
      schedule(() => pageImports.chat(), 2500);
      schedule(() => pageImports.library(), 3500);
      schedule(() => warmApiCache(['/api/content/boards']), 2000);
    }
  };

  // Wait for full load + an extra 1.5s so the main thread is idle before we
  // start downloading & parsing additional route chunks. This fixes Lighthouse
  // TTI/TBT regressions caused by eager prefetch on landing.
  if (document.readyState === 'complete') {
    setTimeout(afterInteractive, 1500);
  } else {
    window.addEventListener('load', () => setTimeout(afterInteractive, 1500), { once: true });
  }
}
