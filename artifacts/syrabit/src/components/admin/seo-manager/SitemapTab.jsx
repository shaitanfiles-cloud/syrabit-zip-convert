import { Loader2, RefreshCw, Map, Sparkles, CheckCircle2, AlertTriangle } from 'lucide-react';

export default function SitemapTab({
  sitemapData, sitemapValidating, handleSitemapValidate,
  refreshingMeta, handleRefreshMeta,
  sitemap, handleRegenerateSitemap,
}) {
  return (
    <div className="space-y-5">
      <div className="rounded-xl border p-5 space-y-4" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.08)' }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-white">Refresh Meta Descriptions</p>
            <p className="text-xs mt-0.5" style={{ color: 'rgba(255,255,255,0.35)' }}>Re-extract meta descriptions from content, diversify titles, and recompute quality scores (no LLM cost)</p>
          </div>
          <button onClick={handleRefreshMeta} disabled={refreshingMeta}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
            style={{ background: '#7c3aed', color: '#fff' }}>
            {refreshingMeta ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {refreshingMeta ? 'Refreshing…' : 'Refresh All Meta'}
          </button>
        </div>
      </div>

      <div className="rounded-xl border p-5 space-y-4" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.08)' }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-white">Sitemap Validator</p>
            <p className="text-xs mt-0.5" style={{ color: 'rgba(255,255,255,0.35)' }}>Validates your sitemap.xml coverage and detects missing or stale URLs</p>
          </div>
          <button onClick={handleSitemapValidate} disabled={sitemapValidating}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
            style={{ background: '#16a34a', color: '#fff' }}>
            {sitemapValidating ? <Loader2 size={14} className="animate-spin" /> : <Map size={14} />}
            {sitemapValidating ? 'Validating…' : 'Validate Sitemap'}
          </button>
        </div>
        {sitemapData && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Total URLs', val: sitemapData.total_urls },
                { label: 'In Sitemap', val: sitemapData.in_sitemap },
                { label: 'Missing', val: sitemapData.missing },
                { label: 'Coverage %', val: sitemapData.coverage_pct != null ? `${sitemapData.coverage_pct}%` : '—' },
              ].map(s => (
                <div key={s.label} className="rounded-lg p-3 text-center border" style={{ background: 'rgba(22,163,74,0.08)', borderColor: 'rgba(22,163,74,0.20)' }}>
                  <p className="text-xl font-bold text-white">{s.val ?? '—'}</p>
                  <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.40)' }}>{s.label}</p>
                </div>
              ))}
            </div>
            {sitemapData.issues?.length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'rgba(255,255,255,0.30)' }}>Issues Detected</p>
                <div className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
                  {sitemapData.issues.map((issue, i) => (
                    <div key={i} className="flex items-start gap-2 p-2 rounded-lg" style={{ background: 'rgba(239,68,68,0.06)' }}>
                      <AlertTriangle size={12} className="text-red-400 flex-shrink-0 mt-0.5" />
                      <span className="text-xs font-mono" style={{ color: 'rgba(232,232,232,0.60)' }}>{issue}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {sitemapData.ok && !sitemapData.issues?.length && (
              <div className="flex items-center gap-2 p-3 rounded-xl" style={{ background: 'rgba(22,163,74,0.08)', border: '1px solid rgba(22,163,74,0.20)' }}>
                <CheckCircle2 size={16} className="text-emerald-400" />
                <p className="text-sm font-medium text-emerald-400">Sitemap is valid — {sitemapData.coverage_pct}% coverage</p>
              </div>
            )}
          </div>
        )}
        {!sitemapData && !sitemapValidating && (
          <p className="text-sm text-center py-4" style={{ color: 'rgba(255,255,255,0.20)' }}>Click "Validate Sitemap" to run a coverage check</p>
        )}
      </div>
      <div className="rounded-xl border p-4" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }}>
        <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: 'rgba(255,255,255,0.25)' }}>Sitemap Actions</p>
        <button onClick={handleRegenerateSitemap} disabled={sitemap}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
          style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.10)', color: 'rgba(232,232,232,0.70)' }}>
          {sitemap ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          Regenerate sitemap.xml
        </button>
      </div>
    </div>
  );
}
