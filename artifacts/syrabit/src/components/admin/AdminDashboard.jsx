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

function GlassCard({ children, className = '', glow, ...props }) {
  return (
    <div
      className={`relative rounded-2xl overflow-hidden ${className}`}
      style={{
        background: 'rgba(15,15,30,0.6)',
        border: '1px solid rgba(255,255,255,0.06)',
        backdropFilter: 'blur(12px)',
      }}
      {...props}
    >
      {glow && (
        <div className="absolute inset-0 pointer-events-none" style={{
          background: `radial-gradient(ellipse at top left, ${glow}08, transparent 60%)`,
        }} />
      )}
      <div className="relative">{children}</div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, color, subLabel, subValue, pulse, onClick }) {
  return (
    <div
      className={`relative rounded-2xl p-5 overflow-hidden transition-all duration-300 group ${onClick ? 'cursor-pointer' : ''}`}
      style={{
        background: 'rgba(15,15,30,0.6)',
        border: '1px solid rgba(255,255,255,0.06)',
      }}
      onClick={onClick}
      data-testid="dashboard-stat-card"
    >
      <div className="absolute inset-0 pointer-events-none transition-opacity duration-300 opacity-0 group-hover:opacity-100" style={{
        background: `radial-gradient(ellipse at top right, ${color}08, transparent 60%)`,
      }} />
      {pulse && (
        <span className="absolute top-3 right-3 flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: color }} />
          <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: color }} />
        </span>
      )}
      <div className="relative flex items-center justify-between mb-3">
        <p className="text-white/40 text-xs font-medium tracking-wide uppercase">{label}</p>
        <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: `${color}12` }}>
          <Icon size={16} style={{ color }} />
        </div>
      </div>
      <p className="relative text-2xl font-bold text-white tracking-tight">{typeof value === 'number' ? value.toLocaleString() : (value ?? 0)}</p>
      {subLabel && (
        <p className="relative text-xs text-white/30 mt-1.5">
          {subLabel}: <span className="text-white/50 font-medium">{typeof subValue === 'number' ? subValue.toLocaleString() : (subValue ?? 0)}</span>
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
  signup:       { icon: UserPlus, color: '#10b981', bg: 'rgba(16,185,129,0.08)' },
  conversation: { icon: MessageSquare, color: '#8b5cf6', bg: 'rgba(139,92,246,0.08)' },
  search:       { icon: Search, color: '#60a5fa', bg: 'rgba(96,165,250,0.08)' },
  subject_view: { icon: BookOpen, color: '#f59e0b', bg: 'rgba(245,158,11,0.08)' },
  ai_click:     { icon: Bot, color: '#a78bfa', bg: 'rgba(167,139,250,0.08)' },
  page_view:    { icon: Eye, color: '#64748b', bg: 'rgba(100,116,139,0.08)' },
};

function ActivityItem({ event, idx }) {
  const cfg = EVENT_ICONS[event.type] || EVENT_ICONS.page_view;
  const Icon = cfg.icon;
  return (
    <div
      key={event.timestamp + idx}
      className="flex items-center gap-3 py-2.5 px-3 rounded-xl transition-colors duration-200 hover:bg-white/[0.02]"
      style={{ border: '1px solid rgba(255,255,255,0.03)' }}
    >
      <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: cfg.bg }}>
        <Icon size={13} style={{ color: cfg.color }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-white/70 truncate">{event.message}</p>
        {event.details && <p className="text-xs text-white/25 truncate">{event.details}</p>}
      </div>
      <span className="text-[11px] text-white/20 flex-shrink-0 ml-2">{formatTimeAgo(event.timestamp)}</span>
    </div>
  );
}

const DEP_ICONS = { mongodb: Database, postgresql: Database, redis: Server, supabase: Database };
const STATUS_COLORS = { ok: '#10b981', error: '#ef4444', not_configured: '#64748b', unknown: '#f59e0b' };

