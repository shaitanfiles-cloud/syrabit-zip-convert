import { useState, useEffect, useCallback, useRef } from 'react';
import {
  MDXEditor,
  headingsPlugin,
  listsPlugin,
  quotePlugin,
  thematicBreakPlugin,
  markdownShortcutPlugin,
  codeBlockPlugin,
  codeMirrorPlugin,
  tablePlugin,
  linkPlugin,
  diffSourcePlugin,
  toolbarPlugin,
  UndoRedo, BoldItalicUnderlineToggles, BlockTypeSelect,
  CreateLink, CodeToggle, InsertTable, InsertThematicBreak,
  ListsToggle, Separator, DiffSourceToggleWrapper, InsertCodeBlock,
  CodeMirrorEditor,
} from '@mdxeditor/editor';
import '@mdxeditor/editor/style.css';
import {
  Plus, Save, Trash2, Loader2, FileText, Globe, Lock,
  Upload, Sparkles, Eye, Edit2, BookOpen,
  Tag, Link2, Search, FileUp, CheckCircle, AlertCircle, BarChart3,
  RefreshCw, Merge,
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

function MdxToolbar({ onAiParse, aiParsing }) {
  return (
    <DiffSourceToggleWrapper>
      <UndoRedo />
      <Separator />
      <BoldItalicUnderlineToggles />
      <CodeToggle />
      <Separator />
      <ListsToggle />
      <Separator />
      <BlockTypeSelect />
      <Separator />
      <CreateLink />
      <InsertTable />
      <InsertThematicBreak />
      <InsertCodeBlock />
      <Separator />
      <button
        type="button"
        onClick={onAiParse}
        disabled={aiParsing}
        title="AI Structure Content"
        style={{
          display: 'flex', alignItems: 'center', gap: 4, padding: '2px 6px',
          borderRadius: 4, fontSize: 11, fontWeight: 600, color: '#a78bfa',
          background: 'rgba(167,139,250,0.10)', border: '1px solid rgba(167,139,250,0.20)',
          cursor: aiParsing ? 'not-allowed' : 'pointer', opacity: aiParsing ? 0.5 : 1,
        }}
      >
        {aiParsing ? (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" style={{ animation: 'spin 1s linear infinite' }}>
            <path d="M12 22C17.5228 22 22 17.5228 22 12H20C20 16.4183 16.4183 20 12 20V22Z"/>
          </svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2L13.09 8.26L19 7L14.74 11.74L20 14L13.74 14.91L14 21L9.26 16.74L7 21L7.91 14.74L2 14L7.26 11.26L3 7L8.91 8.09L12 2Z"/>
          </svg>
        )}
        AI
      </button>
    </DiffSourceToggleWrapper>
  );
}

export default function AdminCmsDocEditor({ adminToken }) {
  const [docs, setDocs]             = useState([]);
  const [loading, setLoading]       = useState(true);
  const [editDoc, setEditDoc]       = useState(null);
  const [form, setForm]             = useState(EMPTY_DOC);
  const [saving, setSaving]         = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [aiParsing, setAiParsing]   = useState(false);
  const [merging, setMerging]       = useState(false);
  const [searchQ, setSearchQ]       = useState('');
  const [seoTab, setSeoTab]         = useState('content');
  const pdfRef  = useRef(null);
  const editorRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await axios.get(`${API}/admin/content/cms-documents`, authHeaders(adminToken));
      setDocs(res.data || []);
    } catch { toast.error('Failed to load CMS documents'); }
    finally { setLoading(false); }
  }, [adminToken]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem('syrabit_cms_prefill');
      if (!raw) return;
      const prefill = JSON.parse(raw);
      if (Date.now() - (prefill.timestamp || 0) > 10 * 60 * 1000) {
        localStorage.removeItem('syrabit_cms_prefill');
        return;
      }
      localStorage.removeItem('syrabit_cms_prefill');
      setEditDoc(null);
      setForm(f => ({
        ...f,
        title:            prefill.title     || f.title,
        content:          prefill.content   || f.content,
        seo_slug:         prefill.seo_slug  || f.seo_slug,
        meta_description: prefill.meta_description || f.meta_description,
        status:           'draft',
      }));
      setSeoTab('content');
      toast.success(`Pre-filled with merged content for "${prefill.title}" — review and save`);
    } catch {}
  }, []);

  const openNew = () => {
    setEditDoc(null);
    setForm({ ...EMPTY_DOC });
    setSeoTab('content');
  };

  const openEdit = (doc) => {
    setEditDoc(doc);
    setForm({
      title:            doc.title || '',
      content:          doc.content || '',
      meta_description: doc.meta_description || '',
      description:      doc.description || '',
      seo_tags:         doc.seo_tags || '',
      primary_keyword:  doc.primary_keyword || '',
      seo_slug:         doc.seo_slug || '',
      category:         doc.category || '',
      geo_tags:         doc.geo_tags || '',
      schema_type:      doc.schema_type || 'Article',
      status:           doc.status || 'draft',
      thumbnail_url:    doc.thumbnail_url || '',
      alt_text:         doc.alt_text || '',
    });
    setSeoTab('content');
  };

  const handleTitleChange = (title) => {
    setForm(f => ({
      ...f, title,
      seo_slug: f.seo_slug === autoSlug(f.title) || !f.seo_slug ? autoSlug(title) : f.seo_slug,
    }));
  };

  const handleAiParse = async () => {
    const content = editorRef.current?.getMarkdown() || form.content;
    if (!content.trim()) { toast.error('Add content first'); return; }
    setAiParsing(true);
    try {
      const res = await axios.post(`${API}/admin/studio/parse`, {
        raw_text: content,
        subject:  form.geo_tags || '',
        chapter:  form.title || '',
      }, authHeaders(adminToken));
      const blocks = res.data.blocks || [];
      if (!blocks.length) { toast.error('AI could not parse content'); return; }
      const formatted = blocks.map(b => `## ${b.title}\n\n${b.content}`).join('\n\n---\n\n');
      setForm(f => ({ ...f, content: formatted }));
      toast.success(`AI structured ${blocks.length} blocks`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'AI parsing failed');
    } finally { setAiParsing(false); }
  };

  const handleSave = async () => {
    if (!form.title.trim()) { toast.error('Title is required'); return; }
    const liveContent = editorRef.current?.getMarkdown() ?? form.content;
    setSaving(true);
    try {
      const payload = { ...form, content: liveContent, seo_slug: form.seo_slug || autoSlug(form.title) };
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
      toast.success(newStatus === 'published' ? 'Published!' : 'Moved to draft');
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
      const current = editorRef.current?.getMarkdown() || form.content;
      setForm(f => ({ ...f, content: current ? `${current}\n\n---\n\n${extracted}` : extracted }));
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

  const inEditor = editDoc !== null || form.title || form.content;

  return (
    <div className="h-full flex overflow-hidden" style={{ background: '#121212' }}>
      {/* Left — document list */}
      <div className="w-72 flex-shrink-0 border-r flex flex-col" style={{ background: '#191919', borderColor: 'rgba(255,255,255,0.07)' }}>
        <div className="px-4 py-3 border-b flex items-center gap-2" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <div className="relative flex-1">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: 'rgba(255,255,255,0.25)' }} />
            <input
              value={searchQ}
              onChange={e => setSearchQ(e.target.value)}
              placeholder="Search documents…"
              className="w-full h-8 pl-8 pr-3 rounded-lg text-xs outline-none focus:border-violet-500"
              style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
            />
          </div>
          <button
            onClick={openNew}
            className="h-8 px-2 rounded-lg flex items-center gap-1 text-xs font-medium flex-shrink-0"
            style={{ background: '#9575e0', color: 'white' }}
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
              <FileText size={28} className="mx-auto mb-3" style={{ color: 'rgba(255,255,255,0.10)' }} />
              <p className="text-xs" style={{ color: 'rgba(255,255,255,0.25)' }}>{searchQ ? 'No results' : 'No documents yet'}</p>
              {!searchQ && <button onClick={openNew} className="mt-3 text-xs" style={{ color: '#9575e0' }}>Create first →</button>}
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
                  className="mx-2 mb-1 p-3 rounded-xl cursor-pointer group transition-colors"
                  style={{
                    border: isActive ? '1px solid rgba(149,117,224,0.30)' : '1px solid transparent',
                    background: isActive ? 'rgba(149,117,224,0.10)' : 'transparent',
                  }}
                >
                  <div className="flex items-start gap-2">
                    <StIcon size={12} className="flex-shrink-0 mt-0.5" style={{ color: st.text }} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate leading-tight" style={{ color: isActive ? '#c4b0f0' : 'rgba(232,232,232,0.75)' }}>
                        {doc.title || 'Untitled'}
                      </p>
                      <p className="text-[10px] truncate mt-0.5 font-mono" style={{ color: 'rgba(255,255,255,0.25)' }}>{doc.seo_slug || '—'}</p>
                      <div className="flex items-center gap-2 mt-1.5">
                        <span className="text-[10px]" style={{ color: st.text }}>{doc.status}</span>
                        {doc.word_count > 0 && <span className="text-[10px]" style={{ color: 'rgba(255,255,255,0.18)' }}>{doc.word_count}w</span>}
                      </div>
                    </div>
                    <button
                      onClick={e => handleDelete(doc.id, e)}
                      className="opacity-0 group-hover:opacity-100 p-1 rounded transition-all flex-shrink-0"
                      style={{ color: 'rgba(255,255,255,0.18)' }}
                      onMouseEnter={e => e.currentTarget.style.color = '#f87171'}
                      onMouseLeave={e => e.currentTarget.style.color = 'rgba(255,255,255,0.18)'}
                    >
                      <Trash2 size={11} />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
        <div className="px-4 py-2 border-t" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <p className="text-[10px] text-center" style={{ color: 'rgba(255,255,255,0.20)' }}>{docs.length} documents</p>
        </div>
      </div>

      {/* Right — editor */}
      {!inEditor ? (
        <div className="flex-1 flex items-center justify-center" style={{ color: 'rgba(232,232,232,0.40)' }}>
          <div className="text-center">
            <BookOpen size={36} className="mx-auto mb-4" style={{ color: 'rgba(255,255,255,0.10)' }} />
            <p className="text-sm mb-1">Select a document or create a new one</p>
            <button onClick={openNew} className="mt-3 h-9 px-4 rounded-xl text-sm font-medium flex items-center gap-2 mx-auto" style={{ background: '#9575e0', color: 'white' }}>
              <Plus size={14} /> New Document
            </button>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Toolbar */}
          <div className="h-14 flex-shrink-0 border-b flex items-center px-5 gap-3" style={{ background: '#191919', borderColor: 'rgba(255,255,255,0.07)' }}>
            <div className="flex-1 min-w-0">
              <input
                value={form.title}
                onChange={e => handleTitleChange(e.target.value)}
                placeholder="Document title…"
                className="w-full text-lg font-bold bg-transparent outline-none truncate"
                style={{ color: '#E8E8E8' }}
              />
            </div>

            {editDoc && (
              <div
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border flex-shrink-0"
                style={{
                  background:  STATUS_COLORS[form.status]?.bg,
                  borderColor: STATUS_COLORS[form.status]?.border,
                  color:       STATUS_COLORS[form.status]?.text,
                }}
              >
                {form.status === 'published' ? <Globe size={11} /> : <Lock size={11} />}
                {form.status}
              </div>
            )}

            <input ref={pdfRef} type="file" accept=".pdf" className="hidden" onChange={handlePdfUpload} />
            <button
              onClick={() => pdfRef.current?.click()}
              disabled={pdfLoading}
              className="h-8 px-3 rounded-lg flex items-center gap-1.5 text-xs font-medium disabled:opacity-40 flex-shrink-0 border"
              style={{ background: 'rgba(59,130,246,0.15)', color: '#60a5fa', borderColor: 'rgba(59,130,246,0.20)' }}
            >
              {pdfLoading ? <Loader2 size={12} className="animate-spin" /> : <FileUp size={12} />}
              PDF
            </button>

            <button
              onClick={handlePublishToggle}
              disabled={publishing || !editDoc}
              className="h-8 px-3 rounded-lg flex items-center gap-1.5 text-xs font-medium disabled:opacity-40 flex-shrink-0 border"
              style={
                form.status === 'published'
                  ? { background: 'rgba(245,158,11,0.15)', color: '#fbbf24', borderColor: 'rgba(245,158,11,0.20)' }
                  : { background: 'rgba(16,185,129,0.15)', color: '#34d399', borderColor: 'rgba(16,185,129,0.20)' }
              }
            >
              {publishing ? <Loader2 size={12} className="animate-spin" /> : <Globe size={12} />}
              {form.status === 'published' ? 'Unpublish' : 'Publish'}
            </button>

            <button
              onClick={handleSave}
              disabled={saving || !form.title.trim()}
              className="h-8 px-4 rounded-lg flex items-center gap-1.5 text-xs font-semibold disabled:opacity-40 flex-shrink-0"
              style={{ background: '#9575e0', color: 'white' }}
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>

          {/* Sub-tabs */}
          <div className="flex-shrink-0 border-b flex gap-0" style={{ background: 'rgba(255,255,255,0.012)', borderColor: 'rgba(255,255,255,0.07)' }}>
            {[
              { id: 'content', label: 'Content', icon: Edit2 },
              { id: 'seo',     label: 'SEO & Meta', icon: Tag },
              { id: 'geo',     label: 'GEO Tags',   icon: Globe },
            ].map(t => (
              <button
                key={t.id}
                onClick={() => setSeoTab(t.id)}
                className="flex items-center gap-1.5 px-5 py-3 text-xs font-medium border-b-2 transition-colors"
                style={{
                  borderBottomColor: seoTab === t.id ? '#9575e0' : 'transparent',
                  color: seoTab === t.id ? '#c4b0f0' : 'rgba(255,255,255,0.35)',
                }}
              >
                <t.icon size={12} />
                {t.label}
              </button>
            ))}
            <div className="ml-auto flex items-center px-4 gap-3">
              {form.content && (
                <span className="text-[10px]" style={{ color: 'rgba(255,255,255,0.20)' }}>
                  {form.content.split(/\s+/).filter(Boolean).length}w · {form.content.length}ch
                </span>
              )}
            </div>
          </div>

          {/* Content tab — Template bar + MDXEditor */}
          {seoTab === 'content' && (
            <div className="flex-1 flex flex-col overflow-hidden">
            {/* Template Library bar */}
            <div className="flex items-center gap-1.5 px-4 py-2 border-b flex-shrink-0 flex-wrap" style={{ borderColor: 'rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.015)' }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.25)" strokeWidth="2" className="flex-shrink-0"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
              <span className="text-[10px] flex-shrink-0 mr-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>Insert:</span>
              {[
                { label: 'PYQ Block',   shortcode: '\n\n> **[PYQ year=2025]** _Question text here._ *(3 marks)*\n\n' },
                { label: 'Formula Box', shortcode: '\n\n> **[FORMULA]** Name: `expression = result`\n\n' },
                { label: 'AHSEC Tip',  shortcode: '\n\n> **[BOARD-TIP]** This topic is important for board exams.\n\n' },
                { label: 'Note Block',  shortcode: '\n\n> **[NOTE]** Key insight or definition here.\n\n' },
                { label: 'H2 Section',  shortcode: '\n\n## Section Title\n\n_Content here._\n\n---\n\n' },
              ].map(t => (
                <button
                  key={t.label}
                  onClick={() => {
                    const current = editorRef.current?.getMarkdown() || form.content;
                    setForm(f => ({ ...f, content: current + t.shortcode }));
                  }}
                  className="px-2 py-0.5 rounded text-[10px] border transition-colors"
                  style={{ borderColor: 'rgba(255,255,255,0.10)', background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.40)' }}
                  onMouseEnter={e => { e.currentTarget.style.color = '#c4b0f0'; e.currentTarget.style.borderColor = 'rgba(149,117,224,0.40)'; }}
                  onMouseLeave={e => { e.currentTarget.style.color = 'rgba(255,255,255,0.40)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.10)'; }}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div
              className="flex-1 overflow-hidden cms-light-editor-wrapper"
              data-color-mode="light"
              style={{ backgroundColor: '#ffffff', color: '#1a1a1a' }}
            >
              <MDXEditor
                ref={editorRef}
                key={editDoc?.id ?? '__new__'}
                markdown={form.content || ''}
                onChange={md => setForm(f => ({ ...f, content: md }))}
                plugins={[
                  headingsPlugin(),
                  listsPlugin(),
                  quotePlugin(),
                  thematicBreakPlugin(),
                  markdownShortcutPlugin(),
                  codeBlockPlugin({ defaultCodeBlockLanguage: 'text' }),
                  codeMirrorPlugin({ codeBlockLanguages: { js: 'JavaScript', ts: 'TypeScript', python: 'Python', text: 'Text', md: 'Markdown', html: 'HTML', css: 'CSS' } }),
                  tablePlugin(),
                  linkPlugin(),
                  diffSourcePlugin({ viewMode: 'rich-text', diffMarkdown: form.content || '' }),
                  toolbarPlugin({
                    toolbarContents: () => <MdxToolbar onAiParse={handleAiParse} aiParsing={aiParsing} />,
                  }),
                ]}
                className="mdx-editor-light h-full"
                contentEditableClassName="cms-editor-content"
              />
            </div>
            </div>
          )}

          {/* SEO & Meta tab */}
          {seoTab === 'seo' && (
            <div className="flex-1 overflow-y-auto p-6">
              <div className="max-w-2xl mx-auto space-y-5">

                {/* ── Google Snippet Preview ─────────────────────── */}
                <div>
                  <p className="text-xs font-medium mb-2" style={{ color: 'rgba(255,255,255,0.40)' }}>Google Search Preview</p>
                  <div className="rounded-xl p-4" style={{ background: '#ffffff' }}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <div className="w-5 h-5 rounded-full flex-shrink-0" style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)' }} />
                      <div className="min-w-0">
                        <p className="text-xs font-medium truncate" style={{ color: '#202124' }}>syrabit.ai</p>
                        <p className="text-[10px] truncate" style={{ color: '#4d5156' }}>
                          https://syrabit.ai/{form.seo_slug || 'your-slug-here'}
                        </p>
                      </div>
                    </div>
                    <p className="text-base leading-tight mb-1" style={{ color: '#1a0dab', fontFamily: 'arial,sans-serif' }}>
                      {form.title ? `${form.title} | Syrabit.ai` : 'Your Page Title — Syrabit.ai'}
                    </p>
                    <p className="text-sm leading-snug" style={{ color: '#4d5156', fontFamily: 'arial,sans-serif' }}>
                      {form.meta_description
                        ? (form.meta_description.length > 160 ? form.meta_description.slice(0, 157) + '…' : form.meta_description)
                        : 'Your meta description will appear here. Write 120–160 characters to maximise click-through.'}
                    </p>
                    {form.meta_description && (
                      <div className="mt-2 flex items-center gap-2">
                        <div className="flex-1 h-1 rounded-full" style={{ background: '#e5e7eb' }}>
                          <div
                            className="h-1 rounded-full transition-all"
                            style={{
                              width: `${Math.min(100, (form.meta_description.length / 160) * 100)}%`,
                              background: form.meta_description.length > 160 ? '#dc2626' : form.meta_description.length > 110 ? '#16a34a' : '#f59e0b',
                            }}
                          />
                        </div>
                        <span className="text-[10px] flex-shrink-0" style={{ color: form.meta_description.length > 160 ? '#dc2626' : '#6b7280' }}>
                          {form.meta_description.length}/160
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                <div>
                  <label className="text-xs block mb-1.5" style={{ color: 'rgba(255,255,255,0.45)' }}>URL Slug</label>
                  <div className="flex items-center gap-2 h-10 rounded-xl overflow-hidden px-3" style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}>
                    <Link2 size={13} style={{ color: 'rgba(255,255,255,0.25)' }} className="flex-shrink-0" />
                    <span className="text-sm" style={{ color: 'rgba(255,255,255,0.20)' }}>/learn/</span>
                    <input
                      value={form.seo_slug}
                      onChange={e => setForm(f => ({ ...f, seo_slug: e.target.value }))}
                      placeholder="auto-from-title"
                      className="flex-1 h-full text-sm bg-transparent outline-none font-mono"
                      style={{ color: '#E8E8E8' }}
                    />
                  </div>
                </div>
                <div>
                  <label className="text-xs block mb-1.5" style={{ color: 'rgba(255,255,255,0.45)' }}>
                    Meta Description <span style={{ color: 'rgba(255,255,255,0.20)' }}>({form.meta_description?.length || 0}/160)</span>
                  </label>
                  <textarea
                    value={form.meta_description}
                    onChange={e => setForm(f => ({ ...f, meta_description: e.target.value.slice(0, 160) }))}
                    placeholder="160-character description for Google snippets…"
                    rows={3}
                    className="w-full px-4 py-2.5 rounded-xl text-sm outline-none resize-none"
                    style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                  />
                </div>
                <div>
                  <label className="text-xs block mb-1.5" style={{ color: 'rgba(255,255,255,0.45)' }}>Primary Keyword</label>
                  <input
                    value={form.primary_keyword}
                    onChange={e => setForm(f => ({ ...f, primary_keyword: e.target.value }))}
                    placeholder="e.g. AHSEC Class 12 Physics Notes"
                    className="w-full h-10 px-4 rounded-xl text-sm outline-none"
                    style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                  />
                </div>
                <div>
                  <label className="text-xs block mb-1.5" style={{ color: 'rgba(255,255,255,0.45)' }}>SEO Tags <span style={{ color: 'rgba(255,255,255,0.20)' }}>(comma-separated)</span></label>
                  <input
                    value={form.seo_tags}
                    onChange={e => setForm(f => ({ ...f, seo_tags: e.target.value }))}
                    placeholder="ahsec, class 12, physics, optics, notes"
                    className="w-full h-10 px-4 rounded-xl text-sm outline-none"
                    style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                  />
                </div>
                <div>
                  <label className="text-xs block mb-1.5" style={{ color: 'rgba(255,255,255,0.45)' }}>Category Path</label>
                  <input
                    value={form.category}
                    onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
                    placeholder="ahsec/class12/science/physics"
                    className="w-full h-10 px-4 rounded-xl text-sm font-mono outline-none"
                    style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                  />
                </div>
                <div>
                  <label className="text-xs block mb-1.5" style={{ color: 'rgba(255,255,255,0.45)' }}>Schema Type</label>
                  <div className="flex gap-2 flex-wrap">
                    {['Article', 'FAQPage', 'HowTo', 'EducationalOccupationalProgram'].map(s => (
                      <button
                        key={s}
                        onClick={() => setForm(f => ({ ...f, schema_type: s }))}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium border transition-all"
                        style={
                          form.schema_type === s
                            ? { borderColor: '#9575e0', background: 'rgba(149,117,224,0.18)', color: '#c4b0f0' }
                            : { borderColor: 'rgba(255,255,255,0.10)', background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.40)' }
                        }
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <label className="text-xs block mb-1.5" style={{ color: 'rgba(255,255,255,0.45)' }}>Long Description</label>
                  <textarea
                    value={form.description}
                    onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                    placeholder="Optional extended description…"
                    rows={4}
                    className="w-full px-4 py-2.5 rounded-xl text-sm outline-none resize-none"
                    style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs block mb-1.5" style={{ color: 'rgba(255,255,255,0.45)' }}>Thumbnail URL</label>
                    <input
                      value={form.thumbnail_url}
                      onChange={e => setForm(f => ({ ...f, thumbnail_url: e.target.value }))}
                      placeholder="https://…"
                      className="w-full h-10 px-4 rounded-xl text-sm outline-none"
                      style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                    />
                  </div>
                  <div>
                    <label className="text-xs block mb-1.5" style={{ color: 'rgba(255,255,255,0.45)' }}>Alt Text</label>
                    <input
                      value={form.alt_text}
                      onChange={e => setForm(f => ({ ...f, alt_text: e.target.value }))}
                      placeholder="Image alt text"
                      className="w-full h-10 px-4 rounded-xl text-sm outline-none"
                      style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
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
                <div>
                  <label className="text-xs block mb-1.5" style={{ color: 'rgba(255,255,255,0.45)' }}>GEO Tags <span style={{ color: 'rgba(255,255,255,0.20)' }}>(board/class/subject/topic)</span></label>
                  <input
                    value={form.geo_tags}
                    onChange={e => setForm(f => ({ ...f, geo_tags: e.target.value }))}
                    placeholder="ahsec/class-12/pcm/physics"
                    className="w-full h-10 px-4 rounded-xl text-sm font-mono outline-none"
                    style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                  />
                </div>
                <div className="p-4 rounded-xl text-xs space-y-1" style={{ background: 'rgba(149,117,224,0.06)', border: '1px solid rgba(149,117,224,0.12)', color: 'rgba(232,232,232,0.55)' }}>
                  <p className="font-semibold mb-2" style={{ color: '#c4b0f0' }}>GEO Presets</p>
                  {['ahsec/class-11/arts', 'ahsec/class-12/science', 'ahsec/class-12/commerce', 'du/degree/bcom', 'du/degree/ba'].map(preset => (
                    <button
                      key={preset}
                      onClick={() => setForm(f => ({ ...f, geo_tags: preset }))}
                      className="block w-full text-left py-1.5 px-2.5 rounded-lg font-mono text-xs transition-colors"
                      style={{ color: 'rgba(232,232,232,0.50)' }}
                      onMouseEnter={e => { e.currentTarget.style.background = 'rgba(149,117,224,0.10)'; e.currentTarget.style.color = '#c4b0f0'; }}
                      onMouseLeave={e => { e.currentTarget.style.background = ''; e.currentTarget.style.color = 'rgba(232,232,232,0.50)'; }}
                    >
                      {preset}
                    </button>
                  ))}
                </div>
                {form.geo_tags && (
                  <div className="p-4 rounded-xl text-xs space-y-2" style={{ background: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.12)' }}>
                    <p className="font-semibold" style={{ color: '#34d399' }}>Live GEO URL Preview</p>
                    <p className="font-mono break-all" style={{ color: 'rgba(232,232,232,0.60)' }}>
                      syrabit.ai/{form.geo_tags}/{form.seo_slug || 'your-slug'}
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
