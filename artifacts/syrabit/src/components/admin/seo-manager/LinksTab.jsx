import { Loader2, Activity, ArrowRight } from 'lucide-react';

export default function LinksTab({
  linksData, linksLoading, handleLinksAnalyze,
  injectSlug, setInjectSlug, injecting, handleLinksInject,
}) {
  return (
    <div className="space-y-5">
      <div className="rounded-xl border p-5 space-y-4" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.08)' }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-white">Internal Link Analysis</p>
            <p className="text-xs mt-0.5" style={{ color: 'rgba(255,255,255,0.35)' }}>Analyzes all published pages and maps semantic link opportunities</p>
          </div>
          <button onClick={handleLinksAnalyze} disabled={linksLoading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
            style={{ background: '#7c3aed', color: '#fff' }}>
            {linksLoading ? <Loader2 size={14} className="animate-spin" /> : <Activity size={14} />}
            {linksLoading ? 'Analyzing…' : 'Analyze Links'}
          </button>
        </div>
        {linksData && (
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'Pages Analyzed', val: linksData.pages_analyzed },
              { label: 'Opportunities', val: linksData.total_opportunities },
              { label: 'High Priority', val: linksData.high_priority },
            ].map(s => (
              <div key={s.label} className="rounded-lg p-3 text-center border" style={{ background: 'rgba(124,58,237,0.08)', borderColor: 'rgba(124,58,237,0.20)' }}>
                <p className="text-xl font-bold text-white">{s.val ?? '—'}</p>
                <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.40)' }}>{s.label}</p>
              </div>
            ))}
          </div>
        )}
        {linksData?.top_opportunities?.length > 0 && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: 'rgba(255,255,255,0.30)' }}>Top Link Opportunities</p>
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {linksData.top_opportunities.slice(0, 20).map((op, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg" style={{ background: 'rgba(255,255,255,0.03)' }}>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: 'rgba(124,58,237,0.15)', color: '#a78bfa' }}>
                    {(op.score * 100).toFixed(0)}%
                  </span>
                  <span className="text-xs flex-1 truncate" style={{ color: 'rgba(232,232,232,0.70)' }}>{op.source_slug}</span>
                  <ArrowRight size={11} style={{ color: 'rgba(255,255,255,0.25)', flexShrink: 0 }} />
                  <span className="text-xs flex-1 truncate text-right" style={{ color: 'rgba(255,255,255,0.40)' }}>{op.target_slug}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="rounded-xl border p-5 space-y-3" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.08)' }}>
        <p className="text-sm font-semibold text-white">Inject Links into a Page</p>
        <div className="flex gap-2">
          <input value={injectSlug} onChange={e => setInjectSlug(e.target.value)}
            placeholder="page-slug (e.g. ahsec/class-11/physics/motion/notes)"
            className="flex-1 h-9 px-3 rounded-xl text-sm outline-none font-mono"
            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.10)', color: '#E8E8E8' }} />
          <button onClick={handleLinksInject} disabled={injecting || !injectSlug.trim()}
            className="px-4 h-9 rounded-xl text-sm font-semibold disabled:opacity-40"
            style={{ background: '#059669', color: '#fff' }}>
            {injecting ? <Loader2 size={14} className="animate-spin" /> : 'Inject'}
          </button>
        </div>
        <p className="text-[11px]" style={{ color: 'rgba(255,255,255,0.25)' }}>
          Injects contextually-relevant internal links into the specified page using semantic similarity.
        </p>
      </div>
    </div>
  );
}
