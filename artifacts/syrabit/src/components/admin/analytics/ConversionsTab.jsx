import { Loader2, RefreshCw, Eye, TrendingUp, DollarSign, Target } from 'lucide-react';
import { Card, Stat } from './shared';

export default function ConversionsTab({ pageConvData, pageConvLoading, loadPageConversions }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-gray-700 font-semibold text-sm">Page-Level Conversion Tracker</h3>
          <p className="text-gray-300 text-xs mt-0.5">Which pages drive the most trial → paid conversions</p>
        </div>
        <button onClick={loadPageConversions} disabled={pageConvLoading}
          className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs text-gray-400 hover:text-gray-900 transition-all"
          style={{ background: '#ffffff', border: '1px solid #e5e7eb' }}>
          <RefreshCw size={12} className={pageConvLoading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {pageConvLoading ? (
        <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-violet-400/60" /></div>
      ) : pageConvData ? (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              { icon: Eye,        label: 'Funnel Hits',  value: (pageConvData.total_views || 0).toLocaleString(), color: '#06b6d4' },
              { icon: Target,     label: 'Conversion Events', value: pageConvData.total_conversions || 0, color: '#8b5cf6' },
              { icon: TrendingUp, label: 'Top CVR',           value: `${pageConvData.top_cvr || 0}%`, color: '#10b981' },
              { icon: DollarSign, label: 'Revenue Attributed',value: `₹${(pageConvData.revenue_attributed || 0).toLocaleString()}`, color: '#f59e0b' },
            ].map(s => <Stat key={s.label} icon={s.icon} label={s.label} value={s.value} color={s.color} />)}
          </div>

          {pageConvData.pages?.length > 0 && (
            <Card title="Top Converting Pages">
              <div className="space-y-2">
                {pageConvData.pages.slice(0, 20).map((p, i) => (
                  <div key={i} className="flex items-center gap-3 p-3 rounded-xl" style={{
                    background: i % 2 === 0 ? '#f9fafb' : 'transparent',
                  }}>
                    <span className="text-gray-200 text-xs w-5 text-right flex-shrink-0">{i + 1}</span>
                    <span className="text-gray-500 text-sm flex-1 truncate">{p.slug || p.url || '—'}</span>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <span className="text-gray-400 text-xs">{(p.views || 0).toLocaleString()} views</span>
                      <span className="text-xs font-mono px-2 py-0.5 rounded-lg" style={{
                        background: (p.cvr || 0) > 3 ? 'rgba(16,185,129,0.12)' : (p.cvr || 0) > 1 ? 'rgba(245,158,11,0.12)' : '#f9fafb',
                        color: (p.cvr || 0) > 3 ? '#34d399' : (p.cvr || 0) > 1 ? '#fbbf24' : '#94a3b8',
                      }}>
                        {p.cvr || 0}% CVR
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {pageConvData.pages?.length === 0 && (
            <div className="rounded-2xl p-10 text-center" style={{
              background: '#ffffff',
              border: '1px solid #e5e7eb',
            }}>
              <Target size={32} className="text-gray-200 mx-auto mb-3" />
              <p className="text-gray-300 text-sm">No page conversion data yet — this populates as users convert from content pages</p>
            </div>
          )}
        </>
      ) : (
        <div className="rounded-2xl p-10 text-center" style={{
          background: '#ffffff',
          border: '1px solid #e5e7eb',
        }}>
          <p className="text-gray-300 text-sm">Click Refresh to load page conversion data</p>
        </div>
      )}
    </div>
  );
}
