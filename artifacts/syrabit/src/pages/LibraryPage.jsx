import { useState, useEffect, useMemo, useCallback, useRef, lazy, Suspense } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Search, Bookmark,
  BookOpen, RefreshCw, Sun, Moon,
} from 'lucide-react';
import { useTheme } from 'next-themes';
import { toast } from 'sonner';

import PageMeta from '@/components/seo/PageMeta';
import { Analytics } from '@/utils/analytics';
import { AppLayout } from '@/components/layout/AppLayout';
import { useAuth } from '@/context/AuthContext';
import {
  useLibraryBundle, useSavedSubjects,
} from '@/hooks/useContent';
import { useToggleSavedSubject } from '@/hooks/useUser';
import SubjectCard from './library/SubjectCard';
import LibrarySkeleton from './library/LibrarySkeleton';
import FilterChip from './library/FilterChip';
import ScrollableFilterRow from './library/ScrollableFilterRow';

const LazyCmsDocsSection = lazy(() => import('./library/CmsDocsSection'));
const LazyCmsPostsGrid = lazy(() => import('./library/CmsPostsGrid'));

function LazyOnVisible({ children }) {
  const [visible, setVisible] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: '200px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref}>
      {visible ? children : null}
    </div>
  );
}

const STREAM_CHIPS = [
  { id: 'all', label: 'All' },
  { id: 'saved', label: '★ Saved' },
];

function getOnboardingProfile() {
  try { const raw = localStorage.getItem('syrabit:onboarding'); return raw ? JSON.parse(raw) : null; } catch { return null; }
}

