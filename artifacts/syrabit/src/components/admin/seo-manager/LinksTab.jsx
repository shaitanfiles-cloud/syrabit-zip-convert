import { Loader2, Activity, ArrowRight } from 'lucide-react';

export default function LinksTab({
  linksData, linksLoading, handleLinksAnalyze,
  injectSlug, setInjectSlug, injecting, handleLinksInject,
}) {
  return (
    <div className="space-y-5">
      <div className="rounded-xl border p-5 space-y-4" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-gray-900">Internal Link Analysis</p>
            <p className="text-xs mt-0.5" style={{ color: '#9ca3af' }}>Analyzes all published pages and maps semantic link opportunities</p>
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
                <p className="text-xl font-bold text-gray-900">{s.val ?? '—'}</p>
                <p className="text-[11px] mt-0.5" style={{ color: '#6b7280' }}>{s.label}</p>
              </div>
            ))}
          </div>
        )}
        {linksData?.top_opportunities?.length > 0 && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: '#9ca3af' }}>Top Link Opportunities</p>
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {linksData.top_opportunities.slice(0, 20).map((op, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg" style={{ background: '#f9fafb' }}>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: 'rgba(124,58,237,0.15)', color: '#a78bfa' }}>
                    {(op.score * 100).toFixed(0)}%
                  </span>
                  <span className="text-xs flex-1 truncate" style={{ color: '#4b5563' }}>{op.source_slug}</span>
                  <ArrowRight size={11} style={{ color: '#9ca3af', flexShrink: 0 }} />
                  <span className="text-xs flex-1 truncate text-right" style={{ color: '#6b7280' }}>{op.target_slug}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="rounded-xl border p-5 space-y-3" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
        <p className="text-sm font-semibold text-gray-900">Inject Links into a Page</p>
        <div className="flex gap-2">
          <input value={injectSlug} onChange={e => setInjectSlug(e.target.value)}
            placeholder="page-slug (e.g. ahsec/class-11/physics/motion/notes)"
            className="flex-1 h-9 px-3 rounded-xl text-sm outline-none font-mono"
            style={{ background: '#f3f4f6', border: '1px solid #e5e7eb', color: '#374151' }} />
          <button onClick={handleLinksInject} disabled={injecting || !injectSlug.trim()}
            className="px-4 h-9 rounded-xl text-sm font-semibold disabled:opacity-40"
            style={{ background: '#059669', color: '#fff' }}>
            {injecting ? <Loader2 size={14} className="animate-spin" /> : 'Inject'}
          </button>
        </div>
        <p className="text-[11px]" style={{ color: '#9ca3af' }}>
          Injects contextually-relevant internal links into the specified page using semantic similarity.
        </p>
      </div>
    </div>
  );
}
