import { useState, useEffect, useCallback } from 'react';
import {
  Users, MessageSquare, BookOpen, Zap, Loader2, Activity,
  ArrowRight, PenTool, Settings, Eye, TrendingUp, RefreshCw,
  UserPlus, Globe, Search, Bot, BarChart2,
} from 'lucide-react';
import { adminGetDashboard } from '@/utils/api';

function StatCard({ label, value, icon: Icon, color, subLabel, subValue, pulse }) {
  return (
    <div
      className="relative bg-slate-900 border border-slate-800 rounded-xl p-5 overflow-hidden"
      data-testid="dashboard-stat-card"
    >
      {pulse && (
        <span className="absolute top-3 right-3 flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: color }} />
          <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: color }} />
        </span>
      )}
      <div className="flex items-center justify-between mb-3">
        <p className="text-slate-500 text-sm">{label}</p>
        <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${color}22` }}>
          <Icon size={16} style={{ color }} />
        </div>
      </div>
      <p className="text-2xl font-bold text-white">{value?.toLocaleString() ?? 0}</p>
      {subLabel && (
        <p className="text-xs text-slate-500 mt-1">
          {subLabel}: <span className="text-slate-400 font-medium">{subValue?.toLocaleString() ?? 0}</span>
        </p>
      )}
    </div>
  );
}

function formatTimeAgo(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

const EVENT_ICONS = {
  signup:       { icon: UserPlus, color: '#10b981', bg: 'rgba(16,185,129,0.10)' },
  conversation: { icon: MessageSquare, color: '#8b5cf6', bg: 'rgba(139,92,246,0.10)' },
  search:       { icon: Search, color: '#60a5fa', bg: 'rgba(96,165,250,0.10)' },
  subject_view: { icon: BookOpen, color: '#f59e0b', bg: 'rgba(245,158,11,0.10)' },
  ai_click:     { icon: Bot, color: '#a78bfa', bg: 'rgba(167,139,250,0.10)' },
  page_view:    { icon: Eye, color: '#64748b', bg: 'rgba(100,116,139,0.10)' },
};

function ActivityItem({ event, idx }) {
  const cfg = EVENT_ICONS[event.type] || EVENT_ICONS.page_view;
  const Icon = cfg.icon;
  return (
    <div
      key={event.timestamp + idx}
      className="flex items-center gap-3 py-2.5 px-3 rounded-lg"
      style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}
    >
      <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: cfg.bg }}>
        <Icon size={13} style={{ color: cfg.color }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-white/80 truncate">{event.message}</p>
        {event.details && <p className="text-xs text-slate-500 truncate">{event.details}</p>}
      </div>
      <span className="text-xs text-slate-600 flex-shrink-0 ml-2">{formatTimeAgo(event.timestamp)}</span>
    </div>
  );
}

export default function AdminDashboard({ adminToken, onNavigate }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const res = await adminGetDashboard(adminToken);
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
    const interval = setInterval(() => load(true), 60000);
    return () => clearInterval(interval);
  }, [load]);

  if (loading) {
    return (
      <div className="flex justify-center p-10">
        <Loader2 size={24} className="animate-spin text-slate-400" />
      </div>
    );
  }

  const vs = data?.visitor_stats || {};
  const recentEvents = data?.recent_events || [];

  const quickActions = [
    { id: 'users',     label: 'View Users',     icon: Users,    color: 'from-violet-600 to-violet-500' },
    { id: 'content',   label: 'Content Editor', icon: PenTool,  color: 'from-blue-600 to-blue-500'    },
    { id: 'analytics', label: 'Analytics',      icon: BarChart2, color: 'from-emerald-600 to-emerald-500' },
    { id: 'settings',  label: 'Settings',       icon: Settings, color: 'from-slate-600 to-slate-500'  },
  ];

  return (
    <div className="p-6 space-y-6">

      {/* ── Refresh bar ── */}
      <div className="flex items-center justify-between">
        <h2 className="text-slate-200 font-semibold text-lg">Overview</h2>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <p className="text-xs text-slate-600">
              Updated {formatTimeAgo(lastRefresh.toISOString())}
            </p>
          )}
          <button
            onClick={() => load(true)}
            disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 transition-all disabled:opacity-50"
          >
            <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* ── Core stats row ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Users"     value={data?.total_users}          icon={Users}         color="#8b5cf6" />
        <StatCard label="Conversations"   value={data?.total_conversations}  icon={MessageSquare} color="#3b82f6" />
        <StatCard label="Messages Sent"   value={data?.total_messages}       icon={Zap}           color="#10b981" />
        <StatCard label="Subjects"        value={data?.total_subjects}       icon={BookOpen}      color="#f59e0b" />
      </div>

      {/* ── Visitor analytics row ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Visitors"
          value={vs.total_visitors}
          icon={Globe}
          color="#06b6d4"
          subLabel="Today"
          subValue={vs.visitors_today}
          pulse
        />
        <StatCard
          label="Visitors Today"
          value={vs.visitors_today}
          icon={TrendingUp}
          color="#f97316"
          pulse
        />
        <StatCard
          label="Page Views Today"
          value={vs.page_views_today}
          icon={Eye}
          color="#ec4899"
          pulse
        />
        <StatCard
          label="Active Users"
          value={data?.plan_distribution
            ? Object.values(data.plan_distribution).reduce((a, b) => a + b, 0)
            : 0}
          icon={Activity}
          color="#84cc16"
          subLabel="Paid"
          subValue={
            (data?.plan_distribution?.starter || 0) +
            (data?.plan_distribution?.pro     || 0)
          }
        />
      </div>

      {/* ── Plan Distribution ── */}
      {data?.plan_distribution && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="text-slate-400 text-sm font-medium mb-4">Plan Distribution</h3>
          <div className="grid grid-cols-3 gap-4">
            {[
              { key: 'free',    label: 'Free',    color: '#64748b' },
              { key: 'starter', label: 'Starter', color: '#8b5cf6' },
              { key: 'pro',     label: 'Pro',     color: '#f59e0b' },
            ].map(({ key, label, color }) => {
              const count = data.plan_distribution[key] || 0;
              const total = Object.values(data.plan_distribution).reduce((a, b) => a + b, 0) || 1;
              const pct = Math.round((count / total) * 100);
              return (
                <div key={key} className="text-center p-4 bg-slate-800/50 rounded-xl">
                  <p className="text-2xl font-bold" style={{ color }}>{count}</p>
                  <p className="text-slate-400 text-sm">{label}</p>
                  <div className="mt-2 h-1 rounded-full bg-slate-700 overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
                  </div>
                  <p className="text-xs text-slate-600 mt-1">{pct}%</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Quick Actions ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {quickActions.map((action) => (
          <button
            key={action.id}
            onClick={() => onNavigate?.(action.id)}
            className="flex items-center justify-between p-4 bg-slate-900 border border-slate-800 rounded-xl hover:border-slate-700 transition-all group"
            data-testid={`quick-action-${action.id}`}
          >
            <div className="flex items-center gap-3">
              <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${action.color} flex items-center justify-center`}>
                <action.icon size={15} className="text-white" />
              </div>
              <span className="text-sm font-medium text-white">{action.label}</span>
            </div>
            <ArrowRight size={14} className="text-slate-600 group-hover:text-slate-400 transition-colors" />
          </button>
        ))}
      </div>

      {/* ── Daily Visitor Trend (sparkline) ── */}
      {vs.daily_visitors?.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-slate-400 text-sm font-medium">Visitor Trend — Last 7 Days</h3>
            <span className="text-xs text-slate-600">Unique visitors per day</span>
          </div>
          <div className="flex items-end gap-2 h-20">
            {vs.daily_visitors.map((d, i) => {
              const maxV = Math.max(...vs.daily_visitors.map(x => x.visitors), 1);
              const pct = Math.max(4, (d.visitors / maxV) * 100);
              const isToday = i === vs.daily_visitors.length - 1;
              return (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
                  <div
                    className="w-full rounded-t transition-all"
                    style={{
                      height: `${pct}%`,
                      background: isToday
                        ? 'linear-gradient(to top, #7c3aed, #a78bfa)'
                        : 'rgba(139,92,246,0.30)',
                      minHeight: 4,
                    }}
                    title={`${d.date}: ${d.visitors} visitors, ${d.page_views} views`}
                  />
                  <span className="text-[10px] text-slate-600 whitespace-nowrap">
                    {d.date.slice(5)}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="flex gap-4 mt-3">
            {vs.daily_visitors.slice(-1).map(d => (
              <div key="today-summary" className="flex gap-4 text-xs text-slate-500">
                <span>Today: <span className="text-violet-400 font-medium">{d.visitors} visitors</span></span>
                <span>·</span>
                <span><span className="text-slate-300 font-medium">{d.page_views}</span> page views</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Recent Activity ── */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6" data-testid="recent-activity">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-violet-400" />
            <h3 className="text-slate-300 font-semibold">Recent Activity</h3>
            <span className="flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-2 w-2 rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
          </div>
          <button
            onClick={() => onNavigate?.('activitylog')}
            className="text-xs text-violet-400 hover:text-violet-300 transition-colors"
          >
            View all logs →
          </button>
        </div>

        {recentEvents.length === 0 ? (
          <div className="text-center py-8">
            <Activity size={28} className="text-slate-700 mx-auto mb-3" />
            <p className="text-slate-600 text-sm">No activity yet — events will appear here in real time</p>
          </div>
        ) : (
          <div className="space-y-1.5">
            {recentEvents.map((event, idx) => (
              <ActivityItem key={idx} event={event} idx={idx} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
