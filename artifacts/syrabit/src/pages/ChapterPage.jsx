import { useState, useEffect, useRef, useMemo, useCallback, lazy, Suspense } from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import {
  BookOpen, ArrowLeft, ChevronRight, Home, Share2, RefreshCw,
  Clock, Hash, Sparkles, FileText, HelpCircle, ChevronDown,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
const MarkdownRenderer = lazy(() => import('@/components/MarkdownRenderer'));
import { apiClient, seoRelatedByChapter } from '@/utils/api';
import { useShare, SerpPreviewModal } from '@/hooks/useShare';
import Analytics from '@/utils/analytics';
import { useContentLang } from '@/context/LanguageContext';
import StickyToc from '@/components/ui/StickyToc';
import ContinueLearning from '@/components/content/ContinueLearning';
import { useLibraryBundle, useLibraryBundleSlim } from '@/hooks/useContent';
import { findSiblingChapters, siblingsAsRelated } from '@/utils/siblingChapter';
import { pushRecentChapter } from '@/utils/recentChapters';

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
        about: (() => {
          const things = [{ '@type': 'Thing', name: chapterTitle }];
          const words = chapterTitle.split(/[\s,\-–—/&]+/).filter(w => w.length > 2);
          words.slice(0, 5).forEach(w => things.push({ '@type': 'Thing', name: w }));
          if (data.chapter_title) things.push({ '@type': 'Thing', name: data.chapter_title });
          return things.length > 1 ? things : things[0];
        })(),
        keywords: (() => {
          const words = chapterTitle.split(/[\s,\-–—/&]+/).filter(w => w.length > 2);
          const kws = [chapterTitle, subjectName, boardName, ...words,
            `${chapterTitle} notes`, `${chapterTitle} definition`, `${chapterTitle} MCQ`,
            `${chapterTitle} ${subjectName}`, `${chapterTitle} ${boardName} ${className}`];
          return [...new Set(kws.map(k => k.toLowerCase()))].join(', ');
        })(),
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
        teaches: chapterTitle,
        provider: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
        inLanguage: 'en-IN',
        isAccessibleForFree: true,
        url,
      },
      {
        '@type': 'WebPage',
        '@id': url,
        name: data.title,
        speakable: {
          '@type': 'SpeakableSpecification',
          cssSelector: ['article h1', 'article > p:first-of-type', 'article h2'],
        },
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

const _NON_TOPIC_RE = /^(key points|example|exam tip|key points for revision|summary)(\s|$)/i;
function filterTopicHeadings(headings) {
  if (headings.filter(h => h.level === 2).length >= 3) return headings.filter(h => h.level === 2);
  return headings.filter(h => {
    if (h.level === 2) return true;
    if (h.level !== 3) return false;
    const t = h.text.toLowerCase().replace(/[:\s\-]+$/g, '').trim();
    return !_NON_TOPIC_RE.test(t);
  });
}


function ImportantQuestions({ chapterTitle, pyqData }) {
  const [expandedMark, setExpandedMark] = useState(null);
  const { contentLang } = useContentLang();
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
          {contentLang === 'as' ? 'গুৰুত্বপূৰ্ণ প্ৰশ্নসমূহ' : 'Important Questions'}
        </h2>
      </div>
      <p className="text-sm text-gray-500 mb-5" style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" }}>
        {contentLang === 'as'
          ? `${chapterTitle} ৰ পূৰ্বৰ বছৰৰ আৰু প্ৰত্যাশিত প্ৰশ্ন (${pyqData.total} টা প্ৰশ্ন)`
          : `Previous year and expected questions for ${chapterTitle} (${pyqData.total} questions)`}
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

// Look up the chapter payload baked into the prerendered HTML by
// scripts/prerender-routes.mjs. On the server (SSR), entry-server.jsx
// stashes the payload on globalThis. On the client, the prerender
// script inlines `window.__CHAPTER_PRELOAD__` BEFORE the bootstrap
// module so it's available on the very first render — letting
// hydrateRoot match the SSR DOM without a skeleton flash. (Task #385)
function readChapterPreload(board, classSlug, subjectSlug, chapterSlug) {
  const matches = (p) =>
    p &&
    p.board === board &&
    p.classSlug === classSlug &&
    p.subjectSlug === subjectSlug &&
    p.chapterSlug === chapterSlug &&
    p.data;
  if (typeof window !== "undefined") {
    const p = window.__CHAPTER_PRELOAD__;
    if (matches(p)) return p.data;
  }
  if (typeof globalThis !== "undefined") {
    const p = globalThis.__SSR_CHAPTER_PRELOAD__;
    if (matches(p)) return p.data;
  }
  return null;
}

export default function ChapterPage() {
  const params = useParams();
  const board = params.board;
  const classSlug = params.classSlug;
  const hasStreamInUrl = !!(params.streamSlug && params.chapterSlug);
  const subjectSlug = hasStreamInUrl ? params.subjectSlug : params.subjectSlug;
  const chapterSlug = hasStreamInUrl ? params.chapterSlug : params.chapterSlug;
  const streamSlug = hasStreamInUrl ? params.streamSlug : null;
  const [searchParams, setSearchParams] = useSearchParams();
  const initialChapterData = useMemo(
    () => readChapterPreload(board, classSlug, subjectSlug, chapterSlug),
    [board, classSlug, subjectSlug, chapterSlug],
  );
  const [data, setData] = useState(initialChapterData);
  const [loading, setLoading] = useState(!initialChapterData);
  const [error, setError] = useState(null);
  const skipFirstFetchRef = useRef(!!initialChapterData);
  const [pyqData, setPyqData] = useState(null);
  const articleRef = useRef(null);
  const [activeId, setActiveId] = useState('');
  const [relatedChapterTopics, setRelatedChapterTopics] = useState([]);

  // Fetch related topics across the chapter for in-content internal links.
  useEffect(() => {
    let cancelled = false;
    if (!data?.chapter_id) { setRelatedChapterTopics([]); return; }
    seoRelatedByChapter(data.chapter_id, null, 6)
      .then((rows) => {
        if (cancelled) return;
        const list = Array.isArray(rows) ? rows : (rows?.related || rows?.items || []);
        setRelatedChapterTopics(Array.isArray(list) ? list : []);
      })
      .catch(() => { if (!cancelled) setRelatedChapterTopics([]); });
    return () => { cancelled = true; };
  }, [data?.chapter_id]);

  // Library bundle (slim then full) — used for sibling chapter prev/next.
  const { data: _slim } = useLibraryBundleSlim();
  const { data: _full } = useLibraryBundle(true);
  const _bundle = _full || _slim;

  // Track recently viewed chapters for the Library "Continue where you left off" rail.
  useEffect(() => {
    if (!data || !data.chapter_id) return;
    pushRecentChapter({
      path: `${`/${board}/${classSlug}${data.stream_slug ? '/' + data.stream_slug : ''}/${subjectSlug}`}/${chapterSlug}`,
      title: data.topic_title || data.chapter_title || chapterSlug,
      subject: data.subject_name || subjectSlug,
      board: data.board_name || board,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.chapter_id]);
  const { sharing, share, serpPreview, confirmShare, dismissPreview } = useShare();
  const { contentLang, switchLang } = useContentLang();

  useEffect(() => {
    if (!board || !classSlug || !subjectSlug || !chapterSlug) return;
    // Skip the first fetch when we hydrated with prerendered chapter
    // data — it already matches this URL (validated in
    // readChapterPreload). Subsequent SPA navigations refetch normally.
    if (skipFirstFetchRef.current) {
      skipFirstFetchRef.current = false;
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const apiPath = hasStreamInUrl
      ? `/content/chapter-by-slug/${board}/${classSlug}/${streamSlug}/${subjectSlug}/${chapterSlug}`
      : `/content/chapter-by-slug/${board}/${classSlug}/${subjectSlug}/${chapterSlug}`;
    apiClient()
      .get(apiPath)
      .then(r => { if (!cancelled) setData(r.data); })
      .catch(e => { if (!cancelled) setError(e.response?.status === 404 ? 'Chapter not found' : 'Failed to load chapter'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [board, classSlug, streamSlug, subjectSlug, chapterSlug, hasStreamInUrl]);

  useEffect(() => {
    if (!data) return;
    Analytics.chapterView(
      data.chapter_id,
      data.topic_title || data.chapter_title || chapterSlug,
      data.subject_name || subjectSlug,
      board,
      data.word_count || 0
    );
  }, [data?.chapter_id]);

  const scrollMilestonesRef = useRef(new Set());
  useEffect(() => {
    scrollMilestonesRef.current = new Set();
  }, [data?.chapter_id]);
  useEffect(() => {
    if (!data || !articleRef.current) return;
    const el = articleRef.current;
    const handler = () => {
      const rect = el.getBoundingClientRect();
      const scrolled = -rect.top;
      const total = rect.height - window.innerHeight;
      if (total <= 0) return;
      const pct = Math.min(100, Math.round((scrolled / total) * 100));
      const milestones = [25, 50, 75, 100];
      for (const m of milestones) {
        if (pct >= m && !scrollMilestonesRef.current.has(m)) {
          scrollMilestonesRef.current.add(m);
          Analytics.scrollDepth(m, data.topic_title || data.chapter_title || chapterSlug);
        }
      }
    };
    window.addEventListener('scroll', handler, { passive: true });
    return () => window.removeEventListener('scroll', handler);
  }, [data?.chapter_id]);

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

  const isQuestionPaper = data?.content_type === 'question_paper' || data?.content_type === 'pyq';
  const hasAssamese = isQuestionPaper ? false : (data?.has_assamese || false);
  const displayContent = useMemo(() => {
    if (!data) return '';
    if (isQuestionPaper) return data.content;
    return (contentLang === 'as' && hasAssamese) ? (data.content_as || data.content) : data.content;
  }, [data, contentLang, hasAssamese, isQuestionPaper]);

  const headings = useMemo(() => {
    if (!displayContent) return [];
    const lines = displayContent.split('\n');
    const result = [];
    const idCounts = {};
    for (const line of lines) {
      const m2 = line.match(/^## (.+)/);
      const m3 = line.match(/^### (.+)/);
      if (m2 || m3) {
        const level = m2 ? 2 : 3;
        const text = (m2 || m3)[1].replace(/\*\*/g, '').trim();
        const baseId = text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
        idCounts[baseId] = (idCounts[baseId] || 0) + 1;
        const id = idCounts[baseId] > 1 ? `${baseId}-${idCounts[baseId]}` : baseId;
        result.push({ level, text, id });
      }
    }
    return result;
  }, [displayContent]);

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

  const highlightDoneRef = useRef(false);
  const topicParam = searchParams.get('topic') || searchParams.get('highlight') || '';
  const chunkParam = searchParams.get('chunk') || '';
  const rchunkParam = searchParams.get('rchunk') || '';
  useEffect(() => { highlightDoneRef.current = false; }, [chapterSlug]);
  useEffect(() => {
    if (loading || !data) return;
    if (highlightDoneRef.current) return;
    const topicRaw = topicParam || window.location.hash.slice(1);
    const chunkSnippet = chunkParam;
    const rchunkSnippet = rchunkParam;
    if (!topicRaw && !chunkSnippet && !rchunkSnippet) return;
    let decoded = '';
    try { decoded = (topicRaw ? decodeURIComponent(topicRaw) : '').toLowerCase(); } catch { decoded = (topicRaw || '').toLowerCase(); }

    const stripMd = (s) => s
      .replace(/#{1,6}\s+/g, '')
      .replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1')
      .replace(/_{1,3}([^_]+)_{1,3}/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/^\s*[-*+]\s+/gm, '')
      .replace(/^\s*\d+\.\s+/gm, '')
      .replace(/\s+/g, ' ')
      .trim();

    const findTarget = () => {
      let el = null;
      const contentTop = document.getElementById('chapter-content-top');

      if (!contentTop && !decoded) return null;

      if (chunkSnippet && contentTop) {
        const snippetNorm = stripMd(chunkSnippet).toLowerCase().replace(/\s+/g, ' ').trim();
        const allBlocks = contentTop.querySelectorAll('p, li, h2, h3, h4, td, ul, ol, blockquote');
        for (const prefixLen of [80, 50, 30]) {
          if (el) break;
          const snippetPrefix = snippetNorm.slice(0, prefixLen);
          if (snippetPrefix.length < 15) continue;
          for (const block of allBlocks) {
            const blockNorm = block.textContent.toLowerCase().replace(/\s+/g, ' ');
            if (blockNorm.includes(snippetPrefix)) { el = block; break; }
          }
        }
        if (!el) {
          const stopW = new Set(['the','a','an','is','are','was','were','be','been','being','have','has','had','do','does','did','will','would','shall','should','may','might','can','could','must','about','also','and','any','but','for','from','how','its','just','more','most','not','now','only','other','our','out','some','such','than','that','them','then','there','these','they','this','those','too','very','what','when','where','which','while','who','why','with','you','your','into','like','over','after','before','between','each','here','both','through','same','well','because','example','many','much','need','make','take','know','good','help','used','using','called','known','based','given','important','include','provide','process','system','type','form','part','first','second','third','way','new','one','two','three']);
          const words = snippetNorm.split(' ').filter(w => w.length > 3 && !stopW.has(w));
          const topWords = words.slice(0, 12);
          if (topWords.length > 0) {
            let bestEl = null;
            let bestScore = 0;
            for (const block of allBlocks) {
              const blockText = block.textContent.toLowerCase();
              let score = 0;
              for (const w of topWords) {
                if (blockText.includes(w)) score++;
              }
              if (score > bestScore) { bestScore = score; bestEl = block; }
            }
            if (bestEl && bestScore >= 2) { el = bestEl; }
          }
        }
      }

      if (!el && rchunkSnippet && contentTop) {
        const rNorm = stripMd(rchunkSnippet).toLowerCase().replace(/\s+/g, ' ').trim();
        const allBlocks2 = contentTop.querySelectorAll('p, li, h2, h3, h4, td, ul, ol, blockquote');
        const stopW2 = new Set(['the','a','an','is','are','was','were','be','been','being','have','has','had','do','does','did','will','would','shall','should','may','might','can','could','must','about','also','and','any','but','for','from','how','its','just','more','most','not','now','only','other','our','out','some','such','than','that','them','then','there','these','they','this','those','too','very','what','when','where','which','while','who','why','with','you','your','into','like','over','after','before','between','each','here','both','through','same','well','because','example','many','much','need','make','take','know','good','help','used','using','called','known','based','given','important','include','provide','process','system','type','form','part','first','second','third','way','new','one','two','three']);
        const rWords = rNorm.split(' ').filter(w => w.length > 3 && !stopW2.has(w)).slice(0, 12);
        if (rWords.length > 0) {
          let bestEl2 = null;
          let bestScore2 = 0;
          for (const block of allBlocks2) {
            const blockText = block.textContent.toLowerCase();
            let score = 0;
            for (const w of rWords) {
              if (blockText.includes(w)) score++;
            }
            if (score > bestScore2) { bestScore2 = score; bestEl2 = block; }
          }
          if (bestEl2 && bestScore2 >= 2) { el = bestEl2; }
        }
      }

      if (!el && decoded) {
        const slugified = decoded.replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
        el = document.getElementById(slugified);
        if (!el) {
          const allH = articleRef.current?.querySelectorAll('h2[id], h3[id]') || [];
          for (const h of allH) {
            if (h.id.includes(slugified) || slugified.includes(h.id)) { el = h; break; }
          }
        }
        if (!el) {
          const allH = articleRef.current?.querySelectorAll('h2[id], h3[id]') || [];
          const stopWords = new Set(['the','a','an','is','are','was','were','be','been','being','have','has','had','do','does','did','will','would','shall','should','may','might','can','could','must','about','above','after','again','all','also','and','any','because','before','between','but','each','for','from','how','its','just','more','most','not','now','only','other','our','out','some','such','than','that','them','then','there','these','they','this','those','too','very','what','when','where','which','while','who','whom','why','with','you','your','me','my','of','on','or','so','to','up','if','in','it','no','by','at']);
          const decodedWords = decoded.split(/\s+/).filter(w => w.length > 2 && !stopWords.has(w));
          if (decodedWords.length > 0) {
            let bestH = null;
            let bestHScore = 0;
            for (const h of allH) {
              const hText = h.textContent.toLowerCase();
              const score = decodedWords.reduce((s, kw) => s + (hText.includes(kw) ? 1 : 0), 0);
              if (score > bestHScore) { bestHScore = score; bestH = h; }
            }
            if (bestH && bestHScore >= 1) { el = bestH; }
          }
        }
      }

      if (!el && decoded && contentTop) {
        const stopWords = new Set(['the','a','an','is','are','was','were','about','and','for','from','how','not','what','when','where','which','who','why','with','you','your','me','my','of','on','or','so','to','up','if','in','it','no','by','at','this','that','can','will','do','does','did','be','have','has','had','its','just','also','but','than','them','then','there','too','very']);
        const keywords = decoded.split(/\s+/).filter(w => w.length > 2 && !stopWords.has(w));
        if (keywords.length > 0) {
          const bolds = contentTop.querySelectorAll('strong, b');
          let bestBold = null;
          let bestBoldScore = 0;
          for (const b of bolds) {
            const bText = b.textContent.toLowerCase();
            const bScore = keywords.reduce((s, kw) => s + (bText.includes(kw) ? 1 : 0), 0);
            if (bScore > bestBoldScore) { bestBoldScore = bScore; bestBold = b; }
          }
          if (bestBold && bestBoldScore >= 1) {
            el = bestBold.closest('p, li, h2, h3, h4, td') || bestBold;
          }
          if (!el) {
            const allBlocks = contentTop.querySelectorAll('p, li, h2, h3, h4, td');
            let bestEl = null;
            let bestScore = 0;
            for (const block of allBlocks) {
              const text = block.textContent.toLowerCase();
              const score = keywords.reduce((s, kw) => s + (text.includes(kw) ? 1 : 0), 0);
              if (score > bestScore) { bestScore = score; bestEl = block; }
            }
            if (bestEl && bestScore >= 1) {
              el = bestEl;
            }
          }
        }
      }
      return el;
    };

    const applyHighlight = (el) => {
      document.querySelectorAll('.highlight-active, .highlight-section-start, .highlight-section-end, .highlight-single').forEach(e => {
        e.classList.remove('highlight-active', 'highlight-section-start', 'highlight-section-end', 'highlight-single');
      });
      const isHeading = /^H[1-4]$/.test(el.tagName);
      if (isHeading) {
        const level = parseInt(el.tagName[1], 10);
        const highlighted = [el];
        let sibling = el.nextElementSibling;
        while (sibling) {
          if (/^H[1-4]$/.test(sibling.tagName) && parseInt(sibling.tagName[1], 10) <= level) break;
          highlighted.push(sibling);
          sibling = sibling.nextElementSibling;
        }
        highlighted.forEach((node, i) => {
          node.classList.add('highlight-active');
          if (i === 0) node.classList.add('highlight-section-start');
          if (i === highlighted.length - 1) node.classList.add('highlight-section-end');
        });
      } else {
        const parent = el.closest('ul, ol, table');
        const target = parent || el;
        target.classList.add('highlight-active', 'highlight-single');
      }
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      highlightDoneRef.current = true;
      setTimeout(() => {
        document.querySelectorAll('.highlight-active, .highlight-section-start, .highlight-section-end, .highlight-single').forEach(e => {
          e.classList.remove('highlight-active', 'highlight-section-start', 'highlight-section-end', 'highlight-single');
        });
      }, 5000);
      try {
        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete('topic');
        cleanUrl.searchParams.delete('highlight');
        cleanUrl.searchParams.delete('chunk');
        cleanUrl.searchParams.delete('rchunk');
        window.history.replaceState(window.history.state, '', cleanUrl.pathname + cleanUrl.search + cleanUrl.hash);
      } catch {}
    };

    let attempt = 0;
    const maxAttempts = 5;
    const delays = [200, 500, 1000, 2000, 3500];
    let cancelled = false;
    const timers = [];
    const tryScroll = () => {
      if (cancelled || highlightDoneRef.current) return;
      const el = findTarget();
      if (el) {
        applyHighlight(el);
      } else if (attempt < maxAttempts - 1) {
        attempt++;
        timers.push(setTimeout(tryScroll, delays[attempt]));
      } else {
        const contentTop = document.getElementById('chapter-content-top');
        if (contentTop) {
          const fallback = contentTop.querySelector('h1, h2, h3, p');
          if (fallback) applyHighlight(fallback);
        }
      }
    };
    timers.push(setTimeout(tryScroll, delays[0]));
    return () => { cancelled = true; timers.forEach(t => clearTimeout(t)); };
  }, [loading, data, topicParam, chunkParam, rchunkParam]);

  const basePath = `/${board}/${classSlug}/${subjectSlug}`;
  const canonical = `https://syrabit.ai${basePath}/${chapterSlug}`;
  const readMins = data?.word_count ? Math.max(1, Math.ceil(data.word_count / 200)) : null;

  const handleShare = useCallback(() => {
    Analytics.chapterShare(data?.title || chapterSlug, `${basePath}/${chapterSlug}`);
    const chapTitle = data?.topic_title || data?.chapter_title || chapterSlug;
    const subjName = data?.subject_name || subjectSlug;
    const brdName = data?.board_name || board;
    const clsName = data?.class_name || classSlug;
    const shareTitle = `${chapTitle} — ${subjName} | ${brdName} ${clsName} Notes`;
    const shareDesc = data?.meta_description || `${chapTitle} notes for ${subjName}. Complete study material for ${brdName} ${clsName} students.`;
    share(shareTitle, `${basePath}/${chapterSlug}`, {
      showSerpPreview: true,
      description: shareDesc,
    });
  }, [data?.title, data?.meta_description, data?.topic_title, data?.chapter_title, data?.subject_name, data?.board_name, data?.class_name, chapterSlug, basePath, subjectSlug, board, classSlug, share]);

  const markdownComponents = useMemo(() => {
    const extractText = (node) => {
      if (typeof node === 'string') return node;
      if (Array.isArray(node)) return node.map(extractText).join('');
      if (node?.props?.children) return extractText(node.props.children);
      return '';
    };
    const counters = {};
    const toId = (children) => {
      const raw = extractText(children).toLowerCase();
      const baseId = raw.replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
      counters[baseId] = (counters[baseId] || 0) + 1;
      return counters[baseId] > 1 ? `${baseId}-${counters[baseId]}` : baseId;
    };
    return {
      h2: ({ children, ...props }) => <h2 id={toId(children)} className="scroll-mt-20" {...props}>{children}</h2>,
      h3: ({ children, ...props }) => <h3 id={toId(children)} className="scroll-mt-20" {...props}>{children}</h3>,
    };
  }, [displayContent]);

  if (loading) {
    return (
      <div className="min-h-screen bg-background text-foreground">
        <div className="max-w-7xl mx-auto px-4 py-8">
          <Skeleton className="h-4 w-48 mb-6" />
          <Skeleton className="h-10 w-full mb-4" />
          <Skeleton className="h-4 w-64 mb-8" />
          {[...Array(8)].map((_, i) => (
            <Skeleton key={i} className="h-5 w-full mb-3" style={{ width: `${60 + (i % 3) * 15}%` }} />
          ))}
        </div>
      </div>
    );
  }

  if (error || !data) {
    const handleRetry = () => {
      Analytics.chapterRetry(chapterSlug);
      setError(null);
      setLoading(true);
      const retryPath = hasStreamInUrl
        ? `/content/chapter-by-slug/${board}/${classSlug}/${streamSlug}/${subjectSlug}/${chapterSlug}`
        : `/content/chapter-by-slug/${board}/${classSlug}/${subjectSlug}/${chapterSlug}`;
      apiClient()
        .get(retryPath)
        .then(r => setData(r.data))
        .catch(e => setError(e.response?.status === 404 ? 'Chapter not found' : 'Failed to load chapter'))
        .finally(() => setLoading(false));
    };
    return (
      <div className="min-h-screen bg-background text-foreground flex items-center justify-center">
        <div className="text-center max-w-md px-6">
          <div className="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mx-auto mb-5">
            <BookOpen size={28} className="text-muted-foreground" />
          </div>
          <h1 className="text-2xl font-bold mb-3">{error || (contentLang === 'as' ? 'অধ্যায় পোৱা নগ\'ল' : 'Chapter not found')}</h1>
          <p className="text-muted-foreground mb-6">{contentLang === 'as' ? 'এই অধ্যায় এতিয়াও উপলব্ধ নহ\'ব পাৰে বা URL ভুল হ\'ব পাৰে।' : 'This chapter may not be available yet or the URL may be incorrect.'}</p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={handleRetry}
              className="inline-flex items-center gap-2 px-6 py-3 bg-purple-600 hover:bg-purple-700 rounded-xl text-white font-medium transition-colors"
            >
              <RefreshCw size={16} /> {contentLang === 'as' ? 'পুনৰ চেষ্টা কৰক' : 'Try Again'}
            </button>
            <Link to={basePath} className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-muted-foreground font-medium transition-colors hover:bg-accent/30" style={{ border: '1px solid hsl(var(--border) / 0.3)' }}>
              <ArrowLeft size={16} /> {contentLang === 'as' ? 'বিষয়লৈ উভতি যাওক' : 'Back to Subject'}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const chapterTitle = data.topic_title || data.chapter_title || chapterSlug;
  const subjectName = data.subject_name || subjectSlug;
  const boardName = data.board_name || board;
  const className = data.class_name || classSlug;
  const streamName = data.stream_name || '';

  // Task #333: Bing-keyword-aware title + description.
  // Pull the top Bing terms once so the same ranked list seeds title,
  // description, and the keywords meta below.
  const bingTopTerms = (Array.isArray(data.bing_keywords) ? data.bing_keywords : [])
    .map(k => (typeof k === 'string' ? k : (k && k.keyword) || ''))
    .map(s => (s || '').trim())
    .filter(Boolean);
  const _baseTitle = `${chapterTitle} — ${subjectName} | ${boardName} ${className} Notes`;
  // If the top Bing search differs from what's already in the title,
  // append it parenthetically so we surface real search demand without
  // breaking the deterministic fallback. Cap at 70 chars for SERP.
  const _topBingForTitle = bingTopTerms.find(t => {
    const lower = t.toLowerCase();
    return lower !== chapterTitle.toLowerCase()
      && !_baseTitle.toLowerCase().includes(lower)
      && t.length <= 40;
  });
  const seoTitle = (_topBingForTitle && (_baseTitle.length + _topBingForTitle.length + 3) <= 70)
    ? `${_baseTitle} (${_topBingForTitle})`
    : _baseTitle;
  const _baseDesc = data.meta_description
    || `${chapterTitle} notes for ${subjectName}. Complete study material for ${boardName} ${className} students.`;
  const _bingDescTerms = bingTopTerms
    .filter(t => !_baseDesc.toLowerCase().includes(t.toLowerCase()))
    .slice(0, 3);
  const seoDesc = _bingDescTerms.length > 0 && _baseDesc.length < 180
    ? `${_baseDesc} Covers ${_bingDescTerms.join(', ')}.`.slice(0, 300)
    : _baseDesc;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <PageMeta
        title={seoTitle}
        description={seoDesc}
        url={canonical}
        keywords={(() => {
          // Task #333: when the monthly Bing keyword refresh has populated
          // `data.bing_keywords` for this chapter, lead with what
          // students actually search for (sorted by impressions). Always
          // append the static template as a fallback so brand-new
          // chapters that haven't been refreshed yet still get keyword
          // coverage.
          const words = chapterTitle.split(/[\s,\-–—/&]+/).filter(w => w.length > 2);
          const base = [chapterTitle, subjectName, `${boardName} notes`, `${className} study material`, 'AHSEC', 'SEBA', 'exam preparation'];
          const fallback = [...base, ...words, `${chapterTitle} notes`, `${chapterTitle} definition`, `${chapterTitle} MCQ`, `${chapterTitle} important questions`, `${chapterTitle} ${subjectName}`, `${subjectName} ${className}`, `${chapterTitle} ${boardName}`, `${chapterTitle} study notes`, `${chapterTitle} exam notes`];
          const bingTerms = Array.isArray(data.bing_keywords)
            ? data.bing_keywords
                .map(k => (typeof k === 'string' ? k : (k && k.keyword) || ''))
                .filter(Boolean)
            : [];
          const expanded = [...bingTerms, ...fallback];
          return [...new Set(expanded)].join(', ');
        })()}
        tags={[chapterTitle, subjectName, boardName, className, data.chapter_title || ''].filter(Boolean)}
        pageType="chapter"
        pageData={{ data, basePath }}
        hasAssamese={hasAssamese}
      />

      <header className="border-b border-border/40 bg-card/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 py-5">
          <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm text-muted-foreground mb-4 flex-wrap">
            <Link to="/" className="hover:text-primary transition-colors flex items-center gap-1">
              <Home size={13} /> Home
            </Link>
            <ChevronRight size={11} className="text-muted-foreground/50" />
            <Link to="/library" className="hover:text-primary transition-colors">Browser</Link>
            <ChevronRight size={11} className="text-muted-foreground/50" />
            <Link to={basePath} className="hover:text-primary transition-colors">{subjectName}</Link>
            <ChevronRight size={11} className="text-muted-foreground/50" />
            <span className="text-foreground/80 font-medium truncate max-w-[200px]">{chapterTitle}</span>
          </nav>

          <div className="flex items-start gap-3 sm:gap-4">
            <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl flex items-center justify-center shrink-0 bg-primary/10 border border-primary/20">
              <FileText size={22} className="text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                <Badge variant="outline" className="text-[11px] text-purple-600 border-purple-500/25 bg-purple-500/5">{boardName}</Badge>
                <Badge variant="outline" className="text-[11px] text-blue-600 border-blue-500/25 bg-blue-500/5">{className}</Badge>
                {streamName && <Badge variant="outline" className="text-[11px] text-emerald-600 border-emerald-500/25 bg-emerald-500/5">{streamName}</Badge>}
              </div>
              <h1 className="text-xl sm:text-2xl md:text-3xl font-bold text-foreground leading-tight">
                {chapterTitle}
              </h1>
              {data.meta_description && (
                <p className="text-muted-foreground mt-1.5 text-sm leading-relaxed max-w-2xl line-clamp-2">{data.meta_description}</p>
              )}
              <div className="flex items-center gap-3 mt-2.5 text-xs sm:text-sm text-muted-foreground">
                {readMins && (
                  <span className="flex items-center gap-1"><Clock size={12} />{readMins} {contentLang === 'as' ? 'মিনিট পঢ়া' : 'min read'}</span>
                )}
                {data.word_count > 0 && (
                  <span>{data.word_count.toLocaleString()} {contentLang === 'as' ? 'শব্দ' : 'words'}</span>
                )}
                {headings.length > 0 && (
                  <span className="flex items-center gap-1"><Hash size={12} />{filterTopicHeadings(headings).length} {contentLang === 'as' ? 'বিষয়' : 'topics'}</span>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 mt-4 flex-wrap">
            <Link
              to={`/chat?subject=${subjectSlug}`}
              onClick={() => Analytics.chapterAskAi(subjectSlug, data?.topic_title || data?.chapter_title || chapterSlug)}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white transition-all hover:opacity-90 active:scale-95"
              style={{ background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)', boxShadow: '0 2px 10px rgba(139,92,246,0.20)' }}
            >
              <Sparkles size={14} /> {contentLang === 'as' ? 'AI সোধক' : 'Ask AI'}
            </Link>
            <button
              onClick={handleShare}
              disabled={sharing}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-muted-foreground transition-all hover:text-foreground hover:bg-accent/30 active:scale-95 disabled:opacity-50"
              style={{ border: '1px solid hsl(var(--border) / 0.3)' }}
            >
              {sharing ? <svg className="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 11-6.219-8.56"/></svg> : <Share2 size={14} />} {contentLang === 'as' ? 'শ্বেয়াৰ' : 'Share'}
            </button>
            {isQuestionPaper ? (
              <span className="ml-auto px-3 py-1 rounded-lg text-xs font-bold bg-amber-100 text-amber-700 border border-amber-200">
                Question Paper
              </span>
            ) : (
              <div className="flex items-center gap-0.5 rounded-lg p-0.5 ml-auto" style={{ background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.12)' }}>
                <button
                  onClick={() => switchLang('en')}
                  className={`px-2.5 py-1 rounded-md text-xs font-semibold transition-all ${
                    contentLang === 'en' ? 'text-white bg-violet-600 shadow-sm' : 'text-violet-600 hover:bg-violet-50'
                  }`}
                >
                  English
                </button>
                <button
                  onClick={() => switchLang('as')}
                  className={`px-2.5 py-1 rounded-md text-xs font-semibold transition-all ${
                    contentLang === 'as' ? 'text-white bg-violet-600 shadow-sm' : 'text-violet-600 hover:bg-violet-50'
                  }`}
                >
                  অসমীয়া
                </button>
              </div>
            )}
          </div>
          {!isQuestionPaper && contentLang === 'as' && !hasAssamese && (
            <p className="mt-2 text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5">
              {contentLang === 'as' ? 'এই অধ্যায়ৰ বাবে অসমীয়া অনুবাদ এতিয়াও উপলব্ধ নহয়। ইংৰাজী বিষয়বস্তু দেখুৱাই আছে।' : 'Assamese translation is not yet available for this chapter. Showing English content.'}
            </p>
          )}
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 py-6">
        <div className="flex gap-8">
          <article ref={articleRef} className="flex-1 min-w-0">
            <div
              id="chapter-content-top"
              className="chapter-textbook rounded-2xl p-5 sm:p-8 scroll-mt-20"
            >
              {data.meta_description && /^\s*(\*|\-|#{2,})/.test(data.content || '') && (
                <p className="text-base leading-relaxed text-muted-foreground mb-6 pb-4 border-b border-border/30">
                  {data.meta_description}
                </p>
              )}
              <Suspense fallback={
                <div className="space-y-3">
                  {[...Array(6)].map((_, i) => (
                    <Skeleton key={i} className="h-5 w-full" style={{ width: `${65 + (i % 3) * 12}%` }} />
                  ))}
                </div>
              }>
                <MarkdownRenderer components={markdownComponents}>
                  {displayContent}
                </MarkdownRenderer>
              </Suspense>
            </div>

            <ImportantQuestions chapterTitle={chapterTitle} pyqData={pyqData} />

            {(() => {
              const subjChapters = (_bundle?.chapters || []).filter(
                (ch) => ch.subject_id && data?.subject_id && ch.subject_id === data.subject_id
              );
              const { prev, next } = findSiblingChapters(
                subjChapters,
                data?.chapter_id,
                chapterSlug,
              );
              const prevLink = prev ? { title: prev.title || prev.slug, path: `${basePath}/${prev.slug}` } : null;
              const nextLink = next ? { title: next.title || next.slug, path: `${basePath}/${next.slug}` } : null;
              const related = relatedChapterTopics.length > 0
                ? relatedChapterTopics
                : siblingsAsRelated(subjChapters, data?.chapter_id, chapterSlug, basePath, 6);
              return (
                <ContinueLearning
                  prev={prevLink}
                  next={nextLink}
                  related={related}
                  subjectName={subjectName}
                  subjectPath={basePath}
                  chatHref={`/chat?subject=${subjectSlug}`}
                  contentLang={contentLang}
                />
              );
            })()}
          </article>

          <aside className="hidden lg:flex flex-col gap-4 w-[300px] flex-shrink-0">
            <StickyToc
              headings={headings}
              activeId={activeId}
              filterFn={filterTopicHeadings}
              getId={(h) => h.id}
              label={contentLang === 'as' ? 'এই পৃষ্ঠাত' : 'On this page'}
              onItemClick={(h) => Analytics.tocClick(h.text, document.title)}
            />
          </aside>
        </div>

        <nav className="mt-10 pt-6 border-t border-border/30" aria-label="Site navigation">
          <div className="flex flex-wrap gap-4 justify-center text-xs text-muted-foreground">
            <Link to="/" className="hover:text-primary transition-colors">Home</Link>
            <Link to="/library" className="hover:text-primary transition-colors">Browser</Link>
            <Link to={basePath} className="hover:text-primary transition-colors">{subjectName}</Link>
            <Link to="/pricing" className="hover:text-primary transition-colors">Plans & Pricing</Link>
          </div>
          <p className="text-center text-xs text-muted-foreground/60 mt-3">
            Syrabit.ai — AI-powered exam prep for Assam Board students (AHSEC · DEGREE · SEBA)
          </p>
        </nav>
      </div>
      <SerpPreviewModal preview={serpPreview} onConfirm={confirmShare} onDismiss={dismissPreview} />
    </div>
  );
}
