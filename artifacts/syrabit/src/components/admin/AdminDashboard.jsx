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
      className={`relative rounded-2xl overflow-hidden bg-white border border-gray-200 shadow-sm ${className}`}
      {...props}
    >
      <div className="relative">{children}</div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, color, subLabel, subValue, pulse, onClick }) {
  return (
    <div
      className={`relative rounded-2xl p-5 overflow-hidden transition-all duration-300 group bg-white border border-gray-200 shadow-sm ${onClick ? 'cursor-pointer hover:shadow-md' : ''}`}
      onClick={onClick}
      data-testid="dashboard-stat-card"
    >
      {pulse && (
        <span className="absolute top-3 right-3 flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: color }} />
          <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: color }} />
        </span>
      )}
      <div className="flex items-center justify-between mb-3">
        <p className="text-gray-500 text-xs font-medium tracking-wide uppercase">{label}</p>
        <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: `${color}15` }}>
          <Icon size={16} style={{ color }} />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 tracking-tight">{typeof value === 'number' ? value.toLocaleString() : (value ?? 0)}</p>
      {subLabel && (
        <p className="text-xs text-gray-400 mt-1.5">
          {subLabel}: <span className="text-gray-600 font-medium">{typeof subValue === 'number' ? subValue.toLocaleString() : (subValue ?? 0)}</span>
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
  signup:       { icon: UserPlus, color: '#10b981', bg: '#ecfdf5' },
  conversation: { icon: MessageSquare, color: '#8b5cf6', bg: '#f5f3ff' },
  search:       { icon: Search, color: '#60a5fa', bg: '#eff6ff' },
  subject_view: { icon: BookOpen, color: '#f59e0b', bg: '#fffbeb' },
  ai_click:     { icon: Bot, color: '#a78bfa', bg: '#f5f3ff' },
  page_view:    { icon: Eye, color: '#64748b', bg: '#f8fafc' },
};

function ActivityItem({ event, idx }) {
  const cfg = EVENT_ICONS[event.type] || EVENT_ICONS.page_view;
  const Icon = cfg.icon;
  return (
    <div
      key={event.timestamp + idx}
      className="flex items-center gap-3 py-2.5 px-3 rounded-xl transition-colors duration-200 hover:bg-gray-50 border border-gray-100"
    >
      <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: cfg.bg }}>
        <Icon size={13} style={{ color: cfg.color }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-700 truncate">{event.message}</p>
        {event.details && <p className="text-xs text-gray-400 truncate">{event.details}</p>}
      </div>
      <span className="text-[11px] text-gray-400 flex-shrink-0 ml-2">{formatTimeAgo(event.timestamp)}</span>
    </div>
  );
}

const DEP_ICONS = { mongodb: Database, postgresql: Database, redis: Server, supabase: Database };
const STATUS_COLORS = { ok: '#10b981', error: '#ef4444', not_configured: '#64748b', unknown: '#f59e0b' };

