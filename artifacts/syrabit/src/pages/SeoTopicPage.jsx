import { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import { Analytics } from '@/utils/analytics';
import { BookOpen, ChevronRight, ArrowLeft, ArrowRight, FileText, HelpCircle,
  Calculator, BookMarked, Home, Sparkles, GraduationCap, Lightbulb, List, Clock, ChevronDown } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { getSeoPage, getSeoPageTypes, getSeoRelated, getChapterBySlug } from '@/utils/api';
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

function extractTocItems(content) {
  if (!content) return [];
  const items = [];
  const lines = content.split('\n');
  const idCounts = {};
  for (const line of lines) {
    const match = line.match(/^(#{1,3})\s+(.+)$/);
    if (match) {
      const level = match[1].length;
      const text = match[2].replace(/\*\*/g, '').trim();
      let baseId = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
      idCounts[baseId] = (idCounts[baseId] || 0) + 1;
      const id = idCounts[baseId] > 1 ? `${baseId}-${idCounts[baseId]}` : baseId;
      items.push({ id, text, level });
    }
  }
  return items;
}

function renderMarkdownWithIds(text) {
  if (!text) return '';
  const idCounts = {};
  const makeId = (t) => {
    let baseId = t.replace(/\*\*/g, '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
    idCounts[baseId] = (idCounts[baseId] || 0) + 1;
    return idCounts[baseId] > 1 ? `${baseId}-${idCounts[baseId]}` : baseId;
  };
  let html = text
    .replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^#### (.+)$/gm, (_, t) => {
      return `<h4 id="${makeId(t)}" class="text-base font-semibold text-white mt-6 mb-3">${t}</h4>`;
    })
    .replace(/^### (.+)$/gm, (_, t) => {
      return `<h3 id="${makeId(t)}" class="text-lg font-semibold text-white mt-8 mb-3">${t}</h3>`;
    })
    .replace(/^## (.+)$/gm, (_, t) => {
      return `<h2 id="${makeId(t)}" class="text-xl font-bold text-white mt-10 mb-4 pb-2 border-b border-white/10">${t}</h2>`;
    })
    .replace(/^# (.+)$/gm, (_, t) => {
      return `<h2 id="${makeId(t)}" class="text-2xl font-bold text-white mt-10 mb-5">${t}</h2>`;
    })
    .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^---$/gm, '<hr class="border-white/10 my-8" />')
    .replace(/^- (.+)$/gm, '<li class="ml-4 mb-1.5 text-gray-300 list-disc leading-relaxed">$1</li>')
    .replace(/^(\d+)\. (.+)$/gm, '<li class="ml-4 mb-1.5 text-gray-300 list-decimal leading-relaxed" value="$1">$2</li>')
    .replace(/`([^`]+)`/g, '<code class="bg-white/10 text-purple-300 px-1.5 py-0.5 rounded text-sm font-mono">$1</code>')
    .replace(/\n\n/g, '</p><p class="text-gray-300 leading-[1.8] mb-4 text-[15px]">')
    .replace(/\n/g, '<br/>');
  return sanitizeHtml(`<p class="text-gray-300 leading-[1.8] mb-4 text-[15px]">${html}</p>`);
}

function ReadingProgressBar() {
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    const onScroll = () => {
      const scrollTop = window.scrollY;
      const docHeight = document.documentElement.scrollHeight - window.innerHeight;
      if (docHeight > 0) setProgress(Math.min((scrollTop / docHeight) * 100, 100));
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  return (
    <div className="fixed top-0 left-0 right-0 z-50 h-0.5" style={{ background: 'rgba(255,255,255,0.03)' }}>
      <div
        className="h-full transition-[width] duration-100"
        style={{ width: `${progress}%`, background: 'linear-gradient(90deg, #7c3aed, #8b5cf6, #a78bfa)' }}
      />
    </div>
  );
}

const SidebarTOC = ({ items, activeId }) => {
  if (!items || items.length < 2) return null;
  return (
    <nav className="hidden xl:block sticky top-24 w-56 shrink-0 self-start" aria-label="Table of Contents">
      <div className="text-[11px] font-bold uppercase tracking-wider text-gray-500 mb-3 px-3">On this page</div>
      <div className="space-y-0.5 max-h-[calc(100vh-8rem)] overflow-y-auto pr-2">
        {items.map((item) => (
          <a
            key={item.id}
            href={`#${item.id}`}
            className="block text-[13px] py-1 px-3 rounded-md transition-all duration-150"
            style={{
              paddingLeft: item.level >= 3 ? '1.5rem' : item.level === 2 ? '0.75rem' : '0.75rem',
              color: activeId === item.id ? 'rgb(167,139,250)' : item.level <= 2 ? 'rgba(255,255,255,0.55)' : 'rgba(255,255,255,0.35)',
              background: activeId === item.id ? 'rgba(139,92,246,0.08)' : 'transparent',
              fontWeight: activeId === item.id ? 600 : 400,
              borderLeft: activeId === item.id ? '2px solid rgb(139,92,246)' : '2px solid transparent',
            }}
          >
            {item.text}
          </a>
        ))}
      </div>
    </nav>
  );
};