export default function LibraryPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();

  const [searchQuery, setSearchQuery]   = useState('');
  const [activeFilter, setActiveFilter] = useState('all');

  const { data: bundle, isLoading: bundleLoading, isFetching, refetch: refetchBundle } = useLibraryBundle();
  const subjects    = bundle?.subjects  || [];
  const boards      = bundle?.boards    || [];
  const classes     = bundle?.classes   || [];
  const streams     = bundle?.streams   || [];
  const allChapters = bundle?.chapters  || [];
  const { data: savedSubjects = [] } = useSavedSubjects(user);
  const toggleSaved = useToggleSavedSubject();

  useEffect(() => {
    const handleContentUploaded = () => { refetchBundle(); };
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
    for (const sub of enrichedSubjects) {
      if (sub.streamSlug && !streamSlugs.has(sub.streamSlug)) {
        streamSlugs.add(sub.streamSlug);
        chips.push({ id: sub.streamSlug, label: sub.streamName || sub.streamSlug });
      }
    }
    return chips;
  }, [enrichedSubjects]);

  const allStreamChips = useMemo(() => [...STREAM_CHIPS, ...dynamicStreamChips], [dynamicStreamChips]);

  const filteredSubjects = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const seen = new Set();
    return enrichedSubjects.filter((sub) => {
      if (seen.has(sub.id)) return false;
      seen.add(sub.id);
      if (sub.status && sub.status !== 'published') return false;
      if (activeFilter === 'saved') {
        if (!savedSubjectsSet.has(sub.id)) return false;
      } else if (activeFilter !== 'all') {
        if (sub.streamSlug !== activeFilter) return false;
      }
      if (q) {
        const subChapters = chaptersBySubject.get(sub.id) || [];
        const inName    = sub.name?.toLowerCase().includes(q);
        const inDesc    = sub.description?.toLowerCase().includes(q);
        const inTags    = Array.isArray(sub.tags) && sub.tags.some((t) => t.toLowerCase().includes(q));
        const inClass   = sub.className?.toLowerCase().includes(q);
        const inStream  = sub.streamName?.toLowerCase().includes(q);
        const inBoard   = sub.boardName?.toLowerCase().includes(q);
        const inChapter = subChapters.some((ch) => ch.title?.toLowerCase().includes(q));
        if (!inName && !inDesc && !inTags && !inClass && !inStream && !inBoard && !inChapter) return false;
      }
      return true;
    });
  }, [enrichedSubjects, activeFilter, searchQuery, savedSubjectsSet, chaptersBySubject]);

  const totalSeoTopics = useMemo(() => {
    return enrichedSubjects.reduce((sum, s) => sum + (s.seo_stats?.topic_count || 0), 0);
  }, [enrichedSubjects]);

  const libraryJsonLd = useMemo(() => {
    if (!filteredSubjects.length) return null;
    return {
      '@context': 'https://schema.org',
      '@graph': [
        {
          '@type': 'ItemList',
          name: 'Assamboard Subject Library',
          description: 'Complete study material library for Assam Board (AHSEC/SEBA) students with notes, MCQs, definitions, and exam preparation resources.',
          numberOfItems: filteredSubjects.length,
          itemListElement: filteredSubjects.map((s, i) => ({
            '@type': 'ListItem',
            position: i + 1,
            item: {
              '@type': 'LearningResource',
              name: s.name,
              description: s.description || `Study ${s.name} — ${s.boardName} ${s.className}`,
              url: s.boardSlug && s.classSlug && s.slug
                ? `https://syrabit.ai/${s.boardSlug}/${s.classSlug}/${s.slug}`
                : `https://syrabit.ai/subject/${s.id}`,
              provider: { '@type': 'Organization', name: 'Syrabit.ai', url: 'https://syrabit.ai' },
              educationalLevel: `${s.className || ''} ${s.boardName || ''}`.trim(),
              inLanguage: 'en-IN',
              isAccessibleForFree: true,
            },
          })),
        },
        {
          '@type': 'WebPage',
          '@id': 'https://syrabit.ai/library',
          name: 'Assamboard Subject Library — Study Notes, MCQs & Exam Prep',
          description: 'Browse study materials for Assam Board subjects. AI-powered notes, MCQs, definitions, important questions, and examples.',
          url: 'https://syrabit.ai/library',
          isPartOf: { '@type': 'WebSite', '@id': 'https://syrabit.ai', name: 'Syrabit.ai' },
          inLanguage: 'en-IN',
        },
        {
          '@type': 'BreadcrumbList',
          itemListElement: [
            { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://syrabit.ai' },
            { '@type': 'ListItem', position: 2, name: 'Library', item: 'https://syrabit.ai/library' },
          ],
        },
      ],
    };
  }, [filteredSubjects]);

  useEffect(() => {
    if (!libraryJsonLd) return;
    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.id = 'library-jsonld';
    script.text = JSON.stringify(libraryJsonLd);
    const existing = document.getElementById('library-jsonld');
    if (existing) existing.remove();
    document.head.appendChild(script);
    return () => { const el = document.getElementById('library-jsonld'); if (el) el.remove(); };
  }, [libraryJsonLd]);

  const handleAskAI = useCallback((subjectId, hasDocument = false, subjectName = '') => {
    try { Analytics.chatStart(subjectId, subjectName, 'syrabit-slm'); } catch {}
    const params = new URLSearchParams({ subject: subjectId });
    if (hasDocument) params.set('document_id', subjectId);
    navigate(`/chat?${params.toString()}`);
  }, [navigate]);

  const handleResetFilters = useCallback(() => { setSearchQuery(''); setActiveFilter('all'); }, []);

  const handleRefetchSubjects = useCallback(async () => { await refetchBundle(); toast.success('Browser refreshed'); }, [refetchBundle]);

  const handleSearchChange = useCallback((e) => setSearchQuery(e.target.value), []);
  const handleFilterChange = useCallback((filterId) => setActiveFilter(filterId), []);
  const handleSearchClear = useCallback(() => setSearchQuery(''), []);

  const seoTitle = 'Assamboard Subject Library — Notes, MCQs, Definitions & Exam Prep';
  const seoDescription = `Explore ${subjects.length || ''} Assamboard Class 11-12 and Degree subjects with ${totalSeoTopics || ''} study topics. AI-powered notes, MCQs, definitions, important questions, and examples for Assam students.`.replace(/  +/g, ' ').trim();
  const seoKeywords = 'Assam Board study material, AHSEC notes, SEBA notes, Class 11 notes Assam, Class 12 notes Assam, MCQs Assam Board, definitions, important questions, exam preparation Assam, Syrabit';

  if (bundleLoading) {
    return (
      <AppLayout pageTitle="Library" hideNavbar>
        <PageMeta
          title={seoTitle}
          description="Explore Assamboard Class 11-12 and Degree subjects. AI-powered notes, MCQs, definitions, and exam preparation for Assam students."
          url="https://syrabit.ai/library"
          keywords={seoKeywords}
        />
        <LibrarySkeleton />
      </AppLayout>
    );
  }

  return (
    <AppLayout pageTitle="Library" hideNavbar>
      <PageMeta
        title={seoTitle}
        description={seoDescription}
        url="https://syrabit.ai/library"
        keywords={seoKeywords}
      />
      <div className="flex flex-col h-full w-full overflow-hidden">

        <div
          className="sticky top-0 shrink-0 w-full z-20"
          style={{
            background: 'var(--background)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
            borderBottom: '1px solid rgba(139,92,246,0.08)',
          }}
        >
          <div className="w-full max-w-6xl mx-auto px-4 md:px-6 pt-5 pb-3 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <h1
                  className="text-foreground shimmer-text"
                  style={{ fontSize: 'clamp(0.95rem, 3.2vw, 1.5rem)', fontWeight: 700, lineHeight: 1.25 }}
                >
                  Educational Browser<br />For Assamboard Students
                </h1>
                <p className="text-xs sm:text-sm text-muted-foreground mt-1">
                  Browse {subjects.length} subjects · {allChapters.length} lessons{totalSeoTopics > 0 ? ` · ${totalSeoTopics} study topics` : ''}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                  title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
                  aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
                  className="min-w-[44px] min-h-[44px] rounded-xl flex items-center justify-center text-muted-foreground hover:text-primary hover:bg-primary/10 transition-all duration-200"
                >
                  {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
                </button>
                <button
                  onClick={handleRefetchSubjects}
                  disabled={isFetching}
                  className="h-11 px-3.5 rounded-xl text-xs font-medium text-white bg-violet-600 hover:bg-violet-500 disabled:opacity-60 transition-all flex items-center gap-1.5 active:scale-95"
                >
                  <RefreshCw size={13} className={isFetching ? 'animate-spin' : ''} />
                  {isFetching ? 'Updating…' : 'Refresh'}
                </button>
              </div>
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

          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="w-full max-w-6xl mx-auto px-4 md:px-6 py-5">

            <ScrollableFilterRow
              role="group"
              aria-label="Stream filters"
              className="pb-4"
              data-testid="library-filter-chips"
            >
              {allStreamChips.map((chip) => (
                <FilterChip
                  key={chip.id}
                  chip={chip}
                  isActive={chip.id === activeFilter}
                  onClick={() => handleFilterChange(chip.id)}
                />
              ))}
            </ScrollableFilterRow>
            {filteredSubjects.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div
                  className="w-20 h-20 rounded-2xl flex items-center justify-center mb-5"
                  style={{
                    background: 'linear-gradient(135deg, rgba(124,58,237,0.08), rgba(139,92,246,0.04))',
                    border: '1px solid rgba(139,92,246,0.12)',
                  }}
                >
                  {activeFilter === 'saved'
                    ? <Bookmark className="w-9 h-9" style={{ color: 'hsl(var(--primary) / 0.4)' }} />
                    : <BookOpen className="w-9 h-9" style={{ color: 'hsl(var(--muted-foreground) / 0.3)' }} />
                  }
                </div>

                {activeFilter === 'saved' && !user ? (
                  <>
                    <h3 className="text-foreground font-semibold text-lg">Sign in to see saved subjects</h3>
                    <p className="text-sm text-muted-foreground/60 mt-1.5 max-w-xs">
                      Create a free account to bookmark subjects and track your progress
                    </p>
                    <Link
                      to="/signup"
                      className="mt-5 px-5 py-2 rounded-xl text-sm text-white font-medium transition-all duration-200 active:scale-95"
                      style={{ background: 'hsl(var(--primary))', boxShadow: '0 0 20px hsl(var(--primary)/0.3)' }}
                    >
                      Sign up free
                    </Link>
                  </>
                ) : activeFilter === 'saved' && user ? (
                  <>
                    <h3 className="text-foreground font-semibold text-lg">No saved subjects yet</h3>
                    <p className="text-sm text-muted-foreground/60 mt-1.5 max-w-xs">
                      Tap the bookmark on any subject card to save it here for quick access
                    </p>
                    <button
                      onClick={() => setActiveFilter('all')}
                      className="mt-5 px-5 py-2 rounded-xl text-sm text-white font-medium transition-all duration-200 active:scale-95"
                      style={{ background: 'hsl(var(--primary))', boxShadow: '0 0 20px hsl(var(--primary)/0.3)' }}
                    >
                      Browse all subjects
                    </button>
                  </>
                ) : (
                  <>
                    <h3 className="text-foreground font-semibold text-lg">No subjects found</h3>
                    <p className="text-sm text-muted-foreground/60 mt-1.5 max-w-xs">
                      {searchQuery
                        ? `No results for "${searchQuery}" — try a different term or clear the search`
                        : 'Try adjusting your filters to discover more subjects'}
                    </p>
                    {(searchQuery || activeFilter !== 'all') && (
                      <button
                        onClick={handleResetFilters}
                        className="mt-5 px-4 py-2 rounded-xl text-sm text-primary hover:text-white transition-all duration-200 active:scale-95"
                        style={{ border: '1px solid rgba(139,92,246,0.25)', background: 'rgba(139,92,246,0.06)' }}
                        data-testid="library-reset-filters-button"
                      >
                        Reset all filters
                      </button>
                    )}
                  </>
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
          <LazyOnVisible>
            <Suspense fallback={null}>
              <LazyCmsDocsSection />
            </Suspense>
          </LazyOnVisible>
          <LazyOnVisible>
            <Suspense fallback={null}>
              <LazyCmsPostsGrid />
            </Suspense>
          </LazyOnVisible>
        </div>

      </div>
    </AppLayout>
  );
}
