import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Search, Bookmark,
  BookOpen, RefreshCw, Sun, Moon,
} from 'lucide-react';
import { useTheme } from 'next-themes';
import { toast } from 'sonner';
import { Toaster } from '@/components/ui/sonner';
import PageMeta from '@/components/seo/PageMeta';
import { Analytics } from '@/utils/analytics';
import { AppLayout } from '@/components/layout/AppLayout';
import { useAuth } from '@/context/AuthContext';
import {
  useLibraryBundle, useSavedSubjects,
} from '@/hooks/useContent';
import { useToggleSavedSubject } from '@/hooks/useUser';
import SubjectCard from './library/SubjectCard';
import CmsDocsSection from './library/CmsDocsSection';
import CmsPostsGrid from './library/CmsPostsGrid';
import LibrarySkeleton from './library/LibrarySkeleton';
import FilterChip from './library/FilterChip';
import ScrollableFilterRow from './library/ScrollableFilterRow';

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
  const [selectedBoardSlug, setSelectedBoardSlug] = useState('all');
  const [selectedClassSlug, setSelectedClassSlug] = useState('all');

  const { data: bundle, isLoading: bundleLoading, isFetching, refetch: refetchBundle } = useLibraryBundle();
  const subjects    = bundle?.subjects  || [];
  const boards      = bundle?.boards    || [];
  const classes     = bundle?.classes   || [];
  const streams     = bundle?.streams   || [];
  const allChapters = bundle?.chapters  || [];
  const { data: savedSubjects = [] } = useSavedSubjects(user);
  const toggleSaved = useToggleSavedSubject();

  const profileApplied = useRef(false);
  useEffect(() => {
    if (profileApplied.current || !boards.length || !classes.length) return;
    const boardId = user?.board_id || getOnboardingProfile()?.board_id;
    const classId = user?.class_id || getOnboardingProfile()?.class_id;
    if (!boardId) return;
    profileApplied.current = true;
    const board = boards.find((b) => b.id === boardId);
    if (board?.slug) setSelectedBoardSlug(board.slug);
    if (classId) {
      const cls = classes.find((c) => c.id === classId);
      if (cls?.slug) setSelectedClassSlug(cls.slug);
    }
  }, [boards, classes, user]);

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
    const filtered = enrichedSubjects.filter((sub) => {
      if (selectedBoardSlug !== 'all' && sub.boardSlug !== selectedBoardSlug) return false;
      if (selectedClassSlug !== 'all' && sub.classSlug !== selectedClassSlug) return false;
      return true;
    });
    for (const sub of filtered) {
      if (sub.streamSlug && !streamSlugs.has(sub.streamSlug)) {
        streamSlugs.add(sub.streamSlug);
        chips.push({ id: sub.streamSlug, label: sub.streamName || sub.streamSlug });
      }
    }
    return chips;
  }, [enrichedSubjects, selectedBoardSlug, selectedClassSlug]);

  const allStreamChips = useMemo(() => [...STREAM_CHIPS, ...dynamicStreamChips], [dynamicStreamChips]);

  const boardChips = useMemo(() => {
    const chips = [{ id: 'all', label: 'All Boards' }];
    for (const b of boards) {
      if (b.slug) chips.push({ id: b.slug, label: b.name || b.slug });
    }
    return chips;
  }, [boards]);

  const classChips = useMemo(() => {
    if (selectedBoardSlug === 'all') return [];
    const board = boards.find((b) => b.slug === selectedBoardSlug);
    if (!board) return [];
    const boardClasses = classes.filter((c) => c.board_id === board.id);
    if (boardClasses.length <= 1) return [];
    const chips = [{ id: 'all', label: 'All' }];
    for (const c of boardClasses) {
      if (c.slug) chips.push({ id: c.slug, label: c.name || c.slug });
    }
    return chips;
  }, [selectedBoardSlug, boards, classes]);

  const filteredSubjects = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const seen = new Set();
    return enrichedSubjects.filter((sub) => {
      if (seen.has(sub.id)) return false;
      seen.add(sub.id);
      if (sub.status && sub.status !== 'published') return false;
      if (selectedBoardSlug !== 'all' && sub.boardSlug !== selectedBoardSlug) return false;
      if (selectedClassSlug !== 'all' && sub.classSlug !== selectedClassSlug) return false;
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
  }, [enrichedSubjects, activeFilter, searchQuery, savedSubjectsSet, selectedBoardSlug, selectedClassSlug, chaptersBySubject]);

  useEffect(() => {
    if (!filteredSubjects.length) return;
    const script = document.createElement('script');
    script.type = 'application/ld+json';
    script.id = 'library-jsonld';
    script.text = JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'ItemList',
      name: 'Assamboard Subject Library',
      itemListElement: filteredSubjects.map((s, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        name: s.name,
        url: s.boardSlug && s.classSlug && s.streamSlug && s.slug
          ? `https://syrabit.ai/${s.boardSlug}/${s.classSlug}/${s.streamSlug}/${s.slug}`
          : `https://syrabit.ai/subject/${s.id}`,
      })),
    });
    const existing = document.getElementById('library-jsonld');
    if (existing) existing.remove();
    document.head.appendChild(script);
    return () => { const el = document.getElementById('library-jsonld'); if (el) el.remove(); };
  }, [filteredSubjects]);

  const handleAskAI = useCallback((subjectId, hasDocument = false, subjectName = '') => {
    try { Analytics.chatStart(subjectId, subjectName, 'openai/gpt-oss-20b'); } catch {}
    const params = new URLSearchParams({ subject: subjectId });
    if (hasDocument) params.set('document_id', subjectId);
    navigate(`/chat?${params.toString()}`);
  }, [navigate]);

  const handleResetFilters = useCallback(() => { setSearchQuery(''); setActiveFilter('all'); setSelectedBoardSlug('all'); setSelectedClassSlug('all'); }, []);

  const handleRefetchSubjects = useCallback(async () => { await refetchBundle(); toast.success('Browser refreshed'); }, [refetchBundle]);

  const handleSearchChange = useCallback((e) => setSearchQuery(e.target.value), []);
  const handleFilterChange = useCallback((filterId) => setActiveFilter(filterId), []);
  const handleSearchClear = useCallback(() => setSearchQuery(''), []);
  const handleBoardChange = useCallback((slug) => { setSelectedBoardSlug(slug); setSelectedClassSlug('all'); setActiveFilter('all'); }, []);
  const handleClassChange = useCallback((slug) => { setSelectedClassSlug(slug); setActiveFilter('all'); }, []);

  if (bundleLoading) {
    return (
      <AppLayout pageTitle="Library" hideNavbar>
        <PageMeta
          title="Assamboard Subject Library"
          description="Explore Assamboard Class 11-12 and Degree subjects. AI-powered notes, chapters, and exam preparation for Assam students."
          url="https://syrabit.ai/library"
        />
        <LibrarySkeleton />
      </AppLayout>
    );
  }

  return (
    <AppLayout pageTitle="Library" hideNavbar>
      <Toaster richColors position="top-right" />
      <PageMeta
        title="Assamboard Subject Library"
        description="Explore Assamboard Class 11-12 and Degree subjects. AI-powered notes, chapters, and exam preparation for Assam students."
        url="https://syrabit.ai/library"
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
                  style={{ fontSize: 'clamp(1.15rem, 4vw, 1.5rem)', fontWeight: 700, lineHeight: 1.3 }}
                >
                  Your Educational Browser
                </h1>
                <p className="text-xs sm:text-sm text-muted-foreground mt-1">
                  Browse {subjects.length} subjects · {allChapters.length} lessons
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                  title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
                  aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
                  className="h-9 w-9 rounded-xl flex items-center justify-center text-muted-foreground hover:text-primary hover:bg-primary/10 transition-all duration-200"
                >
                  {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
                </button>
                <button
                  onClick={handleRefetchSubjects}
                  disabled={isFetching}
                  className="h-9 px-3.5 rounded-xl text-xs font-medium text-white bg-violet-600 hover:bg-violet-500 disabled:opacity-60 transition-all flex items-center gap-1.5 active:scale-95"
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

            {boardChips.length > 2 && (
              <ScrollableFilterRow
                role="group"
                aria-label="Board filters"
                className="pb-2"
                data-testid="library-board-chips"
              >
                {boardChips.map((chip) => (
                  <FilterChip
                    key={`board-${chip.id}`}
                    chip={chip}
                    isActive={chip.id === selectedBoardSlug}
                    onClick={() => handleBoardChange(chip.id)}
                  />
                ))}
              </ScrollableFilterRow>
            )}
            {classChips.length > 0 && (
              <ScrollableFilterRow
                role="group"
                aria-label="Class filters"
                className="pb-2"
                data-testid="library-class-chips"
              >
                {classChips.map((chip) => (
                  <FilterChip
                    key={`class-${chip.id}`}
                    chip={chip}
                    isActive={chip.id === selectedClassSlug}
                    onClick={() => handleClassChange(chip.id)}
                  />
                ))}
              </ScrollableFilterRow>
            )}
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
                    {(searchQuery || activeFilter !== 'all' || selectedBoardSlug !== 'all' || selectedClassSlug !== 'all') && (
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
          <CmsDocsSection />
          <CmsPostsGrid />
        </div>

      </div>
    </AppLayout>
  );
}
