import { useMemo, useState, useCallback, memo } from 'react';
import { Link } from 'react-router-dom';
import {
  Bookmark, BookmarkCheck,
  BookOpen, Layers, ChevronRight, Sparkles,
  Share2, ExternalLink, Lock, Loader2,
  FileText, HelpCircle, List, Lightbulb, CheckSquare, ChevronDown,
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

const SEO_TYPE_CONFIG = {
  notes:                { label: 'Notes',     icon: FileText,    color: '#10b981', bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.25)' },
  definition:           { label: 'Definitions', icon: List,      color: '#3b82f6', bg: 'rgba(59,130,246,0.12)', border: 'rgba(59,130,246,0.25)' },
  mcqs:                 { label: 'MCQs',      icon: CheckSquare, color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.25)' },
  'important-questions': { label: 'Questions', icon: HelpCircle, color: '#ef4444', bg: 'rgba(239,68,68,0.12)',  border: 'rgba(239,68,68,0.25)' },
  examples:             { label: 'Examples',  icon: Lightbulb,   color: '#8b5cf6', bg: 'rgba(139,92,246,0.12)', border: 'rgba(139,92,246,0.25)' },
};

const SEO_TYPE_ORDER = ['notes', 'definition', 'mcqs', 'important-questions', 'examples'];

function TopicPageTypePills({ topic, basePath }) {
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {SEO_TYPE_ORDER.filter(pt => topic.page_types.includes(pt)).map(pt => {
        const cfg = SEO_TYPE_CONFIG[pt];
        const href = pt === 'notes'
          ? `${basePath}/${topic.slug}`
          : `${basePath}/${topic.slug}/${pt}`;
        return (
          <Link
            key={pt}
            to={href}
            className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full transition-all hover:opacity-80"
            style={{ background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}` }}
          >
            {cfg.label}
          </Link>
        );
      })}
    </div>
  );
}

const SubjectCard = memo(function SubjectCard({ sub, chapters = [], isSaved, onToggleSave, onAskAI, index }) {
  const [showTopics, setShowTopics] = useState(null);
  const thumbColors = useMemo(() => THUMB_GRADIENTS[sub.gradient] || THUMB_GRADIENTS.math, [sub.gradient]);
  const tags = useMemo(() => Array.isArray(sub.tags) ? sub.tags : [], [sub.tags]);
  const visibleTags = useMemo(() => tags.slice(0, 3), [tags]);
  const chapterCount = useMemo(() => chapters.length || sub.chapter_count || sub.chapterCount || 0, [chapters.length, sub.chapter_count, sub.chapterCount]);
  const hasDocument = useMemo(() => sub.has_document === true, [sub.has_document]);

  const seoStats = sub.seo_stats || {};
  const hasSeoContent = seoStats.topic_count > 0;

  const seoPath = useMemo(() =>
    sub.boardSlug && sub.classSlug && sub.streamSlug && sub.slug
      ? `/${sub.boardSlug}/${sub.classSlug}/${sub.streamSlug}/${sub.slug}`
      : null,
    [sub.boardSlug, sub.classSlug, sub.streamSlug, sub.slug]
  );

  const seoTopicBasePath = useMemo(() =>
    sub.boardSlug && sub.classSlug && sub.slug
      ? `/${sub.boardSlug}/${sub.classSlug}/${sub.slug}`
      : null,
    [sub.boardSlug, sub.classSlug, sub.slug]
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

  const handleToggleTopics = useCallback((chId) => {
    setShowTopics(prev => prev === chId ? null : chId);
  }, []);

  return (
    <div
      className="w-full rounded-2xl overflow-hidden transition-all duration-300 group/card hover:-translate-y-0.5 relative cursor-pointer"
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
        <Link to={subjectLandingPath} className="block group/title static" aria-label={`View ${sub.name}`}>
          <span className="absolute inset-0 z-0" aria-hidden="true" />
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

        {hasSeoContent && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {SEO_TYPE_ORDER.filter(pt => seoStats[pt] > 0).map(pt => {
              const cfg = SEO_TYPE_CONFIG[pt];
              const Icon = cfg.icon;
              return (
                <span
                  key={pt}
                  className="flex items-center gap-1 text-[9px] font-semibold px-1.5 py-0.5 rounded-full"
                  style={{ background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}` }}
                >
                  <Icon size={8} />
                  {seoStats[pt]} {cfg.label}
                </span>
              );
            })}
          </div>
        )}
      </div>

      {visibleChapters.length > 0 && (
        <div
          className="mx-3 mb-2 sm:mb-3 rounded-xl overflow-hidden relative z-10"
          style={{
            background: 'rgba(139,92,246,0.03)',
            border: '1px solid rgba(139,92,246,0.08)',
          }}
        >
          {sub.thumbnailUrl && (
            <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 0 }}>
              <img
                src={sub.thumbnailUrl}
                alt=""
                loading="lazy"
                className="absolute inset-0 w-full h-full object-cover"
              />
              <div
                className="absolute inset-0"
                style={{ background: 'linear-gradient(180deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.70) 100%)' }}
              />
            </div>
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
              const chTopics = ch.seo_topics || [];
              const isExpanded = showTopics === ch.id;
              return (
                <div key={ch.id || i}>
                  <div
                    className="flex items-center gap-2 px-3 py-2.5 sm:py-2 text-xs transition-all hover:bg-purple-500/8 group/lesson"
                    style={{ borderBottom: (i < visibleChapters.length - 1 && !isExpanded) ? '1px solid rgba(139,92,246,0.05)' : 'none' }}
                  >
                    <span
                      className="w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-bold shrink-0"
                      style={{ background: 'rgba(139,92,246,0.10)', color: 'hsl(var(--primary))' }}
                    >
                      {i + 1}
                    </span>
                    <Link
                      to={chPath}
                      className="text-foreground/75 group-hover/lesson:text-purple-300 truncate transition-colors flex-1"
                      title={`${ch.title} — ${sub.name}`}
                    >
                      {ch.title}
                    </Link>
                    {chTopics.length > 0 ? (
                      <button
                        onClick={() => handleToggleTopics(ch.id)}
                        className="shrink-0 p-0.5 rounded transition-colors text-muted-foreground/40 hover:text-purple-400"
                        aria-label={isExpanded ? 'Collapse topics' : 'Expand topics'}
                      >
                        <ChevronDown size={12} className={`transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`} />
                      </button>
                    ) : (
                      <ExternalLink
                        size={10}
                        className="shrink-0 text-muted-foreground/20 group-hover/lesson:text-purple-400 transition-colors"
                      />
                    )}
                  </div>
                  {isExpanded && chTopics.length > 0 && seoTopicBasePath && (
                    <div
                      className="px-3 pb-2 space-y-1.5"
                      style={{ borderBottom: i < visibleChapters.length - 1 ? '1px solid rgba(139,92,246,0.05)' : 'none' }}
                    >
                      {chTopics.map(topic => (
                        <div key={topic.id} className="pl-7">
                          <Link
                            to={`${seoTopicBasePath}/${topic.slug}`}
                            className="text-[11px] text-foreground/60 hover:text-purple-300 transition-colors leading-tight"
                          >
                            {topic.title}
                          </Link>
                          <TopicPageTypePills topic={topic} basePath={seoTopicBasePath} />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
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
        className="grid grid-cols-2 gap-1.5 px-3 py-2.5 relative z-10"
        style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}
      >
        <button
          onClick={() => { onToggleSave(sub.id); try { Analytics.subjectBookmarked(sub.name, !isSaved); } catch {} }}
          aria-label={isSaved ? `Unsave ${sub.name}` : `Save ${sub.name}`}
          className="flex items-center justify-center gap-1.5 h-11 sm:h-9 rounded-lg text-xs font-medium transition-all duration-200 active:scale-95"
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
          className="flex items-center justify-center gap-1.5 h-11 sm:h-9 rounded-lg text-xs font-medium transition-all duration-200 active:scale-95 hover:bg-white/5"
          style={{ color: 'hsl(var(--muted-foreground))', border: '1px solid rgba(139,92,246,0.12)' }}
        >
          <BookOpen size={12} />
          Browse
        </Link>

        <button
          onClick={() => onAskAI(sub.id, hasDocument, sub.name)}
          aria-label={`Ask AI about ${sub.name}`}
          className="flex items-center justify-center gap-1.5 h-11 sm:h-9 rounded-lg text-xs font-semibold text-white transition-all duration-200 hover:opacity-90 active:scale-95"
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
          className="flex items-center justify-center gap-1.5 h-11 sm:h-9 rounded-lg text-xs font-medium transition-all duration-200 active:scale-95 hover:bg-white/5 disabled:opacity-50"
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
