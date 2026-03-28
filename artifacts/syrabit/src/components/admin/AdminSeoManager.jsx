import { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw, Globe, FileText, Sparkles, CheckCircle2,
  XCircle, BookOpen, Zap, Map, Eye, EyeOff, Trash2, Search } from 'lucide-react';
import { toast } from 'sonner';
import {
  adminSeoStats, adminSeoListTopics, adminSeoExtractTopics,
  adminSeoGenerate, adminSeoListPages, adminSeoUpdatePageStatus,
  adminSeoRegenerateSitemap, adminSeoDeleteTopic, adminSeoPilot,
} from '@/utils/api';

const PAGE_TYPES = [
  { id: 'notes',               label: 'Notes' },
  { id: 'definition',          label: 'Definition' },
  { id: 'important-questions', label: 'Important Questions' },
  { id: 'mcqs',                label: 'MCQs' },
  { id: 'examples',            label: 'Examples' },
];

const STATUS_COLORS = {
  published: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
  draft:     'text-amber-400  bg-amber-400/10  border-amber-400/20',
  archived:  'text-slate-400  bg-slate-400/10  border-slate-400/20',
};

function StatCard({ icon: Icon, label, value, color = 'text-white' }) {
  return (
    <div className="rounded-xl p-4 border border-white/6" style={{ background: 'rgba(255,255,255,0.02)' }}>
      <Icon size={16} className={`${color} mb-2`} />
      <p className={`text-2xl font-bold ${color}`}>{value ?? '—'}</p>
      <p className="text-[11px] text-white/30 mt-0.5">{label}</p>
    </div>
  );
}

