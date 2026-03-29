import { useState, useEffect, useCallback } from 'react';
import AdminQuickLinks from './AdminQuickLinks';
import { Loader2, RefreshCw, Eye, Globe, TrendingUp, Users, Search, BookOpen, Bot,
  FileText, ExternalLink, BarChart2, Flame, DollarSign, Zap, Target, ArrowUpRight, ArrowDownRight,
  CheckCircle, AlertCircle, AlertTriangle, Link as LinkIcon, Calendar, MessageSquare } from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Legend, LineChart, Line, PieChart, Pie, Cell,
} from 'recharts';
import axios from 'axios';
import { adminGetAnalytics, adminGetRevenue, adminGetPredictor,
  adminGetGA4Status, adminGetGA4AuthUrl, adminTestGA4, API_BASE,
  pageConversions, adminGetDailyAnalytics } from '@/utils/api';
import { toast } from 'sonner';

const TT = {
  contentStyle: {
    background: '#0f172a', border: '1px solid #1e293b',
    borderRadius: '8px', color: '#e2e8f0', fontSize: 12,
  },
};

const PLAN_COLORS = { free: '#475569', starter: '#7c3aed', pro: '#10b981' };
const FUNNEL_COLORS = ['#3b82f6', '#8b5cf6', '#10b981'];

function Card({ title, children, empty, emptyMsg, action, error, onRetry }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-slate-400 text-sm font-medium">{title}</h3>
        <div className="flex items-center gap-2">
          {error && onRetry && (
            <button onClick={onRetry} className="text-xs text-amber-400 hover:text-white px-2 py-0.5 rounded bg-amber-500/10 hover:bg-amber-500/20 transition-colors flex items-center gap-1">
              <RefreshCw size={10} /> Retry
            </button>
          )}
          {action}
        </div>
      </div>
      {error
        ? (
          <div className="flex items-center gap-2 py-6 justify-center">
            <AlertTriangle size={14} className="text-amber-400" />
            <p className="text-amber-400 text-sm">Failed to load — data unavailable</p>
          </div>
        )
        : empty
          ? <p className="text-slate-600 text-sm text-center py-6">{emptyMsg || 'No data yet'}</p>
          : children}
    </div>
  );
}

function Stat({ icon: Icon, label, value, color, sub, trend }) {
  const up = trend > 0;
  return (
    <div className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-xl">
      <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: `${color}22` }}>
        <Icon size={15} style={{ color }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-white font-bold text-lg leading-none truncate">{value ?? '—'}</p>
        <p className="text-slate-500 text-xs mt-0.5">{label}</p>
        {sub && <p className="text-slate-600 text-[10px] mt-0.5">{sub}</p>}
      </div>
      {trend !== undefined && (
        <div className={`flex items-center gap-0.5 text-xs font-semibold flex-shrink-0 ${up ? 'text-emerald-400' : 'text-red-400'}`}>
          {up ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
          {Math.abs(trend)}%
        </div>
      )}
    </div>
  );
}

function InsightBar({ label, value, max, color }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  const heat = pct > 70 ? '#ef4444' : pct > 40 ? '#f59e0b' : '#3b82f6';
  const c = color || heat;
  return (
    <div className="flex items-center gap-2">
      <Flame size={11} style={{ color: c }} className="flex-shrink-0" />
      <span className="text-slate-300 text-sm flex-1 truncate">{label}</span>
      <div className="w-20 h-2 rounded-full bg-slate-800 overflow-hidden flex-shrink-0">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: c }} />
      </div>
      <span className="text-slate-500 text-xs w-8 text-right flex-shrink-0">{value}</span>
    </div>
  );
}

const fmt = (d) => d?.slice(5) ?? d;
const fmtInr = (n) => n >= 100000 ? `₹${(n / 100000).toFixed(1)}L` : n >= 1000 ? `₹${(n / 1000).toFixed(1)}k` : `₹${n}`;

