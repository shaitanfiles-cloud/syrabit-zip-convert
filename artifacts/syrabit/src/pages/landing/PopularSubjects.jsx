import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, BookOpen } from 'lucide-react';
import { useLibraryBundleSlim } from '@/hooks/useContent';

const FALLBACK = [
  { label: 'Class 12 Physics',     href: '/ahsec/class-12/physics',     board: 'AHSEC' },
  { label: 'Class 12 Chemistry',   href: '/ahsec/class-12/chemistry',   board: 'AHSEC' },
  { label: 'Class 12 Mathematics', href: '/ahsec/class-12/mathematics', board: 'AHSEC' },
  { label: 'Class 12 Biology',     href: '/ahsec/class-12/biology',     board: 'AHSEC' },
  { label: 'Class 12 Accountancy', href: '/ahsec/class-12/accountancy', board: 'AHSEC' },
  { label: 'Class 11 Physics',     href: '/ahsec/class-11/physics',     board: 'AHSEC' },
  { label: 'Class 10 Science',     href: '/seba/class-10/science',      board: 'SEBA'  },
  { label: 'Class 10 Mathematics', href: '/seba/class-10/mathematics',  board: 'SEBA'  },
];

const _t = {
  en: {
    eyebrow: 'Browse the syllabus',
    heading: 'Popular subjects right now',
    sub: 'Jump straight into the chapters AssamBoard students study most.',
    seeAll: 'See all subjects',
  },
  as: {
    eyebrow: 'পাঠ্যক্ৰম ব্ৰাউজ কৰক',
    heading: 'এতিয়া জনপ্ৰিয় বিষয়সমূহ',
    sub: 'অসম বোৰ্ডৰ ছাত্ৰ-ছাত্ৰীয়ে আটাইতকৈ অধিক অধ্যয়ন কৰা অধ্যায়সমূহলৈ পোনপটীয়াকৈ যাওক।',
    seeAll: 'সকলো বিষয় চাওক',
  },
};

function buildLandingPath(sub) {
  if (sub.boardSlug && sub.classSlug && sub.slug) {
    return `/${sub.boardSlug}/${sub.classSlug}/${sub.slug}`;
  }
  return `/subject/${sub.id}`;
}

export default function PopularSubjects({ contentLang = 'en' }) {
  const t = _t[contentLang] || _t.en;
  const { data: bundle } = useLibraryBundleSlim();

  const items = useMemo(() => {
    const subjects = bundle?.subjects || [];
    if (!subjects.length) return FALLBACK;

    // Score by chapter count (rough proxy for richness/popularity) then take 10.
    const scored = subjects
      .filter((s) => s.boardSlug && s.classSlug && s.slug)
      .map((s) => ({
        label: s.name,
        href: buildLandingPath(s),
        board: (s.board_name || s.boardSlug || '').toString().toUpperCase(),
        score: (s.chapter_count || s.chapterCount || 0),
      }))
      .sort((a, b) => b.score - a.score)
      .slice(0, 10);

    return scored.length > 0 ? scored : FALLBACK;
  }, [bundle]);

  return (
    <section
      className="relative py-20 px-5"
      aria-labelledby="popular-subjects-heading"
      data-testid="popular-subjects"
    >
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-10">
          <p className="text-xs font-semibold tracking-[0.18em] uppercase text-violet-500 mb-2">
            {t.eyebrow}
          </p>
          <h2
            id="popular-subjects-heading"
            className="text-foreground"
            style={{ fontSize: 'clamp(1.6rem,3.4vw,2.4rem)', fontWeight: 800, letterSpacing: '-0.02em' }}
          >
            {t.heading}
          </h2>
          <p className="text-muted-foreground mt-2 text-sm sm:text-base max-w-2xl mx-auto">
            {t.sub}
          </p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
          {items.map((s) => (
            <Link
              key={s.href}
              to={s.href}
              className="group flex flex-col gap-1.5 rounded-xl border border-border/40 hover:border-violet-400/40 hover:bg-violet-500/5 transition-colors px-3.5 py-3 min-h-[80px]"
              data-testid={`popular-subject-${(s.label || '').toLowerCase().replace(/\s+/g, '-')}`}
            >
              <span className="text-[10px] font-semibold uppercase tracking-wider text-violet-500/80">
                {s.board}
              </span>
              <span className="text-sm font-semibold text-foreground leading-snug group-hover:text-violet-600 transition-colors line-clamp-2">
                {s.label}
              </span>
            </Link>
          ))}
        </div>

        <div className="mt-8 flex justify-center">
          <Link
            to="/library"
            className="inline-flex items-center gap-2 h-11 px-5 rounded-xl text-sm font-semibold border border-border/40 hover:border-violet-400/40 hover:bg-violet-500/5 text-foreground transition-colors"
          >
            <BookOpen size={16} className="text-violet-500" />
            {t.seeAll}
            <ArrowRight size={14} />
          </Link>
        </div>
      </div>
    </section>
  );
}