export default function AdminSeoManager({ adminToken }) {
  const [tab, setTab]               = useState('pages');
  const [stats, setStats]           = useState(null);
  const [topics, setTopics]         = useState([]);
  const [pages, setPages]           = useState([]);
  const [loading, setLoading]       = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [sitemap, setSitemap]       = useState(false);
  const [piloting, setPiloting]     = useState(false);
  const [pilotResult, setPilotResult] = useState(null);
  const [pilotBoard, setPilotBoard]   = useState('AHSEC');
  const [pilotClass, setPilotClass]   = useState('Class 11');
  const [pilotSubject, setPilotSubject] = useState('maths');
  const [pilotChapters, setPilotChapters] = useState(3);

  const [topicSearch, setTopicSearch]     = useState('');
  const [pageSearch, setPageSearch]       = useState('');
  const [pageFilter, setPageFilter]       = useState('all');
  const [selectedTopics, setSelectedTopics] = useState(new Set());
  const [selectedTypes, setSelectedTypes]   = useState(new Set(['notes', 'important-questions', 'mcqs']));

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
      setPages(Array.isArray(pagesRes.data) ? pagesRes.data : []);
    } catch (e) {
      toast.error('Failed to load SEO data');
    } finally {
      setLoading(false);
    }
  }, [adminToken]);

  useEffect(() => { load(); }, [load]);

  const handleExtract = async () => {
    setExtracting(true);
    try {
      const res = await adminSeoExtractTopics(adminToken, null);
      toast.success(`Extracted ${res.data?.created || 0} new topics`);
      load();
    } catch {
      toast.error('Topic extraction failed');
    } finally {
      setExtracting(false);
    }
  };

  const handleGenerate = async () => {
    if (!selectedTopics.size) { toast.error('Select at least one topic'); return; }
    if (!selectedTypes.size)  { toast.error('Select at least one page type'); return; }
    setGenerating(true);
    try {
      const res = await adminSeoGenerate(adminToken, {
        topic_ids:  [...selectedTopics],
        page_types: [...selectedTypes],
      });
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
      setPages((prev) => prev.map((p) => (p._id === page._id || p.id === page.id) ? { ...p, status: newStatus } : p));
      toast.success(`Page ${newStatus === 'published' ? 'published' : 'unpublished'}`);
    } catch { toast.error('Status update failed'); }
  };

  const handleDeleteTopic = async (topic) => {
    if (!confirm(`Delete topic "${topic.title}"?`)) return;
    try {
      await adminSeoDeleteTopic(adminToken, topic._id || topic.id);
      setTopics((prev) => prev.filter((t) => (t._id || t.id) !== (topic._id || topic.id)));
      toast.success('Topic deleted');
    } catch { toast.error('Delete failed'); }
  };

  const handleRegenerateSitemap = async () => {
    setSitemap(true);
    try {
      await adminSeoRegenerateSitemap(adminToken);
      toast.success('Sitemap regenerated successfully');
    } catch { toast.error('Sitemap regeneration failed'); }
    finally { setSitemap(false); }
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
      const msg = e?.response?.data?.detail || 'Pilot generation failed';
      toast.error(msg);
      setPilotResult({ error: msg });
    } finally {
      setPiloting(false);
    }
  };

  const toggleTopic = (id) => setSelectedTopics((prev) => {
    const n = new Set(prev);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  const toggleType = (id) => setSelectedTypes((prev) => {
    const n = new Set(prev);
    if (n.has(id)) n.delete(id); else n.add(id);
    return n;
  });

  const filteredTopics = topics.filter((t) => {
    if (!topicSearch.trim()) return true;
    const q = topicSearch.toLowerCase();
    return (t.title || '').toLowerCase().includes(q) ||
           (t.subject_name || '').toLowerCase().includes(q) ||
           (t.chapter_title || '').toLowerCase().includes(q);
  });

  const filteredPages = pages.filter((p) => {
    if (pageFilter !== 'all' && p.status !== pageFilter) return false;
    if (!pageSearch.trim()) return true;
    const q = pageSearch.toLowerCase();
    return (p.title || '').toLowerCase().includes(q) ||
           (p.topic_title || '').toLowerCase().includes(q) ||
           (p.subject_name || '').toLowerCase().includes(q);
  });

  const publishedCount = pages.filter((p) => p.status === 'published').length;
  const draftCount     = pages.filter((p) => p.status !== 'published').length;

  const TABS = [
    { id: 'pages',    label: 'SEO Pages',  count: pages.length },
    { id: 'topics',   label: 'Topics',     count: topics.length },
    { id: 'generate', label: 'Generate',   count: null },
    { id: 'pilot',    label: 'Pilot',      count: null },
  ];

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-lg font-bold text-white">SEO Content Manager</h2>
          <p className="text-sm text-white/40 mt-0.5">Manage topic pages, generate AI content, and control what Googlebot crawls</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="h-9 px-3 rounded-xl text-xs text-white/60 hover:text-white border border-white/10 hover:border-white/20 flex items-center gap-1.5 transition-colors"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button
            onClick={handleRegenerateSitemap}
            disabled={sitemap}
            className="h-9 px-3 rounded-xl text-xs text-white flex items-center gap-1.5 border border-white/10 hover:border-white/20 transition-colors disabled:opacity-50"
          >
            {sitemap ? <Loader2 size={13} className="animate-spin" /> : <Map size={13} />} Regen Sitemap
          </button>
          <a
            href="/api/seo/sitemap.xml"
            target="_blank"
            rel="noopener"
            className="h-9 px-3 rounded-xl text-xs text-violet-300 bg-violet-500/10 border border-violet-500/25 flex items-center gap-1.5 hover:bg-violet-500/20 transition-colors"
          >
            <Globe size={13} /> View Sitemap
          </a>
        </div>
      </div>

      {/* Stats row */}
      {loading ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="rounded-xl p-4 border border-white/6 h-24 animate-pulse" style={{ background: 'rgba(255,255,255,0.02)' }} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard icon={BookOpen}    label="Total Topics"     value={stats?.total_topics ?? topics.length}  color="text-white" />
          <StatCard icon={CheckCircle2} label="Published Pages"  value={publishedCount}                        color="text-emerald-400" />
          <StatCard icon={FileText}    label="Draft Pages"      value={draftCount}                            color="text-amber-400" />
          <StatCard icon={Globe}       label="Sitemap URLs"     value={stats?.sitemap_urls ?? publishedCount} color="text-violet-400" />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-xl" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
        {TABS.map(({ id, label, count }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex-1 h-8 rounded-lg text-xs font-semibold transition-all flex items-center justify-center gap-1.5 ${
              tab === id ? 'bg-violet-600 text-white shadow' : 'text-white/40 hover:text-white/70'
            }`}
          >
            {label}
            {count !== null && (
              <span className={`px-1.5 py-0.5 rounded-full text-[10px] ${tab === id ? 'bg-white/20 text-white' : 'bg-white/5 text-white/30'}`}>
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── SEO Pages Tab ── */}
      {tab === 'pages' && (
        <div className="space-y-3">
          {/* Filters */}
          <div className="flex gap-2 flex-wrap">
            <div className="relative flex-1 min-w-48">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
              <input
                value={pageSearch}
                onChange={(e) => setPageSearch(e.target.value)}
                placeholder="Search pages…"
                className="w-full h-9 pl-8 pr-3 rounded-xl text-sm text-white placeholder:text-white/25 outline-none"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
              />
            </div>
            {['all', 'published', 'draft'].map((f) => (
              <button
                key={f}
                onClick={() => setPageFilter(f)}
                className={`h-9 px-3 rounded-xl text-xs capitalize font-medium transition-all ${pageFilter === f ? 'bg-violet-600 text-white' : 'text-white/40 hover:text-white/70 border border-white/8'}`}
              >
                {f === 'all' ? 'All' : f === 'published' ? `Published (${publishedCount})` : `Draft (${draftCount})`}
              </button>
            ))}
          </div>

          {/* Pages list */}
          {loading ? (
            <div className="space-y-2">{[...Array(5)].map((_, i) => <div key={i} className="h-16 rounded-xl animate-pulse" style={{ background: 'rgba(255,255,255,0.02)' }} />)}</div>
          ) : filteredPages.length === 0 ? (
            <div className="rounded-xl p-8 text-center border border-white/6" style={{ background: 'rgba(255,255,255,0.01)' }}>
              <FileText size={28} className="text-white/10 mx-auto mb-3" />
              <p className="text-white/30 text-sm">
                {pages.length === 0 ? 'No SEO pages generated yet. Go to Generate tab to create content.' : 'No pages match your filter.'}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredPages.map((page) => {
                const pid = page._id || page.id;
                return (
                  <div key={pid} className="flex items-center gap-3 p-3 rounded-xl border border-white/6 hover:border-white/10 transition-colors" style={{ background: 'rgba(255,255,255,0.02)' }}>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white font-medium truncate">{page.title || page.topic_title || '—'}</p>
                      <p className="text-xs text-white/30 truncate mt-0.5">
                        {[page.board_name, page.class_name, page.subject_name, page.page_type].filter(Boolean).join(' · ')}
                      </p>
                    </div>
                    <span className={`shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${STATUS_COLORS[page.status] || STATUS_COLORS.draft}`}>
                      {page.status || 'draft'}
                    </span>
                    <button
                      onClick={() => handleToggleStatus(page)}
                      title={page.status === 'published' ? 'Unpublish' : 'Publish'}
                      className="shrink-0 p-1.5 rounded-lg text-white/30 hover:text-white transition-colors"
                    >
                      {page.status === 'published' ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                    {page.url && (
                      <a
                        href={page.url}
                        target="_blank"
                        rel="noopener"
                        className="shrink-0 p-1.5 rounded-lg text-white/30 hover:text-violet-400 transition-colors"
                        title="View page"
                      >
                        <Globe size={15} />
                      </a>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Topics Tab ── */}
      {tab === 'topics' && (
        <div className="space-y-3">
          {/* Actions */}
          <div className="flex gap-2 flex-wrap items-center">
            <div className="relative flex-1 min-w-48">
              <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
              <input
                value={topicSearch}
                onChange={(e) => setTopicSearch(e.target.value)}
                placeholder="Search topics…"
                className="w-full h-9 pl-8 pr-3 rounded-xl text-sm text-white placeholder:text-white/25 outline-none"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
              />
            </div>
            <button
              onClick={handleExtract}
              disabled={extracting}
              className="h-9 px-4 rounded-xl text-xs font-semibold text-white bg-violet-600 hover:bg-violet-500 flex items-center gap-1.5 disabled:opacity-50 transition-colors"
            >
              {extracting ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
              Auto-Extract from Chapters
            </button>
          </div>

          {/* Topics list */}
          {loading ? (
            <div className="space-y-2">{[...Array(6)].map((_, i) => <div key={i} className="h-14 rounded-xl animate-pulse" style={{ background: 'rgba(255,255,255,0.02)' }} />)}</div>
          ) : filteredTopics.length === 0 ? (
            <div className="rounded-xl p-8 text-center border border-white/6" style={{ background: 'rgba(255,255,255,0.01)' }}>
              <BookOpen size={28} className="text-white/10 mx-auto mb-3" />
              <p className="text-white/30 text-sm">
                {topics.length === 0
                  ? 'No topics yet. Click "Auto-Extract from Chapters" to pull topics from your uploaded chapter content.'
                  : 'No topics match your search.'}
              </p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {filteredTopics.map((topic) => {
                const tid = topic._id || topic.id;
                const isSelected = selectedTopics.has(tid);
                return (
                  <div
                    key={tid}
                    onClick={() => toggleTopic(tid)}
                    className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-all ${isSelected ? 'border-violet-500/40 bg-violet-500/5' : 'border-white/6 hover:border-white/12'}`}
                    style={!isSelected ? { background: 'rgba(255,255,255,0.02)' } : {}}
                  >
                    <div className={`w-4 h-4 rounded flex items-center justify-center shrink-0 border transition-all ${isSelected ? 'bg-violet-600 border-violet-500' : 'border-white/20'}`}>
                      {isSelected && <CheckCircle2 size={10} className="text-white" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white font-medium truncate">{topic.title}</p>
                      <p className="text-xs text-white/30 truncate">
                        {[topic.subject_name, topic.chapter_title].filter(Boolean).join(' › ')}
                      </p>
                    </div>
                    <span className="text-[10px] text-white/20 shrink-0">
                      {topic.slug}
                    </span>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDeleteTopic(topic); }}
                      className="shrink-0 p-1 rounded text-white/20 hover:text-red-400 transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {selectedTopics.size > 0 && (
            <div className="flex items-center justify-between p-3 rounded-xl border border-violet-500/30 bg-violet-500/5">
              <span className="text-sm text-violet-300">{selectedTopics.size} topic{selectedTopics.size !== 1 ? 's' : ''} selected</span>
              <button
                onClick={() => setTab('generate')}
                className="h-8 px-3 rounded-lg text-xs font-semibold text-white bg-violet-600 hover:bg-violet-500"
              >
                Generate Content →
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Generate Tab ── */}
      {tab === 'generate' && (
        <div className="space-y-5">
          {/* Topic selection summary */}
          <div className="rounded-xl p-4 border border-white/6" style={{ background: 'rgba(255,255,255,0.02)' }}>
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-semibold text-white">Selected Topics</p>
              <button
                onClick={() => setTab('topics')}
                className="text-xs text-violet-400 hover:text-violet-300"
              >
                {selectedTopics.size === 0 ? 'Select topics →' : `${selectedTopics.size} selected — change`}
              </button>
            </div>
            {selectedTopics.size === 0 ? (
              <p className="text-xs text-white/30">No topics selected. Go to the Topics tab to pick which topics to generate SEO content for.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {[...selectedTopics].map((tid) => {
                  const t = topics.find((x) => (x._id || x.id) === tid);
                  return t ? (
                    <span key={tid} className="px-2 py-0.5 rounded-full text-xs text-violet-300 bg-violet-500/10 border border-violet-500/20 flex items-center gap-1">
                      {t.title}
                      <button onClick={() => toggleTopic(tid)} className="text-violet-400/60 hover:text-red-400">
                        <XCircle size={10} />
                      </button>
                    </span>
                  ) : null;
                })}
              </div>
            )}
          </div>

          {/* Page type selection */}
          <div className="rounded-xl p-4 border border-white/6" style={{ background: 'rgba(255,255,255,0.02)' }}>
            <p className="text-sm font-semibold text-white mb-3">Page Types to Generate</p>
            <div className="flex flex-wrap gap-2">
              {PAGE_TYPES.map(({ id, label }) => {
                const sel = selectedTypes.has(id);
                return (
                  <button
                    key={id}
                    onClick={() => toggleType(id)}
                    className={`h-8 px-3 rounded-xl text-xs font-medium border transition-all ${sel ? 'bg-violet-600 border-violet-500 text-white' : 'border-white/12 text-white/40 hover:text-white/70'}`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Summary + generate */}
          <div className="rounded-xl p-4 border border-white/8" style={{ background: 'rgba(124,58,237,0.05)' }}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-white">
                  Will generate: <span className="text-violet-300">{selectedTopics.size * selectedTypes.size} pages</span>
                </p>
                <p className="text-xs text-white/40 mt-0.5">
                  {selectedTopics.size} topics × {selectedTypes.size} page types · Runs in background
                </p>
              </div>
              <button
                onClick={handleGenerate}
                disabled={generating || !selectedTopics.size || !selectedTypes.size}
                className="h-10 px-5 rounded-xl text-sm font-semibold text-white bg-violet-600 hover:bg-violet-500 flex items-center gap-2 disabled:opacity-40 transition-colors"
              >
                {generating ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                Generate Content
              </button>
            </div>
          </div>

          {/* How-it-works */}
          <div className="space-y-2">
            <p className="text-xs font-semibold text-white/30 uppercase tracking-wider">How it works</p>
            {[
              ['1. Extract Topics', 'Go to Topics tab → Auto-Extract from Chapters to pull topics from your uploaded content'],
              ['2. Select Topics', 'Check the topics you want SEO pages for (e.g. "Laws of Motion", "Cell Biology")'],
              ['3. Choose Page Types', 'Notes, Definitions, MCQs, Important Questions, Examples'],
              ['4. Generate', 'AI writes SEO-optimised content for each topic × page type combination'],
              ['5. Publish', 'Go to SEO Pages tab → toggle pages to Published so Googlebot can crawl them'],
              ['6. Sitemap', 'Hit Regen Sitemap so Google Search Console picks up the new URLs immediately'],
            ].map(([title, desc]) => (
              <div key={title} className="flex gap-2 text-xs">
                <span className="text-violet-400 font-semibold shrink-0">{title}:</span>
                <span className="text-white/40">{desc}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Pilot Tab ─────────────────────────────────────────────────────────── */}
      {tab === 'pilot' && (
        <div className="space-y-5">
          <div className="rounded-xl p-5 border border-white/8 space-y-4" style={{ background: 'rgba(255,255,255,0.02)' }}>
            <div>
              <h3 className="text-sm font-semibold text-white">Pilot Content Generation</h3>
              <p className="text-xs text-white/40 mt-0.5">
                Bootstrap SEO pages for the first N chapters of a subject. AI generates all page types (Notes, Definitions, MCQs, Examples, Important Questions) in one shot.
              </p>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="space-y-1">
                <label className="text-[11px] text-white/40 uppercase tracking-wider">Board</label>
                <input
                  value={pilotBoard}
                  onChange={(e) => setPilotBoard(e.target.value)}
                  className="w-full h-9 rounded-xl bg-white/5 border border-white/10 text-sm text-white px-3 focus:outline-none focus:border-violet-500"
                  placeholder="AHSEC"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-white/40 uppercase tracking-wider">Class</label>
                <input
                  value={pilotClass}
                  onChange={(e) => setPilotClass(e.target.value)}
                  className="w-full h-9 rounded-xl bg-white/5 border border-white/10 text-sm text-white px-3 focus:outline-none focus:border-violet-500"
                  placeholder="Class 11"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-white/40 uppercase tracking-wider">Subject keyword</label>
                <input
                  value={pilotSubject}
                  onChange={(e) => setPilotSubject(e.target.value)}
                  className="w-full h-9 rounded-xl bg-white/5 border border-white/10 text-sm text-white px-3 focus:outline-none focus:border-violet-500"
                  placeholder="maths"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-white/40 uppercase tracking-wider">Chapters</label>
                <input
                  type="number" min={1} max={20}
                  value={pilotChapters}
                  onChange={(e) => setPilotChapters(Number(e.target.value))}
                  className="w-full h-9 rounded-xl bg-white/5 border border-white/10 text-sm text-white px-3 focus:outline-none focus:border-violet-500"
                />
              </div>
            </div>
            <button
              onClick={handlePilot}
              disabled={piloting}
              className="h-10 px-6 rounded-xl text-sm font-semibold text-white bg-violet-600 hover:bg-violet-500 flex items-center gap-2 disabled:opacity-50 transition-colors"
            >
              {piloting ? <Loader2 size={15} className="animate-spin" /> : <Zap size={15} />}
              {piloting ? 'Running Pilot…' : 'Run Pilot'}
            </button>
          </div>

          {pilotResult && (
            <div className={`rounded-xl p-4 border text-sm space-y-2 ${pilotResult.error ? 'border-red-500/25 bg-red-500/5' : 'border-emerald-500/25 bg-emerald-500/5'}`}>
              {pilotResult.error ? (
                <p className="text-red-400">{pilotResult.error}</p>
              ) : (
                <>
                  <p className="text-emerald-400 font-semibold">{pilotResult.message}</p>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
                    {[
                      ['Chapters', pilotResult.chapters_processed],
                      ['Topics created', pilotResult.topics_created],
                      ['Pages generated', pilotResult.pages_generated],
                      ['Errors', pilotResult.errors],
                    ].map(([label, val]) => (
                      <div key={label} className="rounded-lg p-3 border border-white/8" style={{ background: 'rgba(255,255,255,0.02)' }}>
                        <p className="text-lg font-bold text-white">{val ?? '—'}</p>
                        <p className="text-[11px] text-white/30">{label}</p>
                      </div>
                    ))}
                  </div>
                  <p className="text-xs text-white/40 pt-1">
                    Pages are saved as <span className="text-amber-400">draft</span> — go to SEO Pages tab to publish them, then hit Regen Sitemap.
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
