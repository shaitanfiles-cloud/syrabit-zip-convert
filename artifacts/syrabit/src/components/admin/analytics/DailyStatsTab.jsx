import { Loader2, RefreshCw, Globe, Eye, Users, Bot, MessageSquare,
  Calendar, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import {
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Legend, LineChart, Line, AreaChart, Area,
} from 'recharts';
import { Card, TT, fmt } from './shared';

export default function DailyStatsTab({ dailyDays, setDailyDays, dailyLoading, dailyData, loadDailyAnalytics }) {
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5 text-slate-400 text-sm">
          <Calendar size={14} />
          <span>Date range:</span>
        </div>
        {[7, 14, 30, 60, 90].map(d => (
          <button key={d} onClick={() => setDailyDays(d)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              dailyDays === d ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-700'
            }`}>
            Last {d} days
          </button>
        ))}
        <button onClick={() => loadDailyAnalytics(dailyDays)} disabled={dailyLoading}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white bg-slate-800 border border-slate-700 transition-all">
          <RefreshCw size={12} className={dailyLoading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {dailyLoading ? (
        <div className="flex justify-center p-10">
          <Loader2 size={24} className="animate-spin text-slate-400" />
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
                <div key={sc.label} className="flex items-center gap-3 p-3 bg-slate-900 border border-slate-800 rounded-xl">
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: `${sc.color}22` }}>
                    <sc.icon size={15} style={{ color: sc.color }} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-white font-bold text-lg leading-none">{sc.value.toLocaleString()}</p>
                    <p className="text-slate-500 text-xs mt-0.5 leading-tight">{sc.label}</p>
                  </div>
                  {fmtChg(sc.chg)}
                </div>
              ))}
            </div>

            <Card title={`Daily Visitors & Page Views — Last ${dailyDays} Days`}
              empty={!hasVisitors} emptyMsg="No visitor data for this range yet">
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={daily} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={fmt}
                    interval={Math.max(0, Math.floor(daily.length / 8) - 1)} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                  <Tooltip {...TT} />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                  <Line type="monotone" dataKey="visitors"   name="Unique Visitors" stroke="#06b6d4" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                  <Line type="monotone" dataKey="page_views" name="Page Views"      stroke="#ec4899" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            </Card>

            <Card title={`Daily Sign-ups — Last ${dailyDays} Days`}
              empty={!hasSignups} emptyMsg="No sign-ups recorded in this range">
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={daily} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={fmt}
                    interval={Math.max(0, Math.floor(daily.length / 8) - 1)} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} allowDecimals={false} />
                  <Tooltip {...TT} />
                  <Bar dataKey="signups" name="Sign-ups" fill="#10b981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>

            <Card title={`Messages & AI Interactions — Last ${dailyDays} Days`}
              empty={!hasMessages} emptyMsg="No message data for this range yet">
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={daily} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={fmt}
                    interval={Math.max(0, Math.floor(daily.length / 8) - 1)} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} allowDecimals={false} />
                  <Tooltip {...TT} />
                  <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                  <Bar dataKey="messages"        name="Messages"        fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="ai_interactions" name="AI Interactions" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <Card title="Active Sessions per Day" empty={!daily.some(d => d.sessions > 0)} emptyMsg="Session data from GA4 not available">
                <ResponsiveContainer width="100%" height={160}>
                  <AreaChart data={daily} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={fmt}
                      interval={Math.max(0, Math.floor(daily.length / 6) - 1)} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                    <Tooltip {...TT} />
                    <Area type="monotone" dataKey="sessions" name="Sessions" stroke="#3b82f6" fill="rgba(59,130,246,0.12)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </Card>

              <Card title="Bounce Rate & Avg Session Duration" empty={!hasBounce && !hasDuration} emptyMsg="Bounce rate & duration require GA4">
                <ResponsiveContainer width="100%" height={160}>
                  <LineChart data={daily} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} tickFormatter={fmt}
                      interval={Math.max(0, Math.floor(daily.length / 6) - 1)} />
                    <YAxis yAxisId="br" tick={{ fill: '#64748b', fontSize: 11 }} unit="%" />
                    <YAxis yAxisId="dur" orientation="right" tick={{ fill: '#64748b', fontSize: 11 }} unit="s" />
                    <Tooltip {...TT} />
                    <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                    {hasBounce  && <Line yAxisId="br"  type="monotone" dataKey="bounce_rate"         name="Bounce Rate (%)"    stroke="#ef4444" strokeWidth={2} dot={false} />}
                    {hasDuration && <Line yAxisId="dur" type="monotone" dataKey="avg_session_duration" name="Avg Duration (s)"   stroke="#06b6d4" strokeWidth={2} dot={false} />}
                  </LineChart>
                </ResponsiveContainer>
              </Card>
            </div>
          </>
        );
      })() : (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-10 text-center">
          <Calendar size={32} className="text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500 text-sm">Select a date range above to load daily metrics</p>
        </div>
      )}
    </div>
  );
}