function DepStatusCard({ name, status, latency }) {
  const Icon = DEP_ICONS[name] || Server;
  const color = STATUS_COLORS[status] || STATUS_COLORS.unknown;
  return (
    <div className="flex items-center gap-3 p-3 rounded-xl transition-all duration-200 hover:bg-gray-50 bg-gray-50 border border-gray-100">
      <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${color}15` }}>
        <Icon size={14} style={{ color }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-gray-700 text-sm font-medium capitalize">{name}</p>
        <p className="text-xs" style={{ color }}>{status === 'ok' ? 'Connected' : status}</p>
      </div>
      {status === 'ok' && (
        <div className="text-right">
          <p className="text-gray-900 text-sm font-bold font-mono">{latency}ms</p>
          <div className="h-1.5 w-16 rounded-full overflow-hidden mt-1 bg-gray-100">
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
          <Layers size={14} className="text-violet-500" />
          <h3 className="text-gray-600 font-semibold text-sm">Content Pipeline</h3>
          <span className="text-xs text-gray-400">({pipe.total_topics} topics · {pipe.pages_total} pages)</span>
        </div>
        {pipe.published_today > 0 && (
          <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-600">
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
                <span className="text-xs text-gray-400">{b.label}</span>
                <span className="text-xs font-mono" style={{ color: b.color }}>{b.value} ({pct}%)</span>
              </div>
              <div className="h-1.5 rounded-full overflow-hidden bg-gray-100">
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
        <circle cx="50" cy="50" r="40" fill="none" stroke="#f3f4f6" strokeWidth="10" />
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
        <text x="50" y="50" textAnchor="middle" fontSize="17" fontWeight="bold" fill="#111827" dominantBaseline="central">{pct.toFixed(1)}%</text>
        <text x="50" y="70" textAnchor="middle" fontSize="8" fill="#9ca3af">Target: 98%</text>
      </svg>
    </div>
  );
}

const TOOLTIP_STYLE = {
  background: '#ffffff',
  border: '1px solid #e5e7eb',
  borderRadius: 12,
  color: '#374151',
  fontSize: 12,
  boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
};

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={TOOLTIP_STYLE} className="p-3">
      <p className="text-[11px] text-gray-400 mb-1">{label}</p>
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
  const [botAnalytics, setBotAnalytics] = useState(null);
  const [indexNowStats, setIndexNowStats] = useState(null);
  const [indexNowHistory, setIndexNowHistory] = useState(null);
  const [alertHistory, setAlertHistory] = useState(null);
  const [alertFilter, setAlertFilter] = useState('all');
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
        queriesRes, tokenRes, funnelRes, coverageRes, pwaRes, botRes, indexNowRes, indexNowHistRes,
        alertHistRes,
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
        axios.get(`${API_BASE}/admin/analytics/bot-traffic?days=30`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/indexnow/stats`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/indexnow/history?limit=20`, adminHdr(adminToken)),
        axios.get(`${API_BASE}/admin/alerts?limit=50`, adminHdr(adminToken)),
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
      if (botRes.status === 'fulfilled') setBotAnalytics(botRes.value.data); else { failed.push('bot-analytics'); setBotAnalytics(null); }
      if (indexNowRes.status === 'fulfilled') setIndexNowStats(indexNowRes.value.data); else { failed.push('indexnow'); setIndexNowStats(null); }
      if (indexNowHistRes.status === 'fulfilled') setIndexNowHistory(indexNowHistRes.value.data); else setIndexNowHistory(null);
      if (alertHistRes.status === 'fulfilled') setAlertHistory(alertHistRes.value.data); else { failed.push('alerts'); setAlertHistory(null); }
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
        <Loader2 size={24} className="animate-spin text-violet-500" />
        <span className="text-sm text-gray-400">Loading dashboard...</span>
      </div>
    );
  }

  const handleAcknowledgeAlert = async (alertId) => {
    try {
      await axios.patch(`${API_BASE}/admin/alerts/${alertId}/acknowledge`, {}, adminHdr(adminToken));
      setAlertHistory(prev => ({
        ...prev,
        alerts: prev.alerts.map(a => a._id === alertId ? { ...a, acknowledged: true } : a),
      }));
    } catch (e) {
      log.error('Failed to acknowledge alert', { error: e.message });
    }
  };

  const handleAcknowledgeAll = async () => {
    try {
      await axios.patch(`${API_BASE}/admin/alerts/acknowledge-all`, {}, adminHdr(adminToken));
      setAlertHistory(prev => ({
        ...prev,
        alerts: prev.alerts.map(a => ({ ...a, acknowledged: true })),
      }));
    } catch (e) {
      log.error('Failed to acknowledge all alerts', { error: e.message });
    }
  };

  const vs = data?.visitor_stats || {};
  const recentEvents = data?.recent_events || [];
  const deps = metrics?.dependencies || {};

  const ragAlert = failedSections.includes('rag') ? 'yellow' : (ragAccuracy?.alert || 'green');
  const fallbackAlert = failedSections.includes('fallbacks') ? 'yellow' : (chatFallbacks?.alert || 'green');
  const latencyAlert = failedSections.includes('latency') ? 'yellow' : (latency?.alert || 'green');
  const vectorAlert = failedSections.includes('vector') ? 'yellow'
    : (vectorStats?.overall_coverage_pct ?? 100) < 90 ? 'yellow' : 'green';
  const botAlert = failedSections.includes('bot-analytics') ? 'yellow'
    : (botAnalytics?.alert_level || 'green');

  const hasRagIssue = ragAlert === 'red' || latencyAlert === 'red';

  const quickActions = [
    { id: 'users',     label: 'View Users',     icon: Users,    color: '#7c3aed' },
    { id: 'blog',      label: 'Blog Publisher', icon: PenTool,  color: '#3b82f6' },
    { id: 'analytics', label: 'Analytics',       icon: BarChart2, color: '#10b981' },
    { id: 'monetization', label: 'Monetization', icon: Crown,    color: '#f59e0b' },
  ];

  return (
    <div className="p-4 md:p-6 space-y-5 max-w-[1400px]">

      {failedSections.length > 0 && (
        <div className="flex items-center gap-3 p-3 rounded-xl bg-amber-50 border border-amber-200">
          <AlertTriangle size={14} className="text-amber-500 flex-shrink-0" />
          <p className="text-xs text-amber-700 flex-1">
            Some widgets failed to load ({failedSections.join(', ')}). Metrics may be stale.
          </p>
          <button onClick={() => load(true)} className="text-xs text-amber-700 hover:text-amber-900 px-2.5 py-1 rounded-lg transition-colors bg-amber-100">
            Retry
          </button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-gray-900 font-semibold text-lg tracking-tight">Overview</h2>
          {lastRefresh && (
            <p className="text-gray-400 text-xs mt-0.5">
              Updated {formatTimeAgo(lastRefresh.toISOString())} · auto-refreshes every 60s
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          {metrics?.response_time_ms && (
            <span className="text-xs text-gray-400 flex items-center gap-1">
              <Clock size={10} /> API: {metrics.response_time_ms}ms
            </span>
          )}
          <button
            onClick={() => load(true)}
            disabled={refreshing}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-medium text-gray-500 hover:text-gray-700 transition-all disabled:opacity-40 bg-white border border-gray-200 shadow-sm"
          >
            <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {Object.keys(deps).length > 0 && (
        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <Wifi size={14} className="text-violet-500" />
            <h3 className="text-gray-500 text-sm font-semibold">System Health</h3>
            <div className="ml-auto flex items-center gap-1.5">
              {Object.values(deps).every(d => d.status === 'ok') && !hasRagIssue ? (
                <>
                  <CheckCircle size={12} className="text-emerald-500" />
                  <span className="text-emerald-600 text-xs font-medium">All Systems Operational</span>
                </>
              ) : (
                <>
                  <AlertCircle size={12} className="text-amber-500" />
                  <span className="text-amber-600 text-xs font-medium">
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
        <div className="flex items-center gap-3 p-3 rounded-xl flex-wrap bg-emerald-50 border border-emerald-200">
          <span className="text-xs text-emerald-700 font-bold">Data Recovered</span>
          <span className="text-xs text-gray-500">
            Conversations since <strong className="text-gray-700">{data.conversation_date_range.oldest}</strong>
            {' · '}PG: <strong className="text-blue-600">{data.pg_conversations}</strong>
            {' + '}Supabase: <strong className="text-emerald-600">{data.supa_conversations}</strong>
            {' = '}<strong className="text-gray-700">{data.total_conversations}</strong> total
            {' · '}<strong className="text-gray-700">{data.conversations_with_messages}</strong> with messages
            {' · '}<strong className="text-gray-700">{data.unique_chatters}</strong> unique chatters
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

      <GlassCard className="p-5">
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          <Globe size={14} style={{ color: '#0891b2' }} />
          <span className="text-xs font-bold text-cyan-700">Traffic Sources</span>
          <span className="ml-auto text-[10px] text-gray-400 italic">
            Server-side = Cloudflare-equivalent · JS-tracked = engaged users · Bot = crawlers
          </span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-3">
          <div className="rounded-xl p-3 bg-emerald-50 border border-emerald-200">
            <div className="flex items-center gap-1.5 mb-2">
              <Server size={11} style={{ color: '#10b981' }} />
              <span className="text-[10px] font-bold text-emerald-700 uppercase tracking-wider">All Traffic</span>
              <span className="text-[9px] text-gray-400 ml-auto">server-side</span>
            </div>
            <div className="flex gap-4">
              <div>
                <p className="text-gray-900 font-bold text-lg">{(vs.server_side?.total_unique ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-gray-400">Unique</p>
              </div>
              <div>
                <p className="text-gray-900 font-bold text-lg">{(vs.server_side?.unique_today ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-gray-400">Today</p>
              </div>
              <div>
                <p className="text-gray-500 font-bold text-lg">{(vs.server_side?.total_hits ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-gray-400">Hits</p>
              </div>
            </div>
          </div>

          <div className="rounded-xl p-3 bg-violet-50 border border-violet-200">
            <div className="flex items-center gap-1.5 mb-2">
              <Eye size={11} style={{ color: '#8b5cf6' }} />
              <span className="text-[10px] font-bold text-violet-700 uppercase tracking-wider">Engaged Visitors</span>
              <span className="text-[9px] text-gray-400 ml-auto">JS-tracked</span>
            </div>
            <div className="flex gap-4">
              <div>
                <p className="text-gray-900 font-bold text-lg">{(vs.total_visitors ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-gray-400">All-time</p>
              </div>
              <div>
                <p className="text-gray-900 font-bold text-lg">{(vs.visitors_today ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-gray-400">Today</p>
              </div>
              <div>
                <p className="text-gray-500 font-bold text-lg">{(vs.total_page_views ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-gray-400">Views</p>
              </div>
            </div>
          </div>

          <div className="rounded-xl p-3 bg-amber-50 border border-amber-200">
            <div className="flex items-center gap-1.5 mb-2">
              <Bot size={11} style={{ color: '#f59e0b' }} />
              <span className="text-[10px] font-bold text-amber-700 uppercase tracking-wider">Bot/Crawler Traffic</span>
              <span className="text-[9px] text-gray-400 ml-auto">separate</span>
            </div>
            <div className="flex gap-4">
              <div>
                <p className="text-gray-900 font-bold text-lg">{(vs.bot_traffic?.unique_total ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-gray-400">Unique bots</p>
              </div>
              <div>
                <p className="text-gray-900 font-bold text-lg">{(vs.bot_traffic?.hits_today ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-gray-400">Today</p>
              </div>
              <div>
                <p className="text-gray-500 font-bold text-lg">{(vs.bot_traffic?.total_hits ?? 0).toLocaleString()}</p>
                <p className="text-[10px] text-gray-400">Total</p>
              </div>
            </div>
          </div>
        </div>

        {vs.server_side?.total_unique > 0 && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-lg flex-wrap bg-gray-50 border border-gray-100">
            <span className="text-[10px] text-gray-400 font-semibold">TRACKING FUNNEL:</span>
            <span className="text-[11px] text-emerald-600 font-bold">{(vs.server_side?.total_unique ?? 0).toLocaleString()}</span>
            <span className="text-[10px] text-gray-400">server</span>
            <span className="text-[10px] text-gray-300">&rarr;</span>
            <span className="text-[11px] text-violet-600 font-bold">{(vs.total_visitors ?? 0).toLocaleString()}</span>
            <span className="text-[10px] text-gray-400">JS-tracked</span>
            <span className="text-[10px] text-gray-300">&rarr;</span>
            <span className="text-[11px] text-amber-600 font-bold">{(vs.bot_traffic?.total_hits ?? 0).toLocaleString()}</span>
            <span className="text-[10px] text-gray-400">bot hits</span>
            {vs.total_visitors > 0 && vs.server_side?.total_unique > 0 && (
              <span className="ml-auto text-[10px] text-gray-400">
                JS capture rate: {Math.round((vs.total_visitors / vs.server_side.total_unique) * 100)}%
              </span>
            )}
          </div>
        )}

        {vs.bot_traffic?.top_bots?.length > 0 && (
          <div className="mt-3">
            <div className="text-[10px] text-gray-400 font-semibold mb-1.5 uppercase tracking-wider">Top Crawlers</div>
            <div className="flex flex-wrap gap-1.5">
              {vs.bot_traffic.top_bots.slice(0, 8).map((b, i) => (
                <span key={i} className="text-[10px] px-2 py-0.5 rounded-md text-amber-700 bg-amber-50 border border-amber-200">
                  {b.bot}: {b.hits}
                </span>
              ))}
            </div>
          </div>
        )}
      </GlassCard>

      {botAnalytics && (
        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <Bot size={16} className="text-amber-500" />
            <h3 className="text-gray-700 font-semibold">Bot Traffic Analytics</h3>
            <div className="ml-auto flex items-center gap-2">
              <AlertBadge alert={botAlert} />
              <span className="text-[10px] text-gray-400">{botAnalytics.period_days}-day window</span>
            </div>
          </div>

          {botAnalytics.alerts?.length > 0 && (
            <div className="mb-4 space-y-1.5">
              {botAnalytics.alerts.map((a, i) => (
                <div
                  key={i}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs"
                  style={{
                    background: a.severity === 'red' ? '#fef2f2' : '#fffbeb',
                    border: `1px solid ${a.severity === 'red' ? '#fecaca' : '#fde68a'}`,
                    color: a.severity === 'red' ? '#991b1b' : '#92400e',
                  }}
                >
                  {a.severity === 'red' ? <AlertCircle size={13} /> : <AlertTriangle size={13} />}
                  <span>{a.message}</span>
                </div>
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <div className="rounded-lg p-3 bg-blue-50 border border-blue-200 text-center">
              <p className="text-blue-700 font-bold text-lg">{(botAnalytics.bot_vs_human?.total_bot ?? 0).toLocaleString()}</p>
              <p className="text-[10px] text-gray-500">Bot Hits</p>
            </div>
            <div className="rounded-lg p-3 bg-green-50 border border-green-200 text-center">
              <p className="text-green-700 font-bold text-lg">{(botAnalytics.bot_vs_human?.total_human ?? 0).toLocaleString()}</p>
              <p className="text-[10px] text-gray-500">Human Hits</p>
            </div>
            <div className={`rounded-lg p-3 text-center ${
              botAlert === 'red' ? 'bg-red-50 border border-red-300' :
              botAlert === 'yellow' ? 'bg-yellow-50 border border-yellow-300' :
              'bg-violet-50 border border-violet-200'
            }`}>
              <p className={`font-bold text-lg ${
                botAlert === 'red' ? 'text-red-700' :
                botAlert === 'yellow' ? 'text-yellow-700' :
                'text-violet-700'
              }`}>{botAnalytics.crawl_coverage ?? 0}%</p>
              <p className="text-[10px] text-gray-500">Crawl Coverage</p>
            </div>
            <div className="rounded-lg p-3 bg-amber-50 border border-amber-200 text-center">
              <p className="text-amber-700 font-bold text-lg">{botAnalytics.bot_vs_human?.bot_ratio_pct ?? 0}%</p>
              <p className="text-[10px] text-gray-500">Bot Ratio</p>
            </div>
          </div>

          <div className="text-[10px] text-gray-400 mb-1">
            Crawled {(botAnalytics.pages_crawled ?? 0).toLocaleString()} of {(botAnalytics.total_sitemap_pages ?? 0).toLocaleString()} sitemap pages
          </div>

          {botAnalytics.daily_bot_hits?.length > 0 && (
            <div className="mt-4">
              <div className="text-[10px] text-gray-400 font-semibold mb-2 uppercase tracking-wider">Daily Bot vs Human Hits</div>
              <div style={{ width: '100%', height: 200 }}>
                <ResponsiveContainer>
                  <BarChart data={botAnalytics.daily_bot_hits.slice(-14)} margin={{ top: 5, right: 5, left: -15, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={v => v.slice(5)} />
                    <YAxis tick={{ fontSize: 9 }} />
                    <Tooltip contentStyle={{ fontSize: 11 }} labelFormatter={v => `Date: ${v}`} />
                    <Bar dataKey="bot_hits" fill="#f59e0b" name="Bot" radius={[2, 2, 0, 0]} />
                    <Bar dataKey="human_hits" fill="#6366f1" name="Human" radius={[2, 2, 0, 0]} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {botAnalytics.top_bots?.length > 0 && (
            <div className="mt-4">
              <div className="text-[10px] text-gray-400 font-semibold mb-2 uppercase tracking-wider">Top Bots (by hits)</div>
              <div className="space-y-1.5">
                {botAnalytics.top_bots.slice(0, 10).map((b, i) => {
                  const maxHits = botAnalytics.top_bots[0]?.hits || 1;
                  const pct = Math.round((b.hits / maxHits) * 100);
                  return (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-[10px] text-gray-600 font-medium w-28 truncate">{b.bot}</span>
                      <div className="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden">
                        <div className="h-full bg-amber-400 rounded-full" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="text-[10px] text-gray-500 w-14 text-right">{b.hits.toLocaleString()}</span>
                      <span className="text-[9px] text-gray-400 w-12 text-right">{b.unique_ips} IPs</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {botAnalytics.per_bot_pages?.length > 0 && (
            <div className="mt-4">
              <div className="text-[10px] text-gray-400 font-semibold mb-2 uppercase tracking-wider">Pages Fetched per Bot</div>
              <div className="flex flex-wrap gap-1.5">
                {botAnalytics.per_bot_pages.slice(0, 10).map((b, i) => (
                  <span key={i} className="text-[10px] px-2 py-0.5 rounded-md text-violet-700 bg-violet-50 border border-violet-200">
                    {b.bot}: {b.pages_fetched} pages
                  </span>
                ))}
              </div>
            </div>
          )}
        </GlassCard>
      )}

      {alertHistory && (
        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-4 flex-wrap">
            <AlertTriangle size={16} className="text-orange-500" />
            <h3 className="text-gray-700 font-semibold">Alert History</h3>
            {alertHistory.alerts?.some(a => !a.acknowledged) && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-semibold">
                {alertHistory.alerts.filter(a => !a.acknowledged).length} unacknowledged
              </span>
            )}
            <div className="ml-auto flex items-center gap-2">
              <select
                className="text-[10px] border border-gray-200 rounded-md px-2 py-1 bg-white text-gray-600"
                value={alertFilter}
                onChange={e => setAlertFilter(e.target.value)}
              >
                <option value="all">All alerts</option>
                <option value="unacknowledged">Unacknowledged</option>
                <option value="acknowledged">Acknowledged</option>
              </select>
              {alertHistory.alerts?.some(a => !a.acknowledged) && (
                <button
                  onClick={handleAcknowledgeAll}
                  className="text-[10px] px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 transition-colors font-medium"
                >
                  Acknowledge All
                </button>
              )}
            </div>
          </div>

          {(!alertHistory.alerts || alertHistory.alerts.length === 0) && (
            <p className="text-center text-[11px] text-gray-400 py-6">No alerts have been triggered yet. Alerts appear here when system thresholds are exceeded.</p>
          )}

          {alertHistory.alerts?.length > 0 && (
          <div className="space-y-2 max-h-[400px] overflow-y-auto">
            {alertHistory.alerts
              .filter(a => {
                if (alertFilter === 'unacknowledged') return !a.acknowledged;
                if (alertFilter === 'acknowledged') return a.acknowledged;
                return true;
              })
              .map((alert) => {
                const severityMap = {
                  high_error_rate: 'red',
                  high_latency: 'yellow',
                  spoofed_bot_surge: 'red',
                  high_fallback_rate: 'yellow',
                };
                const severity = severityMap[alert.type] || 'yellow';
                const isRed = severity === 'red';
                return (
                  <div
                    key={alert._id}
                    className={`flex items-start gap-3 px-3 py-2.5 rounded-lg border text-xs transition-all ${
                      alert.acknowledged
                        ? 'bg-gray-50 border-gray-200 opacity-60'
                        : isRed
                          ? 'bg-red-50 border-red-200'
                          : 'bg-amber-50 border-amber-200'
                    }`}
                  >
                    <div className="mt-0.5 flex-shrink-0">
                      {isRed
                        ? <AlertCircle size={14} className="text-red-500" />
                        : <AlertTriangle size={14} className="text-amber-500" />
                      }
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-0.5">
                        <span className={`font-semibold ${alert.acknowledged ? 'text-gray-500' : isRed ? 'text-red-800' : 'text-amber-800'}`}>
                          {alert.title}
                        </span>
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
                          isRed ? 'bg-red-100 text-red-600' : 'bg-amber-100 text-amber-600'
                        }`}>
                          {isRed ? 'High' : 'Medium'}
                        </span>
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 font-medium">
                          {alert.type.replace(/_/g, ' ')}
                        </span>
                        {alert.acknowledged && (
                          <CheckCircle size={12} className="text-emerald-500" />
                        )}
                      </div>
                      <p className={`text-[11px] ${alert.acknowledged ? 'text-gray-400' : 'text-gray-600'} break-words`}>
                        {alert.body}
                      </p>
                      <div className="flex items-center gap-3 mt-1.5">
                        <span className="text-[10px] text-gray-400 flex items-center gap-1">
                          <Clock size={10} />
                          {alert.fired_at ? formatTimeAgo(alert.fired_at) : 'unknown'}
                        </span>
                        {alert.fired_at && (
                          <span className="text-[9px] text-gray-300">
                            {new Date(alert.fired_at).toLocaleString()}
                          </span>
                        )}
                      </div>
                    </div>
                    {!alert.acknowledged && (
                      <button
                        onClick={() => handleAcknowledgeAlert(alert._id)}
                        className="flex-shrink-0 text-[10px] px-2 py-1 rounded-md bg-white border border-gray-200 text-gray-500 hover:bg-emerald-50 hover:text-emerald-600 hover:border-emerald-200 transition-colors"
                        title="Acknowledge"
                      >
                        <CheckCircle size={12} />
                      </button>
                    )}
                  </div>
                );
              })}
          </div>

          {alertHistory.alerts.filter(a => {
            if (alertFilter === 'unacknowledged') return !a.acknowledged;
            if (alertFilter === 'acknowledged') return a.acknowledged;
            return true;
          }).length === 0 && (
            <p className="text-center text-[11px] text-gray-400 py-4">No alerts matching this filter</p>
          )}
          )}
        </GlassCard>
      )}

      {indexNowStats && (
        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <Search size={16} className="text-green-500" />
            <h3 className="text-gray-700 font-semibold">IndexNow Push Status</h3>
            <span className="ml-auto text-[10px] text-gray-400">auto-push active</span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <div className="rounded-lg p-3 bg-green-50 border border-green-200 text-center">
              <p className="text-green-700 font-bold text-lg">{(indexNowStats.total_urls_pushed ?? 0).toLocaleString()}</p>
              <p className="text-[10px] text-gray-500">Total URLs Pushed</p>
            </div>
            <div className="rounded-lg p-3 bg-blue-50 border border-blue-200 text-center">
              <p className="text-blue-700 font-bold text-lg">{(indexNowStats.total_pushes ?? 0).toLocaleString()}</p>
              <p className="text-[10px] text-gray-500">Total Pushes</p>
            </div>
            <div className="rounded-lg p-3 bg-violet-50 border border-violet-200 text-center">
              <p className="text-violet-700 font-bold text-lg">{(indexNowStats.today_urls_pushed ?? 0).toLocaleString()}</p>
              <p className="text-[10px] text-gray-500">URLs Today</p>
            </div>
            <div className="rounded-lg p-3 bg-amber-50 border border-amber-200 text-center">
              <p className="text-amber-700 font-bold text-lg">{indexNowStats.pending ?? 0}</p>
              <p className="text-[10px] text-gray-500">Pending</p>
            </div>
          </div>

          {indexNowStats.last_push && (
            <div className="text-[10px] text-gray-400 mb-3">
              Last push: {new Date(indexNowStats.last_push.pushed_at).toLocaleString()} ({indexNowStats.last_push.url_count} URLs, source: {indexNowStats.last_push.source})
            </div>
          )}

          {indexNowStats.by_source?.length > 0 && (
            <div>
              <div className="text-[10px] text-gray-400 font-semibold mb-1.5 uppercase tracking-wider">Push Sources</div>
              <div className="flex flex-wrap gap-1.5">
                {indexNowStats.by_source.map((s, i) => (
                  <span key={i} className="text-[10px] px-2 py-0.5 rounded-md text-green-700 bg-green-50 border border-green-200">
                    {s.source}: {s.push_count} pushes · {s.url_count} URLs
                  </span>
                ))}
              </div>
            </div>
          )}

          {indexNowHistory?.pushes?.length > 0 && (
            <div className="mt-4">
              <div className="text-[10px] text-gray-400 font-semibold mb-2 uppercase tracking-wider">Recent Push History</div>
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {indexNowHistory.pushes.slice(0, 15).map((push, i) => {
                  const raw = push.results || {};
                  const endpointEntries = raw.chunks
                    ? raw.chunks.flatMap(c => Object.entries(c.endpoints || {}))
                    : Object.entries(raw);
                  const hasError = endpointEntries.some(([, v]) => typeof v === 'string');
                  const allOk = endpointEntries.length > 0 && !hasError && endpointEntries.every(([, v]) => v >= 200 && v < 300);
                  return (
                    <div key={push.id || i} className="flex items-center gap-2 text-[10px] py-1.5 px-2 rounded-lg bg-gray-50 border border-gray-100">
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${allOk ? 'bg-green-400' : hasError ? 'bg-red-400' : 'bg-amber-400'}`} />
                      <span className="text-gray-500 w-32 flex-shrink-0">{new Date(push.pushed_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                      <span className="text-gray-700 font-medium">{push.url_count} URLs</span>
                      <span className="text-gray-400 px-1">·</span>
                      <span className="text-gray-500">{push.source}</span>
                      <span className="ml-auto flex gap-1">
                        {endpointEntries.map(([ep, code], j) => {
                          const host = ep.replace(/https?:\/\//, '').split('/')[0];
                          const ok = typeof code === 'number' && code >= 200 && code < 300;
                          return (
                            <span key={j} className={`px-1 py-0.5 rounded text-[9px] ${ok ? 'text-green-600 bg-green-50' : 'text-red-600 bg-red-50'}`}>
                              {host}: {code}
                            </span>
                          );
                        })}
                      </span>
                    </div>
                  );
                })}
              </div>
              {indexNowHistory.total > 15 && (
                <p className="text-[9px] text-gray-400 mt-1.5 text-center">Showing 15 of {indexNowHistory.total} pushes</p>
              )}
            </div>
          )}
        </GlassCard>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Page Views Today" value={vs.page_views_today ?? 0} icon={Eye}      color="#ec4899" pulse />
        <StatCard label="Total Page Views" value={vs?.total_page_views ?? 0} icon={BarChart2} color="#84cc16"
          subLabel="Today" subValue={vs?.page_views_today ?? 0} />
        <StatCard label="Bounce Rate"  value={vs.bounce_rate != null ? `${vs.bounce_rate}%` : '—'} icon={TrendingUp} color="#f59e0b" />
        <StatCard label="Avg Session"  value={vs.avg_session_duration != null ? `${vs.avg_session_duration}s` : '—'} icon={Clock} color="#a78bfa" />
      </div>

      <GlassCard className="p-5">
        <div className="flex items-center gap-2 mb-5">
          <ShieldCheck size={16} className="text-violet-500" />
          <h3 className="text-gray-700 font-semibold">AI Health</h3>
          <div className="ml-auto flex items-center gap-2">
            <AlertBadge alert={ragAlert} />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="rounded-xl p-4 flex flex-col items-center gap-2 bg-gray-50 border border-gray-100">
            <div className="flex items-center justify-between w-full mb-1">
              <span className="text-gray-500 text-xs font-medium flex items-center gap-1">
                <Target size={11} /> RAG Accuracy
              </span>
              <AlertBadge alert={ragAlert} />
            </div>
            <RagAccuracyGauge accuracy={ragAccuracy?.accuracy_pct ?? 98} />
            <p className="text-xs text-gray-400 text-center">
              {ragAccuracy?.has_data
                ? `${ragAccuracy.answered_queries} / ${ragAccuracy.total_queries} queries answered`
                : 'No queries yet — showing default'}
            </p>
          </div>

          <div className="rounded-xl p-4 bg-gray-50 border border-gray-100">
            <div className="flex items-center justify-between mb-3">
              <span className="text-gray-500 text-xs font-medium flex items-center gap-1">
                <Activity size={11} /> Daily Fallback Rate
              </span>
              <AlertBadge alert={fallbackAlert} />
            </div>
            {chatFallbacks?.has_data && chatFallbacks.daily.length > 0 ? (
              <ResponsiveContainer width="100%" height={90}>
                <LineChart data={chatFallbacks.daily}>
                  <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#9ca3af' }} tickFormatter={d => d.slice(5)} />
                  <YAxis tick={{ fontSize: 9, fill: '#9ca3af' }} domain={[0, 'auto']} />
                  <Tooltip content={<ChartTooltip />} />
                  <ReferenceLine y={5} stroke="#ef4444" strokeDasharray="3 3" label={{ value: '5% max', fill: '#ef4444', fontSize: 9 }} />
                  <Line type="monotone" dataKey="fallback_rate" stroke="#f59e0b" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : failedSections.includes('fallbacks') ? (
              <div className="flex flex-col items-center justify-center h-[90px] text-gray-400 text-xs gap-1">
                <Activity size={20} className="opacity-30" />
                <span className="text-amber-600">Could not load fallback data</span>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-[90px] text-gray-400 text-xs gap-1">
                <Activity size={20} className="opacity-30" />
                <span>No query data yet</span>
                <span className="text-emerald-600 text-xs font-medium">
                  {chatFallbacks?.fallback_rate_pct ?? 0}% fallback rate
                </span>
              </div>
            )}
            <p className="text-xs text-gray-400 mt-1">Target: &lt;5% fallback rate</p>
          </div>

          <div className="rounded-xl p-4 bg-gray-50 border border-gray-100">
            <div className="flex items-center justify-between mb-3">
              <span className="text-gray-500 text-xs font-medium flex items-center gap-1">
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
                      <span className="text-xs text-gray-400">{label}</span>
                      <span className="text-xs font-mono" style={{ color }}>{pct}%</span>
                    </div>
                    <div className="h-1.5 rounded-full overflow-hidden bg-gray-200">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${pct}%`, background: pct >= 90 ? color : '#f59e0b' }}
                      />
                    </div>
                  </div>
                ))}
                <p className="text-xs text-gray-400 pt-1">
                  {vectorStats.embedded ?? 0} / {vectorStats.total ?? 0} items embedded
                </p>
                {(vectorStats.embedded ?? 0) === 0 && (vectorStats.total ?? 0) > 0 && (
                  <p className="text-xs text-amber-600 mt-1">
                    Add VERTEX_SERVICE_ACCOUNT to enable embedding
                  </p>
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-20 text-gray-400 text-xs">
                No vector data
              </div>
            )}
            <p className="text-xs text-gray-400 mt-1">Target: &ge;90%</p>
          </div>
        </div>
      </GlassCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <GlassCard className="p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Clock size={14} className="text-violet-500" />
              <h3 className="text-gray-600 font-semibold text-sm">Query Latency P95</h3>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400">P95: <span className="text-gray-700 font-medium">{latency?.p95_ms ?? 0}ms</span></span>
              <AlertBadge alert={latencyAlert} />
            </div>
          </div>
          {latency?.has_data && latency.daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={110}>
              <LineChart data={latency.daily}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#9ca3af' }} tickFormatter={d => d.slice(5)} />
                <YAxis tick={{ fontSize: 9, fill: '#9ca3af' }} domain={[0, 'auto']} />
                <Tooltip content={<ChartTooltip />} />
                <ReferenceLine y={2000} stroke="#ef4444" strokeDasharray="4 4" label={{ value: '2s target', fill: '#ef4444', fontSize: 9 }} />
                <Line type="monotone" dataKey="p95_ms" stroke="#7c3aed" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex flex-col items-center justify-center h-[110px] text-gray-400 text-xs gap-1">
              <Cpu size={20} className="opacity-30" />
              <span>No latency data yet</span>
              <span className="text-xs text-gray-300">Data recorded after first chat</span>
            </div>
          )}
          <p className="text-xs text-gray-400 mt-1">Target: P95 &lt;2 s · Avg: {latency?.avg_ms ?? 0}ms</p>
        </GlassCard>

        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <Search size={14} className="text-violet-500" />
            <h3 className="text-gray-600 font-semibold text-sm">Top Queries</h3>
            <span className="text-xs text-gray-400">content gap signal</span>
          </div>
          {topQueries?.has_data && topQueries.top_queries.length > 0 ? (
            <div className="space-y-1.5 max-h-[150px] overflow-y-auto pr-1">
              {topQueries.top_queries.map((q, i) => {
                const maxCount = topQueries.top_queries[0]?.count || 1;
                const pct = Math.round((q.count / maxCount) * 100);
                return (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-gray-300 text-xs w-4 flex-shrink-0 font-mono">{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex justify-between mb-0.5">
                        <span className="text-xs text-gray-600 truncate">{q.query}</span>
                        <span className="text-xs text-violet-600 font-mono ml-2 flex-shrink-0">{q.count}</span>
                      </div>
                      <div className="h-1 rounded-full overflow-hidden bg-gray-100">
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: 'linear-gradient(90deg, #7c3aed, #a78bfa)' }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-[100px] text-gray-400 text-xs gap-1">
              <Search size={20} className="opacity-30" />
              <span>No query data yet</span>
              <span className="text-xs text-gray-300">Populates after user chats</span>
            </div>
          )}
          <p className="text-xs text-gray-400 mt-2">
            {topQueries?.total_unique ?? 0} unique queries in last 7 days
          </p>
        </GlassCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <Cpu size={14} className="text-violet-500" />
            <h3 className="text-gray-600 font-semibold text-sm">Token Spend</h3>
          </div>
          {tokenSpend?.has_data && tokenSpend.daily.length > 0 ? (
            <ResponsiveContainer width="100%" height={130}>
              <BarChart data={tokenSpend.daily} barSize={8}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                <XAxis dataKey="date" tick={{ fontSize: 8, fill: '#9ca3af' }} tickFormatter={d => d.slice(5)} />
                <YAxis tick={{ fontSize: 8, fill: '#9ca3af' }} />
                <Tooltip content={<ChartTooltip />} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                <Bar dataKey="gemini_tokens" fill="#8b5cf6" name="Gemini" radius={[3,3,0,0]} />
                <Bar dataKey="xai_tokens" fill="#06b6d4" name="xAI" radius={[3,3,0,0]} />
                <Bar dataKey="groq_tokens" fill="#10b981" name="Groq" radius={[3,3,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex flex-col items-center justify-center h-[130px] text-gray-400 text-xs gap-1">
              <BarChart2 size={20} className="opacity-30" />
              <span>No token data yet</span>
              <span className="text-xs text-gray-300">Grows with AI usage</span>
            </div>
          )}
          {tokenSpend && Object.keys(tokenSpend.totals || {}).length > 0 && (
            <div className="flex gap-3 mt-2 flex-wrap">
              {Object.entries(tokenSpend.totals).map(([p, v]) => (
                <span key={p} className="text-xs text-gray-400">
                  {p}: <span className="text-gray-600">{(v.tokens || 0).toLocaleString()}</span>
                </span>
              ))}
            </div>
          )}
        </GlassCard>

        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={14} className="text-violet-500" />
            <h3 className="text-gray-600 font-semibold text-sm">Conversion Funnel</h3>
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
                      <span className="text-xs text-gray-500">{step.stage}</span>
                      <span className="text-xs font-mono text-gray-700">{step.count.toLocaleString()}</span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden bg-gray-100">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${pct}%`, background: colors[i] || '#7c3aed' }}
                      />
                    </div>
                  </div>
                );
              })}
              <div className="pt-2 border-t border-gray-100 grid grid-cols-2 gap-2">
                <div className="text-center">
                  <p className="text-lg font-bold text-emerald-600">{funnel.free_to_paid_rate}%</p>
                  <p className="text-xs text-gray-400">Free→Paid</p>
                </div>
                <div className="text-center">
                  <p className="text-lg font-bold text-amber-600">{funnel.starter_to_pro_rate}%</p>
                  <p className="text-xs text-gray-400">Starter→Pro</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center h-[130px] text-gray-400 text-xs">
              Loading funnel…
            </div>
          )}
        </GlassCard>

        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <FileCheck size={14} className="text-violet-500" />
            <h3 className="text-gray-600 font-semibold text-sm">Assam Board Coverage</h3>
            <span className="text-xs text-gray-400">chapter × subject</span>
            {coverage?.has_data && coverage.subjects.length > 0 && (
              <span className="ml-auto text-xs text-gray-400">{coverage.subjects.length} subjects</span>
            )}
          </div>
          {coverage?.has_data && coverage.subjects.length > 0 ? (
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
              {coverage.subjects.map(sub => (
                <div key={sub.subject_id}>
                  <div className="flex justify-between mb-1">
                    <span className="text-xs text-gray-600 truncate flex items-center gap-1.5">
                      {sub.subject_name}
                      {(sub.class_name || sub.stream_name) && (
                        <span className="text-[10px] text-gray-400 font-normal shrink-0">
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
                            : '#f3f4f6',
                          border: '1px solid #e5e7eb',
                        }}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-[130px] text-gray-400 text-xs gap-1">
              <BookOpen size={20} className="opacity-30" />
              <span>No subjects found</span>
              <span className="text-xs text-gray-300">Add subjects to see coverage</span>
            </div>
          )}
          <div className="flex items-center gap-3 mt-2 pt-2 border-t border-gray-100">
            {[['#10b981', 'Full'], ['#f59e0b', 'Partial'], ['#f3f4f6', 'None']].map(([c, label]) => (
              <div key={label} className="flex items-center gap-1">
                <div className="w-2.5 h-2.5 rounded-sm" style={{ background: c, border: '1px solid #e5e7eb' }} />
                <span className="text-xs text-gray-400">{label}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>

      {data?.plan_distribution && (
        <GlassCard className="p-5">
          <h3 className="text-gray-500 text-sm font-semibold mb-4">Plan Distribution</h3>
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
                <div key={key} className="text-center p-4 rounded-xl bg-gray-50 border border-gray-100">
                  <p className="text-2xl font-bold" style={{ color }}>{count}</p>
                  <p className="text-gray-500 text-sm">{label}</p>
                  <div className="mt-2 h-1 rounded-full overflow-hidden bg-gray-200">
                    <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
                  </div>
                  <p className="text-xs text-gray-400 mt-1">{pct}%</p>
                </div>
              );
            })}
          </div>
        </GlassCard>
      )}

      {pwaStats && (
        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <Smartphone size={14} className="text-violet-500" />
            <h3 className="text-gray-600 font-semibold text-sm">PWA App Downloads</h3>
            {pwaStats.installs_today > 0 && (
              <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-600">
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
              <div key={item.label} className="rounded-xl p-3 text-center bg-gray-50 border border-gray-100">
                <p className="text-xl font-bold" style={{ color: item.color }}>{item.value}</p>
                <p className="text-xs text-gray-400 mt-0.5">{item.label}</p>
              </div>
            ))}
          </div>

          {pwaStats.daily_installs?.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-gray-400 font-semibold uppercase tracking-wider">Daily Installs (14 days)</span>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-sm" style={{ background: '#8b5cf6' }} />
                    <span className="text-[10px] text-gray-400">Installs</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 rounded-sm" style={{ background: 'rgba(139,92,246,0.25)' }} />
                    <span className="text-[10px] text-gray-400">Prompts</span>
                  </div>
                </div>
              </div>
              <ResponsiveContainer width="100%" height={100}>
                <BarChart data={pwaStats.daily_installs} barSize={10}>
                  <XAxis dataKey="date" tick={{ fontSize: 8, fill: '#9ca3af' }} tickFormatter={d => d.slice(5)} />
                  <YAxis tick={{ fontSize: 8, fill: '#9ca3af' }} allowDecimals={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar dataKey="prompts" fill="rgba(139,92,246,0.25)" name="Prompts" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="installs" fill="#8b5cf6" name="Installs" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="flex items-center gap-4 mt-3 pt-3 border-t border-gray-100 text-xs text-gray-400">
            <span>Dismissed: <span className="text-gray-600 font-medium">{pwaStats.dismissed ?? 0}</span></span>
            <span>Rejected: <span className="text-gray-600 font-medium">{pwaStats.rejected ?? 0}</span></span>
          </div>
        </GlassCard>
      )}

      <PipelineWidget token={adminToken} />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {quickActions.map((action) => (
          <button
            key={action.id}
            onClick={() => onNavigate?.(action.id)}
            className="flex items-center justify-between p-4 rounded-2xl transition-all duration-300 group hover:shadow-md bg-white border border-gray-200 shadow-sm"
            data-testid={`quick-action-${action.id}`}
          >
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: `${action.color}15` }}>
                <action.icon size={15} style={{ color: action.color }} />
              </div>
              <span className="text-sm font-medium text-gray-700 group-hover:text-gray-900 transition-colors">{action.label}</span>
            </div>
            <ArrowRight size={14} className="text-gray-300 group-hover:text-gray-500 transition-colors" />
          </button>
        ))}
      </div>

      {vs.daily_visitors?.length > 0 && (
        <GlassCard className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-gray-500 text-sm font-semibold">Visitor Trend — Last 7 Days</h3>
            <span className="text-xs text-gray-400">Unique visitors per day</span>
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
                        : '#e5e7eb',
                      minHeight: 4,
                    }}
                    title={`${d.date}: ${d.visitors} visitors, ${d.page_views} views`}
                  />
                  <span className="text-[10px] text-gray-400 whitespace-nowrap">
                    {d.date.slice(5)}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="flex gap-4 mt-3">
            {vs.daily_visitors.slice(-1).map(d => (
              <div key="today-summary" className="flex gap-4 text-xs text-gray-400">
                <span>Today: <span className="text-violet-600 font-medium">{d.visitors} visitors</span></span>
                <span>·</span>
                <span><span className="text-gray-600 font-medium">{d.page_views}</span> page views</span>
              </div>
            ))}
          </div>
        </GlassCard>
      )}

      <GlassCard className="p-5" data-testid="recent-activity">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Activity size={16} className="text-violet-500" />
            <h3 className="text-gray-700 font-semibold">Recent Activity</h3>
            <span className="flex h-2 w-2 relative">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
            </span>
          </div>
          <button
            onClick={() => onNavigate?.('activitylog')}
            className="text-xs text-violet-600 hover:text-violet-700 transition-colors"
          >
            View all logs →
          </button>
        </div>

        {recentEvents.length === 0 ? (
          <div className="text-center py-8">
            <Activity size={28} className="text-gray-200 mx-auto mb-3" />
            <p className="text-gray-400 text-sm">No activity yet — events will appear here in real time</p>
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
