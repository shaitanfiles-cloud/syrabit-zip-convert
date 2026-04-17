import { useState, useEffect, useMemo, useCallback, useRef, useDeferredValue, useTransition, lazy, Suspense } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Search, Bookmark, BookOpen } from './library/icons';

import PageMeta from '@/components/seo/PageMeta';
import { Analytics } from '@/utils/analytics';
import { AppLayout } from '@/components/layout/AppLayout';
import { useAuth } from '@/context/AuthContext';
import { useContentLang } from '@/context/LanguageContext';
import {
  useLibraryBundle, useLibraryBundleSlim, useSavedSubjects,
} from '@/hooks/useContent';
import { useToggleSavedSubject } from '@/hooks/useUser';
import SubjectCard from './library/SubjectCard';
import VirtualSubjectGrid from './library/VirtualSubjectGrid';
import LibrarySkeleton from './library/LibrarySkeleton';
import FilterChip from './library/FilterChip';
import ScrollableFilterRow from './library/ScrollableFilterRow';

const LazyCmsDocsSection = lazy(() => import('./library/CmsDocsSection'));
const LazyCmsPostsGrid = lazy(() => import('./library/CmsPostsGrid'));

const _t = {
  en: {
    heading: 'Educational Browser',
    subheading: 'For Assam Board Students',
    browse: (s, c) => `Browse ${s} subjects · ${c} chapters`,
    searchPlaceholder: 'Search subjects, topics, chapters...',
    clear: 'Clear',
    all: 'All',
    saved: 'Saved',
    pyq: 'Previous Year Question Papers',
    noResultsTitle: 'No subjects found',
    noResultsDesc: 'Try a different search term or filter',
    savedSignIn: 'Sign in to see saved subjects',
    savedSignInDesc: 'Create a free account to bookmark subjects and track your progress',
    signUpFree: 'Sign Up Free',
    noSaved: 'No saved subjects yet',
    noSavedDesc: 'Tap the bookmark icon on any subject to save it here',
    browseAll: 'Browse all subjects',
    lessons: 'LESSONS',
    notes: 'notes',
  },
  as: {
    heading: 'শৈক্ষিক ব্ৰাউজাৰ',
    subheading: 'অসম বোৰ্ডৰ ছাত্ৰ-ছাত্ৰীৰ বাবে',
    browse: (s, c) => `${s} টা বিষয় · ${c} টা অধ্যায় চাওক`,
    searchPlaceholder: 'বিষয়, বিষয়বস্তু, অধ্যায় সন্ধান কৰক...',
    clear: 'মচক',
    all: 'সকলো',
    saved: 'সংৰক্ষিত',
    pyq: 'পূৰ্বৰ বছৰৰ প্ৰশ্নকাকত',
    noResultsTitle: 'কোনো বিষয় পোৱা নগ\'ল',
    noResultsDesc: 'এটা বেলেগ সন্ধান শব্দ বা ফিল্টাৰ চেষ্টা কৰক',
    savedSignIn: 'সংৰক্ষিত বিষয় চাবলৈ চাইন ইন কৰক',
    savedSignInDesc: 'বিষয় বুকমাৰ্ক কৰিবলৈ বিনামূলীয়া একাউণ্ট তৈয়াৰ কৰক',
    signUpFree: 'বিনামূলীয়া চাইন আপ',
    noSaved: 'এতিয়াও কোনো সংৰক্ষিত বিষয় নাই',
    noSavedDesc: 'ইয়াত সংৰক্ষণ কৰিবলৈ যিকোনো বিষয়ত বুকমাৰ্ক আইকন টিপক',
    browseAll: 'সকলো বিষয় চাওক',
    lessons: 'পাঠ',
    notes: 'টোকা',
  },
};

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

const STREAM_CHIPS_EN = [
  { id: 'all', label: 'All' },
  { id: 'saved', label: '★ Saved' },
];
const STREAM_CHIPS_AS = [
  { id: 'all', label: 'সকলো' },
  { id: 'saved', label: '★ সংৰক্ষিত' },
];

function getOnboardingProfile() {
  try { const raw = localStorage.getItem('syrabit:onboarding'); return raw ? JSON.parse(raw) : null; } catch { return null; }
}

