import { Globe, TrendingUp, Eye, Users, DollarSign, Zap, Target,
  Activity, Clock, Smartphone, Monitor, Tablet, AlertTriangle, Server, Bot } from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Legend, PieChart, Pie, Cell,
} from 'recharts';
import { Card, Stat, TT, fmt, fmtInr } from './shared';

export default function OverviewTab({ data, vs, widgetErrors, load, liveVisitors, mrr, predicted, growth, arpu, ltv }) {
  const hasDailySignup = data?.daily_signups?.some(d => d.count > 0);
  const hasPlanUsage   = data?.plan_usage && Object.keys(data.plan_usage).length > 0;
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
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat icon={Server}     label="All Traffic (server)"   value={(vs.server_side?.total_unique ?? 0).toLocaleString()} color="#10b981"
          sub="Cloudflare-equivalent" />
        <Stat icon={Eye}        label="Engaged (JS-tracked)"   value={(vs.total_visitors ?? 0).toLocaleString()} color="#8b5cf6" />
        <Stat icon={Bot}        label="Bot/Crawler Hits"       value={(vs.bot_traffic?.total_hits ?? 0).toLocaleString()} color="#f59e0b"
          sub={`${vs.bot_traffic?.unique_total ?? 0} unique bots`} />
        <Stat icon={Users}      label="Active Users"           value={data?.active_users}  color="#06b6d4" />
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

      <Card title="Daily Traffic — Last 7 Days (All Sources)"
        empty={!hasDailyVis && !hasSsDailyVis} emptyMsg="No visitor data yet">
        {(() => {
          const ssDaily = vs.server_side?.daily_visitors || [];
          const jsDaily = vs.daily_visitors || [];
          const merged = ssDaily.map((ss) => {
            const js = jsDaily.find(j => j.date === ss.date) || {};
            return {
              date: ss.date,
              ss_visitors: ss.visitors,
              ss_hits: ss.page_views,
              js_visitors: js.visitors || 0,
              js_page_views: js.page_views || 0,
              bot_hits: ss.bot_hits || 0,
            };
          });
          const chartData = merged.length > 0 ? merged : jsDaily.map(j => ({
            date: j.date, ss_visitors: 0, ss_hits: 0,
            js_visitors: j.visitors, js_page_views: j.page_views, bot_hits: 0,
          }));
          return (
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={fmt} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                <Tooltip {...TT} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                <Area type="monotone" dataKey="ss_visitors"   name="All Traffic (server)" stroke="#10b981" fill="rgba(16,185,129,0.12)" strokeWidth={2} />
                <Area type="monotone" dataKey="js_visitors"   name="Engaged (JS)"        stroke="#8b5cf6" fill="rgba(139,92,246,0.10)" strokeWidth={2} />
                <Area type="monotone" dataKey="bot_hits"      name="Bot Hits"             stroke="#f59e0b" fill="rgba(245,158,11,0.08)" strokeWidth={1.5} strokeDasharray="4 2" />
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
