import { useState, useEffect, useRef, useMemo, useCallback, memo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Search, Bookmark, BookmarkCheck,
  BookOpen, Layers, ChevronRight, Sparkles,
  Share2, RefreshCw, ExternalLink, Lock,
  FileText, Clock, ArrowRight, BookText, Loader2, Sun, Moon,
} from 'lucide-react';
import { MasonryInfiniteGrid } from '@egjs/react-infinitegrid';
import { useTheme } from 'next-themes';

const CMS_API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

function useCmsLibrary() {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(`${CMS_API}/content/cms-library`)
      .then(r => r.json())
      .then(d => setDocs(Array.isArray(d) ? d : []))
      .catch(() => setDocs([]))
      .finally(() => setLoading(false));
  }, []);
  return { docs, loading };
}

function CmsDocCard({ doc }) {
  const tags = doc.seo_tags ? doc.seo_tags.split(',').map(t => t.trim()).filter(Boolean).slice(0, 3) : [];
  return (
    <Link
      to={`/learn/${doc.seo_slug || doc.id}`}
      className="group flex flex-col rounded-2xl overflow-hidden border transition-all duration-200 hover:border-violet-500/30"
      style={{
        background: 'var(--card)',
        border: '1px solid rgba(139,92,246,0.10)',
        boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
      }}
    >
      {doc.thumbnail_url && (
        <div className="w-full aspect-video overflow-hidden">
          <img src={doc.thumbnail_url} alt={doc.alt_text || doc.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" loading="lazy" />
        </div>
      )}
      <div className="p-4 flex flex-col flex-1 gap-3">
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {tags.map(t => (
              <span
                key={t}
                className="px-2 py-0.5 rounded-full text-[10px] font-medium"
                style={t.toLowerCase() === 'syllabus'
                  ? { background: 'rgba(16,185,129,0.12)', color: '#6ee7b7', border: '1px solid rgba(16,185,129,0.2)' }
                  : { background: 'rgba(139,92,246,0.10)', color: '#a78bfa' }
                }
              >{t}</span>
            ))}
          </div>
        )}
        <h3 className="text-sm font-semibold text-foreground leading-snug group-hover:text-violet-300 transition-colors line-clamp-2">{doc.title}</h3>
        {doc.meta_description && (
          <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">{doc.meta_description}</p>
        )}
        <div className="flex items-center gap-3 mt-auto pt-2 border-t border-white/[0.06]">
          {doc.word_count > 0 && (
            <span className="flex items-center gap-1 text-[10px] text-muted-foreground/60">
              <Clock size={10} /> {Math.max(1, Math.ceil(doc.word_count / 200))} min
            </span>
          )}
          <span className="ml-auto flex items-center gap-1 text-[10px] text-violet-400 font-medium group-hover:gap-2 transition-all">
            Read <ArrowRight size={10} />
          </span>
        </div>
      </div>
    </Link>
  );
}

function CmsDocsSection() {
  const { docs, loading } = useCmsLibrary();
  if (loading || docs.length === 0) return null;
  return (
    <div className="w-full max-w-6xl mx-auto px-4 md:px-6 pb-8">
      <div className="flex items-center gap-2 mb-4 mt-2">
        <FileText size={16} className="text-violet-400" />
        <h2 className="text-base font-semibold text-foreground">Study Resources</h2>
        <span className="ml-1 px-2 py-0.5 rounded-full text-[10px] font-medium" style={{ background: 'rgba(139,92,246,0.12)', color: '#a78bfa' }}>{docs.length}</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {docs.slice(0, 9).map(doc => <CmsDocCard key={doc.id} doc={doc} />)}
      </div>
    </div>
  );
}

function CmsPostCard({ post }) {
  const to = `/subject/${post.subject_id}`;
  const mins = post.word_count ? Math.max(1, Math.ceil(post.word_count / 200)) : null;
  return (
    <Link
      to={to}
      data-grid-groupkey={post.groupKey}
      data-grid-key={post.subject_id}
      className="block rounded-2xl overflow-hidden border transition-all duration-200 hover:-translate-y-0.5"
      style={{ background: '#1a1a1a', border: '1px solid rgba(149,117,224,0.10)', boxShadow: '0 4px 20px rgba(0,0,0,0.30)' }}
    >
      <div className="p-4 flex flex-col gap-2">
        <div className="flex items-start gap-2">
          <BookText size={14} className="text-violet-400 shrink-0 mt-0.5" />
          <h3 className="text-sm font-semibold leading-snug line-clamp-2" style={{ color: '#E8E8E8' }}>{post.title || 'Untitled Post'}</h3>
        </div>
        {post.word_count > 0 && (
          <div className="flex items-center gap-3 text-[10px]" style={{ color: 'rgba(232,232,232,0.35)' }}>
            {mins && <span className="flex items-center gap-1"><Clock size={9} />{mins} min</span>}
            <span>{post.word_count.toLocaleString()} words</span>
          </div>
        )}
        <div className="flex items-center justify-between mt-1">
          {post.board_slug && (
            <span className="px-2 py-0.5 rounded-full text-[9px] font-medium uppercase tracking-wide" style={{ background: 'rgba(149,117,224,0.12)', color: '#a78bfa' }}>
              {post.board_slug}
            </span>
          )}
          <span className="ml-auto flex items-center gap-1 text-[10px] font-medium" style={{ color: '#9575e0' }}>
            Read <ArrowRight size={10} />
          </span>
        </div>
      </div>
    </Link>
  );
}

