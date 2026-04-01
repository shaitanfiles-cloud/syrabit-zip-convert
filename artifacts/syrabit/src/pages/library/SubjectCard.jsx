import { useMemo, useState, useCallback, memo } from 'react';
import { Link } from 'react-router-dom';
import {
  Bookmark, BookmarkCheck,
  BookOpen, Layers, ChevronRight, Sparkles,
  Share2, ExternalLink, Lock, Loader2,
} from 'lucide-react';
import { useShare } from '@/hooks/useShare';

const THUMB_GRADIENTS = {
  math:      ['#4f46e5', '#7c3aed'],
  physics:   ['#2563eb', '#0891b2'],
  chemistry: ['#059669', '#0d9488'],
  biology:   ['#16a34a', '#15803d'],
  arts:      ['#d97706', '#b45309'],
  science:   ['#7c3aed', '#4f46e5'],
};

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

  const { sharing, share } = useShare();

  const handleShare = useCallback((e) => {
    e.preventDefault();
    share(sub.name, subjectLandingPath);
  }, [sub.name, subjectLandingPath, share]);

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

      {visibleChapters.length > 0 && (
        <div
          className="mx-3 mb-2 sm:mb-3 rounded-xl overflow-hidden relative"
          style={{
            background: 'rgba(139,92,246,0.03)',
            border: '1px solid rgba(139,92,246,0.08)',
          }}
        >
          {sub.thumbnailUrl && (
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                backgroundImage: `linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.70) 100%), url(${sub.thumbnailUrl})`,
                backgroundSize: 'cover',
                backgroundPosition: 'center',
                zIndex: 0,
              }}
            />
          )}
          <div className="relative z-10">
            <div className="flex items-center justify-between gap-1.5 px-3 py-1.5" style={{ borderBottom: '1px solid rgba(139,92,246,0.06)' }}>
              <div className="flex items-center gap-1.5">
                <Layers size={11} className="text-purple-400/60" />
                <span className="text-[10px] font-semibold text-muted-foreground/70 uppercase tracking-wider">
                  {chapterCount} Lessons
                </span>
              </div>
              {(sub.notes_count > 0 || sub.pyq_count > 0 || sub.flash_count > 0) && (
                <div className="flex items-center gap-1">
                  {sub.notes_count > 0 && chapterCount > 0 && (
                    <span
                      className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full"
                      style={{
                        background: sub.notes_pct >= 100 ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.12)',
                        color: sub.notes_pct >= 100 ? '#10b981' : '#f59e0b',
                        border: `1px solid ${sub.notes_pct >= 100 ? 'rgba(16,185,129,0.25)' : 'rgba(245,158,11,0.20)'}`,
                      }}
                    >
                      {sub.notes_count}/{chapterCount} notes
                    </span>
                  )}
                  {sub.pyq_count > 0 && (
                    <span
                      className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full"
                      style={{ background: 'rgba(99,102,241,0.12)', color: '#818cf8', border: '1px solid rgba(99,102,241,0.20)' }}
                    >
                      {sub.pyq_count} PYQs
                    </span>
                  )}
                  {sub.flash_count > 0 && (
                    <span
                      className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full"
                      style={{ background: 'rgba(139,92,246,0.12)', color: '#c084fc', border: '1px solid rgba(139,92,246,0.20)' }}
                    >
                      {sub.flash_count} Flash
                    </span>
                  )}
                </div>
              )}
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

      <div
        className="grid grid-cols-2 gap-1.5 px-3 py-2.5"
        style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}
      >
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

        <Link
          to={subjectLandingPath}
          className="flex items-center justify-center gap-1.5 h-10 sm:h-9 rounded-lg text-xs font-medium transition-all duration-200 active:scale-95 hover:bg-white/5"
          style={{ color: 'hsl(var(--muted-foreground))', border: '1px solid rgba(139,92,246,0.12)' }}
        >
          <BookOpen size={12} />
          Browse
        </Link>

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

        <button
          onClick={handleShare}
          disabled={sharing}
          aria-label={`Share ${sub.name}`}
          className="flex items-center justify-center gap-1.5 h-10 sm:h-9 rounded-lg text-xs font-medium transition-all duration-200 active:scale-95 hover:bg-white/5 disabled:opacity-50"
          style={{ color: '#94a3b8', border: '1px solid rgba(148,163,184,0.22)' }}
          data-testid="subject-share"
        >
          {sharing ? <Loader2 size={12} className="animate-spin" /> : <Share2 size={12} />}
          Share
        </button>
      </div>
    </div>
  );
});

export default SubjectCard;
