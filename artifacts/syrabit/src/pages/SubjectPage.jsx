import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import {
  BookOpen, Loader2, ArrowLeft, FileText, Calculator,
  BookMarked, HelpCircle, List, ChevronRight, BookText,
  Layers, Hash, Share2, Clock, RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Skeleton } from '@/components/ui/skeleton';
import { AppLayout } from '@/components/layout/AppLayout';
import { getChunks, apiClient, createShare } from '@/utils/api';
import { Analytics } from '@/utils/analytics';
import { useSubject, useChapters } from '@/hooks/useContent';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { toast } from 'sonner';


const CONTENT_TYPE_ICONS = {
  notes:   FileText,
  example: BookMarked,
  formula: Calculator,
  pyq:     HelpCircle,
  summary: List,
};

function ArticleJsonLd({ subject, title, url, wordCount }) {
  useEffect(() => {
    const eduLevel = ((subject?.class_name || '') + ' ' + (subject?.board_name || '') + ' ' + (subject?.stream_name || '')).replace(/\s+/g, ' ').trim() || 'FYUGP';
    const description = subject?.description || `Complete ${subject?.name || title} notes and study material for ${eduLevel} students.`;
    const published = subject?.created_at || new Date().toISOString();
    const modified = subject?.updated_at || published;

    const graphNodes = [
      {
        '@type': 'Article',
        headline: title,
        name: title,
        description,
        url,
        author: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
        publisher: {
          '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai',
          logo: { '@type': 'ImageObject', url: 'https://syrabit.ai/icons/icon-192x192.png' },
        },
        datePublished: published,
        dateModified: modified,
        educationalLevel: eduLevel,
        about: { '@type': 'Thing', name: subject?.name || title },
        wordCount,
        inLanguage: 'en-IN',
        mainEntityOfPage: { '@type': 'WebPage', '@id': url },
        isPartOf: { '@type': 'WebSite', '@id': 'https://syrabit.ai', name: 'Syrabit.ai' },
        image: 'https://syrabit.ai/opengraph.jpg',
      },
      {
        '@type': 'Course',
        name: `${subject?.name || title} — ${eduLevel}`,
        description,
        provider: { '@type': 'Organization', name: 'Syrabit.ai', sameAs: 'https://syrabit.ai' },
        educationalLevel: eduLevel,
        url,
        inLanguage: 'en-IN',
      },
    ];

    const chapters = subject?.chapters || [];
    const faqEntries = [];
    for (const ch of chapters) {
      if (ch.title && ch.description && ch.description.length > 10) {
        faqEntries.push({
          '@type': 'Question',
          name: `What is ${ch.title}?`,
          acceptedAnswer: { '@type': 'Answer', text: ch.description },
        });
      }
      if (faqEntries.length >= 10) break;
    }
    if (faqEntries.length >= 2) {
      graphNodes.push({ '@type': 'FAQPage', mainEntity: faqEntries });
    }

    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.id = 'subject-article-jsonld';
    script.text = JSON.stringify({ '@context': 'https://schema.org', '@graph': graphNodes });
    document.getElementById('subject-article-jsonld')?.remove();
    document.head.appendChild(script);
    return () => document.getElementById('subject-article-jsonld')?.remove();
  }, [title, url, wordCount, subject]);
  return null;
}