const POSTS_PER_PAGE = 12;

function CmsPostsGrid({ board, classSlug }) {
  const [items,    setItems]    = useState([]);
  const [total,    setTotal]    = useState(0);
  const [loading,  setLoading]  = useState(false);
  const [done,     setDone]     = useState(false);
  const groupKey = useRef(0);

  const fetchPage = useCallback(async (skip) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: POSTS_PER_PAGE, skip });
      if (board)      params.append('board',      board);
      if (classSlug)  params.append('class_slug', classSlug);
      const res  = await fetch(`${CMS_API}/cms/posts?${params}`);
      const data = await res.json();
      const newItems = (data.items || []).map(p => ({ ...p, groupKey: groupKey.current }));
      setItems(prev => skip === 0 ? newItems : [...prev, ...newItems]);
      setTotal(data.total || 0);
      if (skip + POSTS_PER_PAGE >= (data.total || 0)) setDone(true);
      groupKey.current += 1;
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, [board, classSlug]);

  useEffect(() => { setItems([]); setDone(false); groupKey.current = 0; fetchPage(0); }, [fetchPage]);

  if (!loading && items.length === 0) return null;

  return (
    <div className="w-full max-w-6xl mx-auto px-4 md:px-6 pb-10">
      <div className="flex items-center gap-2 mb-4 mt-2">
        <BookText size={16} className="text-violet-400" />
        <h2 className="text-base font-semibold text-foreground">Subject Blog Posts</h2>
        {total > 0 && (
          <span className="ml-1 px-2 py-0.5 rounded-full text-[10px] font-medium" style={{ background: 'rgba(149,117,224,0.12)', color: '#a78bfa' }}>{total}</span>
        )}
      </div>
      <MasonryInfiniteGrid
        className="cms-posts-masonry"
        gap={16}
        align="stretch"
        useResizeObserver
        observeChildren
        onRequestAppend={({ groupKey: gk }) => {
          if (loading || done) return;
          fetchPage(items.length);
        }}
      >
        {items.map(post => (
          <CmsPostCard key={post.subject_id} post={post} />
        ))}
      </MasonryInfiniteGrid>
      {loading && (
        <div className="flex justify-center py-6">
          <Loader2 size={20} className="animate-spin text-violet-400" />
        </div>
      )}
      {done && items.length > 0 && (
        <p className="text-center text-xs py-4" style={{ color: 'rgba(232,232,232,0.25)' }}>All {total} posts loaded</p>
      )}
    </div>
  );
}
import { toast } from 'sonner';
import { Toaster } from '@/components/ui/sonner';
import PageMeta from '@/components/seo/PageMeta';
import { Analytics } from '@/utils/analytics';
import { AppLayout } from '@/components/layout/AppLayout';
import { useAuth } from '@/context/AuthContext';
import {
  useLibraryBundle, useSavedSubjects,
} from '@/hooks/useContent';
import { useToggleSavedSubject } from '@/hooks/useUser';

const THUMB_GRADIENTS = {
  math:      ['#4f46e5', '#7c3aed'],
  physics:   ['#2563eb', '#0891b2'],
  chemistry: ['#059669', '#0d9488'],
  biology:   ['#16a34a', '#15803d'],
  arts:      ['#d97706', '#b45309'],
  science:   ['#7c3aed', '#4f46e5'],
};

const FILTER_CHIPS = [
  { id: 'all',         label: 'All'      },
  { id: 'saved',       label: '★ Saved'  },
];

function cn(...classes) {
  return classes.filter(Boolean).join(' ');
}

