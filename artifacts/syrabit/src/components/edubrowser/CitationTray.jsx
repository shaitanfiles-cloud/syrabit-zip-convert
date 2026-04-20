import { memo } from 'react';
import { CitationChip } from './CitationChip';

export const CitationTray = memo(function CitationTray({ citations = [], onCite }) {
  if (!Array.isArray(citations) || citations.length === 0) return null;
  return (
    <div className="border-t border-border/60 bg-muted/30 p-3 md:p-4">
      <div className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wide">
        Sources
      </div>
      <ol className="space-y-2">
        {citations.map((c) => (
          <li key={`${c.index}-${c.url || c.title}`} className="flex items-start gap-2 text-sm">
            <CitationChip citation={c} onClick={onCite} />
            <div className="flex-1 min-w-0">
              <a
                href={c.url || '#'}
                target={c.url?.startsWith('http') ? '_blank' : undefined}
                rel={c.url?.startsWith('http') ? 'noopener noreferrer' : undefined}
                className="font-medium text-foreground hover:text-primary block truncate"
                title={c.title}
              >
                {c.title || c.domain || 'Source'}
              </a>
              {c.domain && (
                <div className="text-xs text-muted-foreground truncate">{c.domain}</div>
              )}
              {c.snippet && (
                <div className="text-xs text-muted-foreground/90 mt-0.5 line-clamp-2">
                  {c.snippet}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
});
