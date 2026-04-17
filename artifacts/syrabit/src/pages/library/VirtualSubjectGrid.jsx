import { useEffect, useMemo, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import SubjectCard from './SubjectCard';

/**
 * Returns the number of grid columns to use, mirroring the
 *   grid-cols-1 md:grid-cols-2 xl:grid-cols-3
 * tailwind classes used by the non-virtualized grid.
 */
function useColumnCount() {
  const [cols, setCols] = useState(() => {
    if (typeof window === 'undefined') return 1;
    if (window.matchMedia('(min-width: 1280px)').matches) return 3;
    if (window.matchMedia('(min-width: 768px)').matches) return 2;
    return 1;
  });
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mqlXl = window.matchMedia('(min-width: 1280px)');
    const mqlMd = window.matchMedia('(min-width: 768px)');
    const update = () => setCols(mqlXl.matches ? 3 : mqlMd.matches ? 2 : 1);
    mqlXl.addEventListener('change', update);
    mqlMd.addEventListener('change', update);
    return () => {
      mqlXl.removeEventListener('change', update);
      mqlMd.removeEventListener('change', update);
    };
  }, []);
  return cols;
}

/**
 * Virtualized grid that only renders the rows currently in (or near) the
 * viewport. Used by LibraryPage when the filtered subject set is large
 * enough that mounting every SubjectCard hurts TBT/INP on mobile.
 *
 * Task #384.
 */
export default function VirtualSubjectGrid({
  scrollParent,
  subjects,
  chaptersBySubject,
  savedSubjects,
  onToggleSave,
  onAskAI,
}) {
  const cols = useColumnCount();
  const rowCount = Math.ceil(subjects.length / cols);
  // O(1) saved-subject lookup — avoids an Array#includes scan per card render.
  const savedSet = useMemo(
    () => (savedSubjects instanceof Set ? savedSubjects : new Set(savedSubjects || [])),
    [savedSubjects]
  );

  const rowVirtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollParent,
    estimateSize: () => 480, // refined per-row by measureElement
    overscan: 3,
  });

  const virtualRows = rowVirtualizer.getVirtualItems();

  return (
    <div
      data-testid="library-subject-grid"
      data-virtualized="true"
      style={{
        position: 'relative',
        height: rowVirtualizer.getTotalSize(),
        width: '100%',
        contain: 'layout style',
        minHeight: '420px',
      }}
    >
      {virtualRows.map((virtualRow) => {
        const rowStart = virtualRow.index * cols;
        const items = subjects.slice(rowStart, rowStart + cols);
        return (
          <div
            key={virtualRow.key}
            data-index={virtualRow.index}
            ref={rowVirtualizer.measureElement}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              transform: `translateY(${virtualRow.start}px)`,
              display: 'grid',
              gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
              gap: '20px',
              paddingBottom: '20px',
            }}
          >
            {items.map((sub, i) => (
              <SubjectCard
                key={sub.id}
                sub={sub}
                chapters={chaptersBySubject.get(sub.id) || []}
                isSaved={savedSet.has(sub.id)}
                onToggleSave={onToggleSave}
                onAskAI={onAskAI}
                index={rowStart + i}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}
