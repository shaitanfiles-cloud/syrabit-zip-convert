import { CheckCircle, ChevronRight, Globe, Loader2, Zap } from 'lucide-react';

export default function WorkflowTracker({
  chapters, selSubject, allChaptersHaveNotes,
  seoTopicsGeneratedIds, assetsGeneratedIds, mergedSubjectIds,
  generatingSeoTopics, publishingBlog,
  onGenerateSeoTopics, onShowPipeline, onPublishAsBlog,
  subjectData, onNavigate,
}) {
  return (
    <div className="flex items-center gap-2 px-4 py-3 rounded-xl border" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.07)' }}>
      <div className={`flex items-center gap-1.5 text-xs font-medium ${chapters.length > 0 ? 'text-emerald-400' : 'text-white/30'}`}>
        {chapters.length > 0 ? <CheckCircle size={13} /> : <div className="w-3.5 h-3.5 rounded-full border-2 border-white/20" />}
        <span>{chapters.length} Chapter{chapters.length !== 1 ? 's' : ''}</span>
      </div>
      <ChevronRight size={11} className="text-white/20" />
      <div className={`flex items-center gap-1.5 text-xs font-medium ${seoTopicsGeneratedIds.has(selSubject) ? 'text-cyan-400' : 'text-white/25'}`}>
        {seoTopicsGeneratedIds.has(selSubject) ? <CheckCircle size={13} /> : <div className="w-3.5 h-3.5 rounded-full border-2 border-white/20" />}
        <span>SEO Topics</span>
      </div>
      <ChevronRight size={11} className="text-white/20" />
      <div className={`flex items-center gap-1.5 text-xs font-medium ${assetsGeneratedIds.has(selSubject) ? 'text-violet-400' : 'text-white/25'}`}>
        {assetsGeneratedIds.has(selSubject) ? <CheckCircle size={13} /> : <div className="w-3.5 h-3.5 rounded-full border-2 border-white/20" />}
        <span>300+ Assets</span>
      </div>
      <ChevronRight size={11} className="text-white/20" />
      <div className={`flex items-center gap-1.5 text-xs font-medium ${mergedSubjectIds.has(selSubject) ? 'text-emerald-400' : 'text-white/25'}`}>
        {mergedSubjectIds.has(selSubject) ? <CheckCircle size={13} /> : <div className="w-3.5 h-3.5 rounded-full border-2 border-white/20" />}
        <span>Published</span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        {onNavigate && (
          <button
            onClick={onGenerateSeoTopics}
            disabled={!selSubject || generatingSeoTopics || chapters.length === 0}
            className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-semibold disabled:opacity-40 transition-all hover:opacity-90"
            style={{ background: 'rgba(6,182,212,0.12)', color: '#67e8f9', border: '1px solid rgba(6,182,212,0.28)' }}
            title={chapters.length === 0 ? 'Add chapters before generating SEO topics' : 'Extract SEO topics for this subject using AI'}
          >
            {generatingSeoTopics ? <Loader2 size={11} className="animate-spin" /> : <Globe size={11} />}
            {generatingSeoTopics ? 'Extracting…' : seoTopicsGeneratedIds.has(selSubject) ? 'SEO Topics ✓' : 'Generate SEO Topics'}
          </button>
        )}
        <button
          onClick={onShowPipeline}
          disabled={chapters.length === 0 || !seoTopicsGeneratedIds.has(selSubject)}
          className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-bold disabled:opacity-40 transition-all hover:opacity-90"
          style={allChaptersHaveNotes
            ? { background: 'linear-gradient(135deg,#0ea5e9,#7c3aed)', color: 'white' }
            : { background: 'linear-gradient(135deg,#7c3aed,#5b21b6)', color: 'white' }}
          title={
            chapters.length === 0
              ? 'Add chapters before running pipeline'
              : !seoTopicsGeneratedIds.has(selSubject)
              ? 'Generate SEO Topics first before running full pipeline'
              : allChaptersHaveNotes
              ? 'SEO Polish — skips re-generation of existing notes/PYQs/flashcards, only publishes blogs & PYQ pages'
              : 'Auto-Generate Full Subject — generates all content, MCQs, blogs & PYQ pages'
          }
        >
          <Zap size={11} /> {allChaptersHaveNotes ? 'SEO Polish ⚡' : 'Auto-Generate Full Subject'}
        </button>
        <button
          onClick={() => onPublishAsBlog(selSubject, subjectData?.name || selSubject)}
          disabled={publishingBlog || chapters.length === 0 || (!assetsGeneratedIds.has(selSubject) && !mergedSubjectIds.has(selSubject))}
          className="flex items-center gap-1.5 h-8 px-4 rounded-lg text-xs font-semibold disabled:opacity-40 transition-all hover:opacity-90"
          style={{
            background: assetsGeneratedIds.has(selSubject)
              ? 'linear-gradient(135deg,#059669,#10b981)'
              : 'linear-gradient(135deg,#7c3aed,#9575e0)',
            color: 'white', boxShadow: '0 2px 8px rgba(124,58,237,0.28)',
          }}
          title={
            chapters.length === 0
              ? 'Add chapters first'
              : (!assetsGeneratedIds.has(selSubject) && !mergedSubjectIds.has(selSubject))
              ? 'Run "Auto-Generate Full Subject" first to build 300+ assets'
              : assetsGeneratedIds.has(selSubject)
              ? '✅ 300+ assets ready — merge & open Blog Publisher'
              : 'Publish merged content as a blog post'
          }
        >
          {publishingBlog ? <Loader2 size={12} className="animate-spin" /> : <Globe size={12} />}
          Publish as Blog
          {assetsGeneratedIds.has(selSubject) && <span style={{ fontSize: 9, marginLeft: 2, opacity: 0.8 }}>✅</span>}
        </button>
      </div>
    </div>
  );
}