const MobileTOC = ({ items }) => {
  const [isOpen, setIsOpen] = useState(false);
  if (!items || items.length < 2) return null;
  return (
    <div className="xl:hidden mb-6">
      <button
        onClick={() => setIsOpen((v) => !v)}
        className="flex items-center gap-2 w-full px-4 py-3 rounded-xl bg-white/[0.04] border border-white/10 hover:border-purple-500/30 transition-colors text-sm text-gray-300"
        aria-expanded={isOpen}
      >
        <List size={16} className="text-purple-400" />
        <span className="font-medium text-white">Table of Contents</span>
        <span className="text-xs text-gray-500 ml-auto">{items.length} sections</span>
        <ChevronDown
          size={14}
          className="transition-transform duration-200"
          style={{ transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)' }}
        />
      </button>
      {isOpen && (
        <nav className="mt-2 rounded-xl bg-white/[0.03] border border-white/5 p-4 space-y-1">
          {items.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              onClick={() => setIsOpen(false)}
              className="block text-sm py-1 hover:text-purple-400 transition-colors"
              style={{
                paddingLeft: item.level >= 3 ? '1.25rem' : '0',
                color: item.level <= 2 ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.45)',
              }}
            >
              {item.text}
            </a>
          ))}
        </nav>
      )}
    </div>
  );
};

