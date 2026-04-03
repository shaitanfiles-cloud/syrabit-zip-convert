import { useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import PageMeta from '@/components/seo/PageMeta';
import {
  BookOpen, ChevronRight, Home, Sparkles,
  Layers, ArrowLeft, Search,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useResolveSubject, useChapters } from '@/hooks/useContent';

export default function SubjectLandingPage() {
  const { board, classSlug, subjectSlug } = useParams();
  const [searchQuery, setSearchQuery] = useState('');

  const { data: subject = null, isLoading: subjectLoading, error: subjectError } = useResolveSubject(board, classSlug, subjectSlug);
  const subjectId = subject?.id || subject?._id;
  const { data: chapters = [], isLoading: chaptersLoading } = useChapters(subjectId);
  const loading = subjectLoading || (!!subjectId && chaptersLoading);
  const error = subjectError
    ? (subjectError.response?.status === 404 ? 'Subject not found' : 'Failed to load subject')
    : null;

  const filteredChapters = useMemo(() => {
    if (!searchQuery.trim()) return chapters;
    const q = searchQuery.toLowerCase();
    return chapters.filter((ch) =>
      ch.title?.toLowerCase().includes(q) ||
      ch.description?.toLowerCase().includes(q)
    );
  }, [chapters, searchQuery]);

  const basePath = `/${board}/${classSlug}/${subjectSlug}`;

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0a1a] text-white">
        <div className="max-w-4xl mx-auto px-4 py-8">
          <Skeleton className="h-4 w-48 mb-6 bg-white/5" />
          <Skeleton className="h-10 w-full mb-4 bg-white/5" />
          <Skeleton className="h-4 w-64 mb-8 bg-white/5" />
          {[...Array(5)].map((_, i) => (
            <Skeleton key={i} className="h-20 w-full mb-3 rounded-xl bg-white/5" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !subject) {
    return (
      <div className="min-h-screen bg-[#0a0a1a] text-white flex items-center justify-center">
        <div className="text-center max-w-md px-6">
          <div className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mx-auto mb-5">
            <BookOpen size={28} className="text-gray-500" />
          </div>
          <h1 className="text-2xl font-bold mb-3">{error || 'Subject not found'}</h1>
          <p className="text-gray-400 mb-6">We couldn't find this subject. It may not be available yet.</p>
          <Link to="/library" className="inline-flex items-center gap-2 px-6 py-3 bg-purple-600 hover:bg-purple-700 rounded-xl text-white font-medium transition-colors">
            <ArrowLeft size={16} />
            Back to Browser
          </Link>
        </div>
      </div>
    );
  }

  const subjectName = subject.name || subjectSlug;
  const boardName = subject.board_name || board;
  const className = subject.class_name || classSlug;
  const streamName = subject.stream_name || '';

  return (
    <div className="min-h-screen bg-[#0a0a1a] text-white">
      <PageMeta
        title={`${subjectName} — ${boardName} ${className} Notes & Study Material`}
        description={subject.description || `Complete ${subjectName} study material for ${boardName} ${className} students. Notes, MCQs, important questions, and AI-powered tutoring.`}
        url={`https://syrabit.ai${basePath}`}
      />

      {/* Header */}
      <header className="border-b border-white/5" style={{ background: 'rgba(10,10,26,0.95)', backdropFilter: 'blur(12px)' }}>
        <div className="max-w-4xl mx-auto px-4 py-5">
          <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm text-gray-400 mb-4 flex-wrap">
            <Link to="/" className="hover:text-purple-400 transition-colors flex items-center gap-1">
              <Home size={13} /> Home
            </Link>
            <ChevronRight size={11} className="text-gray-600" />
            <Link to="/library" className="hover:text-purple-400 transition-colors">Browser</Link>
            <ChevronRight size={11} className="text-gray-600" />
            <span className="text-white/80 font-medium">{subjectName}</span>
          </nav>

          <div className="flex items-start gap-3 sm:gap-4">
            <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl flex items-center justify-center text-xl sm:text-2xl shrink-0" style={{ background: 'linear-gradient(135deg, rgba(124,58,237,0.15), rgba(139,92,246,0.08))', border: '1px solid rgba(139,92,246,0.2)' }}>
              {subject.icon || '📚'}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                <Badge variant="outline" className="text-[11px] text-purple-400 border-purple-500/25 bg-purple-500/5">{boardName}</Badge>
                <Badge variant="outline" className="text-[11px] text-blue-400 border-blue-500/25 bg-blue-500/5">{className}</Badge>
                {streamName && <Badge variant="outline" className="text-[11px] text-emerald-400 border-emerald-500/25 bg-emerald-500/5">{streamName}</Badge>}
              </div>
              <h1 className="text-xl sm:text-2xl md:text-3xl font-bold text-white leading-tight">
                {subjectName}
              </h1>
              {subject.description && (
                <p className="text-gray-400 mt-1.5 text-sm leading-relaxed max-w-2xl line-clamp-2 sm:line-clamp-none">
                  {subject.description}
                </p>
              )}
              <div className="flex items-center gap-3 mt-2.5 text-xs sm:text-sm text-gray-500">
                <span className="flex items-center gap-1">
                  <Layers size={12} />
                  {chapters.length} chapters
                </span>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <div className="max-w-4xl mx-auto px-4 py-6">
        {/* Search */}
        {chapters.length > 4 && (
          <div className="relative mb-6">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search chapters..."
              className="w-full h-10 pl-10 pr-4 rounded-xl text-sm bg-white/[0.04] border border-white/10 text-white placeholder:text-gray-500 outline-none focus:border-purple-500/30 transition-colors"
            />
          </div>
        )}

        {/* AI CTA bar */}
        <Link
          to={`/chat?subject=${subject.id || subject._id || ''}`}
          className="flex items-center gap-3 mb-6 px-4 sm:px-5 py-3.5 rounded-2xl transition-all hover:border-purple-500/30"
          style={{
            background: 'linear-gradient(135deg, rgba(124,58,237,0.08), rgba(139,92,246,0.04))',
            border: '1px solid rgba(139,92,246,0.15)',
          }}
        >
          <Sparkles size={16} className="text-purple-400 shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="text-sm font-medium text-white">Ask AI about {subjectName}</span>
            <span className="hidden sm:inline text-xs text-gray-500 ml-2">Get instant answers aligned with your syllabus</span>
          </div>
          <ChevronRight size={16} className="text-gray-500 shrink-0" />
        </Link>

        {/* Chapter list */}
        <div className="space-y-3">
          {filteredChapters.length === 0 ? (
            <div className="text-center py-12">
              <BookOpen size={32} className="mx-auto mb-3 text-gray-600" />
              <p className="text-gray-400">{searchQuery ? 'No chapters match your search' : 'No chapters available yet'}</p>
            </div>
          ) : (
            filteredChapters.map((ch, i) => {
              const chPath = ch.slug
                ? `${basePath}/${ch.slug}`
                : `${basePath}`;

              return (
                <div
                  key={ch.id || i}
                  className="rounded-2xl overflow-hidden transition-all hover:border-purple-500/15"
                  style={{
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.06)',
                  }}
                >
                  <Link
                    to={chPath}
                    className="flex items-center gap-3 px-5 py-4 group/ch hover:bg-white/[0.02] transition-colors"
                  >
                    <span
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold shrink-0"
                      style={{ background: 'rgba(139,92,246,0.10)', color: 'rgb(167,139,250)' }}
                    >
                      {i + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <h3 className="text-sm font-semibold text-white group-hover/ch:text-purple-300 transition-colors">
                        {ch.title}
                      </h3>
                      {ch.description && (
                        <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">{ch.description}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {ch.content_type && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-gray-400">{ch.content_type}</span>
                      )}
                      <ChevronRight size={16} className="text-gray-600 group-hover/ch:text-purple-400 transition-colors" />
                    </div>
                  </Link>
                </div>
              );
            })
          )}
        </div>

        {/* Tags */}
        {subject.tags?.length > 0 && (
          <div className="mt-8 p-5 rounded-2xl" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}>
            <h3 className="text-sm font-semibold text-gray-400 mb-3">Related Topics</h3>
            <div className="flex flex-wrap gap-2">
              {subject.tags.map((tag) => (
                <span key={tag} className="text-xs px-3 py-1.5 rounded-full bg-purple-500/5 text-purple-300 border border-purple-500/15">
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <nav className="mt-10 pt-6 border-t border-white/5" aria-label="Site navigation">
          <div className="flex flex-wrap gap-4 justify-center text-xs text-gray-500">
            <Link to="/" className="hover:text-purple-400 transition-colors">Home</Link>
            <Link to="/library" className="hover:text-purple-400 transition-colors">Browser</Link>
            <Link to="/pricing" className="hover:text-purple-400 transition-colors">Plans & Pricing</Link>
            <Link to="/chat" className="hover:text-purple-400 transition-colors">Ask Syra</Link>
          </div>
          <p className="text-center text-xs text-gray-600 mt-3">
            Syrabit.ai — AI-powered exam prep for AssamBoard students (AHSEC · DEGREE · SEBA)
          </p>
        </nav>
      </div>
    </div>
  );
}
