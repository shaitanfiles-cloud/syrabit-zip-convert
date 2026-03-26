import { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw, Eye, Globe, TrendingUp, Users, Search, BookOpen, Bot } from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, LineChart, Line, Legend,
} from 'recharts';
import { adminGetAnalytics } from '@/utils/api';

const TOOLTIP_STYLE = {
  contentStyle: {
    background: '#0f172a',
    border: '1px solid #1e293b',
    borderRadius: '8px',
    color: '#e2e8f0',
    fontSize: 12,
  },
};

function SectionCard({ title, children, empty, emptyMsg }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <h3 className="text-slate-400 text-sm font-medium mb-4">{title}</h3>
      {empty ? (
        <p className="text-slate-600 text-sm text-center py-6">{emptyMsg || 'No data yet'}</p>
      ) : children}
    </div>
  );
}

function MiniStat({ icon: Icon, label, value, color }) {
  return (
    <div className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-xl">
      <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${color}22` }}>
        <Icon size={14} style={{ color }} />
      </div>
      <div>
        <p className="text-white font-bold text-lg leading-none">{value?.toLocaleString() ?? 0}</p>
        <p className="text-slate-500 text-xs mt-0.5">{label}</p>
      </div>
    </div>
  );
}

export default function AdminAnalytics({ adminToken }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefresh, setLastRefresh] = useState(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const res = await adminGetAnalytics(adminToken);
      setData(res.data);
      setLastRefresh(new Date());
    } catch {}
    finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [adminToken]);

  useEffect(() => {
    load();
    const iv = setInterval(() => load(true), 60000);
    return () => clearInterval(iv);
  }, [load]);

  if (loading) return (
    <div className="flex justify-center p-10">
      <Loader2 size={24} className="animate-spin text-slate-400" />
    </div>
  );

  if (!data) return (
    <div className="p-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-400">Unable to load analytics data</p>
        <button onClick={load} className="mt-3 text-sm text-violet-400 hover:underline">Retry</button>
      </div>
    </div>
  );

  const vs = data?.visitor_stats || {};
  const hasDailySignups = data?.daily_signups?.some(d => d.count > 0);
  const hasPlanUsage = data?.plan_usage && Object.keys(data.plan_usage).length > 0;
  const hasLibraryEvents = data?.library && (
    data.library.top_searches?.length > 0 ||
    data.library.most_viewed_subjects?.length > 0 ||
    data.library.document_opens > 0
  );
  const hasDailyVisitors = vs.daily_visitors?.some(d => d.visitors > 0 || d.page_views > 0);

  const formatDate = (d) => d?.slice(5) ?? d;

  return (
    <div className="p-6 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-slate-200 font-semibold">Analytics</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500">
            {lastRefresh ? `Updated ${Math.floor((Date.now() - lastRefresh) / 1000)}s ago` : ''}
          </span>
          <button
            onClick={() => load(true)}
            disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white bg-slate-800 border border-slate-700 transition-all"
          >
            <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* ── Visitor Overview KPIs ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <MiniStat icon={Globe}      label="Total Visitors"     value={vs.total_visitors}   color="#06b6d4" />
        <MiniStat icon={TrendingUp} label="Visitors Today"     value={vs.visitors_today}   color="#f97316" />
        <MiniStat icon={Eye}        label="Page Views Today"   value={vs.page_views_today} color="#ec4899" />
        <MiniStat icon={Users}      label="Active Users"       value={data.active_users}   color="#10b981" />
      </div>

      {/* ── Visitor Chart ── */}
      <SectionCard
        title="Daily Visitors & Page Views — Last 7 Days"
        empty={!hasDailyVisitors}
        emptyMsg="No visitor data yet — pages are tracked as users visit the site"
      >
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={vs.daily_visitors || []} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={formatDate} />
            <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
            <Tooltip {...TOOLTIP_STYLE} />
            <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
            <Area
              type="monotone" dataKey="visitors" name="Unique Visitors"
              stroke="#06b6d4" fill="rgba(6,182,212,0.12)" strokeWidth={2}
            />
            <Area
              type="monotone" dataKey="page_views" name="Page Views"
              stroke="#8b5cf6" fill="rgba(139,92,246,0.10)" strokeWidth={2}
            />
          </AreaChart>
        </ResponsiveContainer>
      </SectionCard>

      {/* ── Daily Signups ── */}
      <SectionCard
        title="Daily Signups — Last 7 Days"
        empty={!hasDailySignups}
        emptyMsg="No signups in the last 7 days"
      >
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={data.daily_signups} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={formatDate} />
            <YAxis tick={{ fill: '#64748b', fontSize: 11 }} allowDecimals={false} />
            <Tooltip {...TOOLTIP_STYLE} />
            <Bar dataKey="count" name="Signups" fill="#7c3aed" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </SectionCard>

      {/* ── Plan Usage ── */}
      {hasPlanUsage && (
        <SectionCard title="Credits Used by Plan">
          <ResponsiveContainer width="100%" height={140}>
            <BarChart
              data={Object.entries(data.plan_usage).map(([plan, used]) => ({ plan, used }))}
              margin={{ top: 5, right: 10, bottom: 0, left: -10 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="plan" tick={{ fill: '#64748b', fontSize: 11 }} />
              <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
              <Tooltip {...TOOLTIP_STYLE} />
              <Bar dataKey="used" name="Credits Used" fill="#7c3aed" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </SectionCard>
      )}

      {/* ── Library Interactions ── */}
      {hasLibraryEvents ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {data.library.top_searches?.length > 0 && (
            <SectionCard title="Top Searches">
              <div className="space-y-2">
                {data.library.top_searches.slice(0, 8).map((item, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Search size={12} className="text-blue-400 flex-shrink-0" />
                    <span className="text-sm text-slate-300 flex-1 truncate">
                      {item.query || item._id || 'Unknown'}
                    </span>
                    <span className="text-xs text-slate-500 flex-shrink-0">{item.count}×</span>
                  </div>
                ))}
              </div>
            </SectionCard>
          )}

          {data.library.most_viewed_subjects?.length > 0 && (
            <SectionCard title="Most Viewed Subjects">
              <div className="space-y-2">
                {data.library.most_viewed_subjects.slice(0, 8).map((item, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <BookOpen size={12} className="text-amber-400 flex-shrink-0" />
                    <span className="text-sm text-slate-300 flex-1 truncate">{item.name}</span>
                    <span className="text-xs text-slate-500 flex-shrink-0">{item.view_count} views</span>
                  </div>
                ))}
              </div>
            </SectionCard>
          )}

          {data.library.most_ask_ai_subjects?.length > 0 && (
            <SectionCard title="Most Ask AI Subjects">
              <div className="space-y-2">
                {data.library.most_ask_ai_subjects.slice(0, 8).map((item, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Bot size={12} className="text-violet-400 flex-shrink-0" />
                    <span className="text-sm text-slate-300 flex-1 truncate">{item.name}</span>
                    <span className="text-xs text-slate-500 flex-shrink-0">{item.ask_count}×</span>
                  </div>
                ))}
              </div>
            </SectionCard>
          )}

          {data.library.events_by_type && Object.keys(data.library.events_by_type).length > 0 && (
            <SectionCard title="Events Breakdown">
              <div className="space-y-2">
                {Object.entries(data.library.events_by_type).map(([type, count]) => (
                  <div key={type} className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-violet-400 flex-shrink-0" />
                    <span className="text-sm text-slate-300 flex-1 capitalize">{type.replace(/_/g, ' ')}</span>
                    <span className="text-xs text-slate-500 flex-shrink-0">{count}</span>
                  </div>
                ))}
              </div>
            </SectionCard>
          )}
        </div>
      ) : (
        <SectionCard
          title="Library Interactions"
          empty
          emptyMsg="No user interactions yet. Analytics will appear as users browse subjects and search content."
        />
      )}
    </div>
  );
}
