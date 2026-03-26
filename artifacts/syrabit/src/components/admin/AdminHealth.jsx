import { useState, useEffect, useCallback } from 'react';
import { Database, Zap, CreditCard, RefreshCw, ShieldCheck, AlertTriangle, Wifi, Copy, Check, Users, Activity, MessageSquare, TrendingUp } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import axios from 'axios';

const API_BASE = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

const adminHeaders = (token) => {
  const isRealJwt = token && typeof token === 'string' && token.split('.').length === 3;
  return isRealJwt ? { Authorization: `Bearer ${token}` } : {};
};

function LatencyBadge({ ms }) {
  if (!ms && ms !== 0) return <span className="text-xs text-white/30">—</span>;
  const color = ms < 200 ? 'text-emerald-400' : ms < 600 ? 'text-amber-400' : 'text-red-400';
  return <span className={`text-xs font-mono ${color}`}>{ms}ms</span>;
}

function PeakBadge({ label, value, color = 'violet' }) {
  const colors = {
    violet: 'bg-violet-500/10 text-violet-400 border-violet-500/20',
    emerald: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    amber: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    blue: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  };
  return (
    <div className={`rounded-xl border px-4 py-3 ${colors[color]}`} style={{ background: 'rgba(255,255,255,0.02)' }}>
      <p className="text-[10px] uppercase tracking-wider opacity-60 mb-1">{label}</p>
      <p className="text-2xl font-bold font-mono" data-testid={`peak-${label.replace(/\s+/g, '-').toLowerCase()}`}>{value}</p>
    </div>
  );
}

const TOOLTIP_STYLE = { background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', color: '#e2e8f0', fontSize: 12 };

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={TOOLTIP_STYLE} className="p-3 shadow-xl">
      <p className="text-xs text-white/40 mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-xs" style={{ color: p.color }}>
          {p.name}: <span className="font-mono font-bold">{p.value}</span>
        </p>
      ))}
    </div>
  );
}

