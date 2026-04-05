import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import {
  BookOpen, ArrowLeft, ChevronRight, Home, Share2,
  Clock, Hash, Sparkles, Loader2, FileText, HelpCircle, ChevronDown,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { apiClient } from '@/utils/api';
import { useShare, SerpPreviewModal } from '@/hooks/useShare';

function ChapterJsonLd({ data, url, basePath }) {
  useEffect(() => {
    if (!data) return;
    const subjectName = data.subject_name || '';
    const boardName = data.board_name || '';
    const className = data.class_name || '';
    const chapterTitle = data.topic_title || data.chapter_title || '';
    const graphNodes = [
      {
        '@type': 'Article',
        headline: data.title,
        description: data.meta_description,
        url,
        author: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
        publisher: {
          '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai',
          logo: { '@type': 'ImageObject', url: 'https://syrabit.ai/icons/icon-192x192.png' },
        },
        datePublished: data.generated_at || new Date().toISOString(),
        dateModified: data.updated_at || data.generated_at || new Date().toISOString(),
        educationalLevel: `${className} ${boardName}`.trim(),
        about: { '@type': 'Thing', name: chapterTitle },
        wordCount: data.word_count || 0,
        inLanguage: 'en-IN',
        mainEntityOfPage: { '@type': 'WebPage', '@id': url },
        image: 'https://syrabit.ai/opengraph.jpg',
      },
      {
        '@type': 'LearningResource',
        name: chapterTitle,
        description: data.meta_description,
        educationalLevel: `${className} ${boardName}`.trim(),
        learningResourceType: 'Study Notes',
        provider: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
        inLanguage: 'en-IN',
        url,
      },
      {
        '@type': 'BreadcrumbList',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://syrabit.ai/' },
          { '@type': 'ListItem', position: 2, name: 'Library', item: 'https://syrabit.ai/library' },
          { '@type': 'ListItem', position: 3, name: subjectName, item: `https://syrabit.ai${basePath}` },
          { '@type': 'ListItem', position: 4, name: chapterTitle, item: url },
        ],
      },
    ];
    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.id = 'chapter-jsonld';
    script.text = JSON.stringify({ '@context': 'https://schema.org', '@graph': graphNodes });
    document.getElementById('chapter-jsonld')?.remove();
    document.head.appendChild(script);
    return () => document.getElementById('chapter-jsonld')?.remove();
  }, [data, url]);
  return null;
}

