import {
  AlertTriangle, CheckCircle, AlertCircle, Loader2,
  Sparkles, RefreshCw, Globe, ChevronDown,
} from 'lucide-react';

export default function ContentGapsPanel({
  showGapPanel, setShowGapPanel,
  gapSubjects, loadGapSubjects, loadingGaps,
  gapGenStatus, gapGenSubject,
  bulkGapSelected, setBulkGapSelected,
  bulkGapGenerating, bulkGapProgress,
  onAutoGenerateGap, onMergeGapToCms, onBulkGapAutoGen,
}) {
  return (
    <div className="rounded-xl border" style={{ borderColor: 'rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.01)' }}>
      <button
        onClick={() => {
          const next = !showGapPanel;
          setShowGapPanel(next);
          if (next && gapSubjects.length === 0) loadGapSubjects();
        }}
        className="w-full flex items-center justify-between px-4 py-3 text-xs font-semibold text-white/40 hover:text-white/70 transition-colors"
      >
        <span className="flex items-center gap-2">
          <AlertTriangle size={12} className={gapSubjects.length > 0 ? 'text-amber-400' : ''} />
          Content Gaps
          {gapSubjects.length > 0 && (
            <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: 'rgba(245,158,11,0.20)', color: '#fbbf24' }}>
              {gapSubjects.length} subjects &lt; 3 chapters
            </span>
          )}
        </span>
        <ChevronDown size={12} className={`transition-transform ${showGapPanel ? 'rotate-180' : ''}`} />
      </button>

      {showGapPanel && (
        <div className="border-t px-4 pb-4 pt-3 space-y-3" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
          <p className="text-xs text-white/30">Subjects with fewer than 3 chapters — auto-generate an overview or merge to CMS.</p>
          <div className="flex items-center gap-2 flex-wrap">
            {bulkGapSelected.size > 0 && !bulkGapGenerating && (
              <button onClick={onBulkGapAutoGen}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg"
                style={{ background: 'rgba(139,92,246,0.25)', color: '#c4b0f0', border: '1px solid rgba(139,92,246,0.35)' }}>
                <Sparkles size={11} /> Generate All ({bulkGapSelected.size})
              </button>
            )}
            {bulkGapGenerating && (
              <span className="flex items-center gap-2 text-xs text-amber-400">
                <Loader2 size={11} className="animate-spin" />
                {bulkGapProgress.done}/{bulkGapProgress.total} generating…
              </span>
            )}
            <button onClick={loadGapSubjects} disabled={loadingGaps}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg disabled:opacity-50 ml-auto"
              style={{ background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.40)', border: '1px solid rgba(255,255,255,0.08)' }}>
              {loadingGaps ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
              Refresh
            </button>
          </div>

          {loadingGaps ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {[...Array(3)].map((_, i) => <div key={i} className="h-24 rounded-xl animate-pulse" style={{ background: 'rgba(255,255,255,0.04)' }} />)}
            </div>
          ) : gapSubjects.length === 0 ? (
            <div className="flex items-center gap-2 py-4 text-sm text-white/40">
              <CheckCircle size={15} className="text-emerald-400" /> All subjects have 3+ chapters
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {gapSubjects.map(s => {
                const status = gapGenStatus[s.id];
                const isGen  = gapGenSubject === s.id;
                const isSel  = bulkGapSelected.has(s.id);
                return (
                  <div key={s.id} className="p-3 rounded-xl border transition-all"
                    style={{
                      borderColor: isSel ? 'rgba(139,92,246,0.35)' : status === 'done' ? 'rgba(52,211,153,0.28)' : 'rgba(255,255,255,0.07)',
                      background:  isSel ? 'rgba(139,92,246,0.07)' : 'rgba(255,255,255,0.02)',
                    }}>
                    <div className="flex items-start gap-2 mb-1.5">
                      <input type="checkbox" checked={isSel}
                        onChange={() => setBulkGapSelected(prev => { const n = new Set(prev); n.has(s.id) ? n.delete(s.id) : n.add(s.id); return n; })}
                        className="rounded accent-violet-500 mt-0.5 flex-shrink-0" />
                      <p className="text-xs font-medium flex-1 min-w-0 text-white">{s.icon || '📚'} {s.name}</p>
                      {status === 'done'   && <CheckCircle size={12} className="text-emerald-400 flex-shrink-0" />}
                      {status === 'failed' && <AlertCircle size={12} className="text-red-400 flex-shrink-0" />}
                    </div>
                    <p className="text-[10px] ml-5 mb-2.5 text-amber-400">{s.chapter_count || 0} / 3 chapters</p>
                    <div className="flex gap-1.5 flex-wrap ml-5">
                      <button onClick={() => onAutoGenerateGap(s)} disabled={isGen || status === 'done'}
                        className="px-2 py-1 rounded-lg text-[10px] font-medium disabled:opacity-40 flex items-center gap-1 flex-1"
                        style={{ background: 'rgba(139,92,246,0.20)', color: '#a78bfa' }}>
                        {isGen ? <Loader2 size={9} className="animate-spin" /> : <Sparkles size={9} />}
                        {status === 'done' ? 'Done!' : isGen ? 'Generating…' : 'Auto-Generate Overview'}
                      </button>
                      <button onClick={() => onMergeGapToCms(s)}
                        className="px-2 py-1 rounded-lg text-[10px] font-medium flex items-center gap-1 flex-1"
                        style={{ background: 'rgba(99,102,241,0.18)', color: '#818cf8' }}>
                        <Globe size={9} /> Merge to CMS
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
