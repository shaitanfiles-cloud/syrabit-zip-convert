import { PublicLayout } from '@/components/layout/PublicLayout';
import PageMeta from '@/components/seo/PageMeta';
import { Link } from 'react-router-dom';
import { useContentLang } from '@/context/LanguageContext';

const TECH_STACK = {
  en: [
    {
      category: 'Frontend',
      items: [
        { name: 'React 18', role: 'UI framework with concurrent rendering' },
        { name: 'Vite', role: 'Build tool and dev server with HMR' },
        { name: 'Tailwind CSS', role: 'Utility-first styling system' },
        { name: 'Framer Motion', role: 'Physics-based animations and transitions' },
        { name: 'React Router v6', role: 'Client-side routing with code splitting' },
        { name: 'TanStack React Query', role: 'Server-state management and caching' },
        { name: 'React Helmet Async', role: 'Dynamic SEO meta tag injection' },
        { name: 'Radix UI', role: 'Accessible headless UI primitives' },
      ],
    },
    {
      category: 'Backend',
      items: [
        { name: 'Python / FastAPI', role: 'Async API server with automatic OpenAPI docs' },
        { name: 'Gunicorn', role: 'WSGI/ASGI production server with worker management' },
        { name: 'Node.js', role: 'Edge proxy and build tooling runtime' },
        { name: 'Drizzle ORM', role: 'Type-safe database access layer' },
      ],
    },
    {
      category: 'AI & Machine Learning',
      items: [
        { name: 'Multi-LLM Pipeline', role: 'Hedged requests across Groq, Cerebras, OpenRouter, Fireworks, Sarvam, and Gemini' },
        { name: 'RAG Pipeline', role: 'Multi-stage retrieval-augmented generation with vector search' },
        { name: 'Gemini Embeddings', role: '768-dimensional embeddings via gemini-embedding-001' },
        { name: 'Gemini Vision OCR', role: 'PDF-to-HTML conversion for PYQ replicas' },
        { name: 'Sarvam AI', role: 'Native Assamese language model for bilingual support' },
        { name: 'Cloudflare AI Gateway', role: 'LLM traffic routing, caching, and fallback management' },
      ],
    },
    {
      category: 'Databases & Caching',
      items: [
        { name: 'MongoDB Atlas', role: 'Primary content store with compound indexes' },
        { name: 'PostgreSQL', role: 'User accounts, authentication, and transactional data' },
        { name: 'Redis', role: 'Session cache, rate limiting, and response caching' },
        { name: 'Cloudflare D1', role: 'Edge-replicated SQLite for read-heavy content catalog' },
        { name: 'Cloudflare Vectorize', role: 'Vector index for syllabus embeddings' },
      ],
    },
    {
      category: 'Infrastructure & DevOps',
      items: [
        { name: 'Cloudflare Workers', role: 'Edge proxy with CIDR-based bot verification and caching' },
        { name: 'Cloudflare Pages', role: 'Global CDN hosting for frontend assets' },
        { name: 'Railway', role: 'Backend container hosting with Docker deployment' },
        { name: 'Docker', role: 'Containerized backend with multi-stage builds' },
        { name: 'pnpm Monorepo', role: 'Workspace-based dependency management' },
        { name: 'esbuild', role: 'Fast JavaScript bundling for edge workers' },
      ],
    },
    {
      category: 'Payments & Communication',
      items: [
        { name: 'Razorpay', role: 'INR payment processing with webhook verification' },
        { name: 'Stripe', role: 'USD payment processing for international users' },
        { name: 'Resend', role: 'Transactional email delivery' },
        { name: 'Supabase Auth', role: 'JWT-based authentication with Google OAuth' },
      ],
    },
  ],
  as: [
    {
      category: 'ফ্ৰণ্টেণ্ড',
      items: [
        { name: 'React 18', role: 'একেলগে ৰেণ্ডাৰিঙৰ সৈতে UI ফ্ৰেমৱৰ্ক' },
        { name: 'Vite', role: 'HMR ৰ সৈতে বিল্ড সঁজুলি আৰু ডেভ চাৰ্ভাৰ' },
        { name: 'Tailwind CSS', role: 'ইউটিলিটি-ভিত্তিক ষ্টাইলিং ব্যৱস্থা' },
        { name: 'Framer Motion', role: 'পদাৰ্থবিজ্ঞান-ভিত্তিক এনিমেচন আৰু ট্ৰেন্সিচন' },
        { name: 'React Router v6', role: 'কোড স্প্লিটিঙৰ সৈতে ক্লায়েণ্ট-চাইড ৰাউটিং' },
        { name: 'TanStack React Query', role: 'চাৰ্ভাৰ-ষ্টেট মেনেজমেণ্ট আৰু কেচিং' },
        { name: 'React Helmet Async', role: 'গতিশীল SEO মেটা টেগ ইনজেকচন' },
        { name: 'Radix UI', role: 'সুলভ হেডলেচ UI প্ৰাইমিটিভ' },
      ],
    },
    {
      category: 'বেকেণ্ড',
      items: [
        { name: 'Python / FastAPI', role: 'স্বয়ংক্ৰিয় OpenAPI ডকুমেণ্টেচনৰ সৈতে এচিংক API চাৰ্ভাৰ' },
        { name: 'Gunicorn', role: 'ৱৰ্কাৰ ব্যৱস্থাপনাৰ সৈতে WSGI/ASGI প্ৰডাকচন চাৰ্ভাৰ' },
        { name: 'Node.js', role: 'এজ প্ৰক্সি আৰু বিল্ড টুলিং ৰানটাইম' },
        { name: 'Drizzle ORM', role: 'টাইপ-নিৰাপদ ডাটাবেছ একচেছ লেয়াৰ' },
      ],
    },
    {
      category: 'AI আৰু মেচিন লাৰ্নিং',
      items: [
        { name: 'মাল্টি-LLM পাইপলাইন', role: 'Groq, Cerebras, OpenRouter, Fireworks, Sarvam, আৰু Gemini ৰ মাজত হেজড ৰিকুৱেষ্ট' },
        { name: 'RAG পাইপলাইন', role: 'ভেক্টৰ চাৰ্চৰ সৈতে বহু-পৰ্যায়ৰ ৰিট্ৰিভেল-অগমেণ্টেড জেনাৰেচন' },
        { name: 'Gemini Embeddings', role: 'gemini-embedding-001 ৰ জৰিয়তে 768-মাত্ৰাৰ এম্বেডিংছ' },
        { name: 'Gemini Vision OCR', role: 'PYQ ৰেপ্লিকাৰ বাবে PDF-ৰ পৰা-HTML ৰূপান্তৰ' },
        { name: 'Sarvam AI', role: 'দ্বিভাষিক সমৰ্থনৰ বাবে থলুৱা অসমীয়া ভাষাৰ মডেল' },
        { name: 'Cloudflare AI Gateway', role: 'LLM ট্ৰেফিক ৰাউটিং, কেচিং, আৰু ফলবেক ব্যৱস্থাপনা' },
      ],
    },
    {
      category: 'ডাটাবেছ আৰু কেচিং',
      items: [
        { name: 'MongoDB Atlas', role: 'কম্পাউণ্ড ইনডেক্সৰ সৈতে প্ৰাথমিক কণ্টেণ্ট ষ্টৰ' },
        { name: 'PostgreSQL', role: 'ব্যৱহাৰকাৰী একাউণ্ট, প্ৰমাণীকৰণ, আৰু লেনদেনৰ তথ্য' },
        { name: 'Redis', role: 'চেচন কেচ, ৰেট লিমিটিং, আৰু ৰেচপন্স কেচিং' },
        { name: 'Cloudflare D1', role: 'ৰিড-হেভি কণ্টেণ্ট কেটালগৰ বাবে এজ-ৰেপ্লিকেটেড SQLite' },
        { name: 'Cloudflare Vectorize', role: 'পাঠ্যক্ৰম এম্বেডিংছৰ বাবে ভেক্টৰ ইনডেক্স' },
      ],
    },
    {
      category: 'আন্তঃগাঁথনি আৰু DevOps',
      items: [
        { name: 'Cloudflare Workers', role: 'CIDR-ভিত্তিক বট ভেৰিফিকেচন আৰু কেচিঙৰ সৈতে এজ প্ৰক্সি' },
        { name: 'Cloudflare Pages', role: 'ফ্ৰণ্টেণ্ড এচেটৰ বাবে গ্লবেল CDN হষ্টিং' },
        { name: 'Railway', role: 'Docker ডিপ্লয়মেণ্টৰ সৈতে বেকেণ্ড কণ্টেইনাৰ হষ্টিং' },
        { name: 'Docker', role: 'মাল্টি-ষ্টেজ বিল্ডৰ সৈতে কণ্টেইনাৰাইজড বেকেণ্ড' },
        { name: 'pnpm Monorepo', role: 'ৱৰ্কস্পেচ-ভিত্তিক ডিপেণ্ডেঞ্চি ব্যৱস্থাপনা' },
        { name: 'esbuild', role: 'এজ ৱৰ্কাৰৰ বাবে দ্ৰুত JavaScript বাণ্ডলিং' },
      ],
    },
    {
      category: 'পেমেণ্ট আৰু যোগাযোগ',
      items: [
        { name: 'Razorpay', role: 'ৱেবহুক ভেৰিফিকেচনৰ সৈতে INR পেমেণ্ট প্ৰচেছিং' },
        { name: 'Stripe', role: 'আন্তঃৰাষ্ট্ৰীয় ব্যৱহাৰকাৰীৰ বাবে USD পেমেণ্ট প্ৰচেছিং' },
        { name: 'Resend', role: 'ট্ৰেনজেকচনেল ইমেইল ডেলিভাৰী' },
        { name: 'Supabase Auth', role: 'Google OAuth ৰ সৈতে JWT-ভিত্তিক প্ৰমাণীকৰণ' },
      ],
    },
  ],
};