export default function AdminAnalytics({ adminToken, onNavigate }) {
  const [data, setData]         = useState(null);
  const [funnel, setFunnel]     = useState(null);
  const [heatmap, setHeatmap]   = useState(null);
  const [revenue, setRevenue]   = useState(null);
  const [predict, setPredict]   = useState(null);
  const [ga4Status, setGa4Status] = useState(null);
  const [loading, setLoading]   = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [tab, setTab]           = useState('overview');
  const [ga4Testing, setGa4Testing] = useState(false);
  const [ga4TestResult, setGa4TestResult] = useState(null);
  const [pageConvData, setPageConvData] = useState(null);
  const [pageConvLoading, setPageConvLoading] = useState(false);
  const [dailyData, setDailyData] = useState(null);
  const [dailyLoading, setDailyLoading] = useState(false);
  const [dailyDays, setDailyDays] = useState(30);
  const [widgetErrors, setWidgetErrors] = useState({});

  const h = { withCredentials: true };

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true); else setRefreshing(true);
    const [r1, r2, r3, r4, r5, r6] = await Promise.allSettled([
      adminGetAnalytics(adminToken),
      axios.get(`${API_BASE}/admin/analytics/funnel`, h),
      axios.get(`${API_BASE}/admin/analytics/content-heatmap`, h),
      adminGetRevenue(adminToken, 30),
      adminGetPredictor(adminToken),
      adminGetGA4Status(adminToken),
    ]);
    const errs = {};
    if (r1.status === 'fulfilled') setData(r1.value.data); else { errs.overview = true; setData(null); }
    if (r2.status === 'fulfilled') setFunnel(r2.value.data); else { errs.funnel = true; setFunnel(null); }
    if (r3.status === 'fulfilled') setHeatmap(r3.value.data); else { errs.heatmap = true; setHeatmap(null); }
    if (r4.status === 'fulfilled') setRevenue(r4.value.data); else { errs.revenue = true; setRevenue(null); }
    if (r5.status === 'fulfilled') setPredict(r5.value.data); else { errs.predictions = true; setPredict(null); }
    if (r6.status === 'fulfilled') setGa4Status(r6.value.data); else errs.ga4 = true;
    setWidgetErrors(errs);
    setLastRefresh(new Date());
    setLoading(false);
    setRefreshing(false);
  }, [adminToken]);

  const handleGA4Connect = async () => {
    const redirectUri = `${window.location.origin}/admin?ga4callback=1`;
    try {
      const r = await adminGetGA4AuthUrl(adminToken, redirectUri);
      window.open(r.data.url, '_blank', 'width=600,height=700');
    } catch (e) {
      toast.error('Failed to get GA4 auth URL');
    }
  };

  const handleGA4Test = async () => {
    setGa4Testing(true);
    setGa4TestResult(null);
    try {
      const r = await adminTestGA4(adminToken);
      setGa4TestResult(r.data);
    } catch (e) {
      setGa4TestResult({ ok: false, reason: 'Request failed' });
    }
    setGa4Testing(false);
  };

  const loadPageConversions = useCallback(async () => {
    setPageConvLoading(true);
    try {
      const r = await pageConversions(adminToken, 30);
      setPageConvData(r.data);
    } catch { toast.error('Failed to load page conversions'); }
    finally { setPageConvLoading(false); }
  }, [adminToken]);

  const loadDailyAnalytics = useCallback(async (days = dailyDays) => {
    setDailyLoading(true);
    try {
      const r = await adminGetDailyAnalytics(adminToken, days);
      setDailyData(r.data);
    } catch { toast.error('Failed to load daily analytics'); }
    finally { setDailyLoading(false); }
  }, [adminToken, dailyDays]);

  useEffect(() => {
    load();
    const iv = setInterval(() => load(true), 60000);
    return () => clearInterval(iv);
  }, [load]);

  useEffect(() => {
    if (tab === 'pages') loadPageConversions();
  }, [tab, loadPageConversions]);

  useEffect(() => {
    if (tab === 'daily') loadDailyAnalytics(dailyDays);
  }, [tab, dailyDays]);

  if (loading) return (
    <div className="flex justify-center p-10">
      <Loader2 size={24} className="animate-spin text-slate-400" />
    </div>
  );
  if (!data) return (
    <div className="p-6">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
        <p className="text-slate-400">Unable to load analytics</p>
        <button onClick={load} className="mt-3 text-sm text-violet-400 hover:underline">Retry</button>
      </div>
    </div>
  );

  const vs             = data?.visitor_stats || {};
  const hasDailySignup = data?.daily_signups?.some(d => d.count > 0);
  const hasPlanUsage   = data?.plan_usage && Object.keys(data.plan_usage).length > 0;
  const hasDailyVis    = vs.daily_visitors?.some(d => d.visitors > 0 || d.page_views > 0);
  const hasTopPages    = data?.top_pages?.length > 0;
  const hasReferrers   = data?.top_referrers?.length > 0;

  const mrr         = predict?.current_mrr_inr || 0;
  const predicted   = predict?.predicted_mrr_inr || 0;
  const growth      = predict?.growth_rate_pct || 0;
  const cohorts     = revenue?.cohorts || {};
  const dailyRev    = revenue?.daily_revenue || [];
  const paidUsers   = funnel?.funnel?.find(f => f.stage === 'Paid User')?.count || 0;
  const arpu        = paidUsers > 0 ? Math.round(mrr / paidUsers) : 0;
  const ltv         = arpu > 0 ? Math.round(arpu * 12) : 0;

  // AI-derived content insight from heatmap
  const topSubject  = heatmap?.top_subjects?.[0];
  const topSearch   = heatmap?.top_searches?.[0];
  const aiInsight   = topSubject
    ? `"${topSubject.name}" drives ${topSubject.views} views — push MCQs & Important Questions for it to maximise conversions.`
    : topSearch
    ? `Top search query: "${topSearch.query}" — consider generating dedicated SEO pages for it.`
    : null;

  const cohortData = Object.entries(cohorts).map(([plan, count]) => ({ plan, count }));

  const TABS = [
    { id: 'overview',  label: 'Overview' },
    { id: 'daily',     label: '📅 Daily' },
    { id: 'funnel',    label: 'Funnel' },
    { id: 'heatmap',   label: 'Heatmap' },
    { id: 'seo',       label: 'SEO & Pages' },
    { id: 'revenue',   label: '₹ Revenue' },
    { id: 'predict',   label: '🔮 Predictions' },
    { id: 'pages',     label: '📄 Page Conversions' },
  ];

  return (
    <div className="p-6 space-y-5">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-slate-200 font-semibold">Analytics</h2>
          {lastRefresh && (
            <p className="text-slate-600 text-xs mt-0.5">
              Updated {Math.floor((Date.now() - lastRefresh) / 1000)}s ago · auto-refreshes every 60s
            </p>
          )}
        </div>
        <button onClick={() => load(true)} disabled={refreshing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white bg-slate-800 border border-slate-700 transition-all">
          <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 flex-wrap bg-slate-800/50 rounded-xl p-1 w-fit">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              tab === t.id ? 'bg-violet-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ── OVERVIEW ── */}
      {tab === 'overview' && (
        <>
          {widgetErrors.overview && (
            <div className="flex items-center gap-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
              <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />
              <p className="text-xs text-amber-300 flex-1">Overview data failed to load — some metrics unavailable.</p>
              <button onClick={() => load(true)} className="text-xs text-amber-300 hover:text-white px-2 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 transition-colors">Retry</button>
            </div>
          )}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat icon={Globe}      label="Total Visitors"   value={vs.total_visitors?.toLocaleString()} color="#06b6d4" />
            <Stat icon={TrendingUp} label="Visitors Today"   value={vs.visitors_today}   color="#f97316" />
            <Stat icon={Eye}        label="Page Views Today" value={vs.page_views_today} color="#ec4899" />
            <Stat icon={Users}      label="Active Users"     value={data?.active_users}  color="#10b981" />
          </div>

          {mrr > 0 && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <Stat icon={DollarSign} label="MRR (30d)"       value={fmtInr(mrr)}       color="#10b981" trend={growth} />
              <Stat icon={TrendingUp} label="Predicted MRR"   value={fmtInr(predicted)} color="#7c3aed" />
              <Stat icon={Target}     label="ARPU"            value={fmtInr(arpu)}       color="#f59e0b" />
              <Stat icon={Zap}        label="LTV (12-mo)"     value={fmtInr(ltv)}        color="#06b6d4" />
            </div>
          )}

          <Card title="Daily Visitors & Page Views — Last 7 Days"
            empty={!hasDailyVis} emptyMsg="No visitor data yet">
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={vs.daily_visitors || []} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={fmt} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                <Tooltip {...TT} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} />
                <Area type="monotone" dataKey="visitors"   name="Unique Visitors" stroke="#06b6d4" fill="rgba(6,182,212,0.12)"  strokeWidth={2} />
                <Area type="monotone" dataKey="page_views" name="Page Views"      stroke="#8b5cf6" fill="rgba(139,92,246,0.10)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
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
      )}

      {/* ── DAILY ANALYTICS ── */}
      {tab === 'daily' && (
        <div className="space-y-5">
          {/* Date-range picker */}
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
                {/* Summary metric cards */}
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

                {/* Visitors & Page Views chart */}
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

                {/* Signups chart */}
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

                {/* Messages & AI interactions */}
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

                {/* Sessions & GA4 metrics */}
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
      )}

      {/* ── FUNNEL ── */}
      {tab === 'funnel' && (
        funnel ? (
          <div className="space-y-4">
            <Card title="Conversion Funnel">
              <div className="space-y-3">
                {funnel.funnel?.map((stage, i) => (
                  <div key={i}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-white text-sm font-medium">{stage.stage}</span>
                      <span className="text-slate-400 text-sm">{stage.count?.toLocaleString()} ({stage.pct}%)</span>
                    </div>
                    <div className="h-8 rounded-lg overflow-hidden bg-slate-800">
                      <div className="h-full rounded-lg transition-all duration-500"
                        style={{ width: `${stage.pct}%`, background: `linear-gradient(90deg, ${FUNNEL_COLORS[i]||'#8b5cf6'}, ${FUNNEL_COLORS[i]||'#8b5cf6'}aa)` }} />
                    </div>
                  </div>
                ))}
              </div>
            </Card>
            <div className="grid grid-cols-2 gap-3">
              <Stat icon={DollarSign} label="Revenue / Paid User" value={`₹${funnel.revenue_per_user || 0}`}  color="#10b981" />
              <Stat icon={TrendingUp} label="Conversion Rate"     value={`${funnel.conversion_rate || 0}%`} color="#8b5cf6" />
            </div>
          </div>
        ) : (
          <Card title="Conversion Funnel" error={!!widgetErrors.funnel} onRetry={() => load(true)}
            empty={!widgetErrors.funnel} emptyMsg="Funnel data loading…" />
        )
      )}

      {/* ── HEATMAP ── */}
      {tab === 'heatmap' && (
        heatmap ? (
          <div className="space-y-4">
            {aiInsight && (
              <div className="flex items-start gap-3 p-4 rounded-xl border"
                style={{ background: 'rgba(139,92,246,0.07)', borderColor: 'rgba(139,92,246,0.20)' }}>
                <Zap size={15} className="text-violet-400 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-xs font-semibold text-violet-300 mb-0.5">AI Content Insight</p>
                  <p className="text-slate-300 text-sm leading-relaxed">{aiInsight}</p>
                </div>
              </div>
            )}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <Card title="Top Subjects by Activity"
                empty={!heatmap.top_subjects?.length} emptyMsg="No subject activity yet">
                {heatmap.top_subjects?.length > 0 && (
                  <div className="space-y-2">
                    {heatmap.top_subjects.map((s, i) => (
                      <InsightBar key={i} label={s.name} value={s.views}
                        max={heatmap.top_subjects[0]?.views || 1} />
                    ))}
                  </div>
                )}
              </Card>
              <Card title="Top Search Queries"
                empty={!heatmap.top_searches?.length} emptyMsg="No search data yet">
                {heatmap.top_searches?.length > 0 && (
                  <div className="space-y-2">
                    {heatmap.top_searches.map((s, i) => (
                      <div key={i} className="flex items-center gap-2 p-1.5 hover:bg-slate-800/50 rounded-lg">
                        <Search size={12} className="text-blue-400 flex-shrink-0" />
                        <span className="text-slate-300 text-sm flex-1 truncate">{s.query}</span>
                        <span className="text-slate-500 text-xs flex-shrink-0">{s.count}×</span>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>
          </div>
        ) : (
          <Card title="Content Heatmap" error={!!widgetErrors.heatmap} onRetry={() => load(true)}
            empty={!widgetErrors.heatmap} emptyMsg="Heatmap data loading…" />
        )
      )}

      {/* ── SEO & PAGES ── */}
      {tab === 'seo' && (
        <>
          {onNavigate && (
            <div className="flex justify-end mb-3">
              <button
                onClick={() => onNavigate('seomanager')}
                className="flex items-center gap-1.5 h-8 px-4 rounded-lg text-xs font-semibold transition-all hover:opacity-80"
                style={{ background: 'rgba(6,182,212,0.12)', color: '#67e8f9', border: '1px solid rgba(6,182,212,0.28)' }}
              >
                <Globe size={12} /> Go to SEO Manager →
              </button>
            </div>
          )}
          {/* GA4 Connection Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-8 h-8 rounded-lg bg-blue-900/40 flex items-center justify-center">
                <Globe size={14} className="text-blue-400" />
              </div>
              <div className="flex-1">
                <h3 className="text-slate-200 font-medium text-sm">Google Analytics 4</h3>
                <p className="text-slate-500 text-xs">Real visitor & page data from GA4</p>
              </div>
              {ga4Status && (
                <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                  ga4Status.connected ? 'bg-emerald-900/40 text-emerald-400' : 'bg-slate-800 text-slate-400'
                }`}>
                  {ga4Status.connected
                    ? <><CheckCircle size={11} /> Connected</>
                    : <><AlertCircle size={11} /> Not connected</>}
                </div>
              )}
            </div>

            {ga4Status && !ga4Status.connected && (
              <div className="space-y-3">
                <p className="text-slate-400 text-sm">
                  Connect GA4 to pull real visitor counts, page views, and top pages directly into this dashboard.
                </p>
                <div className="bg-slate-800/60 rounded-lg p-3 space-y-1.5 text-xs text-slate-400">
                  <p className="font-medium text-slate-300 mb-1">Setup steps:</p>
                  <p>1. Add <code className="text-violet-300">GA4_REFRESH_TOKEN</code> secret after connecting below</p>
                  <p>2. Your Property ID is already saved: <code className="text-emerald-300">{ga4Status.property_id || 'not set'}</code></p>
                  <p>3. OAuth credentials: {ga4Status.client_id_set ? '✓ Client ID' : '✗ Client ID'} · {ga4Status.client_secret_set ? '✓ Secret' : '✗ Secret'}</p>
                </div>
                <button onClick={handleGA4Connect}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors">
                  <LinkIcon size={13} /> Connect Google Analytics
                </button>
              </div>
            )}

            {ga4Status?.connected && (
              <div className="flex items-center gap-3 flex-wrap">
                <p className="text-slate-400 text-sm flex-1">Property <code className="text-emerald-300">{ga4Status.property_id}</code> · Data flows automatically into dashboard</p>
                <button onClick={handleGA4Test} disabled={ga4Testing}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-slate-300 hover:text-white border border-slate-700 transition-all">
                  {ga4Testing ? <Loader2 size={11} className="animate-spin" /> : <BarChart2 size={11} />} Test Connection
                </button>
              </div>
            )}

            {ga4TestResult && (
              <div className={`mt-3 p-3 rounded-lg text-xs ${ga4TestResult.ok ? 'bg-emerald-900/30 text-emerald-300 border border-emerald-800/40' : 'bg-red-900/30 text-red-300 border border-red-800/40'}`}>
                {ga4TestResult.ok
                  ? `✓ GA4 working — ${ga4TestResult.stats?.total_visitors?.toLocaleString() || 0} total visitors tracked`
                  : `✗ ${ga4TestResult.reason}`}
              </div>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Stat icon={Eye}       label="Total Visitors"  value={vs.total_visitors?.toLocaleString() || 0} color="#8b5cf6" />
            <Stat icon={BarChart2} label="Pages Tracked"   value={hasTopPages ? data.top_pages.length : 0}  color="#06b6d4" />
            <Stat icon={Globe}     label="Traffic Sources" value={hasReferrers ? data.top_referrers.length : 0} color="#10b981" />
          </div>

          <Card title="Top Visited Pages" empty={!hasTopPages}
            emptyMsg="No page visit data yet"
            action={
              <a href="/api/seo/sitemap.xml" target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-1 text-xs text-violet-400 hover:underline">
                <ExternalLink size={11} /> Sitemap
              </a>
            }>
            <div className="space-y-1.5">
              {(data.top_pages || []).map((pg, i) => (
                <div key={i} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-slate-800/50 transition-colors">
                  <span className="text-slate-600 text-xs w-5 text-right">{i + 1}</span>
                  <FileText size={11} className="text-violet-400 flex-shrink-0" />
                  <span className="text-slate-300 text-xs flex-1 truncate font-mono">{pg.path}</span>
                  <span className="text-slate-500 text-xs flex-shrink-0">{pg.views} views</span>
                  <span className="text-slate-600 text-xs flex-shrink-0">{pg.unique_visitors} uniq</span>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Traffic Sources (Referrers)" empty={!hasReferrers}
            emptyMsg="No referrer data yet — appears when visitors arrive from external sites or search engines">
            <div className="space-y-2">
              {(data.top_referrers || []).map((ref, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Globe size={11} className="text-cyan-400 flex-shrink-0" />
                  <span className="text-slate-300 text-sm flex-1 truncate">{ref.source || 'Direct'}</span>
                  <span className="text-xs text-slate-500">{ref.count} visits</span>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {/* ── REVENUE ── */}
      {tab === 'revenue' && (
        <div className="space-y-4">
          {widgetErrors.revenue && (
            <div className="flex items-center gap-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
              <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />
              <p className="text-xs text-amber-300 flex-1">Revenue data failed to load.</p>
              <button onClick={() => load(true)} className="text-xs text-amber-300 hover:text-white px-2 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 transition-colors">Retry</button>
            </div>
          )}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat icon={DollarSign} label="MRR (30d)"     value={fmtInr(mrr)}       color="#10b981" trend={growth} />
            <Stat icon={TrendingUp} label="Predicted MRR" value={fmtInr(predicted)} color="#7c3aed"
              sub={growth >= 0 ? `${growth}% MoM growth` : `${Math.abs(growth)}% MoM decline`} />
            <Stat icon={Target}     label="ARPU"          value={fmtInr(arpu)}       color="#f59e0b"
              sub={paidUsers > 0 ? `${paidUsers} paid users` : 'No paid users yet'} />
            <Stat icon={Zap}        label="LTV (12-mo)"   value={fmtInr(ltv)}        color="#06b6d4" sub="Avg lifetime value" />
          </div>

          <Card title="Daily Revenue — Last 30 Days"
            empty={!dailyRev.length} emptyMsg="No payment data yet">
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={dailyRev} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={fmt} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={v => `₹${v}`} />
                <Tooltip {...TT} formatter={v => [`₹${v}`, 'Revenue']} />
                <Line type="monotone" dataKey="revenue_inr" name="Revenue ₹" stroke="#10b981" strokeWidth={2.5}
                  dot={{ r: 3, fill: '#10b981' }} activeDot={{ r: 5 }} />
              </LineChart>
            </ResponsiveContainer>
          </Card>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card title="Users by Plan" empty={!cohortData.length} emptyMsg="No cohort data yet">
              {cohortData.length > 0 && (
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={cohortData} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="plan" tick={{ fill: '#64748b', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 11 }} allowDecimals={false} />
                    <Tooltip {...TT} />
                    <Bar dataKey="count" name="Users" radius={[4, 4, 0, 0]}>
                      {cohortData.map((entry, i) => (
                        <Cell key={i} fill={PLAN_COLORS[entry.plan] || '#8b5cf6'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>

            <Card title="Revenue Summary">
              <div className="space-y-3">
                {[
                  { label: 'Payments (this month)', value: predict?.payments_this_month || 0, color: '#10b981' },
                  { label: 'Payments (last month)',  value: predict?.payments_last_month  || 0, color: '#64748b' },
                  { label: 'Signups (this month)',   value: predict?.signups_this_month   || 0, color: '#7c3aed' },
                  { label: 'Signups (last month)',   value: predict?.signups_last_month   || 0, color: '#64748b' },
                  { label: 'Total payments (30d)',   value: revenue?.total_payments       || 0, color: '#f59e0b' },
                ].map((item, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <span className="text-slate-400 text-sm">{item.label}</span>
                    <span className="font-semibold text-sm" style={{ color: item.color }}>{item.value.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* ── PREDICTIONS ── */}
      {tab === 'predict' && (
        <div className="space-y-4">
          {widgetErrors.predictions && (
            <div className="flex items-center gap-3 p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
              <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />
              <p className="text-xs text-amber-300 flex-1">Predictions data failed to load — showing estimates only.</p>
              <button onClick={() => load(true)} className="text-xs text-amber-300 hover:text-white px-2 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 transition-colors">Retry</button>
            </div>
          )}

          {/* MRR Trajectory */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {[
              { label: 'Current MRR',       value: fmtInr(mrr),       sub: 'last 30 days',          color: '#10b981', icon: DollarSign },
              { label: 'Predicted MRR',     value: fmtInr(predicted), sub: `${growth}% MoM rate`,   color: '#7c3aed', icon: TrendingUp },
              { label: 'Path to ₹1L MRR',
                value: mrr > 0 ? `${Math.max(0, Math.ceil(Math.log(100000 / mrr) / Math.log(1 + Math.max(growth, 1) / 100)))} mo` : '—',
                sub: 'at current growth',  color: '#f59e0b', icon: Target },
            ].map((item, i) => (
              <Stat key={i} icon={item.icon} label={item.label} value={item.value} color={item.color} sub={item.sub} />
            ))}
          </div>

          {/* Content Scale Model */}
          <Card title="Content Scale → Revenue Model">
            <div className="space-y-3">
              {[
                { pages: 100,   est: '₹2–5k',  label: 'Seed phase — 100 SEO pages' },
                { pages: 1000,  est: '₹15–30k', label: 'Growth phase — 1k SEO pages' },
                { pages: 5000,  est: '₹60–90k', label: 'Scale phase — 5k SEO pages' },
                { pages: 10000, est: '₹1–1.5L', label: '₹1Cr MRR target — 10k SEO pages' },
              ].map((row, i) => (
                <div key={i} className="flex items-center gap-3 p-3 rounded-lg bg-slate-800/40">
                  <div className="w-8 h-8 rounded-lg bg-violet-900/40 flex items-center justify-center flex-shrink-0">
                    <FileText size={13} className="text-violet-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-slate-200 text-sm font-medium">{row.label}</p>
                    <p className="text-slate-500 text-xs">{row.pages.toLocaleString()} pages × ~200 organic visits/mo × 2% conversion</p>
                  </div>
                  <span className="text-emerald-400 font-bold text-sm flex-shrink-0">{row.est}/mo</span>
                </div>
              ))}
            </div>
          </Card>

          {/* AI Content Insight */}
          {aiInsight && (
            <Card title="AI Content Gap Insight">
              <div className="flex items-start gap-3 p-3 rounded-lg bg-violet-900/20 border border-violet-800/30">
                <Zap size={15} className="text-violet-400 flex-shrink-0 mt-0.5" />
                <p className="text-slate-300 text-sm leading-relaxed">{aiInsight}</p>
              </div>
              {topSubject && (
                <div className="mt-4 space-y-2">
                  <p className="text-slate-500 text-xs font-medium uppercase tracking-wide">Revenue opportunity</p>
                  {['MCQ Practice', 'Important Questions', 'Notes', 'Definitions'].map((pt, i) => (
                    <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-slate-800/40">
                      <span className="text-slate-300 text-sm">{topSubject.name} — {pt}</span>
                      <span className="text-xs text-emerald-400 font-medium">+{[120, 95, 80, 60][i]} organic/mo est.</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          {/* Signup Velocity */}
          <Card title="Signup Velocity">
            <div className="grid grid-cols-2 gap-3">
              <Stat icon={Users}      label="Signups this month" value={predict?.signups_this_month || 0} color="#7c3aed" />
              <Stat icon={ArrowUpRight} label="vs last month"    value={predict?.signups_last_month  || 0} color="#64748b"
                trend={predict?.signups_last_month > 0
                  ? Math.round(((predict.signups_this_month - predict.signups_last_month) / predict.signups_last_month) * 100)
                  : undefined} />
            </div>
          </Card>
        </div>
      )}

      {/* ── Page Conversions Tab ── */}
      {tab === 'pages' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-slate-200 font-semibold text-sm">Page-Level Conversion Tracker</h3>
              <p className="text-slate-500 text-xs mt-0.5">Which pages drive the most trial → paid conversions</p>
            </div>
            <button onClick={loadPageConversions} disabled={pageConvLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white bg-slate-800 border border-slate-700">
              <RefreshCw size={12} className={pageConvLoading ? 'animate-spin' : ''} /> Refresh
            </button>
          </div>

          {pageConvLoading ? (
            <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-slate-500" /></div>
          ) : pageConvData ? (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {[
                  { icon: Eye,        label: 'Total Page Views',  value: (pageConvData.total_views || 0).toLocaleString(), color: '#06b6d4' },
                  { icon: Target,     label: 'Conversion Events', value: pageConvData.total_conversions || 0, color: '#8b5cf6' },
                  { icon: TrendingUp, label: 'Top CVR',           value: `${pageConvData.top_cvr || 0}%`, color: '#10b981' },
                  { icon: DollarSign, label: 'Revenue Attributed',value: `₹${(pageConvData.revenue_attributed || 0).toLocaleString()}`, color: '#f59e0b' },
                ].map(s => <Stat key={s.label} icon={s.icon} label={s.label} value={s.value} color={s.color} />)}
              </div>

              {pageConvData.pages?.length > 0 && (
                <Card title="Top Converting Pages">
                  <div className="space-y-2">
                    {pageConvData.pages.slice(0, 20).map((p, i) => (
                      <div key={i} className="flex items-center gap-3 p-2.5 bg-slate-800/40 rounded-lg">
                        <span className="text-slate-600 text-xs w-5 text-right flex-shrink-0">{i + 1}</span>
                        <span className="text-slate-300 text-sm flex-1 truncate">{p.slug || p.url || '—'}</span>
                        <div className="flex items-center gap-3 flex-shrink-0">
                          <span className="text-slate-400 text-xs">{(p.views || 0).toLocaleString()} views</span>
                          <span className="text-xs font-mono px-2 py-0.5 rounded" style={{
                            background: (p.cvr || 0) > 3 ? 'rgba(16,185,129,0.15)' : (p.cvr || 0) > 1 ? 'rgba(245,158,11,0.15)' : 'rgba(100,116,139,0.15)',
                            color: (p.cvr || 0) > 3 ? '#34d399' : (p.cvr || 0) > 1 ? '#fbbf24' : '#94a3b8',
                          }}>
                            {p.cvr || 0}% CVR
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              {pageConvData.pages?.length === 0 && (
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-10 text-center">
                  <Target size={32} className="text-slate-700 mx-auto mb-3" />
                  <p className="text-slate-500 text-sm">No page conversion data yet — this populates as users convert from content pages</p>
                </div>
              )}
            </>
          ) : (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-10 text-center">
              <p className="text-slate-500 text-sm">Click Refresh to load page conversion data</p>
            </div>
          )}
        </div>
      )}
      <AdminQuickLinks links={['seomanager','users','conversations','monetization','dashboard']} onNavigate={onNavigate} />
    </div>
  );
}