function DepStatusCard({ name, status, latency }) {
  const Icon = DEP_ICONS[name] || Server;
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  return (
    <div className="flex items-center gap-3 p-3 rounded-xl transition-all duration-200 hover:bg-white/[0.02]"
      style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
      <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${color}15` }}>
        <Icon size={14} style={{ color }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-white/80 text-sm font-medium capitalize">{name}</p>
        <p className="text-xs" style={{ color }}>{status === 'ok' ? 'Connected' : status}</p>
      </div>
      {status === 'ok' && (
        <div className="text-right">
          <p className="text-white/90 text-sm font-bold font-mono">{latency}ms</p>
          <div className="h-1.5 w-16 rounded-full overflow-hidden mt-1" style={{ background: 'rgba(255,255,255,0.06)' }}>
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
    <GlassCard className="p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Layers size={14} className="text-violet-400" />
          <h3 className="text-white/70 font-semibold text-sm">Content Pipeline</h3>
          <span className="text-xs text-white/25">({pipe.total_topics} topics · {pipe.pages_total} pages)</span>
        </div>
        {pipe.published_today > 0 && (
          <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full" style={{ background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.2)', color: '#10b981' }}>
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
                <span className="text-xs text-white/35">{b.label}</span>
                <span className="text-xs font-mono" style={{ color: b.color }}>{b.value} ({pct}%)</span>
              </div>
              <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.05)' }}>
                <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: b.color }} />
              </div>
            </div>
          );
        })}
      </div>
    </GlassCard>
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
      className="text-[10px] font-bold px-2 py-0.5 rounded-full"
      style={{ background: `${color}12`, color, border: `1px solid ${color}25` }}
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
        <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="10" />
        <circle
          cx="50" cy="50" r="40"
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 50 50)"
          style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.4,0,0.2,1)' }}
        />
        <text x="50" y="50" textAnchor="middle" fontSize="17" fontWeight="bold" fill="white" dominantBaseline="central">{pct.toFixed(1)}%</text>
        <text x="50" y="70" textAnchor="middle" fontSize="8" fill="rgba(255,255,255,0.3)">Target: 98%</text>
      </svg>
    </div>
  );
}

const TOOLTIP_STYLE = {
  background: 'rgba(15,15,30,0.95)',
  border: '1px solid rgba(255,255,255,0.08)',
  borderRadius: 12,
  color: '#e2e8f0',
  fontSize: 12,
  backdropFilter: 'blur(12px)',
};

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={TOOLTIP_STYLE} className="p-3 shadow-2xl">
      <p className="text-[11px] text-white/30 mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-xs" style={{ color: p.color }}>
          {p.name}: <span className="font-mono font-bold">{p.value}</span>
        </p>
      ))}
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
      <div className="flex flex-col items-center justify-center p-16 gap-3">
        <Loader2 size={24} className="animate-spin text-violet-400/50" />
        <span className="text-sm text-white/20">Loading dashboard...</span>
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
    { id: 'users',     label: 'View Users',     icon: Users,    gradient: 'linear-gradient(135deg, #7c3aed, #6d28d9)' },
    { id: 'blog',      label: 'Blog Publisher', icon: PenTool,  gradient: 'linear-gradient(135deg, #3b82f6, #2563eb)' },
    { id: 'analytics', label: 'Analytics',       icon: BarChart2, gradient: 'linear-gradient(135deg, #10b981, #059669)' },
    { id: 'monetization', label: 'Monetization', icon: Crown,    gradient: 'linear-gradient(135deg, #f59e0b, #d97706)' },
  ];

  return (
    <div className="p-4 md:p-6 space-y-5 max-w-[1400px]">

      {failedSections.length > 0 && (
        <div className="flex items-center gap-3 p-3 rounded-xl" style={{ background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.15)' }}>
          <AlertTriangle size={14} className="text-amber-400/80 flex-shrink-0" />
          <p className="text-xs text-amber-300/70 flex-1">
            Some widgets failed to load ({failedSections.join(', ')}). Metrics may be stale.
          </p>
          <button onClick={() => load(true)} className="text-xs text-amber-300/70 hover:text-white px-2.5 py-1 rounded-lg transition-colors" style={{ background: 'rgba(245,158,11,0.1)' }}>
            Retry
          </button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-white/90 font-semibold text-lg tracking-tight">Overview</h2>
          {lastRefresh && (
            <p className="text-white/20 text-xs mt-0.5">
              Updated {formatTimeAgo(lastRefresh.toISOString())} · auto-refreshes every 60s
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          {metrics?.response_time_ms && (
            <span className="text-xs text-white/20 flex items-center gap-1">
              <Clock size={10} /> API: {metrics.response_time_ms}ms
            </span>
          )}
          <button
            onClick={() => load(true)}
            disabled={refreshing}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-medium text-white/40 hover:text-white/70 transition-all disabled:opacity-40"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}
          >
            <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {Object.keys(deps).length > 0 && (
        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <Wifi size={14} className="text-violet-400" />
            <h3 className="text-white/50 text-sm font-semibold">System Health</h3>
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
        </GlassCard>
      )}

      {data?.conversation_date_range?.oldest && (
        <div className="flex items-center gap-3 p-3 rounded-xl flex-wrap" style={{ background: 'rgba(16,185,129,0.04)', border: '1px solid rgba(16,185,129,0.12)' }}>
          <span className="text-xs text-emerald-400/80 font-bold">Data Recovered</span>
          <span className="text-xs text-white/40">
            Conversations since <strong className="text-white/70">{data.conversation_date_range.oldest}</strong>
            {' · '}PG: <strong className="text-blue-400/80">{data.pg_conversations}</strong>
            {' + '}Supabase: <strong className="text-emerald-400/80">{data.supa_conversations}</strong>
            {' = '}<strong className="text-white/70">{data.total_conversations}</strong> total
            {' · '}<strong className="text-white/70">{data.conversations_with_messages}</strong> with messages
            {' · '}<strong className="text-white/70">{data.unique_chatters}</strong> unique chatters
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Total Users"     value={data?.total_users}          icon={Users}         color="#8b5cf6"
          subLabel="Chatted" subValue={data?.unique_chatters ?? 0} />
        <StatCard label="Conversations"   value={data?.total_conversations}  icon={MessageSquare} color="#3b82f6"
          subLabel="With messages" subValue={data?.conversations_with_messages ?? 0} />
        <StatCard label="Messages (All)"  value={data?.total_messages}       icon={Zap}           color="#10b981"
          subLabel="Since" subValue={data?.conversation_date_range?.oldest ?? '—'} />
        <StatCard label="Subjects"        value={data?.total_subjects}       icon={BookOpen}      color="#f59e0b" />
      </div>

      {metrics?.revenue && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
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
          <StatCard label="SEO Pages"       value={metrics.seo?.published_pages || 0} icon={Globe} color="#06b6d4"
            subLabel="Topics" subValue={metrics.seo?.topics || 0}
            onClick={() => onNavigate?.('seomanager')} />
        </div>
      )}

      <GlassCard className="p-5" glow="#06b6d4">
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          <Globe size={14} style={{ color: '#22d3ee' }} />
          <span className="text-xs font-bold text-cyan-400">Traffic Sources</span>
          <span className="ml-auto text-[10px] text-white/20 italic">
            Server-side = Cloudflare-equivalent · JS-tracked = engaged users · Bot = crawlers
          </span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-3">
          <div className="rounded-xl p-3" style={{ background: 'rgba(16,185,129,0.04)', border: '1px solid rgba(16,185,129,0.12)' }}>
            <div className="flex items-center gap-1.5 mb-2">
              <Server size={11} style={{ color: '#10b981' }} />
              <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider">All Traffic</span>
              <span className="text-[9px] text-white/20 ml-auto">server-side</span>
            </div>
            <div className="flex gap-4">
              <div>
                <p className="text-white font-bold text-lg">{(vs.server_side?.total_unique ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-white/25">Unique</p>
              </div>
              <div>
                <p className="text-white font-bold text-lg">{(vs.server_side?.unique_today ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-white/25">Today</p>
              </div>
              <div>
                <p className="text-white/50 font-bold text-lg">{(vs.server_side?.total_hits ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-white/25">Hits</p>
              </div>
            </div>
          </div>

          <div className="rounded-xl p-3" style={{ background: 'rgba(139,92,246,0.04)', border: '1px solid rgba(139,92,246,0.12)' }}>
            <div className="flex items-center gap-1.5 mb-2">
              <Eye size={11} style={{ color: '#8b5cf6' }} />
              <span className="text-[10px] font-bold text-violet-400 uppercase tracking-wider">Engaged Visitors</span>
              <span className="text-[9px] text-white/20 ml-auto">JS-tracked</span>
            </div>
            <div className="flex gap-4">
              <div>
                <p className="text-white font-bold text-lg">{(vs.total_visitors ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-white/25">All-time</p>
              </div>
              <div>
                <p className="text-white font-bold text-lg">{(vs.visitors_today ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-white/25">Today</p>
              </div>
              <div>
                <p className="text-white/50 font-bold text-lg">{(vs.total_page_views ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-white/25">Views</p>
              </div>
            </div>
          </div>

          <div className="rounded-xl p-3" style={{ background: 'rgba(245,158,11,0.04)', border: '1px solid rgba(245,158,11,0.12)' }}>
            <div className="flex items-center gap-1.5 mb-2">
              <Bot size={11} style={{ color: '#f59e0b' }} />
              <span className="text-[10px] font-bold text-amber-400 uppercase tracking-wider">Bot/Crawler Traffic</span>
              <span className="text-[9px] text-white/20 ml-auto">separate</span>
            </div>
            <div className="flex gap-4">
              <div>
                <p className="text-white font-bold text-lg">{(vs.bot_traffic?.unique_total ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-white/25">Unique bots</p>
              </div>
              <div>
                <p className="text-white font-bold text-lg">{(vs.bot_traffic?.hits_today ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-white/25">Today</p>
              </div>
              <div>
                <p className="text-white/50 font-bold text-lg">{(vs.bot_traffic?.total_hits ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-white/25">Total</p>
              </div>
            </div>
          </div>
        </div>

        {vs.server_side?.total_unique > 0 && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg flex-wrap" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.03)' }}>
            <span className="text-[10px] text-white/25 font-semibold">TRACKING FUNNEL:</span>
            <span className="text-[11px] text-emerald-400 font-bold">{(vs.server_side?.total_unique ?? 0).toLocaleString()}</span>
            <span className="text-[10px] text-white/15">server</span>
            <span className="text-[10px] text-white/10">&rarr;</span>
            <span className="text-[11px] text-violet-400 font-bold">{(vs.total_visitors ?? 0).toLocaleString()}</span>
            <span className="text-[10px] text-white/15">JS-tracked</span>
            <span className="text-[10px] text-white/10">&rarr;</span>
            <span className="text-[11px] text-amber-400 font-bold">{(vs.bot_traffic?.total_hits ?? 0).toLocaleString()}</span>
            <span className="text-[10px] text-white/15">bot hits</span>
            {vs.total_visitors > 0 && vs.server_side?.total_unique > 0 && (
              <span className="ml-auto text-[10px] text-white/20">
                JS capture rate: {Math.round((vs.total_visitors / vs.server_side.total_unique) * 100)}%
              </span>
            )}
          </div>
        )}

        {vs.bot_traffic?.top_bots?.length > 0 && (
          <div className="mt-3">
            <div className="text-[10px] text-white/20 font-semibold mb-1.5 uppercase tracking-wider">Top Crawlers</div>
            <div className="flex flex-wrap gap-1.5">
              {vs.bot_traffic.top_bots.slice(0, 8).map((b, i) => (
                <span key={i} className="text-[10px] px-2 py-0.5 rounded-md" style={{ color: '#f59e0b', background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.1)' }}>
                  {b.bot}: {b.hits}
                </span>
              ))}
            </div>
          </div>
        )}
      </GlassCard>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Page Views Today" value={vs.page_views_today ?? 0} icon={Eye}      color="#ec4899" pulse />
        <StatCard label="Total Page Views" value={vs?.total_page_views ?? 0} icon={BarChart2} color="#84cc16"
          subLabel="Today" subValue={vs?.page_views_today ?? 0} />
        <StatCard label="Bounce Rate"  value={vs.bounce_rate != null ? `${vs.bounce_rate}%` : '—'} icon={TrendingUp} color="#f59e0b" />
        <StatCard label="Avg Session"  value={vs.avg_session_duration != null ? `${vs.avg_session_duration}s` : '—'} icon={Clock} color="#a78bfa" />
      </div>

      <GlassCard className="p-5" glow="#7c3aed">
        <div className="flex items-center gap-2 mb-5">
          <ShieldCheck size={16} className="text-violet-400" />
          <h3 className="text-white/70 font-semibold">AI Health</h3>
          <div className="ml-auto flex items-center gap-2">
            <AlertBadge alert={ragAlert} />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="rounded-xl p-4 flex flex-col items-center gap-2" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
            <div className="flex items-center justify-between w-full mb-1">
              <span className="text-white/35 text-xs font-medium flex items-center gap-1">
                <Target size={11} /> RAG Accuracy
              </span>
              <AlertBadge alert={ragAlert} />
            </div>
            <RagAccuracyGauge accuracy={ragAccuracy?.accuracy_pct ?? 98} />
            <p className="text-xs text-white/25 text-center">
              {ragAccuracy?.has_data
                ? `${ragAccuracy.answered_queries} / ${ragAccuracy.total_queries} queries answered`
                : 'No queries yet — showing default'}
            </p>
          </div>

          <div className="rounded-xl p-4" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-white/35 text-xs font-medium flex items-center gap-1">
                <Activity size={11} /> Daily Fallback Rate
              </span>
              <AlertBadge alert={fallbackAlert} />
            </div>
            {chatFallbacks?.has_data && chatFallbacks.daily.length > 0 ? (
              <ResponsiveContainer width="100%" height={90}>
                <LineChart data={chatFallbacks.daily}>
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.2)' }} tickFormatter={d => d.slice(5)} />
                  <YAxis tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.2)' }} domain={[0, 'auto']} />
                  <Tooltip content={<ChartTooltip />} />
                  <ReferenceLine y={5} stroke="#ef4444" strokeDasharray="3 3" label={{ value: '5% max', fill: '#ef4444', fontSize: 9 }} />
                  <Line type="monotone" dataKey="fallback_rate" stroke="#f59e0b" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : failedSections.includes('fallbacks') ? (
              <div className="flex flex-col items-center justify-center h-[90px] text-white/20 text-xs gap-1">
                <Activity size={20} className="opacity-30" />
                <span className="text-amber-500/60">Could not load fallback data</span>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-[90px] text-white/20 text-xs gap-1">
                <Activity size={20} className="opacity-30" />
                <span>No query data yet</span>
                <span className="text-emerald-400/70 text-xs font-medium">
                  {chatFallbacks?.fallback_rate_pct ?? 0}% fallback rate
                </span>
              </div>
            )}
            <p className="text-xs text-white/20 mt-1">Target: &lt;5% fallback rate</p>
          </div>

          <div className="rounded-xl p-4" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-white/35 text-xs font-medium flex items-center gap-1">
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
                      <span className="text-xs text-white/30">{label}</span>
                      <span className="text-xs font-mono" style={{ color }}>{pct}%</span>
                    </div>
                    <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.05)' }}>
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${pct}%`, background: pct >= 90 ? color : '#f59e0b' }}
                      />
                    </div>
                  </div>
                ))}
                <p className="text-xs text-white/25 pt-1">
                  {vectorStats.embedded ?? 0} / {vectorStats.total ?? 0} items embedded
                </p>
                {(vectorStats.embedded ?? 0) === 0 && (vectorStats.total ?? 0) > 0 && (
                  <p className="text-xs text-amber-400/60 mt-1">
                    Add VERTEX_SERVICE_ACCOUNT to enable embedding
                  </p>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-20 text-white/20 text-xs">
                No vector data
              </div>
            )}
            <p className="text-xs text-white/20 mt-1">Target: &ge;90%</p>
          </div>
        </div>
      </GlassCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <GlassCard className="p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Clock size={14} className="text-violet-400" />
              <h3 className="text-white/70 font-semibold text-sm">Query Latency P95</h3>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-white/30">P95: <span className="text-white/80 font-medium">{latency?.p95_ms ?? 0}ms</span></span>
              <AlertBadge alert={latencyAlert} />
            </div>
          </div>
          {latency?.has_data && latency.daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={110}>
              <LineChart data={latency.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.2)' }} tickFormatter={d => d.slice(5)} />
                <YAxis tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.2)' }} domain={[0, 'auto']} />
                <Tooltip content={<ChartTooltip />} />
                <ReferenceLine y={2000} stroke="#ef4444" strokeDasharray="4 4" label={{ value: '2s target', fill: '#ef4444', fontSize: 9 }} />
                <Line type="monotone" dataKey="p95_ms" stroke="#7c3aed" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex flex-col items-center justify-center h-[110px] text-white/20 text-xs gap-1">
              <Cpu size={20} className="opacity-30" />
              <span>No latency data yet</span>
              <span className="text-xs text-white/15">Data recorded after first chat</span>
            </div>
          )}
          <p className="text-xs text-white/20 mt-1">Target: P95 &lt;2 s · Avg: {latency?.avg_ms ?? 0}ms</p>
        </GlassCard>

        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <Search size={14} className="text-violet-400" />
            <h3 className="text-white/70 font-semibold text-sm">Top Queries</h3>
            <span className="text-xs text-white/20">content gap signal</span>
          </div>
          {topQueries?.has_data && topQueries.top_queries.length > 0 ? (
            <div className="space-y-1.5 max-h-[150px] overflow-y-auto pr-1">
              {topQueries.top_queries.map((q, i) => {
                const maxCount = topQueries.top_queries[0]?.count || 1;
                const pct = Math.round((q.count / maxCount) * 100);
                return (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-white/20 text-xs w-4 flex-shrink-0 font-mono">{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex justify-between mb-0.5">
                        <span className="text-xs text-white/60 truncate">{q.query}</span>
                        <span className="text-xs text-violet-400 font-mono ml-2 flex-shrink-0">{q.count}</span>
                      </div>
                      <div className="h-1 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.04)' }}>
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: 'linear-gradient(90deg, #7c3aed, #a78bfa)' }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-[100px] text-white/20 text-xs gap-1">
              <Search size={20} className="opacity-30" />
              <span>No query data yet</span>
              <span className="text-xs text-white/15">Populates after user chats</span>
            </div>
          )}
          <p className="text-xs text-white/20 mt-2">
            {topQueries?.total_unique ?? 0} unique queries in last 7 days
          </p>
        </GlassCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <Cpu size={14} className="text-violet-400" />
            <h3 className="text-white/70 font-semibold text-sm">Token Spend</h3>
          </div>
          {tokenSpend?.has_data && tokenSpend.daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={130}>
              <BarChart data={tokenSpend.daily} barSize={8}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="date" tick={{ fontSize: 8, fill: 'rgba(255,255,255,0.2)' }} tickFormatter={d => d.slice(5)} />
                <YAxis tick={{ fontSize: 8, fill: 'rgba(255,255,255,0.2)' }} />
                <Tooltip content={<ChartTooltip />} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                <Bar dataKey="gemini_tokens" fill="#8b5cf6" name="Gemini" radius={[3,3,0,0]} />
                <Bar dataKey="xai_tokens" fill="#06b6d4" name="xAI" radius={[3,3,0,0]} />
                <Bar dataKey="groq_tokens" fill="#10b981" name="Groq" radius={[3,3,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex flex-col items-center justify-center h-[130px] text-white/20 text-xs gap-1">
              <BarChart2 size={20} className="opacity-30" />
              <span>No token data yet</span>
              <span className="text-xs text-white/15">Grows with AI usage</span>
            </div>
          )}
          {tokenSpend && Object.keys(tokenSpend.totals || {}).length > 0 && (
            <div className="flex gap-3 mt-2 flex-wrap">
              {Object.entries(tokenSpend.totals).map(([p, v]) => (
                <span key={p} className="text-xs text-white/30">
                  {p}: <span className="text-white/50">{(v.tokens || 0).toLocaleString()}</span>
                </span>
              ))}
            </div>
          )}
        </GlassCard>

        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={14} className="text-violet-400" />
            <h3 className="text-white/70 font-semibold text-sm">Conversion Funnel</h3>
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
                      <span className="text-xs text-white/40">{step.stage}</span>
                      <span className="text-xs font-mono text-white/80">{step.count.toLocaleString()}</span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.04)' }}>
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${pct}%`, background: colors[i] || '#7c3aed' }}
                      />
                    </div>
                  </div>
                );
              })}
              <div className="pt-2 border-t border-white/[0.04] grid grid-cols-2 gap-2">
                <div className="text-center">
                  <p className="text-lg font-bold text-emerald-400">{funnel.free_to_paid_rate}%</p>
                  <p className="text-xs text-white/25">Free→Paid</p>
                </div>
                <div className="text-center">
                  <p className="text-lg font-bold text-amber-400">{funnel.starter_to_pro_rate}%</p>
                  <p className="text-xs text-white/25">Starter→Pro</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-[130px] text-white/20 text-xs">
              Loading funnel…
            </div>
          )}
        </GlassCard>

        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <FileCheck size={14} className="text-violet-400" />
            <h3 className="text-white/70 font-semibold text-sm">Assam Board Coverage</h3>
            <span className="text-xs text-white/20">chapter × subject</span>
            {coverage?.has_data && coverage.subjects.length > 0 && (
              <span className="ml-auto text-xs text-white/25">{coverage.subjects.length} subjects</span>
            )}
          </div>
          {coverage?.has_data && coverage.subjects.length > 0 ? (
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
              {coverage.subjects.map(sub => (
                <div key={sub.subject_id}>
                  <div className="flex justify-between mb-1">
                    <span className="text-xs text-white/60 truncate flex items-center gap-1.5">
                      {sub.subject_name}
                      {(sub.class_name || sub.stream_name) && (
                        <span className="text-[10px] text-white/20 font-normal shrink-0">
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
                            : 'rgba(255,255,255,0.04)',
                          border: '1px solid rgba(255,255,255,0.04)',
                        }}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-[130px] text-white/20 text-xs gap-1">
              <BookOpen size={20} className="opacity-30" />
              <span>No subjects found</span>
              <span className="text-xs text-white/15">Add subjects to see coverage</span>
            </div>
          )}
          <div className="flex items-center gap-3 mt-2 pt-2 border-t border-white/[0.04]">
            {[['#10b981', 'Full'], ['#f59e0b', 'Partial'], ['rgba(255,255,255,0.04)', 'None']].map(([c, label]) => (
              <div key={label} className="flex items-center gap-1">
                <div className="w-2.5 h-2.5 rounded-sm" style={{ background: c, border: '1px solid rgba(255,255,255,0.06)' }} />
                <span className="text-xs text-white/25">{label}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>

      {data?.plan_distribution && (
        <GlassCard className="p-5">
          <h3 className="text-white/50 text-sm font-semibold mb-4">Plan Distribution</h3>
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
                <div key={key} className="text-center p-4 rounded-xl" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                  <p className="text-2xl font-bold" style={{ color }}>{count}</p>
                  <p className="text-white/40 text-sm">{label}</p>
                  <div className="mt-2 h-1 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.05)' }}>
                    <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
                  </div>
                  <p className="text-xs text-white/20 mt-1">{pct}%</p>
                </div>
              );
            })}
          </div>
        </GlassCard>
      )}

      {pwaStats && (
        <GlassCard className="p-5" glow="#8b5cf6">
          <div className="flex items-center gap-2 mb-4">
            <Smartphone size={14} className="text-violet-400" />
            <h3 className="text-white/70 font-semibold text-sm">PWA App Downloads</h3>
            {pwaStats.installs_today > 0 && (
              <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full" style={{ background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.2)', color: '#10b981' }}>
                +{pwaStats.installs_today} today
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
            {[
              { label: 'Total Installs', value: pwaStats.total_installs, color: '#a78bfa' },
              { label: 'Last 7 Days', value: pwaStats.installs_7d, color: '#10b981' },
              { label: 'Prompts Shown', value: pwaStats.prompts_shown, color: '#22d3ee' },
              { label: 'Install Rate', value: `${pwaStats.conversion_rate}%`, color: pwaStats.conversion_rate >= 30 ? '#10b981' : pwaStats.conversion_rate >= 15 ? '#f59e0b' : '#ef4444' },
            ].map(item => (
              <div key={item.label} className="rounded-xl p-3 text-center" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                <p className="text-xl font-bold" style={{ color: item.color }}>{item.value}</p>
                <p className="text-xs text-white/25 mt-0.5">{item.label}</p>
              </div>
            ))}
          </div>

          {pwaStats.daily_installs?.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-white/20 font-semibold uppercase tracking-wider">Daily Installs (14 days)</span>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-sm" style={{ background: '#8b5cf6' }} />
                    <span className="text-[10px] text-white/25">Installs</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-sm" style={{ background: 'rgba(139,92,246,0.25)' }} />
                    <span className="text-[10px] text-white/25">Prompts</span>
                  </div>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={100}>
                <BarChart data={pwaStats.daily_installs} barSize={10}>
                  <XAxis dataKey="date" tick={{ fontSize: 8, fill: 'rgba(255,255,255,0.2)' }} tickFormatter={d => d.slice(5)} />
                  <YAxis tick={{ fontSize: 8, fill: 'rgba(255,255,255,0.2)' }} allowDecimals={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar dataKey="prompts" fill="rgba(139,92,246,0.25)" name="Prompts" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="installs" fill="#8b5cf6" name="Installs" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="flex items-center gap-4 mt-3 pt-3 border-t border-white/[0.04] text-xs text-white/25">
            <span>Dismissed: <span className="text-white/40 font-medium">{pwaStats.dismissed ?? 0}</span></span>
            <span>Rejected: <span className="text-white/40 font-medium">{pwaStats.rejected ?? 0}</span></span>
          </div>
        </GlassCard>
      )}

      <PipelineWidget token={adminToken} />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {quickActions.map((action) => (
          <button
            key={action.id}
            onClick={() => onNavigate?.(action.id)}
            className="flex items-center justify-between p-4 rounded-2xl transition-all duration-300 group hover:scale-[1.01]"
            style={{
              background: 'rgba(15,15,30,0.6)',
              border: '1px solid rgba(255,255,255,0.06)',
            }}
            data-testid={`quick-action-${action.id}`}
          >
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: action.gradient }}>
                <action.icon size={15} className="text-white" />
              </div>
              <span className="text-sm font-medium text-white/80 group-hover:text-white transition-colors">{action.label}</span>
            </div>
            <ArrowRight size={14} className="text-white/15 group-hover:text-white/40 transition-colors" />
          </button>
        ))}
      </div>

      {vs.daily_visitors?.length > 0 && (
        <GlassCard className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white/50 text-sm font-semibold">Visitor Trend — Last 7 Days</h3>
            <span className="text-xs text-white/20">Unique visitors per day</span>
          </div>
          <div className="flex items-end gap-2 h-20">
            {vs.daily_visitors.map((d, i) => {
              const maxV = Math.max(...vs.daily_visitors.map(x => x.visitors), 1);
              const pct = Math.max(4, (d.visitors / maxV) * 100);
              const isToday = i === vs.daily_visitors.length - 1;
              return (
                <div key={d.date} className="flex-1 flex flex-col items-center gap-1">
                  <div
                    className="w-full rounded-t transition-all duration-300"
                    style={{
                      height: `${pct}%`,
                      background: isToday
                        ? 'linear-gradient(to top, #7c3aed, #a78bfa)'
                        : 'rgba(139,92,246,0.20)',
                      minHeight: 4,
                    }}
                    title={`${d.date}: ${d.visitors} visitors, ${d.page_views} views`}
                  />
                  <span className="text-[10px] text-white/20 whitespace-nowrap">
                    {d.date.slice(5)}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="flex gap-4 mt-3">
            {vs.daily_visitors.slice(-1).map(d => (
              <div key="today-summary" className="flex gap-4 text-xs text-white/30">
                <span>Today: <span className="text-violet-400 font-medium">{d.visitors} visitors</span></span>
                <span>·</span>
                <span><span className="text-white/50 font-medium">{d.page_views}</span> page views</span>
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      <GlassCard className="p-5" data-testid="recent-activity">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-violet-400" />
            <h3 className="text-white/70 font-semibold">Recent Activity</h3>
            <span className="flex h-2 w-2 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
          </div>
          <button
            onClick={() => onNavigate?.('activitylog')}
            className="text-xs text-violet-400/70 hover:text-violet-400 transition-colors"
          >
            View all logs →
          </button>
        </div>

        {recentEvents.length === 0 ? (
          <div className="text-center py-8">
            <Activity size={28} className="text-white/10 mx-auto mb-3" />
            <p className="text-white/20 text-sm">No activity yet — events will appear here in real time</p>
          </div>
        ) : (
          <div className="space-y-1.5">
            {recentEvents.map((event, idx) => (
              <ActivityItem key={idx} event={event} idx={idx} />
            ))}
          </div>
        )}
      </GlassCard>

      <AdminQuickLinks links={['content','seomanager','analytics','users','conversations','vertex','monetization']} onNavigate={onNavigate} />
    </div>
  );
}
