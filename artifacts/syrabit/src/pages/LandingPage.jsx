import { useEffect, lazy, Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import { PublicNavbar } from '@/components/layout/PublicNavbar';
import { PublicBottomNav } from '@/components/layout/PublicBottomNav';
import { useAuth } from '@/context/AuthContext';
import HeroSection from './landing/HeroSection';
const FeaturesGrid = lazy(() => import('./landing/FeaturesGrid'));
const PricingSection = lazy(() => import('./landing/PricingSection'));
const PlatformSection = lazy(() => import('./landing/PlatformSection'));
const TestimonialsFooter = lazy(() => import('./landing/TestimonialsFooter'));

export default function LandingPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  useEffect(() => {
    if (user) {
      navigate('/chat', { replace: true });
    }
  }, [user, navigate]);

  const year = new Date().getFullYear();

  return (
    <div className="min-h-screen text-foreground overflow-x-hidden bg-background">
      <PageMeta
        title="Syrabit.ai — Educational Browser For AssamBoard Students"
        description="Syrabit.ai is the educational browser for AssamBoard students. Browse AHSEC Class 11-12, Degree (B.Com, B.A, B.Sc), and SEBA syllabus content, get instant answers, PYQs, notes, and MCQs — free to start. Trusted by students across Assam."
        url="https://syrabit.ai/"
        keywords="AssamBoard educational browser, AHSEC study app, SEBA study tool, Class 11 12 exam prep, AHSEC syllabus browser, degree exam prep Assam, B.Com B.A B.Sc notes, AssamBoard 2025 study tool, free educational browser India"
      />
      <PublicNavbar />
      <HeroSection />
      <Suspense fallback={null}>
        <FeaturesGrid />
        <PlatformSection />
        <PricingSection />
        <TestimonialsFooter year={year} />
      </Suspense>
      <PublicBottomNav />
    </div>
  );
}
