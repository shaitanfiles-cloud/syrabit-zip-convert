import { useState, useEffect, useCallback, useRef } from 'react';
import { toast } from 'sonner';
import { log } from '@/utils/logger';
import AdminQuickLinks from './AdminQuickLinks';
import {
  Users, MessageSquare, BookOpen, Zap, Loader2, Activity,
  ArrowRight, PenTool, Settings, Eye, TrendingUp, RefreshCw,
  UserPlus, Globe, Search, Bot, BarChart2, Server, Clock,
  CheckCircle, AlertCircle, AlertTriangle, Wifi, Database, DollarSign, Crown,
  Layers, Link2, Code2, FileCheck, Target, Cpu, ShieldCheck, Smartphone,
  Volume2, VolumeX, Bell, BellOff, RotateCcw, Upload, Trash2, Music,
} from 'lucide-react';
import AudioTrimPreview from './AudioTrimPreview';
import { usePushNotifications } from '@/hooks/usePushNotifications';
import axios from 'axios';
import { adminGetDashboard, seoPipelineStatus, adminSeoHealthHistory, adminSeoHealthSnapshotNow, seoHealthLive, API_BASE } from '@/utils/api';
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
  const [chatSpeedups, setChatSpeedups] = useState(null);
  const [speedupDays, setSpeedupDays] = useState(7);
  const [speedupLoading, setSpeedupLoading] = useState(false);
  const [topQueries, setTopQueries] = useState(null);
  const [tokenSpend, setTokenSpend] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [pwaStats, setPwaStats] = useState(null);
  const [botAnalytics, setBotAnalytics] = useState(null);
  const [indexNowStats, setIndexNowStats] = useState(null);
  const [indexNowHistory, setIndexNowHistory] = useState(null);
  const [retryingEndpoint, setRetryingEndpoint] = useState(null);
  const [resubmittingIndexNow, setResubmittingIndexNow] = useState(false);
  const [resubmitMessage, setResubmitMessage] = useState('');
  const [alertHistory, setAlertHistory] = useState(null);
  const [seoHealth, setSeoHealth] = useState(null);
  const [seoHealthRefreshing, setSeoHealthRefreshing] = useState(false);
  const [seoLive, setSeoLive] = useState(null);
  const [seoLiveLoading, setSeoLiveLoading] = useState(false);
  const [seoLiveError, setSeoLiveError] = useState(null);
  const [alertFilter, setAlertFilter] = useState('all');
  const [alertSettingsOpen, setAlertSettingsOpen] = useState(false);
  const [alertSettings, setAlertSettings] = useState(null);
  const [alertSettingsDraft, setAlertSettingsDraft] = useState(null);
  const [alertSettingsSaving, setAlertSettingsSaving] = useState(false);
  const [failedSections, setFailedSections] = useState([]);
  const [notifPrefs, setNotifPrefs] = useState(null);
  const [notifPrefsSaving, setNotifPrefsSaving] = useState(false);
  const [notifPrefsOpen, setNotifPrefsOpen] = useState(false);
  const [pushDeliverySummary, setPushDeliverySummary] = useState(null);
  const prevAlertIdsRef = useRef(new Set());
  const audioCtxRef = useRef(null);
  const customAudioRef = useRef(null);
  const chimeFileInputRef = useRef(null);
  const [chimeUploading, setChimeUploading] = useState(false);
  const [pendingChimeFile, setPendingChimeFile] = useState(null);
  const pushNotif = usePushNotifications({
    serverPushEnabled: notifPrefs?.push_enabled,
  });

  const alertSoundEnabled = notifPrefs?.sound_enabled ?? true;
  const chimeTone = notifPrefs?.chime_tone ?? 'default';

  const CHIME_TONES = {
    default: { label: 'Default', freqs: [880, 1100, 880], type: 'sine', dur: 0.5 },
    soft: { label: 'Soft', freqs: [440, 550, 440], type: 'sine', dur: 0.6 },
    urgent: { label: 'Urgent', freqs: [1200, 900, 1200, 900], type: 'square', dur: 0.4 },
    bell: { label: 'Bell', freqs: [1047, 1319, 1568], type: 'sine', dur: 0.7 },
  };

  const ALERT_SEVERITY_LABELS = {
    high_error_rate: 'High Error Rate',
    high_latency: 'High Latency',
    spoofed_bot_surge: 'Bot Surge',
    high_fallback_rate: 'High Fallback Rate',
    endpoint_down: 'Endpoint Down',
    auto_block_expired: 'Auto-Block Expired',
  };

  const loadNotifPrefs = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/admin/notification-prefs`, adminHdr(adminToken));
      setNotifPrefs(res.data);
    } catch (e) {
      log.error('Failed to load notification prefs', { error: e.message });
      setNotifPrefs({
        sound_enabled: true, push_enabled: false, chime_tone: 'default',
        sound_severities: ['high_error_rate', 'high_latency', 'spoofed_bot_surge', 'high_fallback_rate', 'endpoint_down', 'auto_block_expired'],
        push_severities: ['high_error_rate', 'spoofed_bot_surge', 'endpoint_down', 'auto_block_expired'],
      });
    }
    try {
      const statsRes = await axios.get(`${API_BASE}/admin/push/delivery-stats?days=7`, adminHdr(adminToken));
      setPushDeliverySummary(statsRes.data);
    } catch {}
  }, [adminToken]);

  const saveNotifPrefs = useCallback(async (updates) => {
    const merged = { ...notifPrefs, ...updates };
    setNotifPrefs(merged);
    setNotifPrefsSaving(true);
    try {
      const res = await axios.put(`${API_BASE}/admin/notification-prefs`, merged, adminHdr(adminToken));
      setNotifPrefs(res.data);
    } catch (e) {
      log.error('Failed to save notification prefs', { error: e.message });
    } finally {
      setNotifPrefsSaving(false);
    }
  }, [adminToken, notifPrefs]);

  const toggleAlertSound = useCallback(() => {
    saveNotifPrefs({ sound_enabled: !alertSoundEnabled });
  }, [saveNotifPrefs, alertSoundEnabled]);

  const playAlertChime = useCallback((tone) => {
    try {
      const activeTone = tone || chimeTone;
      if (activeTone === 'custom' && notifPrefs?.custom_chime_url) {
        if (customAudioRef.current) {
          customAudioRef.current.pause();
          customAudioRef.current.currentTime = 0;
        }
        const audio = new Audio(notifPrefs.custom_chime_url);
        audio.volume = 0.5;
        customAudioRef.current = audio;
        audio.play().catch(() => {});
        return;
      }
      if (!audioCtxRef.current) {
        audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
      }
      const ctx = audioCtxRef.current;
      const now = ctx.currentTime;
      const toneConfig = CHIME_TONES[activeTone] || CHIME_TONES.default;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = toneConfig.type;
      const step = toneConfig.dur / toneConfig.freqs.length;
      toneConfig.freqs.forEach((f, i) => osc.frequency.setValueAtTime(f, now + i * step));
      gain.gain.setValueAtTime(0.3, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + toneConfig.dur);
      osc.start(now);
      osc.stop(now + toneConfig.dur);
    } catch {}
  }, [chimeTone, notifPrefs?.custom_chime_url]);

  const handleChimeFileSelect = useCallback((e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const validTypes = ['audio/mpeg', 'audio/wav', 'audio/wave', 'audio/x-wav', 'audio/mp3'];
    if (!validTypes.includes(file.type)) {
      toast.error('Only MP3 and WAV files are supported');
      if (chimeFileInputRef.current) chimeFileInputRef.current.value = '';
      return;
    }
    if (file.size > 500 * 1024) {
      toast.error('File must be under 500 KB');
      if (chimeFileInputRef.current) chimeFileInputRef.current.value = '';
      return;
    }
    setPendingChimeFile(file);
    if (chimeFileInputRef.current) chimeFileInputRef.current.value = '';
  }, []);

  const handleChimeUploadConfirm = useCallback(async (fileToUpload) => {
    if (fileToUpload.size > 500 * 1024) {
      toast.error('Trimmed file exceeds 500 KB limit');
      return;
    }
    setChimeUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', fileToUpload);
      const res = await axios.post(`${API_BASE}/admin/notification-prefs/upload-chime`, formData, {
        ...adminHdr(adminToken),
        headers: { ...adminHdr(adminToken).headers, 'Content-Type': 'multipart/form-data' },
      });
      setNotifPrefs(res.data);
      setPendingChimeFile(null);
      toast.success('Custom chime uploaded');
    } catch (err) {
      const msg = err.response?.data?.detail || 'Upload failed';
      toast.error(msg);
    } finally {
      setChimeUploading(false);
    }
  }, [adminToken]);

  const handleDeleteCustomChime = useCallback(async () => {
    try {
      const res = await axios.delete(`${API_BASE}/admin/notification-prefs/custom-chime`, adminHdr(adminToken));
      setNotifPrefs(res.data);
      toast.success('Custom chime removed');
    } catch {
      toast.error('Failed to remove custom chime');
    }
  }, [adminToken]);

  useEffect(() => {
    if (!alertHistory?.alerts || !alertSoundEnabled) return;
    const soundSeverities = new Set(notifPrefs?.sound_severities || []);
    const currentUnack = alertHistory.alerts.filter(a => !a.acknowledged);
    const currentIds = new Set(currentUnack.map(a => a._id));
    const prevIds = prevAlertIdsRef.current;
    const newAlerts = currentUnack.filter(a => !prevIds.has(a._id));
    if (newAlerts.length > 0 && prevIds.size > 0) {
      const shouldSound = newAlerts.some(a => soundSeverities.has(a.type));
      if (shouldSound) playAlertChime();
    }
    prevAlertIdsRef.current = currentIds;
  }, [alertHistory, alertSoundEnabled, notifPrefs, playAlertChime]);

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
        alertHistRes, seoHealthRes,
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
        adminSeoHealthHistory(adminToken, 168),
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
      if (seoHealthRes.status === 'fulfilled') setSeoHealth(seoHealthRes.value.data); else { failed.push('seo-health'); setSeoHealth(null); }
      seoHealthLive()
        .then((r) => { setSeoLive(r.data); setSeoLiveError(null); })
        .catch((e) => { setSeoLive(null); setSeoLiveError(e?.message || 'Failed to load SEO health'); });
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
    loadNotifPrefs();
    const interval = setInterval(() => load(true), 60000);
    return () => clearInterval(interval);
  }, [load, loadNotifPrefs]);

  const loadChatSpeedups = useCallback(async (days) => {
    setSpeedupLoading(true);
    try {
      const res = await axios.get(`${API_BASE}/admin/chat/speedups?days=${days}`, adminHdr(adminToken));
      setChatSpeedups(res.data);
    } catch (e) {
      log.error('Failed to load chat speedups', { error: e.message });
      setChatSpeedups(null);
    } finally {
      setSpeedupLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminToken]);

  useEffect(() => {
    loadChatSpeedups(speedupDays);
    const interval = setInterval(() => loadChatSpeedups(speedupDays), 60000);
    return () => clearInterval(interval);
  }, [loadChatSpeedups, speedupDays]);

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
      toast.success('Alert acknowledged');
    } catch (e) {
      log.error('Failed to acknowledge alert', { error: e.message });
      toast.error(`Failed to acknowledge alert: ${e.response?.data?.error || e.message}`);
    }
  };

  const handleAcknowledgeAll = async () => {
    try {
      await axios.patch(`${API_BASE}/admin/alerts/acknowledge-all`, {}, adminHdr(adminToken));
      setAlertHistory(prev => ({
        ...prev,
        alerts: prev.alerts.map(a => ({ ...a, acknowledged: true })),
      }));
      toast.success('All alerts acknowledged');
    } catch (e) {
      log.error('Failed to acknowledge all alerts', { error: e.message });
      toast.error(`Failed to acknowledge alerts: ${e.response?.data?.error || e.message}`);
    }
  };

  const loadAlertSettings = async () => {
    try {
      const res = await axios.get(`${API_BASE}/admin/alert-settings`, adminHdr(adminToken));
      setAlertSettings(res.data);
      setAlertSettingsDraft({ thresholds: { ...res.data.thresholds }, expiration: { ...res.data.expiration } });
    } catch (e) {
      log.error('Failed to load alert settings', { error: e.message });
    }
  };

  const handleSaveAlertSettings = async () => {
    if (!alertSettingsDraft) return;
    setAlertSettingsSaving(true);
    try {
      await axios.put(`${API_BASE}/admin/alert-settings`, alertSettingsDraft, adminHdr(adminToken));
      setAlertSettings({ ...alertSettings, thresholds: { ...alertSettingsDraft.thresholds }, expiration: { ...alertSettingsDraft.expiration } });
      setAlertSettingsOpen(false);
      toast.success('Alert settings saved');
    } catch (e) {
      log.error('Failed to save alert settings', { error: e.message });
      toast.error(`Failed to save alert settings: ${e.response?.data?.error || e.message}`);
    } finally {
      setAlertSettingsSaving(false);
    }
  };

  const handleOpenAlertSettings = () => {
    if (!alertSettings) loadAlertSettings();
    setAlertSettingsOpen(prev => !prev);
  };

  const handleResetAlertSettings = () => {
    if (alertSettings?.defaults) {
      setAlertSettingsDraft({
        thresholds: { ...alertSettings.defaults.thresholds },
        expiration: { ...alertSettings.defaults.expiration },
      });
    }
  };

  const handleRetryEndpoint = async (endpoint) => {
    setRetryingEndpoint(endpoint);
    try {
      const retryRes = await axios.post(`${API_BASE}/admin/indexnow/endpoint/retry`, { endpoint }, adminHdr(adminToken));
      const requeued = Number(retryRes.data?.requeued ?? retryRes.data?.count ?? 0);
      toast.success(`Endpoint reset — ${requeued} URL${requeued === 1 ? '' : 's'} re-queued`);
      try {
        const statsRes = await axios.get(`${API_BASE}/admin/indexnow/stats`, adminHdr(adminToken));
        setIndexNowStats(statsRes.data);
      } catch (statsErr) {
        log.error('Stats refresh failed after retry', { endpoint, error: statsErr.message });
      }
    } catch (e) {
      log.error('Endpoint retry failed', { endpoint, error: e.message });
      toast.error(`Retry failed: ${e.response?.data?.error || e.message}`);
    } finally {
      setRetryingEndpoint(null);
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
          <StatCard label="Bot Renders"    value={metrics.bot_render?.total_requests || 0} icon={Bot} color="#8b5cf6"
            subLabel="Success Rate" subValue={metrics.bot_render?.success_rate_pct != null ? `${metrics.bot_render.success_rate_pct}%` : '—'} />
        </div>
      )}
      {metrics.bot_render?.by_page_type && Object.keys(metrics.bot_render.by_page_type).length > 0 && (() => {
        const raw = metrics.bot_render.by_page_type;
        const grouped = {};
        Object.entries(raw).forEach(([key, count]) => {
          const [type, status] = key.split(':');
          if (!grouped[type]) grouped[type] = { ok: 0, fail: 0 };
          if (status === 'ok') grouped[type].ok = count;
          else grouped[type].fail = count;
        });
        return (
        <div className="mt-4 bg-white border border-gray-200 rounded-2xl p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2"><Bot size={14} className="text-violet-500" /> Bot Render by Page Type</h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {Object.entries(grouped).map(([type, counts]) => (
              <div key={type} className="bg-gray-50 rounded-xl px-3 py-2 border border-gray-100">
                <p className="text-[10px] uppercase tracking-wider text-gray-400 mb-1">{type.replace(/_/g, ' ')}</p>
                <p className="text-base font-bold font-mono text-gray-800">{counts.ok + counts.fail}</p>
                <p className="text-[10px] text-gray-400">{counts.ok} ok / {counts.fail} fail</p>
              </div>
            ))}
          </div>
        </div>
        );
      })()}

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

      {seoHealth?.banner && (
        <div
          className={`rounded-xl border-2 p-4 flex items-start gap-3 ${
            seoHealth.banner.severity === 'critical'
              ? 'bg-red-50 border-red-300 text-red-800'
              : 'bg-amber-50 border-amber-300 text-amber-800'
          }`}
          role="alert"
        >
          <AlertTriangle size={20} className={seoHealth.banner.severity === 'critical' ? 'text-red-600' : 'text-amber-600'} />
          <div className="flex-1 min-w-0">
            <div className="font-semibold">
              SEO health is {seoHealth.banner.severity.toUpperCase()}
              {seoHealth.banner.consecutive >= 2 && (
                <span className="ml-2 text-xs font-normal opacity-80">
                  ({seoHealth.banner.consecutive} consecutive checks · alert email sent)
                </span>
              )}
            </div>
            <div className="text-xs mt-1 opacity-90">
              Sitemaps valid: {seoHealth.banner.summary?.valid_sitemaps ?? 0}/{seoHealth.banner.summary?.total_sitemaps ?? 0}
              {' · '}URL spot-checks OK: {seoHealth.banner.summary?.ok_url_checks ?? 0}/{seoHealth.banner.summary?.total_url_checks ?? 0}
              {' ('}{seoHealth.banner.summary?.url_check_success_rate ?? 0}%{')'}
              {seoHealth.banner.checked_at && ` · last checked ${new Date(seoHealth.banner.checked_at).toLocaleTimeString()}`}
            </div>
          </div>
          <button
            onClick={async () => {
              setSeoHealthRefreshing(true);
              try {
                await adminSeoHealthSnapshotNow(adminToken);
                const r = await adminSeoHealthHistory(adminToken, 168);
                setSeoHealth(r.data);
                toast.success('SEO health re-checked');
              } catch (e) {
                toast.error('Re-check failed');
              } finally {
                setSeoHealthRefreshing(false);
              }
            }}
            disabled={seoHealthRefreshing}
            className="text-xs px-3 py-1.5 rounded-md bg-white border border-current hover:bg-opacity-80 font-medium disabled:opacity-50"
          >
            {seoHealthRefreshing ? 'Checking…' : 'Re-check now'}
          </button>
        </div>
      )}

      {seoHealth?.history && seoHealth.history.length > 0 && (
        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <Globe size={16} className="text-cyan-500" />
            <h3 className="text-gray-700 font-semibold">SEO Health Trend</h3>
            <span className="text-[10px] text-gray-500">
              last {seoHealth.history.length} hourly snapshots
            </span>
            <div className="ml-auto flex items-center gap-3 text-[10px] text-gray-500">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-emerald-500" /> ok</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-amber-500" /> degraded</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-red-500" /> critical</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-[3px]">
            {seoHealth.history.map((h, i) => {
              const s = (h.status || '').toLowerCase();
              const cls = s === 'ok'
                ? 'bg-emerald-500'
                : s === 'degraded'
                ? 'bg-amber-500'
                : s === 'critical'
                ? 'bg-red-500'
                : 'bg-gray-300';
              const when = h.checked_at || h.recorded_at;
              return (
                <div
                  key={i}
                  className={`w-2.5 h-6 rounded-sm ${cls}`}
                  title={`${s.toUpperCase()} · ${when ? new Date(when).toLocaleString() : ''} · ${h.summary?.valid_sitemaps ?? 0}/${h.summary?.total_sitemaps ?? 0} sitemaps`}
                />
              );
            })}
          </div>
          {seoHealth.latest && (
            <div className="text-[11px] text-gray-500 mt-3">
              Latest: <span className="font-semibold text-gray-700">{(seoHealth.latest.status || 'unknown').toUpperCase()}</span>
              {' · '}{seoHealth.latest.summary?.valid_sitemaps ?? 0}/{seoHealth.latest.summary?.total_sitemaps ?? 0} sitemaps valid
              {' · '}{seoHealth.latest.summary?.url_check_success_rate ?? 0}% URL checks OK
              {seoHealth.latest.checked_at && ` · ${new Date(seoHealth.latest.checked_at).toLocaleString()}`}
            </div>
          )}
        </GlassCard>
      )}

      <GlassCard className="p-5" data-testid="seo-sitemap-health-card">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <FileCheck size={16} className="text-cyan-500" />
          <h3 className="text-gray-700 font-semibold">SEO Sitemap Health</h3>
          {seoLive?.status && (
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase tracking-wider ${
              seoLive.status === 'ok' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' :
              seoLive.status === 'degraded' ? 'bg-amber-50 text-amber-700 border border-amber-200' :
              seoLive.status === 'critical' ? 'bg-red-50 text-red-700 border border-red-200' :
              'bg-gray-50 text-gray-500 border border-gray-200'
            }`} data-testid="seo-live-status">
              {seoLive.status}
            </span>
          )}
          {seoLive?.checked_at && (
            <span className="text-[10px] text-gray-400">
              checked {formatTimeAgo(seoLive.checked_at)}
            </span>
          )}
          <button
            onClick={async () => {
              setSeoLiveLoading(true);
              setSeoLiveError(null);
              try {
                const r = await seoHealthLive();
                setSeoLive(r.data);
              } catch (e) {
                setSeoLiveError(e?.message || 'Failed');
              } finally {
                setSeoLiveLoading(false);
              }
            }}
            disabled={seoLiveLoading}
            className="ml-auto text-[11px] px-3 py-1 rounded-md border border-gray-200 text-gray-500 hover:text-gray-700 hover:bg-gray-50 disabled:opacity-50 inline-flex items-center gap-1"
            data-testid="seo-live-refresh"
          >
            <RefreshCw size={11} className={seoLiveLoading ? 'animate-spin' : ''} />
            {seoLiveLoading ? 'Probing…' : 'Probe now'}
          </button>
        </div>

        {seoLiveError && !seoLive && (
          <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">
            {seoLiveError}
          </div>
        )}

        {!seoLive && !seoLiveError && (
          <div className="flex items-center gap-2 text-xs text-gray-400 py-3">
            <Loader2 size={14} className="animate-spin" /> Loading sitemap probes…
          </div>
        )}

        {seoLive && (
          <>
            {seoLive.summary && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
                <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wider text-gray-400">Sitemaps Valid</p>
                  <p className="text-sm font-bold font-mono text-gray-800">
                    {seoLive.summary.valid_sitemaps ?? 0}/{seoLive.summary.total_sitemaps ?? 0}
                  </p>
                </div>
                <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wider text-gray-400">URL Checks OK</p>
                  <p className="text-sm font-bold font-mono text-gray-800">
                    {seoLive.summary.ok_url_checks ?? 0}/{seoLive.summary.total_url_checks ?? 0}
                  </p>
                </div>
                <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wider text-gray-400">Success Rate</p>
                  <p className="text-sm font-bold font-mono text-gray-800">
                    {seoLive.summary.url_check_success_rate ?? 0}%
                  </p>
                </div>
                <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
                  <p className="text-[10px] uppercase tracking-wider text-gray-400">Published Pages</p>
                  <p className="text-sm font-bold font-mono text-gray-800">
                    {(seoLive.content_stats?.published_pages ?? 0).toLocaleString()}
                  </p>
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              {(seoLive.sitemaps || []).map((sm) => {
                const checks = sm.sample_checks || [];
                const okCount = checks.filter((c) => c.ok).length;
                const totalCount = checks.length;
                const allOk = sm.valid_xml && (totalCount === 0 || okCount === totalCount);
                const partial = sm.valid_xml && totalCount > 0 && okCount > 0 && okCount < totalCount;
                const broken = !sm.valid_xml || (totalCount > 0 && okCount === 0);
                const dotCls = allOk ? 'bg-emerald-500' : partial ? 'bg-amber-500' : broken ? 'bg-red-500' : 'bg-gray-300';
                return (
                  <div
                    key={sm.name}
                    className="flex items-center gap-3 px-3 py-2 rounded-lg border border-gray-100 bg-white hover:bg-gray-50"
                    data-testid={`seo-sitemap-${sm.name}`}
                  >
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotCls}`} />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-mono text-gray-700 truncate">{sm.name}</p>
                      {sm.error && (
                        <p className="text-[10px] text-red-600 truncate" title={sm.error}>
                          {sm.error}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-3 text-[11px] text-gray-500 flex-shrink-0">
                      <span title="URLs in sitemap" className="font-mono">
                        {(sm.url_count ?? 0).toLocaleString()} urls
                      </span>
                      <span
                        className={`font-mono px-2 py-0.5 rounded ${
                          allOk ? 'bg-emerald-50 text-emerald-700' :
                          partial ? 'bg-amber-50 text-amber-700' :
                          broken ? 'bg-red-50 text-red-700' :
                          'bg-gray-50 text-gray-500'
                        }`}
                        title="Sample HEAD checks against random URLs"
                      >
                        {okCount}/{totalCount} ok
                      </span>
                    </div>
                  </div>
                );
              })}
              {(!seoLive.sitemaps || seoLive.sitemaps.length === 0) && (
                <p className="text-xs text-gray-400">No sitemaps reported.</p>
              )}
            </div>

            <div className="mt-4 pt-4 border-t border-gray-100 flex items-center gap-3 flex-wrap">
              <Database size={14} className="text-gray-400" />
              <span className="text-xs font-semibold text-gray-600">D1 Sync</span>
              {(() => {
                const d1 = seoLive.d1_sync || {};
                const d1Status = (d1.status || 'unknown').toLowerCase();
                const cls = d1Status === 'ok' || d1Status === 'fresh'
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : d1Status === 'stale' || d1Status === 'degraded'
                  ? 'bg-amber-50 text-amber-700 border-amber-200'
                  : d1Status === 'error' || d1Status === 'critical'
                  ? 'bg-red-50 text-red-700 border-red-200'
                  : 'bg-gray-50 text-gray-500 border-gray-200';
                const lastSync = d1.last_sync || d1.last_synced_at || d1.updated_at || d1.synced_at;
                return (
                  <>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase tracking-wider ${cls}`} data-testid="d1-sync-status">
                      {d1Status}
                    </span>
                    {lastSync && (
                      <span className="text-[11px] text-gray-500">
                        last sync {formatTimeAgo(lastSync)}
                        <span className="text-gray-400"> · {new Date(lastSync).toLocaleString()}</span>
                      </span>
                    )}
                    {d1.row_count != null && (
                      <span className="text-[11px] text-gray-500 font-mono">
                        rows: {Number(d1.row_count).toLocaleString()}
                      </span>
                    )}
                    {d1.error && (
                      <span className="text-[11px] text-red-600 truncate" title={d1.error}>
                        {d1.error}
                      </span>
                    )}
                  </>
                );
              })()}
              {seoLive.content_stats?.last_content_update && (
                <span className="ml-auto text-[11px] text-gray-500">
                  <Clock size={11} className="inline mr-1 -mt-0.5" />
                  content updated {formatTimeAgo(seoLive.content_stats.last_content_update)}
                </span>
              )}
            </div>
          </>
        )}
      </GlassCard>
      

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
              <button
                onClick={toggleAlertSound}
                className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded-md border transition-colors font-medium ${
                  alertSoundEnabled
                    ? 'bg-violet-50 text-violet-700 border-violet-200 hover:bg-violet-100'
                    : 'bg-gray-50 text-gray-400 border-gray-200 hover:bg-gray-100'
                }`}
                title={alertSoundEnabled ? 'Alert sound on — click to mute' : 'Alert sound off — click to enable'}
              >
                {alertSoundEnabled ? <Volume2 size={11} /> : <VolumeX size={11} />}
                {alertSoundEnabled ? 'Sound On' : 'Sound Off'}
              </button>
              {pushNotif.isSupported && (
                <button
                  onClick={async () => {
                    const currentlyEnabled = notifPrefs?.push_enabled && pushNotif.subscribed;
                    if (currentlyEnabled) {
                      await pushNotif.unsubscribe();
                      saveNotifPrefs({ push_enabled: false });
                    } else {
                      const success = await pushNotif.subscribe();
                      if (success !== false) saveNotifPrefs({ push_enabled: true });
                    }
                  }}
                  disabled={pushNotif.loading}
                  className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded-md border transition-colors font-medium ${
                    (notifPrefs?.push_enabled && pushNotif.subscribed)
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                      : 'bg-gray-50 text-gray-400 border-gray-200 hover:bg-gray-100'
                  }`}
                  title={(notifPrefs?.push_enabled && pushNotif.subscribed) ? 'Push notifications enabled — click to disable' : 'Enable browser push notifications for critical alerts'}
                >
                  {(notifPrefs?.push_enabled && pushNotif.subscribed) ? <Bell size={11} /> : <BellOff size={11} />}
                  {pushNotif.loading ? 'Loading...' : (notifPrefs?.push_enabled && pushNotif.subscribed) ? 'Push On' : 'Push Off'}
                </button>
              )}
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
              <button
                onClick={handleOpenAlertSettings}
                className="text-[10px] px-2.5 py-1 rounded-md bg-gray-50 text-gray-600 border border-gray-200 hover:bg-violet-50 hover:text-violet-600 hover:border-violet-200 transition-colors font-medium flex items-center gap-1"
              >
                <Settings size={10} />
                Settings
              </button>
              <button
                onClick={() => setNotifPrefsOpen(prev => !prev)}
                className={`text-[10px] px-2.5 py-1 rounded-md border transition-colors font-medium flex items-center gap-1 ${
                  notifPrefsOpen
                    ? 'bg-violet-50 text-violet-700 border-violet-200'
                    : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-violet-50 hover:text-violet-600 hover:border-violet-200'
                }`}
              >
                <Bell size={10} />
                Preferences
              </button>
            </div>
          </div>

          {alertSettingsOpen && alertSettingsDraft && (
            <div className="mb-4 p-4 rounded-xl bg-gray-50 border border-gray-200">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-xs font-semibold text-gray-700">Alert Thresholds & Expiration</h4>
                <div className="flex gap-2">
                  <button onClick={handleResetAlertSettings} className="text-[10px] px-2 py-0.5 rounded bg-white border border-gray-200 text-gray-500 hover:bg-gray-100 transition-colors">Reset Defaults</button>
                  <button
                    onClick={handleSaveAlertSettings}
                    disabled={alertSettingsSaving}
                    className="text-[10px] px-3 py-0.5 rounded bg-violet-600 text-white hover:bg-violet-700 transition-colors disabled:opacity-50 font-medium"
                  >
                    {alertSettingsSaving ? 'Saving...' : 'Save'}
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                <div>
                  <label className="text-[10px] text-gray-500 font-medium block mb-1">Error Rate (%)</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0.1"
                    value={alertSettingsDraft.thresholds.error_rate_pct ?? ''}
                    onChange={e => setAlertSettingsDraft(prev => ({ ...prev, thresholds: { ...prev.thresholds, error_rate_pct: parseFloat(e.target.value) || 0 } }))}
                    className="w-full text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:ring-1 focus:ring-violet-300 focus:border-violet-300 outline-none"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 font-medium block mb-1">Latency p95 (ms)</label>
                  <input
                    type="number"
                    step="100"
                    min="100"
                    value={alertSettingsDraft.thresholds.latency_p95_ms ?? ''}
                    onChange={e => setAlertSettingsDraft(prev => ({ ...prev, thresholds: { ...prev.thresholds, latency_p95_ms: parseInt(e.target.value) || 0 } }))}
                    className="w-full text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:ring-1 focus:ring-violet-300 focus:border-violet-300 outline-none"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 font-medium block mb-1">Fallback Rate (%)</label>
                  <input
                    type="number"
                    step="1"
                    min="1"
                    value={alertSettingsDraft.thresholds.fallback_rate_pct ?? ''}
                    onChange={e => setAlertSettingsDraft(prev => ({ ...prev, thresholds: { ...prev.thresholds, fallback_rate_pct: parseFloat(e.target.value) || 0 } }))}
                    className="w-full text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:ring-1 focus:ring-violet-300 focus:border-violet-300 outline-none"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 font-medium block mb-1">Spoof RPM</label>
                  <input
                    type="number"
                    step="1"
                    min="1"
                    value={alertSettingsDraft.thresholds.spoof_rpm ?? ''}
                    onChange={e => setAlertSettingsDraft(prev => ({ ...prev, thresholds: { ...prev.thresholds, spoof_rpm: parseInt(e.target.value) || 0 } }))}
                    className="w-full text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:ring-1 focus:ring-violet-300 focus:border-violet-300 outline-none"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 font-medium block mb-1">Endpoint Down (min)</label>
                  <input
                    type="number"
                    step="5"
                    min="1"
                    value={alertSettingsDraft.thresholds.endpoint_down_minutes ?? ''}
                    onChange={e => setAlertSettingsDraft(prev => ({ ...prev, thresholds: { ...prev.thresholds, endpoint_down_minutes: parseInt(e.target.value) || 0 } }))}
                    className="w-full text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:ring-1 focus:ring-violet-300 focus:border-violet-300 outline-none"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 font-medium block mb-1">EP Check Interval (min)</label>
                  <input
                    type="number"
                    step="5"
                    min="1"
                    value={alertSettingsDraft.thresholds.endpoint_down_check_minutes ?? ''}
                    onChange={e => setAlertSettingsDraft(prev => ({ ...prev, thresholds: { ...prev.thresholds, endpoint_down_check_minutes: parseInt(e.target.value) || 0 } }))}
                    className="w-full text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:ring-1 focus:ring-violet-300 focus:border-violet-300 outline-none"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 font-medium block mb-1" title="Fires when sitemap URL spot-checks return ≥ this % of 404s for two consecutive hourly snapshots.">URL 404 Spike (%)</label>
                  <input
                    type="number"
                    step="1"
                    min="1"
                    max="100"
                    value={alertSettingsDraft.thresholds.url_404_spike_pct ?? ''}
                    onChange={e => {
                      const raw = e.target.value;
                      const parsed = parseFloat(raw);
                      // Keep the previous value if input is blank/invalid so
                      // an empty field never silently coerces to 0% (which
                      // would alert on the slightest failure).
                      const next = (raw === '' || Number.isNaN(parsed))
                        ? alertSettingsDraft.thresholds.url_404_spike_pct
                        : parsed;
                      setAlertSettingsDraft(prev => ({ ...prev, thresholds: { ...prev.thresholds, url_404_spike_pct: next } }));
                    }}
                    className="w-full text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:ring-1 focus:ring-violet-300 focus:border-violet-300 outline-none"
                  />
                </div>
              </div>
              <div className="flex items-center gap-4 pt-2 border-t border-gray-200">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={alertSettingsDraft.expiration.enabled || false}
                    onChange={e => setAlertSettingsDraft(prev => ({ ...prev, expiration: { ...prev.expiration, enabled: e.target.checked } }))}
                    className="w-3.5 h-3.5 rounded border-gray-300 text-violet-600 focus:ring-violet-500"
                  />
                  <span className="text-[11px] text-gray-600 font-medium">Auto-acknowledge after</span>
                </label>
                <input
                  type="number"
                  min="1"
                  max="365"
                  value={alertSettingsDraft.expiration.days ?? 7}
                  onChange={e => setAlertSettingsDraft(prev => ({ ...prev, expiration: { ...prev.expiration, days: parseInt(e.target.value) || 7 } }))}
                  disabled={!alertSettingsDraft.expiration.enabled}
                  className="w-16 text-xs border border-gray-200 rounded-md px-2 py-1 bg-white focus:ring-1 focus:ring-violet-300 focus:border-violet-300 outline-none disabled:opacity-40"
                />
                <span className="text-[11px] text-gray-500">days</span>
              </div>
            </div>
          )}

          {notifPrefsOpen && notifPrefs && (
            <div className="mb-4 p-4 rounded-xl bg-gray-50 border border-gray-200">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-xs font-semibold text-gray-700">Notification Preferences</h4>
                {notifPrefsSaving && <span className="text-[10px] text-violet-500 font-medium">Saving...</span>}
              </div>

              <div className="flex items-center gap-6 mb-3 pb-3 border-b border-gray-200">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={notifPrefs.sound_enabled ?? true}
                    onChange={e => saveNotifPrefs({ sound_enabled: e.target.checked })}
                    className="w-3.5 h-3.5 rounded border-gray-300 text-violet-600 focus:ring-violet-500"
                  />
                  <span className="text-[11px] text-gray-600 font-medium">Sound Enabled</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={notifPrefs.push_enabled ?? false}
                    onChange={async (e) => {
                      const enabled = e.target.checked;
                      if (enabled && !pushNotif.subscribed) {
                        const success = await pushNotif.subscribe();
                        if (success === false) return;
                      }
                      if (!enabled && pushNotif.subscribed) {
                        await pushNotif.unsubscribe();
                      }
                      saveNotifPrefs({ push_enabled: enabled });
                    }}
                    className="w-3.5 h-3.5 rounded border-gray-300 text-violet-600 focus:ring-violet-500"
                  />
                  <span className="text-[11px] text-gray-600 font-medium">Push Enabled</span>
                </label>
              </div>

              <div className="mb-3">
                <label className="text-[10px] text-gray-500 font-medium block mb-1.5">Chime Tone</label>
                <div className="flex items-center gap-2 flex-wrap">
                  {Object.entries(CHIME_TONES).map(([key, tone]) => (
                    <button
                      key={key}
                      onClick={() => { playAlertChime(key); saveNotifPrefs({ chime_tone: key }); }}
                      className={`text-[10px] px-2.5 py-1 rounded-md border transition-colors font-medium ${
                        chimeTone === key
                          ? 'bg-violet-100 text-violet-700 border-violet-300'
                          : 'bg-white text-gray-500 border-gray-200 hover:bg-violet-50 hover:text-violet-600'
                      }`}
                    >
                      {tone.label}
                    </button>
                  ))}
                  {notifPrefs?.custom_chime_url && (
                    <button
                      onClick={() => { playAlertChime('custom'); saveNotifPrefs({ chime_tone: 'custom' }); }}
                      className={`text-[10px] px-2.5 py-1 rounded-md border transition-colors font-medium flex items-center gap-1 ${
                        chimeTone === 'custom'
                          ? 'bg-violet-100 text-violet-700 border-violet-300'
                          : 'bg-white text-gray-500 border-gray-200 hover:bg-violet-50 hover:text-violet-600'
                      }`}
                    >
                      <Music size={10} /> Custom
                    </button>
                  )}
                </div>
                <div className="mt-2">
                  {notifPrefs?.custom_chime_url ? (
                    <div className="flex items-center gap-2 text-[10px]">
                      <Music size={10} className="text-violet-500" />
                      <span className="text-gray-600 truncate max-w-[140px]">{notifPrefs.custom_chime_filename || 'Custom chime'}</span>
                      <button
                        onClick={() => playAlertChime('custom')}
                        className="text-violet-600 hover:text-violet-700 font-medium"
                      >
                        Preview
                      </button>
                      <button
                        onClick={handleDeleteCustomChime}
                        className="text-red-400 hover:text-red-600 ml-1"
                        title="Remove custom chime"
                      >
                        <Trash2 size={10} />
                      </button>
                    </div>
                  ) : pendingChimeFile ? (
                    <AudioTrimPreview
                      file={pendingChimeFile}
                      onConfirm={handleChimeUploadConfirm}
                      onCancel={() => setPendingChimeFile(null)}
                      uploading={chimeUploading}
                    />
                  ) : (
                    <label className="inline-flex items-center gap-1.5 text-[10px] text-violet-600 hover:text-violet-700 cursor-pointer font-medium">
                      <Upload size={10} />
                      Upload custom sound
                      <input
                        ref={chimeFileInputRef}
                        type="file"
                        accept=".mp3,.wav"
                        className="hidden"
                        onChange={handleChimeFileSelect}
                        disabled={chimeUploading}
                      />
                    </label>
                  )}
                  {!pendingChimeFile && <p className="text-[9px] text-gray-400 mt-0.5">MP3 or WAV, max 500 KB</p>}
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-[10px] text-gray-500 font-medium block mb-1.5">Sound Alerts For</label>
                  <div className="space-y-1.5">
                    {Object.entries(ALERT_SEVERITY_LABELS).map(([key, label]) => (
                      <label key={key} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={(notifPrefs.sound_severities || []).includes(key)}
                          onChange={e => {
                            const current = notifPrefs.sound_severities || [];
                            const next = e.target.checked ? [...current, key] : current.filter(s => s !== key);
                            saveNotifPrefs({ sound_severities: next });
                          }}
                          className="w-3.5 h-3.5 rounded border-gray-300 text-violet-600 focus:ring-violet-500"
                        />
                        <span className="text-[11px] text-gray-600">{label}</span>
                      </label>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-gray-500 font-medium block mb-1.5">Push Alerts For</label>
                  <div className="space-y-1.5">
                    {Object.entries(ALERT_SEVERITY_LABELS).map(([key, label]) => (
                      <label key={key} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={(notifPrefs.push_severities || []).includes(key)}
                          onChange={e => {
                            const current = notifPrefs.push_severities || [];
                            const next = e.target.checked ? [...current, key] : current.filter(s => s !== key);
                            saveNotifPrefs({ push_severities: next });
                          }}
                          className="w-3.5 h-3.5 rounded border-gray-300 text-violet-600 focus:ring-violet-500"
                        />
                        <span className="text-[11px] text-gray-600">{label}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between mt-3 pt-2 border-t border-gray-200">
                <button
                  onClick={() => saveNotifPrefs(notifPrefs.defaults || {})}
                  className="text-[10px] px-2 py-0.5 rounded bg-white border border-gray-200 text-gray-500 hover:bg-gray-100 transition-colors"
                >
                  Reset to Defaults
                </button>
              </div>

              {pushDeliverySummary && (
                <div className="mt-3 pt-3 border-t border-gray-200">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Push Delivery (7d)</span>
                    <button
                      onClick={() => onNavigate && onNavigate('notifications')}
                      className="text-[10px] text-violet-600 hover:text-violet-700 font-medium"
                    >
                      View Details
                    </button>
                  </div>
                  <div className="grid grid-cols-4 gap-2">
                    <div className="text-center">
                      <p className="text-sm font-bold text-gray-900">{pushDeliverySummary.total_dispatches}</p>
                      <p className="text-[9px] text-gray-400">Dispatches</p>
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-bold text-emerald-600">{pushDeliverySummary.total_sent}</p>
                      <p className="text-[9px] text-gray-400">Sent</p>
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-bold text-red-500">{pushDeliverySummary.total_failed}</p>
                      <p className="text-[9px] text-gray-400">Failed</p>
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-bold text-amber-500">{pushDeliverySummary.total_expired}</p>
                      <p className="text-[9px] text-gray-400">Expired</p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

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
                  endpoint_down: 'red',
                  auto_block_expired: 'amber',
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
                      {alert.threshold_snapshot && alert.threshold_snapshot.metric != null && alert.threshold_snapshot.value != null && (
                        <div className={`flex items-center gap-2 mt-1 text-[10px] px-2 py-1 rounded ${alert.acknowledged ? 'bg-gray-100 text-gray-400' : 'bg-white/60 text-gray-500'}`}>
                          <span className="font-medium">Limit:</span>
                          <span>{alert.threshold_snapshot.metric.replace(/_/g, ' ')} &gt; {alert.threshold_snapshot.value}{alert.threshold_snapshot.metric.includes('pct') ? '%' : alert.threshold_snapshot.metric.includes('ms') ? 'ms' : ''}</span>
                          {alert.threshold_snapshot.actual != null && (<>
                            <span className="text-gray-300">|</span>
                            <span className="font-medium">Actual:</span>
                            <span className={alert.acknowledged ? '' : isRed ? 'text-red-600' : 'text-amber-600'}>{alert.threshold_snapshot.actual}{alert.threshold_snapshot.metric.includes('pct') ? '%' : alert.threshold_snapshot.metric.includes('ms') ? 'ms' : ''}</span>
                          </>)}
                        </div>
                      )}
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

            {alertHistory.alerts.filter(a => {
              if (alertFilter === 'unacknowledged') return !a.acknowledged;
              if (alertFilter === 'acknowledged') return a.acknowledged;
              return true;
            }).length === 0 && (
              <p className="text-center text-[11px] text-gray-400 py-4">No alerts matching this filter</p>
            )}
          </div>
          )}
        </GlassCard>
      )}

      {indexNowStats && (
        <GlassCard className="p-5">
          <div className="flex items-center gap-2 mb-4">
            <Search size={16} className="text-green-500" />
            <h3 className="text-gray-700 font-semibold">IndexNow Push Status</h3>
            <button
              onClick={async () => {
                if (resubmittingIndexNow) return;
                setResubmittingIndexNow(true);
                try {
                  const res = await axios.post(`${API_BASE}/admin/indexnow/resubmit-recent`, {}, adminHdr(adminToken));
                  const d = res.data || {};
                  const sd = d.sitemap_diff || {};
                  setResubmitMessage(
                    `Pushed ${d.recent_urls_pushed ?? 0} recent · sitemap diff: ${sd.new_queued ?? 0} new (${sd.sitemap_total ?? 0} total)`
                  );
                  try {
                    const statsRes = await axios.get(`${API_BASE}/admin/indexnow/stats`, adminHdr(adminToken));
                    setIndexNowStats(statsRes.data);
                  } catch {}
                } catch (e) {
                  setResubmitMessage(`Re-submit failed: ${e?.response?.data?.detail || e.message || 'unknown error'}`);
                } finally {
                  setResubmittingIndexNow(false);
                  setTimeout(() => setResubmitMessage(''), 8000);
                }
              }}
              disabled={resubmittingIndexNow}
              className="ml-auto text-[10px] px-2.5 py-1 rounded-md bg-green-600 text-white hover:bg-green-700 transition-colors font-medium flex items-center gap-1 disabled:opacity-50"
              title="Re-submit recent URLs and any new sitemap entries to IndexNow"
            >
              <RotateCcw size={10} className={resubmittingIndexNow ? 'animate-spin' : ''} />
              {resubmittingIndexNow ? 'Re-submitting…' : 'Re-submit recent URLs to search engines'}
            </button>
          </div>
          {resubmitMessage && (
            <div className="mb-3 text-[11px] text-gray-600 bg-green-50 border border-green-200 rounded-md px-3 py-1.5">
              {resubmitMessage}
            </div>
          )}

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

          {indexNowStats.sitemap_diff_latest && (
            <div className="mb-4 rounded-lg border border-indigo-200 bg-indigo-50 p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-indigo-700 font-semibold uppercase tracking-wider">Sitemap Diff</span>
                <span className="text-[10px] text-gray-500">
                  Last run: {indexNowStats.sitemap_diff_latest.ran_at ? new Date(indexNowStats.sitemap_diff_latest.ran_at).toLocaleString() : '—'}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded-md bg-white border border-indigo-100 py-1.5">
                  <p className="text-indigo-700 font-bold text-sm">{(indexNowStats.sitemap_diff_latest.sitemap_total ?? 0).toLocaleString()}</p>
                  <p className="text-[9px] text-gray-500">Sitemap Total</p>
                </div>
                <div className="rounded-md bg-white border border-indigo-100 py-1.5">
                  <p className="text-emerald-700 font-bold text-sm">{(indexNowStats.sitemap_diff_latest.new_queued ?? 0).toLocaleString()}</p>
                  <p className="text-[9px] text-gray-500">New Queued</p>
                </div>
                <div className="rounded-md bg-white border border-indigo-100 py-1.5">
                  <p className="text-amber-700 font-bold text-sm">{(indexNowStats.sitemap_diff_latest.skipped_capacity ?? 0).toLocaleString()}</p>
                  <p className="text-[9px] text-gray-500">Skipped (capacity)</p>
                </div>
              </div>
              {indexNowStats.sitemap_diff_history?.length > 1 && (
                <div className="mt-3">
                  <div className="text-[10px] text-gray-500 font-semibold mb-1 uppercase tracking-wider">Recent Runs</div>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {indexNowStats.sitemap_diff_history.map((run, i) => (
                      <div key={i} className="flex items-center gap-2 text-[10px] py-1 px-2 rounded bg-white border border-indigo-100">
                        <span className="text-gray-500 min-w-[140px]">
                          {run.ran_at ? new Date(run.ran_at).toLocaleString() : '—'}
                        </span>
                        <span className="text-gray-700">total <span className="font-mono font-semibold">{(run.sitemap_total ?? 0).toLocaleString()}</span></span>
                        <span className="text-emerald-700">new <span className="font-mono font-semibold">{(run.new_queued ?? 0).toLocaleString()}</span></span>
                        <span className="text-gray-500">already <span className="font-mono">{(run.already_submitted ?? 0).toLocaleString()}</span></span>
                        {(run.skipped_capacity ?? 0) > 0 && (
                          <span className="text-amber-600 ml-auto">skipped <span className="font-mono font-semibold">{run.skipped_capacity.toLocaleString()}</span></span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
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

          {indexNowStats.endpoint_health?.length > 0 && (
            <div className="mt-4">
              <div className="text-[10px] text-gray-400 font-semibold mb-2 uppercase tracking-wider">Endpoint Health</div>
              <div className="space-y-1.5">
                {indexNowStats.endpoint_health.map((ep, i) => {
                  const host = ep.endpoint.replace(/https?:\/\//, '').split('/')[0];
                  const statusColor = ep.is_dead_lettered
                    ? 'bg-red-400'
                    : ep.consecutive_failures > 0
                      ? 'bg-amber-400'
                      : 'bg-green-400';
                  const statusBg = ep.is_dead_lettered
                    ? 'bg-red-50 border-red-200'
                    : ep.consecutive_failures > 0
                      ? 'bg-amber-50 border-amber-200'
                      : 'bg-green-50 border-green-200';
                  return (
                    <div key={i} className={`flex items-center gap-2 text-[10px] py-2 px-3 rounded-lg border ${statusBg}`}>
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusColor}`} />
                      <span className="text-gray-700 font-medium min-w-[120px]">{host}</span>
                      <span className="text-gray-500">
                        {ep.total_successes}&#x2F;{ep.total_successes + ep.total_failures} ok
                      </span>
                      {ep.consecutive_failures > 0 && (
                        <span className="text-amber-600 flex items-center gap-0.5">
                          <AlertTriangle size={10} />
                          {ep.consecutive_failures} consecutive fail{ep.consecutive_failures !== 1 ? 's' : ''}
                        </span>
                      )}
                      {!ep.is_available && ep.backoff_remaining_seconds > 0 && (
                        <span className="text-orange-500 flex items-center gap-0.5">
                          <Clock size={10} />
                          backoff {Math.ceil(ep.backoff_remaining_seconds)}s
                        </span>
                      )}
                      {ep.is_dead_lettered && (
                        <span className="text-red-600 font-semibold flex items-center gap-0.5">
                          <AlertCircle size={10} />
                          dead-lettered
                        </span>
                      )}
                      {ep.pending_retry_urls > 0 && (
                        <span className="text-gray-500">{ep.pending_retry_urls} retry queued</span>
                      )}
                      {ep.is_dead_lettered && (
                        <button
                          onClick={() => handleRetryEndpoint(ep.endpoint)}
                          disabled={retryingEndpoint === ep.endpoint}
                          className="text-[9px] px-2 py-0.5 rounded-md bg-white text-red-600 border border-red-200 hover:bg-red-50 hover:text-red-700 transition-colors font-medium flex items-center gap-1 disabled:opacity-50"
                        >
                          <RotateCcw size={9} className={retryingEndpoint === ep.endpoint ? 'animate-spin' : ''} />
                          {retryingEndpoint === ep.endpoint ? 'Retrying...' : 'Retry'}
                        </button>
                      )}
                      <span className={`ml-auto text-[9px] px-1.5 py-0.5 rounded font-medium ${ep.is_dead_lettered ? 'text-red-700 bg-red-100' : ep.consecutive_failures > 0 ? 'text-amber-700 bg-amber-100' : 'text-green-700 bg-green-100'}`}>
                        {ep.is_dead_lettered ? 'DOWN' : ep.consecutive_failures > 0 ? 'DEGRADED' : 'HEALTHY'}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {indexNowStats.endpoint_health_history && Object.keys(indexNowStats.endpoint_health_history).length > 0 && (
            <div className="mt-4">
              <div className="text-[10px] text-gray-400 font-semibold mb-2 uppercase tracking-wider">Endpoint Health History</div>
              <div className="space-y-3 max-h-48 overflow-y-auto">
                {Object.entries(indexNowStats.endpoint_health_history).map(([endpoint, events]) => {
                  const host = endpoint.replace(/https?:\/\//, '').split('/')[0] || '?';
                  return (
                    <div key={endpoint}>
                      <div className="text-[10px] text-gray-600 font-semibold mb-1">{host}</div>
                      <div className="space-y-1">
                        {events.map((evt, i) => {
                          const eventColor = evt.event === 'recovered'
                            ? 'bg-green-400' : evt.event === 'dead_lettered'
                            ? 'bg-red-400' : evt.event === 'manual_retry'
                            ? 'bg-blue-400' : 'bg-amber-400';
                          const eventLabel = evt.event === 'recovered'
                            ? 'Recovered' : evt.event === 'dead_lettered'
                            ? 'Dead-lettered' : evt.event === 'manual_retry'
                            ? 'Manual retry' : 'Failure started';
                          const ts = evt.timestamp ? new Date(evt.timestamp) : null;
                          const ago = ts ? (() => {
                            const diff = Math.floor((Date.now() - ts.getTime()) / 1000);
                            if (diff < 60) return `${diff}s ago`;
                            if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
                            if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
                            return `${Math.floor(diff / 86400)}d ago`;
                          })() : '';
                          const detail = evt.details?.previous_consecutive_failures
                            ? `after ${evt.details.previous_consecutive_failures} failures`
                            : evt.details?.consecutive_failures
                            ? `${evt.details.consecutive_failures} consecutive`
                            : evt.details?.backoff_seconds
                            ? `backoff ${evt.details.backoff_seconds}s`
                            : '';
                          return (
                            <div key={i} className="flex items-center gap-2 text-[10px] py-1.5 px-2 rounded-lg bg-gray-50 border border-gray-100">
                              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${eventColor}`} />
                              <span className="text-gray-500 min-w-[40px]">{ago}</span>
                              <span className={evt.event === 'recovered' ? 'text-green-600' : evt.event === 'dead_lettered' ? 'text-red-600' : evt.event === 'manual_retry' ? 'text-blue-600' : 'text-amber-600'}>{eventLabel}</span>
                              {detail && <span className="text-gray-400">{detail}</span>}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
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

      <GlassCard className="p-5">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <Zap size={14} className="text-violet-500" />
            <h3 className="text-gray-700 font-semibold text-sm">Chat Speed-up Scoreboard</h3>
            <span className="text-xs text-gray-400">cache &amp; speculative-web impact</span>
          </div>
          <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-0.5">
            {[7, 14, 30].map(d => (
              <button
                key={d}
                onClick={() => setSpeedupDays(d)}
                disabled={speedupLoading}
                className={`text-xs px-2.5 py-1 rounded-md transition-colors ${
                  speedupDays === d
                    ? 'bg-white text-violet-600 font-medium shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
                data-testid={`speedup-period-${d}`}
              >
                {d}d
              </button>
            ))}
            {speedupLoading && <Loader2 size={11} className="animate-spin text-gray-400 ml-1" />}
          </div>
        </div>

        {(() => {
          const totals = chatSpeedups?.totals || {};
          const daily = chatSpeedups?.daily || [];
          const warmRuns = chatSpeedups?.warm_runs || [];
          const hasData = chatSpeedups?.has_data;
          const stats = [
            { label: 'Cache hit', value: `${totals.cache_hit_pct ?? 0}%`, sub: `${(totals.early_cache_hits ?? 0) + (totals.pre_sse_cache_hits ?? 0)} hits`, color: '#10b981' },
            { label: 'Warmed cache', value: `${totals.warmed_cache_hit_pct ?? 0}%`, sub: `${totals.early_cache_hits ?? 0} early`, color: '#7c3aed' },
            { label: 'Speculative web used', value: `${totals.speculative_web_used_pct ?? 0}%`, sub: `${totals.speculative_web_used ?? 0} / ${totals.speculative_web_started ?? 0}`, color: '#f59e0b' },
            { label: 'Avg TTFB', value: `${totals.avg_ttfb_ms ?? 0}ms`, sub: `${totals.ttfb_samples ?? 0} samples`, color: '#3b82f6' },
          ];
          return (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {stats.map(s => (
                  <div key={s.label} className="rounded-xl p-3 bg-gray-50 border border-gray-100">
                    <p className="text-xs text-gray-500 font-medium">{s.label}</p>
                    <p className="text-xl font-bold mt-1" style={{ color: s.color }}>{s.value}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{s.sub}</p>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="rounded-xl p-3 bg-gray-50 border border-gray-100">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-gray-500 font-medium">Cache hit % &middot; Avg TTFB</span>
                    <span className="text-xs text-gray-400">{totals.chats_total ?? 0} chats</span>
                  </div>
                  {hasData && daily.length > 0 ? (
                    <ResponsiveContainer width="100%" height={130}>
                      <LineChart data={daily}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                        <XAxis dataKey="date" tick={{ fontSize: 9, fill: '#9ca3af' }} tickFormatter={d => d.slice(5)} />
                        <YAxis yAxisId="pct" orientation="left" tick={{ fontSize: 9, fill: '#9ca3af' }} domain={[0, 100]} unit="%" />
                        <YAxis yAxisId="ms" orientation="right" tick={{ fontSize: 9, fill: '#9ca3af' }} domain={[0, 'auto']} />
                        <Tooltip content={<ChartTooltip />} />
                        <Legend wrapperStyle={{ fontSize: 9 }} />
                        <Line yAxisId="pct" type="monotone" dataKey="cache_hit_pct" stroke="#10b981" strokeWidth={2} dot={false} name="Cache %" />
                        <Line yAxisId="pct" type="monotone" dataKey="warmed_cache_hit_pct" stroke="#7c3aed" strokeWidth={2} dot={false} name="Warmed %" />
                        <Line yAxisId="ms" type="monotone" dataKey="avg_ttfb_ms" stroke="#3b82f6" strokeWidth={2} dot={false} name="TTFB ms" />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex flex-col items-center justify-center h-[130px] text-gray-400 text-xs gap-1">
                      <Zap size={20} className="opacity-30" />
                      <span>No chat speed-up data yet</span>
                      <span className="text-xs text-gray-300">Populates after chats are served</span>
                    </div>
                  )}
                </div>

                <div className="rounded-xl p-3 bg-gray-50 border border-gray-100">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-gray-500 font-medium flex items-center gap-1">
                      <RefreshCw size={11} /> Recent cache-warm runs
                    </span>
                    <span className="text-xs text-gray-400">6h pre-warm cycle</span>
                  </div>
                  {warmRuns.length > 0 ? (
                    <div className="space-y-1.5 max-h-[130px] overflow-y-auto pr-1" data-testid="speedup-warm-runs">
                      {warmRuns.slice(0, 8).map((r, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <span className="text-gray-400 font-mono w-[88px] flex-shrink-0">
                            {r.ts ? new Date(r.ts).toLocaleString(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}
                          </span>
                          <span className="text-emerald-600 font-mono">{r.warmed}w</span>
                          <span className="text-gray-400 font-mono">{r.already_cached}c</span>
                          <span className={`font-mono ${r.failed > 0 ? 'text-red-500' : 'text-gray-300'}`}>{r.failed}f</span>
                          <span className="text-gray-400 truncate ml-auto">{r.source}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center h-[130px] text-gray-400 text-xs gap-1">
                      <RefreshCw size={20} className="opacity-30" />
                      <span>No warm runs in window</span>
                      <span className="text-xs text-gray-300">Pre-warm cycle runs every 6h</span>
                    </div>
                  )}
                </div>
              </div>

              <p className="text-xs text-gray-400">
                Window: last {chatSpeedups?.period_days ?? speedupDays} day{(chatSpeedups?.period_days ?? speedupDays) === 1 ? '' : 's'}
                {totals.avg_total_ms ? <> &middot; Avg full chat: {totals.avg_total_ms}ms</> : null}
                {totals.instant_fastpath ? <> &middot; Instant fast-path fires: {totals.instant_fastpath}</> : null}
              </p>
            </div>
          );
        })()}
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
