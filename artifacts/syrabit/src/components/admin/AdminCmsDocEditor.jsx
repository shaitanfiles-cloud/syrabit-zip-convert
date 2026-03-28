import { useState, useEffect, useCallback, useRef } from 'react';
import MDEditor, { commands } from '@uiw/react-md-editor';
import {
  Plus, Save, Trash2, X, Loader2, FileText, Globe, Lock,
  Upload, Sparkles, RefreshCw, Eye, Edit2, BookOpen, ChevronRight,
  Tag, Link2, Search, FileUp, CheckCircle, AlertCircle, BarChart3,
} from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

function authHeaders(token) {
  const isRealJwt = token && token.split('.').length === 3;
  return { headers: isRealJwt ? { Authorization: `Bearer ${token}` } : {}, withCredentials: true };
}

function autoSlug(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
}

const STATUS_COLORS = {
  published: { bg: 'rgba(16,185,129,0.15)', border: 'rgba(16,185,129,0.35)', text: '#34d399', icon: Globe },
  draft:     { bg: 'rgba(100,116,139,0.15)', border: 'rgba(100,116,139,0.35)', text: '#94a3b8', icon: Lock },
};

const EMPTY_DOC = {
  title: '', content: '', meta_description: '', description: '',
  seo_tags: '', primary_keyword: '', seo_slug: '', category: '',
  geo_tags: '', schema_type: 'Article', status: 'draft',
  thumbnail_url: '', alt_text: '',
};

