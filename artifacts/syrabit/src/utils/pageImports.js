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
        pageImports.chat();
        requestIdleCallback(() => {
          pageImports.library();
          requestIdleCallback(() => { pageImports.chapter(); });
        });
      });
    } else {
      pageImports.chat();
      setTimeout(() => { pageImports.library(); }, 150);
      setTimeout(() => { pageImports.chapter(); }, 300);
    }
  };
  setTimeout(doPrefetch, 500);
}