function useCmsPost(subjectId, enabled) {
  const [post,    setPost]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);
  useEffect(() => {
    if (!subjectId || !enabled) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiClient().get(`/cms/post/${subjectId}`)
      .then(r => { if (!cancelled) setPost(r.data); })
      .catch(e => { if (!cancelled) setError(e); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [subjectId, enabled]);
  return { post, loading, error };
}

function StickyToc({ headings, activeId }) {
  const h2h3 = useMemo(
    () => headings.filter(h => h.level === 2 || h.level === 3),
    [headings]
  );
  if (h2h3.length < 2) return null;
  return (
    <nav className="sticky top-20 w-56 shrink-0 hidden xl:block self-start" aria-label="Table of contents">
      <p className="text-[11px] font-semibold uppercase tracking-wider mb-3" style={{ color: 'rgba(255,255,255,0.30)' }}>
        On this page
      </p>
      <ul className="space-y-0.5">
        {h2h3.map(h => (
          <li key={h.anchor}>
            <a
              href={`#${h.anchor}`}
              className={`block py-1 text-[12px] leading-snug transition-colors rounded ${
                h.level === 3 ? 'pl-4' : 'pl-0'
              } ${
                activeId === h.anchor
                  ? 'text-violet-400 font-medium toc-active'
                  : 'text-white/40 hover:text-white/70'
              }`}
              style={{ borderLeft: h.level === 2 ? (activeId === h.anchor ? '2px solid #9575e0' : '2px solid transparent') : 'none' }}
              onClick={e => {
                e.preventDefault();
                document.getElementById(h.anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
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

function BlogView({ subject, subjectId }) {
  const { post, loading, error } = useCmsPost(subjectId, true);
  const articleRef = useRef(null);
  const [activeId,  setActiveId]  = useState('');
  const [merging,   setMerging]   = useState(false);
  const [sharing,   setSharing]   = useState(false);

  const headings = useMemo(() => {
    if (!post?.headings) return [];
    try { return JSON.parse(post.headings); } catch { return []; }
  }, [post]);

  const _siteOrigin = import.meta.env.VITE_SITE_URL || window.location.origin;
  const subjectUrl = subject?.board_slug && subject?.class_slug && subject?.stream_slug && subject?.slug
    ? `${_siteOrigin}/${subject.board_slug}/${subject.class_slug}/${subject.stream_slug}/${subject.slug}`
    : `${_siteOrigin}/subject/${subjectId}`;

  const readMins = post?.word_count ? Math.max(1, Math.ceil(post.word_count / 200)) : null;

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
    headings.forEach(h => {
      const el = document.getElementById(h.anchor);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [headings]);

  const handleMerge = async () => {
    if (!subjectId) return;
    setMerging(true);
    try {
      await apiClient().post(`/admin/cms/merge/${subjectId}`);
      toast.success('Merged & published — reload to see Blog View');
    } catch { toast.error('Merge failed (admin access needed)'); }
    finally { setMerging(false); }
  };

  if (loading) return (
    <div className="space-y-5 max-w-3xl mx-auto px-4">
      {[...Array(8)].map((_, i) => <Skeleton key={i} className="h-5 w-full" style={{ width: `${60 + (i % 3) * 15}%` }} />)}
    </div>
  );

  if (error || !post) return (
    <div className="flex flex-col items-center py-16 text-center gap-4 max-w-md mx-auto px-4">
      <BookText size={36} className="opacity-20" />
      <p className="text-sm" style={{ color: 'rgba(232,232,232,0.50)' }}>
        Blog view not yet generated for this subject.
      </p>
      <button
        onClick={handleMerge}
        disabled={merging}
        className="h-9 px-4 rounded-xl text-sm font-medium text-white flex items-center gap-2 disabled:opacity-50"
        style={{ background: 'rgba(149,117,224,0.20)', border: '1px solid rgba(149,117,224,0.30)' }}
      >
        {merging ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
        Generate Blog View (admin)
      </button>
    </div>
  );

  const htmlContent = post.subject_merged_html || '';

  return (
    <div className="blog-view-tab w-full" style={{ background: '#f0f0f1', padding: '1.5rem 0 4rem' }}>
      {subject && (
        <ArticleJsonLd subject={subject} title={post.title || subject.name} url={subjectUrl} wordCount={post.word_count} />
      )}
      <div className="flex gap-8 max-w-4xl mx-auto px-4 sm:px-6">
        <article ref={articleRef} className="flex-1 min-w-0 pb-16 min-w-0">

          {/* Hero info bar — gray header strip */}
          <div className="blog-hero-bar flex flex-wrap items-center gap-3 text-[11px]"
            style={{ background: '#f8f9fa', borderBottom: '1px solid #e2e2e2', color: '#777', padding: '0.6rem 2rem', marginBottom: 0, borderRadius: '4px 4px 0 0' }}>
            {readMins && (
              <span className="flex items-center gap-1"><Clock size={11} />{readMins} min read</span>
            )}
            {post.word_count > 0 && (
              <span>{post.word_count.toLocaleString()} words</span>
            )}
            {headings.length > 0 && (
              <span className="flex items-center gap-1"><Hash size={11} />{headings.filter(h => h.level === 2).length} sections</span>
            )}
            <button
              className="ml-auto flex items-center gap-1 transition-colors text-emerald-600 hover:text-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={sharing}
              onClick={async () => {
                if (sharing) return;
                setSharing(true);
                const utmParams = 'utm_source=whatsapp&utm_medium=referral&utm_campaign=share';
                try {
                  const res = await createShare(post.slug || post.id, post.title, `/subject/${subjectId}`);
                  const referralUrl = res.data.referral_url;
                  try { Analytics.subjectShared(post.title, referralUrl, res.data.code); } catch {}
                  const shareUrl = `${referralUrl}${referralUrl.includes('?') ? '&' : '?'}${utmParams}`;
                  const text = `📚 ${post.title} on Syrabit.ai!\n${shareUrl}`;
                  window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, '_blank', 'noopener,noreferrer');
                } catch {
                  const fallback = `${window.location.origin}/subject/${subjectId}?${utmParams}`;
                  const text = `📚 ${post.title} on Syrabit.ai!\n${fallback}`;
                  window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, '_blank', 'noopener,noreferrer');
                } finally {
                  setSharing(false);
                }
              }}
            >
              {sharing ? <Loader2 size={11} className="animate-spin" /> : <Share2 size={11} />} Share
            </button>
          </div>

          {/* White content card */}
          {htmlContent ? (
            <div
              className="learn-article"
              style={{ background: '#ffffff', color: '#1a1a1a', fontSize: '16px', lineHeight: '1.7', padding: 'clamp(1.25rem, 5vw, 2.5rem) clamp(1rem, 5vw, 2.5rem) 2.5rem', boxShadow: '0 1px 12px rgba(0,0,0,0.09)', borderRadius: '0 0 4px 4px', maxWidth: 'none' }}
              dangerouslySetInnerHTML={{ __html: htmlContent }}
            />
          ) : (
            <div className="learn-article"
              style={{ background: '#ffffff', color: '#1a1a1a', fontSize: '16px', lineHeight: '1.7', padding: 'clamp(1.25rem, 5vw, 2.5rem) clamp(1rem, 5vw, 2.5rem) 2.5rem', boxShadow: '0 1px 12px rgba(0,0,0,0.09)', borderRadius: '0 0 4px 4px', maxWidth: 'none' }}>
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                {post.merged_md || ''}
              </ReactMarkdown>
            </div>
          )}

          {/* AI Tutor CTA */}
          <div className="blog-ai-cta" style={{ background: '#f5f0ff', border: '1px solid #c4b0f0', marginTop: '2.5rem', padding: '1.25rem 1.5rem', borderRadius: '12px' }}>
            <p className="text-sm mb-1" style={{ color: '#5b35a8', fontWeight: 600 }}>Have a question about this topic?</p>
            <p className="text-xs mb-3" style={{ color: '#7c5cbf' }}>Get Assamboard-aligned answers instantly from Syra.</p>
            <Link to={`/chat?subject=${subjectId}`}>
              <Button size="sm" style={{ background: 'hsl(258 60% 68%)', color: 'white' }}>Ask Syra</Button>
            </Link>
          </div>
        </article>

        <StickyToc headings={headings} activeId={activeId} />
      </div>
    </div>
  );
}

function LegacyAccordion({ subject, subjectId, chapters }) {
  const [chunks,         setChunks]         = useState({});
  const [loadingChapter, setLoadingChapter] = useState(null);

  const loadChunks = useCallback(async (chapterId) => {
    if (chunks[chapterId]) return;
    setLoadingChapter(chapterId);
    try {
      const res = await getChunks(chapterId);
      setChunks(prev => ({ ...prev, [chapterId]: res.data }));
    } finally { setLoadingChapter(null); }
  }, [chunks]);

  if (chapters.length === 0) return (
    <div className="text-center py-8" style={{ color: 'rgba(232,232,232,0.40)' }}>
      <BookOpen size={32} className="mx-auto mb-2 opacity-30" />
      <p>No chapters available yet</p>
    </div>
  );

  return (
    <Accordion type="multiple" className="space-y-2 max-w-4xl mx-auto">
      {chapters.map(chapter => {
        const chapterSeoPath = subject?.board_slug && subject?.class_slug && subject?.slug && chapter.slug
          ? `/${subject.board_slug}/${subject.class_slug}/${subject.slug}/${chapter.slug}`
          : null;
        return (
          <AccordionItem key={chapter.id} value={chapter.id} className="glass-card rounded-xl border-0 px-4">
            <AccordionTrigger className="hover:no-underline py-4" onClick={() => loadChunks(chapter.id)}>
              <div className="flex items-center gap-3">
                <span className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center text-xs font-semibold text-primary flex-shrink-0">
                  {chapter.chapter_number}
                </span>
                <span className="text-sm font-medium text-foreground text-left">{chapter.title}</span>
              </div>
            </AccordionTrigger>
            <AccordionContent className="pb-4">
              <article
                itemScope
                itemType="https://schema.org/LearningResource"
                aria-label={`${chapter.title} — ${subject.name} study material`}
              >
                <meta itemProp="name" content={chapter.title} />
                <meta itemProp="educationalLevel" content={subject.class_name || ''} />
                <meta itemProp="learningResourceType" content="Study Notes" />
                <meta itemProp="inLanguage" content="en-IN" />
                {chapter.description && <meta itemProp="description" content={chapter.description} />}
                {chapterSeoPath && (
                  <Link
                    to={chapterSeoPath}
                    className="block mb-3 px-4 py-3 rounded-xl bg-primary/5 border border-primary/10 hover:bg-primary/10 hover:border-primary/20 transition-all group/ch"
                    title={`${chapter.title} — ${subject.name} Notes & Study Material`}
                    itemProp="url"
                  >
                    <div className="flex items-center gap-2">
                      <FileText size={14} className="text-primary flex-shrink-0" />
                      <span className="text-sm font-medium text-foreground group-hover/ch:text-primary transition-colors">
                        {chapter.title} — Notes & Study Material
                      </span>
                      <ChevronRight size={14} className="ml-auto text-muted-foreground group-hover/ch:text-primary flex-shrink-0 transition-colors" />
                    </div>
                    {chapter.description && (
                      <p className="text-xs text-muted-foreground mt-1 ml-6 line-clamp-2">{chapter.description}</p>
                    )}
                  </Link>
                )}
                {loadingChapter === chapter.id ? (
                  <div className="flex justify-center py-4"><Loader2 size={20} className="animate-spin text-primary" /></div>
                ) : chapter.content ? (
                  <div className="px-4 py-2">
                    <div className="md-content-light text-sm" itemProp="text">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{chapter.content}</ReactMarkdown>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-4">
                    <p className="text-sm text-muted-foreground">No content added yet</p>
                  </div>
                )}
                <div className="mt-3">
                  <Link to={`/chat?subject=${subjectId}`}>
                    <Button size="sm" className="text-xs bg-primary hover:bg-primary/90 text-primary-foreground">
                      Ask AI about this chapter
                    </Button>
                  </Link>
                </div>
              </article>
            </AccordionContent>
          </AccordionItem>
        );
      })}
    </Accordion>
  );
}

export default function SubjectPage() {
  const { subjectId }          = useParams();
  const [activeTab, setActiveTab] = useState('blog');

  const { data: subject, isLoading: subjectLoading } = useSubject(subjectId);
  const { data: chapters = [], isLoading: chaptersLoading } = useChapters(subjectId);
  const loading = subjectLoading || chaptersLoading;

  if (loading) return (
    <AppLayout>
      <div className="p-4 sm:p-6 space-y-5 animate-pulse">
        <div className="flex items-center gap-3">
          <div className="h-5 w-5 rounded bg-violet-500/10" />
          <div className="h-4 w-24 rounded bg-violet-500/10" />
        </div>
        <div className="space-y-2">
          <div className="h-8 w-2/3 rounded-lg bg-violet-500/10" />
          <div className="h-4 w-1/2 rounded bg-violet-500/8" />
        </div>
        <div className="flex gap-2">
          <div className="h-10 w-28 rounded-xl bg-violet-500/10" />
          <div className="h-10 w-28 rounded-xl bg-violet-500/8" />
        </div>
        <div className="space-y-3 pt-2">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="rounded-xl border border-violet-500/8 p-4 space-y-2" style={{ background: 'rgba(139,92,246,0.03)' }}>
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-violet-500/10 flex-shrink-0" />
                <div className="flex-1 space-y-1.5">
                  <div className="h-4 rounded w-3/4 bg-violet-500/10" />
                  <div className="h-3 rounded w-1/3 bg-violet-500/6" />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </AppLayout>
  );

  if (!subject) return (
    <AppLayout>
      <div className="p-6 text-center">
        <p className="text-muted-foreground">Subject not found</p>
        <Link to="/library"><Button className="mt-4">Back to Browser</Button></Link>
      </div>
    </AppLayout>
  );

  const SITE_ORIGIN = import.meta.env.VITE_SITE_URL || window.location.origin;
  const subjectUrl  = subject.board_slug && subject.class_slug && subject.stream_slug && subject.slug
    ? `${SITE_ORIGIN}/${subject.board_slug}/${subject.class_slug}/${subject.stream_slug}/${subject.slug}`
    : `${SITE_ORIGIN}/subject/${subjectId}`;
  const boardLabel = subject.board_name || 'Assamboard';
  const classLabel = subject.class_name || '';
  const subjectTitle = (subject.name + ' Notes — ' + (classLabel || boardLabel) + ' ' + (subject.stream_name || '')).trim();
  const subjectDesc  = subject.description
    || ('Complete ' + subject.name + ' notes, chapters, and AI explanations for ' + (classLabel || boardLabel) + ' ' + (subject.stream_name || '') + ' students.');

  const TABS = [
    { id: 'blog',    label: 'Blog View',       icon: BookText },
    { id: 'legacy',  label: 'Chapters',        icon: Layers  },
  ];

  return (
    <AppLayout pageTitle={subject.name}>
      <PageMeta title={subjectTitle} description={subjectDesc.trim()} url={subjectUrl} />
      <div className="p-4 sm:p-6 space-y-6" data-testid="subject-detail">
        {/* Back */}
        <Link to="/library" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft size={14} /> Browser
        </Link>

        {/* Header */}
        <div className="glass-card rounded-2xl p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center text-3xl">
                {subject.icon || '📚'}
              </div>
              <div>
                <h1 className="text-xl font-semibold text-foreground">{subject.name}</h1>
                <p className="text-sm text-muted-foreground mt-0.5">{subject.description}</p>
                <div className="flex items-center gap-3 mt-2">
                  <span className="text-xs text-muted-foreground">
                    <BookOpen size={12} className="inline mr-1" />{chapters.length} chapters
                  </span>
                </div>
              </div>
            </div>
            <Link to={`/chat?subject=${subjectId}`}>
              <Button className="bg-primary hover:bg-primary/90 text-primary-foreground flex-shrink-0">Ask AI</Button>
            </Link>
          </div>
          {subject.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-4">
              {subject.tags.map(tag => (
                <span key={tag} className="text-xs bg-primary/8 text-primary/80 px-2.5 py-1 rounded-full border border-primary/15">
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Tab bar */}
        <div className="flex gap-1 p-1 rounded-xl w-fit" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 h-9 px-4 rounded-lg text-sm font-medium transition-all ${
                activeTab === tab.id
                  ? 'text-white'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
              style={activeTab === tab.id ? { background: 'rgba(149,117,224,0.25)', boxShadow: '0 0 12px rgba(149,117,224,0.15)' } : {}}
            >
              <tab.icon size={14} />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === 'blog' && (
          <BlogView subject={subject} subjectId={subjectId} />
        )}
        {activeTab === 'legacy' && (
          <LegacyAccordion subject={subject} subjectId={subjectId} chapters={chapters} />
        )}
      </div>
    </AppLayout>
  );
}
