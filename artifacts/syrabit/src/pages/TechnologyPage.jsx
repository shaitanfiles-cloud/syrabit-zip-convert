import { PublicLayout } from '@/components/layout/PublicLayout';
import PageMeta from '@/components/seo/PageMeta';
import { Link } from 'react-router-dom';

const TECH_STACK = [
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
];

const SCALE_METRICS = [
  { label: 'API Endpoints', value: '120+' },
  { label: 'Auto-Generated SEO Pages', value: '15,000+' },
  { label: 'Supported Subjects', value: '55+' },
  { label: 'Chapters Indexed', value: '2,500+' },
  { label: 'Backend Modules', value: '40+' },
  { label: 'Frontend Components', value: '80+' },
  { label: 'LLM Providers Integrated', value: '6' },
  { label: 'Database Systems', value: '5' },
];

const jsonLd = {
  '@context': 'https://schema.org',
  '@type': 'WebApplication',
  name: 'Syrabit.ai',
  url: 'https://syrabit.ai',
  applicationCategory: 'EducationalApplication',
  applicationSubCategory: 'AI-Powered Study Platform',
  operatingSystem: 'Web Browser (Chrome, Firefox, Safari, Edge)',
  browserRequirements: 'Requires JavaScript. Works on all modern browsers.',
  softwareVersion: '2.0',
  datePublished: '2024-06-01',
  dateModified: '2026-04-15',
  description:
    'AI-powered educational browser for AHSEC, SEBA, and Degree students in Assam. Features a multi-LLM RAG pipeline, programmatic SEO engine generating 15,000+ pages, bilingual support (English/Assamese), and real-time AI tutoring with source citations.',
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

export default function TechnologyPage() {
  return (
    <PublicLayout>
      <PageMeta
        title="Technology Stack & Architecture"
        description="Explore the technology behind Syrabit.ai — a production-grade AI educational platform built with React, FastAPI, multi-LLM RAG pipeline, MongoDB Atlas, Cloudflare Workers, and programmatic SEO engine generating 15,000+ pages for AHSEC, SEBA, and Degree students."
        url="https://syrabit.ai/technology"
        keywords="Syrabit technology stack, AI education platform architecture, React FastAPI MongoDB, RAG pipeline, programmatic SEO, Cloudflare Workers, EdTech India, AHSEC SEBA Degree"
        jsonLd={jsonLd}
      />
      <div className="min-h-screen pt-8 pb-24 px-4">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-3xl font-semibold text-foreground mb-2">
            Technology Stack &amp; Architecture
          </h1>
          <p className="text-muted-foreground text-sm mb-10">
            The engineering behind Syrabit.ai — a production-grade AI educational platform
          </p>

          <div className="space-y-12 text-foreground/70 leading-relaxed">

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                Platform Overview
              </h2>
              <p className="mb-4">
                Syrabit.ai is a full-stack AI-powered educational platform purpose-built for
                students in Assam preparing for AHSEC (Class 11–12), SEBA (Class 9–10), and
                Degree (B.Com, B.A, B.Sc under Gauhati University, Dibrugarh University, and
                Cotton University) examinations. The platform combines a React single-page
                application with a Python/FastAPI backend, a multi-provider LLM pipeline, and
                a Cloudflare edge network — all orchestrated as a pnpm monorepo with Docker
                containerization for production deployment.
              </p>
              <p>
                The system serves bilingual content in English and Assamese, processes natural
                language queries through a retrieval-augmented generation (RAG) pipeline, and
                auto-generates thousands of SEO-optimized pages covering every chapter in the
                supported curricula.
              </p>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-4">
                Full Technology Stack
              </h2>
              <div className="space-y-8">
                {TECH_STACK.map((group) => (
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
                AI &amp; RAG Pipeline
              </h2>
              <p className="mb-3">
                The core AI system uses a multi-stage retrieval-augmented generation pipeline
                specifically designed for syllabus-grounded answers. When a student asks a
                question, the system:
              </p>
              <ol className="list-decimal list-inside space-y-2 mb-4">
                <li>
                  Classifies the query intent and extracts the academic context (board, class,
                  subject, chapter)
                </li>
                <li>
                  Performs vector similarity search using 768-dimensional Gemini embeddings
                  stored in Cloudflare Vectorize
                </li>
                <li>
                  Retrieves relevant chapter content from MongoDB Atlas with compound index
                  optimization
                </li>
                <li>
                  Routes the augmented prompt to the fastest available LLM using hedged
                  requests — racing multiple providers (Groq, Cerebras, OpenRouter, Fireworks)
                  simultaneously for sub-1-second time-to-first-token
                </li>
                <li>
                  For Assamese queries, races Sarvam AI (native Assamese LLM) against Gemini
                  2.5 Flash with three API key rotation
                </li>
              </ol>
              <p>
                The pipeline achieves under 0.8 seconds TTFT for English queries and under 3
                seconds for Assamese queries. Every response includes source citations linking
                back to the exact chapter and topic.
              </p>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                Programmatic SEO Engine
              </h2>
              <p className="mb-3">
                The backend includes a custom programmatic SEO engine (Generative Engine
                Optimization) that automatically generates thousands of search-optimized pages.
                The engine produces:
              </p>
              <ul className="list-disc list-inside space-y-1.5 mb-4">
                <li>Chapter-level study notes pages with structured JSON-LD data</li>
                <li>MCQ and important question pages per chapter</li>
                <li>Previous year question (PYQ) HTML replicas from PDF scans via Gemini Vision OCR</li>
                <li>Definition and example pages with FAQ schema for Google rich results</li>
                <li>Dynamic sitemaps (9 sub-sitemaps covering pages, subjects, notes, MCQs, PYQs, examples, definitions, chapters, and learn articles)</li>
                <li>RSS/Atom feeds, llms.txt manifests, and AI plugin discovery endpoints</li>
                <li>Keyword expansion engine generating 80+ keyword variants per topic for maximum search coverage</li>
                <li>Automatic IndexNow push to search engines when new content is published</li>
              </ul>
              <p>
                Each generated page includes Schema.org structured data (Article, LearningResource,
                FAQPage, SpeakableSpecification), OpenGraph tags, geo-targeting meta tags for
                Assam (IN-AS), and board-specific keyword variants for AHSEC, SEBA, and Degree
                search queries.
              </p>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                Admin Tools &amp; Content Pipeline
              </h2>
              <p className="mb-3">
                A comprehensive admin dashboard provides full control over content generation,
                quality management, and platform analytics:
              </p>
              <ul className="list-disc list-inside space-y-1.5">
                <li>Batch content generation pipeline with parallel processing (notes, MCQs, flashcards via asyncio.gather)</li>
                <li>Content quality scoring with auto-detection of thin chapters and auto-heal with version history</li>
                <li>SEO management with SERP preview, coverage analytics, and keyword tracking</li>
                <li>Bot traffic analytics with daily hit charts, crawl coverage, and per-bot metrics</li>
                <li>LLM provider health monitoring with latency tracking and provider rotation</li>
                <li>RAG telemetry dashboard with similarity score distributions</li>
                <li>IndexNow push status monitoring with source breakdown</li>
                <li>User analytics, credit usage, and payment tracking</li>
              </ul>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                Infrastructure &amp; Edge Network
              </h2>
              <p className="mb-3">
                The platform uses a hybrid deployment architecture optimized for performance
                and cost:
              </p>
              <ul className="list-disc list-inside space-y-1.5">
                <li>
                  <span className="text-foreground font-medium">Edge Proxy</span> — Cloudflare Worker at api.syrabit.ai handles request routing, bot verification (CIDR-based IP range checking for Google, Bing, OpenAI, Yandex, Apple), rate limiting, and response caching
                </li>
                <li>
                  <span className="text-foreground font-medium">Frontend</span> — Cloudflare Pages at syrabit.ai with global CDN distribution, PWA service worker (multi-cache strategy), and offline access
                </li>
                <li>
                  <span className="text-foreground font-medium">Backend</span> — Railway-hosted Docker container running FastAPI with Gunicorn worker management
                </li>
                <li>
                  <span className="text-foreground font-medium">Edge Data</span> — Cloudflare D1 (SQLite replica) for read-heavy content catalog queries at the edge
                </li>
              </ul>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-4">
                Build Complexity &amp; Scale
              </h2>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
                {SCALE_METRICS.map((metric) => (
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
              <p>
                The platform integrates 6 LLM providers, 5 database systems, 2 payment
                gateways, and a complete Cloudflare edge network — all within a pnpm monorepo
                containing the frontend application, backend API, edge proxy worker, and shared
                libraries. The system handles bilingual content delivery, real-time AI chat
                streaming, automated content generation, and programmatic SEO at scale.
              </p>
            </section>

            <section>
              <h2 className="text-foreground font-semibold text-lg mb-3">
                Project Scale &amp; Development
              </h2>
              <p className="mb-3">
                Syrabit.ai was developed as a grant-funded initiative (funded under the Assam
                Startup ecosystem with ₹7.5 lakh seed funding) to address the lack of quality,
                syllabus-aligned digital education resources for students in Assam. The platform
                covers three major examination boards — AHSEC, SEBA, and university-level
                Degree programmes — across 55+ subjects spanning Science, Commerce, and Arts
                streams.
              </p>
              <p className="mb-3">
                Built by a solo full-stack developer over 12+ months of continuous development,
                the project spans frontend engineering, backend API design, AI/ML pipeline
                architecture, infrastructure and DevOps, content generation automation, SEO
                engine development, payment integration, and admin tooling. The architecture
                is designed for horizontal scalability with edge caching, database replication,
                and provider failover at every layer.
              </p>
              <p>
                Learn more about our mission and approach on the{' '}
                <Link to="/about" className="text-violet-600 hover:underline">
                  About page
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