function StickyToc({ headings, activeId }) {
  if (headings.length < 2) return null;
  return (
    <nav className="sticky top-20 w-56 shrink-0 hidden xl:block self-start" aria-label="Table of contents">
      <p className="text-[11px] font-semibold uppercase tracking-wider mb-3" style={{ color: 'rgba(255,255,255,0.30)' }}>
        On this page
      </p>
      <ul className="space-y-0.5">
        {headings.map(h => (
          <li key={h.id}>
            <a
              href={`#${h.id}`}
              className={`block py-1 text-[12px] leading-snug transition-colors rounded ${
                h.level === 3 ? 'pl-4' : 'pl-0'
              } ${
                activeId === h.id
                  ? 'text-violet-400 font-medium'
                  : 'text-white/40 hover:text-white/70'
              }`}
              style={{ borderLeft: h.level === 2 ? (activeId === h.id ? '2px solid #9575e0' : '2px solid transparent') : 'none' }}
              onClick={e => {
                e.preventDefault();
                document.getElementById(h.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
            >
              {h.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function ImportantQuestions({ chapterTitle, pyqData }) {
  const [expandedMark, setExpandedMark] = useState(null);
  if (!pyqData || pyqData.total === 0) return null;

  const markWise = pyqData.mark_wise || {};
  const sortedMarks = Object.keys(markWise).sort((a, b) => Number(a) - Number(b));
  const flatPyqs = pyqData.pyqs || [];

  const hasMW = sortedMarks.length > 0 && sortedMarks.some(m => (markWise[m] || []).length > 0);

  return (
    <div className="chapter-textbook rounded-2xl p-5 sm:p-8 mt-6">
      <div className="flex items-center gap-2 mb-4">
        <HelpCircle size={20} className="text-purple-600" />
        <h2 className="text-xl font-bold text-gray-900" style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", border: 'none', margin: 0, padding: 0 }}>
          Important Questions
        </h2>
      </div>
      <p className="text-sm text-gray-500 mb-5" style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" }}>
        Previous year and expected questions for {chapterTitle} ({pyqData.total} questions)
      </p>

      {hasMW ? (
        <div className="space-y-3">
          {sortedMarks.map(mark => {
            const questions = markWise[mark] || [];
            if (questions.length === 0) return null;
            const isOpen = expandedMark === mark;
            return (
              <div key={mark} className="border border-gray-200 rounded-xl overflow-hidden">
                <button
                  onClick={() => setExpandedMark(isOpen ? null : mark)}
                  className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                  style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" }}
                >
                  <div className="flex items-center gap-3">
                    <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-sm font-bold text-white"
                      style={{ background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)' }}
                    >
                      {mark}
                    </span>
                    <span className="font-semibold text-gray-800">{mark}-Mark Questions</span>
                    <span className="text-xs text-gray-400">({questions.length})</span>
                  </div>
                  <ChevronDown size={16} className={`text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                </button>
                {isOpen && (
                  <div className="px-4 pb-4 pt-1">
                    <ol className="space-y-2" style={{ color: '#333', listStyle: 'decimal', paddingLeft: '1.25rem' }}>
                      {questions.map((q, i) => {
                        const qText = typeof q === 'string' ? q : q.question || q.text || JSON.stringify(q);
                        return (
                          <li key={i} className="text-sm leading-relaxed text-gray-700 pl-1">
                            {qText}
                          </li>
                        );
                      })}
                    </ol>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : flatPyqs.length > 0 ? (
        <ol className="space-y-2" style={{ color: '#333', listStyle: 'decimal', paddingLeft: '1.25rem' }}>
          {flatPyqs.map((q, i) => {
            const qText = typeof q === 'string' ? q : q.question || q.text || JSON.stringify(q);
            const marks = q.marks;
            return (
              <li key={i} className="text-sm leading-relaxed text-gray-700 pl-1">
                {qText}
                {marks && (
                  <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
                    {marks}M
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      ) : null}
    </div>
  );
}

export default function ChapterPage() {
  const { board, classSlug, subjectSlug, chapterSlug } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [pyqData, setPyqData] = useState(null);
  const articleRef = useRef(null);
  const [activeId, setActiveId] = useState('');
  const { sharing, share, serpPreview, confirmShare, dismissPreview } = useShare();

  useEffect(() => {
    if (!board || !classSlug || !subjectSlug || !chapterSlug) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiClient()
      .get(`/content/chapter-by-slug/${board}/${classSlug}/${subjectSlug}/${chapterSlug}`)
      .then(r => { if (!cancelled) setData(r.data); })
      .catch(e => { if (!cancelled) setError(e.response?.status === 404 ? 'Chapter not found' : 'Failed to load chapter'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [board, classSlug, subjectSlug, chapterSlug]);

  useEffect(() => {
    setPyqData(null);
    if (!data?.chapter_id) return;
    let cancelled = false;
    apiClient()
      .get(`/content/chapters/${data.chapter_id}/topic-pyqs?limit=50`)
      .then(r => { if (!cancelled) setPyqData(r.data); })
      .catch(() => { if (!cancelled) setPyqData(null); });
    return () => { cancelled = true; };
  }, [data?.chapter_id]);

  const headings = useMemo(() => {
    if (!data?.content) return [];
    const lines = data.content.split('\n');
    const result = [];
    for (const line of lines) {
      const m2 = line.match(/^## (.+)/);
      const m3 = line.match(/^### (.+)/);
      if (m2) {
        const text = m2[1].replace(/\*\*/g, '').trim();
        const id = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
        result.push({ level: 2, text, id });
      } else if (m3) {
        const text = m3[1].replace(/\*\*/g, '').trim();
        const id = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
        result.push({ level: 3, text, id });
      }
    }
    return result;
  }, [data?.content]);

  useEffect(() => {
    if (!articleRef.current || headings.length === 0) return;
    const observer = new IntersectionObserver(
      entries => {
        for (const entry of entries) {
          if (entry.isIntersecting) { setActiveId(entry.target.id); break; }
        }
      },
      { rootMargin: '-80px 0px -70% 0px', threshold: 0 }
    );
    const timer = setTimeout(() => {
      headings.forEach(h => {
        const el = document.getElementById(h.id);
        if (el) observer.observe(el);
      });
    }, 200);
    return () => { clearTimeout(timer); observer.disconnect(); };
  }, [headings, data]);

  useEffect(() => {
    if (loading || !data) return;
    const topicText = searchParams.get('topic') || searchParams.get('highlight') || window.location.hash.slice(1);
    if (!topicText) return;
    const decoded = decodeURIComponent(topicText).toLowerCase();
    const timer = setTimeout(() => {
      let el = null;
      const slugified = decoded.replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
      el = document.getElementById(slugified);
      if (!el) {
        const allH = articleRef.current?.querySelectorAll('h2[id], h3[id]') || [];
        for (const h of allH) {
          if (h.id.includes(slugified) || slugified.includes(h.id)) { el = h; break; }
        }
      }
      if (!el) {
        const contentTop = document.getElementById('chapter-content-top');
        if (contentTop) {
          const keywords = decoded.split(/\s+/).filter(w => w.length > 2);
          if (keywords.length > 0) {
            const allBlocks = contentTop.querySelectorAll('p, li, h2, h3, h4, strong, td');
            let bestEl = null;
            let bestScore = 0;
            for (const block of allBlocks) {
              const text = block.textContent.toLowerCase();
              const score = keywords.reduce((s, kw) => s + (text.includes(kw) ? 1 : 0), 0);
              if (score > bestScore) { bestScore = score; bestEl = block; }
            }
            if (bestEl && bestScore >= Math.min(2, keywords.length)) {
              el = bestEl;
            }
          }
          if (!el) {
            const firstChild = contentTop.querySelector('h1, h2, h3, p');
            el = firstChild || contentTop;
          }
        }
      }
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('highlight-active');
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev);
          next.delete('topic');
          next.delete('highlight');
          return next;
        }, { replace: true });
      }
    }, 400);
    return () => clearTimeout(timer);
  }, [loading, data, searchParams]);

  const basePath = `/${board}/${classSlug}/${subjectSlug}`;
  const canonical = `https://syrabit.ai${basePath}/${chapterSlug}`;
  const readMins = data?.word_count ? Math.max(1, Math.ceil(data.word_count / 200)) : null;

  const handleShare = useCallback(() => {
    share(data?.title || chapterSlug, `${basePath}/${chapterSlug}`, {
      showSerpPreview: true,
      description: data?.meta_description || '',
    });
  }, [data?.title, data?.meta_description, chapterSlug, basePath, share]);

  const markdownComponents = useMemo(() => {
    const extractText = (node) => {
      if (typeof node === 'string') return node;
      if (Array.isArray(node)) return node.map(extractText).join('');
      if (node?.props?.children) return extractText(node.props.children);
      return '';
    };
    const toId = (children) => extractText(children).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
    return {
      h2: ({ children, ...props }) => <h2 id={toId(children)} className="scroll-mt-20" {...props}>{children}</h2>,
      h3: ({ children, ...props }) => <h3 id={toId(children)} className="scroll-mt-20" {...props}>{children}</h3>,
    };
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a1a] text-white">
        <div className="max-w-4xl mx-auto px-4 py-8">
          <Skeleton className="h-4 w-48 mb-6 bg-white/5" />
          <Skeleton className="h-10 w-full mb-4 bg-white/5" />
          <Skeleton className="h-4 w-64 mb-8 bg-white/5" />
          {[...Array(8)].map((_, i) => (
            <Skeleton key={i} className="h-5 w-full mb-3 bg-white/5" style={{ width: `${60 + (i % 3) * 15}%` }} />
          ))}
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-[#0a0a1a] text-white flex items-center justify-center">
        <div className="text-center max-w-md px-6">
          <div className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mx-auto mb-5">
            <BookOpen size={28} className="text-gray-500" />
          </div>
          <h1 className="text-2xl font-bold mb-3">{error || 'Chapter not found'}</h1>
          <p className="text-gray-400 mb-6">This chapter may not be available yet or the URL may be incorrect.</p>
          <Link to={basePath} className="inline-flex items-center gap-2 px-6 py-3 bg-purple-600 hover:bg-purple-700 rounded-xl text-white font-medium transition-colors">
            <ArrowLeft size={16} /> Back to Subject
          </Link>
        </div>
      </div>
    );
  }

  const chapterTitle = data.topic_title || data.chapter_title || chapterSlug;
  const subjectName = data.subject_name || subjectSlug;
  const boardName = data.board_name || board;
  const className = data.class_name || classSlug;
  const streamName = data.stream_name || '';

  const seoTitle = `${chapterTitle} — ${subjectName} | ${boardName} ${className} Notes`;
  const seoDesc = data.meta_description || `${chapterTitle} notes for ${subjectName}. Complete study material for ${boardName} ${className} students.`;

  return (
    <div className="min-h-screen bg-[#0a0a1a] text-white">
      <PageMeta
        title={seoTitle}
        description={seoDesc}
        url={canonical}
        keywords={`${chapterTitle}, ${subjectName}, ${boardName} notes, ${className} study material, AHSEC, SEBA, exam preparation`}
      />
      <ChapterJsonLd data={data} url={canonical} basePath={basePath} />

      <header className="border-b border-white/5" style={{ background: 'rgba(10,10,26,0.95)', backdropFilter: 'blur(12px)' }}>
        <div className="max-w-4xl mx-auto px-4 py-5">
          <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm text-gray-400 mb-4 flex-wrap">
            <Link to="/" className="hover:text-purple-400 transition-colors flex items-center gap-1">
              <Home size={13} /> Home
            </Link>
            <ChevronRight size={11} className="text-gray-600" />
            <Link to="/library" className="hover:text-purple-400 transition-colors">Browser</Link>
            <ChevronRight size={11} className="text-gray-600" />
            <Link to={basePath} className="hover:text-purple-400 transition-colors">{subjectName}</Link>
            <ChevronRight size={11} className="text-gray-600" />
            <span className="text-white/80 font-medium truncate max-w-[200px]">{chapterTitle}</span>
          </nav>

          <div className="flex items-start gap-3 sm:gap-4">
            <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl flex items-center justify-center shrink-0" style={{ background: 'linear-gradient(135deg, rgba(124,58,237,0.15), rgba(139,92,246,0.08))', border: '1px solid rgba(139,92,246,0.2)' }}>
              <FileText size={22} className="text-purple-400" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                <Badge variant="outline" className="text-[11px] text-purple-400 border-purple-500/25 bg-purple-500/5">{boardName}</Badge>
                <Badge variant="outline" className="text-[11px] text-blue-400 border-blue-500/25 bg-blue-500/5">{className}</Badge>
                {streamName && <Badge variant="outline" className="text-[11px] text-emerald-400 border-emerald-500/25 bg-emerald-500/5">{streamName}</Badge>}
              </div>
              <h1 className="text-xl sm:text-2xl md:text-3xl font-bold text-white leading-tight">
                {chapterTitle}
              </h1>
              {data.meta_description && (
                <p className="text-gray-400 mt-1.5 text-sm leading-relaxed max-w-2xl line-clamp-2">{data.meta_description}</p>
              )}
              <div className="flex items-center gap-3 mt-2.5 text-xs sm:text-sm text-gray-500">
                {readMins && (
                  <span className="flex items-center gap-1"><Clock size={12} />{readMins} min read</span>
                )}
                {data.word_count > 0 && (
                  <span>{data.word_count.toLocaleString()} words</span>
                )}
                {headings.length > 0 && (
                  <span className="flex items-center gap-1"><Hash size={12} />{headings.filter(h => h.level === 2).length} sections</span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 mt-4">
            <Link
              to={`/chat?subject=${subjectSlug}`}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all hover:opacity-90 active:scale-95"
              style={{ background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)', boxShadow: '0 2px 10px rgba(139,92,246,0.20)' }}
            >
              <Sparkles size={14} /> Ask AI
            </Link>
            <button
              onClick={handleShare}
              disabled={sharing}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-gray-300 transition-all hover:text-white hover:bg-white/5 active:scale-95 disabled:opacity-50"
              style={{ border: '1px solid rgba(255,255,255,0.1)' }}
            >
              {sharing ? <Loader2 size={14} className="animate-spin" /> : <Share2 size={14} />} Share
            </button>
          </div>
        </div>
      </header>

      <div className="max-w-4xl mx-auto px-4 py-6">
        <div className="flex gap-8">
          <article ref={articleRef} className="flex-1 min-w-0">
            <div
              id="chapter-content-top"
              className="chapter-textbook rounded-2xl p-5 sm:p-8 scroll-mt-20"
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeRaw]}
                components={markdownComponents}
              >
                {data.content}
              </ReactMarkdown>
            </div>

            <ImportantQuestions chapterTitle={chapterTitle} pyqData={pyqData} />

            <div className="mt-8 p-5 rounded-2xl" style={{ background: 'rgba(124,58,237,0.06)', border: '1px solid rgba(124,58,237,0.15)' }}>
              <p className="text-sm font-semibold text-purple-300 mb-1">Have a question about {chapterTitle}?</p>
              <p className="text-xs text-gray-400 mb-3">Get {boardName}-aligned answers instantly from Syra.</p>
              <Link
                to={`/chat?subject=${subjectSlug}`}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all hover:opacity-90"
                style={{ background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)' }}
              >
                <Sparkles size={14} /> Ask Syra about this
              </Link>
            </div>
          </article>

          <StickyToc headings={headings} activeId={activeId} />
        </div>

        <nav className="mt-10 pt-6 border-t border-white/5" aria-label="Site navigation">
          <div className="flex flex-wrap gap-4 justify-center text-xs text-gray-500">
            <Link to="/" className="hover:text-purple-400 transition-colors">Home</Link>
            <Link to="/library" className="hover:text-purple-400 transition-colors">Browser</Link>
            <Link to={basePath} className="hover:text-purple-400 transition-colors">{subjectName}</Link>
            <Link to="/pricing" className="hover:text-purple-400 transition-colors">Plans & Pricing</Link>
          </div>
          <p className="text-center text-xs text-gray-600 mt-3">
            Syrabit.ai — AI-powered exam prep for AssamBoard students (AHSEC · DEGREE · SEBA)
          </p>
        </nav>
      </div>
      <SerpPreviewModal preview={serpPreview} onConfirm={confirmShare} onDismiss={dismissPreview} />
    </div>
  );
}
