import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import { BookOpen, ChevronRight, ArrowLeft, ArrowRight, FileText, HelpCircle, Calculator, BookMarked, Home } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { getSeoPage, getSeoPageTypes, getSeoRelated } from '@/utils/api';

const PAGE_TYPE_META = {
  'notes':               { label: 'Notes',               icon: FileText,   color: 'bg-blue-500/15 text-blue-400 border-blue-500/25' },
  'definition':          { label: 'Definition',           icon: BookOpen,   color: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25' },
  'important-questions': { label: 'Important Questions',  icon: HelpCircle, color: 'bg-amber-500/15 text-amber-400 border-amber-500/25' },
  'mcqs':                { label: 'MCQs',                 icon: Calculator, color: 'bg-violet-500/15 text-violet-400 border-violet-500/25' },
  'examples':            { label: 'Examples',             icon: BookMarked, color: 'bg-pink-500/15 text-pink-400 border-pink-500/25' },
};

function sanitizeHtml(html) {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const scripts = doc.querySelectorAll('script, iframe, object, embed, form');
  scripts.forEach((el) => el.remove());
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
    .replace(/^# (.+)$/gm, '<h1 class="text-2xl font-bold text-white mt-8 mb-4">$1</h1>')
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
  const { board, classSlug, subjectSlug, chapterSlug, topicSlug, pageType } = useParams();
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
      getSeoPage(board, classSlug, subjectSlug, chapterSlug, topicSlug, currentType),
      getSeoPageTypes(board, classSlug, subjectSlug, chapterSlug, topicSlug),
      getSeoRelated(topicSlug),
    ])
      .then(([pageRes, typesRes, relatedRes]) => {
        if (cancelled) return;
        setPage(pageRes.data);
        setPageTypes(typesRes.data || []);
        setRelated(relatedRes.data || { related: [], prev: null, next: null });
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.response?.status === 404 ? 'Page not found' : 'Failed to load content');
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [board, classSlug, subjectSlug, chapterSlug, topicSlug, currentType]);

  useEffect(() => {
    if (!page) return;
    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.id = 'seo-topic-jsonld';
    script.text = JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'Article',
      headline: page.title,
      description: page.meta_description,
      author: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
      publisher: { '@type': 'Organization', name: 'Syrabit.ai' },
      datePublished: page.generated_at,
      dateModified: page.updated_at,
      mainEntityOfPage: {
        '@type': 'WebPage',
        '@id': `https://syrabit.ai/${board}/${classSlug}/${subjectSlug}/${chapterSlug}/${topicSlug}${currentType !== 'notes' ? `/${currentType}` : ''}`,
      },
      educationalLevel: `${page.class_name || ''} ${page.board_name || ''}`.trim(),
      about: { '@type': 'Thing', name: page.topic_title },
    });
    const existing = document.getElementById('seo-topic-jsonld');
    if (existing) existing.remove();
    document.head.appendChild(script);
    return () => { const el = document.getElementById('seo-topic-jsonld'); if (el) el.remove(); };
  }, [page, board, classSlug, subjectSlug, chapterSlug, topicSlug, currentType]);

  const basePath = `/${board}/${classSlug}/${subjectSlug}/${chapterSlug}/${topicSlug}`;
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

  return (
    <div className="min-h-screen bg-[#0a0a1a] text-white">
      <PageMeta
        title={page.title}
        description={page.meta_description}
        url={canonicalUrl}
      />

      <div className="max-w-4xl mx-auto px-4 py-6">

        <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm text-gray-400 mb-6 flex-wrap">
          <Link to="/" className="hover:text-purple-400 transition-colors flex items-center gap-1">
            <Home size={14} aria-hidden="true" /> Home
          </Link>
          <ChevronRight size={12} aria-hidden="true" />
          <Link to="/library" className="hover:text-purple-400 transition-colors">Library</Link>
          <ChevronRight size={12} aria-hidden="true" />
          <span className="text-gray-500">{page.subject_name}</span>
          <ChevronRight size={12} aria-hidden="true" />
          <span className="text-gray-500">{page.chapter_title}</span>
          <ChevronRight size={12} aria-hidden="true" />
          <span className="text-white font-medium">{page.topic_title}</span>
        </nav>

        <div className="mb-6">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <Badge variant="outline" className="text-xs text-purple-400 border-purple-500/30">
              {page.board_name}
            </Badge>
            <Badge variant="outline" className="text-xs text-blue-400 border-blue-500/30">
              {page.class_name}
            </Badge>
            <Badge variant="outline" className="text-xs text-emerald-400 border-emerald-500/30">
              {page.subject_name}
            </Badge>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold text-white leading-tight">
            {page.topic_title} — {page.board_name} {page.class_name} {page.subject_name}
          </h1>
          <p className="text-gray-400 mt-2 text-sm">
            {page.chapter_title} &middot; {page.word_count} words &middot; Updated {new Date(page.updated_at).toLocaleDateString()}
          </p>
        </div>

        <div className="flex gap-2 mb-8 overflow-x-auto pb-2" role="tablist" aria-label="Content type tabs">
          {Object.entries(PAGE_TYPE_META).map(([type, meta]) => {
            const available = pageTypes.some((p) => p.page_type === type);
            const Icon = meta.icon;
            const isActive = currentType === type;
            const linkPath = type === 'notes' ? basePath : `${basePath}/${type}`;

            return available ? (
              <Link
                key={type}
                to={linkPath}
                role="tab"
                aria-selected={isActive}
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
              <span
                key={type}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium whitespace-nowrap bg-white/[0.02] text-gray-600 cursor-not-allowed"
              >
                <Icon size={14} aria-hidden="true" />
                {meta.label}
              </span>
            );
          })}
        </div>

        <article className="prose prose-invert max-w-none bg-white/[0.03] rounded-2xl border border-white/5 p-6 md:p-8">
          <div dangerouslySetInnerHTML={{ __html: renderMarkdown(page.content) }} />
        </article>

        {(related.prev || related.next) && (
          <div className="flex justify-between items-center mt-8 gap-4">
            {related.prev ? (
              <Link
                to={related.prev.seo_path || '#'}
                className="flex items-center gap-2 px-4 py-3 rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-sm text-gray-300 hover:text-white group"
              >
                <ArrowLeft size={16} className="group-hover:-translate-x-1 transition-transform" aria-hidden="true" />
                <div className="text-left">
                  <div className="text-xs text-gray-500">Previous</div>
                  <div className="font-medium">{related.prev.title}</div>
                </div>
              </Link>
            ) : <div />}
            {related.next ? (
              <Link
                to={related.next.seo_path || '#'}
                className="flex items-center gap-2 px-4 py-3 rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-sm text-gray-300 hover:text-white group text-right"
              >
                <div>
                  <div className="text-xs text-gray-500">Next</div>
                  <div className="font-medium">{related.next.title}</div>
                </div>
                <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" aria-hidden="true" />
              </Link>
            ) : <div />}
          </div>
        )}

        {related.related?.length > 0 && (
          <div className="mt-8 bg-white/[0.03] rounded-2xl border border-white/5 p-6">
            <h2 className="text-lg font-bold text-white mb-4">Related Topics</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {related.related.map((t) => (
                <Link
                  key={t.id}
                  to={t.seo_path || '#'}
                  className="flex items-center gap-3 px-4 py-3 rounded-xl bg-white/5 hover:bg-white/10 transition-colors group"
                >
                  <BookOpen size={16} className="text-purple-400" aria-hidden="true" />
                  <div>
                    <div className="text-sm font-medium text-gray-200 group-hover:text-white transition-colors">{t.title}</div>
                  </div>
                  <ChevronRight size={14} className="ml-auto text-gray-600 group-hover:text-gray-400" aria-hidden="true" />
                </Link>
              ))}
            </div>
          </div>
        )}

        <div className="mt-8 text-center">
          <Link
            to="/library"
            className="inline-flex items-center gap-2 px-6 py-3 bg-purple-600/20 hover:bg-purple-600/30 text-purple-400 rounded-xl transition-colors text-sm font-medium"
          >
            <BookOpen size={16} aria-hidden="true" />
            Explore More Subjects
          </Link>
        </div>
      </div>
    </div>
  );
}
