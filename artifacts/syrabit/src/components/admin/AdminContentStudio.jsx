import { useState, useCallback, useEffect } from 'react';
import {
  Loader2, Sparkles, Eye, Code, Send, FileText,
  BookOpen, Layers, HelpCircle, Calculator, StickyNote,
  CheckCircle, AlertCircle, Copy, Check, RefreshCw,
  Globe, Zap, AlertTriangle,
} from 'lucide-react';
import axios from 'axios';
import { API_BASE } from '@/utils/api';
import { toast } from 'sonner';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

function authHeaders(token) {
  const isRealJwt = token && token.split('.').length === 3;
  return { headers: isRealJwt ? { Authorization: `Bearer ${token}` } : {}, withCredentials: true };
}

const BLOCK_ICONS = {
  summary:    { icon: FileText,    color: '#8b5cf6', bg: 'rgba(139,92,246,0.12)' },
  definition: { icon: BookOpen,    color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
  example:    { icon: Layers,      color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
  pyq:        { icon: HelpCircle,  color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  formula:    { icon: Calculator,  color: '#ec4899', bg: 'rgba(236,72,153,0.12)' },
  note:       { icon: StickyNote,  color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
};

function BlockCard({ block, index, onEdit, onRemove }) {
  const cfg = BLOCK_ICONS[block.type] || BLOCK_ICONS.note;
  const Icon = cfg.icon;
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState(block.content);

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 group">
      <div className="flex items-center gap-2 mb-3">
        <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: cfg.bg }}>
          <Icon size={14} style={{ color: cfg.color }} />
        </div>
        <span className="text-xs font-bold uppercase tracking-wider" style={{ color: cfg.color }}>{block.type}</span>
        <span className="text-slate-400 text-sm font-medium ml-2">{block.title}</span>
        <div className="ml-auto flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button onClick={() => { setEditing(!editing); setEditContent(block.content); }}
            className="px-2 py-1 text-xs text-slate-400 hover:text-white bg-slate-700 rounded-lg">
            {editing ? 'Cancel' : 'Edit'}
          </button>
          <button onClick={() => onRemove(index)}
            className="px-2 py-1 text-xs text-red-400 hover:text-red-300 bg-slate-700 rounded-lg">
            Remove
          </button>
        </div>
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea value={editContent} onChange={(e) => setEditContent(e.target.value)} rows={4}
            className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white resize-y" />
          <button onClick={() => { onEdit(index, editContent); setEditing(false); }}
            className="px-3 py-1.5 text-xs bg-violet-600 text-white rounded-lg hover:bg-violet-500">Save</button>
        </div>
      ) : (
        <p className="text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">{block.content}</p>
      )}
    </div>
  );
}

function PreviewPane({ blocks, title }) {
  return (
    <div className="bg-white/[0.02] border border-slate-700/50 rounded-xl p-6 overflow-y-auto max-h-[600px]">
      <h2 className="text-white text-xl font-bold mb-6">{title || 'Preview'}</h2>
      {blocks.map((block, i) => {
        const cfg = BLOCK_ICONS[block.type] || BLOCK_ICONS.note;
        return (
          <div key={i} className="mb-6 pb-4 border-b border-slate-800 last:border-0">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-bold uppercase" style={{ color: cfg.color }}>{block.type}</span>
              <span className="text-slate-200 font-semibold">{block.title}</span>
            </div>
            <p className="text-slate-400 text-sm leading-relaxed whitespace-pre-wrap">{block.content}</p>
          </div>
        );
      })}
      {blocks.length === 0 && <p className="text-slate-600 text-center py-12">Paste text and click Parse to see preview</p>}
    </div>
  );
}

