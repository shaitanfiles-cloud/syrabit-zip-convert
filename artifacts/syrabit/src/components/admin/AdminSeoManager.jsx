import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Loader2, RefreshCw, Globe, FileText, Sparkles, CheckCircle2,
  XCircle, BookOpen, Zap, Map, Eye, EyeOff, Trash2, Search,
  AlertTriangle, Play, TrendingUp, BarChart2, ChevronRight,
  ArrowRight, CheckCheck, Clock, Activity,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  adminSeoStats, adminSeoListTopics, adminSeoExtractTopics,
  adminSeoGenerate, adminSeoListPages, adminSeoUpdatePageStatus,
  adminSeoRegenerateSitemap, adminSeoDeleteTopic, adminSeoPilot,
  adminSeoAutoRun, adminSeoJobStatus, adminSeoInsights, adminSeoExpand,
  adminSeoBulkPublish,
  seoInternalLinksAnalyze, seoInternalLinksInject,
  seoInjectSchemaBulk, seoInjectSchema, seoSitemapValidate,
} from '@/utils/api';

const PAGE_TYPES = [
  { id: 'notes',               label: 'Notes',               color: '#7c3aed' },
  { id: 'definition',          label: 'Definitions',         color: '#0891b2' },
  { id: 'important-questions', label: 'Important Questions', color: '#d97706' },
  { id: 'mcqs',                label: 'MCQs',                color: '#16a34a' },
  { id: 'examples',            label: 'Examples',            color: '#e11d48' },
];

const STATUS_COLORS = {
  published: { text: '#34d399', bg: 'rgba(16,185,129,0.10)', border: 'rgba(52,211,153,0.20)' },
  draft:     { text: '#fbbf24', bg: 'rgba(245,158,11,0.10)',  border: 'rgba(251,191,36,0.20)' },
  archived:  { text: '#9ca3af', bg: 'rgba(156,163,175,0.10)', border: 'rgba(156,163,175,0.20)' },
};

function StatCard({ icon: Icon, label, value, color = '#e8e8e8', sub }) {
  return (
    <div className="rounded-xl p-4 border" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }}>
      <Icon size={15} style={{ color, marginBottom: 8 }} />
      <p className="text-2xl font-bold" style={{ color }}>{value ?? '—'}</p>
      <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>{label}</p>
      {sub && <p className="text-[10px] mt-1" style={{ color: 'rgba(255,255,255,0.20)' }}>{sub}</p>}
    </div>
  );
}

function JobProgress({ job, onDismiss }) {
  if (!job) return null;
  const pct = job.total > 0 ? Math.min(100, Math.round((job.done / job.total) * 100)) : 0;
  const isDone = job.status === 'done';
  const isErr  = job.status === 'error';
  const barColor = isErr ? '#f87171' : isDone ? '#34d399' : '#7c3aed';
  return (
    <div className="rounded-xl p-4 border" style={{ background: 'rgba(124,58,237,0.06)', borderColor: 'rgba(124,58,237,0.25)' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {isDone ? <CheckCheck size={14} style={{ color: '#34d399' }} />
           : isErr ? <AlertTriangle size={14} style={{ color: '#f87171' }} />
           : <Loader2 size={14} className="animate-spin" style={{ color: '#a78bfa' }} />}
          <span className="text-xs font-semibold" style={{ color: isDone ? '#34d399' : isErr ? '#f87171' : '#c4b0f0' }}>
            {isDone ? 'Pipeline Complete' : isErr ? 'Pipeline Error' : 'Pipeline Running…'}
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.35)' }}>
            {job.job_id}
          </span>
        </div>
        {(isDone || isErr) && (
          <button onClick={onDismiss} className="text-[10px]" style={{ color: 'rgba(255,255,255,0.30)' }}>Dismiss</button>
        )}
      </div>
      <div className="flex items-center gap-3 mb-2">
        <div className="flex-1 h-2 rounded-full" style={{ background: 'rgba(255,255,255,0.06)' }}>
          <div className="h-2 rounded-full transition-all duration-300" style={{ width: `${isDone ? 100 : pct}%`, background: barColor }} />
        </div>
        <span className="text-[11px] font-mono flex-shrink-0" style={{ color: 'rgba(255,255,255,0.45)' }}>
          {isDone ? '100%' : `${pct}%`}
        </span>
      </div>
      <div className="flex items-center gap-4 text-[10px]" style={{ color: 'rgba(255,255,255,0.35)' }}>
        <span>✓ {job.done ?? 0} done</span>
        {job.skipped > 0 && <span>⟳ {job.skipped} skipped</span>}
        {job.errors > 0 && <span style={{ color: '#f87171' }}>✗ {job.errors} errors</span>}
        {job.total > 0 && <span>of {job.total}</span>}
      </div>
      {job.current && (
        <p className="text-[10px] truncate mt-1.5" style={{ color: 'rgba(255,255,255,0.25)' }}>{job.current}</p>
      )}
    </div>
  );
}

function InsightCard({ insight, onAction, loading }) {
  const colors = {
    critical: { bg: 'rgba(239,68,68,0.07)', border: 'rgba(239,68,68,0.22)', badge: '#f87171', badgeBg: 'rgba(239,68,68,0.15)' },
    gap:      { bg: 'rgba(124,58,237,0.06)', border: 'rgba(124,58,237,0.22)', badge: '#a78bfa', badgeBg: 'rgba(139,92,246,0.15)' },
    info:     { bg: 'rgba(255,255,255,0.02)', border: 'rgba(255,255,255,0.08)', badge: '#94a3b8', badgeBg: 'rgba(255,255,255,0.06)' },
  };
  const c = colors[insight.type] || colors.info;
  return (
    <div className="rounded-xl p-4 border" style={{ background: c.bg, borderColor: c.border }}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: c.badgeBg, color: c.badge }}>
              {insight.count} pages
            </span>
            {insight.page_type && (
              <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.35)' }}>
                {insight.page_type}
              </span>
            )}
          </div>
          <p className="text-sm font-semibold mb-1" style={{ color: 'rgba(232,232,232,0.85)' }}>{insight.title}</p>
          <p className="text-xs leading-relaxed" style={{ color: 'rgba(255,255,255,0.35)' }}>{insight.description}</p>
        </div>
        <button
          onClick={() => onAction(insight)}
          disabled={loading}
          className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
          style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)', color: '#fff' }}>
          {loading ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />}
          {insight.action === 'auto-run' ? 'Auto-Run' : 'Generate'}
        </button>
      </div>
    </div>
  );
}

