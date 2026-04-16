import { useMemo } from 'react';

export default function StickyToc({
  headings,
  activeId,
  filterFn,
  getId = (h) => h.anchor ?? h.id,
  getLevel = (h) => h.level,
  label = 'On this page',
  onItemClick,
}) {
  const filtered = useMemo(() => {
    if (filterFn) return filterFn(headings);
    return headings.filter((h) => {
      const lvl = getLevel(h);
      return lvl === 2 || lvl === 3;
    });
  }, [headings, filterFn, getLevel]);

  if (filtered.length < 2) return null;

  return (
    <nav
      className="sticky top-20 w-56 shrink-0 hidden xl:block self-start"
      aria-label="Table of contents"
    >
      <p className="text-[11px] font-semibold uppercase tracking-wider mb-3 text-muted-foreground/50">
        {label}
      </p>
      <ul className="space-y-0.5">
        {filtered.map((h) => {
          const id = getId(h);
          const level = getLevel(h);
          const isActive = activeId === id;
          return (
            <li key={id}>
              <a
                href={`#${id}`}
                className={`block py-1 text-[12px] leading-snug transition-colors rounded ${
                  level === 3 ? 'pl-4' : 'pl-0'
                } ${
                  isActive
                    ? 'text-primary font-medium toc-active'
                    : 'text-muted-foreground/50 hover:text-foreground/70'
                }`}
                style={{
                  borderLeft:
                    level === 2
                      ? isActive
                        ? '2px solid #9575e0'
                        : '2px solid transparent'
                      : 'none',
                }}
                onClick={(e) => {
                  e.preventDefault();
                  if (onItemClick) onItemClick(h);
                  document
                    .getElementById(id)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }}
              >
                {h.text}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
