import React, { useEffect, useState, useCallback } from 'react';
import { Loader2, RefreshCw, Map, Sparkles, CheckCircle2, AlertTriangle, Send } from 'lucide-react';
import { adminSeoGoogleIndexingStats } from '@/utils/api';

const INDEXING_FIELDS = [
  { key: 'sent',               label: 'Submitted' },
  { key: 'status_2xx',         label: 'Accepted (2xx)' },
  { key: 'status_4xx',         label: 'Client errors (4xx)' },
  { key: 'status_5xx',         label: 'Server errors (5xx)' },
  { key: 'quota_blocks',       label: 'Quota blocks' },
  { key: 'sitemap_ping_sent',  label: 'Sitemap pings' },
];

function IndexingStatsCard({ adminToken }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!adminToken) return;
    setLoading(true);
    setError(null);
    try {
      const r = await adminSeoGoogleIndexingStats(adminToken);
      setData(r.data);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to load Google indexing stats');
    } finally {
      setLoading(false);
    }
  }, [adminToken]);

  useEffect(() => { load(); }, [load]);

  const today = data || null;
  const yesterday = data?.yesterday ?? null;
  const dailyLimit = today?.daily_limit ?? 200;
  const remaining = today?.quota_remaining;

  return (
    <div className="rounded-xl border p-5 space-y-4" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Send size={14} className="text-violet-500" />
            Google Indexing API — Daily Usage
          </p>
          <p className="text-xs mt-0.5" style={{ color: '#9ca3af' }}>
            Submissions to Google's Indexing API + sitemap pings, persisted across restarts. Cap is {dailyLimit} URLs/day.
          </p>
        </div>
        <button onClick={load} disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border disabled:opacity-40"
          style={{ borderColor: '#e5e7eb', color: '#4b5563', background: '#fff' }}>
          {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Refresh
        </button>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-2.5 rounded-lg" style={{ background: 'rgba(239,68,68,0.06)' }}>
          <AlertTriangle size={12} className="text-red-400 flex-shrink-0 mt-0.5" />
          <span className="text-xs" style={{ color: '#dc2626' }}>{error}</span>
        </div>
      )}

      {today?.enabled === false && !error && (
        <div className="p-3 rounded-lg text-xs" style={{ background: 'rgba(245,158,11,0.08)', color: '#92400e' }}>
          Google Indexing API integration is disabled
          {today?.error ? ` — ${today.error}` : ' (set GOOGLE_INDEXING_ENABLED=true and provide GOOGLE_INDEXING_SERVICE_ACCOUNT)'}.
        </div>
      )}

      {today && today.enabled !== false && (
        <>
          {typeof remaining === 'number' && (
            <div className="flex items-center justify-between text-xs" style={{ color: '#6b7280' }}>
              <span>
                <span className="font-semibold text-gray-900">{remaining}</span> of {dailyLimit} submissions remaining today
              </span>
              <span style={{ color: '#9ca3af' }}>UTC day {today.day}</span>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <DayColumn title="Today" tone="violet" day={today} />
            <DayColumn title="Yesterday" tone="gray" day={yesterday} />
          </div>
        </>
      )}
    </div>
  );
}

function DayColumn({ title, tone, day }) {
  const tones = {
    violet: { bg: 'rgba(124,58,237,0.06)', border: 'rgba(124,58,237,0.20)', label: '#7c3aed' },
    gray:   { bg: '#ffffff',                border: '#e5e7eb',               label: '#6b7280' },
  };
  const t = tones[tone] || tones.gray;
  const empty = !day;

  return (
    <div className="rounded-lg border p-3.5" style={{ background: t.bg, borderColor: t.border }}>
      <div className="flex items-center justify-between mb-2.5">
        <p className="text-[11px] font-bold uppercase tracking-wider" style={{ color: t.label }}>
          {title}
        </p>
        {!empty && day.day && (
          <p className="text-[10px] font-mono" style={{ color: '#9ca3af' }}>{day.day}</p>
        )}
      </div>
      {empty ? (
        <p className="text-xs italic py-3 text-center" style={{ color: '#9ca3af' }}>
          No prior-day data
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-x-3 gap-y-2">
          {INDEXING_FIELDS.map(f => (
            <div key={f.key} className="flex flex-col">
              <span className="text-base font-bold text-gray-900 leading-none">
                {Number(day[f.key] ?? 0).toLocaleString()}
              </span>
              <span className="text-[10px] mt-0.5" style={{ color: '#9ca3af' }}>{f.label}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function SitemapTab({
  sitemapData, sitemapValidating, handleSitemapValidate,
  refreshingMeta, handleRefreshMeta,
  sitemap, handleRegenerateSitemap,
  adminToken,
}) {
  return (
    <div className="space-y-5">
      <IndexingStatsCard adminToken={adminToken} />

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