function getOnboardingProfile() {
  try {
    const raw = localStorage.getItem('syrabit:onboarding');
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function LibrarySkeleton() {
  const pulse = { background: 'rgba(255,255,255,0.06)' };
  const pulseDim = { background: 'rgba(255,255,255,0.04)' };
  return (
    <div className="flex flex-col h-full w-full overflow-hidden animate-pulse">
      {/* Sticky header skeleton */}
      <div className="shrink-0 w-full" style={{ borderBottom: '1px solid rgba(139,92,246,0.08)' }}>
        <div className="w-full max-w-6xl mx-auto px-4 md:px-6 pt-5 pb-3 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div className="space-y-2">
              <div className="h-6 w-48 rounded-lg" style={pulse} />
              <div className="h-3 w-32 rounded" style={pulseDim} />
            </div>
            <div className="h-9 w-24 rounded-xl" style={pulse} />
          </div>
          <div className="h-11 w-full rounded-xl" style={pulseDim} />
          <div className="flex gap-2.5">
            <div className="h-9 flex-1 rounded-xl" style={pulseDim} />
            <div className="h-9 flex-1 rounded-xl" style={pulseDim} />
          </div>
          <div className="flex gap-2">
            {[60, 80, 72, 68, 90].map((w) => (
              <div key={w} className="h-8 rounded-full flex-shrink-0" style={{ width: w, ...pulseDim }} />
            ))}
          </div>
        </div>
      </div>
      {/* Cards skeleton */}
      <div className="flex-1 overflow-hidden">
        <div className="w-full max-w-6xl mx-auto px-4 md:px-6 py-5">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
            {[...Array(6)].map((_, i) => (
              <div
                key={i}
                className="rounded-2xl border"
                style={{ background: 'rgba(255,255,255,0.03)', borderColor: 'rgba(139,92,246,0.07)' }}
              >
                <div className="h-9 rounded-t-2xl" style={pulseDim} />
                <div className="p-3 space-y-2.5">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl flex-shrink-0" style={pulse} />
                    <div className="flex-1 space-y-1.5">
                      <div className="h-4 rounded w-3/4" style={pulse} />
                      <div className="h-3 rounded w-1/2" style={pulseDim} />
                    </div>
                  </div>
                  <div className="h-3 rounded w-full" style={pulseDim} />
                  <div className="space-y-1.5">
                    {[...Array(3)].map((_, j) => (
                      <div key={j} className="h-9 rounded-lg" style={pulseDim} />
                    ))}
                  </div>
                  <div className="grid grid-cols-2 gap-1.5 pt-1">
                    {[...Array(4)].map((_, j) => (
                      <div key={j} className="h-10 rounded-lg" style={pulseDim} />
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

const FilterChip = memo(function FilterChip({ chip, isActive, onClick }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={isActive}
      className="flex-shrink-0 px-4 py-1.5 rounded-full text-sm transition-all duration-200 active:scale-95"
      style={
        isActive
          ? {
              color: '#fff',
              fontWeight: 600,
              background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
              boxShadow: '0 4px 20px rgba(139,92,246,0.40), 0 0 0 1px rgba(255,255,255,0.06) inset',
            }
          : {
              color: 'hsl(var(--muted-foreground))',
              fontWeight: 500,
              background: 'rgba(139,92,246,0.05)',
              border: '1px solid rgba(139,92,246,0.14)',
            }
      }
      onMouseEnter={e => {
        if (!isActive) {
          e.currentTarget.style.background = 'rgba(139,92,246,0.10)';
          e.currentTarget.style.borderColor = 'rgba(139,92,246,0.22)';
          e.currentTarget.style.color = 'hsl(var(--foreground))';
        }
      }}
      onMouseLeave={e => {
        if (!isActive) {
          e.currentTarget.style.background = 'rgba(139,92,246,0.05)';
          e.currentTarget.style.borderColor = 'rgba(139,92,246,0.14)';
          e.currentTarget.style.color = 'hsl(var(--muted-foreground))';
        }
      }}
      data-testid="library-filter-chip"
    >
      {chip.label}
    </button>
  );
});

const SubjectCard = memo(function SubjectCard({ sub, chapters = [], isSaved, onToggleSave, onAskAI, index }) {
  const thumbColors = useMemo(() => THUMB_GRADIENTS[sub.gradient] || THUMB_GRADIENTS.math, [sub.gradient]);
  const tags = useMemo(() => Array.isArray(sub.tags) ? sub.tags : [], [sub.tags]);
  const visibleTags = useMemo(() => tags.slice(0, 3), [tags]);
  const chapterCount = useMemo(() => chapters.length || sub.chapter_count || sub.chapterCount || 0, [chapters.length, sub.chapter_count, sub.chapterCount]);
  const hasDocument = useMemo(() => sub.has_document === true, [sub.has_document]);

  const seoPath = useMemo(() =>
    sub.boardSlug && sub.classSlug && sub.streamSlug && sub.slug
      ? `/${sub.boardSlug}/${sub.classSlug}/${sub.streamSlug}/${sub.slug}`
      : null,
    [sub.boardSlug, sub.classSlug, sub.streamSlug, sub.slug]
  );

  const subjectLandingPath = useMemo(() =>
    sub.boardSlug && sub.classSlug && sub.slug
      ? `/${sub.boardSlug}/${sub.classSlug}/${sub.slug}`
      : `/subject/${sub.id}`,
    [sub.boardSlug, sub.classSlug, sub.slug, sub.id]
  );

  const displayUrl = useMemo(() => {
    if (seoPath) return `syrabit.ai${seoPath}`;
    return `syrabit.ai/subject/${sub.id?.slice(0, 8)}`;
  }, [seoPath, sub.id]);

  const whatsappShareUrl = useMemo(() => {
    const fullUrl = `https://syrabit.ai${subjectLandingPath}`;
    const text = `📚 Study ${sub.name} on Syrabit.ai — AI-powered notes & practice for AHSEC students!\n${fullUrl}`;
    return `https://wa.me/?text=${encodeURIComponent(text)}`;
  }, [sub.name, subjectLandingPath]);

  const visibleChapters = useMemo(() => chapters.slice(0, 3), [chapters]);
  const moreChapters = chapters.length - 3;

  return (
    <div
      className="w-full rounded-2xl overflow-hidden transition-all duration-300 group/card hover:-translate-y-0.5"
      style={{
        background: 'var(--card)',
        border: isSaved
          ? '1px solid rgba(139,92,246,0.40)'
          : '1px solid rgba(139,92,246,0.10)',
        boxShadow: isSaved
          ? '0 0 32px rgba(139,92,246,0.15), 0 8px 32px rgba(0,0,0,0.25)'
          : '0 4px 24px rgba(0,0,0,0.18)',
        animationDelay: `${index * 50}ms`,
      }}
      data-testid="library-subject-card"
      data-subject-id={sub.id}
    >
      {/* Color Accent Header Strip — replaces browser chrome */}
      <div
        className="flex items-center justify-between px-3.5 py-2.5"
        style={{
          background: `linear-gradient(135deg, ${thumbColors[0]}22, ${thumbColors[1]}14)`,
          borderBottom: `1px solid ${thumbColors[0]}28`,
        }}
      >
        <div className="flex items-center gap-2">
          <div
            className="w-5 h-5 rounded-md flex items-center justify-center"
            style={{ background: `linear-gradient(135deg, ${thumbColors[0]}, ${thumbColors[1]})`, boxShadow: `0 0 8px ${thumbColors[0]}50` }}
          >
            <Layers size={10} className="text-white" />
          </div>
          <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: thumbColors[0] }}>
            {sub.streamName || sub.boardName || 'Subject'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {hasDocument && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-semibold"
              style={{ background: 'rgba(16,185,129,0.12)', color: '#6ee7b7', border: '1px solid rgba(16,185,129,0.20)' }}>
              <Lock size={7} /> Doc
            </span>
          )}
          {isSaved && (
            <BookmarkCheck size={13} className="text-violet-400" style={{ filter: 'drop-shadow(0 0 4px rgba(139,92,246,0.5))' }} />
          )}
        </div>
      </div>

      {/* Card Content */}
      <div className="px-3 sm:px-4 pt-3 pb-2">
        <Link to={subjectLandingPath} className="block group/title">
          <div className="flex items-start gap-3 mb-2">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center text-xl shrink-0"
              style={{
                background: `linear-gradient(135deg, ${thumbColors[0]}30, ${thumbColors[1]}20)`,
                border: `1px solid ${thumbColors[0]}30`,
              }}
            >
              {sub.icon || '📚'}
            </div>
            <div className="min-w-0 flex-1">
              <h3
                className="text-foreground font-bold group-hover/title:text-purple-300 transition-colors leading-tight"
                style={{ fontSize: '0.95rem' }}
              >
                {sub.name}
              </h3>
              <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 mt-0.5">
                <span className="text-[11px] font-medium px-1.5 py-0.5 rounded" style={{ background: 'rgba(139,92,246,0.12)', color: 'hsl(var(--primary))' }}>
                  {sub.boardName}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {sub.className}
                </span>
                {sub.streamName && (
                  <>
                    <span className="text-[11px] text-muted-foreground/60">·</span>
                    <span className="text-[11px] text-muted-foreground/60">
                      {sub.streamName}
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>
        </Link>

        {sub.description && (
          <p className="text-muted-foreground text-xs leading-relaxed mb-1.5 sm:mb-2 line-clamp-1 sm:line-clamp-2">
            {sub.description}
          </p>
        )}

        {visibleTags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2 sm:mb-3">
            {visibleTags.map((tag) => (
              <span
                key={tag}
                className="px-2 py-0.5 rounded-full text-[10px] font-medium"
                style={{
                  color: 'hsl(var(--primary) / 0.8)',
                  background: 'rgba(139,92,246,0.06)',
                  border: '1px solid rgba(139,92,246,0.12)',
                }}
              >
                {tag}
              </span>
            ))}
            {tags.length > 3 && (
              <span className="text-[10px] text-muted-foreground/40 px-1">
                +{tags.length - 3}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Chapters as Lesson Links */}
      {visibleChapters.length > 0 && (
        <div
          className="mx-3 mb-2 sm:mb-3 rounded-xl overflow-hidden relative"
          style={{
            background: 'rgba(139,92,246,0.03)',
            border: '1px solid rgba(139,92,246,0.08)',
          }}
        >
          {/* Thumbnail background — semi-transparent so links stay readable */}
          {sub.thumbnailUrl && (
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                backgroundImage: `url(${sub.thumbnailUrl})`,
                backgroundSize: 'cover',
                backgroundPosition: 'center top',
                opacity: 0.13,
                zIndex: 0,
              }}
            />
          )}
          {/* z-10 wrapper keeps chapter links above the thumbnail background */}
          <div className="relative z-10">
            <div className="flex items-center gap-1.5 px-3 py-1.5" style={{ borderBottom: '1px solid rgba(139,92,246,0.06)' }}>
              <Layers size={11} className="text-purple-400/60" />
              <span className="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wider">
                {chapterCount} Lessons
              </span>
            </div>
            {visibleChapters.map((ch, i) => {
              const chPath = sub.boardSlug && sub.classSlug && sub.slug && ch.slug
                ? `/${sub.boardSlug}/${sub.classSlug}/${sub.slug}/${ch.slug}`
                : subjectLandingPath;
              return (
                <Link
                  key={ch.id || i}
                  to={chPath}
                  className="flex items-center gap-2 px-3 py-2.5 sm:py-2 text-xs transition-all hover:bg-purple-500/8 group/lesson"
                  style={{ borderBottom: i < visibleChapters.length - 1 ? '1px solid rgba(139,92,246,0.05)' : 'none' }}
                  title={`${ch.title} — ${sub.name}`}
                >
                  <span
                    className="w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-bold shrink-0"
                    style={{ background: 'rgba(139,92,246,0.10)', color: 'hsl(var(--primary))' }}
                  >
                    {i + 1}
                  </span>
                  <span className="text-foreground/75 group-hover/lesson:text-purple-300 truncate transition-colors flex-1">
                    {ch.title}
                  </span>
                  <ExternalLink
                    size={10}
                    className="shrink-0 text-muted-foreground/20 group-hover/lesson:text-purple-400 transition-colors"
                  />
                </Link>
              );
            })}
            {moreChapters > 0 && (
              <Link
                to={subjectLandingPath}
                className="flex items-center justify-center gap-1 px-3 py-2 text-[11px] font-medium text-purple-400/70 hover:text-purple-300 hover:bg-purple-500/5 transition-colors"
                style={{ borderTop: '1px solid rgba(139,92,246,0.06)' }}
              >
                +{moreChapters} more lessons
                <ChevronRight size={11} />
              </Link>
            )}
          </div>
        </div>
      )}

      {/* Action Bar — 2×2 grid */}
      <div
        className="grid grid-cols-2 gap-1.5 px-3 py-2.5"
        style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}
      >
        {/* Row 1 — left: Save */}
        <button
          onClick={() => { onToggleSave(sub.id); try { Analytics.subjectBookmarked(sub.name, !isSaved); } catch {} }}
          aria-label={isSaved ? `Unsave ${sub.name}` : `Save ${sub.name}`}
          className="flex items-center justify-center gap-1.5 h-10 sm:h-9 rounded-lg text-xs font-medium transition-all duration-200 active:scale-95"
          style={
            isSaved
              ? { color: 'hsl(var(--primary))', background: 'rgba(139,92,246,0.10)', border: '1px solid rgba(139,92,246,0.25)' }
              : { color: 'hsl(var(--muted-foreground))', background: 'transparent', border: '1px solid rgba(139,92,246,0.12)' }
          }
          data-testid="subject-bookmark-button"
        >
          {isSaved ? <BookmarkCheck size={12} /> : <Bookmark size={12} />}
          {isSaved ? 'Saved' : 'Save'}
        </button>

        {/* Row 1 — right: Browse */}
        <Link
          to={subjectLandingPath}
          className="flex items-center justify-center gap-1.5 h-10 sm:h-9 rounded-lg text-xs font-medium transition-all duration-200 active:scale-95 hover:bg-white/5"
          style={{ color: 'hsl(var(--muted-foreground))', border: '1px solid rgba(139,92,246,0.12)' }}
        >
          <BookOpen size={12} />
          Browse
        </Link>

        {/* Row 2 — left: Ask AI */}
        <button
          onClick={() => onAskAI(sub.id, hasDocument, sub.name)}
          aria-label={`Ask AI about ${sub.name}`}
          className="flex items-center justify-center gap-1.5 h-10 sm:h-9 rounded-lg text-xs font-semibold text-white transition-all duration-200 hover:opacity-90 active:scale-95"
          style={{
            background: hasDocument
              ? 'linear-gradient(135deg, #059669, #10b981)'
              : 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
            boxShadow: '0 2px 10px rgba(139,92,246,0.20)',
          }}
          data-testid="subject-ask-ai-button"
        >
          <Sparkles size={12} />
          Ask AI
        </button>

        {/* Row 2 — right: WhatsApp Share */}
        <a
          href={whatsappShareUrl}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Share ${sub.name} on WhatsApp`}
          className="flex items-center justify-center gap-1.5 h-10 sm:h-9 rounded-lg text-xs font-medium transition-all duration-200 active:scale-95 hover:bg-white/5"
          style={{ color: '#25D366', border: '1px solid rgba(37,211,102,0.22)' }}
          data-testid="subject-whatsapp-share"
        >
          <Share2 size={12} />
          Share
        </a>
      </div>
    </div>
  );
});

export default function LibraryPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();

  const [searchQuery, setSearchQuery]   = useState('');
  const [activeFilter, setActiveFilter] = useState('all');
  const [selectedBoardSlug, setSelectedBoardSlug] = useState('all');
  const [selectedClassSlug, setSelectedClassSlug] = useState('all');

  const { data: bundle, isLoading: bundleLoading, isFetching, refetch: refetchBundle } = useLibraryBundle();
  const subjects    = bundle?.subjects  || [];
  const boards      = bundle?.boards    || [];
  const classes     = bundle?.classes   || [];
  const streams     = bundle?.streams   || [];
  const allChapters = bundle?.chapters  || [];
  const { data: savedSubjects = [] } = useSavedSubjects(user);
  const toggleSaved = useToggleSavedSubject();

  // Run the onboarding auto-filter exactly once when streams first load
  // Prefer user object from auth context; fall back to localStorage
  const onboardingApplied = useRef(false);
  useEffect(() => {
    if (onboardingApplied.current || !streams.length) return;
    onboardingApplied.current = true;

    // Try user object first (most up-to-date)
    if (user?.stream_id) {
      const stream = streams.find((s) => s.id === user.stream_id);
      if (stream?.slug) { setActiveFilter(stream.slug); return; }
    }

    // Fall back to localStorage
    const profile = getOnboardingProfile();
    if (profile?.stream_id) {
      const stream = streams.find((s) => s.id === profile.stream_id);
      if (stream?.slug) setActiveFilter(stream.slug);
    }
  }, [streams, user]);

  useEffect(() => {
    const handleContentUploaded = () => {
      refetchBundle();
    };
    window.addEventListener('content-uploaded', handleContentUploaded);
    return () => window.removeEventListener('content-uploaded', handleContentUploaded);
  }, [refetchBundle]);

  const streamMap = useMemo(() => new Map(streams.map(s => [s.id, s])), [streams]);
  const classMap = useMemo(() => new Map(classes.map(c => [c.id, c])), [classes]);
  const boardMap = useMemo(() => new Map(boards.map(b => [b.id, b])), [boards]);

  const chaptersBySubject = useMemo(() => {
    const map = new Map();
    for (const ch of allChapters) {
      if (!ch.subject_id) continue;
      if (!map.has(ch.subject_id)) map.set(ch.subject_id, []);
      map.get(ch.subject_id).push(ch);
    }
    return map;
  }, [allChapters]);

  const enrichedSubjects = useMemo(() => {
    return subjects.map((sub) => {
      const stream = streamMap.get(sub.stream_id);
      const cls = classMap.get(stream?.class_id);
      const board = boardMap.get(cls?.board_id);
      return {
        ...sub,
        boardName: board?.name || '',
        className: cls?.name || '',
        streamName: stream?.name || '',
        boardSlug: board?.slug || '',
        classSlug: cls?.slug || '',
        streamSlug: stream?.slug || '',
      };
    });
  }, [subjects, streamMap, classMap, boardMap]);

  const savedSubjectsSet = useMemo(() => new Set(savedSubjects), [savedSubjects]);
  const dynamicStreamChips = useMemo(() => {
    const streamSlugs = new Set();
    const chips = [];
    const filtered = enrichedSubjects.filter((sub) => {
      if (selectedBoardSlug !== 'all' && sub.boardSlug !== selectedBoardSlug) return false;
      if (selectedClassSlug !== 'all' && sub.classSlug !== selectedClassSlug) return false;
      return true;
    });
    for (const sub of filtered) {
      if (sub.streamSlug && !streamSlugs.has(sub.streamSlug)) {
        streamSlugs.add(sub.streamSlug);
        chips.push({ id: sub.streamSlug, label: sub.streamName || sub.streamSlug });
      }
    }
    return chips;
  }, [enrichedSubjects, selectedBoardSlug, selectedClassSlug]);

  const allFilterChips = useMemo(() => [...FILTER_CHIPS, ...dynamicStreamChips], [dynamicStreamChips]);

  const filteredSubjects = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return enrichedSubjects.filter((sub) => {
      if (sub.status && sub.status !== 'published') return false;
      if (selectedBoardSlug !== 'all' && sub.boardSlug !== selectedBoardSlug) return false;
      if (selectedClassSlug !== 'all' && sub.classSlug !== selectedClassSlug) return false;
      if (activeFilter === 'saved') {
        if (!savedSubjectsSet.has(sub.id)) return false;
      } else if (activeFilter !== 'all') {
        if (sub.streamSlug !== activeFilter) return false;
      }
      if (q) {
        const subChapters = chaptersBySubject.get(sub.id) || [];
        const inName    = sub.name?.toLowerCase().includes(q);
        const inDesc    = sub.description?.toLowerCase().includes(q);
        const inTags    = Array.isArray(sub.tags) && sub.tags.some((t) => t.toLowerCase().includes(q));
        const inClass   = sub.className?.toLowerCase().includes(q);
        const inStream  = sub.streamName?.toLowerCase().includes(q);
        const inBoard   = sub.boardName?.toLowerCase().includes(q);
        const inChapter = subChapters.some((ch) => ch.title?.toLowerCase().includes(q));
        if (!inName && !inDesc && !inTags && !inClass && !inStream && !inBoard && !inChapter) return false;
      }
      return true;
    });
  }, [enrichedSubjects, activeFilter, searchQuery, savedSubjectsSet, selectedBoardSlug, selectedClassSlug, chaptersBySubject]);

  useEffect(() => {
    if (!filteredSubjects.length) return;
    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.id = 'library-jsonld';
    script.text = JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'ItemList',
      name: 'AHSEC Subject Library',
      itemListElement: filteredSubjects.map((s, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        name: s.name,
        url: s.boardSlug && s.classSlug && s.streamSlug && s.slug
          ? `https://syrabit.ai/${s.boardSlug}/${s.classSlug}/${s.streamSlug}/${s.slug}`
          : `https://syrabit.ai/subject/${s.id}`,
      })),
    });
    const existing = document.getElementById('library-jsonld');
    if (existing) existing.remove();
    document.head.appendChild(script);
    return () => { const el = document.getElementById('library-jsonld'); if (el) el.remove(); };
  }, [filteredSubjects]);

  const handleAskAI = useCallback((subjectId, hasDocument = false, subjectName = '') => {
    try { Analytics.chatStart(subjectId, subjectName, 'openai/gpt-oss-20b'); } catch {}
    const params = new URLSearchParams({ subject: subjectId });
    if (hasDocument) params.set('document_id', subjectId);
    navigate(`/chat?${params.toString()}`);
  }, [navigate]);

  const handleResetFilters = useCallback(() => {
    setSearchQuery('');
    setActiveFilter('all');
    setSelectedBoardSlug('all');
    setSelectedClassSlug('all');
  }, []);

  const handleRefetchSubjects = useCallback(async () => {
    await refetchBundle();
    toast.success('Browser refreshed');
  }, [refetchBundle]);

  const handleSearchChange = useCallback((e) => {
    setSearchQuery(e.target.value);
  }, []);

  const handleFilterChange = useCallback((filterId) => {
    setActiveFilter(filterId);
  }, []);

  const handleSearchClear = useCallback(() => {
    setSearchQuery('');
  }, []);

  if (bundleLoading) {
    return (
      <AppLayout pageTitle="Library" hideNavbar>
        <PageMeta
          title="AHSEC Subject Library"
          description="Explore AHSEC Class 11-12 and Degree subjects. AI-powered notes, chapters, and exam preparation for Assam students."
          url="https://syrabit.ai/library"
        />
        <LibrarySkeleton />
      </AppLayout>
    );
  }

  return (
    <AppLayout pageTitle="Library" hideNavbar>
      <Toaster richColors position="top-right" />
      <PageMeta
        title="AHSEC Subject Library"
        description="Explore AHSEC Class 11-12 and Degree subjects. AI-powered notes, chapters, and exam preparation for Assam students."
        url="https://syrabit.ai/library"
      />
      <div className="flex flex-col h-full w-full overflow-hidden">

        {/* ── Sticky controls header ───────────────────────────────── */}
        <div
          className="sticky top-0 shrink-0 w-full z-20"
          style={{
            background: 'var(--background)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
            borderBottom: '1px solid rgba(139,92,246,0.08)',
          }}
        >
          <div className="w-full max-w-6xl mx-auto px-4 md:px-6 pt-5 pb-3 space-y-3">

            {/* Title + Refresh */}
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <h1
                  className="text-foreground shimmer-text"
                  style={{ fontSize: 'clamp(1.15rem, 4vw, 1.5rem)', fontWeight: 700, lineHeight: 1.3 }}
                >
                  Your Educational Browser
                </h1>
                <p className="text-xs sm:text-sm text-muted-foreground mt-1">
                  Browse {subjects.length} subjects · {allChapters.length} lessons
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                  title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
                  aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
                  className="h-9 w-9 rounded-xl flex items-center justify-center text-muted-foreground hover:text-primary hover:bg-primary/10 transition-all duration-200"
                >
                  {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
                </button>
                <button
                  onClick={handleRefetchSubjects}
                  disabled={isFetching}
                  className="h-9 px-3.5 rounded-xl text-xs font-medium text-white bg-violet-600 hover:bg-violet-500 disabled:opacity-60 transition-all flex items-center gap-1.5 active:scale-95"
                >
                  <RefreshCw size={13} className={isFetching ? 'animate-spin' : ''} />
                  {isFetching ? 'Updating…' : 'Refresh'}
                </button>
              </div>
            </div>

            {/* Search */}
            <div className="relative group/search">
              <Search
                className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none transition-colors text-muted-foreground group-focus-within/search:text-primary"
                aria-hidden="true"
              />
              <input
                type="text"
                value={searchQuery}
                onChange={handleSearchChange}
                aria-label="Search subjects"
                placeholder="Search subjects, topics, chapters..."
                className="w-full h-11 pl-10 pr-4 rounded-xl text-sm text-foreground outline-none transition-all focus:ring-2 focus:ring-primary/20"
                style={{
                  background: 'var(--card)',
                  border: '1px solid rgba(139,92,246,0.15)',
                  color: 'hsl(var(--foreground))',
                }}
                data-testid="library-search-input"
              />
              {searchQuery && (
                <button
                  onClick={handleSearchClear}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-foreground text-xs px-1.5 py-0.5 rounded transition-colors"
                  aria-label="Clear search"
                  data-testid="library-search-clear"
                >
                  Clear
                </button>
              )}
            </div>

          </div>
        </div>

        {/* ── Scrollable cards area ─────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto">
          <div className="w-full max-w-6xl mx-auto px-4 md:px-6 py-5">

            {/* Filter chips */}
            <div
              role="group"
              aria-label="Subject filters"
              className="flex gap-2 overflow-x-auto pb-4 no-scrollbar"
              data-testid="library-filter-chips"
            >
              {allFilterChips.map((chip) => (
                <FilterChip
                  key={chip.id}
                  chip={chip}
                  isActive={chip.id === activeFilter}
                  onClick={() => handleFilterChange(chip.id)}
                />
              ))}
            </div>
            {filteredSubjects.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div
                  className="w-20 h-20 rounded-2xl flex items-center justify-center mb-5"
                  style={{
                    background: 'linear-gradient(135deg, rgba(124,58,237,0.08), rgba(139,92,246,0.04))',
                    border: '1px solid rgba(139,92,246,0.12)',
                  }}
                >
                  {activeFilter === 'saved'
                    ? <Bookmark className="w-9 h-9" style={{ color: 'hsl(var(--primary) / 0.4)' }} />
                    : <BookOpen className="w-9 h-9" style={{ color: 'hsl(var(--muted-foreground) / 0.3)' }} />
                  }
                </div>

                {activeFilter === 'saved' && !user ? (
                  <>
                    <h3 className="text-foreground font-semibold text-lg">Sign in to see saved subjects</h3>
                    <p className="text-sm text-muted-foreground/60 mt-1.5 max-w-xs">
                      Create a free account to bookmark subjects and track your progress
                    </p>
                    <Link
                      to="/signup"
                      className="mt-5 px-5 py-2 rounded-xl text-sm text-white font-medium transition-all duration-200 active:scale-95"
                      style={{ background: 'hsl(var(--primary))', boxShadow: '0 0 20px hsl(var(--primary)/0.3)' }}
                    >
                      Sign up free
                    </Link>
                  </>
                ) : activeFilter === 'saved' && user ? (
                  <>
                    <h3 className="text-foreground font-semibold text-lg">No saved subjects yet</h3>
                    <p className="text-sm text-muted-foreground/60 mt-1.5 max-w-xs">
                      Tap the bookmark on any subject card to save it here for quick access
                    </p>
                    <button
                      onClick={() => setActiveFilter('all')}
                      className="mt-5 px-5 py-2 rounded-xl text-sm text-white font-medium transition-all duration-200 active:scale-95"
                      style={{ background: 'hsl(var(--primary))', boxShadow: '0 0 20px hsl(var(--primary)/0.3)' }}
                    >
                      Browse all subjects
                    </button>
                  </>
                ) : (
                  <>
                    <h3 className="text-foreground font-semibold text-lg">No subjects found</h3>
                    <p className="text-sm text-muted-foreground/60 mt-1.5 max-w-xs">
                      {searchQuery
                        ? `No results for "${searchQuery}" — try a different term or clear the search`
                        : 'Try adjusting your filters to discover more subjects'}
                    </p>
                    {(searchQuery || activeFilter !== 'all' || selectedBoardSlug !== 'all' || selectedClassSlug !== 'all') && (
                      <button
                        onClick={handleResetFilters}
                        className="mt-5 px-4 py-2 rounded-xl text-sm text-primary hover:text-white transition-all duration-200 active:scale-95"
                        style={{ border: '1px solid rgba(139,92,246,0.25)', background: 'rgba(139,92,246,0.06)' }}
                        data-testid="library-reset-filters-button"
                      >
                        Reset all filters
                      </button>
                    )}
                  </>
                )}
              </div>
            ) : (
              <div
                className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5"
                data-testid="library-subject-grid"
              >
                {filteredSubjects.map((sub, index) => (
                  <SubjectCard
                    key={sub.id}
                    sub={sub}
                    chapters={chaptersBySubject.get(sub.id) || []}
                    isSaved={savedSubjects.includes(sub.id)}
                    onToggleSave={(id) => toggleSaved.mutate(id)}
                    onAskAI={handleAskAI}
                    index={index}
                  />
                ))}
              </div>
            )}
          </div>
          <CmsDocsSection />
          <CmsPostsGrid />
        </div>

      </div>
    </AppLayout>
  );
}
