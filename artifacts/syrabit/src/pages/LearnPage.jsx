import { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { Helmet } from 'react-helmet-async';
import {
  BookOpen, ChevronRight, Clock, BarChart3, Share2,
  ArrowLeft, List, Loader2, AlertCircle, ExternalLink,
  Globe, CheckCircle, GraduationCap, Layers,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/AppLayout';
import axios from 'axios';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

function buildToc(headingsJson) {
  try {
    return JSON.parse(headingsJson || '[]');
  } catch {
    return [];
  }
}

function SchemaOrg({ doc }) {
  const schema = {
    '@context': 'https://schema.org',
    '@type': doc.schema_type || 'Article',
    headline: doc.title,
    description: doc.meta_description || doc.description || '',
    author: { '@type': 'Organization', name: 'Syrabit.ai' },
    publisher: {
      '@type': 'Organization',
      name: 'Syrabit.ai',
      logo: { '@type': 'ImageObject', url: 'https://syrabit.ai/logo.png' },
    },
    datePublished: doc.created_at,
    dateModified: doc.updated_at,
    keywords: doc.seo_tags || '',
    inLanguage: 'en-IN',
    educationalLevel: doc.geo_tags || 'Class 11-12',
    about: {
      '@type': 'Thing',
      name: doc.primary_keyword || doc.title,
    },
  };

  const breadcrumb = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://syrabit.ai' },
      { '@type': 'ListItem', position: 2, name: 'Browser', item: 'https://syrabit.ai/library' },
      { '@type': 'ListItem', position: 3, name: doc.title, item: `https://syrabit.ai/learn/${doc.seo_slug}` },
    ],
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(schema) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }}
      />
    </>
  );
}

