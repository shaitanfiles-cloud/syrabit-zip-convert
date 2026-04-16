import { PublicLayout } from '@/components/layout/PublicLayout';
import { Link } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import { useContentLang } from '@/context/LanguageContext';
import {
  Brain, BookOpen, GraduationCap, Smartphone, Sparkles,
  Shield, CreditCard, Search, Bell, Languages,
  Globe, FileText, Star, ChevronRight, Zap,
} from 'lucide-react';

const CATEGORIES = [
  {
    icon: Brain,
    color: '#7c3aed',
    featureCount: 13,
    en: {
      title: 'AI Study Assistant',
      description: 'Ask Syra anything about your syllabus and get instant, source-cited answers grounded in your actual chapter content. Supports both English and Assamese.',
      highlights: ['Instant syllabus-aligned answers', 'Source citations on every response', 'Bilingual AI tutoring (EN/অসমীয়া)'],
    },
    as: {
      title: 'AI অধ্যয়ন সহায়ক',
      description: 'আপোনাৰ পাঠ্যক্ৰমৰ বিষয়ে Syra ক যিকোনো কথা সুধক আৰু আপোনাৰ প্ৰকৃত অধ্যায়ৰ বিষয়বস্তুত ভিত্তি কৰি তৎক্ষণাত উৎস-উদ্ধৃত উত্তৰ পাওক। ইংৰাজী আৰু অসমীয়া দুয়োটাতে সমৰ্থন কৰে।',
      highlights: ['তৎক্ষণাত পাঠ্যক্ৰম-সংযুক্ত উত্তৰ', 'প্ৰতিটো উত্তৰত উৎস উদ্ধৃতি', 'দ্বিভাষিক AI শিক্ষণ (EN/অসমীয়া)'],
    },
  },
  {
    icon: BookOpen,
    color: '#2563eb',
    featureCount: 8,
    en: {
      title: 'Smart Content Library',
      description: 'Browse 55+ subjects organized by board, class, and stream. Each subject is a structured knowledge hub with chapter-wise notes, summaries, and study guides.',
      highlights: ['55+ subjects across AHSEC, SEBA & Degree', 'Chapter-wise structured notes', 'SEO-optimized study guides'],
    },
    as: {
      title: 'স্মাৰ্ট বিষয়বস্তু পুথিভঁৰাল',
      description: 'বৰ্ড, শ্ৰেণী, আৰু শাখা অনুসাৰে সজোৱা ৫৫+ বিষয় ব্ৰাউজ কৰক। প্ৰতিটো বিষয় অধ্যায়ভিত্তিক টোকা, সাৰাংশ, আৰু অধ্যয়ন গাইডৰ সৈতে এটা গাঁথনিগত জ্ঞান কেন্দ্ৰ।',
      highlights: ['AHSEC, SEBA আৰু ডিগ্ৰীৰ ৫৫+ বিষয়', 'অধ্যায়ভিত্তিক গাঁথনিগত টোকা', 'SEO-অনুকূলিত অধ্যয়ন গাইড'],
    },
  },
  {
    icon: GraduationCap,
    color: '#059669',
    featureCount: 21,
    en: {
      title: 'Exam Preparation Tools',
      description: 'Previous year questions with solutions, mark-wise question banks (1, 2, 3, 5, 10 marks), MCQs, important questions, flashcards, and memory tricks — all aligned to your board syllabus.',
      highlights: ['Previous year questions with solutions', 'Mark-wise question banks', 'Flashcards & memory tricks'],
    },
    as: {
      title: 'পৰীক্ষাৰ প্ৰস্তুতি সঁজুলি',
      description: 'সমাধানসহ আগৰ বছৰৰ প্ৰশ্ন, নম্বৰভিত্তিক প্ৰশ্ন বেংক (১, ২, ৩, ৫, ১০ নম্বৰ), MCQ, গুৰুত্বপূৰ্ণ প্ৰশ্ন, ফ্লেচকাৰ্ড, আৰু স্মৃতি কৌশল — সকলো আপোনাৰ বৰ্ড পাঠ্যক্ৰমৰ সৈতে সংযুক্ত।',
      highlights: ['সমাধানসহ আগৰ বছৰৰ প্ৰশ্ন', 'নম্বৰভিত্তিক প্ৰশ্ন বেংক', 'ফ্লেচকাৰ্ড আৰু স্মৃতি কৌশল'],
    },
  },
  {
    icon: Smartphone,
    color: '#d97706',
    featureCount: 6,
    en: {
      title: 'Offline & Mobile Ready',
      description: 'Install Syrabit.ai on your phone like a native app. Access cached study materials even without internet — perfect for students in areas with limited connectivity.',
      highlights: ['Install as mobile app', 'Offline access to study materials', 'Works on any device'],
    },
    as: {
      title: 'অফলাইন আৰু মোবাইল সাজু',
      description: 'Syrabit.ai আপোনাৰ ফোনত এটা নেটিভ এপৰ দৰে ইনস্টল কৰক। ইণ্টাৰনেট নোহোৱাকৈও কেচ কৰা অধ্যয়ন সামগ্ৰী অভিগম কৰক — সীমিত সংযোগ থকা অঞ্চলৰ ছাত্ৰ-ছাত্ৰীৰ বাবে উপযুক্ত।',
      highlights: ['মোবাইল এপ হিচাপে ইনস্টল কৰক', 'অধ্যয়ন সামগ্ৰীলৈ অফলাইন অভিগম', 'যিকোনো ডিভাইচত কাম কৰে'],
    },
  },
  {
    icon: Sparkles,
    color: '#ec4899',
    featureCount: 18,
    en: {
      title: 'Personalized Learning',
      description: 'Set your board, class, and stream during onboarding and get a tailored experience. Your AI tutor adapts to your academic context, showing only relevant content.',
      highlights: ['Board & stream-specific content', 'Adaptive AI responses', 'Personal study dashboard'],
    },
    as: {
      title: 'ব্যক্তিগতকৃত শিক্ষণ',
      description: 'অনবৰ্ডিংৰ সময়ত আপোনাৰ বৰ্ড, শ্ৰেণী, আৰু শাখা ছেট কৰক আৰু এটা উপযুক্ত অভিজ্ঞতা পাওক। আপোনাৰ AI শিক্ষকে আপোনাৰ শৈক্ষিক প্ৰসংগৰ সৈতে খাপ খায়, কেৱল প্ৰাসংগিক বিষয়বস্তু দেখুৱায়।',
      highlights: ['বৰ্ড আৰু শাখা-নিৰ্দিষ্ট বিষয়বস্তু', 'অভিযোজিত AI উত্তৰ', 'ব্যক্তিগত অধ্যয়ন ডেচবৰ্ড'],
    },
  },
  {
    icon: Search,
    color: '#0891b2',
    featureCount: 9,
    en: {
      title: 'Smart Search & Discovery',
      description: 'Find any topic instantly with intelligent search across all subjects. Deep-topic landing pages help you explore concepts with structured explanations and related questions.',
      highlights: ['Instant topic search', 'Deep-topic exploration pages', 'Related questions & concepts'],
    },
    as: {
      title: 'স্মাৰ্ট সন্ধান আৰু আৱিষ্কাৰ',
      description: 'সকলো বিষয়ত বুদ্ধিমান সন্ধানৰ সৈতে তৎক্ষণাত যিকোনো বিষয়বস্তু বিচাৰক। গভীৰ-বিষয়বস্তু লেণ্ডিং পৃষ্ঠাই আপোনাক গাঁথনিগত ব্যাখ্যা আৰু সম্পৰ্কীয় প্ৰশ্নৰ সৈতে ধাৰণা অন্বেষণ কৰাত সহায় কৰে।',
      highlights: ['তৎক্ষণাত বিষয়বস্তু সন্ধান', 'গভীৰ-বিষয়বস্তু অন্বেষণ পৃষ্ঠা', 'সম্পৰ্কীয় প্ৰশ্ন আৰু ধাৰণা'],
    },
  },
  {
    icon: Languages,
    color: '#6366f1',
    featureCount: 4,
    en: {
      title: 'Bilingual Support',
      description: 'Full English and Assamese (অসমীয়া) support across the entire platform — from AI answers to study notes to the interface itself. Switch languages anytime with one tap.',
      highlights: ['Full Assamese language support', 'Bilingual AI answers', 'One-tap language switching'],
    },
    as: {
      title: 'দ্বিভাষিক সমৰ্থন',
      description: 'সমগ্ৰ মঞ্চত সম্পূৰ্ণ ইংৰাজী আৰু অসমীয়া সমৰ্থন — AI উত্তৰৰ পৰা অধ্যয়ন টোকালৈ ইণ্টাৰফেচলৈকে। যিকোনো সময়তে এটা টেপত ভাষা সলনি কৰক।',
      highlights: ['সম্পূৰ্ণ অসমীয়া ভাষাৰ সমৰ্থন', 'দ্বিভাষিক AI উত্তৰ', 'এটা টেপত ভাষা সলনি'],
    },
  },
  {
    icon: CreditCard,
    color: '#dc2626',
    featureCount: 12,
    en: {
      title: 'Flexible Plans & Payments',
      description: 'Start free with 30 daily credits. Upgrade to Starter or Pro for more credits and premium content. Pay via UPI, cards, or international methods.',
      highlights: ['Free tier with 30 daily credits', 'UPI & card payments', 'Credit top-ups available'],
    },
    as: {
      title: 'নমনীয় পৰিকল্পনা আৰু পৰিশোধ',
      description: '৩০ টা দৈনিক ক্ৰেডিটৰ সৈতে বিনামূলীয়াকৈ আৰম্ভ কৰক। অধিক ক্ৰেডিট আৰু প্ৰিমিয়াম বিষয়বস্তুৰ বাবে Starter বা Pro লৈ আপগ্ৰেড কৰক। UPI, কাৰ্ড, বা আন্তৰ্জাতিক পদ্ধতিৰে পৰিশোধ কৰক।',
      highlights: ['৩০ টা দৈনিক ক্ৰেডিটৰ সৈতে বিনামূলীয়া', 'UPI আৰু কাৰ্ড পৰিশোধ', 'ক্ৰেডিট টপ-আপ উপলব্ধ'],
    },
  },
  {
    icon: Shield,
    color: '#475569',
    featureCount: 8,
    en: {
      title: 'Trust & Accuracy',
      description: 'Every AI answer includes source citations so you can verify the information. Syra never makes things up — if it can\'t find relevant content with high confidence, it tells you.',
      highlights: ['Source citations on every answer', 'No hallucination guarantee', 'Syllabus-grounded responses'],
    },
    as: {
      title: 'বিশ্বাস আৰু সঠিকতা',
      description: 'প্ৰতিটো AI উত্তৰত উৎস উদ্ধৃতি অন্তৰ্ভুক্ত থাকে যাতে আপুনি তথ্য পৰীক্ষা কৰিব পাৰে। Syra ই কেতিয়াও কথা সাজি নুলিয়ায় — যদি ই উচ্চ আত্মবিশ্বাসেৰে প্ৰাসংগিক বিষয়বস্তু বিচাৰি নাপায়, তেন্তে ই আপোনাক জনায়।',
      highlights: ['প্ৰতিটো উত্তৰত উৎস উদ্ধৃতি', 'কোনো হেলুচিনেচন নাই', 'পাঠ্যক্ৰম-ভিত্তিক উত্তৰ'],
    },
  },
  {
    icon: Bell,
    color: '#7c2d12',
    featureCount: 8,
    en: {
      title: 'Notifications & Updates',
      description: 'Get push notifications for exam schedules, new content, and important updates. Stay informed about board exam routines, result dates, and study reminders.',
      highlights: ['Exam schedule alerts', 'New content notifications', 'Board exam routine updates'],
    },
    as: {
      title: 'জাননী আৰু আপডেট',
      description: 'পৰীক্ষাৰ সূচী, নতুন বিষয়বস্তু, আৰু গুৰুত্বপূৰ্ণ আপডেটৰ বাবে পুশ্ব জাননী পাওক। বৰ্ড পৰীক্ষাৰ ৰুটিন, ফলাফলৰ তাৰিখ, আৰু অধ্যয়নৰ সোঁৱৰণীৰ বিষয়ে অৱগত থাকক।',
      highlights: ['পৰীক্ষাৰ সূচী সতৰ্কতা', 'নতুন বিষয়বস্তুৰ জাননী', 'বৰ্ড পৰীক্ষাৰ ৰুটিন আপডেট'],
    },
  },
];

