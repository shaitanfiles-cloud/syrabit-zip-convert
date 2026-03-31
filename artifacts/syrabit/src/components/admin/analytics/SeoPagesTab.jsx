import { Globe, Eye, BarChart2, FileText, ExternalLink, Loader2,
  CheckCircle, AlertCircle, Link as LinkIcon } from 'lucide-react';
import { Card, Stat } from './shared';

export default function SeoPagesTab({
  data, vs, ga4Status, ga4Testing, ga4TestResult,
  handleGA4Connect, handleGA4Test, onNavigate,
}) {
  const hasTopPages  = data?.top_pages?.length > 0;
  const hasReferrers = data?.top_referrers?.length > 0;

  return (
    <>
      {onNavigate && (
        <div className="flex justify-end mb-3">
          <button
            onClick={() => onNavigate('seomanager')}
            className="flex items-center gap-1.5 h-8 px-4 rounded-lg text-xs font-semibold transition-all hover:opacity-80"
            style={{ background: 'rgba(6,182,212,0.12)', color: '#67e8f9', border: '1px solid rgba(6,182,212,0.28)' }}
          >
            <Globe size={12} /> Go to SEO Manager →
          </button>
        </div>
      )}

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-8 h-8 rounded-lg bg-blue-900/40 flex items-center justify-center">
            <Globe size={14} className="text-blue-400" />
          </div>
          <div className="flex-1">
            <h3 className="text-slate-200 font-medium text-sm">Google Analytics 4</h3>
            <p className="text-slate-500 text-xs">Real visitor & page data from GA4</p>
          </div>
          {ga4Status && (
            <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
              ga4Status.connected ? 'bg-emerald-900/40 text-emerald-400' : 'bg-slate-800 text-slate-400'
            }`}>
              {ga4Status.connected
                ? <><CheckCircle size={11} /> Connected</>
                : <><AlertCircle size={11} /> Not connected</>}
            </div>
          )}
        </div>

        {ga4Status && !ga4Status.connected && (
          <div className="space-y-3">
            <p className="text-slate-400 text-sm">
              Connect GA4 to pull real visitor counts, page views, and top pages directly into this dashboard.
            </p>
            <div className="bg-slate-800/60 rounded-lg p-3 space-y-1.5 text-xs text-slate-400">
              <p className="font-medium text-slate-300 mb-1">Setup steps:</p>
              <p>1. Add <code className="text-violet-300">GA4_REFRESH_TOKEN</code> secret after connecting below</p>
              <p>2. Your Property ID is already saved: <code className="text-emerald-300">{ga4Status.property_id || 'not set'}</code></p>
              <p>3. OAuth credentials: {ga4Status.client_id_set ? '✓ Client ID' : '✗ Client ID'} · {ga4Status.client_secret_set ? '✓ Secret' : '✗ Secret'}</p>
            </div>
            <button onClick={handleGA4Connect}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors">
              <LinkIcon size={13} /> Connect Google Analytics
            </button>
          </div>
        )}

        {ga4Status?.connected && (
          <div className="flex items-center gap-3 flex-wrap">
            <p className="text-slate-400 text-sm flex-1">Property <code className="text-emerald-300">{ga4Status.property_id}</code> · Data flows automatically into dashboard</p>
            <button onClick={handleGA4Test} disabled={ga4Testing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-slate-300 hover:text-white border border-slate-700 transition-all">
              {ga4Testing ? <Loader2 size={11} className="animate-spin" /> : <BarChart2 size={11} />} Test Connection
            </button>
          </div>
        )}

        {ga4TestResult && (
          <div className={`mt-3 p-3 rounded-lg text-xs ${ga4TestResult.ok ? 'bg-emerald-900/30 text-emerald-300 border border-emerald-800/40' : 'bg-red-900/30 text-red-300 border border-red-800/40'}`}>
            {ga4TestResult.ok
              ? `✓ GA4 working — ${ga4TestResult.stats?.total_visitors?.toLocaleString() || 0} total visitors tracked`
              : `✗ ${ga4TestResult.reason}`}
          </div>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat icon={Eye}       label="Total Visitors"  value={vs.total_visitors?.toLocaleString() || 0} color="#8b5cf6" />
        <Stat icon={BarChart2} label="Pages Tracked"   value={hasTopPages ? data.top_pages.length : 0}  color="#06b6d4" />
        <Stat icon={Globe}     label="Traffic Sources" value={hasReferrers ? data.top_referrers.length : 0} color="#10b981" />
      </div>

      <Card title="Top Visited Pages" empty={!hasTopPages}
        emptyMsg="No page visit data yet"
        action={
          <a href="/api/seo/sitemap.xml" target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs text-violet-400 hover:underline">
            <ExternalLink size={11} /> Sitemap
          </a>
        }>
        <div className="space-y-1.5">
          {(data.top_pages || []).map((pg, i) => (
            <div key={i} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-slate-800/50 transition-colors">
              <span className="text-slate-600 text-xs w-5 text-right">{i + 1}</span>
              <FileText size={11} className="text-violet-400 flex-shrink-0" />
              <span className="text-slate-300 text-xs flex-1 truncate font-mono">{pg.path}</span>
              <span className="text-slate-500 text-xs flex-shrink-0">{pg.views} views</span>
              <span className="text-slate-600 text-xs flex-shrink-0">{pg.unique_visitors} uniq</span>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Traffic Sources (Referrers)" empty={!hasReferrers}
        emptyMsg="No referrer data yet — appears when visitors arrive from external sites or search engines">
        <div className="space-y-2">
          {(data.top_referrers || []).map((ref, i) => (
            <div key={i} className="flex items-center gap-2">
              <Globe size={11} className="text-cyan-400 flex-shrink-0" />
              <span className="text-slate-300 text-sm flex-1 truncate">{ref.source || 'Direct'}</span>
              <span className="text-xs text-slate-500">{ref.count} visits</span>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
