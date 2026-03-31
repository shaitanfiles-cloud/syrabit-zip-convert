import { Search, Zap, Share2, MousePointerClick, Users, TrendingUp } from 'lucide-react';
import { Card, InsightBar, Stat } from './shared';

export default function HeatmapTab({ heatmap, aiInsight, widgetErrors, load, shareStats }) {
  if (!heatmap) {
    return (
      <Card title="Content Heatmap" error={!!widgetErrors.heatmap} onRetry={() => load(true)}
        empty={!widgetErrors.heatmap} emptyMsg="Heatmap data loading…" />
    );
  }

  const dailyMax = Math.max(
    ...(shareStats?.daily || []).map(d => Math.max(d.shares || 0, d.clicks || 0, d.unique_clicks || 0)),
    1
  );

  return (
    <div className="space-y-4">
      {aiInsight && (
        <div className="flex items-start gap-3 p-4 rounded-xl border"
          style={{ background: 'rgba(139,92,246,0.07)', borderColor: 'rgba(139,92,246,0.20)' }}>
          <Zap size={15} className="text-violet-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-semibold text-violet-300 mb-0.5">AI Content Insight</p>
            <p className="text-slate-300 text-sm leading-relaxed">{aiInsight}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Stat icon={Share2} label="Total Shares" value={shareStats?.total_shares ?? '—'} color="#25D366" />
        <Stat icon={MousePointerClick} label="Total Clicks" value={shareStats?.total_clicks ?? '—'} color="#f97316" />
        <Stat icon={Users} label="Unique Clicks" value={shareStats?.unique_clicks ?? '—'} color="#06b6d4" />
        <Stat icon={TrendingUp} label="Conversions" value={shareStats?.conversions ?? '—'} color="#10b981" />
        <Stat icon={Share2} label="Click Rate"
          value={shareStats?.total_shares > 0 ? `${Math.round((shareStats.total_clicks / shareStats.total_shares) * 100)}%` : '—'}
          color="#8b5cf6" />
      </div>

      {shareStats?.daily?.length > 0 && (
        <Card title="Shares & Clicks Per Day">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 px-2 pb-1.5 border-b border-slate-800 text-[10px] text-slate-500 uppercase tracking-wider">
              <span className="w-20">Date</span>
              <span className="flex-1">Activity</span>
              <span className="w-14 text-right">Shares</span>
              <span className="w-14 text-right">Clicks</span>
              <span className="w-14 text-right">Unique</span>
            </div>
            {shareStats.daily.slice(-14).map((d) => (
              <div key={d.date} className="flex items-center gap-2 px-2 py-1 hover:bg-slate-800/50 rounded-lg">
                <span className="text-slate-500 text-[11px] w-20 font-mono">{d.date.slice(5)}</span>
                <div className="flex-1 flex gap-0.5 h-3">
                  <div className="bg-emerald-500/60 rounded-sm" style={{ width: `${Math.max((d.shares / dailyMax) * 100, 2)}%` }} title={`${d.shares} shares`} />
                  <div className="bg-orange-500/60 rounded-sm" style={{ width: `${Math.max((d.clicks / dailyMax) * 100, 2)}%` }} title={`${d.clicks} clicks`} />
                  <div className="bg-cyan-500/60 rounded-sm" style={{ width: `${Math.max(((d.unique_clicks || 0) / dailyMax) * 100, 2)}%` }} title={`${d.unique_clicks || 0} unique`} />
                </div>
                <span className="text-emerald-400 text-xs w-14 text-right">{d.shares}</span>
                <span className="text-orange-400 text-xs w-14 text-right">{d.clicks}</span>
                <span className="text-cyan-400 text-xs w-14 text-right">{d.unique_clicks || 0}</span>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-4 mt-3 px-2 text-[10px] text-slate-500">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-emerald-500/60" />Shares</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-orange-500/60" />Total Clicks</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-cyan-500/60" />Unique Clicks</span>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Top Subjects by Activity"
          empty={!heatmap.top_subjects?.length} emptyMsg="No subject activity yet">
          {heatmap.top_subjects?.length > 0 && (
            <div className="space-y-2">
              {heatmap.top_subjects.map((s, i) => (
                <InsightBar key={i} label={s.name} value={s.views}
                  max={heatmap.top_subjects[0]?.views || 1} />
              ))}
            </div>
          )}
        </Card>
        <Card title="Top Search Queries"
          empty={!heatmap.top_searches?.length} emptyMsg="No search data yet">
          {heatmap.top_searches?.length > 0 && (
            <div className="space-y-2">
              {heatmap.top_searches.map((s, i) => (
                <div key={i} className="flex items-center gap-2 p-1.5 hover:bg-slate-800/50 rounded-lg">
                  <Search size={12} className="text-blue-400 flex-shrink-0" />
                  <span className="text-slate-300 text-sm flex-1 truncate">{s.query}</span>
                  <span className="text-slate-500 text-xs flex-shrink-0">{s.count}×</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {shareStats?.subjects?.length > 0 && (
        <Card title="Referral Shares by Subject">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 px-2 pb-1.5 border-b border-slate-800 text-[10px] text-slate-500 uppercase tracking-wider">
              <span className="flex-1">Subject</span>
              <span className="w-16 text-right">Shares</span>
              <span className="w-16 text-right">Clicks</span>
              <span className="w-16 text-right">Unique</span>
              <span className="w-16 text-right">CTR</span>
            </div>
            {shareStats.subjects.map((s, i) => (
              <div key={i} className="flex items-center gap-2 px-2 py-1.5 hover:bg-slate-800/50 rounded-lg">
                <Share2 size={11} className="text-emerald-400 flex-shrink-0" />
                <span className="text-slate-300 text-sm flex-1 truncate">{s.name}</span>
                <span className="text-slate-400 text-xs w-16 text-right">{s.shares}</span>
                <span className="text-orange-400 text-xs w-16 text-right">{s.clicks}</span>
                <span className="text-cyan-400 text-xs w-16 text-right">{s.unique_clicks || 0}</span>
                <span className="text-violet-400 text-xs w-16 text-right">
                  {s.shares > 0 ? `${Math.round((s.clicks / s.shares) * 100)}%` : '0%'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