const STATS = {
  en: [
    { value: '159', label: 'Platform Features' },
    { value: '55+', label: 'Subjects Covered' },
    { value: '3', label: 'Boards Supported' },
    { value: '6', label: 'Content Types' },
  ],
  as: [
    { value: '১৫৯', label: 'মঞ্চৰ বৈশিষ্ট্য' },
    { value: '৫৫+', label: 'বিষয় সামৰি লোৱা' },
    { value: '৩', label: 'বৰ্ড সমৰ্থিত' },
    { value: '৬', label: 'বিষয়বস্তুৰ প্ৰকাৰ' },
  ],
};

const _t = {
  en: {
    pageTitle: 'Technology & Features',
    pageDescription: 'Explore 159 features across 10 categories powering Syrabit.ai — the AI exam preparation platform for AHSEC, SEBA and Degree students in Assam.',
    heroHeading: 'What Powers Your Learning',
    heroSubtext: 'Syrabit.ai brings together 159 features across 10 categories to deliver a complete AI-powered study experience for students in Assam. Here\'s what the platform does for you.',
    categoriesHeading: 'Platform Capabilities',
    categoriesSubtext: 'Every feature is designed to help you study smarter, prepare better, and score higher on your board exams.',
    boardsTitle: 'Built for Your Board',
    boardsSubtext: 'Whether you\'re preparing for AHSEC, SEBA, or university exams — Syrabit.ai covers your syllabus.',
    boards: [
      { name: 'AHSEC', desc: 'Class 11 & 12 — Science, Commerce, Arts' },
      { name: 'SEBA', desc: 'Secondary board curriculum' },
      { name: 'Degree', desc: 'B.Com, B.A, B.Sc under GU & DU' },
    ],
    contentTypesTitle: 'Content You Get',
    contentTypes: [
      'Chapter-wise study notes',
      'Previous year questions with solutions',
      'Mark-wise question banks (1, 2, 3, 5, 10 marks)',
      'Multiple choice questions (MCQs)',
      'Flashcards & memory tricks',
      'AI-generated study guides',
    ],
    founderLabel: 'Founded by',
    ctaHeading: 'Start Learning for Free',
    ctaSubtext: 'No credit card required. Get 30 free credits every day.',
    ctaButton: 'Try Syrabit.ai',
    features: 'features',
  },
  as: {
    pageTitle: 'প্ৰযুক্তি আৰু বৈশিষ্ট্য',
    pageDescription: 'Syrabit.ai চালিত ১০ টা শ্ৰেণীত ১৫৯ টা বৈশিষ্ট্য অন্বেষণ কৰক — অসমৰ AHSEC, SEBA আৰু ডিগ্ৰী ছাত্ৰ-ছাত্ৰীৰ বাবে AI পৰীক্ষা প্ৰস্তুতি মঞ্চ।',
    heroHeading: 'আপোনাৰ শিক্ষণক কিহে চালিত কৰে',
    heroSubtext: 'অসমৰ ছাত্ৰ-ছাত্ৰীৰ বাবে সম্পূৰ্ণ AI-চালিত অধ্যয়ন অভিজ্ঞতা প্ৰদান কৰিবলৈ Syrabit.ai য়ে ১০ টা শ্ৰেণীত ১৫৯ টা বৈশিষ্ট্য একত্ৰিত কৰে। মঞ্চখনে আপোনাৰ বাবে কি কৰে ইয়াত আছে।',
    categoriesHeading: 'মঞ্চৰ সক্ষমতা',
    categoriesSubtext: 'প্ৰতিটো বৈশিষ্ট্য আপোনাক স্মাৰ্ট অধ্যয়ন কৰাত, ভালকৈ প্ৰস্তুতি লোৱাত, আৰু বৰ্ড পৰীক্ষাত উচ্চ নম্বৰ পোৱাত সহায় কৰিবলৈ ডিজাইন কৰা হৈছে।',
    boardsTitle: 'আপোনাৰ বৰ্ডৰ বাবে নিৰ্মিত',
    boardsSubtext: 'আপুনি AHSEC, SEBA, বা বিশ্ববিদ্যালয় পৰীক্ষাৰ বাবে প্ৰস্তুতি লওক — Syrabit.ai ই আপোনাৰ পাঠ্যক্ৰম সামৰে।',
    boards: [
      { name: 'AHSEC', desc: 'শ্ৰেণী ১১ আৰু ১২ — বিজ্ঞান, বাণিজ্য, কলা' },
      { name: 'SEBA', desc: 'মাধ্যমিক বৰ্ড পাঠ্যক্ৰম' },
      { name: 'ডিগ্ৰী', desc: 'GU আৰু DU ৰ অধীনত B.Com, B.A, B.Sc' },
    ],
    contentTypesTitle: 'আপুনি পোৱা বিষয়বস্তু',
    contentTypes: [
      'অধ্যায়ভিত্তিক অধ্যয়ন টোকা',
      'সমাধানসহ আগৰ বছৰৰ প্ৰশ্ন',
      'নম্বৰভিত্তিক প্ৰশ্ন বেংক (১, ২, ৩, ৫, ১০ নম্বৰ)',
      'বহুবিকল্পৰ প্ৰশ্ন (MCQ)',
      'ফ্লেচকাৰ্ড আৰু স্মৃতি কৌশল',
      'AI-সৃষ্ট অধ্যয়ন গাইড',
    ],
    founderLabel: 'প্ৰতিষ্ঠাপক',
    ctaHeading: 'বিনামূলীয়াকৈ শিকিবলৈ আৰম্ভ কৰক',
    ctaSubtext: 'কোনো ক্ৰেডিট কাৰ্ডৰ প্ৰয়োজন নাই। প্ৰতিদিনে ৩০ টা বিনামূলীয়া ক্ৰেডিট পাওক।',
    ctaButton: 'Syrabit.ai চেষ্টা কৰক',
    features: 'বৈশিষ্ট্য',
  },
};

