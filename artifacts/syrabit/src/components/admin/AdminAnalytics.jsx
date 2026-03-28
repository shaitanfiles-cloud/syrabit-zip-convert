import { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw, Eye, Globe, TrendingUp, Users, Search, BookOpen, Bot,
  FileText, ExternalLink, CheckCircle, AlertCircle, Copy, Check, BarChart2, Flame, DollarSign } from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, Legend, PieChart, Pie, Cell,
} from 'recharts';
import axios from 'axios';
import { adminGetAnalytics, API_BASE } from '@/utils/api';

const TOOLTIP_STYLE = {
  contentStyle: {
    background: '#0f172a',
    border: '1px solid #1e293b',
    borderRadius: '8px',
    color: '#e2e8f0',
    fontSize: 12,
  },
};

function SectionCard({ title, children, empty, emptyMsg, action }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-slate-400 text-sm font-medium">{title}</h3>
        {action}
      </div>
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

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <button onClick={copy} className="inline-flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors">
      {copied ? <><Check size={11} /> Copied</> : <><Copy size={11} /> Copy</>}
    </button>
  );
}

function SetupStep({ num, title, done, children }) {
  return (
    <div className="flex gap-3">
      <div className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold mt-0.5"
           style={{ background: done ? 'rgba(16,185,129,0.15)' : 'rgba(139,92,246,0.15)',
                    color: done ? '#10b981' : '#8b5cf6', border: `1px solid ${done ? '#10b981' : '#7c3aed'}33` }}>
        {done ? <CheckCircle size={13} /> : num}
      </div>
      <div className="flex-1">
        <p className="text-slate-200 text-sm font-medium mb-1">{title}</p>
        <div className="text-slate-400 text-xs space-y-1 leading-relaxed">{children}</div>
      </div>
    </div>
  );
}

const FUNNEL_COLORS = ['#3b82f6', '#8b5cf6', '#10b981'];

