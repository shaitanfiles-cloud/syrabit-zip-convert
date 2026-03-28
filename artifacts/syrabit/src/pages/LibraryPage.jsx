import { useState, useEffect, useMemo, useCallback, memo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Search, Bookmark, BookmarkCheck,
  BookOpen, Layers, ChevronRight, Sparkles, FileText,
  Share2, Copy, Check as CheckIcon, X as XIcon,
  ExternalLink, Globe as GlobeIcon, Lock,
} from 'lucide-react';
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
  return (
    <div className="w-full max-w-6xl mx-auto px-4 md:px-6 py-5 space-y-5">
      <div className="flex gap-2 animate-pulse">
        {[80, 96, 72, 88].map((w) => (
          <div
            key={w}
            className="h-9 rounded-xl flex-shrink-0"
            style={{ width: w, background: 'rgba(255,255,255,0.06)' }}
          />
        ))}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {[...Array(6)].map((_, i) => (
          <div
            key={i}
            className="rounded-2xl border animate-pulse"
            style={{
              background: 'rgba(255,255,255,0.04)',
              borderColor: 'rgba(139,92,246,0.07)',
            }}
          >
            <div className="h-10 rounded-t-2xl" style={{ background: 'rgba(255,255,255,0.03)' }} />
            <div className="p-4 space-y-3">
              <div className="h-5 rounded-lg w-3/4" style={{ background: 'rgba(255,255,255,0.08)' }} />
              <div className="h-3 rounded w-1/2" style={{ background: 'rgba(255,255,255,0.05)' }} />
              <div className="space-y-2">
                {[...Array(3)].map((_, j) => (
                  <div key={j} className="h-8 rounded-lg" style={{ background: 'rgba(255,255,255,0.04)' }} />
                ))}
              </div>
            </div>
          </div>
        ))}
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
              boxShadow: '0 4px 16px var(--glow-primary, rgba(139,92,246,0.35))',
            }
          : {
              color: 'hsl(var(--muted-foreground))',
              fontWeight: 400,
              background: 'var(--card)',
              border: '1px solid rgba(139,92,246,0.12)',
            }
      }
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
  const chapterCount = useMemo(() => sub.chapter_count || sub.chapterCount || chapters.length || 0, [sub.chapter_count, sub.chapterCount, chapters.length]);
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

  const visibleChapters = useMemo(() => chapters.slice(0, 6), [chapters]);
  const moreChapters = chapters.length - 6;

  return (
    <div
      className="w-full rounded-2xl overflow-hidden transition-all duration-300 group/card"
      style={{
        background: 'var(--card)',
        border: isSaved
          ? '1px solid rgba(139,92,246,0.35)'
          : '1px solid rgba(139,92,246,0.10)',
        boxShadow: isSaved
          ? '0 0 24px var(--glow-primary, rgba(139,92,246,0.12)), 0 8px 32px rgba(0,0,0,0.25)'
          : '0 4px 24px rgba(0,0,0,0.18)',
        animationDelay: `${index * 50}ms`,
      }}
      data-testid="library-subject-card"
      data-subject-id={sub.id}
    >
      {/* Browser Chrome */}
      <div
        className="flex items-center gap-2 px-3 py-2"
        style={{
          background: 'rgba(255,255,255,0.03)',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        <div className="flex gap-1.5 shrink-0">
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#ff5f57' }} />
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#ffbd2e' }} />
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#28c840' }} />
        </div>
        <Link
          to={subjectLandingPath}
          className="flex-1 flex items-center gap-1.5 h-6 px-2.5 rounded-md text-[11px] font-mono truncate transition-colors hover:bg-white/5"
          style={{
            background: 'rgba(255,255,255,0.04)',
            color: 'rgba(255,255,255,0.45)',
            border: '1px solid rgba(255,255,255,0.06)',
          }}
          title={`Open ${sub.name}`}
        >
          {hasDocument ? (
            <Lock size={9} className="shrink-0 text-emerald-400" />
          ) : (
            <GlobeIcon size={9} className="shrink-0 opacity-50" />
          )}
          <span className="truncate">{displayUrl}</span>
        </Link>
        {isSaved && (
          <BookmarkCheck size={13} className="shrink-0 text-purple-400" />
        )}
      </div>

      {/* Card Content */}
      <div className="px-4 pt-3 pb-2">
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
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-[11px] font-medium px-1.5 py-0.5 rounded" style={{ background: 'rgba(139,92,246,0.12)', color: 'hsl(var(--primary))' }}>
                  {sub.boardName}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {sub.className}
                </span>
                <span className="text-[11px] text-muted-foreground/60">·</span>
                <span className="text-[11px] text-muted-foreground/60">
                  {sub.streamName}
                </span>
              </div>
            </div>
          </div>
        </Link>

        {sub.description && (
          <p
            className="text-muted-foreground text-xs leading-relaxed mb-2"
            style={{
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {sub.description}
          </p>
        )}

        {visibleTags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
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
          className="mx-3 mb-3 rounded-xl overflow-hidden"
          style={{
            background: 'rgba(139,92,246,0.03)',
            border: '1px solid rgba(139,92,246,0.08)',
          }}
        >
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
                className="flex items-center gap-2 px-3 py-2 text-xs transition-all hover:bg-purple-500/8 group/lesson"
                style={{ borderBottom: i < visibleChapters.length - 1 ? '1px solid rgba(139,92,246,0.05)' : 'none' }}
                title={`${ch.title} — ${sub.name}`}
              >
                <span
                  className="w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-bold shrink-0"
                  style={{ background: 'rgba(139,92,246,0.10)', color: 'hsl(var(--primary))' }}
                >
                  {ch.order_index ?? i + 1}
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
      )}

      {/* Action Bar */}
      <div
        className="flex items-center gap-1.5 px-3 py-2.5"
        style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}
      >
        <button
          onClick={() => { onToggleSave(sub.id); try { Analytics.subjectBookmarked(sub.name, !isSaved); } catch {} }}
          aria-label={isSaved ? `Unsave ${sub.name}` : `Save ${sub.name}`}
          className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-medium transition-all duration-200 active:scale-95"
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

        <button
          onClick={() => onAskAI(sub.id, hasDocument, sub.name)}
          aria-label={`Ask AI about ${sub.name}`}
          className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-semibold text-white transition-all duration-200 hover:opacity-90 active:scale-95 ml-auto"
          style={{
            background: hasDocument
              ? 'linear-gradient(135deg, #059669, #10b981)'
              : 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
            boxShadow: '0 2px 10px rgba(139,92,246,0.25)',
          }}
          data-testid="subject-ask-ai-button"
        >
          <Sparkles size={12} />
          Ask AI
        </button>

        <Link
          to={subjectLandingPath}
          className="flex items-center gap-1 h-8 px-3 rounded-lg text-xs font-medium transition-all duration-200 active:scale-95 hover:bg-white/5"
          style={{ color: 'hsl(var(--muted-foreground))', border: '1px solid rgba(139,92,246,0.12)' }}
        >
          <BookOpen size={12} />
          Browse
        </Link>
      </div>
    </div>
  );
});

