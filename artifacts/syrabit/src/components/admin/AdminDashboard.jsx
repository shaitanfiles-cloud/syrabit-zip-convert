import { useState, useEffect, useCallback } from 'react';
import { log } from '@/utils/logger';
import AdminQuickLinks from './AdminQuickLinks';
import {
  Users, MessageSquare, BookOpen, Zap, Loader2, Activity,
  ArrowRight, PenTool, Settings, Eye, TrendingUp, RefreshCw,
  UserPlus, Globe, Search, Bot, BarChart2, Server, Clock,
  CheckCircle, AlertCircle, AlertTriangle, Wifi, Database, DollarSign, Crown,
  Layers, Link2, Code2, FileCheck, Target, Cpu, ShieldCheck, Smartphone,
} from 'lucide-react';
import axios from 'axios';
import { adminGetDashboard, seoPipelineStatus, API_BASE } from '@/utils/api';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine, CartesianGrid, Legend,
} from 'recharts';

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
      <p className="text-2xl font-bold text-white">{typeof value === 'number' ? value.toLocaleString() : (value ?? 0)}</p>
      {subLabel && (
        <p className="text-xs text-slate-500 mt-1">
          {subLabel}: <span className="text-slate-400 font-medium">{typeof subValue === 'number' ? subValue.toLocaleString() : (subValue ?? 0)}</span>
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

const DEP_ICONS = { mongodb: Database, postgresql: Database, redis: Server, supabase: Database };
const STATUS_COLORS = { ok: '#10b981', error: '#ef4444', not_configured: '#64748b', unknown: '#f59e0b' };

function DepStatusCard({ name, status, latency }) {
  const Icon = DEP_ICONS[name] || Server;
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  return (
    <div className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-xl border border-slate-700/50">
      <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${color}20` }}>
        <Icon size={14} style={{ color }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-white text-sm font-medium capitalize">{name}</p>
        <p className="text-xs" style={{ color }}>{status === 'ok' ? 'Connected' : status}</p>
      </div>
      {status === 'ok' && (
        <div className="text-right">
          <p className="text-white text-sm font-bold">{latency}ms</p>
          <div className="h-1.5 w-16 rounded-full bg-slate-700 overflow-hidden mt-1">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.min(100, (latency / 500) * 100)}%`,
                background: latency < 100 ? '#10b981' : latency < 300 ? '#f59e0b' : '#ef4444',
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function PipelineWidget({ token }) {
  const [pipe, setPipe] = useState(null);
  useEffect(() => {
    seoPipelineStatus(token).then(r => setPipe(r.data)).catch(() => {});
  }, [token]);
  if (!pipe) return null;
  const bars = [
    { label: 'Published', value: pipe.published, total: pipe.total_topics, color: '#10b981' },
    { label: 'Has Content', value: pipe.has_content, total: pipe.total_topics, color: '#7c3aed' },
    { label: 'Needs Schema', value: pipe.needs_schema, total: pipe.total_topics, color: '#f59e0b', invert: true },
    { label: 'Needs Links', value: pipe.needs_internal_links, total: pipe.total_topics, color: '#3b82f6', invert: true },
  ];
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Layers size={14} className="text-violet-400" />
          <h3 className="text-slate-300 font-semibold text-sm">Content Pipeline</h3>
          <span className="text-xs text-slate-600">({pipe.total_topics} topics · {pipe.pages_total} pages)</span>
        </div>
        {pipe.published_today > 0 && (
          <span style={{ background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.25)', color: '#10b981', borderRadius: 20, padding: '2px 8px', fontSize: 11, fontWeight: 700 }}>
            +{pipe.published_today} today
          </span>
        )}
      </div>
      <div className="space-y-3">
        {bars.map(b => {
          const pct = Math.round((b.value / Math.max(b.total, 1)) * 100);
          return (
            <div key={b.label}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-500">{b.label}</span>
                <span className="text-xs font-mono" style={{ color: b.color }}>{b.value} ({pct}%)</span>
              </div>
              <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: b.color }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function alertColor(alert) {
  if (alert === 'red') return '#ef4444';
  if (alert === 'yellow') return '#f59e0b';
  return '#10b981';
}

function AlertBadge({ alert }) {
  const color = alertColor(alert);
  const label = alert === 'red' ? 'RED' : alert === 'yellow' ? 'YELLOW' : 'GREEN';
  return (
    <span
      className="text-xs font-bold px-2 py-0.5 rounded-full"
      style={{ background: `${color}20`, color, border: `1px solid ${color}40` }}
    >
      {label}
    </span>
  );
}

function RagAccuracyGauge({ accuracy }) {
  const pct = Math.min(100, Math.max(0, accuracy));
  const alert = pct < 95 ? 'red' : 'green';
  const color = alertColor(alert);
  const circumference = 2 * Math.PI * 40;
  const offset = circumference - (pct / 100) * circumference;
  return (
    <div className="flex flex-col items-center justify-center gap-2">
      <svg width="100" height="100" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="40" fill="none" stroke="#1e293b" strokeWidth="10" />
        <circle
          cx="50" cy="50" r="40"
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 50 50)"
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
        <text x="50" y="53" textAnchor="middle" fontSize="16" fontWeight="bold" fill="white">{pct.toFixed(1)}%</text>
        <text x="50" y="67" textAnchor="middle" fontSize="8" fill="#64748b">Target: 98%</text>
      </svg>
    </div>
  );
}

export default function AdminDashboard({ adminToken, onNavigate }) {
  const [data, setData] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const [ragAccuracy, setRagAccuracy] = useState(null);
  const [chatFallbacks, setChatFallbacks] = useState(null);
  const [vectorStats, setVectorStats] = useState(null);
  const [latency, setLatency] = useState(null);
  const [topQueries, setTopQueries] = useState(null);
  const [tokenSpend, setTokenSpend] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [pwaStats, setPwaStats] = useState(null);
  const [failedSections, setFailedSections] = useState([]);

  const headers = { withCredentials: true };
  const adminHdr = (token) => {
    const isJwt = token && typeof token === 'string' && token.split('.').length === 3;
    return isJwt ? { headers: { Authorization: `Bearer ${token}` }, withCredentials: true } : { withCredentials: true };
  };

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const [
        dashRes, metricsRes,
        ragAccRes, fallbackRes, vectorRes, latencyRes,
        queriesRes, tokenRes, funnelRes, coverageRes, pwaRes,
      ] = await Promise.allSettled([
        adminGetDashboard(adminToken),
        axios.get(`${API_BASE}/admin/dashboard/metrics`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/rag/accuracy`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/chat/fallbacks`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/vector/stats`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/perf/latency`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/analytics/queries`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/billing/tokens`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/monetization/funnel`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/content/coverage`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/pwa/stats`, adminHdr(adminToken)),
      ]);
      const failed = [];
      if (dashRes.status === 'fulfilled') setData(dashRes.value.data); else { failed.push('overview'); setData(null); }
      if (metricsRes.status === 'fulfilled') setMetrics(metricsRes.value.data); else { failed.push('metrics'); setMetrics(null); }
      if (ragAccRes.status === 'fulfilled') setRagAccuracy(ragAccRes.value.data); else { failed.push('rag'); setRagAccuracy(null); }
      if (fallbackRes.status === 'fulfilled') setChatFallbacks(fallbackRes.value.data); else { failed.push('fallbacks'); setChatFallbacks(null); }
      if (vectorRes.status === 'fulfilled') setVectorStats(vectorRes.value.data); else { failed.push('vector'); setVectorStats(null); }
      if (latencyRes.status === 'fulfilled') setLatency(latencyRes.value.data); else { failed.push('latency'); setLatency(null); }
      if (queriesRes.status === 'fulfilled') setTopQueries(queriesRes.value.data); else { failed.push('queries'); setTopQueries(null); }
      if (tokenRes.status === 'fulfilled') setTokenSpend(tokenRes.value.data); else { failed.push('tokens'); setTokenSpend(null); }
      if (funnelRes.status === 'fulfilled') setFunnel(funnelRes.value.data); else { failed.push('funnel'); setFunnel(null); }
      if (coverageRes.status === 'fulfilled') setCoverage(coverageRes.value.data); else { failed.push('coverage'); setCoverage(null); }
      if (pwaRes.status === 'fulfilled') setPwaStats(pwaRes.value.data); else { failed.push('pwa'); setPwaStats(null); }
      setFailedSections(failed);
      setLastRefresh(new Date());
    } catch (e) {
      log.error('Admin dashboard load failed', { error: e.message, status: e.response?.status });
      setFailedSections(['overview', 'metrics', 'rag', 'fallbacks', 'vector', 'latency', 'queries', 'tokens', 'funnel', 'coverage']);
    }
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
  const deps = metrics?.dependencies || {};

  const ragAlert = failedSections.includes('rag') ? 'yellow' : (ragAccuracy?.alert || 'green');
  const fallbackAlert = failedSections.includes('fallbacks') ? 'yellow' : (chatFallbacks?.alert || 'green');
  const latencyAlert = failedSections.includes('latency') ? 'yellow' : (latency?.alert || 'green');
  const vectorAlert = failedSections.includes('vector') ? 'yellow'
    : (vectorStats?.overall_coverage_pct ?? 100) < 90 ? 'yellow' : 'green';

  const hasRagIssue = ragAlert === 'red' || latencyAlert === 'red';

  const quickActions = [
    { id: 'users',     label: 'View Users',     icon: Users,    color: 'from-violet-600 to-violet-500' },
    { id: 'blog',      label: 'Blog Publisher', icon: PenTool,  color: 'from-blue-600 to-blue-500'    },
    { id: 'analytics', label: 'Analytics',       icon: BarChart2, color: 'from-emerald-600 to-emerald-500' },
    { id: 'monetization', label: 'Monetization', icon: Crown,    color: 'from-amber-600 to-amber-500'  },
  ];

  return (
    <div className="p-6 space-y-6">

      {failedSections.length > 0 && (
        <div className="flex items-center gap-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
          <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />
          <p className="text-xs text-amber-300 flex-1">
            Some widgets failed to load ({failedSections.join(', ')}). Metrics may be stale.
          </p>
          <button onClick={() => load(true)} className="text-xs text-amber-300 hover:text-white px-2 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 transition-colors">
            Retry
          </button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-slate-200 font-semibold text-lg">Overview</h2>
        <div className="flex items-center gap-3">
          {metrics?.response_time_ms && (
            <span className="text-xs text-slate-600 flex items-center gap-1">
              <Clock size={10} /> API: {metrics.response_time_ms}ms
            </span>
          )}
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

      {Object.keys(deps).length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Wifi size={14} className="text-violet-400" />
            <h3 className="text-slate-400 text-sm font-medium">System Health</h3>
            <div className="ml-auto flex items-center gap-1.5">
              {Object.values(deps).every(d => d.status === 'ok') && !hasRagIssue ? (
                <>
                  <CheckCircle size={12} className="text-emerald-400" />
                  <span className="text-emerald-400 text-xs font-medium">All Systems Operational</span>
                </>
              ) : (
                <>
                  <AlertCircle size={12} className="text-amber-400" />
                  <span className="text-amber-400 text-xs font-medium">
                    {hasRagIssue ? 'RAG/Latency Issue Detected' : 'Degraded'}
                  </span>
                </>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(deps).map(([name, info]) => (
              <DepStatusCard
                key={name}
                name={name}
                status={info.status}
                latency={info.latency_ms}
              />
            ))}
          </div>
        </div>
      )}

      {/* Data recovery summary banner */}
      {data?.conversation_date_range?.oldest && (
        <div style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.18)', borderRadius: 12, padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, color: '#10b981', fontWeight: 700 }}>✓ Data Recovered</span>
          <span style={{ fontSize: 12, color: 'rgba(232,232,232,0.55)' }}>
            Conversations since <strong style={{ color: '#e8e8e8' }}>{data.conversation_date_range.oldest}</strong>
            {' · '}PG: <strong style={{ color: '#60a5fa' }}>{data.pg_conversations}</strong>
            {' + '}Supabase: <strong style={{ color: '#34d399' }}>{data.supa_conversations}</strong>
            {' = '}<strong style={{ color: '#e8e8e8' }}>{data.total_conversations}</strong> total
            {' · '}<strong style={{ color: '#e8e8e8' }}>{data.conversations_with_messages}</strong> with messages
            {' · '}<strong style={{ color: '#e8e8e8' }}>{data.unique_chatters}</strong> unique chatters
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Users"     value={data?.total_users}          icon={Users}         color="#8b5cf6"
          subLabel="Chatted" subValue={data?.unique_chatters ?? 0} />
        <StatCard label="Conversations"   value={data?.total_conversations}  icon={MessageSquare} color="#3b82f6"
          subLabel="With messages" subValue={data?.conversations_with_messages ?? 0} />
        <StatCard label="Messages (All)"  value={data?.total_messages}       icon={Zap}           color="#10b981"
          subLabel="Since" subValue={data?.conversation_date_range?.oldest ?? '—'} />
        <StatCard label="Subjects"        value={data?.total_subjects}       icon={BookOpen}      color="#f59e0b" />
      </div>

      {metrics?.revenue && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Revenue (INR)"
            value={'₹' + Math.round(metrics.revenue.total_inr || 0).toLocaleString('en-IN')}
            icon={DollarSign}
            color="#10b981"
            subLabel="MRR"
            subValue={'₹' + Math.round(metrics.revenue.mrr_inr || 0).toLocaleString('en-IN')}
          />
          <StatCard label="Paid Users"      value={metrics.users?.paid || 0}     icon={Crown}  color="#f59e0b" />
          <StatCard label="Free Users"      value={metrics.users?.free || 0}     icon={Users}  color="#64748b" />
          <div className="cursor-pointer" onClick={() => onNavigate?.('seomanager')}>
            <StatCard label="SEO Pages"       value={metrics.seo?.published_pages || 0} icon={Globe} color="#06b6d4"
              subLabel="Topics" subValue={metrics.seo?.topics || 0} />
          </div>
        </div>
      )}

      {/* ── VISITOR RECOVERY SECTION ───────────────────────────────────────── */}
      <div style={{ background: 'rgba(6,182,212,0.04)', border: '1px solid rgba(6,182,212,0.15)', borderRadius: 14, padding: '14px 18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <Globe size={14} style={{ color: '#22d3ee' }} />
          <span style={{ fontSize: 12, fontWeight: 700, color: '#22d3ee' }}>All-time Visitor Recovery</span>
          {vs.users_since && (
            <span style={{ fontSize: 11, color: 'rgba(232,232,232,0.4)', marginLeft: 4 }}>
              since {vs.users_since}
            </span>
          )}
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'rgba(232,232,232,0.3)', fontStyle: 'italic' }}>
            Session tracking started {vs.tracking_since || '2026-03-29'} · pre-tracking data from user registrations
          </span>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" style={{ marginBottom: vs.daily_signups?.length ? 14 : 0 }}>
          <StatCard
            label="Total Visitors"
            value={vs.registered_visitors ?? vs.total_visitors ?? 0}
            icon={Users}
            color="#22d3ee"
            subLabel="All-time (best estimate)"
            subValue=""
          />
          <StatCard
            label="AI Chatters"
            value={vs.chatters ?? 0}
            icon={MessageSquare}
            color="#8b5cf6"
            subLabel="Used AI chat"
            subValue=""
          />
          <StatCard
            label="Session-tracked"
            value={vs.total_visitors ?? 0}
            icon={Eye}
            color="#06b6d4"
            subLabel={`Since ${vs.tracking_since || '2026-03-29'}`}
            subValue=""
          />
          <StatCard label="Visitors Today"  value={vs.visitors_today ?? 0}   icon={TrendingUp} color="#f97316" pulse
            subLabel="Page views" subValue={vs.page_views_today ?? 0} />
        </div>

        {/* Daily signups sparkline as traffic proxy */}
        {vs.daily_signups?.length > 0 && (
          <div>
            <div style={{ fontSize: 10, color: 'rgba(232,232,232,0.35)', fontWeight: 600, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Daily User Signups (traffic proxy since {vs.users_since})
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 40 }}>
              {(() => {
                const max = Math.max(...(vs.daily_signups || []).map(d => d.signups), 1);
                return (vs.daily_signups || []).map((d, i) => {
                  const h = Math.max(3, Math.round((d.signups / max) * 36));
                  const isToday = d.date === new Date().toISOString().slice(0,10);
                  return (
                    <div key={i} title={`${d.date}: ${d.signups} signups`}
                      style={{ flex: 1, minWidth: 4, maxWidth: 20, height: h, borderRadius: 2,
                        background: isToday ? '#f97316' : d.signups > 10 ? '#22d3ee' : 'rgba(6,182,212,0.35)',
                        cursor: 'default' }} />
                  );
                });
              })()}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3 }}>
              <span style={{ fontSize: 9, color: 'rgba(232,232,232,0.25)' }}>{vs.daily_signups?.[0]?.date}</span>
              <span style={{ fontSize: 9, color: 'rgba(232,232,232,0.25)' }}>{vs.daily_signups?.[vs.daily_signups.length-1]?.date}</span>
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Page Views Today" value={vs.page_views_today ?? 0} icon={Eye}      color="#ec4899" pulse />
        <StatCard label="Total Page Views" value={vs?.total_page_views ?? 0} icon={BarChart2} color="#84cc16"
          subLabel="Today" subValue={vs?.page_views_today ?? 0} />
        <StatCard label="Bounce Rate"  value={vs.bounce_rate != null ? `${vs.bounce_rate}%` : '—'} icon={TrendingUp} color="#f59e0b" />
        <StatCard label="Avg Session"  value={vs.avg_session_duration != null ? `${vs.avg_session_duration}s` : '—'} icon={Clock} color="#a78bfa" />
      </div>

      {/* ── AI HEALTH SECTION ─────────────────────────────────────────────── */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-5">
          <ShieldCheck size={16} className="text-violet-400" />
          <h3 className="text-slate-300 font-semibold">AI Health</h3>
          <div className="ml-auto flex items-center gap-2">
            <AlertBadge alert={ragAlert} />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {/* Widget 1: RAG Accuracy Gauge */}
          <div className="bg-slate-800/60 rounded-xl p-4 flex flex-col items-center gap-2">
            <div className="flex items-center justify-between w-full mb-1">
              <span className="text-slate-400 text-xs font-medium flex items-center gap-1">
                <Target size={11} /> RAG Accuracy
              </span>
              <AlertBadge alert={ragAlert} />
            </div>
            <RagAccuracyGauge
              accuracy={ragAccuracy?.accuracy_pct ?? 98}
            />
            <p className="text-xs text-slate-500 text-center">
              {ragAccuracy?.has_data
                ? `${ragAccuracy.answered_queries} / ${ragAccuracy.total_queries} queries answered`
                : 'No queries yet — showing default'}
            </p>
          </div>

          {/* Widget 2: Fallback Rate Line Chart */}
          <div className="bg-slate-800/60 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-slate-400 text-xs font-medium flex items-center gap-1">
                <Activity size={11} /> Daily Fallback Rate
              </span>
              <AlertBadge alert={fallbackAlert} />
            </div>
            {chatFallbacks?.has_data && chatFallbacks.daily.length > 0 ? (
              <ResponsiveContainer width="100%" height={90}>
                <LineChart data={chatFallbacks.daily}>
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#64748b' }} tickFormatter={d => d.slice(5)} />
                  <YAxis tick={{ fontSize: 9, fill: '#64748b' }} domain={[0, 'auto']} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: 'none', fontSize: 11 }}
                    formatter={v => [`${v}%`, 'Fallback Rate']}
                  />
                  <ReferenceLine y={5} stroke="#ef4444" strokeDasharray="3 3" label={{ value: '5% max', fill: '#ef4444', fontSize: 9 }} />
                  <Line type="monotone" dataKey="fallback_rate" stroke="#f59e0b" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : failedSections.includes('fallbacks') ? (
              <div className="flex flex-col items-center justify-center h-[90px] text-slate-600 text-xs gap-1">
                <Activity size={20} className="opacity-40" />
                <span className="text-amber-500/80">Could not load fallback data</span>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-[90px] text-slate-600 text-xs gap-1">
                <Activity size={20} className="opacity-40" />
                <span>No query data yet. Populates after first chat.</span>
                <span className="text-emerald-500 text-xs font-medium">
                  {chatFallbacks?.fallback_rate_pct ?? 0}% fallback rate
                </span>
              </div>
            )}
            <p className="text-xs text-slate-500 mt-1">
              Target: &lt;5% fallback rate
            </p>
          </div>

          {/* Widget 3: Vector Coverage Progress Bar */}
          <div className="bg-slate-800/60 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-slate-400 text-xs font-medium flex items-center gap-1">
                <Database size={11} /> Vector Coverage
              </span>
              <AlertBadge alert={vectorAlert} />
            </div>
            {vectorStats ? (
              <div className="space-y-3">
                {[
                  { label: 'SEO Pages', pct: vectorStats.pages?.coverage_pct ?? 0, color: '#8b5cf6' },
                  { label: 'Chapters', pct: vectorStats.chapters?.coverage_pct ?? 0, color: '#3b82f6' },
                  { label: 'Overall', pct: vectorStats.overall_coverage_pct ?? 0, color: '#10b981' },
                ].map(({ label, pct, color }) => (
                  <div key={label}>
                    <div className="flex justify-between mb-1">
                      <span className="text-xs text-slate-500">{label}</span>
                      <span className="text-xs font-mono" style={{ color }}>{pct}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-slate-700 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ width: `${pct}%`, background: pct >= 90 ? color : '#f59e0b' }}
                      />
                    </div>
                  </div>
                ))}
                <p className="text-xs text-slate-500 pt-1">
                  {vectorStats.embedded ?? 0} / {vectorStats.total ?? 0} items embedded
                </p>
                {(vectorStats.embedded ?? 0) === 0 && (vectorStats.total ?? 0) > 0 && (
                  <p className="text-xs text-amber-500/80 mt-1">
                    Add VERTEX_SERVICE_ACCOUNT to enable embedding
                  </p>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-20 text-slate-600 text-xs">
                No vector data
              </div>
            )}
            <p className="text-xs text-slate-500 mt-1">Target: ≥90%</p>
          </div>
        </div>
      </div>

      {/* ── PERFORMANCE & QUERIES ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Widget 4: P95 Latency Sparkline */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Clock size={14} className="text-violet-400" />
              <h3 className="text-slate-300 font-semibold text-sm">Query Latency P95</h3>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">P95: <span className="text-white font-medium">{latency?.p95_ms ?? 0}ms</span></span>
              <AlertBadge alert={latencyAlert} />
            </div>
          </div>
          {latency?.has_data && latency.daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={110}>
              <LineChart data={latency.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#64748b' }} tickFormatter={d => d.slice(5)} />
                <YAxis tick={{ fontSize: 9, fill: '#64748b' }} domain={[0, 'auto']} />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: 'none', fontSize: 11 }}
                  formatter={v => [`${v}ms`, 'P95']}
                />
                <ReferenceLine y={2000} stroke="#ef4444" strokeDasharray="4 4" label={{ value: '2s target', fill: '#ef4444', fontSize: 9 }} />
                <Line type="monotone" dataKey="p95_ms" stroke="#7c3aed" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex flex-col items-center justify-center h-[110px] text-slate-600 text-xs gap-1">
              <Cpu size={20} className="opacity-40" />
              <span>No latency data yet</span>
              <span className="text-xs text-slate-500">Data recorded after first chat</span>
            </div>
          )}
          <p className="text-xs text-slate-500 mt-1">Target: P95 &lt;2 s · Avg: {latency?.avg_ms ?? 0}ms</p>
        </div>

        {/* Widget 5: Top 10 Queries Leaderboard */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <Search size={14} className="text-violet-400" />
            <h3 className="text-slate-300 font-semibold text-sm">Top Queries</h3>
            <span className="text-xs text-slate-600">content gap signal</span>
          </div>
          {topQueries?.has_data && topQueries.top_queries.length > 0 ? (
            <div className="space-y-1.5 max-h-[150px] overflow-y-auto pr-1">
              {topQueries.top_queries.map((q, i) => {
                const maxCount = topQueries.top_queries[0]?.count || 1;
                const pct = Math.round((q.count / maxCount) * 100);
                return (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-slate-600 text-xs w-4 flex-shrink-0">{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex justify-between mb-0.5">
                        <span className="text-xs text-slate-300 truncate">{q.query}</span>
                        <span className="text-xs text-violet-400 font-mono ml-2 flex-shrink-0">{q.count}</span>
                      </div>
                      <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: '#7c3aed' }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-[100px] text-slate-600 text-xs gap-1">
              <Search size={20} className="opacity-40" />
              <span>No query data yet</span>
              <span className="text-xs text-slate-500">Populates after user chats</span>
            </div>
          )}
          <p className="text-xs text-slate-500 mt-2">
            {topQueries?.total_unique ?? 0} unique queries in last 7 days
          </p>
        </div>
      </div>

      {/* ── REVENUE INTELLIGENCE ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Widget 6: Token Spend Bar Chart */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <Cpu size={14} className="text-violet-400" />
            <h3 className="text-slate-300 font-semibold text-sm">Token Spend</h3>
          </div>
          {tokenSpend?.has_data && tokenSpend.daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={130}>
              <BarChart data={tokenSpend.daily} barSize={8}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fontSize: 8, fill: '#64748b' }} tickFormatter={d => d.slice(5)} />
                <YAxis tick={{ fontSize: 8, fill: '#64748b' }} />
                <Tooltip contentStyle={{ background: '#1e293b', border: 'none', fontSize: 10 }} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                <Bar dataKey="gemini_tokens" fill="#8b5cf6" name="Gemini" />
                <Bar dataKey="xai_tokens" fill="#06b6d4" name="xAI" />
                <Bar dataKey="groq_tokens" fill="#10b981" name="Groq" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex flex-col items-center justify-center h-[130px] text-slate-600 text-xs gap-1">
              <BarChart2 size={20} className="opacity-40" />
              <span>No token data yet</span>
              <span className="text-xs text-slate-500">Grows with AI usage</span>
            </div>
          )}
          {tokenSpend && Object.keys(tokenSpend.totals || {}).length > 0 && (
            <div className="flex gap-3 mt-2 flex-wrap">
              {Object.entries(tokenSpend.totals).map(([p, v]) => (
                <span key={p} className="text-xs text-slate-500">
                  {p}: <span className="text-slate-300">{(v.tokens || 0).toLocaleString()}</span>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Widget 7: Pro Conversion Funnel */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={14} className="text-violet-400" />
            <h3 className="text-slate-300 font-semibold text-sm">Conversion Funnel</h3>
          </div>
          {funnel ? (
            <div className="space-y-2">
              {(funnel.funnel || []).map((step, i) => {
                const maxCount = funnel.funnel[0]?.count || 1;
                const pct = Math.round((step.count / maxCount) * 100);
                const colors = ['#64748b', '#8b5cf6', '#f59e0b', '#10b981'];
                return (
                  <div key={step.stage}>
                    <div className="flex justify-between mb-0.5">
                      <span className="text-xs text-slate-400">{step.stage}</span>
                      <span className="text-xs font-mono text-white">{step.count.toLocaleString()}</span>
                    </div>
                    <div className="h-2.5 rounded-full bg-slate-800 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{ width: `${pct}%`, background: colors[i] || '#7c3aed' }}
                      />
                    </div>
                  </div>
                );
              })}
              <div className="pt-2 border-t border-slate-800 grid grid-cols-2 gap-2">
                <div className="text-center">
                  <p className="text-lg font-bold text-emerald-400">{funnel.free_to_paid_rate}%</p>
                  <p className="text-xs text-slate-500">Free→Paid</p>
                </div>
                <div className="text-center">
                  <p className="text-lg font-bold text-amber-400">{funnel.starter_to_pro_rate}%</p>
                  <p className="text-xs text-slate-500">Starter→Pro</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-[130px] text-slate-600 text-xs">
              Loading funnel…
            </div>
          )}
        </div>

        {/* Widget 8: AssamBoard Coverage Heatmap */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <FileCheck size={14} className="text-violet-400" />
            <h3 className="text-slate-300 font-semibold text-sm">AssamBoard Coverage</h3>
            <span className="text-xs text-slate-600">chapter × subject</span>
            {coverage?.has_data && coverage.subjects.length > 0 && (
              <span className="ml-auto text-xs text-slate-500">{coverage.subjects.length} subjects</span>
            )}
          </div>
          {coverage?.has_data && coverage.subjects.length > 0 ? (
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
              {coverage.subjects.map(sub => (
                <div key={sub.subject_id}>
                  <div className="flex justify-between mb-1">
                    <span className="text-xs text-slate-300 truncate flex items-center gap-1.5">
                      {sub.subject_name}
                      {(sub.class_name || sub.stream_name) && (
                        <span className="text-[10px] text-slate-600 font-normal shrink-0">
                          {[sub.class_name, sub.stream_name].filter(Boolean).join(' · ')}
                        </span>
                      )}
                    </span>
                    <span
                      className="text-xs font-mono ml-2 flex-shrink-0"
                      style={{ color: sub.coverage_pct >= 80 ? '#10b981' : sub.coverage_pct >= 50 ? '#f59e0b' : '#ef4444' }}
                    >
                      {sub.coverage_pct}%
                    </span>
                  </div>
                  <div className="flex gap-0.5 flex-wrap">
                    {(sub.chapters || []).map(ch => (
                      <div
                        key={ch.chapter_id}
                        title={`${ch.title}: ${ch.coverage}`}
                        className="w-3 h-3 rounded-sm"
                        style={{
                          background: ch.coverage === 'full' ? '#10b981'
                            : ch.coverage === 'partial' ? '#f59e0b'
                            : '#1e293b',
                          border: '1px solid rgba(255,255,255,0.05)',
                        }}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-[130px] text-slate-600 text-xs gap-1">
              <BookOpen size={20} className="opacity-40" />
              <span>No subjects found</span>
              <span className="text-xs text-slate-500">Add subjects to see coverage</span>
            </div>
          )}
          <div className="flex items-center gap-3 mt-2 pt-2 border-t border-slate-800">
            {[['#10b981', 'Full'], ['#f59e0b', 'Partial'], ['#1e293b', 'None']].map(([c, label]) => (
              <div key={label} className="flex items-center gap-1">
                <div className="w-2.5 h-2.5 rounded-sm" style={{ background: c, border: '1px solid rgba(255,255,255,0.1)' }} />
                <span className="text-xs text-slate-500">{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

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

      {pwaStats && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <Smartphone size={14} className="text-violet-400" />
            <h3 className="text-slate-300 font-semibold text-sm">PWA App Downloads</h3>
            {pwaStats.installs_today > 0 && (
              <span style={{ background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.25)', color: '#10b981', borderRadius: 20, padding: '2px 8px', fontSize: 11, fontWeight: 700 }}>
                +{pwaStats.installs_today} today
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
            <div className="bg-slate-800/50 rounded-xl p-3 text-center">
              <p className="text-xl font-bold text-violet-400">{pwaStats.total_installs}</p>
              <p className="text-xs text-slate-500 mt-0.5">Total Installs</p>
            </div>
            <div className="bg-slate-800/50 rounded-xl p-3 text-center">
              <p className="text-xl font-bold text-emerald-400">{pwaStats.installs_7d}</p>
              <p className="text-xs text-slate-500 mt-0.5">Last 7 Days</p>
            </div>
            <div className="bg-slate-800/50 rounded-xl p-3 text-center">
              <p className="text-xl font-bold text-cyan-400">{pwaStats.prompts_shown}</p>
              <p className="text-xs text-slate-500 mt-0.5">Prompts Shown</p>
            </div>
            <div className="bg-slate-800/50 rounded-xl p-3 text-center">
              <p className="text-xl font-bold" style={{ color: pwaStats.conversion_rate >= 30 ? '#10b981' : pwaStats.conversion_rate >= 15 ? '#f59e0b' : '#ef4444' }}>
                {pwaStats.conversion_rate}%
              </p>
              <p className="text-xs text-slate-500 mt-0.5">Install Rate</p>
            </div>
          </div>

          {pwaStats.daily_installs?.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <span style={{ fontSize: 10, color: 'rgba(232,232,232,0.35)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Daily Installs (14 days)
                </span>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-sm" style={{ background: '#8b5cf6' }} />
                    <span className="text-[10px] text-slate-500">Installs</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-sm" style={{ background: 'rgba(139,92,246,0.25)' }} />
                    <span className="text-[10px] text-slate-500">Prompts</span>
                  </div>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={100}>
                <BarChart data={pwaStats.daily_installs} barSize={10}>
                  <XAxis dataKey="date" tick={{ fontSize: 8, fill: '#64748b' }} tickFormatter={d => d.slice(5)} />
                  <YAxis tick={{ fontSize: 8, fill: '#64748b' }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: 'none', fontSize: 11, borderRadius: 8 }}
                    labelStyle={{ color: '#94a3b8' }}
                  />
                  <Bar dataKey="prompts" fill="rgba(139,92,246,0.25)" name="Prompts" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="installs" fill="#8b5cf6" name="Installs" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="flex items-center gap-4 mt-3 pt-3 border-t border-slate-800 text-xs text-slate-500">
            <span>Dismissed: <span className="text-slate-400 font-medium">{pwaStats.dismissed ?? 0}</span></span>
            <span>Rejected: <span className="text-slate-400 font-medium">{pwaStats.rejected ?? 0}</span></span>
          </div>
        </div>
      )}

      <PipelineWidget token={adminToken} />

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
      <AdminQuickLinks links={['content','seomanager','analytics','users','conversations','vertex','monetization']} onNavigate={onNavigate} />
    </div>
  );
}