export default function AdminCmsDocEditor({ adminToken }) {
  const [docs, setDocs]             = useState([]);
  const [loading, setLoading]       = useState(true);
  const [editDoc, setEditDoc]       = useState(null);
  const [form, setForm]             = useState(EMPTY_DOC);
  const [saving, setSaving]         = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [aiParsing, setAiParsing]   = useState(false);
  const [searchQ, setSearchQ]       = useState('');
  const [seoTab, setSeoTab]         = useState('content');
  const pdfRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/content/cms-documents`, authHeaders(adminToken));
      setDocs(res.data || []);
    } catch { toast.error('Failed to load CMS documents'); }
    finally { setLoading(false); }
  }, [adminToken]);

  useEffect(() => { load(); }, [load]);

  const openNew = () => {
    setEditDoc(null);
    setForm({ ...EMPTY_DOC });
    setSeoTab('content');
  };

  const openEdit = (doc) => {
    setEditDoc(doc);
    setForm({
      title: doc.title || '',
      content: doc.content || '',
      meta_description: doc.meta_description || '',
      description: doc.description || '',
      seo_tags: doc.seo_tags || '',
      primary_keyword: doc.primary_keyword || '',
      seo_slug: doc.seo_slug || '',
      category: doc.category || '',
      geo_tags: doc.geo_tags || '',
      schema_type: doc.schema_type || 'Article',
      status: doc.status || 'draft',
      thumbnail_url: doc.thumbnail_url || '',
      alt_text: doc.alt_text || '',
    });
    setSeoTab('content');
  };

  const handleTitleChange = (title) => {
    setForm(f => ({
      ...f,
      title,
      seo_slug: f.seo_slug === autoSlug(f.title) || !f.seo_slug ? autoSlug(title) : f.seo_slug,
    }));
  };

  const aiParseCommand = {
    name: 'ai-parse',
    keyCommand: 'ai-parse',
    buttonProps: { 'aria-label': 'AI Structure Content', title: 'AI Structure Content' },
    icon: (
      <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 600, color: '#a78bfa', padding: '0 2px' }}>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2L13.09 8.26L19 7L14.74 11.74L20 14L13.74 14.91L14 21L9.26 16.74L7 21L7.91 14.74L2 14L7.26 11.26L3 7L8.91 8.09L12 2Z"/>
        </svg>
        AI
      </span>
    ),
    execute: async () => {
      if (!form.content.trim()) { toast.error('Add content first'); return; }
      setAiParsing(true);
      try {
        const res = await axios.post(`${API}/admin/studio/parse`, {
          raw_text: form.content,
          subject: form.geo_tags || '',
          chapter: form.title || '',
        }, authHeaders(adminToken));
        const blocks = res.data.blocks || [];
        if (!blocks.length) { toast.error('AI could not parse content'); return; }
        const formatted = blocks.map(b => `## ${b.title}\n\n${b.content}`).join('\n\n---\n\n');
        setForm(f => ({ ...f, content: formatted }));
        toast.success(`AI structured ${blocks.length} blocks`);
      } catch (e) {
        toast.error(e.response?.data?.detail || 'AI parsing failed');
      } finally { setAiParsing(false); }
    },
  };

  const handleSave = async () => {
    if (!form.title.trim()) { toast.error('Title is required'); return; }
    setSaving(true);
    try {
      const payload = { ...form, seo_slug: form.seo_slug || autoSlug(form.title) };
      if (editDoc) {
        await axios.patch(`${API}/admin/content/cms-documents/${editDoc.id}`, payload, authHeaders(adminToken));
        toast.success('Document updated');
      } else {
        const res = await axios.post(`${API}/admin/content/cms-documents`, payload, authHeaders(adminToken));
        setEditDoc(res.data);
        toast.success('Document created');
      }
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Save failed');
    } finally { setSaving(false); }
  };

  const handlePublishToggle = async () => {
    if (!editDoc) { toast.error('Save the document first'); return; }
    setPublishing(true);
    try {
      const res = await axios.post(`${API}/admin/content/cms-documents/${editDoc.id}/publish`, {}, authHeaders(adminToken));
      const newStatus = res.data.status;
      setForm(f => ({ ...f, status: newStatus }));
      setEditDoc(d => ({ ...d, status: newStatus }));
      toast.success(newStatus === 'published' ? 'Published! Sitemap will update.' : 'Moved to draft');
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to toggle publish');
    } finally { setPublishing(false); }
  };

  const handleDelete = async (id, e) => {
    e.stopPropagation();
    if (!window.confirm('Delete this document permanently?')) return;
    try {
      await axios.delete(`${API}/admin/content/cms-documents/${id}`, authHeaders(adminToken));
      if (editDoc?.id === id) { setEditDoc(null); setForm(EMPTY_DOC); }
      await load();
      toast.success('Document deleted');
    } catch { toast.error('Delete failed'); }
  };

  const handlePdfUpload = async () => {
    const file = pdfRef.current?.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) { toast.error('Only PDF files accepted'); return; }
    setPdfLoading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await axios.post(
        `${API}/admin/content/extract-pdf-text`,
        formData,
        { ...authHeaders(adminToken), headers: { ...authHeaders(adminToken).headers, 'Content-Type': 'multipart/form-data' } }
      );
      const extracted = res.data.text || '';
      if (!extracted) { toast.error('No text extracted from PDF'); return; }
      setForm(f => ({ ...f, content: f.content ? `${f.content}\n\n---\n\n${extracted}` : extracted }));
      toast.success(`Extracted ${res.data.chars?.toLocaleString() || '?'} chars from ${res.data.pages} pages`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'PDF extraction failed');
    } finally {
      setPdfLoading(false);
      if (pdfRef.current) pdfRef.current.value = '';
    }
  };

  const filtered = searchQ
    ? docs.filter(d => d.title?.toLowerCase().includes(searchQ.toLowerCase()) || d.seo_slug?.includes(searchQ))
    : docs;

  const isEditing = editDoc !== null || (form.title && !editDoc);
  const inEditor = isEditing || form.title || form.content;

  return (
    <div className="h-full flex overflow-hidden" style={{ background: '#0a0a14' }}>
      {/* Left — document list */}
      <div className="w-72 flex-shrink-0 border-r border-white/10 flex flex-col" style={{ background: 'rgba(255,255,255,0.012)' }}>
        <div className="px-4 py-3 border-b border-white/10 flex items-center gap-2">
          <div className="relative flex-1">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-white/30" />
            <input
              value={searchQ}
              onChange={e => setSearchQ(e.target.value)}
              placeholder="Search documents…"
              className="w-full h-8 pl-8 pr-3 rounded-lg text-xs text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
            />
          </div>
          <button
            onClick={openNew}
            className="h-8 px-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white flex items-center gap-1 text-xs font-medium flex-shrink-0"
            title="New document"
          >
            <Plus size={13} /> New
          </button>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {loading ? (
            <div className="space-y-1.5 p-3">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-14 rounded-xl animate-pulse" style={{ background: 'rgba(255,255,255,0.04)' }} />
              ))}
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-6 text-center">
              <FileText size={28} className="text-white/15 mx-auto mb-3" />
              <p className="text-xs text-white/30">{searchQ ? 'No results' : 'No documents yet'}</p>
              {!searchQ && <button onClick={openNew} className="mt-3 text-xs text-violet-400 hover:text-violet-300">Create first →</button>}
            </div>
          ) : (
            filtered.map(doc => {
              const st = STATUS_COLORS[doc.status] || STATUS_COLORS.draft;
              const StIcon = st.icon;
              const isActive = editDoc?.id === doc.id;
              return (
                <div
                  key={doc.id}
                  onClick={() => openEdit(doc)}
                  className={`mx-2 mb-1 p-3 rounded-xl cursor-pointer group transition-colors ${isActive ? 'bg-violet-500/15 border border-violet-500/30' : 'hover:bg-white/5 border border-transparent'}`}
                >
                  <div className="flex items-start gap-2">
                    <StIcon size={12} className="flex-shrink-0 mt-0.5" style={{ color: st.text }} />
                    <div className="min-w-0 flex-1">
                      <p className={`text-sm font-medium truncate leading-tight ${isActive ? 'text-violet-200' : 'text-white/80'}`}>
                        {doc.title || 'Untitled'}
                      </p>
                      <p className="text-[10px] text-white/30 truncate mt-0.5 font-mono">{doc.seo_slug || '—'}</p>
                      <div className="flex items-center gap-2 mt-1.5">
                        <span className="text-[10px]" style={{ color: st.text }}>{doc.status}</span>
                        {doc.word_count > 0 && <span className="text-[10px] text-white/20">{doc.word_count}w</span>}
                      </div>
                    </div>
                    <button
                      onClick={e => handleDelete(doc.id, e)}
                      className="opacity-0 group-hover:opacity-100 p-1 text-white/20 hover:text-red-400 rounded transition-all flex-shrink-0"
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
        <div className="px-4 py-2 border-t border-white/10">
          <p className="text-[10px] text-white/25 text-center">{docs.length} documents</p>
        </div>
      </div>

      {/* Right — editor */}
      {!inEditor ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <BookOpen size={36} className="text-white/15 mx-auto mb-4" />
            <p className="text-white/40 text-sm mb-1">Select a document or create a new one</p>
            <button onClick={openNew} className="mt-3 h-9 px-4 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium flex items-center gap-2 mx-auto">
              <Plus size={14} /> New Document
            </button>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Toolbar */}
          <div className="h-14 flex-shrink-0 border-b border-white/10 flex items-center px-5 gap-3" style={{ background: 'rgba(255,255,255,0.02)' }}>
            <div className="flex-1 min-w-0">
              <input
                value={form.title}
                onChange={e => handleTitleChange(e.target.value)}
                placeholder="Document title…"
                className="w-full text-lg font-bold text-white bg-transparent outline-none placeholder-white/25 truncate"
              />
            </div>

            {/* Status badge */}
            {editDoc && (
              <div
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border flex-shrink-0"
                style={{
                  background: STATUS_COLORS[form.status]?.bg,
                  borderColor: STATUS_COLORS[form.status]?.border,
                  color: STATUS_COLORS[form.status]?.text,
                }}
              >
                {form.status === 'published' ? <Globe size={11} /> : <Lock size={11} />}
                {form.status}
              </div>
            )}

            {/* PDF upload */}
            <input ref={pdfRef} type="file" accept=".pdf" className="hidden" onChange={handlePdfUpload} />
            <button
              onClick={() => pdfRef.current?.click()}
              disabled={pdfLoading}
              className="h-8 px-3 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-500/20 flex items-center gap-1.5 text-xs font-medium disabled:opacity-40 flex-shrink-0"
              title="Upload PDF and append text to editor"
            >
              {pdfLoading ? <Loader2 size={12} className="animate-spin" /> : <FileUp size={12} />}
              PDF
            </button>

            {/* Publish toggle */}
            <button
              onClick={handlePublishToggle}
              disabled={publishing || !editDoc}
              className={`h-8 px-3 rounded-lg flex items-center gap-1.5 text-xs font-medium disabled:opacity-40 flex-shrink-0 border transition-colors ${
                form.status === 'published'
                  ? 'bg-amber-600/20 hover:bg-amber-600/30 text-amber-400 border-amber-500/20'
                  : 'bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border-emerald-500/20'
              }`}
            >
              {publishing ? <Loader2 size={12} className="animate-spin" /> : <Globe size={12} />}
              {form.status === 'published' ? 'Unpublish' : 'Publish'}
            </button>

            {/* Save */}
            <button
              onClick={handleSave}
              disabled={saving || !form.title.trim()}
              className="h-8 px-4 rounded-lg bg-violet-600 hover:bg-violet-500 text-white flex items-center gap-1.5 text-xs font-semibold disabled:opacity-40 flex-shrink-0"
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>

          {/* Sub-tabs */}
          <div className="flex-shrink-0 border-b border-white/10 flex gap-0" style={{ background: 'rgba(255,255,255,0.015)' }}>
            {[
              { id: 'content', label: 'Content', icon: Edit2 },
              { id: 'seo', label: 'SEO & Meta', icon: Tag },
              { id: 'geo', label: 'GEO Tags', icon: Globe },
            ].map(t => (
              <button
                key={t.id}
                onClick={() => setSeoTab(t.id)}
                className={`flex items-center gap-1.5 px-5 py-3 text-xs font-medium border-b-2 transition-colors ${
                  seoTab === t.id
                    ? 'border-violet-500 text-violet-400'
                    : 'border-transparent text-white/40 hover:text-white/70'
                }`}
              >
                <t.icon size={12} />
                {t.label}
              </button>
            ))}
            <div className="ml-auto flex items-center px-4 gap-3">
              {form.content && (
                <span className="text-[10px] text-white/25">
                  {form.content.split(/\s+/).filter(Boolean).length}w · {form.content.length}ch
                </span>
              )}
            </div>
          </div>

          {/* Content tab — Gutenberg-style MD editor */}
          {seoTab === 'content' && (
            <div className="flex-1 overflow-hidden" data-color-mode="dark">
              <MDEditor
                value={form.content}
                onChange={val => setForm(f => ({ ...f, content: val || '' }))}
                height="100%"
                preview="live"
                visibleDragbar={false}
                extraCommands={[aiParseCommand, commands.divider, commands.fullscreen]}
                style={{ borderRadius: 0, border: 'none', height: '100%' }}
              />
            </div>
          )}

          {/* SEO & Meta tab */}
          {seoTab === 'seo' && (
            <div className="flex-1 overflow-y-auto p-6">
              <div className="max-w-2xl mx-auto space-y-5">
                <div>
                  <label className="text-xs text-white/50 block mb-1.5">URL Slug</label>
                  <div className="flex items-center gap-2 h-10 rounded-xl bg-white/5 border border-white/10 overflow-hidden px-3">
                    <Link2 size={13} className="text-white/30 flex-shrink-0" />
                    <span className="text-white/25 text-sm">/learn/</span>
                    <input
                      value={form.seo_slug}
                      onChange={e => setForm(f => ({ ...f, seo_slug: e.target.value }))}
                      placeholder="auto-from-title"
                      className="flex-1 h-full text-sm text-white bg-transparent outline-none font-mono"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs text-white/50 block mb-1.5">
                    Meta Description <span className="text-white/25">({form.meta_description?.length || 0}/160)</span>
                  </label>
                  <textarea
                    value={form.meta_description}
                    onChange={e => setForm(f => ({ ...f, meta_description: e.target.value.slice(0, 160) }))}
                    placeholder="160-character description for Google snippets…"
                    rows={3}
                    className="w-full px-4 py-2.5 rounded-xl text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500 resize-none"
                  />
                </div>

                <div>
                  <label className="text-xs text-white/50 block mb-1.5">Primary Keyword</label>
                  <input
                    value={form.primary_keyword}
                    onChange={e => setForm(f => ({ ...f, primary_keyword: e.target.value }))}
                    placeholder="e.g. AHSEC Class 12 Physics Notes"
                    className="w-full h-10 px-4 rounded-xl text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
                  />
                </div>

                <div>
                  <label className="text-xs text-white/50 block mb-1.5">SEO Tags <span className="text-white/25">(comma-separated)</span></label>
                  <input
                    value={form.seo_tags}
                    onChange={e => setForm(f => ({ ...f, seo_tags: e.target.value }))}
                    placeholder="ahsec, class 12, physics, optics, notes"
                    className="w-full h-10 px-4 rounded-xl text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
                  />
                </div>

                <div>
                  <label className="text-xs text-white/50 block mb-1.5">Category Path</label>
                  <input
                    value={form.category}
                    onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
                    placeholder="ahsec/class12/science/physics"
                    className="w-full h-10 px-4 rounded-xl text-sm text-white bg-white/5 border border-white/10 font-mono outline-none focus:border-violet-500"
                  />
                </div>

                <div>
                  <label className="text-xs text-white/50 block mb-1.5">Schema Type</label>
                  <div className="flex gap-2">
                    {['Article', 'FAQPage', 'HowTo', 'EducationalOccupationalProgram'].map(s => (
                      <button
                        key={s}
                        onClick={() => setForm(f => ({ ...f, schema_type: s }))}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                          form.schema_type === s
                            ? 'border-violet-500 bg-violet-500/20 text-violet-300'
                            : 'border-white/10 bg-white/5 text-white/40 hover:text-white/70'
                        }`}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="text-xs text-white/50 block mb-1.5">Long Description</label>
                  <textarea
                    value={form.description}
                    onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                    placeholder="Optional extended description for the document…"
                    rows={4}
                    className="w-full px-4 py-2.5 rounded-xl text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500 resize-none"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-white/50 block mb-1.5">Thumbnail URL</label>
                    <input
                      value={form.thumbnail_url}
                      onChange={e => setForm(f => ({ ...f, thumbnail_url: e.target.value }))}
                      placeholder="https://…"
                      className="w-full h-10 px-4 rounded-xl text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-white/50 block mb-1.5">Alt Text</label>
                    <input
                      value={form.alt_text}
                      onChange={e => setForm(f => ({ ...f, alt_text: e.target.value }))}
                      placeholder="Image alt text"
                      className="w-full h-10 px-4 rounded-xl text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* GEO Tags tab */}
          {seoTab === 'geo' && (
            <div className="flex-1 overflow-y-auto p-6">
              <div className="max-w-2xl mx-auto space-y-5">
                <div className="px-4 py-3 rounded-xl border border-violet-500/20 bg-violet-500/5">
                  <p className="text-xs text-violet-300 font-medium mb-1">GEO Targeting</p>
                  <p className="text-xs text-white/40">These tags help AI search engines (Perplexity, ChatGPT, Gemini) surface this page for Assam board students.</p>
                </div>

                <div>
                  <label className="text-xs text-white/50 block mb-1.5">GEO Context Tags <span className="text-white/25">(comma-separated)</span></label>
                  <input
                    value={form.geo_tags}
                    onChange={e => setForm(f => ({ ...f, geo_tags: e.target.value }))}
                    placeholder="AHSEC, Assam Board, Class 12, Science, Physics, Optics"
                    className="w-full h-10 px-4 rounded-xl text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
                  />
                </div>

                <div>
                  <label className="text-xs text-white/50 block mb-2">Quick presets</label>
                  <div className="flex flex-wrap gap-2">
                    {[
                      'AHSEC, Assam Board, Class 11, Science',
                      'AHSEC, Assam Board, Class 12, Science',
                      'AHSEC, Assam Board, Class 11, Arts',
                      'AHSEC, Assam Board, Class 12, Arts',
                      'Dibrugarh University, Degree, Science',
                      'Dibrugarh University, Degree, Arts',
                    ].map(preset => (
                      <button
                        key={preset}
                        onClick={() => setForm(f => ({ ...f, geo_tags: preset }))}
                        className="px-3 py-1.5 rounded-lg text-xs text-white/50 hover:text-white border border-white/10 hover:border-violet-500/40 transition-colors"
                      >
                        {preset}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="border-t border-white/10 pt-5">
                  <p className="text-xs text-white/40 mb-3">Content stats</p>
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { label: 'Words', value: form.content.split(/\s+/).filter(Boolean).length },
                      { label: 'Characters', value: form.content.length },
                      { label: 'Headings', value: (form.content.match(/^#{1,3}\s/gm) || []).length },
                    ].map(stat => (
                      <div key={stat.label} className="px-4 py-3 rounded-xl bg-white/[0.03] border border-white/10 text-center">
                        <p className="text-lg font-bold text-white">{stat.value.toLocaleString()}</p>
                        <p className="text-[10px] text-white/35 mt-0.5">{stat.label}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="border-t border-white/10 pt-5">
                  <p className="text-xs text-white/40 mb-3">Live page URL</p>
                  <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-white/[0.03] border border-white/10">
                    <Globe size={12} className="text-violet-400 flex-shrink-0" />
                    <span className="text-xs font-mono text-white/60">/learn/{form.seo_slug || autoSlug(form.title) || 'your-slug'}</span>
                    {form.status === 'published' && <CheckCircle size={12} className="text-emerald-400 ml-auto" />}
                    {form.status !== 'published' && <AlertCircle size={12} className="text-white/20 ml-auto" />}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