// ── Read hub context from localStorage ───────────────────────────────────────
const HUB_CTX_KEY = 'syrabit_hub_ctx';
function readHubCtx() {
  try {
    const raw = localStorage.getItem(HUB_CTX_KEY);
    if (!raw) return null;
    const ctx = JSON.parse(raw);
    if (Date.now() - (ctx._ts || 0) > 2 * 60 * 60 * 1000) return null;
    return ctx;
  } catch { return null; }
}

export default function AdminSeoManager({ adminToken }) {
  const [tab, setTab]               = useState('pages');
  const [stats, setStats]           = useState(null);
  const [topics, setTopics]         = useState([]);
  const [pages, setPages]           = useState([]);
  const [insights, setInsights]     = useState(null);
  const [loading, setLoading]       = useState(true);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [sitemap, setSitemap]       = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [activeJob, setActiveJob]   = useState(null);
  const [actionLoading, setActionLoading] = useState(null);
  const pollRef = useRef(null);

  const [topicSearch, setTopicSearch]   = useState('');
  const [pageSearch, setPageSearch]     = useState('');
  const [pageFilter, setPageFilter]     = useState('all');
  const [selectedTopics, setSelectedTopics]   = useState(new Set());
  const [selectedTypes, setSelectedTypes]     = useState(new Set(['notes', 'important-questions', 'mcqs']));

  const [piloting, setPiloting]     = useState(false);
  const [pilotResult, setPilotResult] = useState(null);
  const [pilotBoard, setPilotBoard]   = useState('AHSEC');
  const [pilotClass, setPilotClass]   = useState('Class 11');
  const [pilotSubject, setPilotSubject] = useState('');
  const [pilotChapters, setPilotChapters] = useState(3);

  // ── Hub context (active subject from Content Hub) ─────────────────────────
  const [hubCtx, setHubCtx] = useState(readHubCtx);
  // Refresh hub context whenever the tab is focused
  useEffect(() => {
    const onFocus = () => setHubCtx(readHubCtx());
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, []);
  const [scopeSubjectOnly, setScopeSubjectOnly] = useState(false);

  // Internal Links
  const [linksData, setLinksData]     = useState(null);
  const [linksLoading, setLinksLoading] = useState(false);
  const [injectSlug, setInjectSlug]   = useState('');
  const [injecting, setInjecting]     = useState(false);
  // Schema
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [schemaSlug, setSchemaSlug]   = useState('');
  const [schemaResult, setSchemaResult] = useState(null);
  // Sitemap
  const [sitemapData, setSitemapData] = useState(null);
  const [sitemapValidating, setSitemapValidating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [statsRes, topicsRes, pagesRes] = await Promise.all([
        adminSeoStats(adminToken),
        adminSeoListTopics(adminToken),
        adminSeoListPages(adminToken),
      ]);
      setStats(statsRes.data);
      setTopics(Array.isArray(topicsRes.data) ? topicsRes.data : []);
      const raw = pagesRes.data;
      setPages(Array.isArray(raw) ? raw : (raw?.pages || []));
    } catch {
      toast.error('Failed to load SEO data');
    } finally {
      setLoading(false);
    }
  }, [adminToken]);

  const loadInsights = useCallback(async () => {
    setInsightsLoading(true);
    try {
      const res = await adminSeoInsights(adminToken);
      setInsights(res.data);
    } catch {
      toast.error('Could not load insights');
    } finally {
      setInsightsLoading(false);
    }
  }, [adminToken]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (tab === 'insights' && !insights) loadInsights();
  }, [tab, insights, loadInsights]);

  // Job polling
  const startPolling = useCallback((jobId) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const res = await adminSeoJobStatus(adminToken, jobId);
        const job = res.data;
        setActiveJob(job);
        if (job.status === 'done' || job.status === 'error') {
          clearInterval(pollRef.current);
          pollRef.current = null;
          load();
          if (insights) loadInsights();
        }
      } catch {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 2000);
  }, [adminToken, load, insights, loadInsights]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const handleAutoRun = async () => {
    try {
      toast.loading('Starting full pipeline…', { id: 'autorun' });
      const res = await adminSeoAutoRun(adminToken);
      const jobId = res.data?.job_id;
      if (!jobId) throw new Error('No job_id returned');
      setActiveJob({ job_id: jobId, status: 'queued', total: 0, done: 0, errors: 0, skipped: 0, current: 'Starting…' });
      startPolling(jobId);
      toast.success('Pipeline launched — tracking progress below', { id: 'autorun' });
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Auto-run failed', { id: 'autorun' });
    }
  };

  const handleExtract = async (force = false) => {
    const sid = hubCtx?.subjectId || null;
    const label = sid && hubCtx?.subjectName ? ` for "${hubCtx.subjectName}"` : '';
    setExtracting(true);
    toast.loading(`Extracting topics${label} using AI…`, { id: 'extract' });
    try {
      // Pass subject_id + force as query params (API already supports both)
      const params = new URLSearchParams();
      if (sid) params.set('subject_id', sid);
      if (force) params.set('force', 'true');
      const res = await adminSeoExtractTopics(adminToken, sid, force);
      const d = res.data || {};
      toast.success(
        `Created ${d.created || 0} topics${label}` +
        (d.skipped ? ` · ${d.skipped} already existed` : '') +
        (d.errors   ? ` · ${d.errors} AI errors` : ''),
        { id: 'extract' }
      );
      load();
    } catch {
      toast.error('Topic extraction failed', { id: 'extract' });
    } finally {
      setExtracting(false);
    }
  };

  const handleGenerate = async () => {
    if (!selectedTopics.size) { toast.error('Select at least one topic'); return; }
    if (!selectedTypes.size)  { toast.error('Select at least one page type'); return; }
    setGenerating(true);
    try {
      const res = await adminSeoGenerate(adminToken, { topic_ids: [...selectedTopics], page_types: [...selectedTypes] });
      toast.success(`Generating ${res.data?.total || 0} pages in background…`);
      setTimeout(load, 3000);
    } catch {
      toast.error('Generation failed');
    } finally {
      setGenerating(false);
    }
  };

  const handleToggleStatus = async (page) => {
    const newStatus = page.status === 'published' ? 'draft' : 'published';
    try {
      await adminSeoUpdatePageStatus(adminToken, page._id || page.id, newStatus);
      setPages(prev => prev.map(p => (p._id === page._id || p.id === page.id) ? { ...p, status: newStatus } : p));
      toast.success(`Page ${newStatus === 'published' ? 'published' : 'unpublished'}`);
    } catch { toast.error('Status update failed'); }
  };

  const handleDeleteTopic = async (topic) => {
    if (!confirm(`Delete topic "${topic.title}"?`)) return;
    try {
      await adminSeoDeleteTopic(adminToken, topic._id || topic.id);
      setTopics(prev => prev.filter(t => (t._id || t.id) !== (topic._id || topic.id)));
      toast.success('Topic deleted');
    } catch { toast.error('Delete failed'); }
  };

  const handleRegenerateSitemap = async () => {
    setSitemap(true);
    try {
      await adminSeoRegenerateSitemap(adminToken);
      toast.success('Sitemap regenerated');
    } catch { toast.error('Sitemap regeneration failed'); }
    finally { setSitemap(false); }
  };

  const handleBulkPublish = async () => {
    if (!confirm(`Publish all draft SEO pages? This will make them publicly indexed.`)) return;
    setPublishing(true);
    try {
      const res = await adminSeoBulkPublish(adminToken);
      toast.success(res.data?.message || 'Pages published');
      load();
    } catch { toast.error('Bulk publish failed'); }
    finally { setPublishing(false); }
  };

  const handleInsightAction = async (insight) => {
    setActionLoading(insight.title);
    try {
      if (insight.action === 'auto-run') {
        await handleAutoRun();
      } else if (insight.action === 'generate' && insight.page_type) {
        const res = await adminSeoGenerate(adminToken, {
          page_types: [insight.page_type],
          topic_ids: topics.slice(0, 200).map(t => t._id || t.id),
        });
        toast.success(`Generating ${res.data?.total || 0} ${insight.page_type} pages…`);
        setTimeout(load, 3000);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Action failed');
    } finally {
      setActionLoading(null);
    }
  };

  const handleLinksAnalyze = async () => {
    setLinksLoading(true);
    try {
      const res = await seoInternalLinksAnalyze(adminToken);
      setLinksData(res.data);
    } catch { toast.error('Link analysis failed'); }
    finally { setLinksLoading(false); }
  };

  const handleLinksInject = async () => {
    if (!injectSlug.trim()) { toast.error('Enter a slug'); return; }
    setInjecting(true);
    try {
      const res = await seoInternalLinksInject(adminToken, injectSlug.trim());
      toast.success(res.data?.message || 'Links injected');
    } catch (e) { toast.error(e.response?.data?.detail || 'Injection failed'); }
    finally { setInjecting(false); }
  };

  const handleSchemaInjectSingle = async () => {
    if (!schemaSlug.trim()) { toast.error('Enter a slug'); return; }
    setSchemaLoading(true);
    try {
      const res = await seoInjectSchema(adminToken, schemaSlug.trim());
      setSchemaResult(res.data);
      toast.success('Schema injected');
    } catch (e) { toast.error(e.response?.data?.detail || 'Schema inject failed'); }
    finally { setSchemaLoading(false); }
  };

  const handleSchemaBulk = async () => {
    if (!confirm('Inject schema.org markup for ALL published pages? This will take a while.')) return;
    setSchemaLoading(true);
    try {
      const res = await seoInjectSchemaBulk(adminToken);
      toast.success(res.data?.message || 'Bulk schema injection started');
    } catch (e) { toast.error(e.response?.data?.detail || 'Bulk inject failed'); }
    finally { setSchemaLoading(false); }
  };

  const handleSitemapValidate = async () => {
    setSitemapValidating(true);
    try {
      const res = await seoSitemapValidate(adminToken);
      setSitemapData(res.data);
    } catch { toast.error('Sitemap validation failed'); }
    finally { setSitemapValidating(false); }
  };

  const handlePilot = async () => {
    setPiloting(true);
    setPilotResult(null);
    try {
      const res = await adminSeoPilot(adminToken, {
        board_name: pilotBoard,
        class_name: pilotClass,
        subject_keyword: pilotSubject,
        chapter_limit: pilotChapters,
      });
      setPilotResult(res.data);
      toast.success(res.data?.message || 'Pilot complete');
      setTimeout(load, 2000);
    } catch (e) {
      const msg = e?.response?.data?.detail || 'Pilot failed';
      toast.error(msg);
      setPilotResult({ error: msg });
    } finally {
      setPiloting(false);
    }
  };

  const toggleTopic = (id) => setSelectedTopics(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const toggleType  = (id) => setSelectedTypes(prev  => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const filteredTopics = topics.filter(t => {
    if (scopeSubjectOnly && hubCtx?.subjectId && t.subject_id !== hubCtx.subjectId) return false;
    if (!topicSearch.trim()) return true;
    const q = topicSearch.toLowerCase();
    return (t.title || '').toLowerCase().includes(q)
      || (t.subject_name || '').toLowerCase().includes(q)
      || (t.chapter_title || '').toLowerCase().includes(q);
  });

  const filteredPages = pages.filter(p => {
    if (pageFilter !== 'all' && p.status !== pageFilter) return false;
    if (!pageSearch.trim()) return true;
    const q = pageSearch.toLowerCase();
    return (p.title || '').toLowerCase().includes(q) || (p.topic_title || '').toLowerCase().includes(q) || (p.subject_name || '').toLowerCase().includes(q);
  });

  const publishedCount = pages.filter(p => p.status === 'published').length;
  const draftCount     = pages.filter(p => p.status !== 'published').length;
  const coverage       = topics.length > 0 ? Math.round((publishedCount / (topics.length * 5)) * 100) : 0;

  const TABS = [
    { id: 'pages',    label: 'SEO Pages',  count: pages.length },
    { id: 'topics',   label: 'Topics',     count: topics.length },
    { id: 'insights', label: '✦ Insights', count: insights?.insights?.length ?? null },
    { id: 'generate', label: 'Generate',   count: null },
    { id: 'pilot',    label: 'Pilot',      count: null },
    { id: 'links',    label: '🔗 Int. Links', count: null },
    { id: 'schema',   label: '🧬 Schema',  count: null },
    { id: 'sitemap',  label: '🗺 Sitemap', count: null },
  ];

  return (
    <div className="space-y-5 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold text-white">SEO Content Manager</h2>
          <p className="text-sm mt-0.5" style={{ color: 'rgba(255,255,255,0.35)' }}>Manage topic pages, generate AI content, and control what Googlebot crawls</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={load} className="h-9 px-3 rounded-xl text-xs flex items-center gap-1.5 transition-colors border"
            style={{ color: 'rgba(255,255,255,0.50)', borderColor: 'rgba(255,255,255,0.10)' }}>
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button onClick={handleRegenerateSitemap} disabled={sitemap}
            className="h-9 px-3 rounded-xl text-xs flex items-center gap-1.5 transition-colors border disabled:opacity-50"
            style={{ color: 'rgba(255,255,255,0.60)', borderColor: 'rgba(255,255,255,0.10)' }}>
            {sitemap ? <Loader2 size={13} className="animate-spin" /> : <Map size={13} />} Regen Sitemap
          </button>
          {draftCount > 0 && (
            <button onClick={handleBulkPublish} disabled={publishing}
              className="h-9 px-3 rounded-xl text-xs flex items-center gap-1.5 transition-colors border disabled:opacity-50"
              style={{ color: '#34d399', borderColor: 'rgba(52,211,153,0.30)', background: 'rgba(52,211,153,0.07)' }}>
              {publishing ? <Loader2 size={13} className="animate-spin" /> : <CheckCheck size={13} />}
              Publish All ({draftCount})
            </button>
          )}
          <a href="/api/seo/sitemap.xml" target="_blank" rel="noopener"
            className="h-9 px-3 rounded-xl text-xs flex items-center gap-1.5 transition-colors"
            style={{ color: '#a78bfa', background: 'rgba(139,92,246,0.10)', border: '1px solid rgba(139,92,246,0.25)' }}>
            <Globe size={13} /> View Sitemap
          </a>
          <button onClick={handleAutoRun}
            disabled={activeJob && activeJob.status !== 'done' && activeJob.status !== 'error'}
            className="h-9 px-4 rounded-xl text-xs font-semibold flex items-center gap-1.5 disabled:opacity-40 transition-all"
            style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)', color: '#fff' }}>
            {(activeJob && activeJob.status !== 'done' && activeJob.status !== 'error')
              ? <><Loader2 size={13} className="animate-spin" /> Running…</>
              : <><Play size={13} /> Auto-Run All</>}
          </button>
        </div>
      </div>

      {/* Active job progress */}
      {activeJob && (
        <JobProgress job={activeJob} onDismiss={() => setActiveJob(null)} />
      )}

      {/* Stats row */}
      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="rounded-xl p-4 border h-24 animate-pulse" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          <StatCard icon={BookOpen}     label="Topics"          value={topics.length}      color="rgba(255,255,255,0.70)" />
          <StatCard icon={CheckCircle2} label="Published"       value={publishedCount}     color="#34d399" />
          <StatCard icon={FileText}     label="Drafts"          value={draftCount}         color="#fbbf24" />
          <StatCard icon={Globe}        label="Sitemap URLs"    value={stats?.sitemap_urls ?? publishedCount} color="#a78bfa" />
          <StatCard icon={Activity}     label="Coverage"        value={`${coverage}%`}     color={coverage >= 80 ? '#34d399' : coverage >= 40 ? '#fbbf24' : '#f87171'}
            sub={`${topics.length} topics × 5 types`} />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-xl overflow-x-auto" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
        {TABS.map(({ id, label, count }) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex-shrink-0 h-8 px-3 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${
              tab === id ? 'text-white shadow' : 'hover:text-white/70'
            }`}
            style={tab === id ? { background: '#7c3aed', color: '#fff' } : { color: 'rgba(255,255,255,0.40)' }}>
            {label}
            {count !== null && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px]"
                style={{ background: tab === id ? 'rgba(255,255,255,0.20)' : 'rgba(255,255,255,0.06)', color: tab === id ? '#fff' : 'rgba(255,255,255,0.30)' }}>
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── SEO Pages Tab ─────────────────────────────────────────────── */}
      {tab === 'pages' && (
        <div className="space-y-3">
          <div className="flex gap-2 flex-wrap">
            <div className="relative flex-1 min-w-48">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'rgba(255,255,255,0.25)' }} />
              <input value={pageSearch} onChange={e => setPageSearch(e.target.value)} placeholder="Search pages…"
                className="w-full h-9 pl-8 pr-3 rounded-xl text-sm outline-none"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: '#E8E8E8' }}
              />
            </div>
            {['all', 'published', 'draft'].map(f => (
              <button key={f} onClick={() => setPageFilter(f)}
                className="h-9 px-3 rounded-xl text-xs capitalize font-medium transition-all"
                style={pageFilter === f
                  ? { background: '#7c3aed', color: '#fff' }
                  : { color: 'rgba(255,255,255,0.40)', border: '1px solid rgba(255,255,255,0.08)' }}>
                {f === 'all' ? 'All' : f === 'published' ? `Published (${publishedCount})` : `Draft (${draftCount})`}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="space-y-2">{[...Array(5)].map((_, i) => <div key={i} className="h-16 rounded-xl animate-pulse" style={{ background: 'rgba(255,255,255,0.02)' }} />)}</div>
          ) : filteredPages.length === 0 ? (
            <div className="rounded-xl p-10 text-center border" style={{ background: 'rgba(255,255,255,0.01)', borderColor: 'rgba(255,255,255,0.06)' }}>
              <FileText size={28} className="mx-auto mb-3" style={{ color: 'rgba(255,255,255,0.10)' }} />
              <p className="text-sm" style={{ color: 'rgba(255,255,255,0.30)' }}>
                {pages.length === 0
                  ? 'No SEO pages yet. Click Auto-Run All to start the pipeline.'
                  : 'No pages match your filter.'}
              </p>
              {pages.length === 0 && (
                <button onClick={handleAutoRun} className="mt-4 h-9 px-5 rounded-xl text-xs font-semibold flex items-center gap-2 mx-auto"
                  style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)', color: '#fff' }}>
                  <Play size={13} /> Auto-Run All
                </button>
              )}
            </div>
          ) : (
            <div className="space-y-1.5">
              {filteredPages.map(page => {
                const pid = page._id || page.id;
                const sc = STATUS_COLORS[page.status] || STATUS_COLORS.draft;
                const typeInfo = PAGE_TYPES.find(p => p.id === page.page_type);
                return (
                  <div key={pid} className="flex items-center gap-3 p-3 rounded-xl border transition-colors"
                    style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }}>
                    {typeInfo && (
                      <div className="w-1.5 h-8 rounded-full flex-shrink-0" style={{ background: typeInfo.color }} />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate" style={{ color: '#E8E8E8' }}>{page.title || page.topic_title || '—'}</p>
                      <p className="text-xs truncate mt-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>
                        {[page.board_name, page.class_name, page.subject_name, page.page_type].filter(Boolean).join(' · ')}
                      </p>
                    </div>
                    <span className="flex-shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold border"
                      style={{ color: sc.text, background: sc.bg, borderColor: sc.border }}>
                      {page.status || 'draft'}
                    </span>
                    <button onClick={() => handleToggleStatus(page)} title={page.status === 'published' ? 'Unpublish' : 'Publish'}
                      className="flex-shrink-0 p-1.5 rounded-lg transition-colors"
                      style={{ color: 'rgba(255,255,255,0.25)' }}>
                      {page.status === 'published' ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                    {page.url && (
                      <a href={page.url} target="_blank" rel="noopener"
                        className="flex-shrink-0 p-1.5 rounded-lg transition-colors"
                        style={{ color: 'rgba(255,255,255,0.25)' }}>
                        <Globe size={14} />
                      </a>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Topics Tab ────────────────────────────────────────────────── */}
      {tab === 'topics' && (
        <div className="space-y-3">

          {/* ── Hub context banner ──────────────────────────────────────── */}
          {hubCtx?.subjectId && (
            <div className="flex items-center justify-between px-4 py-2.5 rounded-xl"
              style={{ background: 'rgba(124,58,237,0.08)', border: '1px solid rgba(124,58,237,0.22)' }}>
              <div className="flex items-center gap-2">
                <BookOpen size={13} style={{ color: '#a78bfa' }} />
                <span className="text-xs font-semibold" style={{ color: '#c4b5fd' }}>
                  Active subject:
                </span>
                <span className="text-xs px-2 py-0.5 rounded-full font-medium"
                  style={{ background: 'rgba(139,92,246,0.20)', color: '#ddd6fe' }}>
                  {[hubCtx.boardName, hubCtx.className, hubCtx.streamName, hubCtx.subjectName]
                    .filter(Boolean).join(' › ')}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={scopeSubjectOnly}
                    onChange={e => setScopeSubjectOnly(e.target.checked)}
                    className="rounded"
                  />
                  <span className="text-[11px]" style={{ color: 'rgba(255,255,255,0.45)' }}>
                    Show this subject only
                  </span>
                </label>
              </div>
            </div>
          )}

          <div className="flex gap-2 flex-wrap items-center">
            <div className="relative flex-1 min-w-48">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'rgba(255,255,255,0.25)' }} />
              <input value={topicSearch} onChange={e => setTopicSearch(e.target.value)} placeholder="Search topics…"
                className="w-full h-9 pl-8 pr-3 rounded-xl text-sm outline-none"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: '#E8E8E8' }}
              />
            </div>
            <button onClick={() => handleExtract(false)} disabled={extracting}
              className="h-9 px-4 rounded-xl text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50"
              style={{ background: '#7c3aed', color: '#fff' }}>
              {extracting ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
              {hubCtx?.subjectName
                ? `Auto-Extract from ${hubCtx.subjectName}`
                : 'Auto-Extract from Chapters'}
            </button>
            {hubCtx?.subjectId && (
              <button onClick={() => handleExtract(true)} disabled={extracting}
                title="Re-extract and replace existing topics"
                className="h-9 px-3 rounded-xl text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50"
                style={{ background: 'rgba(239,68,68,0.12)', color: '#fca5a5', border: '1px solid rgba(239,68,68,0.25)' }}>
                <RefreshCw size={12} />
                Re-extract
              </button>
            )}
          </div>

          {loading ? (
            <div className="space-y-2">{[...Array(6)].map((_, i) => <div key={i} className="h-14 rounded-xl animate-pulse" style={{ background: 'rgba(255,255,255,0.02)' }} />)}</div>
          ) : filteredTopics.length === 0 ? (
            <div className="rounded-xl p-10 text-center border" style={{ background: 'rgba(255,255,255,0.01)', borderColor: 'rgba(255,255,255,0.06)' }}>
              <BookOpen size={28} className="mx-auto mb-3" style={{ color: 'rgba(255,255,255,0.10)' }} />
              <p className="text-sm" style={{ color: 'rgba(255,255,255,0.30)' }}>
                {topics.length === 0
                  ? 'No topics yet. Click "Auto-Extract from Chapters" to bootstrap.'
                  : 'No topics match your search.'}
              </p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {filteredTopics.map(topic => {
                const tid = topic._id || topic.id;
                const isSel = selectedTopics.has(tid);
                return (
                  <div key={tid} onClick={() => toggleTopic(tid)}
                    className="flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-all"
                    style={{
                      background: isSel ? 'rgba(124,58,237,0.08)' : 'rgba(255,255,255,0.02)',
                      borderColor: isSel ? 'rgba(124,58,237,0.35)' : 'rgba(255,255,255,0.06)',
                    }}>
                    <div className={`w-4 h-4 rounded flex items-center justify-center flex-shrink-0 border transition-all ${isSel ? 'border-violet-500' : ''}`}
                      style={isSel ? { background: '#7c3aed', borderColor: '#7c3aed' } : { borderColor: 'rgba(255,255,255,0.20)' }}>
                      {isSel && <CheckCircle2 size={10} className="text-white" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate" style={{ color: '#E8E8E8' }}>{topic.title}</p>
                      <p className="text-xs truncate" style={{ color: 'rgba(255,255,255,0.30)' }}>
                        {[topic.subject_name, topic.chapter_title].filter(Boolean).join(' › ')}
                      </p>
                    </div>
                    <span className="text-[10px] font-mono" style={{ color: 'rgba(255,255,255,0.18)' }}>{topic.slug}</span>
                    <button onClick={e => { e.stopPropagation(); handleDeleteTopic(topic); }}
                      className="flex-shrink-0 p-1 rounded transition-colors" style={{ color: 'rgba(255,255,255,0.20)' }}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {selectedTopics.size > 0 && (
            <div className="flex items-center justify-between p-3 rounded-xl border"
              style={{ background: 'rgba(124,58,237,0.08)', borderColor: 'rgba(124,58,237,0.30)' }}>
              <span className="text-sm" style={{ color: '#c4b0f0' }}>{selectedTopics.size} topic{selectedTopics.size !== 1 ? 's' : ''} selected</span>
              <button onClick={() => setTab('generate')}
                className="h-8 px-3 rounded-lg text-xs font-semibold flex items-center gap-1"
                style={{ background: '#7c3aed', color: '#fff' }}>
                Generate Content <ArrowRight size={12} />
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Insights Tab ──────────────────────────────────────────────── */}
      {tab === 'insights' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold" style={{ color: 'rgba(232,232,232,0.80)' }}>AI Gap Analysis</p>
              <p className="text-xs mt-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>Actionable insights based on your current topic and page coverage</p>
            </div>
            <button onClick={loadInsights} disabled={insightsLoading}
              className="h-8 px-3 rounded-lg text-xs flex items-center gap-1.5 border disabled:opacity-50"
              style={{ color: 'rgba(255,255,255,0.50)', borderColor: 'rgba(255,255,255,0.10)' }}>
              <RefreshCw size={12} className={insightsLoading ? 'animate-spin' : ''} /> Refresh
            </button>
          </div>

          {insightsLoading ? (
            <div className="space-y-3">{[...Array(4)].map((_, i) => <div key={i} className="h-24 rounded-xl animate-pulse" style={{ background: 'rgba(255,255,255,0.02)' }} />)}</div>
          ) : !insights ? (
            <div className="rounded-xl p-10 text-center border" style={{ background: 'rgba(255,255,255,0.01)', borderColor: 'rgba(255,255,255,0.06)' }}>
              <Sparkles size={28} className="mx-auto mb-3" style={{ color: 'rgba(255,255,255,0.10)' }} />
              <p className="text-sm mb-4" style={{ color: 'rgba(255,255,255,0.30)' }}>Click Refresh to generate gap analysis</p>
              <button onClick={loadInsights} className="h-9 px-4 rounded-xl text-xs font-semibold mx-auto flex items-center gap-2"
                style={{ background: '#7c3aed', color: '#fff' }}>
                <Sparkles size={13} /> Analyse Gaps
              </button>
            </div>
          ) : (
            <>
              {/* Summary stats */}
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-xl p-3 border text-center" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }}>
                  <p className="text-xl font-bold" style={{ color: '#E8E8E8' }}>{insights.summary?.total_topics ?? 0}</p>
                  <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>Total Topics</p>
                </div>
                <div className="rounded-xl p-3 border text-center" style={{ background: 'rgba(239,68,68,0.06)', borderColor: 'rgba(239,68,68,0.18)' }}>
                  <p className="text-xl font-bold" style={{ color: '#f87171' }}>{insights.summary?.topics_with_no_pages ?? 0}</p>
                  <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>No pages yet</p>
                </div>
                <div className="rounded-xl p-3 border text-center" style={{ background: 'rgba(124,58,237,0.06)', borderColor: 'rgba(124,58,237,0.18)' }}>
                  <p className="text-xl font-bold" style={{ color: '#a78bfa' }}>
                    {Object.values(insights.summary?.page_type_gaps || {}).reduce((a, b) => a + b, 0)}
                  </p>
                  <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>Total gaps</p>
                </div>
              </div>

              {/* Insight cards */}
              {insights.insights?.length > 0 ? (
                <div className="space-y-2.5">
                  {insights.insights.map((insight, i) => (
                    <InsightCard key={i} insight={insight}
                      onAction={handleInsightAction}
                      loading={actionLoading === insight.title} />
                  ))}
                </div>
              ) : (
                <div className="rounded-xl p-6 text-center border" style={{ background: 'rgba(16,185,129,0.05)', borderColor: 'rgba(16,185,129,0.15)' }}>
                  <CheckCheck size={24} className="mx-auto mb-2" style={{ color: '#34d399' }} />
                  <p className="text-sm font-semibold" style={{ color: '#34d399' }}>Full coverage!</p>
                  <p className="text-xs mt-1" style={{ color: 'rgba(255,255,255,0.30)' }}>All topics have all page types. Nothing to fill.</p>
                </div>
              )}

              {/* Per-subject breakdown */}
              {insights.subject_breakdown?.length > 0 && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: 'rgba(255,255,255,0.25)' }}>Subject Breakdown</p>
                  <div className="space-y-2">
                    {insights.subject_breakdown.map((s, i) => (
                      <div key={i} className="rounded-xl p-3 border" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }}>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-medium" style={{ color: '#E8E8E8' }}>{s.subject}</span>
                          <span className="text-[10px]" style={{ color: 'rgba(255,255,255,0.30)' }}>{s.board} · {s.class}</span>
                        </div>
                        <div className="flex gap-1.5 flex-wrap">
                          {PAGE_TYPES.map(pt => (
                            <span key={pt.id} className="text-[10px] px-2 py-0.5 rounded-full"
                              style={{
                                background: s[pt.id] > 0 ? `${pt.color}20` : 'rgba(255,255,255,0.04)',
                                color: s[pt.id] > 0 ? pt.color : 'rgba(255,255,255,0.20)',
                                border: `1px solid ${s[pt.id] > 0 ? pt.color + '40' : 'rgba(255,255,255,0.06)'}`,
                              }}>
                              {pt.label.split(' ')[0]} {s[pt.id] > 0 ? `×${s[pt.id]}` : '—'}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ── Generate Tab ──────────────────────────────────────────────── */}
      {tab === 'generate' && (
        <div className="space-y-5">
          <div className="rounded-xl p-4 border" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }}>
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-semibold" style={{ color: '#E8E8E8' }}>Selected Topics</p>
              <button onClick={() => setTab('topics')} className="text-xs" style={{ color: '#a78bfa' }}>
                {selectedTopics.size === 0 ? 'Select topics →' : `${selectedTopics.size} selected — change`}
              </button>
            </div>
            {selectedTopics.size === 0 ? (
              <p className="text-xs" style={{ color: 'rgba(255,255,255,0.30)' }}>No topics selected. Go to the Topics tab to pick topics.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {[...selectedTopics].map(tid => {
                  const t = topics.find(x => (x._id || x.id) === tid);
                  return t ? (
                    <span key={tid} className="px-2 py-0.5 rounded-full text-xs flex items-center gap-1"
                      style={{ background: 'rgba(124,58,237,0.12)', color: '#a78bfa', border: '1px solid rgba(124,58,237,0.25)' }}>
                      {t.title}
                      <button onClick={() => toggleTopic(tid)}><XCircle size={10} /></button>
                    </span>
                  ) : null;
                })}
              </div>
            )}
          </div>

          <div className="rounded-xl p-4 border" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }}>
            <p className="text-sm font-semibold mb-3" style={{ color: '#E8E8E8' }}>Page Types to Generate</p>
            <div className="flex flex-wrap gap-2">
              {PAGE_TYPES.map(({ id, label, color }) => {
                const sel = selectedTypes.has(id);
                return (
                  <button key={id} onClick={() => toggleType(id)}
                    className="h-8 px-3 rounded-xl text-xs font-medium border transition-all"
                    style={sel ? { background: color + '20', borderColor: color + '60', color } : { borderColor: 'rgba(255,255,255,0.12)', color: 'rgba(255,255,255,0.40)' }}>
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="rounded-xl p-4 border" style={{ background: 'rgba(124,58,237,0.05)', borderColor: 'rgba(124,58,237,0.20)' }}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold" style={{ color: '#E8E8E8' }}>
                  Will generate: <span style={{ color: '#a78bfa' }}>{selectedTopics.size * selectedTypes.size} pages</span>
                </p>
                <p className="text-xs mt-0.5" style={{ color: 'rgba(255,255,255,0.35)' }}>
                  {selectedTopics.size} topics × {selectedTypes.size} page types · Runs in background
                </p>
              </div>
              <button onClick={handleGenerate} disabled={generating || !selectedTopics.size || !selectedTypes.size}
                className="h-10 px-5 rounded-xl text-sm font-semibold flex items-center gap-2 disabled:opacity-40"
                style={{ background: '#7c3aed', color: '#fff' }}>
                {generating ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                Generate Content
              </button>
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'rgba(255,255,255,0.25)' }}>How it works</p>
            {[
              ['1. Extract Topics', 'Topics tab → Auto-Extract — pulls topic names from all uploaded chapters'],
              ['2. Select Topics', 'Check topics you want to generate pages for'],
              ['3. Choose Page Types', 'Notes, Definitions, MCQs, Important Questions, or Examples'],
              ['4. Generate', 'AI generates structured, exam-aligned content with GEO authority signals'],
              ['5. Publish', 'Pages go live at /{board}/{class}/{subject}/{topic}/{type}'],
            ].map(([h, d]) => (
              <div key={h} className="flex items-start gap-3 p-3 rounded-xl" style={{ background: 'rgba(255,255,255,0.02)' }}>
                <ChevronRight size={13} className="flex-shrink-0 mt-0.5" style={{ color: '#7c3aed' }} />
                <div>
                  <p className="text-xs font-semibold" style={{ color: 'rgba(232,232,232,0.70)' }}>{h}</p>
                  <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>{d}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Pilot Tab ─────────────────────────────────────────────────── */}
      {tab === 'pilot' && (
        <div className="space-y-5 max-w-lg">
          <div>
            <p className="text-sm font-semibold mb-1" style={{ color: '#E8E8E8' }}>Seed Pilot Content</p>
            <p className="text-xs" style={{ color: 'rgba(255,255,255,0.35)' }}>
              Generate full SEO content for the first N chapters of a subject — use this to test the pipeline before running at scale.
            </p>
          </div>

          <div className="space-y-3">
            {[
              { label: 'Board', value: pilotBoard, onChange: setPilotBoard, placeholder: 'AHSEC' },
              { label: 'Class', value: pilotClass, onChange: setPilotClass, placeholder: 'Class 11' },
              { label: 'Subject keyword', value: pilotSubject, onChange: setPilotSubject, placeholder: 'maths / physics / english…' },
            ].map(({ label, value, onChange, placeholder }) => (
              <div key={label}>
                <label className="text-[11px] block mb-1.5" style={{ color: 'rgba(255,255,255,0.40)' }}>{label}</label>
                <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
                  className="w-full h-10 px-3 rounded-xl text-sm outline-none"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)', color: '#E8E8E8' }}
                />
              </div>
            ))}
            <div>
              <label className="text-[11px] block mb-1.5" style={{ color: 'rgba(255,255,255,0.40)' }}>Chapter limit</label>
              <input type="number" min={1} max={20} value={pilotChapters} onChange={e => setPilotChapters(Number(e.target.value))}
                className="w-full h-10 px-3 rounded-xl text-sm outline-none"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)', color: '#E8E8E8' }}
              />
            </div>
          </div>

          <button onClick={handlePilot} disabled={piloting || !pilotSubject.trim()}
            className="w-full h-11 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 disabled:opacity-40"
            style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)', color: '#fff' }}>
            {piloting ? <><Loader2 size={15} className="animate-spin" /> Generating pilot…</> : <><Sparkles size={15} /> Run Pilot</>}
          </button>

          {pilotResult && !pilotResult.error && (
            <div className="rounded-xl p-4 border" style={{ background: 'rgba(16,185,129,0.07)', borderColor: 'rgba(16,185,129,0.20)' }}>
              <p className="text-xs font-semibold mb-2" style={{ color: '#34d399' }}>Pilot Complete</p>
              {[
                ['Subject', pilotResult.subject],
                ['Chapters processed', pilotResult.chapters_processed],
                ['Topics created', pilotResult.topics_created],
                ['Pages generated', pilotResult.pages_generated],
                ['Errors', pilotResult.errors],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between py-1 border-b" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
                  <span className="text-xs" style={{ color: 'rgba(255,255,255,0.40)' }}>{k}</span>
                  <span className="text-xs font-semibold" style={{ color: '#E8E8E8' }}>{v ?? '—'}</span>
                </div>
              ))}
            </div>
          )}
          {pilotResult?.error && (
            <div className="rounded-xl p-4 border" style={{ background: 'rgba(239,68,68,0.07)', borderColor: 'rgba(239,68,68,0.20)' }}>
              <p className="text-xs font-semibold" style={{ color: '#f87171' }}>Error: {pilotResult.error}</p>
            </div>
          )}
        </div>
      )}

      {/* ── Internal Links Tab ─────────────────────────────────────── */}
      {tab === 'links' && (
        <div className="space-y-5">
          <div className="rounded-xl border p-5 space-y-4" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.08)' }}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-white">Internal Link Analysis</p>
                <p className="text-xs mt-0.5" style={{ color: 'rgba(255,255,255,0.35)' }}>Analyzes all published pages and maps semantic link opportunities</p>
              </div>
              <button onClick={handleLinksAnalyze} disabled={linksLoading}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
                style={{ background: '#7c3aed', color: '#fff' }}>
                {linksLoading ? <Loader2 size={14} className="animate-spin" /> : <Activity size={14} />}
                {linksLoading ? 'Analyzing…' : 'Analyze Links'}
              </button>
            </div>
            {linksData && (
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'Pages Analyzed', val: linksData.pages_analyzed },
                  { label: 'Opportunities', val: linksData.total_opportunities },
                  { label: 'High Priority', val: linksData.high_priority },
                ].map(s => (
                  <div key={s.label} className="rounded-lg p-3 text-center border" style={{ background: 'rgba(124,58,237,0.08)', borderColor: 'rgba(124,58,237,0.20)' }}>
                    <p className="text-xl font-bold text-white">{s.val ?? '—'}</p>
                    <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.40)' }}>{s.label}</p>
                  </div>
                ))}
              </div>
            )}
            {linksData?.top_opportunities?.length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: 'rgba(255,255,255,0.30)' }}>Top Link Opportunities</p>
                <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                  {linksData.top_opportunities.slice(0, 20).map((op, i) => (
                    <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg" style={{ background: 'rgba(255,255,255,0.03)' }}>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: 'rgba(124,58,237,0.15)', color: '#a78bfa' }}>
                        {(op.score * 100).toFixed(0)}%
                      </span>
                      <span className="text-xs flex-1 truncate" style={{ color: 'rgba(232,232,232,0.70)' }}>{op.source_slug}</span>
                      <ArrowRight size={11} style={{ color: 'rgba(255,255,255,0.25)', flexShrink: 0 }} />
                      <span className="text-xs flex-1 truncate text-right" style={{ color: 'rgba(255,255,255,0.40)' }}>{op.target_slug}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="rounded-xl border p-5 space-y-3" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.08)' }}>
            <p className="text-sm font-semibold text-white">Inject Links into a Page</p>
            <div className="flex gap-2">
              <input value={injectSlug} onChange={e => setInjectSlug(e.target.value)}
                placeholder="page-slug (e.g. ahsec/class-11/physics/motion/notes)"
                className="flex-1 h-9 px-3 rounded-xl text-sm outline-none font-mono"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.10)', color: '#E8E8E8' }} />
              <button onClick={handleLinksInject} disabled={injecting || !injectSlug.trim()}
                className="px-4 h-9 rounded-xl text-sm font-semibold disabled:opacity-40"
                style={{ background: '#059669', color: '#fff' }}>
                {injecting ? <Loader2 size={14} className="animate-spin" /> : 'Inject'}
              </button>
            </div>
            <p className="text-[11px]" style={{ color: 'rgba(255,255,255,0.25)' }}>
              Injects contextually-relevant internal links into the specified page using semantic similarity.
            </p>
          </div>
        </div>
      )}

      {/* ── Schema Tab ─────────────────────────────────────────────── */}
      {tab === 'schema' && (
        <div className="space-y-5">
          <div className="rounded-xl border p-5 space-y-4" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.08)' }}>
            <div>
              <p className="text-sm font-semibold text-white mb-1">Inject Schema for Single Page</p>
              <p className="text-xs mb-3" style={{ color: 'rgba(255,255,255,0.35)' }}>Add structured data (schema.org) to a specific page to improve rich snippet eligibility</p>
              <div className="flex gap-2">
                <input value={schemaSlug} onChange={e => setSchemaSlug(e.target.value)}
                  placeholder="page-slug"
                  className="flex-1 h-9 px-3 rounded-xl text-sm outline-none font-mono"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.10)', color: '#E8E8E8' }} />
                <button onClick={handleSchemaInjectSingle} disabled={schemaLoading || !schemaSlug.trim()}
                  className="px-4 h-9 rounded-xl text-sm font-semibold disabled:opacity-40"
                  style={{ background: '#0891b2', color: '#fff' }}>
                  {schemaLoading ? <Loader2 size={14} className="animate-spin" /> : 'Inject'}
                </button>
              </div>
              {schemaResult && (
                <div className="mt-3 rounded-lg p-3 border text-xs font-mono overflow-x-auto" style={{ background: 'rgba(8,145,178,0.07)', borderColor: 'rgba(8,145,178,0.20)', color: '#67e8f9' }}>
                  {JSON.stringify(schemaResult, null, 2).slice(0, 600)}
                </div>
              )}
            </div>
          </div>
          <div className="rounded-xl border p-5" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.08)' }}>
            <p className="text-sm font-semibold text-white mb-1">Bulk Schema Injection</p>
            <p className="text-xs mb-4" style={{ color: 'rgba(255,255,255,0.35)' }}>
              Auto-generate and inject schema.org JSON-LD markup into all {publishedCount} published pages. 
              Uses EducationalOrganization + Article schema types.
            </p>
            <button onClick={handleSchemaBulk} disabled={schemaLoading}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold disabled:opacity-40"
              style={{ background: 'linear-gradient(135deg,#0891b2,#06b6d4)', color: '#fff' }}>
              {schemaLoading ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
              Bulk Inject Schema ({publishedCount} pages)
            </button>
          </div>
        </div>
      )}

      {/* ── Sitemap Tab ─────────────────────────────────────────────── */}
      {tab === 'sitemap' && (
        <div className="space-y-5">
          <div className="rounded-xl border p-5 space-y-4" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.08)' }}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-white">Sitemap Validator</p>
                <p className="text-xs mt-0.5" style={{ color: 'rgba(255,255,255,0.35)' }}>Validates your sitemap.xml coverage and detects missing or stale URLs</p>
              </div>
              <button onClick={handleSitemapValidate} disabled={sitemapValidating}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
                style={{ background: '#16a34a', color: '#fff' }}>
                {sitemapValidating ? <Loader2 size={14} className="animate-spin" /> : <Map size={14} />}
                {sitemapValidating ? 'Validating…' : 'Validate Sitemap'}
              </button>
            </div>
            {sitemapData && (
              <div className="space-y-3">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: 'Total URLs', val: sitemapData.total_urls },
                    { label: 'In Sitemap', val: sitemapData.in_sitemap },
                    { label: 'Missing', val: sitemapData.missing },
                    { label: 'Coverage %', val: sitemapData.coverage_pct != null ? `${sitemapData.coverage_pct}%` : '—' },
                  ].map(s => (
                    <div key={s.label} className="rounded-lg p-3 text-center border" style={{ background: 'rgba(22,163,74,0.08)', borderColor: 'rgba(22,163,74,0.20)' }}>
                      <p className="text-xl font-bold text-white">{s.val ?? '—'}</p>
                      <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.40)' }}>{s.label}</p>
                    </div>
                  ))}
                </div>
                {sitemapData.issues?.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'rgba(255,255,255,0.30)' }}>Issues Detected</p>
                    <div className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
                      {sitemapData.issues.map((issue, i) => (
                        <div key={i} className="flex items-start gap-2 p-2 rounded-lg" style={{ background: 'rgba(239,68,68,0.06)' }}>
                          <AlertTriangle size={12} className="text-red-400 flex-shrink-0 mt-0.5" />
                          <span className="text-xs font-mono" style={{ color: 'rgba(232,232,232,0.60)' }}>{issue}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {sitemapData.ok && !sitemapData.issues?.length && (
                  <div className="flex items-center gap-2 p-3 rounded-xl" style={{ background: 'rgba(22,163,74,0.08)', border: '1px solid rgba(22,163,74,0.20)' }}>
                    <CheckCircle2 size={16} className="text-emerald-400" />
                    <p className="text-sm font-medium text-emerald-400">Sitemap is valid — {sitemapData.coverage_pct}% coverage</p>
                  </div>
                )}
              </div>
            )}
            {!sitemapData && !sitemapValidating && (
              <p className="text-sm text-center py-4" style={{ color: 'rgba(255,255,255,0.20)' }}>Click "Validate Sitemap" to run a coverage check</p>
            )}
          </div>
          <div className="rounded-xl border p-4" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.06)' }}>
            <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: 'rgba(255,255,255,0.25)' }}>Sitemap Actions</p>
            <button onClick={handleRegenerateSitemap} disabled={sitemap}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
              style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.10)', color: 'rgba(232,232,232,0.70)' }}>
              {sitemap ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              Regenerate sitemap.xml
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