export default function LibraryPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { contentLang, switchLang } = useContentLang();
  const t = _t[contentLang] || _t.en;

  const [searchQuery, setSearchQuery]   = useState('');
  const [activeFilter, setActiveFilter] = useState('all');
  const deferredQuery = useDeferredValue(searchQuery);
  const [, startTransition] = useTransition();

  const { data: slimBundle, isLoading: slimLoading } = useLibraryBundleSlim();
  // Defer the heavy "full" library bundle (which carries every chapter) until
  // the user actually interacts with the page (search, filter, scroll, tap).
  // A long fallback keeps SEO bots and bounce visitors covered.
  const [chaptersReady, setChaptersReady] = useState(false);
  useEffect(() => {
    if (!slimBundle || chaptersReady) return;
    const fire = () => { setChaptersReady(true); cleanup(); };
    const events = ['pointerdown', 'keydown', 'scroll', 'touchstart'];
    const opts = { passive: true, capture: true, once: true };
    events.forEach((ev) => window.addEventListener(ev, fire, opts));
    const fallback = setTimeout(fire, 6000);
    function cleanup() {
      events.forEach((ev) => window.removeEventListener(ev, fire, { capture: true }));
      clearTimeout(fallback);
    }
    return cleanup;
  }, [slimBundle, chaptersReady]);
  const { data: fullBundle, isFetching, refetch: refetchBundle } = useLibraryBundle(chaptersReady);

  const bundle = fullBundle || slimBundle;
  const bundleLoading = slimLoading;
  const bundleError = !bundle && !slimLoading;
  const subjects    = bundle?.subjects  || [];
  const boards      = bundle?.boards    || [];
  const classes     = bundle?.classes   || [];
  const streams     = bundle?.streams   || [];
  const allChapters = fullBundle?.chapters || [];
  const { data: savedSubjects = [] } = useSavedSubjects(user);
  const toggleSaved = useToggleSavedSubject();
  const handleToggleSave = useCallback((id) => toggleSaved.mutate(id), [toggleSaved]);

  useEffect(() => {
    const handleContentUploaded = () => { refetchBundle(); };
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') refetchBundle();
    };
    window.addEventListener('content-uploaded', handleContentUploaded);
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      window.removeEventListener('content-uploaded', handleContentUploaded);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
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

  const baseChips = contentLang === 'as' ? STREAM_CHIPS_AS : STREAM_CHIPS_EN;
  const allStreamChips = useMemo(() => [...baseChips, ...dynamicStreamChips], [baseChips, dynamicStreamChips]);

  const filteredSubjects = useMemo(() => {
    const q = deferredQuery.trim().toLowerCase();
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
  }, [enrichedSubjects, activeFilter, deferredQuery, savedSubjectsSet, chaptersBySubject]);

  const totalSeoTopics = useMemo(() => {
    return enrichedSubjects.reduce((sum, s) => sum + (s.seo_stats?.topic_count || 0), 0);
  }, [enrichedSubjects]);

  // JSON-LD now emitted via PageMeta (pageType="library"); see src/lib/jsonld.js

  const handleAskAI = useCallback((subjectId, hasDocument = false, subjectName = '') => {
    try { Analytics.chatStart(subjectId, subjectName, 'openai/gpt-oss-20b'); } catch {}
    const params = new URLSearchParams({ subject: subjectId });
    if (hasDocument) params.set('document_id', subjectId);
    navigate(`/chat?${params.toString()}`);
  }, [navigate]);

  const handleResetFilters = useCallback(() => { setSearchQuery(''); setActiveFilter('all'); }, []);

  const searchTimerRef = useRef(null);
  const handleSearchChange = useCallback((e) => {
    const val = e.target.value;
    setSearchQuery(val);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (val.trim().length >= 2) {
      searchTimerRef.current = setTimeout(() => {
        const q = val.trim().toLowerCase();
        const count = enrichedSubjects.filter(s =>
          (s.name || '').toLowerCase().includes(q) ||
          (s.description || '').toLowerCase().includes(q) ||
          (s.topics || []).some(t => (t.name || '').toLowerCase().includes(q))
        ).length;
        Analytics.searchUsed(val.trim(), count);
      }, 1000);
    }
  }, [enrichedSubjects]);
  const handleFilterChange = useCallback((filterId) => {
    startTransition(() => setActiveFilter(filterId));
  }, []);
  const handleSearchClear = useCallback(() => setSearchQuery(''), []);

  // Lightweight windowing — render the first VIRTUAL_CHUNK cards immediately,
  // then progressively reveal the rest as the user scrolls near the bottom of
  // the grid. Keeps initial DOM bounded for catalogues with hundreds of items.
  const VIRTUAL_CHUNK = 30;
  const [renderLimit, setRenderLimit] = useState(VIRTUAL_CHUNK);
  const sentinelRef = useRef(null);
  // Track in state (not just a ref) so child virtualizers re-measure once
  // the scroll container actually mounts.
  const [scrollContainerEl, setScrollContainerEl] = useState(null);
  // Switch to a true windowed renderer once the catalogue grows past the
  // chunk size — keeps DOM nodes bounded so TBT/INP stay flat on mobile
  // even with hundreds of subjects. Task #384.
  const useVirtualGrid = filteredSubjects.length > VIRTUAL_CHUNK;
  useEffect(() => { setRenderLimit(VIRTUAL_CHUNK); }, [activeFilter, deferredQuery]);
  useEffect(() => {
    if (filteredSubjects.length <= renderLimit) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) {
        startTransition(() => setRenderLimit((n) => n + VIRTUAL_CHUNK));
      }
    }, { rootMargin: '600px' });
    io.observe(el);
    return () => io.disconnect();
  }, [filteredSubjects.length, renderLimit]);
  const visibleSubjects = useMemo(
    () => filteredSubjects.slice(0, renderLimit),
    [filteredSubjects, renderLimit]
  );

  const seoTitle = 'Assamboard Subject Library — Notes, MCQs, Definitions & Exam Prep';
  const seoDescription = `Explore ${subjects.length || ''} Assamboard Class 11-12 and Degree subjects with ${totalSeoTopics || ''} study topics. AI-powered notes, MCQs, definitions, important questions, and examples for Assam students.`.replace(/  +/g, ' ').trim();
  const seoKeywords = 'Assam Board study material, AHSEC notes, SEBA notes, Class 11 notes Assam, Class 12 notes Assam, MCQs Assam Board, definitions, important questions, exam preparation Assam, Syrabit';

  if (bundleLoading) {
    return (
      <AppLayout pageTitle="Library" hideNavbar>
        <PageMeta
          title={seoTitle}
          description="Explore Assam Board Class 11-12 and Degree subjects. AI-powered notes, MCQs, definitions, and exam preparation for Assam students."
          url="https://syrabit.ai/library"
          keywords={seoKeywords}
        />
        <LibrarySkeleton />
      </AppLayout>
    );
  }

  if (bundleError && !bundle) {
    return (
      <AppLayout pageTitle="Library" hideNavbar>
        <PageMeta title={seoTitle} url="https://syrabit.ai/library" />
        <div className="flex flex-col items-center justify-center min-h-[60vh] px-4 text-center">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5" style={{ background: 'rgba(239,68,68,0.1)' }}>
            <BookOpen size={28} className="text-red-400" />
          </div>
          <h2 className="text-lg font-semibold text-foreground mb-2">{contentLang === 'as' ? 'লাইব্ৰেৰী ল\'ড কৰিব পৰা নগ\'ল' : 'Failed to load library'}</h2>
          <p className="text-muted-foreground text-sm mb-6 max-w-xs">
            {contentLang === 'as' ? 'ছাৰ্ভাৰৰ সৈতে সংযোগ কৰিব পৰা নগ\'ল। আপোনাৰ সংযোগ পৰীক্ষা কৰি পুনৰ চেষ্টা কৰক।' : 'We couldn\'t reach the server. Please check your connection and try again.'}
          </p>
          <button
            onClick={() => refetchBundle()}
            className="h-11 px-5 rounded-xl text-sm font-medium text-white bg-violet-600 hover:bg-violet-500 transition-all flex items-center gap-2 active:scale-95"
          >
            {contentLang === 'as' ? 'পুনৰ চেষ্টা কৰক' : 'Try Again'}
          </button>
        </div>
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
        pageType="library"
        pageData={{ subjects: filteredSubjects }}
      />
      <div className="flex flex-col h-full w-full overflow-hidden">

        <div
          className="sticky top-0 shrink-0 w-full z-20"
          style={{
            background: 'var(--background)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
            borderBottom: '1px solid rgba(139,92,246,0.08)',
            minHeight: '140px',
            contain: 'layout',
          }}
        >
          <div className="w-full max-w-6xl mx-auto px-4 md:px-6 pt-5 pb-3 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <h1
                  className="text-foreground shimmer-text"
                  style={{ fontSize: 'clamp(0.95rem, 3.2vw, 1.5rem)', fontWeight: 700, lineHeight: 1.25 }}
                >
                  {t.heading}<br />{t.subheading}
                </h1>
                <p className="text-xs sm:text-sm text-muted-foreground mt-1">
                  {t.browse(subjects.length, allChapters.length)}
                </p>
              </div>
              <div className="flex items-center gap-1 shrink-0 rounded-xl p-0.5" style={{ background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.12)' }}>
                <button
                  onClick={() => switchLang('en')}
                  className={`h-9 px-3 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                    contentLang === 'en'
                      ? 'text-white bg-violet-600 shadow-sm'
                      : 'text-violet-600 hover:bg-violet-50'
                  }`}
                  aria-label="Switch to English"
                >
                  English
                </button>
                <button
                  onClick={() => switchLang('as')}
                  className={`h-9 px-3 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
                    contentLang === 'as'
                      ? 'text-white bg-violet-600 shadow-sm'
                      : 'text-violet-600 hover:bg-violet-50'
                  }`}
                  aria-label="Switch to Assamese"
                >
                  অসমীয়া
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
                placeholder={t.searchPlaceholder}
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
                  {t.clear}
                </button>
              )}
            </div>

          </div>
        </div>

        <div className="flex-1 overflow-y-auto" ref={setScrollContainerEl}>
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
                    <h3 className="text-foreground font-semibold text-lg">{t.savedSignIn}</h3>
                    <p className="text-sm text-muted-foreground/60 mt-1.5 max-w-xs">
                      {t.savedSignInDesc}
                    </p>
                    <Link
                      to="/signup"
                      className="mt-5 px-5 py-2 rounded-xl text-sm text-white font-medium transition-all duration-200 active:scale-95"
                      style={{ background: 'hsl(var(--primary))', boxShadow: '0 0 20px hsl(var(--primary)/0.3)' }}
                    >
                      {t.signUpFree}
                    </Link>
                  </>
                ) : activeFilter === 'saved' && user ? (
                  <>
                    <h3 className="text-foreground font-semibold text-lg">{t.noSaved}</h3>
                    <p className="text-sm text-muted-foreground/60 mt-1.5 max-w-xs">
                      {t.noSavedDesc}
                    </p>
                    <button
                      onClick={() => setActiveFilter('all')}
                      className="mt-5 px-5 py-2 rounded-xl text-sm text-white font-medium transition-all duration-200 active:scale-95"
                      style={{ background: 'hsl(var(--primary))', boxShadow: '0 0 20px hsl(var(--primary)/0.3)' }}
                    >
                      {t.browseAll}
                    </button>
                  </>
                ) : (
                  <>
                    <h3 className="text-foreground font-semibold text-lg">{t.noResultsTitle}</h3>
                    <p className="text-sm text-muted-foreground/60 mt-1.5 max-w-xs">
                      {searchQuery
                        ? (contentLang === 'as'
                          ? `"${searchQuery}" ৰ বাবে কোনো ফলাফল নাই — অন্য শব্দ চেষ্টা কৰক বা সন্ধান মচক`
                          : `No results for "${searchQuery}" — try a different term or clear the search`)
                        : (contentLang === 'as'
                          ? 'আৰু বিষয় বিচাৰিবলৈ আপোনাৰ ফিল্টাৰ সালসলনি কৰক'
                          : 'Try adjusting your filters to discover more subjects')}
                    </p>
                    {(searchQuery || activeFilter !== 'all') && (
                      <button
                        onClick={handleResetFilters}
                        className="mt-5 px-4 py-2 rounded-xl text-sm text-primary hover:text-white transition-all duration-200 active:scale-95"
                        style={{ border: '1px solid rgba(139,92,246,0.25)', background: 'rgba(139,92,246,0.06)' }}
                        data-testid="library-reset-filters-button"
                      >
                        {contentLang === 'as' ? 'সকলো ফিল্টাৰ মচক' : 'Reset all filters'}
                      </button>
                    )}
                  </>
                )}
              </div>
            ) : (
              useVirtualGrid ? (
                <VirtualSubjectGrid
                  scrollParent={scrollContainerEl}
                  subjects={filteredSubjects}
                  chaptersBySubject={chaptersBySubject}
                  savedSubjects={savedSubjects}
                  onToggleSave={handleToggleSave}
                  onAskAI={handleAskAI}
                />
              ) : (
              <>
              <div
                className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5"
                data-testid="library-subject-grid"
                style={{ contain: 'layout style', minHeight: '420px' }}
              >
                {visibleSubjects.map((sub, index) => (
                  <SubjectCard
                    key={sub.id}
                    sub={sub}
                    chapters={chaptersBySubject.get(sub.id) || []}
                    isSaved={savedSubjects.includes(sub.id)}
                    onToggleSave={handleToggleSave}
                    onAskAI={handleAskAI}
                    index={index}
                  />
                ))}
              </div>
              {filteredSubjects.length > visibleSubjects.length && (
                <div ref={sentinelRef} aria-hidden="true" style={{ height: 1 }} />
              )}
              </>
              )
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
