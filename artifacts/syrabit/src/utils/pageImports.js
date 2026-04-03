export const pageImports = {
  library: () => import("@/pages/LibraryPage"),
  chat: () => import("@/pages/ChatPage"),
  history: () => import("@/pages/HistoryPage"),
  profile: () => import("@/pages/ProfilePage"),
  chapter: () => import("@/pages/ChapterPage"),
};

export function prefetchCriticalRoutes() {
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(() => {
      pageImports.chat();
      pageImports.library();
    });
  } else {
    setTimeout(() => {
      pageImports.chat();
      pageImports.library();
    }, 1500);
  }
}
