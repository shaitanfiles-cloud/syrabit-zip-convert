import { BrowserRouter, Routes, Route } from "react-router-dom";
import { lazy, Suspense, useEffect, useState } from "react";
import { PageTracker } from "@/utils/usePageTracking";
import { initGA4 } from "@/utils/analytics";
import { Toaster } from "sonner";
import { AuthProvider } from "@/context/AuthContext";
import { AuthGuard } from "@/components/AuthGuard";
import { AdminGuard } from "@/components/AdminGuard";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { HelmetProvider } from "react-helmet-async";
import { Loader2 } from "lucide-react";
import { apiClient } from "@/utils/api";

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


import { pageImports } from "@/utils/pageImports";

// ── React.lazy() code splitting — all pages ────────────────────────────────
const LandingPage        = lazy(() => import("@/pages/LandingPage"));
const LoginPage          = lazy(() => import("@/pages/LoginPage"));
const SignupPage         = lazy(() => import("@/pages/SignupPage"));
const ResetPasswordPage  = lazy(() => import("@/pages/ResetPasswordPage"));
const OnboardingPage     = lazy(() => import("@/pages/OnboardingPage"));
const LibraryPage        = lazy(pageImports.library);
const SubjectPage        = lazy(() => import("@/pages/SubjectPage"));
const ChatPage           = lazy(pageImports.chat);
const HistoryPage        = lazy(pageImports.history);
const ProfilePage        = lazy(pageImports.profile);
const PricingPage        = lazy(() => import("@/pages/PricingPage"));
const TermsPage          = lazy(() => import("@/pages/TermsPage"));
const PrivacyPage        = lazy(() => import("@/pages/PrivacyPage"));
const NotFoundPage       = lazy(() => import("@/pages/NotFoundPage"));
const AdminLoginPage     = lazy(() => import("@/pages/AdminLoginPage"));
const AdminPage          = lazy(() => import("@/pages/AdminPage"));
const ExamRoutinePage    = lazy(() => import("@/pages/ExamRoutinePage"));
const SeoTopicPage       = lazy(() => import("@/pages/SeoTopicPage"));
const SubjectLandingPage = lazy(() => import("@/pages/SubjectLandingPage"));
const CurriculumMap      = lazy(() => import("@/pages/CurriculumMap"));
const PaymentSuccessPage = lazy(() => import("@/pages/PaymentSuccessPage"));
const PaymentCancelPage  = lazy(() => import("@/pages/PaymentCancelPage"));
const LearnPage              = lazy(() => import("@/pages/LearnPage"));
const PYQReplicaPage         = lazy(() => import("@/pages/PYQReplicaPage"));
const PersonalizedCmsPage    = lazy(() => import("@/pages/PersonalizedCmsPage"));

// ── Page loading fallback (boot splash) ──────────────────────────────────────
const PageFallbackContent = () => (
  <div
    className="min-h-screen flex items-center justify-center bg-background"
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

function DeferredFallback({ delay = 300 }) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setShow(true), delay);
    return () => clearTimeout(timer);
  }, [delay]);
  return show ? <PageFallbackContent /> : null;
}

// ── App ───────────────────────────────────────────────────────────────────────
function App() {
  useEffect(() => { initGA4(); }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      queryClient.prefetchQuery({
        queryKey: ['library-bundle'],
        queryFn: () => apiClient().get('/content/library-bundle').then((r) => r.data),
        staleTime: 30 * 60 * 1000,
      });
    }, 1000);
    return () => clearTimeout(timer);
  }, []);

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
              <PageTracker />
              <Toaster richColors position="top-center" closeButton />
              <Suspense fallback={<DeferredFallback />}>
                <Routes>
                  {/* ── Public routes ── */}
                  <Route path="/"         element={<LandingPage />} />
                  <Route path="/pricing"  element={<PricingPage />} />
                  <Route path="/terms"    element={<TermsPage />} />
                  <Route path="/privacy"       element={<PrivacyPage />} />
                  <Route path="/exam-routine" element={<ExamRoutinePage />} />
                  <Route path="/payment/success" element={<PaymentSuccessPage />} />
                  <Route path="/payment/cancel" element={<PaymentCancelPage />} />

                  {/* ── Auth routes ── */}
                  <Route path="/login"          element={<LoginPage />} />
                  <Route path="/signup"         element={<SignupPage />} />
                  <Route path="/reset-password" element={<ResetPasswordPage />} />

                  {/* ── Onboarding (self-guarded) ── */}
                  <Route path="/onboarding" element={<OnboardingPage />} />

                  {/* ── Public content routes (no auth) ── */}
                  <Route path="/library"           element={<LibraryPage />} />
                  <Route path="/curriculum"        element={<CurriculumMap />} />
                  <Route path="/subject/:subjectId" element={<SubjectPage />} />

                  {/* ── CMS Learn pages ── */}
                  <Route path="/learn/:slug" element={<LearnPage />} />

                  {/* ── Personalized CMS (private, paid) ── */}
                  <Route path="/cms/:userId/:slug" element={<AuthGuard><PersonalizedCmsPage /></AuthGuard>} />

                  {/* /subscribe → pricing */}
                  <Route path="/subscribe" element={<PricingPage />} />

                  {/* ── PYQ HTML Replica pages ── */}
                  <Route path="/pyq/:slug" element={<PYQReplicaPage />} />

                  {/* ── Programmatic SEO routes: /{board}/{class-N}/{subject}/{topic}/{type?} ── */}
                  <Route path="/:board/:classSlug/:subjectSlug/:topicSlug/:pageType" element={<SeoTopicPage />} />
                  <Route path="/:board/:classSlug/:subjectSlug/:topicSlug" element={<SeoTopicPage />} />
                  <Route path="/:board/:classSlug/:subjectSlug" element={<SubjectLandingPage />} />

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