export default function AdminHealth({ adminToken }) {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [metricsData, setMetricsData] = useState(null);
  const [metricsLoading, setMetricsLoading] = useState(true);
  const [timeRange, setTimeRange] = useState(60);

  const healthUrl = `${import.meta.env.VITE_BACKEND_URL || ''}/health`;

  const loadHealth = () => {
    setLoading(true);
    axios.get(`${API_BASE.replace('/api','')}/api/health`)
      .then((r) => setHealth(r.data))
      .catch(() => setHealth({ status: 'error', dependencies: {} }))
      .finally(() => setLoading(false));
  };

  const loadMetrics = useCallback(() => {
    setMetricsLoading(true);
    axios.get(`${API_BASE}/metrics/history?minutes=${timeRange}`, {
      headers: adminHeaders(adminToken),
      withCredentials: true,
    })
      .then((r) => setMetricsData(r.data))
      .catch(() => setMetricsData(null))
      .finally(() => setMetricsLoading(false));
  }, [adminToken, timeRange]);

  useEffect(() => { loadHealth(); }, []);
  useEffect(() => { loadMetrics(); }, [loadMetrics]);

  useEffect(() => {
    const interval = setInterval(loadMetrics, 60000);
    return () => clearInterval(interval);
  }, [loadMetrics]);

  const handleCopy = () => {
    navigator.clipboard.writeText(healthUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const deps = health?.dependencies || {};
  const allOk = Object.values(deps).every((d) => d.status === 'ok' || d.status === 'not_configured' || d.status === 'unavailable');
  const hasError = Object.values(deps).some((d) => d.status === 'error' || d.status === 'not_configured');

  const chartData = (metricsData?.history || []).map((s) => ({
    ...s,
    time: s.t ? new Date(s.t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '',
  }));

  const peaks = metricsData?.peaks || {};
  const current = metricsData?.current || {};

  return (
    <div className="space-y-6 max-w-4xl">
      <div className={`rounded-2xl p-4 flex items-center gap-3 border ${
        loading ? 'border-white/8 bg-zinc-500/5' :
        hasError ? 'border-red-500/20 bg-red-500/5' :
        'border-emerald-500/20 bg-emerald-500/5'
      }`}>
        {loading ? <Wifi size={20} className="text-white/30 animate-pulse" /> :
         hasError ? <AlertTriangle size={20} className="text-red-400" /> :
         <ShieldCheck size={20} className="text-emerald-400" />}
        <div className="flex-1">
          <p className={`text-sm font-semibold ${
            loading ? 'text-white/40' : hasError ? 'text-red-400' : 'text-emerald-400'
          }`}>
            {loading ? 'Running health probes...' : hasError ? 'Degraded — Check Dependencies' : 'All Systems Operational'}
          </p>
          {health && (
            <p className="text-xs text-white/30 mt-0.5">
              v{health.version || '1.0.0'} · {health.workers} workers · uptime {Math.floor((health.uptime_seconds || 0) / 60)}m
            </p>
          )}
        </div>
        <button onClick={() => { loadHealth(); loadMetrics(); }} className="p-2 rounded-xl text-white/30 hover:text-white/60 hover:bg-white/5" data-testid="button-refresh-health">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <PeakBadge label="Active Now (5m)" value={current.active_5m ?? 0} color="emerald" />
        <PeakBadge label="Peak Users (5m)" value={peaks.active_users_5m ?? 0} color="violet" />
        <PeakBadge label="Current RPS" value={current.rps ?? 0} color="blue" />
        <PeakBadge label="Peak RPS" value={peaks.rps ?? 0} color="amber" />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <PeakBadge label="Active (15m)" value={current.active_15m ?? 0} color="emerald" />
        <PeakBadge label="Active (60m)" value={current.active_60m ?? 0} color="emerald" />
        <PeakBadge label="Total Requests" value={current.requests ?? 0} color="blue" />
        <PeakBadge label="AI Chats" value={current.chats ?? 0} color="violet" />
      </div>

      <div className="rounded-xl border border-white/6 p-5" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Users size={16} className="text-violet-400" />
            <h3 className="text-sm font-semibold text-white">Active Users Over Time</h3>
          </div>
          <div className="flex gap-1">
            {[
              { label: '1h', val: 60 },
              { label: '6h', val: 360 },
              { label: '24h', val: 1440 },
            ].map(({ label, val }) => (
              <button
                key={val}
                onClick={() => setTimeRange(val)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                  timeRange === val
                    ? 'bg-violet-500/20 text-violet-400 border border-violet-500/30'
                    : 'text-white/40 hover:text-white/60 hover:bg-white/5 border border-transparent'
                }`}
                data-testid={`button-range-${label}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {metricsLoading ? (
          <div className="flex justify-center py-10">
            <RefreshCw size={20} className="animate-spin text-white/20" />
          </div>
        ) : chartData.length < 2 ? (
          <div className="flex flex-col items-center justify-center py-10 text-white/30">
            <Activity size={32} className="mb-2 opacity-40" />
            <p className="text-sm">Collecting data... Graph will appear after 2+ minutes.</p>
            <p className="text-xs mt-1 opacity-60">Snapshots are taken every 60 seconds.</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="grad5m" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#7c3aed" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#7c3aed" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="grad15m" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="grad60m" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="time" tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', paddingTop: 8 }}
                iconType="circle"
                iconSize={8}
              />
              <Area type="monotone" dataKey="active_5m" name="Active (5m)" stroke="#7c3aed" fill="url(#grad5m)" strokeWidth={2} dot={false} />
              <Area type="monotone" dataKey="active_15m" name="Active (15m)" stroke="#10b981" fill="url(#grad15m)" strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
              <Area type="monotone" dataKey="active_60m" name="Active (60m)" stroke="#3b82f6" fill="url(#grad60m)" strokeWidth={1.5} dot={false} strokeDasharray="6 3" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="rounded-xl border border-white/6 p-5" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp size={16} className="text-blue-400" />
          <h3 className="text-sm font-semibold text-white">Requests Per Second</h3>
        </div>
        {metricsLoading ? (
          <div className="flex justify-center py-10">
            <RefreshCw size={20} className="animate-spin text-white/20" />
          </div>
        ) : chartData.length < 2 ? (
          <div className="flex flex-col items-center justify-center py-8 text-white/30">
            <p className="text-sm">Waiting for data points...</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="gradRps" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="time" tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: 'rgba(255,255,255,0.3)', fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip content={<CustomTooltip />} />
              <Area type="monotone" dataKey="rps" name="RPS" stroke="#f59e0b" fill="url(#gradRps)" strokeWidth={2} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="space-y-3">
        {[
          { key: 'mongodb',  icon: Database,   label: 'Syrabit DB (MongoDB)', desc: 'User data, sessions, content, rate limits' },
          { key: 'redis',    icon: Wifi,        label: 'Redis Cache (Upstash)', desc: 'Shared content cache & session store' },
          { key: 'llm',      icon: Zap,         label: 'AI Provider (Groq)',    desc: 'LLM inference — llama-3.1-8b-instant' },
          { key: 'supabase', icon: Database,    label: 'Supabase',              desc: 'Auth, user profiles, persistent storage' },
        ].map(({key, icon: Icon, label, desc}) => {
          const dep = deps[key] || {};
          const isOk = dep.status === 'ok';
          const isNotConfigured = dep.status === 'not_configured';
          const isError = dep.status === 'error';
          return (
            <div key={key} className="rounded-xl border border-white/6 p-4 flex items-center gap-3" style={{ background: 'rgba(255,255,255,0.02)' }} data-testid={`dep-${key}`}>
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                isOk ? 'bg-emerald-500/10' : isNotConfigured ? 'bg-zinc-500/10' : isError ? 'bg-red-500/10' : 'bg-amber-500/10'
              }`}>
                <Icon size={18} className={isOk ? 'text-emerald-400' : isNotConfigured ? 'text-zinc-400' : isError ? 'text-red-400' : 'text-amber-400'} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white">{label}</p>
                <p className="text-xs text-white/40">{desc}</p>
                {dep.error && <p className="text-xs text-red-400 mt-0.5">{dep.error}</p>}
              </div>
              <div className="flex items-center gap-2">
                <LatencyBadge ms={dep.latencyMs} />
                <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                  isOk ? 'bg-emerald-500/10 text-emerald-400' :
                  isNotConfigured ? 'bg-zinc-500/10 text-zinc-400' :
                  isError ? 'bg-red-500/10 text-red-400' :
                  'bg-amber-500/10 text-amber-400 animate-pulse'
                }`}>
                  {loading ? 'PROBING...' : dep.status?.toUpperCase().replace('_',' ') || 'UNKNOWN'}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="rounded-xl border border-white/6 p-4" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <p className="text-xs font-bold text-white/40 uppercase tracking-wider mb-2">Health Endpoint URL</p>
        <div className="flex items-center gap-2">
          <code className="flex-1 text-xs font-mono text-white/60 bg-white/4 px-3 py-2 rounded-lg truncate">{healthUrl}</code>
          <button onClick={handleCopy} className="p-2 rounded-lg text-white/40 hover:text-white/70 hover:bg-white/5 flex-shrink-0" data-testid="button-copy-url">
            {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-white/6 p-4" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <p className="text-xs font-bold text-white/40 uppercase tracking-wider mb-3">UptimeRobot Setup</p>
        <ol className="space-y-2">
          {['Create free UptimeRobot account at uptimerobot.com','Add new HTTP(s) monitor','Paste the health URL above','Enable keyword monitoring: \'"status":"ok"\'','Configure alert contacts (email/Slack)','Save — you\'ll get 5-minute uptime checks'].map((s, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-white/50">
              <span className="w-5 h-5 rounded-full bg-violet-500/15 flex items-center justify-center text-[10px] font-bold text-violet-400 flex-shrink-0 mt-0.5">{i+1}</span>{s}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
