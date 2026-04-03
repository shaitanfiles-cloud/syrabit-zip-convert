export const pageImports = {
  library: () => import("@/pages/LibraryPage"),
  chat: () => import("@/pages/ChatPage"),
  history: () => import("@/pages/HistoryPage"),
  profile: () => import("@/pages/ProfilePage"),
  seoTopic: () => import("@/pages/SeoTopicPage"),
};

export function prefetchCriticalRoutes() {
  if (typeof requestIdleCallback === 'function') {
    requestIdleCallback(() => {
      pageImports.chat();
      pageImports.library();
      pageImports.seoTopic();
    });
  } else {
    setTimeout(() => {
      pageImports.chat();
      pageImports.library();
      pageImports.seoTopic();
    }, 1500);
  }
}
