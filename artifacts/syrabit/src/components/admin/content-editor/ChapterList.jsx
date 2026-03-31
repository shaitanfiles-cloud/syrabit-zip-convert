import {
  Sparkles, Loader2, Eye, Edit2, Trash2,
  CheckCircle, FileText, Layers, Globe, AlertTriangle,
  Zap, BookOpen,
} from 'lucide-react';

export default function ChapterList({
  chapters, chapterAssets, selectedChapters, setSelectedChapters,
  generatingNotes, bulkGenerating,
  onGenerateNotes, onDeleteChapter,
  onViewChapter, onEditChapter,
  showAgenticCreator, setShowAgenticCreator,
  autoAgentic, setAutoAgentic,
  onBulkMerge, bulkMerging,
  selSubject, subjectData, onCreateNew,
}) {
  return (
    <>
      <button
        onClick={onCreateNew}
        className="w-full p-5 rounded-xl border border-dashed border-violet-500/30 hover:border-violet-500/60 bg-violet-500/5 hover:bg-violet-500/10 text-center transition-colors"
      >
        <BookOpen size={28} className="mx-auto text-violet-400 mb-2" />
        <p className="text-sm font-bold text-white">Create New Chapter</p>
        <p className="text-[11px] text-white/40 mt-1">Add chapter content with Markdown — slug auto-generated</p>
      </button>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-white">Chapters ({chapters.length})</p>
          <div className="flex items-center gap-2">
            {chapters.length > 0 && (
              <button
                onClick={() => setSelectedChapters(prev => prev.size === chapters.length ? new Set() : new Set(chapters.map(c => c.id)))}
                className="text-[10px] text-white/30 hover:text-white transition-colors"
              >
                {selectedChapters.size === chapters.length ? 'Deselect all' : 'Select all'}
              </button>
            )}
            {chapters.length > 0 && (
              <button
                onClick={() => setShowAgenticCreator(true)}
                className="flex items-center gap-1 h-6 px-2.5 rounded-lg text-[10px] font-semibold transition-all hover:brightness-110"
                style={{ background: 'linear-gradient(135deg,rgba(124,58,237,0.30),rgba(79,70,229,0.30))', color: '#c4b0f0', border: '1px solid rgba(139,92,246,0.30)' }}
                title="Agentic content creator — notes, MCQs, flashcards"
              >
                <Zap size={10} />
                Agentic Generate
              </button>
            )}
            <button
              onClick={() => setAutoAgentic(v => !v)}
              className="flex items-center gap-1 h-6 px-2 rounded-lg text-[10px] font-medium transition-all"
              style={autoAgentic
                ? { background: 'rgba(245,158,11,0.20)', color: '#fbbf24', border: '1px solid rgba(245,158,11,0.35)' }
                : { background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.25)', border: '1px solid rgba(255,255,255,0.08)' }}
              title={autoAgentic ? 'Auto-Agentic ON — notes generation will auto-trigger Agentic Generate' : 'Auto-Agentic OFF — click to enable auto-cascade after notes generation'}
            >
              <Zap size={9} className={autoAgentic ? 'text-amber-400' : ''} />
              Auto-Agentic {autoAgentic ? 'ON' : 'OFF'}
            </button>
          </div>
        </div>

        {selectedChapters.size > 0 && (
          <div className="flex items-center gap-3 px-3 py-2 rounded-xl" style={{ background: 'rgba(149,117,224,0.10)', border: '1px solid rgba(149,117,224,0.20)' }}>
            <span className="text-xs text-violet-300 font-medium">{selectedChapters.size} selected</span>
            <button
              onClick={onBulkMerge}
              disabled={bulkMerging}
              className="flex items-center gap-1.5 h-7 px-3 rounded-lg text-xs font-medium disabled:opacity-40 transition-colors"
              style={{ background: 'rgba(149,117,224,0.25)', color: '#c4b0f0' }}
            >
              {bulkMerging ? <Loader2 size={11} className="animate-spin" /> : <Globe size={11} />}
              Merge to Blog
            </button>
            <button
              onClick={() => setSelectedChapters(new Set())}
              className="ml-auto text-[10px] text-white/30 hover:text-white transition-colors"
            >
              Clear
            </button>
          </div>
        )}

        {chapters.length === 0 && <p className="text-xs text-white/30 py-4 text-center">No chapters yet — create the first one above</p>}
        {chapters.map(ch => {
          const assets   = chapterAssets[ch.id] || {};
          const hasNotes = assets.notesGenerated || (ch.content && ch.content.trim().length > 50);
          const preview  = ch.content ? ch.content.replace(/#{1,6}\s?/g, '').replace(/\*+/g, '').replace(/\n+/g, ' ').trim().slice(0, 130) : '';
          const wordCount = ch.content ? ch.content.split(/\s+/).filter(Boolean).length : 0;
          const hasPyqs   = (assets.pyqCount || 0) > 0;
          const hasFc     = (assets.flashcardCount || 0) > 0;
          const hasBlogs  = (assets.blogCount || 0) > 0;
          const isSelected = selectedChapters.has(ch.id);
          return (
            <div key={ch.id}
              className="rounded-xl border transition-all"
              style={{
                borderColor: isSelected ? 'rgba(149,117,224,0.40)' : hasNotes ? 'rgba(16,185,129,0.18)' : 'rgba(255,255,255,0.08)',
                background:  isSelected ? 'rgba(149,117,224,0.05)' : 'rgba(255,255,255,0.02)',
              }}>
              <div className="flex items-start gap-2 p-3 pb-2">
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={e => setSelectedChapters(prev => {
                    const next = new Set(prev);
                    if (e.target.checked) next.add(ch.id); else next.delete(ch.id);
                    return next;
                  })}
                  className="rounded flex-shrink-0 accent-violet-500 cursor-pointer mt-0.5"
                  onClick={e => e.stopPropagation()}
                />
                <div className="flex-shrink-0 mt-1">
                  {hasNotes
                    ? <div className="w-2 h-2 rounded-full bg-emerald-400" title="Notes generated" />
                    : <div className="w-2 h-2 rounded-full bg-white/15" title="No notes yet" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-sm font-semibold text-white truncate">{ch.title}</p>
                    {ch.content_type && ch.content_type !== 'notes' && (
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-white/10 text-white/40 uppercase tracking-wide">{ch.content_type}</span>
                    )}
                    {wordCount > 0 && (
                      <span className="text-[9px] text-white/25 font-mono">{wordCount.toLocaleString()} words</span>
                    )}
                  </div>
                  {ch.description && !preview && (
                    <p className="text-xs text-white/35 mt-0.5 truncate">{ch.description}</p>
                  )}
                  {preview && (
                    <p className="text-[11px] text-white/40 mt-1 leading-relaxed line-clamp-2">{preview}{preview.length >= 130 ? '…' : ''}</p>
                  )}
                  {!hasNotes && !preview && (
                    <p className="text-[11px] text-white/20 mt-1 italic">No notes yet — generate with AI or edit manually</p>
                  )}
                </div>
                <div className="flex gap-0.5 flex-shrink-0 ml-1">
                  <button
                    onClick={() => onGenerateNotes(ch.id, ch.title)}
                    disabled={generatingNotes.has(ch.id) || bulkGenerating}
                    className="flex items-center gap-1 h-6 px-2 rounded-lg text-[10px] font-semibold disabled:opacity-40 transition-all hover:brightness-110"
                    style={hasNotes
                      ? { background: 'rgba(16,185,129,0.15)', color: '#6ee7b7', border: '1px solid rgba(16,185,129,0.25)' }
                      : { background: 'linear-gradient(135deg,rgba(124,58,237,0.35),rgba(79,70,229,0.35))', color: '#c4b0f0', border: '1px solid rgba(139,92,246,0.35)' }}
                    title={hasNotes ? 'Regenerate AI notes for this chapter' : 'Generate AI notes for this chapter'}
                  >
                    {generatingNotes.has(ch.id)
                      ? <><Loader2 size={10} className="animate-spin" /> Generating…</>
                      : <><Sparkles size={10} /> {hasNotes ? 'Regen' : 'AI ⚡'}</>}
                  </button>
                  <button onClick={() => onViewChapter(ch)} className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-white/30 hover:text-emerald-400" title="Preview lesson" data-testid={`open-chapter-${ch.id}`}><Eye size={13} /></button>
                  <button onClick={() => onEditChapter(ch)}
                    className="p-1.5 rounded-lg hover:bg-violet-500/10 text-white/30 hover:text-violet-400" title="Edit chapter"><Edit2 size={13} /></button>
                  <button onClick={() => onDeleteChapter(ch.id)} className="p-1.5 rounded-lg hover:bg-red-500/10 text-white/30 hover:text-red-400" title="Delete chapter"><Trash2 size={13} /></button>
                </div>
              </div>
              {(hasNotes || hasPyqs || hasFc || hasBlogs || ch.slug) && (
                <div className="flex items-center gap-1.5 px-3 pb-2.5 flex-wrap">
                  {hasNotes && (
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-semibold"
                      style={{ background: 'rgba(16,185,129,0.12)', color: '#6ee7b7', border: '1px solid rgba(16,185,129,0.20)' }}>
                      <CheckCircle size={9} /> Notes
                    </span>
                  )}
                  {hasPyqs && (
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-semibold"
                      style={{ background: 'rgba(245,158,11,0.12)', color: '#fcd34d', border: '1px solid rgba(245,158,11,0.20)' }}>
                      <FileText size={9} /> {assets.pyqCount} PYQs
                    </span>
                  )}
                  {hasFc && (
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-semibold"
                      style={{ background: 'rgba(16,185,129,0.10)', color: '#6ee7b7', border: '1px solid rgba(16,185,129,0.18)' }}>
                      <Layers size={9} /> {assets.flashcardCount} Flashcards
                    </span>
                  )}
                  {hasBlogs && (
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-semibold"
                      style={{ background: 'rgba(59,130,246,0.12)', color: '#93c5fd', border: '1px solid rgba(59,130,246,0.20)' }}>
                      <Globe size={9} /> {assets.blogCount} Blogs
                    </span>
                  )}
                  {assets.pyqPage && (
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-semibold"
                      style={{ background: 'rgba(236,72,153,0.10)', color: '#f9a8d4', border: '1px solid rgba(236,72,153,0.18)' }}>
                      <Sparkles size={9} /> PYQ Page
                    </span>
                  )}
                  {ch.coverage_score != null && (
                    <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-semibold"
                      style={ch.coverage_score < 60
                        ? { background: 'rgba(239,68,68,0.12)', color: '#fca5a5', border: '1px solid rgba(239,68,68,0.25)' }
                        : ch.coverage_score < 80
                        ? { background: 'rgba(245,158,11,0.12)', color: '#fcd34d', border: '1px solid rgba(245,158,11,0.20)' }
                        : { background: 'rgba(16,185,129,0.12)', color: '#6ee7b7', border: '1px solid rgba(16,185,129,0.20)' }
                      }
                      title={ch.coverage_score < 60 ? 'Low syllabus coverage — consider regenerating' : `${ch.coverage_score}% of syllabus topics covered`}
                    >
                      {ch.coverage_score < 60 && <AlertTriangle size={9} />}
                      {ch.coverage_score >= 60 && <CheckCircle size={9} />}
                      {ch.coverage_score}% Coverage
                    </span>
                  )}
                  {ch.slug && !hasPyqs && !hasFc && !hasBlogs && (
                    <span className="text-[9px] text-white/20 font-mono">/{ch.slug}</span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