const SCALE_METRICS = {
  en: [
    { label: 'API Endpoints', value: '120+' },
    { label: 'Auto-Generated SEO Pages', value: '15,000+' },
    { label: 'Supported Subjects', value: '55+' },
    { label: 'Chapters Indexed', value: '2,500+' },
    { label: 'Backend Modules', value: '40+' },
    { label: 'Frontend Components', value: '80+' },
    { label: 'LLM Providers Integrated', value: '6' },
    { label: 'Database Systems', value: '5' },
  ],
  as: [
    { label: 'API এণ্ডপইণ্ট', value: '120+' },
    { label: 'স্বয়ংক্ৰিয় SEO পৃষ্ঠা', value: '15,000+' },
    { label: 'সমৰ্থিত বিষয়', value: '55+' },
    { label: 'সূচীভুক্ত অধ্যায়', value: '2,500+' },
    { label: 'বেকেণ্ড মডিউল', value: '40+' },
    { label: 'ফ্ৰণ্টেণ্ড কম্পনেণ্ট', value: '80+' },
    { label: 'LLM প্ৰদানকাৰী', value: '6' },
    { label: 'ডাটাবেছ ব্যৱস্থা', value: '5' },
  ],
};

const _t = {
  en: {
    pageTitle: 'Technology Stack & Architecture',
    pageDescription: "Explore the technology behind Syrabit.ai \u2014 a production-grade AI educational platform built with React, FastAPI, multi-LLM RAG pipeline, MongoDB Atlas, Cloudflare Workers, and programmatic SEO engine generating 15,000+ pages for AHSEC, SEBA, and Degree students.",
    pageSubtitle: 'The engineering behind Syrabit.ai \u2014 a production-grade AI educational platform',
    platformOverviewTitle: 'Platform Overview',
    platformOverviewP1: 'Syrabit.ai is a full-stack AI-powered educational platform purpose-built for students in Assam preparing for AHSEC (Class 11\u201312), SEBA (Class 9\u201310), and Degree (B.Com, B.A, B.Sc under Gauhati University, Dibrugarh University, and Cotton University) examinations. The platform combines a React single-page application with a Python/FastAPI backend, a multi-provider LLM pipeline, and a Cloudflare edge network \u2014 all orchestrated as a pnpm monorepo with Docker containerization for production deployment.',
    platformOverviewP2: 'The system serves bilingual content in English and Assamese, processes natural language queries through a retrieval-augmented generation (RAG) pipeline, and auto-generates thousands of SEO-optimized pages covering every chapter in the supported curricula.',
    techStackTitle: 'Full Technology Stack',
    ragTitle: 'AI & RAG Pipeline',
    ragIntro: 'The core AI system uses a multi-stage retrieval-augmented generation pipeline specifically designed for syllabus-grounded answers. When a student asks a question, the system:',
    ragSteps: [
      'Classifies the query intent and extracts the academic context (board, class, subject, chapter)',
      'Performs vector similarity search using 768-dimensional Gemini embeddings stored in Cloudflare Vectorize',
      'Retrieves relevant chapter content from MongoDB Atlas with compound index optimization',
      'Routes the augmented prompt to the fastest available LLM using hedged requests \u2014 racing multiple providers (Groq, Cerebras, OpenRouter, Fireworks) simultaneously for sub-1-second time-to-first-token',
      'For Assamese queries, races Sarvam AI (native Assamese LLM) against Gemini 2.5 Flash with three API key rotation',
    ],
    ragConclusion: 'The pipeline achieves under 0.8 seconds TTFT for English queries and under 3 seconds for Assamese queries. Every response includes source citations linking back to the exact chapter and topic.',
    seoTitle: 'Programmatic SEO Engine',
    seoIntro: 'The backend includes a custom programmatic SEO engine (Generative Engine Optimization) that automatically generates thousands of search-optimized pages. The engine produces:',
    seoItems: [
      'Chapter-level study notes pages with structured JSON-LD data',
      'MCQ and important question pages per chapter',
      'Previous year question (PYQ) HTML replicas from PDF scans via Gemini Vision OCR',
      'Definition and example pages with FAQ schema for Google rich results',
      'Dynamic sitemaps (9 sub-sitemaps covering pages, subjects, notes, MCQs, PYQs, examples, definitions, chapters, and learn articles)',
      'RSS/Atom feeds, llms.txt manifests, and AI plugin discovery endpoints',
      'Keyword expansion engine generating 80+ keyword variants per topic for maximum search coverage',
      'Automatic IndexNow push to search engines when new content is published',
    ],
    seoConclusion: "Each generated page includes Schema.org structured data (Article, LearningResource, FAQPage, SpeakableSpecification), OpenGraph tags, geo-targeting meta tags for Assam (IN-AS), and board-specific keyword variants for AHSEC, SEBA, and Degree search queries.",
    adminTitle: 'Admin Tools & Content Pipeline',
    adminIntro: 'A comprehensive admin dashboard provides full control over content generation, quality management, and platform analytics:',
    adminItems: [
      'Batch content generation pipeline with parallel processing (notes, MCQs, flashcards via asyncio.gather)',
      'Content quality scoring with auto-detection of thin chapters and auto-heal with version history',
      'SEO management with SERP preview, coverage analytics, and keyword tracking',
      'Bot traffic analytics with daily hit charts, crawl coverage, and per-bot metrics',
      'LLM provider health monitoring with latency tracking and provider rotation',
      'RAG telemetry dashboard with similarity score distributions',
      'IndexNow push status monitoring with source breakdown',
      'User analytics, credit usage, and payment tracking',
    ],
    infraTitle: 'Infrastructure & Edge Network',
    infraIntro: 'The platform uses a hybrid deployment architecture optimized for performance and cost:',
    infraItems: [
      { label: 'Edge Proxy', text: 'Cloudflare Worker at api.syrabit.ai handles request routing, bot verification (CIDR-based IP range checking for Google, Bing, OpenAI, Yandex, Apple), rate limiting, and response caching' },
      { label: 'Frontend', text: 'Cloudflare Pages at syrabit.ai with global CDN distribution, PWA service worker (multi-cache strategy), and offline access' },
      { label: 'Backend', text: 'Railway-hosted Docker container running FastAPI with Gunicorn worker management' },
      { label: 'Edge Data', text: 'Cloudflare D1 (SQLite replica) for read-heavy content catalog queries at the edge' },
    ],
    scaleTitle: 'Build Complexity & Scale',
    scaleConclusion: 'The platform integrates 6 LLM providers, 5 database systems, 2 payment gateways, and a complete Cloudflare edge network \u2014 all within a pnpm monorepo containing the frontend application, backend API, edge proxy worker, and shared libraries. The system handles bilingual content delivery, real-time AI chat streaming, automated content generation, and programmatic SEO at scale.',
    projectTitle: 'Project Scale & Development',
    projectP1: 'Syrabit.ai was developed as a grant-funded initiative (funded under the Assam Startup ecosystem with \u20B97.5 lakh seed funding) to address the lack of quality, syllabus-aligned digital education resources for students in Assam. The platform covers three major examination boards \u2014 AHSEC, SEBA, and university-level Degree programmes \u2014 across 55+ subjects spanning Science, Commerce, and Arts streams.',
    projectP2: 'Built by a solo full-stack developer over 12+ months of continuous development, the project spans frontend engineering, backend API design, AI/ML pipeline architecture, infrastructure and DevOps, content generation automation, SEO engine development, payment integration, and admin tooling. The architecture is designed for horizontal scalability with edge caching, database replication, and provider failover at every layer.',
    projectCta: 'Learn more about our mission and approach on the',
    aboutLink: 'About page',
  },
  as: {
    pageTitle: 'প্ৰযুক্তি স্তৰ আৰু আৰ্কিটেকচাৰ',
    pageDescription: "Syrabit.ai ৰ আঁৰৰ প্ৰযুক্তি অন্বেষণ কৰক \u2014 React, FastAPI, মাল্টি-LLM RAG পাইপলাইন, MongoDB Atlas, Cloudflare Workers, আৰু AHSEC, SEBA, আৰু ডিগ্ৰী ছাত্ৰ-ছাত্ৰীৰ বাবে 15,000+ পৃষ্ঠা সৃষ্টি কৰা প্ৰ'গ্ৰামেটিক SEO ইঞ্জিনৰ সৈতে নিৰ্মিত এখন প্ৰডাকচন-গ্ৰেড AI শিক্ষামূলক মঞ্চ।",
    pageSubtitle: 'Syrabit.ai ৰ আঁৰৰ ইঞ্জিনিয়াৰিং \u2014 এখন প্ৰডাকচন-গ্ৰেড AI শিক্ষামূলক মঞ্চ',
    platformOverviewTitle: 'মঞ্চৰ আভাস',
    platformOverviewP1: 'Syrabit.ai হৈছে অসমৰ AHSEC (শ্ৰেণী 11\u201312), SEBA (শ্ৰেণী 9\u201310), আৰু ডিগ্ৰী (গুৱাহাটী বিশ্ববিদ্যালয়, ডিব্ৰুগড় বিশ্ববিদ্যালয়, আৰু কটন বিশ্ববিদ্যালয়ৰ অধীনত B.Com, B.A, B.Sc) পৰীক্ষাৰ বাবে প্ৰস্তুতি লোৱা ছাত্ৰ-ছাত্ৰীৰ বাবে বিশেষভাৱে নিৰ্মিত এখন সম্পূৰ্ণ AI-চালিত শিক্ষামূলক মঞ্চ। মঞ্চখনে React চিংগল-পেজ এপ্লিকেচন, Python/FastAPI বেকেণ্ড, মাল্টি-প্ৰভাইডাৰ LLM পাইপলাইন, আৰু Cloudflare এজ নেটৱৰ্ক সংযুক্ত কৰে \u2014 সকলোবোৰ pnpm মনৰেপ হিচাপে আৰু প্ৰডাকচন ডিপ্লয়মেণ্টৰ বাবে Docker কণ্টেইনাৰাইজেচনৰ সৈতে সংগঠিত।',
    platformOverviewP2: 'ব্যৱস্থাটোৱে ইংৰাজী আৰু অসমীয়াত দ্বিভাষিক বিষয়বস্তু প্ৰদান কৰে, প্ৰাকৃতিক ভাষাৰ প্ৰশ্নসমূহ ৰিট্ৰিভেল-অগমেণ্টেড জেনাৰেচন (RAG) পাইপলাইনৰ জৰিয়তে প্ৰক্ৰিয়াকৰণ কৰে, আৰু সমৰ্থিত পাঠ্যক্ৰমৰ প্ৰতিটো অধ্যায় সামৰি হাজাৰ হাজাৰ SEO-অনুকূলিত পৃষ্ঠা স্বয়ংক্ৰিয়ভাৱে সৃষ্টি কৰে।',
    techStackTitle: 'সম্পূৰ্ণ প্ৰযুক্তি স্তৰ',
    ragTitle: 'AI আৰু RAG পাইপলাইন',
    ragIntro: 'মূল AI ব্যৱস্থাটোৱে পাঠ্যক্ৰম-ভিত্তিক উত্তৰৰ বাবে বিশেষভাৱে ডিজাইন কৰা এটা বহু-পৰ্যায়ৰ ৰিট্ৰিভেল-অগমেণ্টেড জেনাৰেচন পাইপলাইন ব্যৱহাৰ কৰে। এজন ছাত্ৰ-ছাত্ৰীয়ে প্ৰশ্ন কৰিলে ব্যৱস্থাটোৱে:',
    ragSteps: [
      'প্ৰশ্নৰ উদ্দেশ্য শ্ৰেণীবিভাজন কৰে আৰু শৈক্ষিক প্ৰসংগ (বৰ্ড, শ্ৰেণী, বিষয়, অধ্যায়) আহৰণ কৰে',
      'Cloudflare Vectorize ত সংৰক্ষিত 768-মাত্ৰাৰ Gemini এম্বেডিংছ ব্যৱহাৰ কৰি ভেক্টৰ সাদৃশ্য সন্ধান কৰে',
      'কম্পাউণ্ড ইনডেক্স অনুকূলনৰ সৈতে MongoDB Atlas ৰ পৰা প্ৰাসংগিক অধ্যায় বিষয়বস্তু পুনৰুদ্ধাৰ কৰে',
      'হেজড ৰিকুৱেষ্ট ব্যৱহাৰ কৰি অগমেণ্টেড প্ৰম্পটটো দ্ৰুততম উপলব্ধ LLM লৈ ৰাউট কৰে \u2014 একেলগে একাধিক প্ৰদানকাৰী (Groq, Cerebras, OpenRouter, Fireworks) ৰেচ কৰি 1-ছেকেণ্ডতকৈ কম সময়ত প্ৰথম টোকেন পাবলৈ',
      'অসমীয়া প্ৰশ্নৰ বাবে, তিনিটা API কি ৰটেচনৰ সৈতে Sarvam AI (থলুৱা অসমীয়া LLM) আৰু Gemini 2.5 Flash ৰ মাজত ৰেচ কৰে',
    ],
    ragConclusion: 'পাইপলাইনে ইংৰাজী প্ৰশ্নৰ বাবে 0.8 ছেকেণ্ডতকৈ কম আৰু অসমীয়া প্ৰশ্নৰ বাবে 3 ছেকেণ্ডতকৈ কম TTFT লাভ কৰে। প্ৰতিটো উত্তৰত সঠিক অধ্যায় আৰু বিষয়লৈ সংযুক্ত উৎস উদ্ধৃতি অন্তৰ্ভুক্ত থাকে।',
    seoTitle: 'প্ৰগ্ৰামেটিক SEO ইঞ্জিন',
    seoIntro: 'বেকেণ্ডত এটা কাষ্টম প্ৰগ্ৰামেটিক SEO ইঞ্জিন (জেনাৰেটিভ ইঞ্জিন অপ্টিমাইজেচন) অন্তৰ্ভুক্ত আছে যিয়ে স্বয়ংক্ৰিয়ভাৱে হাজাৰ হাজাৰ সন্ধান-অনুকূলিত পৃষ্ঠা সৃষ্টি কৰে। ইঞ্জিনে সৃষ্টি কৰে:',
    seoItems: [
      'গাঁথনিগত JSON-LD তথ্যৰ সৈতে অধ্যায়-স্তৰৰ অধ্যয়ন টোকা পৃষ্ঠা',
      'প্ৰতি অধ্যায়ত MCQ আৰু গুৰুত্বপূৰ্ণ প্ৰশ্নৰ পৃষ্ঠা',
      'Gemini Vision OCR ৰ জৰিয়তে PDF স্কেনৰ পৰা আগৰ বছৰৰ প্ৰশ্ন (PYQ) HTML ৰেপ্লিকা',
      'Google ৰিচ ৰিজাল্টৰ বাবে FAQ স্কিমাৰ সৈতে সংজ্ঞা আৰু উদাহৰণ পৃষ্ঠা',
      'ডাইনামিক চাইটমেপ (পৃষ্ঠা, বিষয়, টোকা, MCQ, PYQ, উদাহৰণ, সংজ্ঞা, অধ্যায়, আৰু শিক্ষা প্ৰবন্ধ সামৰি 9 খন উপ-চাইটমেপ)',
      'RSS/Atom ফিড, llms.txt মেনিফেষ্ট, আৰু AI প্লাগিন আৱিষ্কাৰ এণ্ডপইণ্ট',
      'সৰ্বাধিক সন্ধান কভাৰেজৰ বাবে প্ৰতি বিষয়ত 80+ কীৱৰ্ড ভেৰিয়েণ্ট সৃষ্টি কৰা কীৱৰ্ড সম্প্ৰসাৰণ ইঞ্জিন',
      'নতুন বিষয়বস্তু প্ৰকাশ হলে সন্ধান ইঞ্জিনলৈ স্বয়ংক্ৰিয় IndexNow পুছ',
    ],
    seoConclusion: "প্ৰতিটো সৃষ্টি কৰা পৃষ্ঠাত Schema.org গাঁথনিগত তথ্য (Article, LearningResource, FAQPage, SpeakableSpecification), OpenGraph টেগ, অসম (IN-AS) ৰ বাবে জিঅ-টাৰ্গেটিং মেটা টেগ, আৰু AHSEC, SEBA, আৰু ডিগ্ৰী সন্ধান প্ৰশ্নৰ বাবে বৰ্ড-নিৰ্দিষ্ট কীৱৰ্ড ভেৰিয়েণ্ট অন্তৰ্ভুক্ত থাকে।",
    adminTitle: 'প্ৰশাসন সঁজুলি আৰু বিষয়বস্তু পাইপলাইন',
    adminIntro: 'এটা বিস্তৃত প্ৰশাসন ডেচবৰ্ডে বিষয়বস্তু সৃষ্টি, গুণগত মান ব্যৱস্থাপনা, আৰু মঞ্চ বিশ্লেষণৰ ওপৰত সম্পূৰ্ণ নিয়ন্ত্ৰণ প্ৰদান কৰে:',
    adminItems: [
      'সমান্তৰাল প্ৰক্ৰিয়াকৰণৰ সৈতে বেচ বিষয়বস্তু সৃষ্টি পাইপলাইন (asyncio.gather ৰ জৰিয়তে টোকা, MCQ, ফ্লেচকাৰ্ড)',
      'পাতল অধ্যায়ৰ স্বয়ংক্ৰিয় চিনাক্তকৰণ আৰু সংস্কৰণ ইতিহাসৰ সৈতে স্বয়ংক্ৰিয় মেৰামতিৰ সৈতে বিষয়বস্তু গুণগত মান স্কৰিং',
      'SERP পূৰ্বদৰ্শন, কভাৰেজ বিশ্লেষণ, আৰু কীৱৰ্ড ট্ৰেকিঙৰ সৈতে SEO ব্যৱস্থাপনা',
      'দৈনিক হিট চাৰ্ট, ক্ৰল কভাৰেজ, আৰু প্ৰতি-বট মেট্ৰিক্সৰ সৈতে বট ট্ৰেফিক বিশ্লেষণ',
      'লেটেঞ্চি ট্ৰেকিং আৰু প্ৰদানকাৰী ৰটেচনৰ সৈতে LLM প্ৰদানকাৰী স্বাস্থ্য নিৰীক্ষণ',
      'সাদৃশ্য স্কৰ বিতৰণৰ সৈতে RAG টেলিমেট্ৰি ডেচবৰ্ড',
      'উৎস বিশ্লেষণৰ সৈতে IndexNow পুছ স্থিতি নিৰীক্ষণ',
      'ব্যৱহাৰকাৰী বিশ্লেষণ, ক্ৰেডিট ব্যৱহাৰ, আৰু পেমেণ্ট ট্ৰেকিং',
    ],
    infraTitle: 'আন্তঃগাঁথনি আৰু এজ নেটৱৰ্ক',
    infraIntro: 'মঞ্চখনে কাৰ্যক্ষমতা আৰু ব্যয়ৰ বাবে অনুকূলিত এটা হাইব্ৰিড ডিপ্লয়মেণ্ট আৰ্কিটেকচাৰ ব্যৱহাৰ কৰে:',
    infraItems: [
      { label: 'এজ প্ৰক্সি', text: 'api.syrabit.ai ত Cloudflare Worker য়ে ৰিকুৱেষ্ট ৰাউটিং, বট ভেৰিফিকেচন (Google, Bing, OpenAI, Yandex, Apple ৰ বাবে CIDR-ভিত্তিক IP ৰেঞ্জ পৰীক্ষা), ৰেট লিমিটিং, আৰু ৰেচপন্স কেচিং পৰিচালনা কৰে' },
      { label: 'ফ্ৰণ্টেণ্ড', text: 'গ্লবেল CDN বিতৰণ, PWA চাৰ্ভিচ ৱৰ্কাৰ (মাল্টি-কেচ ষ্ট্ৰেটেজি), আৰু অফলাইন একচেছৰ সৈতে syrabit.ai ত Cloudflare Pages' },
      { label: 'বেকেণ্ড', text: 'Gunicorn ৱৰ্কাৰ ব্যৱস্থাপনাৰ সৈতে FastAPI চলোৱা Railway-হষ্টেড Docker কণ্টেইনাৰ' },
      { label: 'এজ ডাটা', text: 'এজত ৰিড-হেভি কণ্টেণ্ট কেটালগ ক্যুৱেৰিৰ বাবে Cloudflare D1 (SQLite ৰেপ্লিকা)' },
    ],
    scaleTitle: 'নিৰ্মাণ জটিলতা আৰু পৰিসৰ',
    scaleConclusion: 'মঞ্চখনে 6 টা LLM প্ৰদানকাৰী, 5 টা ডাটাবেছ ব্যৱস্থা, 2 টা পেমেণ্ট গেটৱে, আৰু এটা সম্পূৰ্ণ Cloudflare এজ নেটৱৰ্ক সংযুক্ত কৰে \u2014 সকলোবোৰ ফ্ৰণ্টেণ্ড এপ্লিকেচন, বেকেণ্ড API, এজ প্ৰক্সি ৱৰ্কাৰ, আৰু শ্বেয়াৰড লাইব্ৰেৰী থকা এটা pnpm মনৰেপৰ ভিতৰত। ব্যৱস্থাটোৱে দ্বিভাষিক বিষয়বস্তু বিতৰণ, ৰিয়েল-টাইম AI চেট ষ্ট্ৰিমিং, স্বয়ংক্ৰিয় বিষয়বস্তু সৃষ্টি, আৰু বৃহৎ পৰিসৰত প্ৰগ্ৰামেটিক SEO পৰিচালনা কৰে।',
    projectTitle: 'প্ৰকল্পৰ পৰিসৰ আৰু উন্নয়ন',
    projectP1: 'Syrabit.ai অসমৰ ছাত্ৰ-ছাত্ৰীৰ বাবে গুণগত মানসম্পন্ন, পাঠ্যক্ৰম-সংযুক্ত ডিজিটেল শিক্ষা সম্পদৰ অভাৱ পূৰণ কৰিবলৈ এটা অনুদান-পুঁজিৰে গঢ়া উদ্যোগ হিচাপে বিকশিত কৰা হৈছিল (অসম ষ্টাৰ্টআপ ইকচিষ্টেমৰ অধীনত \u20B97.5 লাখ বীজ পুঁজিৰে পুঁজিভুক্ত)। মঞ্চখনে তিনিটা প্ৰধান পৰীক্ষা বৰ্ড \u2014 AHSEC, SEBA, আৰু বিশ্ববিদ্যালয়-স্তৰৰ ডিগ্ৰী কাৰ্যক্ৰম \u2014 বিজ্ঞান, বাণিজ্য, আৰু কলা শাখাৰ 55+ বিষয় সামৰি লয়।',
    projectP2: 'এজন একক ফুল-ষ্টেক ডেভেলপাৰে 12+ মাহৰ নিৰন্তৰ বিকাশৰ জৰিয়তে নিৰ্মাণ কৰা এই প্ৰকল্পই ফ্ৰণ্টেণ্ড ইঞ্জিনিয়াৰিং, বেকেণ্ড API ডিজাইন, AI/ML পাইপলাইন আৰ্কিটেকচাৰ, আন্তঃগাঁথনি আৰু DevOps, বিষয়বস্তু সৃষ্টি স্বয়ংক্ৰিয়কৰণ, SEO ইঞ্জিন বিকাশ, পেমেণ্ট সংহতি, আৰু প্ৰশাসন সঁজুলিকৰণ সামৰি লয়। আৰ্কিটেকচাৰটো প্ৰতিটো স্তৰত এজ কেচিং, ডাটাবেছ ৰেপ্লিকেচন, আৰু প্ৰদানকাৰী ফেইলঅভাৰৰ সৈতে অনুভূমিক স্কেলেবিলিটিৰ বাবে ডিজাইন কৰা হৈছে।',
    projectCta: 'আমাৰ লক্ষ্য আৰু পদ্ধতিৰ বিষয়ে অধিক জানক',
    aboutLink: 'সম্পৰ্কে পৃষ্ঠা',
  },
};

