import { memo } from 'react';
import { BookOpen, Globe, FileText } from 'lucide-react';

const TYPE_STYLE = {
  page:    { Icon: FileText, ring: 'ring-violet-200 bg-violet-50 text-violet-700' },
  chapter: { Icon: BookOpen, ring: 'ring-emerald-200 bg-emerald-50 text-emerald-700' },
  web:     { Icon: Globe,    ring: 'ring-sky-200 bg-sky-50 text-sky-700' },
};

export const CitationChip = memo(function CitationChip({ citation, compact = false, onClick }) {
  if (!citation) return null;
  const { index, type = 'web' } = citation;
  const style = TYPE_STYLE[type] || TYPE_STYLE.web;
  const Icon = style.Icon;
  const label = compact ? `[${index}]` : `${index}`;
  const title = citation.title || citation.domain || 'Source';
  const className = `inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${style.ring} align-baseline`;

  // Inline chips inside answer text shouldn't be focusable buttons with no
  // action — render them as a <span> instead so keyboard users don't tab
  // through dozens of no-op controls.
  if (!onClick) {
    return (
      <span
        className={className}
        title={title}
        aria-label={`Source ${index}${citation.title ? `: ${citation.title}` : ''}`}
      >
        {!compact && <Icon className="w-3 h-3" aria-hidden="true" />}
        <span>{label}</span>
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onClick(citation)}
      className={`${className} hover:opacity-80 transition-opacity`}
      title={title}
      aria-label={`Source ${index}${citation.title ? `: ${citation.title}` : ''}`}
    >
      {!compact && <Icon className="w-3 h-3" aria-hidden="true" />}
      <span>{label}</span>
    </button>
  );
});