export default function LibraryPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [searchQuery, setSearchQuery]   = useState('');
  const [activeFilter, setActiveFilter] = useState('all');
  const [selectedBoardSlug, setSelectedBoardSlug] = useState('all');
  const [selectedClassSlug, setSelectedClassSlug] = useState('all');

  const { data: bundle, isLoading: bundleLoading, refetch: refetchBundle } = useLibraryBundle();
  const subjects    = bundle?.subjects  || [];
  const boards      = bundle?.boards    || [];
  const classes     = bundle?.classes   || [];
  const streams     = bundle?.streams   || [];
  const allChapters = bundle?.chapters  || [];
  const { data: savedSubjects = [] } = useSavedSubjects(user);
  const toggleSaved = useToggleSavedSubject();

  useEffect(() => {
    if (!streams.length) return;
    const profile = getOnboardingProfile();
    if (profile?.stream_id) {
      const stream = streams.find((s) => s.id === profile.stream_id);
      if (stream?.slug) setActiveFilter(stream.slug);
    }
  }, [streams.length]);

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
    return enrichedSubjects.filter((sub) => {
      if (sub.status && sub.status !== 'published') return false;
      if (selectedBoardSlug !== 'all' && sub.boardSlug !== selectedBoardSlug) return false;
      if (selectedClassSlug !== 'all' && sub.classSlug !== selectedClassSlug) return false;
      if (activeFilter === 'all') {
      } else if (activeFilter === 'saved') {
        if (!savedSubjectsSet.has(sub.id)) return false;
      } else {
        if (sub.streamSlug !== activeFilter) return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const inName = sub.name?.toLowerCase().includes(q);
        const inTags = Array.isArray(sub.tags) && sub.tags.some((t) => t.toLowerCase().includes(q));
        const inClass = sub.className?.toLowerCase().includes(q);
        const inStream = sub.streamName?.toLowerCase().includes(q);
        const inBoard = sub.boardName?.toLowerCase().includes(q);
        if (!inName && !inTags && !inClass && !inStream && !inBoard) return false;
      }
      return true;
    });
  }, [enrichedSubjects, activeFilter, searchQuery, savedSubjectsSet, selectedBoardSlug, selectedClassSlug]);

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

  const handleRefetchSubjects = useCallback(() => {
    refetchBundle();
    toast.success('Library updated!');
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
      <AppLayout pageTitle="Library">
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
    <AppLayout pageTitle="Library">
      <Toaster richColors position="top-right" />
      <PageMeta
        title="AHSEC Subject Library"
        description="Explore AHSEC Class 11-12 and Degree subjects. AI-powered notes, chapters, and exam preparation for Assam students."
        url="https://syrabit.ai/library"
      />
      <div className="flex flex-col h-full w-full overflow-x-hidden">
        <div className="w-full max-w-6xl mx-auto px-4 md:px-6 py-5 space-y-5">

          <div className="flex items-start justify-between gap-4">
            <div>
              <h1
                className="text-foreground shimmer-text"
                style={{ fontSize: '1.5rem', fontWeight: 700, lineHeight: 1.3 }}
              >
                Your Educational Browser
              </h1>
              <p className="text-sm text-muted-foreground mt-1">
                Browse {subjects.length} subjects · {allChapters.length} lessons
              </p>
            </div>

            <button
              onClick={handleRefetchSubjects}
              className="h-9 px-3.5 rounded-xl text-xs font-medium text-white bg-violet-600 hover:bg-violet-500 transition-all flex items-center gap-1.5"
            >
              <Layers size={13} />
              Refresh
            </button>
          </div>

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
                backdropFilter: 'blur(20px)',
                WebkitBackdropFilter: 'blur(20px)',
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

          <div className="flex gap-3 flex-wrap">
            <select
              value={selectedBoardSlug}
              onChange={(e) => { setSelectedBoardSlug(e.target.value); setSelectedClassSlug('all'); setActiveFilter('all'); }}
              aria-label="Filter by board"
              className="h-9 px-3 rounded-xl text-sm outline-none transition-all focus:ring-2 focus:ring-primary/20"
              style={{
                background: 'var(--card)',
                border: '1px solid rgba(139,92,246,0.15)',
                color: 'hsl(var(--foreground))',
                minWidth: 120,
              }}
            >
              <option value="all">All Boards</option>
              {boards.map((b) => (
                <option key={b.id} value={b.slug}>{b.name}</option>
              ))}
            </select>
            <select
              value={selectedClassSlug}
              onChange={(e) => { setSelectedClassSlug(e.target.value); setActiveFilter('all'); }}
              aria-label="Filter by class"
              className="h-9 px-3 rounded-xl text-sm outline-none transition-all focus:ring-2 focus:ring-primary/20"
              style={{
                background: 'var(--card)',
                border: '1px solid rgba(139,92,246,0.15)',
                color: 'hsl(var(--foreground))',
                minWidth: 120,
              }}
            >
              <option value="all">All Classes</option>
              {classes
                .filter((c) => selectedBoardSlug === 'all' || boards.find((b) => b.slug === selectedBoardSlug)?.id === c.board_id)
                .map((c) => (
                  <option key={c.id} value={c.slug}>{c.name}</option>
                ))}
            </select>
          </div>

          <div
            role="group"
            aria-label="Subject filters"
            className="flex gap-2 overflow-x-auto pb-0.5 no-scrollbar"
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
            <div className="col-span-full flex flex-col items-center justify-center py-20 text-center">
              <div
                className="w-20 h-20 rounded-2xl flex items-center justify-center mb-5"
                style={{
                  background: 'linear-gradient(135deg, rgba(124,58,237,0.08), rgba(139,92,246,0.04))',
                  border: '1px solid rgba(139,92,246,0.12)',
                }}
              >
                <BookOpen className="w-10 h-10" style={{ color: 'hsl(var(--muted-foreground) / 0.3)' }} />
              </div>
              <h3 className="text-foreground font-semibold text-lg">No subjects found</h3>
              <p className="text-sm text-muted-foreground/60 mt-1.5 max-w-xs">
                Try adjusting your search or filters to discover more subjects
              </p>
              {(searchQuery || activeFilter !== 'all') && (
                <button
                  onClick={handleResetFilters}
                  className="mt-4 px-4 py-2 rounded-xl text-sm text-primary hover:text-white transition-all duration-200 active:scale-95"
                  style={{
                    border: '1px solid rgba(139,92,246,0.25)',
                    background: 'rgba(139,92,246,0.06)',
                  }}
                  data-testid="library-reset-filters-button"
                >
                  Reset filters
                </button>
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
      </div>
    </AppLayout>
  );
}