function getJsonLd(lang) {
  const featureList = CATEGORIES.map(c => c[lang]?.title || c.en.title);
  return [
    {
      '@context': 'https://schema.org',
      '@type': 'SoftwareApplication',
      name: 'Syrabit.ai',
      url: 'https://syrabit.ai',
      applicationCategory: 'EducationalApplication',
      operatingSystem: 'Any',
      inLanguage: lang === 'as' ? ['as', 'en'] : ['en', 'as'],
      description: lang === 'as'
        ? 'অসমৰ AHSEC, SEBA আৰু ডিগ্ৰী ছাত্ৰ-ছাত্ৰীৰ বাবে ১৫৯ টা বৈশিষ্ট্যৰে চালিত AI পৰীক্ষা প্ৰস্তুতি মঞ্চ।'
        : 'AI exam preparation platform with 159 features for AHSEC, SEBA and Degree students in Assam.',
      featureList,
      offers: [
        { '@type': 'Offer', name: 'Free Plan', price: '0', priceCurrency: 'INR' },
        { '@type': 'Offer', name: 'Starter Plan', price: '99', priceCurrency: 'INR' },
        { '@type': 'Offer', name: 'Pro Plan', price: '999', priceCurrency: 'INR' },
      ],
      aggregateRating: {
        '@type': 'AggregateRating',
        ratingValue: '4.8',
        reviewCount: '127',
      },
      provider: {
        '@type': 'Organization',
        name: 'Syrabit.ai',
        url: 'https://syrabit.ai',
        founder: {
          '@type': 'Person',
          name: 'Dipak Rai',
        },
      },
    },
    {
      '@context': 'https://schema.org',
      '@type': 'WebPage',
      name: lang === 'as' ? 'প্ৰযুক্তি আৰু বৈশিষ্ট্য — Syrabit.ai' : 'Technology & Features — Syrabit.ai',
      url: 'https://syrabit.ai/technology',
      inLanguage: lang === 'as' ? ['as', 'en'] : ['en', 'as'],
      isPartOf: {
        '@type': 'WebSite',
        name: 'Syrabit.ai',
        url: 'https://syrabit.ai',
      },
    },
  ];
}