export default function AdminContentStudio({ adminToken }) {
  const [rawText, setRawText]       = useState('');
  const [subject, setSubject]       = useState('');
  const [subjectId, setSubjectId]   = useState('');
  const [chapter, setChapter]       = useState('');
  const [blocks, setBlocks]         = useState([]);
  const [parsing, setParsing]       = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [published, setPublished]   = useState(null);
  const [view, setView]             = useState('editor');
  const [title, setTitle]           = useState('');
  const [slug, setSlug]             = useState('');
  const [merging, setMerging]       = useState(false);

  const [allSubjects, setAllSubjects] = useState([]);
  const [gapSubjects, setGapSubjects] = useState([]);
  const [loadingGaps, setLoadingGaps] = useState(false);
  const [gapGenSubject, setGapGenSubject] = useState(null);
  const [gapGenStatus, setGapGenStatus]   = useState({});

  const headers = { withCredentials: true };

  const loadGapSubjects = useCallback(async () => {
    setLoadingGaps(true);
    try {
      const res = await axios.get(`${API}/content/subjects`);
      const subjects = res.data || [];
      setAllSubjects(subjects);
      setGapSubjects(subjects.filter(s => (s.chapter_count || 0) < 3));
    } catch {
      toast.error('Could not load subjects');
    } finally {
      setLoadingGaps(false);
    }
  }, []);

  useEffect(() => {
    if (view === 'gaps') loadGapSubjects();
  }, [view, loadGapSubjects]);

  const handleParse = useCallback(async () => {
    if (!rawText.trim()) return;
    setParsing(true);
    setPublished(null);
    try {
      const res = await axios.post(`${API_BASE}/admin/studio/parse`, {
        raw_text: rawText, subject, chapter,
      }, headers);
      const parsed = res.data.blocks || [];
      setBlocks(parsed);
      if (!title && parsed.length > 0) setTitle(parsed[0].title || subject || 'Untitled');
      if (!slug && (subject || chapter))
        setSlug((subject + '-' + chapter).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+/g, '-'));
    } catch (err) {
      toast.error('AI parse failed');
    } finally {
      setParsing(false);
    }
  }, [rawText, subject, chapter, title, slug]);

  const handlePublish = useCallback(async () => {
    if (!blocks.length || !slug.trim()) return;
    setPublishing(true);
    try {
      const res = await axios.post(`${API_BASE}/admin/studio/publish`, {
        title: title || 'Untitled',
        slug: slug.trim(),
        blocks,
        subject_slug: subject.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
      }, headers);
      setPublished(res.data);
      toast.success('Published to SEO pages!');
    } catch (err) {
      toast.error('Publish failed');
    } finally {
      setPublishing(false);
    }
  }, [blocks, title, slug, subject]);

  const handleMergeToBlog = useCallback(async () => {
    if (!subjectId) { toast.error('Select a subject with a known ID first (use Gap Fill mode)'); return; }
    setMerging(true);
    try {
      await axios.post(`${API}/admin/cms/merge/${subjectId}`, {}, authHeaders(adminToken));
      toast.success(`Blog merged for ${subject || subjectId} — go to CMS Editor to review`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Merge failed');
    } finally {
      setMerging(false);
    }
  }, [adminToken, subjectId, subject]);

  const handleEditBlock  = (index, newContent) => setBlocks(prev => prev.map((b, i) => i === index ? { ...b, content: newContent } : b));
  const handleRemoveBlock = (index) => setBlocks(prev => prev.filter((_, i) => i !== index));

  const handleGapFill = (s) => {
    setSubject(s.name);
    setSubjectId(s.id);
    setView('editor');
    setRawText('');
    setBlocks([]);
    setTitle(s.name);
    setSlug(s.name.toLowerCase().replace(/[^a-z0-9]+/g, '-'));
    toast.success(`Loaded "${s.name}" — paste notes then click Parse with AI`);
  };

  const handleAutoGenerate = useCallback(async (s) => {
    setGapGenSubject(s.id);
    setGapGenStatus(prev => ({ ...prev, [s.id]: 'generating' }));
    try {
      const prompt = `Generate comprehensive educational notes for: ${s.name}. Include key concepts, definitions, examples, and PYQ-style questions for AHSEC students.`;
      const res = await axios.post(`${API_BASE}/admin/studio/parse`, {
        raw_text: prompt,
        subject: s.name,
        chapter: 'Overview',
      }, headers);
      const parsed = res.data.blocks || [];
      if (!parsed.length) { setGapGenStatus(prev => ({ ...prev, [s.id]: 'failed' })); return; }
      const markdown = parsed.map(b => `## ${b.title}\n\n${b.content}`).join('\n\n---\n\n');
      await axios.post(
        `${API}/admin/content/chapters`,
        {
          subject_id:   s.id,
          title:        `${s.name} — Overview`,
          slug:         s.name.toLowerCase().replace(/[^a-z0-9]+/g, '-') + '-overview',
          content:      markdown,
          content_type: 'notes',
          order:        1,
        },
        authHeaders(adminToken)
      );
      setGapGenStatus(prev => ({ ...prev, [s.id]: 'done' }));
      toast.success(`Auto-generated chapter for "${s.name}"`);
      loadGapSubjects();
    } catch {
      setGapGenStatus(prev => ({ ...prev, [s.id]: 'failed' }));
      toast.error(`Auto-generate failed for "${s.name}"`);
    } finally {
      setGapGenSubject(null);
    }
  }, [adminToken, loadGapSubjects]);

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-white font-bold text-lg flex items-center gap-2">
            <Sparkles size={18} className="text-violet-400" />
            AI Content Studio
          </h2>
          <p className="text-slate-500 text-sm mt-1">Paste raw notes → AI categorizes → Edit → Publish to SEO pages</p>
        </div>
        <div className="flex gap-1 bg-slate-800/50 rounded-xl p-1">
          {[
            { id: 'editor',  label: 'Editor',   icon: Code },
            { id: 'preview', label: 'Preview',  icon: Eye },
            { id: 'gaps',    label: 'Gap Fill',  icon: AlertTriangle },
          ].map(t => (
            <button key={t.id} onClick={() => setView(t.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                view === t.id ? 'bg-violet-600 text-white' : 'text-slate-400 hover:text-white'
              }`}
            >
              <t.icon size={12} />
              {t.label}
              {t.id === 'gaps' && gapSubjects.length > 0 && (
                <span className="ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-400">{gapSubjects.length}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── Gap Fill Mode ────────────────────────────────── */}
      {view === 'gaps' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-white font-semibold">Subjects with &lt; 3 Chapters</h3>
              <p className="text-slate-500 text-xs mt-0.5">Auto-generate a starter chapter or load into the editor to add notes manually.</p>
            </div>
            <button onClick={loadGapSubjects} disabled={loadingGaps}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-slate-400 hover:text-white bg-slate-800 rounded-lg disabled:opacity-50">
              {loadingGaps ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              Refresh
            </button>
          </div>

          {loadingGaps ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {[...Array(6)].map((_, i) => (
                <div key={i} className="h-24 rounded-xl animate-pulse bg-slate-800/60" />
              ))}
            </div>
          ) : gapSubjects.length === 0 ? (
            <div className="text-center py-16">
              <CheckCircle size={36} className="text-emerald-400 mx-auto mb-3" />
              <p className="text-slate-300 font-semibold">All subjects have 3+ chapters!</p>
              <p className="text-slate-500 text-sm mt-1">No gaps detected in the curriculum.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {gapSubjects.map(s => {
                const status = gapGenStatus[s.id];
                const isGenerating = gapGenSubject === s.id;
                return (
                  <div key={s.id} className="p-4 rounded-xl border bg-slate-900/60" style={{ borderColor: status === 'done' ? 'rgba(16,185,129,0.30)' : 'rgba(255,255,255,0.07)' }}>
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <p className="text-sm font-medium text-white">{s.icon || '📚'} {s.name}</p>
                      {status === 'done' && <CheckCircle size={14} className="text-emerald-400 flex-shrink-0 mt-0.5" />}
                      {status === 'failed' && <AlertCircle size={14} className="text-red-400 flex-shrink-0 mt-0.5" />}
                    </div>
                    <p className="text-xs text-amber-400 mb-3">{s.chapter_count || 0} / 3 chapters</p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleGapFill(s)}
                        className="flex-1 py-1.5 rounded-lg text-xs font-medium text-slate-300 bg-slate-700 hover:bg-slate-600 transition-colors"
                      >
                        Load in Editor
                      </button>
                      <button
                        onClick={() => handleAutoGenerate(s)}
                        disabled={isGenerating || status === 'done'}
                        className="flex-1 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40 transition-colors flex items-center justify-center gap-1"
                        style={{ background: 'rgba(139,92,246,0.20)', color: '#a78bfa' }}
                      >
                        {isGenerating ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
                        {status === 'done' ? 'Generated!' : isGenerating ? 'Generating…' : 'Auto-Generate'}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Editor + Preview tabs ─────────────────────────── */}
      {view !== 'gaps' && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <input value={subject} onChange={(e) => setSubject(e.target.value)}
              placeholder="Subject (e.g. Physics)"
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600" />
            <input value={chapter} onChange={(e) => setChapter(e.target.value)}
              placeholder="Chapter (e.g. Optics)"
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600" />
            <button onClick={handleParse} disabled={parsing || !rawText.trim()}
              className="flex items-center justify-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors">
              {parsing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              {parsing ? 'AI Parsing...' : 'Parse with AI'}
            </button>
          </div>

          {subjectId && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs" style={{ background: 'rgba(139,92,246,0.10)', border: '1px solid rgba(139,92,246,0.20)' }}>
              <CheckCircle size={12} className="text-violet-400" />
              <span className="text-violet-300">Subject linked: <span className="font-mono text-violet-200">{subjectId}</span> — {subject}</span>
              <button onClick={() => { setSubjectId(''); }} className="ml-auto text-white/30 hover:text-white text-[10px]">Unlink</button>
            </div>
          )}

          {view === 'editor' ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <div className="space-y-4">
                <div>
                  <label className="text-slate-500 text-xs mb-1 block">Raw Text Input</label>
                  <textarea value={rawText} onChange={(e) => setRawText(e.target.value)}
                    placeholder="Paste your raw educational notes, textbook content, or study material here..."
                    rows={16}
                    className="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white placeholder-slate-600 resize-y font-mono" />
                  <p className="text-xs text-slate-600 mt-1">{rawText.length} characters</p>
                </div>
              </div>
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <label className="text-slate-500 text-xs">Structured Blocks {blocks.length > 0 && `(${blocks.length})`}</label>
                  {blocks.length > 0 && (
                    <button onClick={() => setBlocks([])} className="text-xs text-slate-500 hover:text-slate-300">Clear all</button>
                  )}
                </div>
                <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
                  {blocks.map((block, i) => (
                    <BlockCard key={i} block={block} index={i} onEdit={handleEditBlock} onRemove={handleRemoveBlock} />
                  ))}
                  {blocks.length === 0 && (
                    <div className="bg-slate-800/30 border border-dashed border-slate-700 rounded-xl p-8 text-center">
                      <Sparkles size={24} className="text-slate-700 mx-auto mb-3" />
                      <p className="text-slate-600 text-sm">AI-parsed blocks will appear here</p>
                      <p className="text-slate-700 text-xs mt-1">Paste text and click "Parse with AI"</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <PreviewPane blocks={blocks} title={title} />
          )}

          {blocks.length > 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <h3 className="text-slate-300 text-sm font-semibold mb-4">Publish Pipeline</h3>
              <div className="grid grid-cols-2 gap-3 mb-4">
                <div>
                  <label className="text-slate-500 text-xs mb-1 block">Page Title</label>
                  <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Page title"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white" />
                </div>
                <div>
                  <label className="text-slate-500 text-xs mb-1 block">URL Slug</label>
                  <input value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="url-slug"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white font-mono" />
                </div>
              </div>
              <div className="flex items-center gap-3 flex-wrap">
                <button onClick={handlePublish} disabled={publishing || !slug.trim()}
                  className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg px-5 py-2.5 text-sm font-medium transition-colors">
                  {publishing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  {publishing ? 'Publishing...' : 'Publish Page'}
                </button>
                {subjectId && (
                  <button onClick={handleMergeToBlog} disabled={merging}
                    className="flex items-center gap-2 disabled:opacity-50 text-white rounded-lg px-5 py-2.5 text-sm font-medium transition-colors"
                    style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)' }}>
                    {merging ? <Loader2 size={14} className="animate-spin" /> : <Globe size={14} />}
                    {merging ? 'Merging…' : 'Merge to Blog'}
                  </button>
                )}
                {published && (
                  <div className="flex items-center gap-2 text-emerald-400 text-sm">
                    <CheckCircle size={14} />
                    Published! URL: <code className="text-xs bg-slate-800 px-2 py-0.5 rounded">{published.url}</code>
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
