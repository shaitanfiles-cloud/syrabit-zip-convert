const prefetched = new Set();
const pending = new Map();

const routeImports = {
  '/library': () => import('@/pages/LibraryPage'),
  '/chat': () => import('@/pages/ChatPage'),
  '/history': () => import('@/pages/HistoryPage'),
  '/profile': () => import('@/pages/ProfilePage'),
  '/pricing': () => import('@/pages/PricingPage'),
  '/curriculum': () => import('@/pages/CurriculumMap'),
  '/exam-routine': () => import('@/pages/ExamRoutinePage'),
  '/login': () => import('@/pages/LoginPage'),
  '/signup': () => import('@/pages/SignupPage'),
};

export function prefetchRoute(path) {
  if (prefetched.has(path) || pending.has(path)) return;
  const loader = routeImports[path];
  if (!loader) return;
  const timer = setTimeout(() => {
    pending.delete(path);
    loader()
      .then(() => prefetched.add(path))
      .catch(() => {});
  }, 50);
  pending.set(path, timer);
}