export default function AdminAnalytics({ adminToken }) {
  const [data, setData] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [heatmap, setHeatmap] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [tab, setTab] = useState('overview');

  const headers = { withCredentials: true };

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const [res, funnelRes, heatRes] = await Promise.allSettled([
        adminGetAnalytics(adminToken),
        axios.get(`${API_BASE}/admin/analytics/funnel`, headers),
        axios.get(`${API_BASE}/admin/analytics/content-heatmap`, headers),
      ]);
      if (res.status === 'fulfilled') setData(res.value.data);
      if (funnelRes.status === 'fulfilled') setFunnel(funnelRes.value.data);
      if (heatRes.status === 'fulfilled') setHeatmap(heatRes.value.data);
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
  const hasTopPages = data?.top_pages?.length > 0;
  const hasReferrers = data?.top_referrers?.length > 0;

  const formatDate = (d) => d?.slice(5) ?? d;

  const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'funnel',   label: 'Funnel' },
    { id: 'heatmap',  label: 'Heatmap' },
    { id: 'seo',      label: 'SEO & Pages' },
    { id: 'library',  label: 'Library' },
    { id: 'setup',    label: '🔧 Setup Guide' },
  ];

  const DYNAMIC_SITEMAP_URL = `${window.location.origin.replace(':25144', ':8000')}/api/seo/sitemap.xml`;

  return (
    <div className="p-6 space-y-5">

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

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-800/50 rounded-xl p-1 w-fit">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              tab === t.id
                ? 'bg-violet-600 text-white'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── OVERVIEW TAB ── */}
      {tab === 'overview' && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <MiniStat icon={Globe}      label="Total Visitors"    value={vs.total_visitors}   color="#06b6d4" />
            <MiniStat icon={TrendingUp} label="Visitors Today"    value={vs.visitors_today}   color="#f97316" />
            <MiniStat icon={Eye}        label="Page Views Today"  value={vs.page_views_today} color="#ec4899" />
            <MiniStat icon={Users}      label="Active Users"      value={data.active_users}   color="#10b981" />
          </div>

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
                <Area type="monotone" dataKey="visitors" name="Unique Visitors" stroke="#06b6d4" fill="rgba(6,182,212,0.12)" strokeWidth={2} />
                <Area type="monotone" dataKey="page_views" name="Page Views" stroke="#8b5cf6" fill="rgba(139,92,246,0.10)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </SectionCard>

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
        </>
      )}

      {/* ── FUNNEL TAB ── */}
      {tab === 'funnel' && funnel && (
        <div className="space-y-4">
          <SectionCard title="Conversion Funnel">
            <div className="space-y-3">
              {funnel.funnel?.map((stage, i) => (
                <div key={i}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-white text-sm font-medium">{stage.stage}</span>
                    <span className="text-slate-400 text-sm">{stage.count} ({stage.pct}%)</span>
                  </div>
                  <div className="h-8 rounded-lg overflow-hidden bg-slate-800">
                    <div
                      className="h-full rounded-lg transition-all duration-500"
                      style={{
                        width: `${stage.pct}%`,
                        background: `linear-gradient(90deg, ${FUNNEL_COLORS[i] || '#8b5cf6'}, ${FUNNEL_COLORS[i] || '#8b5cf6'}aa)`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </SectionCard>
          <div className="grid grid-cols-2 gap-3">
            <MiniStat icon={DollarSign} label="Revenue / Paid User" value={'₹' + (funnel.revenue_per_user || 0)} color="#10b981" />
            <MiniStat icon={TrendingUp} label="Conversion Rate" value={(funnel.conversion_rate || 0) + '%'} color="#8b5cf6" />
          </div>
        </div>
      )}
      {tab === 'funnel' && !funnel && (
        <SectionCard title="Conversion Funnel" empty emptyMsg="Funnel data is loading..." />
      )}

      {/* ── HEATMAP TAB ── */}
      {tab === 'heatmap' && heatmap && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SectionCard
            title="Top Subjects by Activity"
            empty={!heatmap.top_subjects?.length}
            emptyMsg="No subject activity data yet"
          >
            {heatmap.top_subjects?.length > 0 && (
              <div className="space-y-2">
                {heatmap.top_subjects.map((subj, i) => {
                  const maxViews = Math.max(...heatmap.top_subjects.map(s => s.views), 1);
                  const pct = (subj.views / maxViews) * 100;
                  const heat = pct > 70 ? '#ef4444' : pct > 40 ? '#f59e0b' : '#3b82f6';
                  return (
                    <div key={i} className="flex items-center gap-2">
                      <Flame size={12} style={{ color: heat }} className="flex-shrink-0" />
                      <span className="text-slate-300 text-sm flex-1 truncate">{subj.name}</span>
                      <div className="w-20 h-2 rounded-full bg-slate-800 overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: heat }} />
                      </div>
                      <span className="text-slate-500 text-xs w-10 text-right">{subj.views}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </SectionCard>

          <SectionCard
            title="Top Search Queries"
            empty={!heatmap.top_searches?.length}
            emptyMsg="No search data yet"
          >
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
          </SectionCard>
        </div>
      )}
      {tab === 'heatmap' && !heatmap && (
        <SectionCard title="Content Heatmap" empty emptyMsg="Heatmap data is loading..." />
      )}

      {/* ── SEO & PAGES TAB ── */}
      {tab === 'seo' && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <MiniStat icon={Eye}        label="Total Page Views"  value={vs.total_visitors ? undefined : 0} color="#8b5cf6" />
            <MiniStat icon={BarChart2}  label="Pages Tracked"     value={hasTopPages ? data.top_pages.length : 0} color="#06b6d4" />
            <MiniStat icon={Globe}      label="Traffic Sources"   value={hasReferrers ? data.top_referrers.length : 0} color="#10b981" />
          </div>

          <SectionCard
            title="Top Visited Pages"
            empty={!hasTopPages}
            emptyMsg="No page visit data yet — pages are tracked as visitors browse your site"
            action={
              <a href="/api/seo/sitemap.xml" target="_blank" rel="noopener noreferrer"
                className="flex items-center gap-1 text-xs text-violet-400 hover:underline">
                <ExternalLink size={11} /> View Sitemap
              </a>
            }
          >
            <div className="space-y-1.5">
              {(data.top_pages || []).map((pg, i) => (
                <div key={i} className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-slate-800/50 transition-colors group">
                  <span className="text-slate-600 text-xs w-5 text-right">{i + 1}</span>
                  <FileText size={11} className="text-violet-400 flex-shrink-0" />
                  <span className="text-slate-300 text-xs flex-1 truncate font-mono">{pg.path}</span>
                  <span className="text-slate-500 text-xs flex-shrink-0">{pg.views} views</span>
                  <span className="text-slate-600 text-xs flex-shrink-0">{pg.unique_visitors} uniq</span>
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard
            title="Traffic Sources (Referrers)"
            empty={!hasReferrers}
            emptyMsg="No referrer data yet — referrers appear when visitors arrive from external sites, search engines, or social media"
          >
            <div className="space-y-2">
              {(data.top_referrers || []).map((ref, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Globe size={11} className="text-cyan-400 flex-shrink-0" />
                  <span className="text-slate-300 text-sm flex-1 truncate">{ref.source || 'Direct'}</span>
                  <span className="text-xs text-slate-500">{ref.count} visits</span>
                </div>
              ))}
            </div>
          </SectionCard>
        </>
      )}

      {/* ── LIBRARY TAB ── */}
      {tab === 'library' && (
        hasLibraryEvents ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {data.library.top_searches?.length > 0 && (
              <SectionCard title="Top Searches">
                <div className="space-y-2">
                  {data.library.top_searches.slice(0, 8).map((item, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Search size={12} className="text-blue-400 flex-shrink-0" />
                      <span className="text-sm text-slate-300 flex-1 truncate">{item.query || item._id || 'Unknown'}</span>
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
          </div>
        ) : (
          <SectionCard
            title="Library Interactions"
            empty
            emptyMsg="No user interactions yet. Analytics will appear as users browse subjects and search content."
          />
        )
      )}

      {/* ── SETUP GUIDE TAB ── */}
      {tab === 'setup' && (
        <div className="space-y-4">

          {/* Google Analytics 4 */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-7 h-7 rounded-lg bg-orange-500/15 flex items-center justify-center">
                <TrendingUp size={14} className="text-orange-400" />
              </div>
              <div>
                <h3 className="text-slate-200 text-sm font-semibold">Google Analytics 4</h3>
                <p className="text-slate-500 text-xs">Track users, sessions, and conversions — free forever</p>
              </div>
              <a href="https://analytics.google.com" target="_blank" rel="noopener noreferrer"
                className="ml-auto text-xs text-violet-400 hover:underline flex items-center gap-1">
                Open GA4 <ExternalLink size={10} />
              </a>
            </div>
            <div className="space-y-3">
              <SetupStep num="1" title="Create a GA4 Property">
                <p>Go to <strong className="text-slate-300">analytics.google.com</strong> → Admin → Create Property → choose "Web"</p>
                <p>Set the URL to <code className="bg-slate-800 px-1 rounded text-violet-300">syrabit.ai</code> and get your Measurement ID (starts with <code className="bg-slate-800 px-1 rounded text-violet-300">G-</code>)</p>
              </SetupStep>
              <SetupStep num="2" title="Add your Measurement ID to Replit">
                <p>In your Replit project, go to <strong className="text-slate-300">Secrets</strong> and add:</p>
                <div className="mt-1 flex items-center gap-2 bg-slate-800 rounded-lg px-3 py-2">
                  <code className="text-violet-300 text-xs flex-1">VITE_GA_MEASUREMENT_ID = G-XXXXXXXXXX</code>
                  <CopyButton text="VITE_GA_MEASUREMENT_ID" />
                </div>
                <p className="mt-1">Then <strong className="text-slate-300">restart the web workflow</strong>. GA4 will auto-load.</p>
              </SetupStep>
              <SetupStep num="3" title="Verify tracking is working">
                <p>In GA4, go to <strong className="text-slate-300">Reports → Realtime</strong> and open your site in a new tab. You should see your visit appear within seconds.</p>
              </SetupStep>
            </div>
          </div>

          {/* Google Search Console */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-7 h-7 rounded-lg bg-blue-500/15 flex items-center justify-center">
                <Search size={14} className="text-blue-400" />
              </div>
              <div>
                <h3 className="text-slate-200 text-sm font-semibold">Google Search Console</h3>
                <p className="text-slate-500 text-xs">See which keywords rank, fix indexing issues, submit sitemap</p>
              </div>
              <a href="https://search.google.com/search-console" target="_blank" rel="noopener noreferrer"
                className="ml-auto text-xs text-violet-400 hover:underline flex items-center gap-1">
                Open GSC <ExternalLink size={10} />
              </a>
            </div>
            <div className="space-y-3">
              <SetupStep num="1" title="Add your property">
                <p>Go to <strong className="text-slate-300">search.google.com/search-console</strong> → Add property → URL prefix → enter <code className="bg-slate-800 px-1 rounded text-violet-300">https://syrabit.ai</code></p>
              </SetupStep>
              <SetupStep num="2" title="Verify ownership via HTML tag">
                <p>Choose "HTML tag" verification method. Copy the <code className="bg-slate-800 px-1 rounded text-violet-300">content="..."</code> value from the meta tag Google shows you.</p>
                <p className="mt-1">Open <code className="bg-slate-800 px-1 rounded text-violet-300">artifacts/syrabit/index.html</code> and uncomment + fill in the GSC verification line near the top of the &lt;head&gt;.</p>
              </SetupStep>
              <SetupStep num="3" title="Submit your sitemap">
                <p>After verifying, go to <strong className="text-slate-300">Sitemaps</strong> in GSC and add your dynamic sitemap URL:</p>
                <div className="mt-1 flex items-center gap-2 bg-slate-800 rounded-lg px-3 py-2">
                  <code className="text-violet-300 text-xs flex-1 truncate">https://syrabit.ai/api/seo/sitemap.xml</code>
                  <CopyButton text="https://syrabit.ai/api/seo/sitemap.xml" />
                </div>
                <p className="mt-1">Also add the static sitemap: <code className="bg-slate-800 px-1 rounded text-violet-300">https://syrabit.ai/sitemap.xml</code></p>
              </SetupStep>
            </div>
          </div>

          {/* PostHog — already active */}
          <div className="bg-slate-900 border border-emerald-800/40 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-7 h-7 rounded-lg bg-emerald-500/15 flex items-center justify-center">
                <CheckCircle size={14} className="text-emerald-400" />
              </div>
              <div>
                <h3 className="text-slate-200 text-sm font-semibold">PostHog Analytics</h3>
                <p className="text-emerald-500 text-xs">✓ Already active — session recording + event tracking running</p>
              </div>
              <a href="https://posthog.com" target="_blank" rel="noopener noreferrer"
                className="ml-auto text-xs text-violet-400 hover:underline flex items-center gap-1">
                Dashboard <ExternalLink size={10} />
              </a>
            </div>
            <p className="text-slate-500 text-xs">PostHog is embedded in your app and tracks all events (signups, chat, payments, page views) automatically. Log in to PostHog to see your full funnel analytics and session recordings.</p>
          </div>

          {/* Internal analytics — already active */}
          <div className="bg-slate-900 border border-emerald-800/40 rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-7 h-7 rounded-lg bg-emerald-500/15 flex items-center justify-center">
                <CheckCircle size={14} className="text-emerald-400" />
              </div>
              <div>
                <h3 className="text-slate-200 text-sm font-semibold">Internal Visitor Analytics</h3>
                <p className="text-emerald-500 text-xs">✓ Already active — stored in your own MongoDB database</p>
              </div>
            </div>
            <p className="text-slate-500 text-xs">Every page view is tracked in MongoDB. See the <strong className="text-slate-400">Overview</strong> and <strong className="text-slate-400">SEO & Pages</strong> tabs above for your data.</p>
          </div>

          {/* SEO status */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h3 className="text-slate-200 text-sm font-semibold mb-3">SEO Implementation Status</h3>
            <div className="space-y-2">
              {[
                ['Dynamic sitemap.xml (auto-updates with every published page)', true],
                ['Static sitemap.xml (core pages)', true],
                ['robots.txt with both sitemaps listed', true],
                ['WebSite schema + SearchAction (Google Sitelinks search box)', true],
                ['EducationalOrganization schema', true],
                ['Article JSON-LD on all topic content pages', true],
                ['BreadcrumbList JSON-LD on topic pages', true],
                ['FAQPage schema auto-extracted from MCQs/PYQs', true],
                ['Open Graph + Twitter Card on all pages', true],
                ['og:locale=en_IN, og:site_name, og:image:width/height', true],
                ['Per-page keywords meta tag', true],
                ['Canonical URLs on all pages', true],
                ['Share button with copy link on library cards', true],
                ['Google Analytics 4 (set VITE_GA_MEASUREMENT_ID to activate)', false],
                ['Google Search Console verified (uncomment meta tag + submit sitemap)', false],
              ].map(([label, done]) => (
                <div key={label} className="flex items-start gap-2">
                  {done
                    ? <CheckCircle size={13} className="text-emerald-400 mt-0.5 flex-shrink-0" />
                    : <AlertCircle size={13} className="text-amber-400 mt-0.5 flex-shrink-0" />
                  }
                  <span className={`text-xs ${done ? 'text-slate-300' : 'text-amber-300'}`}>{label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