function TocSidebar({ toc, activeId }) {
  if (!toc.length) return null;
  return (
    <nav className="sticky top-6 w-56 flex-shrink-0 hidden xl:block">
      <div className="rounded-2xl border border-white/10 overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)' }}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10">
          <List size={13} className="text-violet-400" />
          <span className="text-xs font-semibold text-white/60 uppercase tracking-wider">On this page</span>
        </div>
        <ul className="py-2 max-h-[70vh] overflow-y-auto">
          {toc.map(h => (
            <li key={h.anchor}>
              <a
                href={`#${h.anchor}`}
                className={`block py-1.5 pr-4 text-xs transition-colors leading-snug ${
                  h.level === 1 ? 'pl-4 font-medium' : h.level === 2 ? 'pl-6' : 'pl-8'
                } ${
                  activeId === h.anchor
                    ? 'text-violet-400 border-r-2 border-violet-500'
                    : 'text-white/40 hover:text-white/70'
                }`}
              >
                {h.text}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}

function injectHeadingIds(html) {
  return html.replace(/<(h[1-3])>(.*?)<\/h[1-3]>/gi, (_, tag, text) => {
    const plain = text.replace(/<[^>]+>/g, '').trim();
    const id = plain.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    return `<${tag} id="${id}">${text}</${tag}>`;
  });
}

export default function LearnPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);
  const [activeId, setActiveId] = useState('');
  const articleRef = useRef(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    axios.get(`${API}/content/cms-documents/${slug}`)
      .then(r => setDoc(r.data))
      .catch(e => setError(e.response?.status === 404 ? 'not-found' : 'error'))
      .finally(() => setLoading(false));
  }, [slug]);

  useEffect(() => {
    if (!doc) return;
    const obs = new IntersectionObserver(
      entries => {
        for (const e of entries) {
          if (e.isIntersecting) setActiveId(e.target.id);
        }
      },
      { rootMargin: '-10% 0% -80% 0%', threshold: 0 }
    );
    const headings = articleRef.current?.querySelectorAll('h1, h2, h3') || [];
    headings.forEach(h => h.id && obs.observe(h));
    return () => obs.disconnect();
  }, [doc]);

  const toc = useMemo(() => buildToc(doc?.headings), [doc]);

  const readTime = useMemo(() => {
    if (!doc) return 0;
    const wpm = 200;
    return Math.max(1, Math.ceil((doc.word_count || 0) / wpm));
  }, [doc]);

  const processedHtml = useMemo(() => {
    if (!doc?.content_html) return '';
    return injectHeadingIds(doc.content_html);
  }, [doc]);

  const handleShare = () => {
    if (navigator.share) {
      navigator.share({ title: doc?.title, url: window.location.href });
    } else {
      navigator.clipboard?.writeText(window.location.href);
      // simple feedback
    }
  };

  if (loading) {
    return (
      <AppLayout>
        <div className="min-h-screen flex items-center justify-center futuristic-bg">
          <Loader2 size={28} className="animate-spin text-violet-400" />
        </div>
      </AppLayout>
    );
  }

  if (error === 'not-found') {
    return (
      <AppLayout>
        <div className="min-h-screen flex flex-col items-center justify-center gap-4 futuristic-bg">
          <AlertCircle size={40} className="text-amber-400" />
          <h1 className="text-xl font-bold text-white">Page Not Found</h1>
          <p className="text-white/50 text-sm">This study resource doesn't exist or hasn't been published yet.</p>
          <Link to="/library" className="mt-2 h-9 px-4 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium flex items-center gap-2">
            <ArrowLeft size={14} /> Back to Browser
          </Link>
        </div>
      </AppLayout>
    );
  }

  if (error) {
    return (
      <AppLayout>
        <div className="min-h-screen flex flex-col items-center justify-center gap-4 futuristic-bg">
          <AlertCircle size={40} className="text-red-400" />
          <p className="text-white/50 text-sm">Failed to load content. Please try again.</p>
          <button onClick={() => window.location.reload()} className="h-9 px-4 rounded-xl bg-white/10 hover:bg-white/15 text-white text-sm">
            Retry
          </button>
        </div>
      </AppLayout>
    );
  }

  const tags = doc.seo_tags ? doc.seo_tags.split(',').map(t => t.trim()).filter(Boolean) : [];

  return (
    <AppLayout>
      {doc && (
        <>
          <Helmet>
            <title>{doc.title} | Syrabit.ai</title>
            <meta name="description" content={doc.meta_description || doc.description || doc.title} />
            <meta property="og:title" content={`${doc.title} | Syrabit.ai`} />
            <meta property="og:description" content={doc.meta_description || doc.description || ''} />
            <meta property="og:type" content="article" />
            <meta property="og:url" content={`https://syrabit.ai/learn/${doc.seo_slug}`} />
            {doc.thumbnail_url && <meta property="og:image" content={doc.thumbnail_url} />}
            <meta name="keywords" content={doc.seo_tags || ''} />
            <link rel="canonical" href={`https://syrabit.ai/learn/${doc.seo_slug}`} />
          </Helmet>
          <SchemaOrg doc={doc} />
        </>
      )}

      <div className="min-h-screen futuristic-bg pb-20">
        <div className="max-w-6xl mx-auto px-4 md:px-6 pt-6">

          {/* Breadcrumb */}
          <nav className="flex items-center gap-1 text-xs text-white/35 mb-6" aria-label="Breadcrumb">
            <Link to="/" className="hover:text-white/70 transition-colors">Home</Link>
            <ChevronRight size={11} className="flex-shrink-0" />
            <Link to="/library" className="hover:text-white/70 transition-colors">Browser</Link>
            <ChevronRight size={11} className="flex-shrink-0" />
            <span className="text-white/55 truncate max-w-xs">{doc?.title}</span>
          </nav>

          {/* Hero header */}
          <div className="mb-8">
            {/* Syllabus type banner */}
            {doc?.type === 'syllabus' && (
              <div className="flex items-center gap-2 mb-4 px-3 py-2 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] w-fit">
                <GraduationCap size={14} className="text-emerald-400" />
                <span className="text-xs font-semibold text-emerald-300">Official Syllabus</span>
                <span className="text-white/25 text-xs">·</span>
                <span className="text-xs text-white/40">AI-assisted learning available</span>
              </div>
            )}
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-4">
                {tags.slice(0, 5).map(tag => (
                  <span
                    key={tag}
                    className="px-2.5 py-1 rounded-full text-[11px] font-medium border"
                    style={tag.toLowerCase() === 'syllabus'
                      ? { borderColor: 'rgba(16,185,129,0.25)', background: 'rgba(16,185,129,0.08)', color: '#6ee7b7' }
                      : { borderColor: 'rgba(139,92,246,0.2)', background: 'rgba(139,92,246,0.08)', color: '#a78bfa' }
                    }
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
            <h1 className="text-2xl md:text-3xl font-bold text-white leading-tight mb-3">{doc?.title}</h1>
            {(doc?.meta_description || doc?.description) && (
              <p className="text-white/55 text-base leading-relaxed max-w-3xl">
                {doc.meta_description || doc.description}
              </p>
            )}
            <div className="flex items-center gap-4 mt-4 flex-wrap">
              <div className="flex items-center gap-1.5 text-xs text-white/35">
                <Clock size={12} />
                <span>{readTime} min read</span>
              </div>
              {doc?.word_count > 0 && (
                <div className="flex items-center gap-1.5 text-xs text-white/35">
                  <BarChart3 size={12} />
                  <span>{doc.word_count.toLocaleString()} words</span>
                </div>
              )}
              <div className="flex items-center gap-1.5 text-xs text-white/35">
                <CheckCircle size={12} className="text-emerald-400" />
                <span>Published · Syrabit.ai</span>
              </div>
              <button
                onClick={handleShare}
                className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-white/40 hover:text-white/70 border border-white/10 hover:border-white/20 transition-colors"
              >
                <Share2 size={11} /> Share
              </button>
            </div>
          </div>

          {/* Main layout: content + TOC */}
          <div className="flex gap-8 items-start">
            {/* Article */}
            <article
              ref={articleRef}
              className="flex-1 min-w-0 rounded-2xl border border-white/10 overflow-hidden"
              style={{ background: 'rgba(255,255,255,0.025)' }}
            >
              {doc?.thumbnail_url && (
                <div className="w-full aspect-video overflow-hidden">
                  <img
                    src={doc.thumbnail_url}
                    alt={doc.alt_text || doc.title}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                </div>
              )}
              <div className="p-6 md:p-10">
                {processedHtml ? (
                  <div
                    className="md-content learn-article max-w-none"
                    dangerouslySetInnerHTML={{ __html: processedHtml }}
                  />
                ) : doc?.content ? (
                  <div className="md-content whitespace-pre-wrap text-sm leading-relaxed">{doc.content}</div>
                ) : (
                  <p className="text-white/30 italic">No content available.</p>
                )}
              </div>
            </article>

            {/* TOC */}
            <TocSidebar toc={toc} activeId={activeId} />
          </div>

          {/* Syllabus: Lessons Coming Soon */}
          {doc?.type === 'syllabus' && (
            <div className="mt-8 rounded-2xl border border-white/10 overflow-hidden">
              <div className="px-6 py-4 border-b border-white/[0.06] flex items-center gap-2" style={{ background: 'rgba(16,185,129,0.05)' }}>
                <Layers size={15} className="text-emerald-400" />
                <span className="text-sm font-semibold text-white">Lesson Content</span>
                <span className="ml-auto px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/20">Coming Soon</span>
              </div>
              <div className="px-6 py-8 text-center" style={{ background: 'rgba(255,255,255,0.015)' }}>
                <GraduationCap size={32} className="mx-auto text-white/10 mb-3" />
                <p className="text-white/50 text-sm mb-1">Detailed lesson content is being prepared for each chapter.</p>
                <p className="text-white/30 text-xs">Each chapter will have full explanations, examples, and practice questions.</p>
                <Link
                  to="/chat"
                  className="inline-flex items-center gap-2 mt-5 h-9 px-4 rounded-xl bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 text-sm font-medium transition-colors border border-emerald-500/20"
                >
                  <BookOpen size={13} /> Ask AI about this subject now
                </Link>
              </div>
            </div>
          )}

          {/* Footer CTA */}
          <div className="mt-8 rounded-2xl border border-white/10 p-6 flex flex-col sm:flex-row items-center gap-4" style={{ background: 'rgba(139,92,246,0.06)' }}>
            <div className="flex-1 text-center sm:text-left">
              <p className="text-white font-semibold mb-1">Want AI-powered answers on this topic?</p>
              <p className="text-white/45 text-sm">Ask Syrabit — your AHSEC exam tutor — any question about this content.</p>
            </div>
            <Link
              to="/chat"
              className="h-10 px-5 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-semibold flex items-center gap-2 flex-shrink-0 transition-colors"
            >
              <BookOpen size={14} /> Ask AI Tutor
            </Link>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
