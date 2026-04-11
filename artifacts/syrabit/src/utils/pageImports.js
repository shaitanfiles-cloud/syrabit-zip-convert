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
    if (path === '/chat' || path === '/') {
      schedule(() => pageImports.library(), 200);
      schedule(() => pageImports.chapter(), 800);
      schedule(() => warmApiCache(['/api/content/boards', '/api/content/subjects']), 400);
    } else if (path === '/library' || path.match(/^\/[a-z]+\/[a-z]/)) {
      schedule(() => pageImports.chat(), 200);
      schedule(() => pageImports.chapter(), 600);
      schedule(() => warmApiCache(['/api/content/boards']), 300);
    } else {
      schedule(() => pageImports.chat(), 300);
      schedule(() => pageImports.library(), 800);
      schedule(() => pageImports.chapter(), 1200);
      schedule(() => warmApiCache(['/api/content/boards']), 500);
    }
  };

  if (document.readyState === 'complete') {
    setTimeout(afterInteractive, 100);
  } else {
    window.addEventListener('load', () => setTimeout(afterInteractive, 200), { once: true });
  }
}
