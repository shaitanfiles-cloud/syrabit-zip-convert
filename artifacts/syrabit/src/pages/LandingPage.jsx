import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import { PublicNavbar } from '@/components/layout/PublicNavbar';
import { useAuth } from '@/context/AuthContext';
import HeroSection from './landing/HeroSection';
import FeaturesGrid from './landing/FeaturesGrid';
import PricingSection from './landing/PricingSection';
import TestimonialsFooter from './landing/TestimonialsFooter';

export default function LandingPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  useEffect(() => {
    if (user) {
      navigate('/library', { replace: true });
    }
    const timer = setTimeout(() => {
      navigate('/library', { replace: true });
    }, 3000);
    return () => clearTimeout(timer);
  }, [user, navigate]);

  const year = new Date().getFullYear();

  return (
    <div className="min-h-screen text-white overflow-x-hidden" style={{ background: '#06060e' }}>
      <PageMeta
        title="Syrabit.ai — Educational Browser For AssamBoard Students"
        description="Syrabit.ai is the educational browser for AssamBoard students. Browse AHSEC Class 11-12, Degree (B.Com, B.A, B.Sc), and SEBA syllabus content, get instant answers, PYQs, notes, and MCQs — free to start. Trusted by 500+ students."
        url="https://syrabit.ai/"
        keywords="AssamBoard educational browser, AHSEC study app, SEBA study tool, Class 11 12 exam prep, AHSEC syllabus browser, degree exam prep Assam, B.Com B.A B.Sc notes, AssamBoard 2025 study tool, free educational browser India"
      />
      <PublicNavbar />
      <HeroSection />
      <FeaturesGrid />
      <PricingSection />
      <TestimonialsFooter year={year} />
    </div>
  );
}
