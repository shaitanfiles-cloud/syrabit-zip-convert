import { Loader2, RefreshCw, Map, Sparkles, CheckCircle2, AlertTriangle } from 'lucide-react';

export default function SitemapTab({
  sitemapData, sitemapValidating, handleSitemapValidate,
  refreshingMeta, handleRefreshMeta,
  sitemap, handleRegenerateSitemap,
}) {
  return (
    <div className="space-y-5">
      <div className="rounded-xl border p-5 space-y-4" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-gray-900">Refresh Meta Descriptions</p>
            <p className="text-xs mt-0.5" style={{ color: '#9ca3af' }}>Re-extract meta descriptions from content, diversify titles, and recompute quality scores (no LLM cost)</p>
          </div>
          <button onClick={handleRefreshMeta} disabled={refreshingMeta}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
            style={{ background: '#7c3aed', color: '#fff' }}>
            {refreshingMeta ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {refreshingMeta ? 'Refreshing…' : 'Refresh All Meta'}
          </button>
        </div>
      </div>

      <div className="rounded-xl border p-5 space-y-4" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-gray-900">Sitemap Validator</p>
            <p className="text-xs mt-0.5" style={{ color: '#9ca3af' }}>Validates your sitemap.xml coverage and detects missing or stale URLs</p>
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
                  <p className="text-xl font-bold text-gray-900">{s.val ?? '—'}</p>
                  <p className="text-[11px] mt-0.5" style={{ color: '#6b7280' }}>{s.label}</p>
                </div>
              ))}
            </div>
            {sitemapData.issues?.length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: '#9ca3af' }}>Issues Detected</p>
                <div className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
                  {sitemapData.issues.map((issue, i) => (
                    <div key={i} className="flex items-start gap-2 p-2 rounded-lg" style={{ background: 'rgba(239,68,68,0.06)' }}>
                      <AlertTriangle size={12} className="text-red-400 flex-shrink-0 mt-0.5" />
                      <span className="text-xs font-mono" style={{ color: '#6b7280' }}>{issue}</span>
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
          <p className="text-sm text-center py-4" style={{ color: '#d1d5db' }}>Click "Validate Sitemap" to run a coverage check</p>
        )}
      </div>
      <div className="rounded-xl border p-4" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
        <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: '#9ca3af' }}>Sitemap Actions</p>
        <button onClick={handleRegenerateSitemap} disabled={sitemap}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
          style={{ background: '#e5e7eb', border: '1px solid #e5e7eb', color: '#4b5563' }}>
          {sitemap ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          Regenerate sitemap.xml
        </button>
      </div>
    </div>
  );
}
