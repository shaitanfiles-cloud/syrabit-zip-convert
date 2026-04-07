import { Loader2, RefreshCw, Globe, Eye, Users, Bot, MessageSquare,
  Calendar, ArrowUpRight, ArrowDownRight, Cloud, BarChart3, Server } from 'lucide-react';
import {
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Legend, LineChart, Line, AreaChart, Area,
} from 'recharts';
import { Card, TT, fmt } from './shared';

export default function DailyStatsTab({ dailyDays, setDailyDays, dailyLoading, dailyData, loadDailyAnalytics }) {
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5 text-white/30 text-sm">
          <Calendar size={14} />
          <span>Date range:</span>
        </div>
        {[7, 14, 30, 60, 90].map(d => (
          <button key={d} onClick={() => setDailyDays(d)}
            className={`px-3.5 py-1.5 rounded-xl text-xs font-medium transition-all ${
              dailyDays === d ? 'text-white' : 'text-white/30 hover:text-white/60'
            }`}
            style={dailyDays === d
              ? { background: 'linear-gradient(135deg, #7c3aed, #6d28d9)', boxShadow: '0 2px 12px rgba(124,58,237,0.3)' }
              : { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }
            }>
            Last {d} days
          </button>
        ))}
        <button onClick={() => loadDailyAnalytics(dailyDays)} disabled={dailyLoading}
          className="ml-auto flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs text-white/40 hover:text-white transition-all"
          style={{ background: 'rgba(15,15,30,0.6)', border: '1px solid rgba(255,255,255,0.06)' }}>
          <RefreshCw size={12} className={dailyLoading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {dailyLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 size={24} className="animate-spin text-violet-400/60" />
        </div>
      ) : dailyData ? (() => {
        const s = dailyData.summary || {};
        const daily = dailyData.daily || [];
        const hasVisitors = daily.some(d => d.visitors > 0);
        const hasSignups = daily.some(d => d.signups > 0);
        const hasMessages = daily.some(d => d.messages > 0 || d.ai_interactions > 0);
        const hasBounce = daily.some(d => d.bounce_rate != null);
        const hasDuration = daily.some(d => d.avg_session_duration != null);

        const fmtChg = (pct) => {
          if (pct == null) return null;
          const up = pct >= 0;
          return (
            <div className={`flex items-center gap-0.5 text-xs font-semibold flex-shrink-0 ${up ? 'text-emerald-400' : 'text-red-400'}`}>
              {up ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
              {Math.abs(pct)}%
            </div>
          );
        };

        const summaryCards = [
          { icon: Globe,          label: 'Unique Visitors Today',    value: s.visitors?.today ?? 0,          chg: s.visitors?.change_pct,         color: '#06b6d4' },
          { icon: Eye,            label: 'Page Views Today',          value: s.page_views?.today ?? 0,        chg: s.page_views?.change_pct,       color: '#ec4899' },
          { icon: Users,          label: 'New Sign-ups Today',        value: s.signups?.today ?? 0,           chg: s.signups?.change_pct,          color: '#10b981' },
          { icon: MessageSquare,  label: 'Messages Today',            value: s.messages?.today ?? 0,          chg: s.messages?.change_pct,         color: '#8b5cf6' },
          { icon: Bot,            label: 'AI Interactions Today',     value: s.ai_interactions?.today ?? 0,   chg: s.ai_interactions?.change_pct,  color: '#f59e0b' },
        ];

        return (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
              {summaryCards.map(sc => (
                <div key={sc.label}
                  className="flex items-center gap-3 p-3.5 rounded-xl group transition-all duration-300 relative overflow-hidden"
                  style={{
                    background: 'rgba(15,15,30,0.5)',
                    border: '1px solid rgba(255,255,255,0.06)',
                  }}
                >
                  <div className="absolute inset-0 pointer-events-none transition-opacity duration-300 opacity-0 group-hover:opacity-100" style={{
                    background: `radial-gradient(ellipse at top right, ${sc.color}0a, transparent 60%)`,
                  }} />
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 relative" style={{ background: `${sc.color}18` }}>
                    <sc.icon size={15} style={{ color: sc.color }} />
                  </div>
                  <div className="flex-1 min-w-0 relative">
                    <p className="text-white font-bold text-lg leading-none">{sc.value.toLocaleString()}</p>
                    <p className="text-white/30 text-xs mt-0.5 leading-tight">{sc.label}</p>
                  </div>
                  {fmtChg(sc.chg)}
                </div>
              ))}
            </div>

            <Card title={`Daily Visitors & Page Views — Last ${dailyDays} Days (Best Estimate)`}
              empty={!hasVisitors} emptyMsg="No visitor data for this range yet">
              {(() => {
                const hasSources = daily.some(d => d.sources && Object.keys(d.sources).length > 1);
                const chartData = daily.map(d => {
                  const row = { date: d.date, visitors: d.visitors, page_views: d.page_views, visitor_source: d.visitor_source };
                  if (d.sources) {
                    if (d.sources.cloudflare) {
                      row.cf_visitors = d.sources.cloudflare.visitors;
                      row.cf_pv = d.sources.cloudflare.page_views;
                    }
                    if (d.sources.ga4) {
                      row.ga4_visitors = d.sources.ga4.visitors;
                      row.ga4_pv = d.sources.ga4.page_views;
                    }
                    if (d.sources.server) {
                      row.ss_visitors = d.sources.server.visitors;
                      row.ss_pv = d.sources.server.page_views;
                    }
                    if (d.sources['js-tracked']) {
                      row.js_visitors = d.sources['js-tracked'].visitors;
                      row.js_pv = d.sources['js-tracked'].page_views;
                    }
                  }
                  return row;
                });
                const hasCf = chartData.some(d => d.cf_visitors > 0);
                const hasGa4 = chartData.some(d => d.ga4_visitors > 0);
                const hasSs = chartData.some(d => d.ss_visitors > 0);
                const hasJs = chartData.some(d => d.js_visitors > 0);
                return (
                  <ResponsiveContainer width="100%" height={260}>
                    <AreaChart data={chartData} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                      <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 10 }} tickFormatter={fmt}
                        interval={Math.max(0, Math.floor(daily.length / 8) - 1)} />
                      <YAxis tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 11 }} />
                      <Tooltip {...TT} />
                      <Legend wrapperStyle={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }} />
                      {hasSources && hasCf && <Area type="monotone" dataKey="cf_visitors" name="CF Visitors" stroke="#f6821f" fill="rgba(246,130,31,0.08)" strokeWidth={1.5} />}
                      {hasSources && hasGa4 && <Area type="monotone" dataKey="ga4_visitors" name="GA4 Visitors" stroke="#4285f4" fill="rgba(66,133,244,0.08)" strokeWidth={1.5} />}
                      {hasSources && hasSs && <Area type="monotone" dataKey="ss_visitors" name="Server Visitors" stroke="#10b981" fill="rgba(16,185,129,0.08)" strokeWidth={1.5} />}
                      {hasSources && hasJs && <Area type="monotone" dataKey="js_visitors" name="JS Visitors" stroke="#8b5cf6" fill="rgba(139,92,246,0.08)" strokeWidth={1.5} />}
                      <Area type="monotone" dataKey="visitors" name="Best Visitors" stroke="#06b6d4" fill="rgba(6,182,212,0.15)" strokeWidth={2.5} />
                      <Area type="monotone" dataKey="page_views" name="Best Page Views" stroke="#ec4899" fill="rgba(236,72,153,0.10)" strokeWidth={2} strokeDasharray="4 2" />
                    </AreaChart>
                  </ResponsiveContainer>
                );
              })()}
            </Card>

            <Card title={`Daily Sign-ups — Last ${dailyDays} Days`}
              empty={!hasSignups} emptyMsg="No sign-ups recorded in this range">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={daily} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 10 }} tickFormatter={fmt}
                    interval={Math.max(0, Math.floor(daily.length / 8) - 1)} />
                  <YAxis tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 11 }} allowDecimals={false} />
                  <Tooltip {...TT} />
                  <Bar dataKey="signups" name="Sign-ups" fill="#10b981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>

            <Card title={`Messages & AI Interactions — Last ${dailyDays} Days`}
              empty={!hasMessages} emptyMsg="No message data for this range yet">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={daily} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 10 }} tickFormatter={fmt}
                    interval={Math.max(0, Math.floor(daily.length / 8) - 1)} />
                  <YAxis tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 11 }} allowDecimals={false} />
                  <Tooltip {...TT} />
                  <Legend wrapperStyle={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }} />
                  <Bar dataKey="messages"        name="Messages"        fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="ai_interactions" name="AI Interactions" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <Card title="Active Sessions per Day" empty={!daily.some(d => d.sessions > 0)} emptyMsg="Session data from GA4 not available">
                <ResponsiveContainer width="100%" height={160}>
                  <AreaChart data={daily} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                    <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 10 }} tickFormatter={fmt}
                      interval={Math.max(0, Math.floor(daily.length / 6) - 1)} />
                    <YAxis tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 11 }} />
                    <Tooltip {...TT} />
                    <Area type="monotone" dataKey="sessions" name="Sessions" stroke="#3b82f6" fill="rgba(59,130,246,0.12)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </Card>

              <Card title="Bounce Rate & Avg Session Duration" empty={!hasBounce && !hasDuration} emptyMsg="Bounce rate & duration require GA4">
                <ResponsiveContainer width="100%" height={160}>
                  <LineChart data={daily} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                    <XAxis dataKey="date" tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 10 }} tickFormatter={fmt}
                      interval={Math.max(0, Math.floor(daily.length / 6) - 1)} />
                    <YAxis yAxisId="br" tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 11 }} unit="%" />
                    <YAxis yAxisId="dur" orientation="right" tick={{ fill: 'rgba(255,255,255,0.25)', fontSize: 11 }} unit="s" />
                    <Tooltip {...TT} />
                    <Legend wrapperStyle={{ fontSize: 11, color: 'rgba(255,255,255,0.4)' }} />
                    {hasBounce  && <Line yAxisId="br"  type="monotone" dataKey="bounce_rate"         name="Bounce Rate (%)"    stroke="#ef4444" strokeWidth={2} dot={false} />}
                    {hasDuration && <Line yAxisId="dur" type="monotone" dataKey="avg_session_duration" name="Avg Duration (s)"   stroke="#06b6d4" strokeWidth={2} dot={false} />}
                  </LineChart>
                </ResponsiveContainer>
              </Card>
            </div>
          </>
        );
      })() : (
        <div className="rounded-2xl p-10 text-center" style={{
          background: 'rgba(15,15,30,0.6)',
          border: '1px solid rgba(255,255,255,0.06)',
        }}>
          <Calendar size={32} className="text-white/10 mx-auto mb-3" />
          <p className="text-white/25 text-sm">Select a date range above to load daily metrics</p>
        </div>
      )}
    </div>
  );
}
