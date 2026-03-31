import { useNavigate } from 'react-router-dom';
import { BookOpen, ExternalLink } from 'lucide-react';

function slugToTitle(slug) {
  if (!slug) return '';
  const cleaned = slug.replace(/-(notes|mcqs|definition|important-questions|examples|ahsec|seba|degree)$/i, '').replace(/-+/g, ' ').trim();
  return cleaned.replace(/\b\w/g, c => c.toUpperCase());
}

export function SourcesCard({ sources, ragSource, ragChunks, ragSubjectId, ragSubjectName }) {
  const navigate = useNavigate();

  const hasSrc = sources && sources.length > 0;
  const hasRag = ragSource && ragSource !== 'none';

  if (!hasSrc && !hasRag) return null;

  const boardLabel = (() => {
    if (ragSource === 'document')                       return 'Document';
    if (ragSource === 'rag' || ragSource === 'rag+web') {
      // Use the actual subject name when known; avoid hard-coding the board name
      return ragSubjectName ? `${ragSubjectName} — Curriculum` : 'Syrabit Curriculum';
    }
    if (ragSource === 'web')                            return 'Web Search';
    return 'Syrabit Library';
  })();

  const handleNav = (url) => {
    if (!url) return;
    if (url.startsWith('http')) window.open(url, '_blank', 'noopener,noreferrer');
    else navigate(url);
  };

  // Separate content-card attribution from URL-based sources
  const contentCardSource = hasSrc ? sources.find(s => s.type === 'content_card') : null;
  const hasNamedContentCard = !!(contentCardSource && (contentCardSource.card_name || contentCardSource.lesson_name));
  // Always show all sources with a URL — content card is additive, not a replacement
  const visibleSources = hasSrc
    ? sources.filter(s => s.type !== 'content_card' && (s.url || s.slug))
    : [];
  const subjectUrl     = ragSubjectId ? `/subject/${ragSubjectId}` : null;
  const fallbackUrl    = subjectUrl || '/library';
  const displayTitle   = ragSubjectName || 'Syrabit Library';

  const footerText = [
    ragChunks > 0 ? `${ragChunks} chunks` : null,
    (ragSource === 'rag' || ragSource === 'rag+web') ? (ragSubjectName ? `${ragSubjectName} curriculum` : 'Syrabit curriculum') : null,
    ragSource === 'web' ? 'Web search' : null,
    ragSource === 'document' ? 'Uploaded document' : null,
  ].filter(Boolean).join(' · ');

  // No individual page sources — make entire card a single clickable link
  if (visibleSources.length === 0 && !hasNamedContentCard) {
    return (
      <button
        onClick={() => handleNav(fallbackUrl)}
        className="source-card source-card-clickable w-full text-left"
        title={`View ${displayTitle}`}
      >
        <div className="source-watermark">
          <BookOpen size={13} className="shrink-0" style={{ color: '#60a5fa' }} />
          <span>Syrabit.ai · {boardLabel}</span>
          {ragChunks > 0 && <span className="source-chunk-badge">{ragChunks} blocks</span>}
          <ExternalLink size={10} className="ml-auto shrink-0 opacity-40" style={{ color: '#60a5fa' }} />
        </div>
        <div className="source-pages">
          <div className="source-link" style={{ pointerEvents: 'none' }}>
            <span className="source-link-icon">📖</span>
            <span className="truncate">{displayTitle}</span>
          </div>
        </div>
        {footerText && <div className="source-stats">{footerText}</div>}
      </button>
    );
  }

  // Individual source pages — watermark header links to subject, each page is its own link
  return (
    <div className="source-card">
      {/* Watermark header — always links to subject */}
      <button
        onClick={() => handleNav(fallbackUrl)}
        className="source-watermark source-watermark-btn w-full text-left"
        title={`View ${displayTitle}`}
      >
        <BookOpen size={13} className="shrink-0" style={{ color: '#60a5fa' }} />
        <span>Syrabit.ai · {boardLabel}</span>
        {ragChunks > 0 && <span className="source-chunk-badge">{ragChunks} blocks</span>}
        <ExternalLink size={10} className="ml-auto shrink-0 opacity-40" style={{ color: '#60a5fa' }} />
      </button>

      {/* Content card attribution — shown when type="content_card" is present */}
      {/* Breadcrumb: Topic · Chapter · Subject (rightmost = most specific = leftmost visually) */}
      {hasNamedContentCard && (
        <div className="flex items-center gap-1.5 mb-2 px-1 mt-1 flex-wrap">
          <span className="text-[10px] font-semibold text-white/25 uppercase tracking-widest">From</span>
          {contentCardSource.board_name && (
            <>
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-md" style={{ background: 'rgba(34,197,94,0.07)', color: '#86efac' }}>
                {contentCardSource.board_name}
              </span>
              <span className="text-[10px] text-white/20">›</span>
            </>
          )}
          {contentCardSource.class_name && (
            <>
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-md" style={{ background: 'rgba(234,179,8,0.07)', color: '#fde68a' }}>
                {contentCardSource.class_name}
              </span>
              <span className="text-[10px] text-white/20">›</span>
            </>
          )}
          {contentCardSource.subject_name && (
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-md" style={{ background: 'rgba(59,130,246,0.07)', color: '#7dd3fc' }}>
              {contentCardSource.subject_name}
            </span>
          )}
          {contentCardSource.subject_name && contentCardSource.lesson_name && (
            <span className="text-[10px] text-white/20">›</span>
          )}
          {contentCardSource.lesson_name && (
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-md" style={{ background: 'rgba(96,165,250,0.08)', color: '#93c5fd' }}>
              {contentCardSource.lesson_name}
            </span>
          )}
          {contentCardSource.lesson_name && contentCardSource.card_name && contentCardSource.card_name !== contentCardSource.lesson_name && (
            <span className="text-[10px] text-white/20">›</span>
          )}
          {contentCardSource.card_name && contentCardSource.card_name !== contentCardSource.lesson_name && (
            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-md" style={{ background: 'rgba(139,92,246,0.10)', color: '#a78bfa' }}>
              {contentCardSource.card_name}
            </span>
          )}
        </div>
      )}

      {/* Subject label — shown when no named content card */}
      {!hasNamedContentCard && displayTitle && (
        <div className="flex items-center gap-1.5 mb-2 px-1 mt-1">
          <span className="text-[10px] font-semibold text-white/25 uppercase tracking-widest">From</span>
          <span
            className="text-[11px] font-semibold px-2 py-0.5 rounded-md"
            style={{ background: 'rgba(139,92,246,0.10)', color: '#a78bfa' }}
          >
            {displayTitle}
          </span>
        </div>
      )}

      {/* Individual page links — always shown when available (content card is additive) */}
      {visibleSources.length > 0 && (
        <div className="source-pages">
          {visibleSources.map((src, i) => {
            const tooltip = [src.board_name, src.class_name, ragSubjectName || src.subject_name, src.chapter_name, src.title || src.slug].filter(Boolean).join(' › ') || src.url || 'View source';
            return (
              <button
                key={i}
                onClick={() => handleNav(src.url || '')}
                className="source-link"
                title={tooltip}
                disabled={!src.url}
              >
                <span className="source-link-icon">📖</span>
                <span className="truncate">{src.title || slugToTitle(src.slug) || src.slug}</span>
                {src.url && <ExternalLink size={9} className="shrink-0 ml-auto opacity-40" />}
              </button>
            );
          })}
        </div>
      )}

      {footerText && <div className="source-stats">{footerText}</div>}
    </div>
  );
}
