/**
 * LibraryPage — /library
 */
import { useState, useEffect, useMemo, useCallback, memo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Search, Bookmark, BookmarkCheck,
  BookOpen, Layers, ChevronRight, Sparkles, FileText,
  Share2, Copy, Check as CheckIcon, X as XIcon,
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

// ── Inline Globe SVG (no lucide Globe import in this file per spec) ──────────
function Globe({ className }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
      <path d="M2 12h20" />
    </svg>
  );
}

// ── Thumbnail gradient maps (for subjects without a real thumbnailUrl) ────────
const THUMB_GRADIENTS = {
  math:      ['#4f46e5', '#7c3aed'],
  physics:   ['#2563eb', '#0891b2'],
  chemistry: ['#059669', '#0d9488'],
  biology:   ['#16a34a', '#15803d'],
  arts:      ['#d97706', '#b45309'],
  science:   ['#7c3aed', '#4f46e5'],
};

// ── Filter chips — 11 total covering both boards ──────────────────────────────
const FILTER_CHIPS = [
  { id: 'all',         label: 'All'      },
  { id: 'saved',       label: '★ Saved'  },
];

// ── Helpers ──────────────────────────────────────────────────────────────────
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

// ── Skeleton screen ───────────────────────────────────────────────────────────
function LibrarySkeleton() {
  return (
    <div className="w-full max-w-3xl mx-auto px-4 md:px-6 py-5 space-y-5">
      {/* Filter bar skeleton */}
      <div className="flex gap-2 animate-pulse">
        {[80, 96, 72, 88].map((w) => (
          <div
            key={w}
            className="h-9 rounded-xl flex-shrink-0"
            style={{ width: w, background: 'rgba(255,255,255,0.06)' }}
          />
        ))}
      </div>
      {/* Card grid skeleton */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {[...Array(6)].map((_, i) => (
          <div
            key={i}
            className="rounded-2xl border p-4 space-y-3 animate-pulse"
            style={{
              background: 'rgba(255,255,255,0.04)',
              borderColor: 'rgba(139,92,246,0.07)',
            }}
          >
            <div className="h-28 rounded-xl" style={{ background: 'rgba(255,255,255,0.06)' }} />
            <div className="h-4 rounded-lg w-3/4" style={{ background: 'rgba(255,255,255,0.08)' }} />
            <div className="h-3 rounded w-1/2" style={{ background: 'rgba(255,255,255,0.05)' }} />
            <div className="flex gap-2">
              <div className="h-5 w-16 rounded-full" style={{ background: 'rgba(255,255,255,0.05)' }} />
              <div className="h-5 w-20 rounded-full" style={{ background: 'rgba(255,255,255,0.05)' }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Filter Chip (memoized) ────────────────────────────────────────────────────
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

// ── Subject Card (memoized with deep optimization) ────────────────────────────
const SubjectCard = memo(function SubjectCard({ sub, chapters = [], isSaved, onToggleSave, onOpen, onAskAI, onSeoNav, index }) {
  const [showChapters, setShowChapters] = useState(false);
  const thumbColors = useMemo(() => THUMB_GRADIENTS[sub.gradient] || THUMB_GRADIENTS.math, [sub.gradient]);
  const hasThumbnail = useMemo(() => !!sub.thumbnailUrl, [sub.thumbnailUrl]);
  const tags = useMemo(() => Array.isArray(sub.tags) ? sub.tags : [], [sub.tags]);
  const visibleTags = useMemo(() => tags.slice(0, 4), [tags]);
  const overflowCount = useMemo(() => tags.length - 4, [tags.length]);
  const chapterCount = useMemo(() => sub.chapter_count || sub.chapterCount || 0, [sub.chapter_count, sub.chapterCount]);
  const totalTokens = useMemo(() => sub.total_tokens || sub.totalTokens || 0, [sub.total_tokens, sub.totalTokens]);
  const totalChats = useMemo(() => sub.total_chats || sub.totalChats || 0, [sub.total_chats, sub.totalChats]);
  const hasDocument = useMemo(() => sub.has_document === true, [sub.has_document]);
  const seoPath = useMemo(() => 
    sub.boardSlug && sub.classSlug && sub.streamSlug && sub.slug
      ? `/${sub.boardSlug}/${sub.classSlug}/${sub.streamSlug}/${sub.slug}`
      : null,
    [sub.boardSlug, sub.classSlug, sub.streamSlug, sub.slug]
  );

  // ── Share state ────────────────────────────────────────────────────────────
  const [showShare, setShowShare] = useState(false);
  const [copied, setCopied] = useState(false);

  const shareUrl = useMemo(() => {
    const path = seoPath || `/subject/${sub.id}`;
    return `${window.location.origin}${path}`;
  }, [seoPath, sub.id]);

  const handleCopyLink = () => {
    navigator.clipboard.writeText(shareUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      try { Analytics.subjectShared(sub.name, shareUrl); } catch {}
    });
  };

  return (
    <div
      className="w-full rounded-2xl overflow-hidden card-3d transition-all duration-300"
      style={{
        background: 'var(--card)',
        backdropFilter: 'blur(20px) saturate(1.5)',
        WebkitBackdropFilter: 'blur(20px) saturate(1.5)',
        border: isSaved
          ? '1px solid rgba(139,92,246,0.35)'
          : '1px solid rgba(139,92,246,0.12)',
        boxShadow: isSaved
          ? '0 0 20px var(--glow-primary, rgba(139,92,246,0.15)), 0 4px 24px rgba(0,0,0,0.2)'
          : '0 4px 24px rgba(0,0,0,0.15)',
        animationDelay: `${index * 60}ms`,
      }}
      data-testid="library-subject-card"
      data-subject-id={sub.id}
    >
      {/* ── Thumbnail + Description as SEO link ── */}
      <Link
        to={seoPath || `/subject/${sub.id}`}
        className="block group/card"
        title={`${sub.name} — ${[sub.boardName, sub.className, sub.streamName].filter(Boolean).join(' ')} Notes & Study Material`}
      >
        <div className="relative h-44 overflow-hidden">
          {hasDocument && (
            <div
              className="absolute top-3 left-3 z-10 flex items-center gap-1 px-2 py-1 rounded-lg text-white text-[10px] font-semibold"
              style={{ background: 'rgba(16,185,129,0.75)', backdropFilter: 'blur(8px)', border: '1px solid rgba(16,185,129,0.35)' }}
            >
              <FileText size={10} aria-hidden="true" /> DOC
            </div>
          )}
          {hasThumbnail ? (
            <img
              src={sub.thumbnailUrl}
              alt={`${sub.name} — ${sub.boardName} ${sub.className} ${sub.streamName} | Syrabit`}
              className="w-full h-full object-cover transition-transform duration-500 group-hover/card:scale-105"
              loading="lazy"
              decoding="async"
            />
          ) : (
            <div
              className="w-full h-full transition-transform duration-500 group-hover/card:scale-105"
              style={{
                background: `linear-gradient(135deg, ${thumbColors[0]}, ${thumbColors[1]})`,
              }}
            >
              <div className="absolute inset-0 flex items-center justify-center">
                <span aria-hidden="true" style={{ fontSize: '3rem', opacity: 0.85 }}>{sub.icon || '📚'}</span>
              </div>
            </div>
          )}

          <div
            className="absolute inset-0"
            style={{
              background: 'linear-gradient(to top, rgba(0,0,0,0.80), rgba(0,0,0,0.30), rgba(0,0,0,0.10))',
            }}
          />

          <div
            className="absolute top-3 left-3 px-2.5 py-1 rounded-lg text-white text-xs font-semibold"
            style={{
              background: 'rgba(0,0,0,0.50)',
              backdropFilter: 'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
              border: '1px solid rgba(255,255,255,0.10)',
            }}
          >
            {sub.streamName || '—'}
          </div>

          <div
            className="absolute top-3 right-3 px-2.5 py-1 rounded-lg text-white text-xs font-semibold"
            style={{
              background: 'linear-gradient(135deg, rgba(124,58,237,0.85), rgba(139,92,246,0.85))',
              backdropFilter: 'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
              boxShadow: '0 2px 10px rgba(124,58,237,0.3)',
            }}
          >
            {sub.className || '—'}
          </div>

          {isSaved && (
            <div
              className="absolute top-3 flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-white"
              style={{
                right: '4.5rem',
                background: 'rgba(124,58,237,0.70)',
                backdropFilter: 'blur(12px)',
                WebkitBackdropFilter: 'blur(12px)',
              }}
            >
              <BookmarkCheck size={12} />
            </div>
          )}

          <div className="absolute bottom-3 left-3.5 right-3.5">
            <h3
              className="text-white group-hover/card:text-purple-200 transition-colors"
              style={{
                fontSize: '1.05rem',
                fontWeight: 700,
                lineHeight: 1.3,
                textShadow: '0 1px 6px rgba(0,0,0,0.5)',
              }}
            >
              {sub.name}
            </h3>
            <p className="text-white/65 mt-0.5" style={{ fontSize: '0.78rem' }}>
              {[sub.boardName, sub.className, sub.streamName].filter(Boolean).join(' · ')}
            </p>
          </div>
        </div>

        <div className="px-4 pt-3.5 pb-2">
          <p
            className="text-muted-foreground leading-relaxed group-hover/card:text-foreground/70 transition-colors"
            style={{
              fontSize: '0.82rem',
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {sub.description || 'No description available.'}
          </p>

          <div className="flex items-center gap-4 text-xs text-muted-foreground mt-2">
            {totalTokens > 0 && (
              <span>{(totalTokens / 1000).toFixed(0)}K tokens</span>
            )}
            {totalChats > 0 && (
              <span>{totalChats} chats</span>
            )}
          </div>
        </div>
      </Link>

      {/* ── Card Body (non-link) ── */}
      <div className="px-4 pb-4 space-y-3">

        {/* Chapter links */}
        {chapters.length > 0 && (
          <div>
            <button
              onClick={() => setShowChapters((v) => !v)}
              className="flex items-center gap-1.5 w-full text-left text-xs font-medium transition-colors"
              style={{ color: 'hsl(var(--muted-foreground))' }}
            >
              <Layers size={12} aria-hidden="true" style={{ color: 'hsl(var(--primary) / 0.6)' }} />
              <span>{chapters.length} Chapters</span>
              <ChevronRight
                size={12}
                className="ml-auto transition-transform duration-200"
                style={{ transform: showChapters ? 'rotate(90deg)' : 'rotate(0deg)', color: 'hsl(var(--primary) / 0.4)' }}
                aria-hidden="true"
              />
            </button>
            {showChapters && (
              <div
                className="mt-2 rounded-xl overflow-hidden"
                style={{
                  background: 'rgba(139,92,246,0.04)',
                  border: '1px solid rgba(139,92,246,0.10)',
                }}
              >
                {chapters.map((ch, i) => {
                  const chPath = sub.boardSlug && sub.classSlug && sub.slug && ch.slug
                    ? `/${sub.boardSlug}/${sub.classSlug}/${sub.slug}/${ch.slug}`
                    : `/subject/${sub.id}`;
                  return (
                    <Link
                      key={ch.id || i}
                      to={chPath}
                      className="flex items-center gap-2 px-3 py-2 text-xs transition-colors hover:bg-primary/8 group/ch"
                      style={{ borderBottom: i < chapters.length - 1 ? '1px solid rgba(139,92,246,0.06)' : 'none' }}
                      title={`${ch.title} — ${sub.name}`}
                    >
                      <span
                        className="w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-semibold shrink-0"
                        style={{ background: 'rgba(139,92,246,0.10)', color: 'hsl(var(--primary))' }}
                      >
                        {ch.order_index ?? i + 1}
                      </span>
                      <span className="text-foreground/80 group-hover/ch:text-primary truncate transition-colors">
                        {ch.title}
                      </span>
                      <ChevronRight
                        size={11}
                        className="ml-auto shrink-0 text-muted-foreground/30 group-hover/ch:text-primary transition-colors"
                        aria-hidden="true"
                      />
                    </Link>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Tags */}
        {visibleTags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {visibleTags.map((tag) => (
              <span
                key={tag}
                className="px-2.5 py-0.5 rounded-full text-xs font-medium"
                style={{
                  color: 'hsl(var(--primary))',
                  background: 'rgba(139,92,246,0.08)',
                  border: '1px solid rgba(139,92,246,0.15)',
                }}
              >
                {tag}
              </span>
            ))}
            {overflowCount > 0 && (
              <span className="px-2 py-0.5 text-xs text-muted-foreground/50">
                +{overflowCount}
              </span>
            )}
          </div>
        )}

        {/* SEO path row */}
        {seoPath && (
          <Link
            to={seoPath}
            className="group/seo flex items-center gap-1 text-xs text-muted-foreground/50 hover:text-primary/60 transition-colors"
            title={`Open ${sub.name} subject page`}
          >
            <Globe className="w-3 h-3 flex-shrink-0" aria-hidden="true" />
            <span className="truncate group-hover/seo:underline">{seoPath}</span>
          </Link>
        )}

        {/* Share URL panel — slides in above buttons when Share is active */}
        {showShare && (
          <div
            className="rounded-xl px-3 py-2.5 flex items-center gap-2"
            style={{
              background: 'rgba(139,92,246,0.07)',
              border: '1px solid rgba(139,92,246,0.22)',
            }}
          >
            {/* URL text */}
            <span
              className="flex-1 text-xs text-muted-foreground truncate font-mono select-all"
              title={shareUrl}
            >
              {shareUrl}
            </span>

            {/* Copy button */}
            <button
              onClick={handleCopyLink}
              aria-label="Copy link"
              className="flex-shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 active:scale-95"
              style={
                copied
                  ? { color: '#10b981', background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.30)' }
                  : { color: 'hsl(var(--primary))', background: 'rgba(139,92,246,0.10)', border: '1px solid rgba(139,92,246,0.25)' }
              }
              data-testid="share-copy-button"
            >
              {copied
                ? <><CheckIcon size={12} /> Copied!</>
                : <><Copy size={12} /> Copy</>
              }
            </button>

            {/* Close */}
            <button
              onClick={() => setShowShare(false)}
              aria-label="Close share"
              className="flex-shrink-0 p-1 rounded-lg text-muted-foreground/50 hover:text-muted-foreground transition-colors"
            >
              <XIcon size={13} />
            </button>
          </div>
        )}

        {/* Action buttons — 4 equal columns */}
        <div className="grid grid-cols-4 gap-1.5 pt-1">
          {/* Save / Unsave */}
          <button
            onClick={() => { onToggleSave(sub.id); try { Analytics.subjectBookmarked(sub.name, !isSaved); } catch {} }}
            aria-label={isSaved ? `Unsave ${sub.name}` : `Save ${sub.name}`}
            className="flex items-center justify-center gap-1 h-10 rounded-xl text-xs font-medium transition-all duration-200 active:scale-95"
            style={
              isSaved
                ? { color: 'hsl(var(--primary))', background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.30)' }
                : { color: 'hsl(var(--muted-foreground))', background: 'transparent', border: '1px solid rgba(139,92,246,0.15)' }
            }
            data-testid="subject-bookmark-button"
          >
            {isSaved ? 'Saved' : 'Save'}
          </button>

          {/* Open */}
          <button
            onClick={() => onOpen(sub)}
            aria-label={`Open ${sub.name}`}
            className="flex items-center justify-center gap-1 h-10 rounded-xl text-xs font-medium transition-all duration-200 active:scale-95"
            style={{ color: 'hsl(var(--muted-foreground))', background: 'transparent', border: '1px solid rgba(139,92,246,0.15)' }}
            data-testid="subject-open-button"
          >
            Open
          </button>

          {/* Ask AI — gradient button */}
          <button
            onClick={() => onAskAI(sub.id, hasDocument, sub.name)}
            aria-label={`Ask AI about ${sub.name}`}
            className="flex items-center justify-center gap-1 h-10 rounded-xl text-xs font-semibold text-white transition-all duration-200 hover:opacity-90 hover:shadow-lg active:scale-95"
            style={{
              background: hasDocument
                ? 'linear-gradient(135deg, #059669, #10b981)'
                : 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
              boxShadow: hasDocument
                ? '0 4px 18px rgba(16,185,129,0.35)'
                : '0 4px 18px var(--glow-primary, rgba(139,92,246,0.35))',
            }}
            data-testid="subject-ask-ai-button"
          >
            Ask AI
          </button>

          {/* Share */}
          <button
            onClick={() => { setShowShare((v) => !v); setCopied(false); }}
            aria-label={`Share ${sub.name}`}
            className="flex items-center justify-center gap-1 h-10 rounded-xl text-xs font-medium transition-all duration-200 active:scale-95"
            style={
              showShare
                ? { color: 'hsl(var(--primary))', background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.30)' }
                : { color: 'hsl(var(--muted-foreground))', background: 'transparent', border: '1px solid rgba(139,92,246,0.15)' }
            }
            data-testid="subject-share-button"
          >
            <Share2 size={13} />
            Share
          </button>
        </div>
      </div>
    </div>
  );
});

// ── LibraryPage ───────────────────────────────────────────────────────────────
export default function LibraryPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [searchQuery, setSearchQuery]   = useState('');
  const [activeFilter, setActiveFilter] = useState('all');
  const [selectedBoardSlug, setSelectedBoardSlug] = useState('all');
  const [selectedClassSlug, setSelectedClassSlug] = useState('all');

  // ── Single API call for all library data ─────────────────────────────────
  const { data: bundle, isLoading: bundleLoading, refetch: refetchBundle } = useLibraryBundle();
  const subjects    = bundle?.subjects  || [];
  const boards      = bundle?.boards    || [];
  const classes     = bundle?.classes   || [];
  const streams     = bundle?.streams   || [];
  const allChapters = bundle?.chapters  || [];
  const { data: savedSubjects = [] } = useSavedSubjects(user);
  const toggleSaved = useToggleSavedSubject();

  // ── Auto-select stream from onboarding ───────────────────────────────
  useEffect(() => {
    if (!streams.length) return;
    const profile = getOnboardingProfile();
    if (profile?.stream_id) {
      const stream = streams.find((s) => s.id === profile.stream_id);
      if (stream?.slug) setActiveFilter(stream.slug);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streams.length]);

  // ── Listen for content uploads to refresh subjects ───────────────────────────
  useEffect(() => {
    const handleContentUploaded = () => {
      
      refetchBundle();
    };
    
    window.addEventListener('content-uploaded', handleContentUploaded);
    return () => window.removeEventListener('content-uploaded', handleContentUploaded);
  }, [refetchBundle]);

  // ── Data enrichment pipeline (memoized for O(1) lookup) ──────────────────
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

  // ── Filter + search pipeline (memoized to avoid re-filtering on re-render) ──
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

  // ── JSON-LD ItemList schema ───────────────────────────────────────────────
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

  // ── Handlers (memoized to avoid re-creating on every render) ───────────────
  const handleOpen = useCallback((sub) => {
    try { Analytics.subjectOpened(sub.id, sub.name); } catch {}
    navigate(`/subject/${sub.id}`);
  }, [navigate]);

  const handleAskAI = useCallback((subjectId, hasDocument = false, subjectName = '') => {
    try { Analytics.chatStart(subjectId, subjectName, 'openai/gpt-oss-20b'); } catch {}
    const params = new URLSearchParams({ subject: subjectId });
    if (hasDocument) params.set('document_id', subjectId);
    navigate(`/chat?${params.toString()}`);
  }, [navigate]);

  const handleSeoNav = useCallback((path) => navigate(path), [navigate]);
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

  // ── Loading skeleton ──────────────────────────────────────────────────────
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

  // ── Loaded state ──────────────────────────────────────────────────────────
  return (
    <AppLayout pageTitle="Library">
      <Toaster richColors position="top-right" />
      <PageMeta
        title="AHSEC Subject Library"
        description="Explore AHSEC Class 11-12 and Degree subjects. AI-powered notes, chapters, and exam preparation for Assam students."
        url="https://syrabit.ai/library"
      />
      <div className="flex flex-col h-full w-full overflow-x-hidden">
        <div className="w-full max-w-3xl mx-auto px-4 md:px-6 py-5 space-y-5">

          {/* ── Header row ── */}
          <div className="flex items-start justify-between">
            <div>
              <h1
                className="text-foreground shimmer-text"
                style={{ fontSize: '1.6rem', fontWeight: 700, lineHeight: 1.3 }}
              >
                AHSEC & DEGREE<br />
                STUDY LIBRARY
              </h1>
            </div>

            <button
              onClick={handleRefetchSubjects}
              className="h-10 px-4 rounded-xl text-sm font-medium text-white bg-violet-600 hover:bg-violet-500 transition-all flex items-center gap-2"
            >
              <Layers size={14} />
              Update Library
            </button>
          </div>

          {/* ── Search input ── */}
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
              placeholder="Search subjects, topics..."
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

          {/* ── Board / Class dropdown filters ── */}
          <div className="flex gap-3">
            <select
              value={selectedBoardSlug}
              onChange={(e) => { setSelectedBoardSlug(e.target.value); setSelectedClassSlug('all'); setActiveFilter('all'); }}
              aria-label="Filter by board"
              className="h-10 px-3 rounded-xl text-sm outline-none transition-all focus:ring-2 focus:ring-primary/20"
              style={{
                background: 'var(--card)',
                border: '1px solid rgba(139,92,246,0.15)',
                color: 'hsl(var(--foreground))',
                minWidth: 130,
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
              className="h-10 px-3 rounded-xl text-sm outline-none transition-all focus:ring-2 focus:ring-primary/20"
              style={{
                background: 'var(--card)',
                border: '1px solid rgba(139,92,246,0.15)',
                color: 'hsl(var(--foreground))',
                minWidth: 130,
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

          {/* ── Stream / filter chips ── */}
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

          {/* ── Subject grid or empty state ── */}
          {filteredSubjects.length === 0 ? (
            /* Empty state */
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
              className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
              data-testid="library-subject-grid"
            >
              {filteredSubjects.map((sub, index) => (
                <SubjectCard
                  key={sub.id}
                  sub={sub}
                  chapters={chaptersBySubject.get(sub.id) || []}
                  isSaved={savedSubjects.includes(sub.id)}
                  onToggleSave={(id) => toggleSaved.mutate(id)}
                  onOpen={handleOpen}
                  onAskAI={handleAskAI}
                  onSeoNav={handleSeoNav}
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
