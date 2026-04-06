import { Globe, TrendingUp, Eye, Users, DollarSign, Zap, Target,
  Activity, Clock, Smartphone, Monitor, Tablet, AlertTriangle, Server, Bot,
  Cloud, BarChart3, Download, Loader2, CheckCircle } from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Legend, PieChart, Pie, Cell,
} from 'recharts';
import { Card, Stat, TT, fmt, fmtInr } from './shared';

const SOURCE_COLORS = {
  cloudflare: '#f6821f',
  ga4: '#4285f4',
  server: '#10b981',
  'js-tracked': '#8b5cf6',
};

const SOURCE_LABELS = {
  cloudflare: 'Cloudflare',
  ga4: 'GA4',
  server: 'Server-side',
  'js-tracked': 'JS-tracked',
};

function SourceBadge({ source }) {
  if (!source || source === 'none') return null;
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wide"
      style={{ background: `${SOURCE_COLORS[source] || '#64748b'}22`, color: SOURCE_COLORS[source] || '#64748b' }}>
      {SOURCE_LABELS[source] || source}
    </span>
  );
}

export default function OverviewTab({ data, vs, widgetErrors, load, liveVisitors, mrr, predicted, growth, arpu, ltv,
  syncing, onSyncHistorical, cfConnected, ga4Connected }) {
  const hasDailySignup = data?.daily_signups?.some(d => d.count > 0);
  const hasPlanUsage   = data?.plan_usage && Object.keys(data.plan_usage).length > 0;
  const best = vs.best_estimate || {};
  const mergedDaily = vs.merged_daily || [];
  const hasMergedDaily = mergedDaily.some(d => d.visitors > 0 || d.page_views > 0);
  const hasDailyVis    = vs.daily_visitors?.some(d => d.visitors > 0 || d.page_views > 0);
  const hasSsDailyVis  = vs.server_side?.daily_visitors?.some(d => d.visitors > 0 || d.page_views > 0);

  return (
    <>
      {widgetErrors.overview && (
        <div className="flex items-center gap-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
          <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />
          <p className="text-xs text-amber-300 flex-1">Overview data failed to load — some metrics unavailable.</p>
          <button onClick={() => load(true)} className="text-xs text-amber-300 hover:text-white px-2 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 transition-colors">Retry</button>
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap p-3 bg-slate-900/50 border border-slate-800 rounded-xl">
        <span className="text-slate-500 text-xs font-medium">Data Sources:</span>
        <div className="flex items-center gap-1.5">
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${cfConnected ? 'bg-orange-500/15 text-orange-400' : 'bg-slate-800 text-slate-600'}`}>
            <Cloud size={10} /> Cloudflare {cfConnected ? <CheckCircle size={9} /> : '(not connected)'}
          </span>
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${ga4Connected ? 'bg-blue-500/15 text-blue-400' : 'bg-slate-800 text-slate-600'}`}>
            <BarChart3 size={10} /> GA4 {ga4Connected ? <CheckCircle size={9} /> : '(not connected)'}
          </span>
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/15 text-emerald-400">
            <Server size={10} /> Server <CheckCircle size={9} />
          </span>
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-violet-500/15 text-violet-400">
            <Eye size={10} /> JS-tracked <CheckCircle size={9} />
          </span>
        </div>
        <button onClick={() => onSyncHistorical(90)} disabled={syncing}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white bg-slate-800 border border-slate-700 transition-all disabled:opacity-50">
          {syncing ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
          {syncing ? 'Syncing...' : 'Sync Historical Data'}
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="flex items-center gap-3 p-3 bg-gradient-to-br from-slate-900 to-slate-800 border border-slate-700 rounded-xl">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(124,58,237,0.15)' }}>
            <TrendingUp size={15} style={{ color: '#7c3aed' }} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-white font-bold text-xl leading-none">{(best.total_visitors ?? 0).toLocaleString()}</p>
            <p className="text-slate-500 text-xs mt-0.5">Best Estimate (7d)</p>
            <SourceBadge source={best.total_visitors_source} />
          </div>
        </div>
        <div className="flex items-center gap-3 p-3 bg-gradient-to-br from-slate-900 to-slate-800 border border-slate-700 rounded-xl">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(6,182,212,0.15)' }}>
            <Users size={15} style={{ color: '#06b6d4' }} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-white font-bold text-xl leading-none">{(best.visitors_today ?? 0).toLocaleString()}</p>
            <p className="text-slate-500 text-xs mt-0.5">Best Estimate (Today)</p>
            <SourceBadge source={best.visitors_today_source} />
          </div>
        </div>
        <div className="flex items-center gap-3 p-3 bg-gradient-to-br from-slate-900 to-slate-800 border border-slate-700 rounded-xl">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(236,72,153,0.15)' }}>
            <Eye size={15} style={{ color: '#ec4899' }} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-white font-bold text-xl leading-none">{(best.page_views_today ?? 0).toLocaleString()}</p>
            <p className="text-slate-500 text-xs mt-0.5">Page Views Today</p>
            <SourceBadge source={best.page_views_today_source} />
          </div>
        </div>
        <Stat icon={Users} label="Active Users" value={data?.active_users} color="#06b6d4" />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        {vs.cloudflare && (
          <Stat icon={Cloud} label="Cloudflare Visitors" value={(vs.cloudflare.total_visitors ?? 0).toLocaleString()} color="#f6821f"
            sub={`${(vs.cloudflare.total_requests ?? 0).toLocaleString()} requests`} />
        )}
        {vs.ga4 && (
          <Stat icon={BarChart3} label="GA4 Visitors" value={(vs.ga4.total_visitors ?? 0).toLocaleString()} color="#4285f4" />
        )}
        <Stat icon={Server} label="Server-side Unique" value={(vs.server_side?.total_unique ?? 0).toLocaleString()} color="#10b981"
          sub={`${(vs.server_side?.total_hits ?? 0).toLocaleString()} hits`} />
        <Stat icon={Eye} label="JS-tracked" value={(vs.total_visitors ?? 0).toLocaleString()} color="#8b5cf6" />
        <Stat icon={Bot} label="Bot/Crawler Hits" value={(vs.bot_traffic?.total_hits ?? 0).toLocaleString()} color="#f59e0b"
          sub={`${vs.bot_traffic?.unique_total ?? 0} unique bots`} />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="flex items-center gap-3 p-3 bg-slate-900 border border-slate-800 rounded-xl relative overflow-hidden">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(16,185,129,0.15)' }}>
            <Activity size={15} style={{ color: '#10b981' }} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-white font-bold text-lg leading-none">{liveVisitors !== null ? liveVisitors : '—'}</p>
            <p className="text-slate-500 text-xs mt-0.5">Live Now</p>
          </div>
          {liveVisitors > 0 && (
            <span className="absolute top-2 right-2 flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
          )}
        </div>
        <Stat icon={Users}      label="New Visitors Today"      value={vs.new_visitors ?? '—'}       color="#8b5cf6" />
        <Stat icon={TrendingUp} label="Returning Today"          value={vs.returning_visitors ?? '—'} color="#06b6d4" />
        <div className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-xl">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(245,158,11,0.15)' }}>
            <Clock size={15} style={{ color: '#f59e0b' }} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-white font-bold text-lg leading-none">
              {vs.avg_session_duration != null ? `${Math.floor(vs.avg_session_duration / 60)}m ${vs.avg_session_duration % 60}s` : '—'}
            </p>
            <p className="text-slate-500 text-xs mt-0.5">Avg Session</p>
            {vs.bounce_rate != null && <p className="text-slate-600 text-[10px] mt-0.5">Bounce: {vs.bounce_rate}%</p>}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card title="Device Breakdown">
          {(() => {
            const devData = vs.device_breakdown || {};
            const entries = Object.entries(devData);
            const hasData = entries.some(([, v]) => v.count > 0);
            if (!hasData) return <p className="text-slate-600 text-sm text-center py-6">No device data yet</p>;
            const DEVICE_COLORS = { mobile: '#8b5cf6', desktop: '#06b6d4', tablet: '#f59e0b' };
            const DEVICE_ICONS = { mobile: Smartphone, desktop: Monitor, tablet: Tablet };
            const pieData = entries.map(([k, v]) => ({ name: k, value: v.count, pct: v.pct }));
            return (
              <div className="flex flex-col gap-3">
                <ResponsiveContainer width="100%" height={140}>
                  <PieChart>
                    <Pie data={pieData} cx="50%" cy="50%" innerRadius={40} outerRadius={65} paddingAngle={3} dataKey="value">
                      {pieData.map((entry) => (
                        <Cell key={entry.name} fill={DEVICE_COLORS[entry.name] || '#64748b'} />
                      ))}
                    </Pie>
                    <Tooltip {...TT} formatter={(v, name) => [`${v} views`, name]} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="space-y-1">
                  {pieData.map(entry => {
                    const Icon = DEVICE_ICONS[entry.name] || Monitor;
                    return (
                      <div key={entry.name} className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: DEVICE_COLORS[entry.name] || '#64748b' }} />
                        <Icon size={11} style={{ color: DEVICE_COLORS[entry.name] || '#64748b' }} />
                        <span className="text-slate-300 text-xs capitalize flex-1">{entry.name}</span>
                        <span className="text-slate-500 text-xs">{entry.pct}%</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })()}
        </Card>

        <Card title="Top Countries">
          {(() => {
            const countries = vs.top_countries || [];
            if (!countries.length) return <p className="text-slate-600 text-sm text-center py-6">No country data yet</p>;
            const maxCount = countries[0]?.count || 1;
            return (
              <div className="space-y-2.5">
                {countries.map((c, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-slate-400 text-xs w-6 text-right flex-shrink-0">{i + 1}</span>
                    <Globe size={11} className="text-cyan-400 flex-shrink-0" />
                    <span className="text-slate-300 text-sm flex-1 truncate font-medium">{c.country}</span>
                    <div className="w-16 h-1.5 rounded-full bg-slate-800 overflow-hidden flex-shrink-0">
                      <div className="h-full rounded-full bg-cyan-500" style={{ width: `${Math.round(c.count / maxCount * 100)}%` }} />
                    </div>
                    <span className="text-slate-500 text-xs w-8 text-right flex-shrink-0">{c.count}</span>
                  </div>
                ))}
              </div>
            );
          })()}
        </Card>

        <Card title="New vs. Returning">
          {(() => {
            const nv = vs.new_visitors ?? 0;
            const rv = vs.returning_visitors ?? 0;
            const total = nv + rv;
            if (total === 0) return <p className="text-slate-600 text-sm text-center py-6">No visitor data today yet</p>;
            const pieData = [
              { name: 'New', value: nv },
              { name: 'Returning', value: rv },
            ];
            return (
              <div className="flex flex-col gap-3">
                <ResponsiveContainer width="100%" height={140}>
                  <PieChart>
                    <Pie data={pieData} cx="50%" cy="50%" innerRadius={40} outerRadius={65} paddingAngle={3} dataKey="value">
                      <Cell fill="#7c3aed" />
                      <Cell fill="#06b6d4" />
                    </Pie>
                    <Tooltip {...TT} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex justify-around">
                  <div className="text-center">
                    <p className="text-violet-400 font-bold text-lg">{nv}</p>
                    <p className="text-slate-500 text-xs">New</p>
                  </div>
                  <div className="text-center">
                    <p className="text-cyan-400 font-bold text-lg">{rv}</p>
                    <p className="text-slate-500 text-xs">Returning</p>
                  </div>
                </div>
              </div>
            );
          })()}
        </Card>
      </div>

      {mrr > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat icon={DollarSign} label="MRR (30d)"       value={fmtInr(mrr)}       color="#10b981" trend={growth} />
          <Stat icon={TrendingUp} label="Predicted MRR"   value={fmtInr(predicted)} color="#7c3aed" />
          <Stat icon={Target}     label="ARPU"            value={fmtInr(arpu)}       color="#f59e0b" />
          <Stat icon={Zap}        label="LTV (12-mo)"     value={fmtInr(ltv)}        color="#06b6d4" />
        </div>
      )}

      <Card title="Daily Visitors — Last 7 Days (All Sources)"
        empty={!hasMergedDaily && !hasDailyVis && !hasSsDailyVis} emptyMsg="No visitor data yet">
        {(() => {
          if (hasMergedDaily) {
            const chartData = mergedDaily.map(d => {
              const row = { date: d.date, best_visitors: d.visitors };
              const sources = d.sources || {};
              if (sources.cloudflare) row.cf_visitors = sources.cloudflare.visitors;
              if (sources.ga4) row.ga4_visitors = sources.ga4.visitors;
              if (sources.server) row.ss_visitors = sources.server.visitors;
              if (sources['js-tracked']) row.js_visitors = sources['js-tracked'].visitors;
              return row;
            });
            const hasCf = chartData.some(d => d.cf_visitors > 0);
            const hasGa4 = chartData.some(d => d.ga4_visitors > 0);
            const hasSs = chartData.some(d => d.ss_visitors > 0);
            const hasJs = chartData.some(d => d.js_visitors > 0);
            return (
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={fmt} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                  <Tooltip {...TT} />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                  {hasCf && <Area type="monotone" dataKey="cf_visitors" name="Cloudflare" stroke="#f6821f" fill="rgba(246,130,31,0.10)" strokeWidth={2} />}
                  {hasGa4 && <Area type="monotone" dataKey="ga4_visitors" name="GA4" stroke="#4285f4" fill="rgba(66,133,244,0.10)" strokeWidth={2} />}
                  {hasSs && <Area type="monotone" dataKey="ss_visitors" name="Server-side" stroke="#10b981" fill="rgba(16,185,129,0.10)" strokeWidth={2} />}
                  {hasJs && <Area type="monotone" dataKey="js_visitors" name="JS-tracked" stroke="#8b5cf6" fill="rgba(139,92,246,0.08)" strokeWidth={1.5} />}
                </AreaChart>
              </ResponsiveContainer>
            );
          }
          const ssDaily = vs.server_side?.daily_visitors || [];
          const jsDaily = vs.daily_visitors || [];
          const merged = ssDaily.map((ss) => {
            const js = jsDaily.find(j => j.date === ss.date) || {};
            return {
              date: ss.date, ss_visitors: ss.visitors, js_visitors: js.visitors || 0,
            };
          });
          const chartData = merged.length > 0 ? merged : jsDaily.map(j => ({
            date: j.date, ss_visitors: 0, js_visitors: j.visitors,
          }));
          return (
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={fmt} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                <Tooltip {...TT} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                <Area type="monotone" dataKey="ss_visitors" name="Server-side" stroke="#10b981" fill="rgba(16,185,129,0.12)" strokeWidth={2} />
                <Area type="monotone" dataKey="js_visitors" name="JS-tracked" stroke="#8b5cf6" fill="rgba(139,92,246,0.10)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          );
        })()}
      </Card>

      <Card title="Daily Page Views — Last 7 Days (All Sources)"
        empty={!hasMergedDaily && !hasDailyVis && !hasSsDailyVis} emptyMsg="No page view data yet">
        {(() => {
          if (hasMergedDaily) {
            const chartData = mergedDaily.map(d => {
              const row = { date: d.date, best_pv: d.page_views };
              const sources = d.sources || {};
              if (sources.cloudflare) row.cf_pv = sources.cloudflare.page_views;
              if (sources.ga4) row.ga4_pv = sources.ga4.page_views;
              if (sources.server) row.ss_pv = sources.server.page_views;
              if (sources['js-tracked']) row.js_pv = sources['js-tracked'].page_views;
              return row;
            });
            const hasCf = chartData.some(d => d.cf_pv > 0);
            const hasGa4 = chartData.some(d => d.ga4_pv > 0);
            const hasSs = chartData.some(d => d.ss_pv > 0);
            const hasJs = chartData.some(d => d.js_pv > 0);
            return (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={fmt} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                  <Tooltip {...TT} />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                  {hasCf && <Area type="monotone" dataKey="cf_pv" name="Cloudflare PV" stroke="#f6821f" fill="rgba(246,130,31,0.10)" strokeWidth={2} />}
                  {hasGa4 && <Area type="monotone" dataKey="ga4_pv" name="GA4 PV" stroke="#4285f4" fill="rgba(66,133,244,0.10)" strokeWidth={2} />}
                  {hasSs && <Area type="monotone" dataKey="ss_pv" name="Server PV" stroke="#10b981" fill="rgba(16,185,129,0.10)" strokeWidth={2} />}
                  {hasJs && <Area type="monotone" dataKey="js_pv" name="JS-tracked PV" stroke="#8b5cf6" fill="rgba(139,92,246,0.08)" strokeWidth={1.5} />}
                </AreaChart>
              </ResponsiveContainer>
            );
          }
          const ssDaily = vs.server_side?.daily_visitors || [];
          const jsDaily = vs.daily_visitors || [];
          const merged = ssDaily.map((ss) => {
            const js = jsDaily.find(j => j.date === ss.date) || {};
            return { date: ss.date, ss_pv: ss.page_views, js_pv: js.page_views || 0 };
          });
          const chartData = merged.length > 0 ? merged : jsDaily.map(j => ({
            date: j.date, ss_pv: 0, js_pv: j.page_views,
          }));
          return (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={fmt} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                <Tooltip {...TT} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                <Area type="monotone" dataKey="ss_pv" name="Server PV" stroke="#10b981" fill="rgba(16,185,129,0.12)" strokeWidth={2} />
                <Area type="monotone" dataKey="js_pv" name="JS-tracked PV" stroke="#8b5cf6" fill="rgba(139,92,246,0.10)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          );
        })()}
      </Card>

      <Card title="Daily Signups — Last 7 Days" empty={!hasDailySignup} emptyMsg="No signups in the last 7 days">
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={data.daily_signups} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={fmt} />
            <YAxis tick={{ fill: '#64748b', fontSize: 11 }} allowDecimals={false} />
            <Tooltip {...TT} />
            <Bar dataKey="count" name="Signups" fill="#7c3aed" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {hasPlanUsage && (
        <Card title="Credits Used by Plan">
          <ResponsiveContainer width="100%" height={140}>
            <BarChart data={Object.entries(data.plan_usage).map(([plan, used]) => ({ plan, used }))}
              margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="plan" tick={{ fill: '#64748b', fontSize: 11 }} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
              <Tooltip {...TT} />
              <Bar dataKey="used" name="Credits Used" fill="#7c3aed" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      )}
    </>
  );
}