function getJsonLd(lang) {
  return {
    '@context': 'https://schema.org',
    '@type': 'WebApplication',
    name: 'Syrabit.ai',
    url: 'https://syrabit.ai',
    inLanguage: lang === 'as' ? ['as', 'en'] : ['en', 'as'],
    applicationCategory: 'EducationalApplication',
    applicationSubCategory: 'AI-Powered Study Platform',
    operatingSystem: 'Web Browser (Chrome, Firefox, Safari, Edge)',
    browserRequirements: 'Requires JavaScript. Works on all modern browsers.',
    softwareVersion: '2.0',
    datePublished: '2024-06-01',
    dateModified: '2026-04-16',
    description: lang === 'as'
      ? 'অসমৰ AHSEC, SEBA, আৰু ডিগ্ৰী ছাত্ৰ-ছাত্ৰীৰ বাবে AI-চালিত শিক্ষামূলক ব্ৰাউজাৰ। 6 টা প্ৰদানকাৰীৰ মাজত মাল্টি-LLM RAG পাইপলাইন, 15,000+ পৃষ্ঠা সৃষ্টি কৰা প্ৰগ্ৰামেটিক SEO ইঞ্জিন, দ্বিভাষিক সমৰ্থন (ইংৰাজী/অসমীয়া), আৰু উৎস উদ্ধৃতিৰ সৈতে ৰিয়েল-টাইম AI টিউটৰিং বৈশিষ্ট্যযুক্ত।'
      : 'AI-powered educational browser for AHSEC, SEBA, and Degree students in Assam. Features a multi-LLM RAG pipeline, programmatic SEO engine generating 15,000+ pages, bilingual support (English/Assamese), and real-time AI tutoring with source citations.',
    featureList: [
      'Multi-LLM RAG pipeline with hedged requests across 6 providers',
      'Programmatic SEO engine with 15,000+ auto-generated pages',
      'Bilingual AI tutoring (English and Assamese)',
      'Real-time chat with sub-1s TTFT via hedged LLM requests',
      'Vector search with 768-dimensional Gemini embeddings',
      'Cloudflare edge proxy with CIDR-based bot verification',
      'Progressive Web App with offline access',
      'Credit-based monetization with Razorpay and Stripe',
      'Admin dashboard with content pipeline, SEO management, and analytics',
      'PYQ PDF-to-HTML conversion via Gemini Vision OCR',
    ],
    screenshot: 'https://syrabit.ai/opengraph.jpg',
    offers: {
      '@type': 'AggregateOffer',
      priceCurrency: 'INR',
      lowPrice: '0',
      highPrice: '999',
      offerCount: '3',
      offers: [
        {
          '@type': 'Offer',
          name: 'Free Plan',
          price: '0',
          priceCurrency: 'INR',
          description: 'Limited daily credits for basic usage',
        },
        {
          '@type': 'Offer',
          name: 'Starter Plan',
          price: '99',
          priceCurrency: 'INR',
          description: '500 credits per day',
        },
        {
          '@type': 'Offer',
          name: 'Pro Plan',
          price: '999',
          priceCurrency: 'INR',
          description: '4,000 credits per day with priority support',
        },
      ],
    },
    creator: {
      '@type': 'Organization',
      name: 'Syrabit',
      url: 'https://syrabit.ai',
      foundingDate: '2024',
      areaServed: {
        '@type': 'State',
        name: 'Assam',
        containedInPlace: { '@type': 'Country', name: 'India' },
      },
    },
    audience: {
      '@type': 'EducationalAudience',
      educationalRole: 'student',
      audienceType:
        'AHSEC Class 11-12, SEBA Class 9-10, Degree (B.Com, B.A, B.Sc) students in Assam',
    },
  };
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

export default function TechnologyPage() {
  const { contentLang, switchLang } = useContentLang();
  const t = _t[contentLang] || _t.en;
  const techStack = TECH_STACK[contentLang] || TECH_STACK.en;
  const scaleMetrics = SCALE_METRICS[contentLang] || SCALE_METRICS.en;
  const jsonLd = getJsonLd(contentLang);

  return (
    <PublicLayout>
      <PageMeta
        title={t.pageTitle}
        description={t.pageDescription}
        url="https://syrabit.ai/technology"
        keywords="Syrabit technology stack, AI education platform architecture, React FastAPI MongoDB, RAG pipeline, programmatic SEO, Cloudflare Workers, EdTech India, AHSEC SEBA Degree, Syrabit প্ৰযুক্তি, অসমীয়া AI শিক্ষা মঞ্চ"
        jsonLd={jsonLd}
      />
      <div className="min-h-screen pt-8 pb-24 px-4">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-start justify-between gap-4 mb-2">
            <h1 className="text-3xl font-semibold text-foreground">
              {t.pageTitle}
            </h1>
            <LangToggle contentLang={contentLang} switchLang={switchLang} />
          </div>
          <p className="text-muted-foreground text-sm mb-10">
            {t.pageSubtitle}
          </p>

          <div className="space-y-12 text-foreground/70 leading-relaxed">

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                {t.platformOverviewTitle}
              </h2>
              <p className="mb-4">{t.platformOverviewP1}</p>
              <p>{t.platformOverviewP2}</p>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-4">
                {t.techStackTitle}
              </h2>
              <div className="space-y-8">
                {techStack.map((group) => (
                  <div key={group.category}>
                    <h3 className="text-foreground font-medium mb-3">{group.category}</h3>
                    <div className="grid sm:grid-cols-2 gap-x-6 gap-y-2">
                      {group.items.map((item) => (
                        <div key={item.name} className="flex items-start gap-2 py-1.5">
                          <span className="text-violet-600 mt-1.5 w-1.5 h-1.5 rounded-full bg-violet-600 flex-shrink-0" />
                          <div>
                            <span className="text-foreground font-medium text-sm">
                              {item.name}
                            </span>
                            <span className="text-muted-foreground text-sm"> — {item.role}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                {t.ragTitle}
              </h2>
              <p className="mb-3">{t.ragIntro}</p>
              <ol className="list-decimal list-inside space-y-2 mb-4">
                {t.ragSteps.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
              <p>{t.ragConclusion}</p>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                {t.seoTitle}
              </h2>
              <p className="mb-3">{t.seoIntro}</p>
              <ul className="list-disc list-inside space-y-1.5 mb-4">
                {t.seoItems.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
              <p>{t.seoConclusion}</p>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                {t.adminTitle}
              </h2>
              <p className="mb-3">{t.adminIntro}</p>
              <ul className="list-disc list-inside space-y-1.5">
                {t.adminItems.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                {t.infraTitle}
              </h2>
              <p className="mb-3">{t.infraIntro}</p>
              <ul className="list-disc list-inside space-y-1.5">
                {t.infraItems.map((item, i) => (
                  <li key={i}>
                    <span className="text-foreground font-medium">{item.label}</span> — {item.text}
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-4">
                {t.scaleTitle}
              </h2>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
                {scaleMetrics.map((metric) => (
                  <div
                    key={metric.label}
                    className="rounded-xl p-4 text-center"
                    style={{
                      background: 'hsl(var(--muted) / 0.4)',
                      border: '1px solid hsl(var(--border) / 0.5)',
                    }}
                  >
                    <div className="text-2xl font-bold text-violet-600">{metric.value}</div>
                    <div className="text-xs text-muted-foreground mt-1">{metric.label}</div>
                  </div>
                ))}
              </div>
              <p>{t.scaleConclusion}</p>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                {t.projectTitle}
              </h2>
              <p className="mb-3">{t.projectP1}</p>
              <p className="mb-3">{t.projectP2}</p>
              <p>
                {t.projectCta}{' '}
                <Link to="/about" className="text-violet-600 hover:underline">
                  {t.aboutLink}
                </Link>
                .
              </p>
            </section>

          </div>
        </div>
      </div>
    </PublicLayout>
  );
}
