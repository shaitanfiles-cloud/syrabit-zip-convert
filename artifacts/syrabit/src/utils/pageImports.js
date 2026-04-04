export const pageImports = {
  library: () => import("@/pages/LibraryPage"),
  chat: () => import("@/pages/ChatPage"),
  history: () => import("@/pages/HistoryPage"),
  profile: () => import("@/pages/ProfilePage"),
  chapter: () => import("@/pages/ChapterPage"),
};

export function prefetchCriticalRoutes() {
  const doPrefetch = () => {
    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(() => {
        pageImports.library();
        requestIdleCallback(() => { pageImports.chat(); });
      });
    } else {
      pageImports.library();
      setTimeout(() => { pageImports.chat(); }, 500);
    }
  };
  setTimeout(doPrefetch, 4000);
}
