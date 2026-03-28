import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import { Analytics } from '@/utils/analytics';
import { BookOpen, ChevronRight, ArrowLeft, ArrowRight, FileText, HelpCircle,
  Calculator, BookMarked, Home, Sparkles, GraduationCap, Lightbulb } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { getSeoPage, getSeoPageTypes, getSeoRelated } from '@/utils/api';
import CommonQuestions from '@/components/seo/CommonQuestions';

const PAGE_TYPE_META = {
  'notes':               { label: 'Notes',               icon: FileText,   color: 'bg-blue-500/15 text-blue-400 border-blue-500/25' },
  'definition':          { label: 'Definition',           icon: BookOpen,   color: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25' },
  'important-questions': { label: 'Important Questions',  icon: HelpCircle, color: 'bg-amber-500/15 text-amber-400 border-amber-500/25' },
  'mcqs':                { label: 'MCQs',                 icon: Calculator, color: 'bg-violet-500/15 text-violet-400 border-violet-500/25' },
  'examples':            { label: 'Examples',             icon: BookMarked, color: 'bg-pink-500/15 text-pink-400 border-pink-500/25' },
};

function sanitizeHtml(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  doc.querySelectorAll('script, iframe, object, embed, form').forEach((el) => el.remove());
  doc.querySelectorAll('*').forEach((el) => {
    for (const attr of [...el.attributes]) {
      if (attr.name.startsWith('on') || attr.value.trim().toLowerCase().startsWith('javascript:')) {
        el.removeAttribute(attr.name);
      }
    }
  });
  return doc.body.innerHTML;
}

function renderMarkdown(text) {
  if (!text) return '';
  let html = text
    .replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^#### (.+)$/gm, '<h4 class="text-base font-semibold text-white mt-5 mb-2">$1</h4>')
    .replace(/^### (.+)$/gm, '<h3 class="text-lg font-semibold text-white mt-6 mb-2">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="text-xl font-bold text-white mt-8 mb-3 pb-2 border-b border-white/10">$1</h2>')
    .replace(/^# (.+)$/gm, '<h2 class="text-2xl font-bold text-white mt-8 mb-4">$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^---$/gm, '<hr class="border-white/10 my-6" />')
    .replace(/^- (.+)$/gm, '<li class="ml-4 mb-1 text-gray-300 list-disc">$1</li>')
    .replace(/^(\d+)\. (.+)$/gm, '<li class="ml-4 mb-1 text-gray-300 list-decimal" value="$1">$2</li>')
    .replace(/`([^`]+)`/g, '<code class="bg-white/10 text-purple-300 px-1.5 py-0.5 rounded text-sm">$1</code>')
    .replace(/\n\n/g, '</p><p class="text-gray-300 leading-relaxed mb-3">')
    .replace(/\n/g, '<br/>');
  return sanitizeHtml(`<p class="text-gray-300 leading-relaxed mb-3">${html}</p>`);
}

export default function SeoTopicPage() {
  const { board, classSlug, subjectSlug, topicSlug, pageType } = useParams();
  const navigate = useNavigate();
  const currentType = pageType || 'notes';

  const [page, setPage] = useState(null);
  const [pageTypes, setPageTypes] = useState([]);
  const [related, setRelated] = useState({ related: [], prev: null, next: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      getSeoPage(board, classSlug, subjectSlug, topicSlug, currentType),
      getSeoPageTypes(board, classSlug, subjectSlug, topicSlug),
      getSeoRelated(topicSlug),
    ])
      .then(([pageRes, typesRes, relatedRes]) => {
        if (cancelled) return;
        setPage(pageRes.data);
        setPageTypes(typesRes.data || []);
        setRelated(relatedRes.data || { related: [], prev: null, next: null });
        try { Analytics.seoPageView(board, classSlug, subjectSlug, topicSlug, currentType); } catch {}
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.response?.status === 404 ? 'Page not found' : 'Failed to load content');
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [board, classSlug, subjectSlug, topicSlug, currentType]);

  useEffect(() => {
    if (!page) return;
    const pageUrl = `https://syrabit.ai/${board}/${classSlug}/${subjectSlug}/${topicSlug}${currentType !== 'notes' ? `/${currentType}` : ''}`;

    const articleSchema = {
      '@context': 'https://schema.org',
      '@type': 'Article',
      headline: page.title,
      description: page.meta_description,
      author: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
      publisher: {
        '@type': 'Organization',
        name: 'Syrabit.ai',
        url: 'https://syrabit.ai',
        logo: { '@type': 'ImageObject', url: 'https://syrabit.ai/icons/icon-192x192.png' },
      },
      datePublished: page.generated_at,
      dateModified: page.updated_at || page.generated_at,
      image: 'https://syrabit.ai/opengraph.jpg',
      mainEntityOfPage: { '@type': 'WebPage', '@id': pageUrl },
      educationalLevel: `${page.class_name || ''} ${page.board_name || ''}`.trim(),
      about: { '@type': 'Thing', name: page.topic_title },
      isPartOf: { '@type': 'WebSite', '@id': 'https://syrabit.ai', name: 'Syrabit.ai' },
      inLanguage: 'en-IN',
    };

    const breadcrumbSchema = {
      '@context': 'https://schema.org',
      '@type': 'BreadcrumbList',
      itemListElement: [
        { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://syrabit.ai' },
        { '@type': 'ListItem', position: 2, name: 'Library', item: 'https://syrabit.ai/library' },
        { '@type': 'ListItem', position: 3, name: page.subject_name || subjectSlug, item: 'https://syrabit.ai/library' },
        { '@type': 'ListItem', position: 4, name: page.topic_title || topicSlug, item: pageUrl },
      ],
    };

    const schemas = [articleSchema, breadcrumbSchema];

    if (['important-questions', 'mcqs'].includes(currentType) && page.content) {
      const lines = page.content.split('\n').filter(Boolean);
      const questions = [];
      let currentQ = null;
      for (const line of lines) {
        const stripped = line.replace(/^#+\s*/, '').replace(/^\*\*/, '').replace(/\*\*$/, '').trim();
        if (line.match(/^[#*]/) && stripped.endsWith('?')) { currentQ = stripped; }
        else if (currentQ && stripped.length > 10) {
          questions.push({ '@type': 'Question', name: currentQ, acceptedAnswer: { '@type': 'Answer', text: stripped } });
          currentQ = null;
          if (questions.length >= 10) break;
        }
      }
      if (questions.length >= 3) {
        schemas.push({ '@context': 'https://schema.org', '@type': 'FAQPage', mainEntity: questions });
      }
    }

    ['seo-topic-jsonld', 'seo-topic-breadcrumb', 'seo-topic-faq'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.remove();
    });
    const ids = ['seo-topic-jsonld', 'seo-topic-breadcrumb', 'seo-topic-faq'];
    schemas.forEach((schema, i) => {
      const s = document.createElement('script');
      s.type = 'application/ld+json';
      s.id = ids[i];
      s.text = JSON.stringify(schema);
      document.head.appendChild(s);
    });
    return () => {
      ['seo-topic-jsonld', 'seo-topic-breadcrumb', 'seo-topic-faq'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.remove();
      });
    };
  }, [page, board, classSlug, subjectSlug, topicSlug, currentType]);

  const basePath = `/${board}/${classSlug}/${subjectSlug}/${topicSlug}`;
  const canonicalUrl = `https://syrabit.ai${basePath}${currentType !== 'notes' ? `/${currentType}` : ''}`;

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a1a] text-white">
        <div className="max-w-4xl mx-auto px-4 py-8">
          <Skeleton className="h-6 w-64 mb-4 bg-white/5" />
          <Skeleton className="h-10 w-full mb-6 bg-white/5" />
          <Skeleton className="h-4 w-3/4 mb-2 bg-white/5" />
          <Skeleton className="h-4 w-full mb-2 bg-white/5" />
          <Skeleton className="h-4 w-2/3 mb-2 bg-white/5" />
          <Skeleton className="h-64 w-full bg-white/5" />
        </div>
      </div>
    );
  }

  if (error || !page) {
    return (
      <div className="min-h-screen bg-[#0a0a1a] text-white flex items-center justify-center">
        <div className="text-center">
          <h1 className="text-2xl font-bold mb-4">{error || 'Page not found'}</h1>
          <p className="text-gray-400 mb-6">The study material you're looking for hasn't been generated yet.</p>
          <Link to="/library" className="px-6 py-3 bg-purple-600 hover:bg-purple-700 rounded-lg text-white font-medium transition-colors">
            Browse Library
          </Link>
        </div>
      </div>
    );
  }

  const typeMeta = PAGE_TYPE_META[currentType] || PAGE_TYPE_META['notes'];
  const boardShort = (page.board_name || board).toUpperCase();
  const pageTypeLabel = currentType === 'notes' ? 'Notes' : currentType === 'important-questions' ? 'Important Questions for Board Exam' : currentType === 'mcqs' ? 'MCQ Practice' : currentType === 'definition' ? 'Definition & Meaning' : 'Examples & Solutions';

  return (
    <div className="min-h-screen bg-[#0a0a1a] text-white">
      <PageMeta
        title={page.title}
        description={page.meta_description}
        url={canonicalUrl}
        type="article"
        section={page.subject_name}
        keywords={[
          page.topic_title,
          `${page.topic_title} notes`,
          `${page.topic_title} ${boardShort}`,
          `${page.topic_title} ${page.class_name}`,
          `${page.topic_title} important questions`,
          page.subject_name,
          page.chapter_title,
          page.board_name,
          page.class_name,
          'board exam preparation',
          'study notes',
          'AHSEC', 'SEBA',
        ].filter(Boolean).join(', ')}
        tags={[page.topic_title, page.subject_name, page.board_name].filter(Boolean)}
        publishedTime={page.generated_at}
        modifiedTime={page.updated_at || page.generated_at}
      />

      <div className="max-w-4xl mx-auto px-4 py-6">

        {/* Breadcrumb */}
        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm text-gray-400 mb-6 flex-wrap">
          <Link to="/" className="hover:text-purple-400 transition-colors flex items-center gap-1">
            <Home size={14} aria-hidden="true" /> Home
          </Link>
          <ChevronRight size={12} aria-hidden="true" />
          <Link to="/library" className="hover:text-purple-400 transition-colors">Library</Link>
          <ChevronRight size={12} aria-hidden="true" />
          <span className="text-gray-500">{page.subject_name}</span>
          <ChevronRight size={12} aria-hidden="true" />
          <span className="text-white font-medium">{page.topic_title}</span>
        </nav>

        {/* Title block */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <Badge variant="outline" className="text-xs text-purple-400 border-purple-500/30">{page.board_name}</Badge>
            <Badge variant="outline" className="text-xs text-blue-400 border-blue-500/30">{page.class_name}</Badge>
            <Badge variant="outline" className="text-xs text-emerald-400 border-emerald-500/30">{page.subject_name}</Badge>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold text-white leading-tight">
            {page.topic_title} – {boardShort} {page.class_name} {page.subject_name}
          </h1>
          <p className="text-gray-400 mt-1 text-sm">
            {pageTypeLabel} &middot; {page.chapter_title}
          </p>
          <p className="text-gray-500 text-xs mt-1">
            {page.word_count} words &middot; Updated {new Date(page.updated_at || page.generated_at || Date.now()).toLocaleDateString('en-IN')}
          </p>
        </div>

        {/* Content type tabs */}
        <div className="flex gap-2 mb-8 overflow-x-auto pb-2" role="tablist" aria-label="Content type tabs">
          {Object.entries(PAGE_TYPE_META).map(([type, meta]) => {
            const available = pageTypes.some((p) => p.page_type === type);
            const Icon = meta.icon;
            const isActive = currentType === type;
            const linkPath = type === 'notes' ? basePath : `${basePath}/${type}`;
            const ariaLabel = `${meta.label} for ${page.topic_title}`;
            return available ? (
              <Link
                key={type}
                to={linkPath}
                role="tab"
                aria-selected={isActive}
                aria-label={ariaLabel}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-all ${
                  isActive
                    ? 'bg-purple-600 text-white shadow-lg shadow-purple-500/20'
                    : 'bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white'
                }`}
              >
                <Icon size={14} aria-hidden="true" />
                {meta.label}
              </Link>
            ) : (
              <span key={type} className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap bg-white/[0.02] text-gray-600 cursor-not-allowed">
                <Icon size={14} aria-hidden="true" />
                {meta.label}
              </span>
            );
          })}
        </div>

        {/* Main content */}
        <article className="prose prose-invert max-w-none bg-white/[0.03] rounded-2xl border border-white/5 p-6 md:p-8">
          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(page.content) }} />
        </article>

        {/* Board exam tips section */}
        <div className="mt-6 bg-amber-500/5 border border-amber-500/15 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <Lightbulb size={16} className="text-amber-400" aria-hidden="true" />
            <h2 className="text-white font-semibold text-base">
              {boardShort} Board Exam Tips for {page.topic_title}
            </h2>
          </div>
          <ul className="space-y-1.5 text-gray-400 text-sm">
            <li className="flex items-start gap-2">
              <span className="text-amber-400 mt-0.5">•</span>
              <span>This topic is part of <strong className="text-gray-300">{page.chapter_title}</strong> in {boardShort} {page.class_name} {page.subject_name} syllabus.</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-amber-400 mt-0.5">•</span>
              <span>Study the <Link to={`${basePath}/important-questions`} className="text-purple-400 hover:underline">important questions for {page.topic_title}</Link> and <Link to={`${basePath}/mcqs`} className="text-purple-400 hover:underline">MCQs</Link> to prepare for your {boardShort} exam.</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-amber-400 mt-0.5">•</span>
              <span>Use the <Link to="/chat" className="text-purple-400 hover:underline">AI Chat</Link> to ask any question about {page.topic_title} and get instant, syllabus-aligned answers.</span>
            </li>
          </ul>
        </div>

        {/* Explore other content types for this topic */}
        <div className="mt-6 bg-white/[0.025] border border-white/5 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <GraduationCap size={16} className="text-blue-400" aria-hidden="true" />
            <h2 className="text-white font-semibold text-base">
              More Study Material for {page.topic_title}
            </h2>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {[
              { type: 'notes',               label: `${page.topic_title} Notes` },
              { type: 'definition',          label: `${page.topic_title} Definition` },
              { type: 'important-questions', label: `${page.topic_title} Important Questions` },
              { type: 'mcqs',                label: `${page.topic_title} MCQs` },
              { type: 'examples',            label: `${page.topic_title} Examples` },
            ].filter(({ type }) => type !== currentType && pageTypes.some(p => p.page_type === type)).map(({ type, label }) => (
              <Link
                key={type}
                to={type === 'notes' ? basePath : `${basePath}/${type}`}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-sm text-gray-400 hover:text-white"
                aria-label={label}
              >
                {PAGE_TYPE_META[type]?.icon && (() => { const Icon = PAGE_TYPE_META[type].icon; return <Icon size={12} aria-hidden="true" />; })()}
                <span className="truncate">{PAGE_TYPE_META[type]?.label}</span>
              </Link>
            ))}
          </div>
        </div>

        {/* Prev/Next navigation */}
        {(related.prev || related.next) && (
          <div className="flex justify-between items-center mt-8 gap-4">
            {related.prev ? (
              <Link
                to={related.prev.seo_path || '#'}
                aria-label={`Previous topic: ${related.prev.title}`}
                className="flex items-center gap-2 px-4 py-3 rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-sm text-gray-300 hover:text-white group"
              >
                <ArrowLeft size={16} className="group-hover:-translate-x-1 transition-transform" aria-hidden="true" />
                <div className="text-left">
                  <div className="text-xs text-gray-500">Previous Topic</div>
                  <div className="font-medium">{related.prev.title}</div>
                </div>
              </Link>
            ) : <div />}
            {related.next ? (
              <Link
                to={related.next.seo_path || '#'}
                aria-label={`Next topic: ${related.next.title}`}
                className="flex items-center gap-2 px-4 py-3 rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-sm text-gray-300 hover:text-white group text-right"
              >
                <div>
                  <div className="text-xs text-gray-500">Next Topic</div>
                  <div className="font-medium">{related.next.title}</div>
                </div>
                <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" aria-hidden="true" />
              </Link>
            ) : <div />}
          </div>
        )}

        {/* Related topics — keyword-rich anchor text */}
        {related.related?.length > 0 && (
          <div className="mt-8 bg-white/[0.03] rounded-2xl border border-white/5 p-6">
            <div className="flex items-center gap-2 mb-4">
              <BookOpen size={16} className="text-purple-400" aria-hidden="true" />
              <h2 className="text-lg font-bold text-white">
                Related {page.subject_name} Topics — {boardShort} {page.class_name}
              </h2>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {related.related.map((t) => (
                <Link
                  key={t.id}
                  to={t.seo_path || '#'}
                  aria-label={`${t.title} — ${boardShort} ${page.class_name} ${page.subject_name} Notes`}
                  className="flex items-center gap-3 px-4 py-3 rounded-xl bg-white/5 hover:bg-white/10 transition-colors group"
                >
                  <BookOpen size={16} className="text-purple-400 flex-shrink-0" aria-hidden="true" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-gray-200 group-hover:text-white transition-colors truncate">
                      {t.title}
                    </div>
                    <div className="text-xs text-gray-500">
                      {page.subject_name} &middot; {boardShort}
                    </div>
                  </div>
                  <ChevronRight size={14} className="ml-auto text-gray-600 group-hover:text-gray-400 flex-shrink-0" aria-hidden="true" />
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* Common Questions (from QA pairs) */}
        {page?.qa_pairs?.length > 0 && (
          <CommonQuestions
            qaPairs={page.qa_pairs}
            board={board}
            classSlug={classSlug}
            subjectSlug={subjectSlug}
            topicSlug={topicSlug}
          />
        )}

        {/* AI CTA */}
        <div className="mt-8 bg-violet-600/10 border border-violet-500/20 rounded-2xl p-6 flex flex-col sm:flex-row items-center gap-4">
          <div className="flex-1 text-center sm:text-left">
            <div className="flex items-center gap-2 justify-center sm:justify-start mb-1">
              <Sparkles size={16} className="text-violet-400" aria-hidden="true" />
              <span className="text-violet-400 text-sm font-medium">Study with AI</span>
            </div>
            <p className="text-gray-300 text-sm">
              Got questions about <strong className="text-white">{page.topic_title}</strong>? Ask our AI tutor for instant, {boardShort}-aligned answers.
            </p>
          </div>
          <Link
            to="/chat"
            className="flex-shrink-0 px-5 py-2.5 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-sm font-medium transition-colors whitespace-nowrap"
          >
            Ask AI Tutor
          </Link>
        </div>

        {/* Footer nav */}
        <nav className="mt-8 pt-6 border-t border-white/5" aria-label="Site navigation">
          <div className="flex flex-wrap gap-3 justify-center text-xs text-gray-500">
            <Link to="/" className="hover:text-purple-400 transition-colors">Home</Link>
            <Link to="/library" className="hover:text-purple-400 transition-colors">Study Library</Link>
            <Link to="/pricing" className="hover:text-purple-400 transition-colors">Plans &amp; Pricing</Link>
            <Link to="/signup" className="hover:text-purple-400 transition-colors">Get Started Free</Link>
            <Link to="/chat" className="hover:text-purple-400 transition-colors">AI Tutor</Link>
          </div>
          <p className="text-center text-xs text-gray-600 mt-3">
            Syrabit.ai — AI-powered exam prep for Assam Board students · {boardShort} · SEBA · AHSEC · Degree College
          </p>
        </nav>

      </div>
    </div>
  );
}
