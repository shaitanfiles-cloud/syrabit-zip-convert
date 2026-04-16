import { useEffect, lazy, Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import { PublicNavbar } from '@/components/layout/PublicNavbar';
import { PublicBottomNav } from '@/components/layout/PublicBottomNav';
import { useAuth } from '@/context/AuthContext';
import { useContentLang } from '@/context/LanguageContext';
import HeroSection from './landing/HeroSection';
const FeaturesGrid = lazy(() => import('./landing/FeaturesGrid'));
const PricingSection = lazy(() => import('./landing/PricingSection'));
const PlatformSection = lazy(() => import('./landing/PlatformSection'));
const TestimonialsFooter = lazy(() => import('./landing/TestimonialsFooter'));

const _meta = {
  en: {
    title: "Syrabit.ai — Educational Browser For AssamBoard Students",
    description: "Syrabit.ai is the educational browser for AssamBoard students. Browse AHSEC Class 11-12, Degree (B.Com, B.A, B.Sc), and SEBA syllabus content, get instant answers, PYQs, notes, and MCQs — free to start. Trusted by students across Assam.",
  },
  as: {
    title: "Syrabit.ai — অসম বোৰ্ডৰ ছাত্ৰ-ছাত্ৰীৰ বাবে শৈক্ষিক ব্ৰাউজাৰ",
    description: "Syrabit.ai হৈছে অসম বোৰ্ডৰ ছাত্ৰ-ছাত্ৰীৰ বাবে শৈক্ষিক ব্ৰাউজাৰ। AHSEC একাদশ-দ্বাদশ শ্ৰেণী, ডিগ্ৰী (B.Com, B.A, B.Sc), আৰু SEBA পাঠ্যক্ৰমৰ বিষয়বস্তু ব্ৰাউজ কৰক, তাৎক্ষণিক উত্তৰ, PYQ, টোকা, আৰু MCQ পাওক — বিনামূলীয়াকৈ আৰম্ভ কৰক।",
  },
};

function LangToggle({ contentLang, switchLang }) {
  return (
    <div className="fixed top-20 right-4 z-30 flex items-center gap-1 rounded-xl p-0.5" style={{ background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.12)', backdropFilter: 'blur(8px)' }}>
      <button
        onClick={() => switchLang('en')}
        className={`h-8 px-2.5 rounded-lg text-xs font-semibold transition-all ${
          contentLang === 'en'
            ? 'text-white bg-violet-600 shadow-sm'
            : 'text-violet-400 hover:bg-violet-500/10'
        }`}
      >
        EN
      </button>
      <button
        onClick={() => switchLang('as')}
        className={`h-8 px-2.5 rounded-lg text-xs font-semibold transition-all ${
          contentLang === 'as'
            ? 'text-white bg-violet-600 shadow-sm'
            : 'text-violet-400 hover:bg-violet-500/10'
        }`}
      >
        অসমীয়া
      </button>
    </div>
  );
}

export default function LandingPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { contentLang, switchLang } = useContentLang();

  useEffect(() => {
    if (user) {
      navigate('/chat', { replace: true });
    }
  }, [user, navigate]);

  const year = new Date().getFullYear();
  const m = _meta[contentLang] || _meta.en;

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: m.title,
    url: 'https://syrabit.ai/',
    inLanguage: contentLang === 'as' ? ['as', 'en'] : ['en', 'as'],
    description: m.description,
    isPartOf: { '@type': 'WebSite', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
  };

  return (
    <div className="min-h-screen text-foreground overflow-x-hidden bg-background">
      <PageMeta
        title={m.title}
        description={m.description}
        url="https://syrabit.ai/"
        keywords="AssamBoard educational browser, AHSEC study app, SEBA study tool, Class 11 12 exam prep, AHSEC syllabus browser, degree exam prep Assam, B.Com B.A B.Sc notes, AssamBoard 2025 study tool, free educational browser India"
        jsonLd={jsonLd}
      />
      <PublicNavbar />
      <LangToggle contentLang={contentLang} switchLang={switchLang} />
      <HeroSection contentLang={contentLang} />
      <Suspense fallback={null}>
        <FeaturesGrid contentLang={contentLang} />
        <PlatformSection contentLang={contentLang} />
        <PricingSection contentLang={contentLang} />
        <TestimonialsFooter year={year} contentLang={contentLang} />
      </Suspense>
      <PublicBottomNav />
    </div>
  );
}