export default function SeoTopicPage() {
  const { board, classSlug, subjectSlug, topicSlug, pageType } = useParams();
  const navigate = useNavigate();
  const currentType = pageType || 'notes';
  const articleRef = useRef(null);

  const [page, setPage] = useState(null);
  const [pageTypes, setPageTypes] = useState([]);
  const [related, setRelated] = useState({ related: [], prev: null, next: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeHeadingId, setActiveHeadingId] = useState('');

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
      .catch(async (err) => {
        if (cancelled) return;
        if (err.response?.status === 404 && currentType === 'notes') {
          try {
            const fallbackRes = await getChapterBySlug(board, classSlug, subjectSlug, topicSlug);
            if (!cancelled) {
              setPage(fallbackRes.data);
              setPageTypes([]);
              setRelated({ related: [], prev: null, next: null });
            }
          } catch {
            if (!cancelled) setError('Page not found');
          }
        } else {
          setError(err.response?.status === 404 ? 'Page not found' : 'Failed to load content');
        }
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [board, classSlug, subjectSlug, topicSlug, currentType]);

  const tocItems = useMemo(() => extractTocItems(page?.content), [page?.content]);

  useEffect(() => {
    if (!tocItems.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveHeadingId(entry.target.id);
          }
        }
      },
      { rootMargin: '-80px 0px -70% 0px', threshold: 0 }
    );
    const headings = document.querySelectorAll('article h1[id], article h2[id], article h3[id], article h4[id]');
    headings.forEach((h) => observer.observe(h));
    return () => observer.disconnect();
  }, [tocItems, page]);

  useEffect(() => {
    if (!page) return;
    const pageUrl = `https://syrabit.ai/${board}/${classSlug}/${subjectSlug}/${topicSlug}${currentType !== 'notes' ? `/${currentType}` : ''}`;

    const graphNodes = [
      {
        '@type': 'Article',
        headline: page.title,
        description: page.meta_description,
        author: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
        publisher: {
          '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai',
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
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://syrabit.ai' },
          { '@type': 'ListItem', position: 2, name: 'Library', item: 'https://syrabit.ai/library' },
          { '@type': 'ListItem', position: 3, name: page.subject_name || subjectSlug, item: `https://syrabit.ai/${board}/${classSlug}/${subjectSlug}` },
          { '@type': 'ListItem', position: 4, name: page.topic_title || topicSlug, item: pageUrl },
        ],
      },
      {
        '@type': 'Course',
        name: `${page.topic_title || topicSlug} — ${page.class_name || ''} ${page.board_name || ''}`.trim(),
        description: page.meta_description || page.summary || '',
        provider: { '@type': 'Organization', name: 'Syrabit.ai', sameAs: 'https://syrabit.ai' },
        educationalLevel: `${page.class_name || ''} ${page.board_name || ''}`.trim(),
        url: pageUrl,
        inLanguage: 'en-IN',
      },
    ];

    let faqMainEntity = [];
    if (Array.isArray(page.qa_pairs) && page.qa_pairs.length > 0) {
      faqMainEntity = page.qa_pairs.map((q) => ({
        '@type': 'Question', name: q.question,
        acceptedAnswer: { '@type': 'Answer', text: q.answer },
      }));
    } else if (['important-questions', 'mcqs'].includes(currentType) && page.content) {
      const lines = page.content.split('\n').filter(Boolean);
      let currentQ = null;
      for (const line of lines) {
        const stripped = line.replace(/^#+\s*/, '').replace(/^\*\*/, '').replace(/\*\*$/, '').trim();
        if (line.match(/^[#*]/) && stripped.endsWith('?')) { currentQ = stripped; }
        else if (currentQ && stripped.length > 10) {
          faqMainEntity.push({ '@type': 'Question', name: currentQ, acceptedAnswer: { '@type': 'Answer', text: stripped } });
          currentQ = null;
          if (faqMainEntity.length >= 10) break;
        }
      }
    }
    if (faqMainEntity.length >= 2) graphNodes.push({ '@type': 'FAQPage', mainEntity: faqMainEntity });

    const existing = document.getElementById('seo-topic-graph');
    if (existing) existing.remove();
    const s = document.createElement('script');
    s.type = 'application/ld+json';
    s.id = 'seo-topic-graph';
    s.text = JSON.stringify({ '@context': 'https://schema.org', '@graph': graphNodes });
    document.head.appendChild(s);
    return () => { const el = document.getElementById('seo-topic-graph'); if (el) el.remove(); };
  }, [page, board, classSlug, subjectSlug, topicSlug, currentType]);

  const basePath = `/${board}/${classSlug}/${subjectSlug}/${topicSlug}`;
  const subjectPath = `/${board}/${classSlug}/${subjectSlug}`;
  const canonicalUrl = `https://syrabit.ai${basePath}${currentType !== 'notes' ? `/${currentType}` : ''}`;

  const readTimeMin = useMemo(() => {
    if (!page?.word_count) return 0;
    return Math.max(1, Math.ceil(page.word_count / 200));
  }, [page?.word_count]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a1a] text-white">
        <ReadingProgressBar />
        <div className="max-w-4xl mx-auto px-4 py-8">
          <Skeleton className="h-4 w-48 mb-6 bg-white/5" />
          <Skeleton className="h-8 w-full mb-4 bg-white/5" />
          <Skeleton className="h-4 w-64 mb-2 bg-white/5" />
          <div className="flex gap-2 mb-8">
            {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-9 w-24 rounded-lg bg-white/5" />)}
          </div>
          <Skeleton className="h-96 w-full rounded-2xl bg-white/5" />
        </div>
      </div>
    );
  }

  if (error || !page) {
    return (
      <div className="min-h-screen bg-[#0a0a1a] text-white flex items-center justify-center">
        <div className="text-center max-w-md px-6">
          <div className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mx-auto mb-5">
            <BookOpen size={28} className="text-gray-500" />
          </div>
          <h1 className="text-2xl font-bold mb-3">{error || 'Page not found'}</h1>
          <p className="text-gray-400 mb-6">The study material you're looking for hasn't been generated yet.</p>
          <Link to="/library" className="inline-flex items-center gap-2 px-6 py-3 bg-purple-600 hover:bg-purple-700 rounded-xl text-white font-medium transition-colors">
            <BookOpen size={16} />
            Browse Library
          </Link>
        </div>
      </div>
    );
  }

  const boardShort = (page.board_name || board).toUpperCase();
  const pageTypeLabel = currentType === 'notes' ? 'Notes' : currentType === 'important-questions' ? 'Important Questions' : currentType === 'mcqs' ? 'MCQ Practice' : currentType === 'definition' ? 'Definition & Meaning' : 'Examples & Solutions';

  return (
    <div className="min-h-screen bg-[#0a0a1a] text-white">
      <ReadingProgressBar />
      <PageMeta
        title={page.title}
        description={page.meta_description}
        url={canonicalUrl}
        type="article"
        section={page.subject_name}
        keywords={[
          page.topic_title, `${page.topic_title} notes`, `${page.topic_title} ${boardShort}`,
          page.subject_name, page.board_name, page.class_name, 'AHSEC',
        ].filter(Boolean).join(', ')}
        tags={[page.topic_title, page.subject_name, page.board_name].filter(Boolean)}
        publishedTime={page.generated_at}
        modifiedTime={page.updated_at || page.generated_at}
      />

      {/* Header */}
      <header
        className="border-b border-white/5"
        style={{ background: 'rgba(10,10,26,0.95)', backdropFilter: 'blur(12px)' }}
      >
        <div className="max-w-6xl mx-auto px-4 py-4">
          <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm text-gray-400 mb-4 flex-wrap">
            <Link to="/" className="hover:text-purple-400 transition-colors flex items-center gap-1">
              <Home size={13} /> Home
            </Link>
            <ChevronRight size={11} className="text-gray-600" />
            <Link to="/library" className="hover:text-purple-400 transition-colors">Library</Link>
            <ChevronRight size={11} className="text-gray-600" />
            <Link to={subjectPath} className="hover:text-purple-400 transition-colors">{page.subject_name}</Link>
            <ChevronRight size={11} className="text-gray-600" />
            <span className="text-white/80 font-medium truncate max-w-[200px]">{page.topic_title}</span>
          </nav>

          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <Badge variant="outline" className="text-[11px] text-purple-400 border-purple-500/25 bg-purple-500/5">{page.board_name}</Badge>
            <Badge variant="outline" className="text-[11px] text-blue-400 border-blue-500/25 bg-blue-500/5">{page.class_name}</Badge>
            <Badge variant="outline" className="text-[11px] text-emerald-400 border-emerald-500/25 bg-emerald-500/5">{page.subject_name}</Badge>
          </div>

          <h1 className="text-2xl md:text-3xl lg:text-4xl font-bold text-white leading-tight max-w-3xl">
            {page.topic_title}
          </h1>

          <div className="flex items-center gap-3 mt-3 text-sm text-gray-400 flex-wrap">
            <span className="flex items-center gap-1">
              <Clock size={13} />
              {readTimeMin} min read
            </span>
            <span className="text-gray-600">·</span>
            <span>{page.word_count?.toLocaleString()} words</span>
            <span className="text-gray-600">·</span>
            <span>{pageTypeLabel}</span>
            <span className="text-gray-600">·</span>
            <span>{page.chapter_title}</span>
            {page.updated_at && (
              <>
                <span className="text-gray-600">·</span>
                <span>Updated {new Date(page.updated_at || page.generated_at).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' })}</span>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Content type tabs — hidden for fallback pages with no SEO types */}
      {(!page?.is_fallback || pageTypes.length > 0) && (
      <div className="border-b border-white/5" style={{ background: 'rgba(10,10,26,0.8)' }}>
        <div className="max-w-6xl mx-auto px-4">
          <div className="flex gap-1 overflow-x-auto py-2" role="tablist" aria-label="Content type tabs">
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
                  className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-all ${
                    isActive
                      ? 'bg-purple-600 text-white shadow-lg shadow-purple-500/20'
                      : 'text-gray-400 hover:bg-white/5 hover:text-white'
                  }`}
                >
                  <Icon size={14} />
                  {meta.label}
                </Link>
              ) : (
                <span key={type} className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap text-gray-600 cursor-not-allowed">
                  <Icon size={14} />
                  {meta.label}
                </span>
              );
            })}
          </div>
        </div>
      </div>
      )}

      {/* Main layout: sidebar TOC + article */}
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex gap-8 items-start">
          <SidebarTOC items={tocItems} activeId={activeHeadingId} />

          <div className="flex-1 min-w-0 max-w-3xl">
            <MobileTOC items={tocItems} />

            <article
              ref={articleRef}
              className="rounded-2xl border border-white/5 p-6 md:p-10"
              style={{ background: 'rgba(255,255,255,0.02)' }}
            >
              <div
                className="article-content"
                dangerouslySetInnerHTML={{ __html: renderMarkdownWithIds(page.content) }}
              />
            </article>

            {/* Board exam tips */}
            <div className="mt-8 bg-amber-500/5 border border-amber-500/15 rounded-2xl p-6">
              <div className="flex items-center gap-2 mb-3">
                <Lightbulb size={16} className="text-amber-400" />
                <h2 className="text-white font-semibold text-base">
                  {boardShort} Board Exam Tips for {page.topic_title}
                </h2>
              </div>
              <ul className="space-y-2 text-gray-400 text-sm leading-relaxed">
                <li className="flex items-start gap-2">
                  <span className="text-amber-400 mt-0.5">•</span>
                  <span>This topic is part of <strong className="text-gray-300">{page.chapter_title}</strong> in {boardShort} {page.class_name} {page.subject_name} syllabus.</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-amber-400 mt-0.5">•</span>
                  <span>Study the <Link to={`${basePath}/important-questions`} className="text-purple-400 hover:underline">important questions</Link> and <Link to={`${basePath}/mcqs`} className="text-purple-400 hover:underline">MCQs</Link> to prepare for your exam.</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-amber-400 mt-0.5">•</span>
                  <span>Use the <Link to="/chat" className="text-purple-400 hover:underline">AI Chat</Link> to ask any question about {page.topic_title}.</span>
                </li>
              </ul>
            </div>

            {/* More study material */}
            {pageTypes.filter(p => p.page_type !== currentType).length > 0 && (
              <div className="mt-6 bg-white/[0.025] border border-white/5 rounded-2xl p-6">
                <div className="flex items-center gap-2 mb-4">
                  <GraduationCap size={16} className="text-blue-400" />
                  <h2 className="text-white font-semibold text-base">
                    More on {page.topic_title}
                  </h2>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {[
                    { type: 'notes', label: 'Notes' },
                    { type: 'definition', label: 'Definition' },
                    { type: 'important-questions', label: 'Important Questions' },
                    { type: 'mcqs', label: 'MCQs' },
                    { type: 'examples', label: 'Examples' },
                  ].filter(({ type }) => type !== currentType && pageTypes.some(p => p.page_type === type)).map(({ type, label }) => {
                    const Icon = PAGE_TYPE_META[type]?.icon;
                    return (
                      <Link
                        key={type}
                        to={type === 'notes' ? basePath : `${basePath}/${type}`}
                        className="flex items-center gap-2 px-4 py-3 rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-sm text-gray-400 hover:text-white"
                      >
                        {Icon && <Icon size={14} />}
                        <span>{label}</span>
                        <ChevronRight size={12} className="ml-auto text-gray-600" />
                      </Link>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Prev/Next navigation */}
            {(related.prev || related.next) && (
              <div className="flex justify-between items-stretch mt-8 gap-4">
                {related.prev ? (
                  <Link
                    to={related.prev.seo_path || '#'}
                    className="flex items-center gap-3 px-5 py-4 rounded-2xl bg-white/[0.03] border border-white/5 hover:bg-white/[0.06] hover:border-purple-500/20 transition-all text-sm text-gray-300 hover:text-white group flex-1"
                  >
                    <ArrowLeft size={18} className="group-hover:-translate-x-1 transition-transform text-gray-500 shrink-0" />
                    <div className="text-left min-w-0">
                      <div className="text-[11px] text-gray-500 mb-0.5">Previous</div>
                      <div className="font-medium truncate">{related.prev.title}</div>
                    </div>
                  </Link>
                ) : <div className="flex-1" />}
                {related.next ? (
                  <Link
                    to={related.next.seo_path || '#'}
                    className="flex items-center gap-3 px-5 py-4 rounded-2xl bg-white/[0.03] border border-white/5 hover:bg-white/[0.06] hover:border-purple-500/20 transition-all text-sm text-gray-300 hover:text-white group flex-1 text-right justify-end"
                  >
                    <div className="min-w-0">
                      <div className="text-[11px] text-gray-500 mb-0.5">Next</div>
                      <div className="font-medium truncate">{related.next.title}</div>
                    </div>
                    <ArrowRight size={18} className="group-hover:translate-x-1 transition-transform text-gray-500 shrink-0" />
                  </Link>
                ) : <div className="flex-1" />}
              </div>
            )}

            {/* Related topics */}
            {related.related?.length > 0 && (
              <div className="mt-8 bg-white/[0.025] rounded-2xl border border-white/5 p-6">
                <div className="flex items-center gap-2 mb-4">
                  <BookOpen size={16} className="text-purple-400" />
                  <h2 className="text-lg font-bold text-white">
                    Related {page.subject_name} Topics
                  </h2>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {related.related.map((t) => (
                    <Link
                      key={t.id}
                      to={t.seo_path || '#'}
                      className="flex items-center gap-3 px-4 py-3 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/5 hover:border-purple-500/15 transition-all group"
                    >
                      <BookOpen size={14} className="text-purple-400/60 shrink-0" />
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-gray-300 group-hover:text-white transition-colors truncate">{t.title}</div>
                        <div className="text-xs text-gray-500">{page.subject_name}</div>
                      </div>
                      <ChevronRight size={12} className="ml-auto text-gray-600 shrink-0" />
                    </Link>
                  ))}
                </div>
              </div>
            )}

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
            <div className="mt-8 rounded-2xl p-6 flex flex-col sm:flex-row items-center gap-4" style={{ background: 'linear-gradient(135deg, rgba(124,58,237,0.08), rgba(139,92,246,0.04))', border: '1px solid rgba(139,92,246,0.15)' }}>
              <div className="flex-1 text-center sm:text-left">
                <div className="flex items-center gap-2 justify-center sm:justify-start mb-1">
                  <Sparkles size={16} className="text-violet-400" />
                  <span className="text-violet-400 text-sm font-semibold">Study with AI</span>
                </div>
                <p className="text-gray-300 text-sm leading-relaxed">
                  Got questions about <strong className="text-white">{page.topic_title}</strong>? Ask our AI tutor for instant, {boardShort}-aligned answers.
                </p>
              </div>
              <Link
                to="/chat"
                className="shrink-0 px-6 py-2.5 bg-purple-600 hover:bg-purple-500 text-white rounded-xl text-sm font-medium transition-colors flex items-center gap-2"
              >
                <Sparkles size={14} />
                Ask AI Tutor
              </Link>
            </div>

            {/* Footer */}
            <nav className="mt-10 pt-6 border-t border-white/5" aria-label="Site navigation">
              <div className="flex flex-wrap gap-4 justify-center text-xs text-gray-500">
                <Link to="/" className="hover:text-purple-400 transition-colors">Home</Link>
                <Link to="/library" className="hover:text-purple-400 transition-colors">Study Library</Link>
                <Link to="/pricing" className="hover:text-purple-400 transition-colors">Plans & Pricing</Link>
                <Link to="/signup" className="hover:text-purple-400 transition-colors">Get Started Free</Link>
                <Link to="/chat" className="hover:text-purple-400 transition-colors">AI Tutor</Link>
              </div>
              <p className="text-center text-xs text-gray-600 mt-3">
                Syrabit.ai — AI-powered exam prep for Assam Board students
              </p>
            </nav>
          </div>
        </div>
      </div>
    </div>
  );
}