function LangToggle({ contentLang, switchLang }) {
  return (
    <div className="flex items-center gap-1 shrink-0 rounded-xl p-0.5" style={{ background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.12)' }}>
      <button
        onClick={() => switchLang('en')}
        className={`h-9 px-3 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
          contentLang === 'en'
            ? 'text-white bg-violet-600 shadow-sm'
            : 'text-violet-600 hover:bg-violet-50'
        }`}
      >
        English
      </button>
      <button
        onClick={() => switchLang('as')}
        className={`h-9 px-3 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
          contentLang === 'as'
            ? 'text-white bg-violet-600 shadow-sm'
            : 'text-violet-600 hover:bg-violet-50'
        }`}
      >
        অসমীয়া
      </button>
    </div>
  );
}

function StatCard({ value, label }) {
  return (
    <div className="text-center p-5 rounded-2xl border border-border/40 bg-card/50">
      <p className="text-3xl font-bold text-violet-600 mb-1">{value}</p>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

function CategoryCard({ category, lang, t }) {
  const Icon = category.icon;
  const c = category[lang] || category.en;
  return (
    <div className="group rounded-2xl border border-border/40 bg-card/80 p-6 transition-all hover:shadow-md hover:border-border/60">
      <div className="flex items-start gap-4 mb-4">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: `${category.color}15` }}
        >
          <Icon size={20} style={{ color: category.color }} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-foreground text-base leading-snug">{c.title}</h3>
          <p className="text-xs text-muted-foreground mt-0.5">{category.featureCount} {t.features}</p>
        </div>
      </div>
      <p className="text-sm text-foreground/70 leading-relaxed mb-4">{c.description}</p>
      <ul className="space-y-1.5">
        {c.highlights.map((h, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-foreground/60">
            <ChevronRight size={14} className="mt-0.5 shrink-0 text-violet-500/60" />
            <span>{h}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function TechnologyPage() {
  const { contentLang, switchLang } = useContentLang();
  const t = _t[contentLang] || _t.en;
  const stats = STATS[contentLang] || STATS.en;
  const jsonLd = getJsonLd(contentLang);

  return (
    <PublicLayout>
      <PageMeta
        title={t.pageTitle}
        description={t.pageDescription}
        url="https://syrabit.ai/technology"
        keywords="Syrabit.ai technology, AI education features, AHSEC exam prep platform, Syrabit features, AI study assistant Assam, Syrabit প্ৰযুক্তি, অসমীয়া AI শিক্ষা মঞ্চ"
        jsonLd={jsonLd}
      />
      <div className="min-h-screen pt-8 pb-24 px-4">
        <div className="max-w-5xl mx-auto">

          <div className="flex items-start justify-between gap-4 mb-2">
            <h1 className="text-3xl font-semibold text-foreground">{t.heroHeading}</h1>
            <LangToggle contentLang={contentLang} switchLang={switchLang} />
          </div>
          <p className="text-muted-foreground text-sm mb-10 max-w-2xl">{t.heroSubtext}</p>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-14">
            {stats.map((s, i) => (
              <StatCard key={i} value={s.value} label={s.label} />
            ))}
          </div>

          <div className="mb-14">
            <h2 className="text-xl font-semibold text-foreground mb-1">{t.categoriesHeading}</h2>
            <p className="text-muted-foreground text-sm mb-6">{t.categoriesSubtext}</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {CATEGORIES.map((cat, i) => (
                <CategoryCard key={i} category={cat} lang={contentLang} t={t} />
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-14">
            <div className="rounded-2xl border border-border/40 bg-card/80 p-6">
              <h2 className="text-lg font-semibold text-foreground mb-3 flex items-center gap-2">
                <Globe size={18} className="text-violet-600" />
                {t.boardsTitle}
              </h2>
              <p className="text-sm text-muted-foreground mb-4">{t.boardsSubtext}</p>
              <div className="space-y-3">
                {t.boards.map((b, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-violet-500 shrink-0" />
                    <div>
                      <p className="font-medium text-foreground text-sm">{b.name}</p>
                      <p className="text-xs text-muted-foreground">{b.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-border/40 bg-card/80 p-6">
              <h2 className="text-lg font-semibold text-foreground mb-3 flex items-center gap-2">
                <FileText size={18} className="text-violet-600" />
                {t.contentTypesTitle}
              </h2>
              <ul className="space-y-2">
                {t.contentTypes.map((ct, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-foreground/70">
                    <Star size={12} className="mt-1 shrink-0 text-amber-500" />
                    <span>{ct}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="text-center mb-14">
            <p className="text-sm text-muted-foreground">
              {t.founderLabel}{' '}
              <span className="font-semibold text-foreground">Dipak Rai</span>
            </p>
          </div>

          <div className="rounded-2xl border border-violet-200/40 bg-gradient-to-br from-violet-50/60 to-white p-8 text-center">
            <h2 className="text-xl font-semibold text-foreground mb-2">{t.ctaHeading}</h2>
            <p className="text-muted-foreground text-sm mb-5">{t.ctaSubtext}</p>
            <Link
              to="/chat"
              className="inline-flex items-center gap-2 h-11 px-6 rounded-xl text-sm font-semibold text-white bg-violet-600 hover:bg-violet-700 transition-all active:scale-[0.98] shadow-sm"
            >
              <Zap size={16} />
              {t.ctaButton}
            </Link>
          </div>

        </div>
      </div>
    </PublicLayout>
  );
}
