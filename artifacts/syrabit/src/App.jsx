import "./App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { lazy, Suspense, useEffect } from "react";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/context/AuthContext";
import { AuthGuard } from "@/components/AuthGuard";
import { AdminGuard } from "@/components/AdminGuard";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { HelmetProvider } from "react-helmet-async";
import { Loader2 } from "lucide-react";

// ── React Query client ────────────────────────────────────────────────────────
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      gcTime: 60 * 60 * 1000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

import axios from 'axios';
const API_BASE = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;
queryClient.prefetchQuery({
  queryKey: ['library-bundle'],
  queryFn: () => axios.get(`${API_BASE}/content/library-bundle`).then(r => r.data),
  staleTime: 30 * 60 * 1000,
});

// ── React.lazy() code splitting — all pages ────────────────────────────────
const LandingPage        = lazy(() => import("@/pages/LandingPage"));
const LoginPage          = lazy(() => import("@/pages/LoginPage"));
const SignupPage         = lazy(() => import("@/pages/SignupPage"));
const ResetPasswordPage  = lazy(() => import("@/pages/ResetPasswordPage"));
const OnboardingPage     = lazy(() => import("@/pages/OnboardingPage"));
const LibraryPage        = lazy(() => import("@/pages/LibraryPage"));
const SubjectPage        = lazy(() => import("@/pages/SubjectPage"));
const ChatPage           = lazy(() => import("@/pages/ChatPage"));
const HistoryPage        = lazy(() => import("@/pages/HistoryPage"));
const ProfilePage        = lazy(() => import("@/pages/ProfilePage"));
const PricingPage        = lazy(() => import("@/pages/PricingPage"));
const TermsPage          = lazy(() => import("@/pages/TermsPage"));
const PrivacyPage        = lazy(() => import("@/pages/PrivacyPage"));
const NotFoundPage       = lazy(() => import("@/pages/NotFoundPage"));
const AdminLoginPage     = lazy(() => import("@/pages/AdminLoginPage"));
const AdminPage          = lazy(() => import("@/pages/AdminPage"));
const ExamRoutinePage    = lazy(() => import("@/pages/ExamRoutinePage"));
const SeoTopicPage       = lazy(() => import("@/pages/SeoTopicPage"));
const SeoSubjectRedirect = lazy(() => import("@/pages/SeoSubjectRedirect"));

// ── Page loading fallback (boot splash) ──────────────────────────────────────
const PageFallback = () => (
  <div
    className="min-h-screen flex items-center justify-center bg-background futuristic-bg"
    role="status"
    aria-label="Loading Syrabit.ai"
  >
    <div className="flex flex-col items-center gap-4">
      <div className="relative">
        <div
          className="w-14 h-14 rounded-2xl flex items-center justify-center pulse-glow overflow-hidden"
          aria-hidden="true"
        >
          <img src="/logo.png" alt="" className="w-14 h-14 object-cover" />
        </div>
        <div
          className="absolute orbit-ring"
          style={{
            inset: "-5px",
            borderRadius: "1rem",
            border: "1px solid hsl(var(--primary) / 0.25)",
          }}
          aria-hidden="true"
        />
      </div>
      <Loader2
        className="w-5 h-5 animate-spin text-primary"
        aria-hidden="true"
      />
      <span className="sr-only">Loading page…</span>
    </div>
  </div>
);

// ── App ───────────────────────────────────────────────────────────────────────
function App() {
  // Nuke Emergent badge completely — fast interval + all hiding properties
  useEffect(() => {
    const HIDE = [
      'display:none!important',
      'visibility:hidden!important',
      'opacity:0!important',
      'width:0!important',
      'height:0!important',
      'max-width:0!important',
      'max-height:0!important',
      'min-width:0!important',
      'min-height:0!important',
      'overflow:hidden!important',
      'clip:rect(0 0 0 0)!important',
      'clip-path:inset(50%)!important',
      'transform:scale(0)!important',
      'border:0!important',
      'padding:0!important',
      'margin:0!important',
      'background:transparent!important',
      'box-shadow:none!important',
      'position:fixed!important',
      'bottom:0!important',
      'right:0!important',
      'z-index:-9999!important',
      'pointer-events:none!important',
    ].join(';');

    const nuke = () => {
      ['#emergent-badge', 'a[href*="emergent.sh"]', '[id*="emergent-badge"]'].forEach((sel) => {
        document.querySelectorAll(sel).forEach((el) => {
          el.style.cssText = HIDE;
          el.querySelectorAll('*').forEach((c) => {
            c.style.cssText = 'display:none!important;width:0!important;height:0!important;font-size:0!important;color:transparent!important;';
          });
        });
      });
    };

    nuke();
    // Fast interval for first 5s, then maintenance interval
    const fastIv = setInterval(nuke, 100);
    const slowIv = setTimeout(() => {
      clearInterval(fastIv);
      setInterval(nuke, 2000);
    }, 5000);

    const mo = new MutationObserver(nuke);
    mo.observe(document.documentElement, { childList: true, subtree: true });

    return () => {
      clearInterval(fastIv);
      clearTimeout(slowIv);
      mo.disconnect();
    };
  }, []);
  return (
    <HelmetProvider>
    <ErrorBoundary>
      <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false}>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <BrowserRouter>
              <Toaster richColors position="top-right" closeButton />
              <Suspense fallback={<PageFallback />}>
                <Routes>
                  {/* ── Public routes ── */}
                  <Route path="/"         element={<LandingPage />} />
                  <Route path="/pricing"  element={<PricingPage />} />
                  <Route path="/terms"    element={<TermsPage />} />
                  <Route path="/privacy"       element={<PrivacyPage />} />
                  <Route path="/exam-routine" element={<ExamRoutinePage />} />

                  {/* ── Auth routes ── */}
                  <Route path="/login"          element={<LoginPage />} />
                  <Route path="/signup"         element={<SignupPage />} />
                  <Route path="/reset-password" element={<ResetPasswordPage />} />

                  {/* ── Onboarding (self-guarded) ── */}
                  <Route path="/onboarding" element={<OnboardingPage />} />

                  {/* ── Public content routes (no auth) ── */}
                  <Route path="/library"           element={<LibraryPage />} />
                  <Route path="/subject/:subjectId" element={<SubjectPage />} />

                  {/* ── Programmatic SEO routes ── */}
                  <Route path="/:board/:classSlug/:streamSlug/:subjectSlug" element={<SeoSubjectRedirect />} />
                  <Route path="/:board/:classSlug/:subjectSlug/:chapterSlug/:topicSlug/:pageType" element={<SeoTopicPage />} />
                  <Route path="/:board/:classSlug/:subjectSlug/:chapterSlug/:topicSlug" element={<SeoTopicPage />} />

                  {/* ── Protected routes (require login) ── */}
                  <Route path="/chat"              element={<AuthGuard><ChatPage /></AuthGuard>} />
                  <Route path="/history"           element={<AuthGuard><HistoryPage /></AuthGuard>} />
                  <Route path="/profile"           element={<AuthGuard><ProfilePage /></AuthGuard>} />

                  {/* ── Admin routes ── */}
                  <Route path="/admin/login" element={<AdminLoginPage />} />
                  <Route path="/admin"       element={<AdminGuard><AdminPage /></AdminGuard>} />

                  {/* ── 404 ── */}
                  <Route path="*" element={<NotFoundPage />} />
                </Routes>
              </Suspense>
            </BrowserRouter>
          </AuthProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </ErrorBoundary>
    </HelmetProvider>
  );
}

export default App;
