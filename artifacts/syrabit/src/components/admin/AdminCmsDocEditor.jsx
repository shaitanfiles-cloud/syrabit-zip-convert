import { useState, useEffect, useCallback, useRef } from 'react';
import {
  MDXEditor,
  headingsPlugin, listsPlugin, quotePlugin, thematicBreakPlugin,
  markdownShortcutPlugin, codeBlockPlugin, codeMirrorPlugin, tablePlugin,
  linkPlugin, diffSourcePlugin, toolbarPlugin,
  UndoRedo, BoldItalicUnderlineToggles, BlockTypeSelect,
  CreateLink, CodeToggle, InsertTable, InsertThematicBreak,
  ListsToggle, Separator, DiffSourceToggleWrapper, InsertCodeBlock,
} from '@mdxeditor/editor';
import '@mdxeditor/editor/style.css';
import {
  Plus, Save, Trash2, Loader2, FileText, Globe, Lock,
  Sparkles, Eye, Edit2, BookOpen, Tag, Link2, Search,
  FileUp, GitBranch, ExternalLink, Monitor, ArrowRightLeft,
  CheckCircle, Copy, Zap, ChevronDown, ChevronRight as ChevronRightIcon,
  Languages, X,
} from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { cmsAiSuggest } from '@/utils/api';

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

const TEMPLATES = [
  { label: 'PYQ Block',      shortcode: '\n\n> **[PYQ year=2025]** _Question text here._ *(3 marks)*\n\n' },
  { label: 'Formula Box',    shortcode: '\n\n> **[FORMULA]** Name: `expression = result`\n\n' },
  { label: 'AHSEC Tip',      shortcode: '\n\n> **[BOARD-TIP]** This topic is important for board exams.\n\n' },
  { label: 'Note Block',     shortcode: '\n\n> **[NOTE]** Key insight or definition here.\n\n' },
  { label: 'H2 Section',     shortcode: '\n\n## Section Title\n\n_Content here._\n\n---\n\n' },
  { label: 'Syllabus Intro', shortcode: '\n\n## Syllabus Overview\n\nThis document covers the official syllabus as per the board guidelines.\n\n### Key Topics\n\n- Topic 1\n- Topic 2\n- Topic 3\n\n### Chapters\n\n1. Chapter 1\n2. Chapter 2\n\n### Exam Guidelines\n\n_As per official board regulations._\n\n---\n\n' },
  { label: 'Chapter Link',   shortcode: '\n\n[Chapter: Title](/learn/chapter-slug)\n\n' },
];

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
        {aiParsing
          ? <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" style={{ animation: 'spin 1s linear infinite' }}><path d="M12 22C17.5228 22 22 17.5228 22 12H20C20 16.4183 16.4183 20 12 20V22Z"/></svg>
          : <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L13.09 8.26L19 7L14.74 11.74L20 14L13.74 14.91L14 21L9.26 16.74L7 21L7.91 14.74L2 14L7.26 11.26L3 7L8.91 8.09L12 2Z"/></svg>}
        AI
      </button>
    </DiffSourceToggleWrapper>
  );
}

export default function AdminCmsDocEditor({ adminToken, onNavigate, hubContext }) {
  const [docs, setDocs]               = useState([]);
  const [loading, setLoading]         = useState(true);
  const [editDoc, setEditDoc]         = useState(null);
  const [form, setForm]               = useState(EMPTY_DOC);
  const [saving, setSaving]           = useState(false);
  const [publishing, setPublishing]   = useState(false);
  const [pdfLoading, setPdfLoading]   = useState(false);
  const [aiParsing, setAiParsing]     = useState(false);
  const [seoGenerating, setSeoGenerating] = useState(false);
  const [seoResult, setSeoResult]     = useState(null);
  const [searchQ, setSearchQ]         = useState('');
  const [seoTab, setSeoTab]           = useState('content');
  const [filterType, setFilterType]   = useState('all');

  const [showPreview, setShowPreview]             = useState(false);
  const [syllabusOpen, setSyllabusOpen]           = useState(false);
  const [spBoards, setSpBoards]                   = useState([]);
  const [spClasses, setSpClasses]                 = useState([]);
  const [spStreams, setSpStreams]                  = useState([]);
  const [spSubjects, setSpSubjects]               = useState([]);
  const [spBoard, setSpBoard]                     = useState('');
  const [spClass, setSpClass]                     = useState('');
  const [spStream, setSpStream]                   = useState('');
  const [spSubject, setSpSubject]                 = useState('');
  const [syllabusInserting, setSyllabusInserting] = useState(false);
  const [savingRevision, setSavingRevision]       = useState(false);
  const [linkingScope, setLinkingScope]           = useState(false);
  const [linkedScopeLabel, setLinkedScopeLabel]   = useState('');
  const [scopePickerOpen, setScopePickerOpen]     = useState(false);
  const [autoKeywordLoading, setAutoKeywordLoading] = useState(false);
  const [translateOpen, setTranslateOpen]         = useState(false);
  const [translateLang, setTranslateLang]         = useState('as');
  const [translating, setTranslating]             = useState(false);
  const [translateResult, setTranslateResult]     = useState('');
  const [aiPaletteOpen, setAiPaletteOpen]         = useState(false);
  const [aiPaletteText, setAiPaletteText]         = useState('');
  const [aiPaletteAction, setAiPaletteAction]     = useState('improve');
  const [aiPaletteResult, setAiPaletteResult]     = useState('');
  const [aiPaletteLoading, setAiPaletteLoading]   = useState(false);

  const pdfRef    = useRef(null);
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
        title:            prefill.title            || f.title,
        content:          prefill.content          || f.content,
        seo_slug:         prefill.seo_slug         || f.seo_slug,
        meta_description: prefill.meta_description || f.meta_description,
        status:           'draft',
      }));
      setSeoTab('content');
      toast.success(`Pre-filled with merged content for "${prefill.title}" — review and save`);
    } catch {}
  }, []);

  useEffect(() => {
    axios.get(`${API}/content/boards`).then(r => setSpBoards(r.data || [])).catch(() => {});
  }, []);

  // ── Pre-fill scope picker from hub context ────────────────────────────────
  useEffect(() => {
    if (!hubContext?.subjectId) return;
    if (hubContext.boardId   && !spBoard)   setSpBoard(hubContext.boardId);
    if (hubContext.classId   && !spClass)   setSpClass(hubContext.classId);
    if (hubContext.streamId  && !spStream)  setSpStream(hubContext.streamId);
    if (hubContext.subjectId && !spSubject) setSpSubject(hubContext.subjectId);
  }, [hubContext?.subjectId]);

  useEffect(() => {
    if (!spBoard) { setSpClasses([]); setSpClass(''); return; }
    axios.get(`${API}/content/classes?board_id=${spBoard}`).then(r => setSpClasses(r.data || [])).catch(() => {});
    setSpClass(''); setSpStream(''); setSpSubject('');
  }, [spBoard]);

  useEffect(() => {
    if (!spClass) { setSpStreams([]); setSpStream(''); return; }
    axios.get(`${API}/content/streams?class_id=${spClass}`).then(r => setSpStreams(r.data || [])).catch(() => {});
    setSpStream(''); setSpSubject('');
  }, [spClass]);

  useEffect(() => {
    if (!spStream) { setSpSubjects([]); setSpSubject(''); return; }
    axios.get(`${API}/content/subjects?stream_id=${spStream}`).then(r => setSpSubjects(r.data || [])).catch(() => {});
    setSpSubject('');
  }, [spStream]);

  useEffect(() => {
    if (editDoc?.linked_scope) {
      const parts = editDoc.linked_scope.split('/');
      setLinkedScopeLabel(editDoc.linked_scope);
      if (parts[0]) setSpBoard(parts[0]);
      if (parts[1]) setSpClass(parts[1]);
      if (parts[2]) setSpStream(parts[2]);
      if (parts[3]) setSpSubject(parts[3]);
    } else {
      setLinkedScopeLabel('');
    }
  }, [editDoc]);

  const openNew = () => { setEditDoc(null); setForm({ ...EMPTY_DOC }); setSeoTab('content'); setLinkedScopeLabel(''); setShowPreview(false); };

  const openEdit = (doc) => {
    setEditDoc(doc);
    setForm({
      title:            doc.title            || '',
      content:          doc.content          || '',
      meta_description: doc.meta_description || '',
      description:      doc.description      || '',
      seo_tags:         doc.seo_tags         || '',
      primary_keyword:  doc.primary_keyword  || '',
      seo_slug:         doc.seo_slug         || '',
      category:         doc.category         || '',
      geo_tags:         doc.geo_tags         || '',
      schema_type:      doc.schema_type      || 'Article',
      status:           doc.status           || 'draft',
      thumbnail_url:    doc.thumbnail_url    || '',
      alt_text:         doc.alt_text         || '',
    });
    setSeoTab('content');
    setShowPreview(false);
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
        raw_text: content, subject: form.geo_tags || '', chapter: form.title || '',
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
    if (!confirm('Delete this document permanently?')) return;
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
        `${API}/admin/content/extract-pdf-text`, formData,
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

  const handleTranslate = async () => {
    const content = editorRef.current?.getMarkdown() || form.content;
    if (!content) { toast.error('No content to translate'); return; }
    setTranslating(true);
    setTranslateResult('');
    try {
      const res = await axios.post(
        `${API}/admin/vertex/translate`,
        { text: content.slice(0, 4000), target_lang: translateLang, source_lang: 'en' },
        authHeaders(adminToken)
      );
      setTranslateResult(res.data.translated || '');
      toast.success('Translation ready');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Translation failed');
    } finally { setTranslating(false); }
  };

  const handleAiPalette = async () => {
    const selected = aiPaletteText.trim();
    if (!selected) { toast.error('Enter or paste text to rewrite'); return; }
    setAiPaletteLoading(true);
    setAiPaletteResult('');
    try {
      const res = await cmsAiSuggest(adminToken, selected, aiPaletteAction, form.geo_tags || '', form.title || '');
      const suggestion = res.data?.suggestion || res.data?.text || '';
      setAiPaletteResult(suggestion);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'AI suggestion failed');
    } finally { setAiPaletteLoading(false); }
  };

  const applyAiPaletteResult = () => {
    if (!aiPaletteResult) return;
    const current = editorRef.current?.getMarkdown() || form.content;
    const updated = aiPaletteText
      ? current.replace(aiPaletteText, aiPaletteResult)
      : current + '\n\n' + aiPaletteResult;
    setForm(f => ({ ...f, content: updated }));
    setAiPaletteOpen(false);
    setAiPaletteText('');
    setAiPaletteResult('');
    toast.success('AI suggestion applied to content');
  };

  const handleInsertSyllabus = async () => {
    if (!spBoard || !spClass) { toast.error('Select at least Board and Class'); return; }
    setSyllabusInserting(true);
    try {
      let url = `${API}/syllabi/${spBoard}/${spClass}`;
      if (spStream && spSubject) url = `${API}/syllabi/${spBoard}/${spClass}/${spStream}/${spSubject}`;
      else if (spStream) url = `${API}/syllabi/${spBoard}/${spClass}/${spStream}`;
      const res = await axios.get(url, { withCredentials: true });
      const syl = res.data;
      if (!syl?.content && !syl?.chapters?.length) { toast.error('No syllabus found for this scope'); return; }
      let block = `\n\n# Subject Syllabus\n\n`;
      if (syl.content) block += `${syl.content}\n\n`;
      if (syl.topics?.length) block += `## Key Topics\n\n${syl.topics.map(t => `- ${t}`).join('\n')}\n\n`;
      if (syl.chapters?.length) block += `## Chapters\n\n${syl.chapters.map((c, i) => `${i + 1}. ${c}`).join('\n')}\n\n`;
      if (syl.guidelines) block += `## Guidelines\n\n${syl.guidelines}\n\n`;
      block += '---\n\n';
      const current = editorRef.current?.getMarkdown() || form.content;
      setForm(f => ({ ...f, content: current + block }));
      if (syl.topics?.length && !form.primary_keyword) {
        setForm(f => ({ ...f, primary_keyword: syl.topics[0] }));
      }
      setSyllabusOpen(false);
      toast.success('Syllabus block inserted');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to fetch syllabus');
    } finally { setSyllabusInserting(false); }
  };

  const handleSaveRevision = async () => {
    if (!editDoc) { toast.error('Save the document first'); return; }
    setSavingRevision(true);
    try {
      const res = await axios.post(`${API}/admin/content/cms-documents/${editDoc.id}/revisions`, {}, authHeaders(adminToken));
      await load();
      toast.success(`Revision saved: ${res.data.title}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Revision failed');
    } finally { setSavingRevision(false); }
  };

  const handleHandOff = () => {
    const liveContent = editorRef.current?.getMarkdown() || form.content;
    if (!liveContent.trim()) { toast.error('No content to hand off'); return; }
    localStorage.setItem('syrabit_editor_prefill', JSON.stringify({
      title:     form.title,
      content:   liveContent,
      timestamp: Date.now(),
    }));
    toast.success('Content handed off to Content Editor');
    onNavigate?.('editor');
  };

  const handleLinkSyllabus = async () => {
    if (!editDoc) { toast.error('Save the document first'); return; }
    if (!spBoard || !spClass) { toast.error('Select Board and Class at minimum'); return; }
    setLinkingScope(true);
    try {
      const res = await axios.post(
        `${API}/admin/content/cms-documents/${editDoc.id}/link-syllabus`,
        { board_id: spBoard, class_id: spClass, stream_id: spStream, subject_id: spSubject },
        authHeaders(adminToken)
      );
      setForm(f => ({ ...f, geo_tags: res.data.geo_tags || f.geo_tags }));
      setLinkedScopeLabel(`${res.data.board_name} / ${res.data.class_name}${res.data.stream_name ? ' / ' + res.data.stream_name : ''}${res.data.subject_name ? ' / ' + res.data.subject_name : ''}`);
      setEditDoc(d => ({ ...d, linked_scope: `${spBoard}/${spClass}/${spStream}/${spSubject}`, canonical_url: res.data.canonical_url }));
      setScopePickerOpen(false);
      await load();
      toast.success('Linked to syllabus scope');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Link failed');
    } finally { setLinkingScope(false); }
  };

  const handleAutoKeyword = () => {
    const terms = [form.title, ...(form.seo_tags || '').split(',').map(t => t.trim())].filter(Boolean);
    if (!terms.length) { toast.error('Add a title or SEO tags first'); return; }
    const kw = terms[0];
    setForm(f => ({ ...f, primary_keyword: kw }));
    toast.success(`Primary keyword set to "${kw}"`);
  };

  const handleGenerateSeoMeta = async () => {
    if (!form.title && !form.content && !form.primary_keyword) {
      toast.error('Add a title or content first so AI has context');
      return;
    }
    setSeoGenerating(true);
    setSeoResult(null);
    try {
      const payload = {
        title:           form.title,
        content:         form.content?.slice(0, 3000) || '',
        primary_keyword: form.primary_keyword,
        seo_tags:        form.seo_tags,
        linked_scope:    editDoc?.linked_scope || '',
        board:           editDoc?.geo_tags?.includes('ahsec') ? 'AHSEC' : 'AHSEC',
        subject:         form.category || form.seo_tags?.split(',')[0] || '',
      };
      const { data } = await axios.post(`${API}/admin/seo/generate`, payload, authHeaders(adminToken));
      setSeoResult(data);
      toast.success('SEO metadata generated — review and apply below');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'AI SEO generation failed');
    } finally {
      setSeoGenerating(false);
    }
  };

  const applySeoResult = () => {
    if (!seoResult) return;
    setForm(f => ({
      ...f,
      title:           seoResult.seo_title || f.title,
      meta_description: seoResult.meta_description || f.meta_description,
      primary_keyword: seoResult.primary_keyword || f.primary_keyword,
      seo_tags:        seoResult.seo_tags || f.seo_tags,
    }));
    setSeoResult(null);
    toast.success('SEO metadata applied to page');
  };

  const handleAutoGeoTags = () => {
    const parts = [];
    if (form.title) parts.push(form.title);
    if (form.geo_tags) parts.push(form.geo_tags);
    if (form.seo_tags) form.seo_tags.split(',').slice(0, 3).forEach(t => parts.push(t.trim()));
    if (!parts.length) { toast.error('Add title and GEO tags first'); return; }
    const phrases = [...new Set(parts.filter(Boolean))];
    setForm(f => ({ ...f, geo_tags: phrases.join(', ') }));
    toast.success(`${phrases.length} authority phrases set`);
  };

  const filtered = docs.filter(d => {
    const matchQ = !searchQ || d.title?.toLowerCase().includes(searchQ.toLowerCase()) || d.seo_slug?.includes(searchQ);
    const matchType = filterType === 'all' ? true
      : filterType === 'published' ? d.status === 'published'
      : filterType === 'draft' ? d.status === 'draft'
      : filterType === 'syllabus' ? d.type === 'syllabus'
      : filterType === 'revision' ? d.is_revision === true
      : true;
    return matchQ && matchType;
  });

  const inEditor = editDoc !== null || form.title || form.content;
  const canPreview = showPreview && !!form.seo_slug;
  const FILTER_OPTIONS = [
    { id: 'all',      label: 'All' },
    { id: 'published',label: 'Live' },
    { id: 'draft',    label: 'Draft' },
    { id: 'syllabus', label: 'Syllabus' },
    { id: 'revision', label: 'Revisions' },
  ];

  const selectStyle = {
    color: '#E8E8E8', background: 'rgba(255,255,255,0.05)',
    border: '1px solid rgba(255,255,255,0.10)', borderRadius: 8,
    padding: '4px 8px', fontSize: 11, outline: 'none',
  };

  return (
    <div className="h-full flex overflow-hidden" style={{ background: '#121212' }}>
      {/* ── Left — document list ─────────────────────────────────────── */}
      <div className="w-72 flex-shrink-0 border-r flex flex-col" style={{ background: '#191919', borderColor: 'rgba(255,255,255,0.07)' }}>
        <div className="px-3 py-3 border-b space-y-2" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: 'rgba(255,255,255,0.25)' }} />
              <input
                value={searchQ}
                onChange={e => setSearchQ(e.target.value)}
                placeholder="Search documents…"
                className="w-full h-8 pl-8 pr-3 rounded-lg text-xs outline-none"
                style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
              />
            </div>
            <button onClick={openNew} className="h-8 px-2 rounded-lg flex items-center gap-1 text-xs font-medium flex-shrink-0" style={{ background: '#9575e0', color: 'white' }}>
              <Plus size={13} /> New
            </button>
          </div>
          <div className="flex gap-1 flex-wrap">
            {FILTER_OPTIONS.map(opt => (
              <button
                key={opt.id}
                onClick={() => setFilterType(opt.id)}
                className="px-2 py-0.5 rounded-md text-[10px] font-medium transition-colors"
                style={filterType === opt.id
                  ? { background: 'rgba(149,117,224,0.25)', color: '#c4b0f0', border: '1px solid rgba(149,117,224,0.35)' }
                  : { background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.35)', border: '1px solid rgba(255,255,255,0.07)' }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto py-2">
          {loading ? (
            <div className="space-y-1.5 p-3">
              {[...Array(5)].map((_, i) => <div key={i} className="h-14 rounded-xl animate-pulse" style={{ background: 'rgba(255,255,255,0.04)' }} />)}
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-6 text-center">
              <FileText size={28} className="mx-auto mb-3" style={{ color: 'rgba(255,255,255,0.10)' }} />
              <p className="text-xs" style={{ color: 'rgba(255,255,255,0.25)' }}>{searchQ || filterType !== 'all' ? 'No results' : 'No documents yet'}</p>
              {!searchQ && filterType === 'all' && <button onClick={openNew} className="mt-3 text-xs" style={{ color: '#9575e0' }}>Create first →</button>}
            </div>
          ) : filtered.map(doc => {
            const st = STATUS_COLORS[doc.status] || STATUS_COLORS.draft;
            const StIcon = st.icon;
            const isActive = editDoc?.id === doc.id;
            return (
              <div
                key={doc.id}
                onClick={() => openEdit(doc)}
                className="mx-2 mb-1 p-3 rounded-xl cursor-pointer group transition-colors"
                style={{ border: isActive ? '1px solid rgba(149,117,224,0.30)' : '1px solid transparent', background: isActive ? 'rgba(149,117,224,0.10)' : 'transparent' }}
              >
                <div className="flex items-start gap-2">
                  <StIcon size={12} className="flex-shrink-0 mt-0.5" style={{ color: st.text }} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate leading-tight" style={{ color: isActive ? '#c4b0f0' : 'rgba(232,232,232,0.75)' }}>
                      {doc.title || 'Untitled'}
                    </p>
                    <p className="text-[10px] truncate mt-0.5 font-mono" style={{ color: 'rgba(255,255,255,0.25)' }}>{doc.seo_slug || '—'}</p>
                    <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                      <span className="text-[10px]" style={{ color: st.text }}>{doc.status}</span>
                      {doc.type === 'syllabus' && <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(16,185,129,0.12)', color: '#34d399' }}>syllabus</span>}
                      {doc.is_revision && <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(245,158,11,0.12)', color: '#fbbf24' }}>rev</span>}
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
          })}
        </div>

        <div className="px-4 py-2 border-t" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <p className="text-[10px] text-center" style={{ color: 'rgba(255,255,255,0.20)' }}>{docs.length} documents</p>
        </div>
      </div>

      {/* ── Right — editor ───────────────────────────────────────────── */}
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
          {/* ── Toolbar ──────────────────────────────────────────────── */}
          <div className="h-14 flex-shrink-0 border-b flex items-center px-4 gap-2" style={{ background: '#191919', borderColor: 'rgba(255,255,255,0.07)' }}>
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
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border flex-shrink-0"
                style={{ background: STATUS_COLORS[form.status]?.bg, borderColor: STATUS_COLORS[form.status]?.border, color: STATUS_COLORS[form.status]?.text }}>
                {form.status === 'published' ? <Globe size={11} /> : <Lock size={11} />}
                {form.status}
              </div>
            )}

            {linkedScopeLabel && (
              <div className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium border flex-shrink-0"
                style={{ background: 'rgba(16,185,129,0.10)', borderColor: 'rgba(16,185,129,0.25)', color: '#34d399' }}>
                <Link2 size={9} /> Linked
              </div>
            )}

            <button onClick={() => setShowPreview(v => !v)} title="Toggle live preview"
              className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-xs font-medium flex-shrink-0 border transition-all"
              style={showPreview
                ? { background: 'rgba(124,58,237,0.20)', color: '#c4b0f0', borderColor: 'rgba(124,58,237,0.35)' }
                : { background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.45)', borderColor: 'rgba(255,255,255,0.10)' }}>
              <Monitor size={12} /> Preview
            </button>

            <input ref={pdfRef} type="file" accept=".pdf" className="hidden" onChange={handlePdfUpload} />
            <button onClick={() => pdfRef.current?.click()} disabled={pdfLoading}
              className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-xs font-medium disabled:opacity-40 flex-shrink-0 border"
              style={{ background: 'rgba(59,130,246,0.15)', color: '#60a5fa', borderColor: 'rgba(59,130,246,0.20)' }}>
              {pdfLoading ? <Loader2 size={12} className="animate-spin" /> : <FileUp size={12} />}
              PDF
            </button>

            <button onClick={() => { setAiPaletteOpen(v => !v); setAiPaletteResult(''); }}
              className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-xs font-medium flex-shrink-0 border"
              style={aiPaletteOpen
                ? { background: 'rgba(139,92,246,0.25)', color: '#c4b5fd', borderColor: 'rgba(139,92,246,0.45)' }
                : { background: 'rgba(139,92,246,0.10)', color: '#a78bfa', borderColor: 'rgba(139,92,246,0.22)' }}>
              <Sparkles size={12} /> AI Write
            </button>

            <button onClick={() => { setTranslateOpen(v => !v); setTranslateResult(''); }}
              className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-xs font-medium flex-shrink-0 border"
              style={translateOpen
                ? { background: 'rgba(16,185,129,0.20)', color: '#34d399', borderColor: 'rgba(16,185,129,0.35)' }
                : { background: 'rgba(16,185,129,0.10)', color: '#34d399', borderColor: 'rgba(16,185,129,0.20)' }}>
              <Languages size={12} /> Translate
            </button>

            {editDoc && (
              <button onClick={handleSaveRevision} disabled={savingRevision} title="Save as new revision"
                className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-xs font-medium disabled:opacity-40 flex-shrink-0 border"
                style={{ background: 'rgba(245,158,11,0.12)', color: '#fbbf24', borderColor: 'rgba(245,158,11,0.20)' }}>
                {savingRevision ? <Loader2 size={12} className="animate-spin" /> : <GitBranch size={12} />}
                Revision
              </button>
            )}

            {editDoc && (
              <button onClick={handleHandOff} title="Hand off content to Content Editor"
                className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-xs font-medium flex-shrink-0 border"
                style={{ background: 'rgba(99,102,241,0.12)', color: '#818cf8', borderColor: 'rgba(99,102,241,0.22)' }}>
                <ArrowRightLeft size={12} /> Hand Off
              </button>
            )}

            <button onClick={handlePublishToggle} disabled={publishing || !editDoc}
              className="h-8 px-2.5 rounded-lg flex items-center gap-1.5 text-xs font-medium disabled:opacity-40 flex-shrink-0 border"
              style={form.status === 'published'
                ? { background: 'rgba(245,158,11,0.15)', color: '#fbbf24', borderColor: 'rgba(245,158,11,0.20)' }
                : { background: 'rgba(16,185,129,0.15)', color: '#34d399', borderColor: 'rgba(16,185,129,0.20)' }}>
              {publishing ? <Loader2 size={12} className="animate-spin" /> : <Globe size={12} />}
              {form.status === 'published' ? 'Unpublish' : 'Publish'}
            </button>

            <button onClick={handleSave} disabled={saving || !form.title.trim()}
              className="h-8 px-3 rounded-lg flex items-center gap-1.5 text-xs font-semibold disabled:opacity-40 flex-shrink-0"
              style={{ background: '#9575e0', color: 'white' }}>
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>

          {/* ── Sub-tabs ─────────────────────────────────────────────── */}
          <div className="flex-shrink-0 border-b flex gap-0" style={{ background: 'rgba(255,255,255,0.012)', borderColor: 'rgba(255,255,255,0.07)' }}>
            {[
              { id: 'content', label: 'Content',    icon: Edit2 },
              { id: 'seo',     label: 'SEO & Meta', icon: Tag },
              { id: 'geo',     label: 'GEO Tags',   icon: Globe },
            ].map(t => (
              <button key={t.id} onClick={() => setSeoTab(t.id)}
                className="flex items-center gap-1.5 px-5 py-3 text-xs font-medium border-b-2 transition-colors"
                style={{ borderBottomColor: seoTab === t.id ? '#9575e0' : 'transparent', color: seoTab === t.id ? '#c4b0f0' : 'rgba(255,255,255,0.35)' }}>
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
              {editDoc && form.seo_slug && (
                <a href={`/learn/${form.seo_slug}`} target="_blank" rel="noreferrer"
                  className="flex items-center gap-1 text-[10px] transition-colors"
                  style={{ color: 'rgba(255,255,255,0.25)' }}
                  onMouseEnter={e => e.currentTarget.style.color = '#c4b0f0'}
                  onMouseLeave={e => e.currentTarget.style.color = 'rgba(255,255,255,0.25)'}>
                  <ExternalLink size={10} /> View
                </a>
              )}
            </div>
          </div>

          {/* ── Content Tab ──────────────────────────────────────────── */}
          {seoTab === 'content' && (
            <div className="flex-1 flex flex-col overflow-hidden min-h-0">
              {/* Template + Syllabus bar */}
              <div className="flex-shrink-0 border-b" style={{ borderColor: 'rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.015)' }}>
                <div className="flex items-center gap-1.5 px-4 py-2 flex-wrap">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.25)" strokeWidth="2" className="flex-shrink-0"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
                  <span className="text-[10px] flex-shrink-0 mr-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>Insert:</span>
                  {TEMPLATES.map(t => (
                    <button key={t.label}
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
                  <button
                    onClick={() => setSyllabusOpen(v => !v)}
                    className="ml-1 px-2 py-0.5 rounded text-[10px] border flex items-center gap-1 transition-colors"
                    style={syllabusOpen
                      ? { borderColor: 'rgba(149,117,224,0.50)', background: 'rgba(149,117,224,0.15)', color: '#c4b0f0' }
                      : { borderColor: 'rgba(149,117,224,0.25)', background: 'rgba(149,117,224,0.07)', color: 'rgba(196,176,240,0.65)' }}>
                    <BookOpen size={9} />
                    Insert Syllabus
                    {syllabusOpen ? <ChevronDown size={9} /> : <ChevronRightIcon size={9} />}
                  </button>
                </div>

                {syllabusOpen && (
                  <div className="px-4 pb-3 flex items-end gap-2 flex-wrap" style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                    <div>
                      <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.30)' }}>Board</p>
                      <select value={spBoard} onChange={e => setSpBoard(e.target.value)} style={selectStyle}>
                        <option value="">— Board —</option>
                        {spBoards.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                      </select>
                    </div>
                    <div>
                      <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.30)' }}>Class</p>
                      <select value={spClass} onChange={e => setSpClass(e.target.value)} disabled={!spBoard} style={selectStyle}>
                        <option value="">— Class —</option>
                        {spClasses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </select>
                    </div>
                    <div>
                      <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.30)' }}>Stream</p>
                      <select value={spStream} onChange={e => setSpStream(e.target.value)} disabled={!spClass} style={selectStyle}>
                        <option value="">— Stream —</option>
                        {spStreams.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                      </select>
                    </div>
                    <div>
                      <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.30)' }}>Subject</p>
                      <select value={spSubject} onChange={e => setSpSubject(e.target.value)} disabled={!spStream} style={selectStyle}>
                        <option value="">— Subject —</option>
                        {spSubjects.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                      </select>
                    </div>
                    <button onClick={handleInsertSyllabus} disabled={syllabusInserting || !spBoard || !spClass}
                      className="h-8 px-3 rounded-lg flex items-center gap-1.5 text-xs font-medium disabled:opacity-40"
                      style={{ background: '#9575e0', color: 'white' }}>
                      {syllabusInserting ? <Loader2 size={11} className="animate-spin" /> : <BookOpen size={11} />}
                      Insert
                    </button>
                  </div>
                )}
              </div>

              {/* Gemini Translate Panel */}
              {translateOpen && (
                <div style={{ background: 'rgba(16,185,129,0.06)', borderBottom: '1px solid rgba(16,185,129,0.18)', padding: '10px 16px' }}>
                  <div className="flex items-center gap-3 flex-wrap">
                    <Languages size={14} color="#34d399" />
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#34d399' }}>Gemini Translate</span>
                    <select value={translateLang} onChange={e => setTranslateLang(e.target.value)}
                      style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(16,185,129,0.30)', borderRadius: 8, padding: '4px 10px', color: '#e8e8e8', fontSize: 12 }}>
                      <option value="as">Assamese (অসমীয়া)</option>
                      <option value="hi">Hindi (हिन्दी)</option>
                      <option value="bn">Bengali (বাংলা)</option>
                      <option value="bho">Bodo (बड़ो)</option>
                    </select>
                    <button onClick={handleTranslate} disabled={translating}
                      style={{ background: 'rgba(16,185,129,0.2)', border: '1px solid rgba(16,185,129,0.35)', color: '#34d399', borderRadius: 8, padding: '4px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
                      {translating ? <Loader2 size={12} className="animate-spin" /> : <Languages size={12} />}
                      {translating ? 'Translating…' : 'Translate Content'}
                    </button>
                    <button onClick={() => setTranslateOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(255,255,255,0.35)', marginLeft: 'auto' }}>
                      <X size={14} />
                    </button>
                  </div>
                  {translateResult && (
                    <div style={{ marginTop: 10, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(16,185,129,0.20)', borderRadius: 8, padding: '10px 14px', maxHeight: 180, overflowY: 'auto' }}>
                      <div className="flex items-center justify-between mb-2">
                        <span style={{ fontSize: 10, fontWeight: 700, color: '#34d399', textTransform: 'uppercase' }}>Translation Result</span>
                        <button onClick={() => { navigator.clipboard.writeText(translateResult); toast.success('Copied!'); }}
                          style={{ background: 'rgba(16,185,129,0.15)', border: '1px solid rgba(16,185,129,0.3)', color: '#34d399', borderRadius: 6, padding: '2px 8px', fontSize: 11, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                          <Copy size={10} /> Copy
                        </button>
                      </div>
                      <p style={{ fontSize: 13, color: '#e8e8e8', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{translateResult}</p>
                    </div>
                  )}
                </div>
              )}

              {/* Gemini AI Writing Palette */}
              {aiPaletteOpen && (
                <div style={{ background: 'rgba(139,92,246,0.07)', borderBottom: '1px solid rgba(139,92,246,0.22)', padding: '10px 16px' }}>
                  <div className="flex items-center gap-3 flex-wrap mb-2">
                    <Sparkles size={14} color="#a78bfa" />
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#a78bfa' }}>Gemini AI Palette</span>
                    <select value={aiPaletteAction} onChange={e => setAiPaletteAction(e.target.value)}
                      style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(139,92,246,0.30)', borderRadius: 8, padding: '4px 10px', color: '#e8e8e8', fontSize: 12 }}>
                      <option value="improve">Improve writing</option>
                      <option value="simplify">Simplify</option>
                      <option value="expand">Expand explanation</option>
                      <option value="summarize">Summarize</option>
                      <option value="rewrite">Rewrite formally</option>
                      <option value="bullets">Convert to bullets</option>
                    </select>
                    <button onClick={handleAiPalette} disabled={aiPaletteLoading || !aiPaletteText.trim()}
                      style={{ background: 'rgba(139,92,246,0.20)', border: '1px solid rgba(139,92,246,0.40)', color: '#c4b5fd', borderRadius: 8, padding: '4px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, opacity: aiPaletteLoading || !aiPaletteText.trim() ? 0.5 : 1 }}>
                      {aiPaletteLoading ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
                      {aiPaletteLoading ? 'Rewriting…' : 'Run'}
                    </button>
                    <button onClick={() => setAiPaletteOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(255,255,255,0.35)', marginLeft: 'auto' }}>
                      <X size={14} />
                    </button>
                  </div>
                  <textarea
                    value={aiPaletteText}
                    onChange={e => { setAiPaletteText(e.target.value); setAiPaletteResult(''); }}
                    placeholder="Paste or type the text you want Gemini to rewrite…"
                    rows={3}
                    style={{ width: '100%', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(139,92,246,0.20)', borderRadius: 8, padding: '8px 12px', color: '#e8e8e8', fontSize: 12, resize: 'vertical', outline: 'none' }}
                  />
                  {aiPaletteResult && (
                    <div style={{ marginTop: 8, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(139,92,246,0.20)', borderRadius: 8, padding: '10px 14px' }}>
                      <div className="flex items-center justify-between mb-2">
                        <span style={{ fontSize: 10, fontWeight: 700, color: '#a78bfa', textTransform: 'uppercase' }}>Suggestion</span>
                        <div className="flex items-center gap-2">
                          <button onClick={() => { navigator.clipboard.writeText(aiPaletteResult); toast.success('Copied!'); }}
                            style={{ background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.3)', color: '#a78bfa', borderRadius: 6, padding: '2px 8px', fontSize: 11, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                            <Copy size={10} /> Copy
                          </button>
                          <button onClick={applyAiPaletteResult}
                            style={{ background: 'rgba(139,92,246,0.25)', border: '1px solid rgba(139,92,246,0.4)', color: '#c4b5fd', borderRadius: 6, padding: '2px 8px', fontSize: 11, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                            <CheckCircle size={10} /> Apply to Content
                          </button>
                        </div>
                      </div>
                      <p style={{ fontSize: 13, color: '#e8e8e8', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>{aiPaletteResult}</p>
                    </div>
                  )}
                </div>
              )}

              {/* Editor area — split when preview is on */}
              <div className={`flex-1 min-h-0 flex ${canPreview ? 'gap-0' : ''} overflow-hidden`}>
                <div className={`${canPreview ? 'w-1/2 border-r' : 'flex-1'} overflow-hidden cms-light-editor-wrapper`}
                  data-color-mode="light"
                  style={{ backgroundColor: '#ffffff', color: '#1a1a1a', borderColor: 'rgba(0,0,0,0.08)' }}>
                  <MDXEditor
                    ref={editorRef}
                    key={editDoc?.id ?? '__new__'}
                    markdown={form.content || ''}
                    onChange={md => setForm(f => ({ ...f, content: md }))}
                    plugins={[
                      headingsPlugin(), listsPlugin(), quotePlugin(), thematicBreakPlugin(),
                      markdownShortcutPlugin(),
                      codeBlockPlugin({ defaultCodeBlockLanguage: 'text' }),
                      codeMirrorPlugin({ codeBlockLanguages: { js: 'JavaScript', ts: 'TypeScript', python: 'Python', text: 'Text', md: 'Markdown', html: 'HTML', css: 'CSS' } }),
                      tablePlugin(), linkPlugin(),
                      diffSourcePlugin({ viewMode: 'rich-text', diffMarkdown: form.content || '' }),
                      toolbarPlugin({ toolbarContents: () => <MdxToolbar onAiParse={handleAiParse} aiParsing={aiParsing} /> }),
                    ]}
                    className="mdx-editor-light h-full"
                    contentEditableClassName="cms-editor-content"
                  />
                </div>

                {canPreview && (
                  <div className="w-1/2 flex flex-col overflow-hidden" style={{ background: '#ffffff' }}>
                    <div className="flex items-center gap-2 px-3 py-1.5 border-b flex-shrink-0" style={{ borderColor: 'rgba(0,0,0,0.08)', background: '#f8f8f8' }}>
                      <Eye size={11} style={{ color: '#6b7280' }} />
                      <span className="text-[10px] font-mono" style={{ color: '#9ca3af' }}>/learn/{form.seo_slug}</span>
                    </div>
                    <iframe
                      key={form.seo_slug}
                      src={`/learn/${form.seo_slug}`}
                      className="flex-1 w-full border-0"
                      title="Live Preview"
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── SEO & Meta Tab ───────────────────────────────────────── */}
          {seoTab === 'seo' && (
            <div className="flex-1 overflow-y-auto p-6">
              <div className="max-w-2xl mx-auto space-y-6">

                {/* ── AI SEO + GEO Generator ─────────────────────────────── */}
                <div className="rounded-xl p-4 border" style={{ background: 'rgba(139,92,246,0.06)', borderColor: 'rgba(139,92,246,0.20)' }}>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <Sparkles size={13} style={{ color: '#a78bfa' }} />
                      <span className="text-xs font-semibold" style={{ color: '#c4b0f0' }}>AI SEO &amp; GEO Generator</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(139,92,246,0.18)', color: '#a78bfa' }}>Beta</span>
                    </div>
                    <button
                      onClick={handleGenerateSeoMeta}
                      disabled={seoGenerating}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-opacity disabled:opacity-50"
                      style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)', color: '#fff' }}>
                      {seoGenerating
                        ? <><Loader2 size={11} className="animate-spin" /> Generating…</>
                        : <><Zap size={11} /> Generate Title + Meta</>}
                    </button>
                  </div>
                  <p className="text-[11px] leading-relaxed" style={{ color: 'rgba(255,255,255,0.35)' }}>
                    Generates a 55–65 char SEO title + 148–158 char GEO-rich meta description optimised for Google ranking and AI citation (Perplexity, ChatGPT search). Uses your current title, keyword, content, and linked syllabus scope as context.
                  </p>

                  {/* Result card */}
                  {seoResult && (
                    <div className="mt-4 space-y-3 pt-4 border-t" style={{ borderColor: 'rgba(139,92,246,0.18)' }}>
                      {/* SEO Title */}
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: 'rgba(255,255,255,0.35)' }}>SEO Title</span>
                          <span className="text-[10px]" style={{ color: seoResult.char_counts?.title > 65 ? '#dc2626' : '#16a34a' }}>
                            {seoResult.char_counts?.title || seoResult.seo_title?.length || 0} / 65 chars
                          </span>
                        </div>
                        <p className="text-sm font-medium px-3 py-2 rounded-lg" style={{ background: 'rgba(255,255,255,0.05)', color: '#e8e8e8' }}>
                          {seoResult.seo_title}
                        </p>
                      </div>
                      {/* Meta Description */}
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: 'rgba(255,255,255,0.35)' }}>Meta Description</span>
                          <span className="text-[10px]" style={{ color: seoResult.char_counts?.meta > 160 ? '#dc2626' : seoResult.char_counts?.meta >= 140 ? '#16a34a' : '#f59e0b' }}>
                            {seoResult.char_counts?.meta || seoResult.meta_description?.length || 0} / 160 chars
                          </span>
                        </div>
                        <p className="text-xs leading-relaxed px-3 py-2 rounded-lg" style={{ background: 'rgba(255,255,255,0.05)', color: 'rgba(232,232,232,0.75)' }}>
                          {seoResult.meta_description}
                        </p>
                      </div>
                      {/* Primary Keyword */}
                      <div>
                        <span className="text-[10px] font-semibold uppercase tracking-wide block mb-1" style={{ color: 'rgba(255,255,255,0.35)' }}>Primary Keyword</span>
                        <p className="text-xs font-mono px-3 py-1.5 rounded-lg" style={{ background: 'rgba(255,255,255,0.05)', color: '#a78bfa' }}>
                          {seoResult.primary_keyword}
                        </p>
                      </div>
                      {/* GEO authority phrases */}
                      {seoResult.geo_phrases?.length > 0 && (
                        <div>
                          <span className="text-[10px] font-semibold uppercase tracking-wide block mb-1.5" style={{ color: 'rgba(255,255,255,0.35)' }}>GEO Authority Phrases</span>
                          <div className="flex flex-wrap gap-2">
                            {seoResult.geo_phrases.map((p, i) => (
                              <span key={i} className="text-[10px] px-2 py-1 rounded-lg" style={{ background: 'rgba(16,185,129,0.10)', color: '#34d399', border: '1px solid rgba(16,185,129,0.18)' }}>
                                {p}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {/* SEO Tags preview */}
                      {seoResult.seo_tags && (
                        <div>
                          <span className="text-[10px] font-semibold uppercase tracking-wide block mb-1.5" style={{ color: 'rgba(255,255,255,0.35)' }}>SEO Tags</span>
                          <div className="flex flex-wrap gap-1.5">
                            {seoResult.seo_tags.split(',').map(t => t.trim()).filter(Boolean).map((t, i) => (
                              <span key={i} className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.45)' }}>
                                {t}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {/* Apply button */}
                      <div className="flex gap-2 pt-1">
                        <button onClick={applySeoResult}
                          className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold"
                          style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)', color: '#fff' }}>
                          <CheckCircle size={12} /> Apply All to Page
                        </button>
                        <button onClick={() => setSeoResult(null)}
                          className="px-3 py-2 rounded-lg text-xs"
                          style={{ background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.40)' }}>
                          Dismiss
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* Google SERP preview */}
                <div>
                  <p className="text-xs font-medium mb-2" style={{ color: 'rgba(255,255,255,0.40)' }}>Google Search Preview</p>
                  <div className="rounded-xl p-4" style={{ background: '#ffffff' }}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <div className="w-5 h-5 rounded-full flex-shrink-0" style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)' }} />
                      <div className="min-w-0">
                        <p className="text-xs font-medium truncate" style={{ color: '#202124' }}>syrabit.ai</p>
                        <p className="text-[10px] truncate" style={{ color: '#4d5156' }}>https://syrabit.ai/{form.seo_slug || 'your-slug-here'}</p>
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
                          <div className="h-1 rounded-full transition-all" style={{
                            width: `${Math.min(100, (form.meta_description.length / 160) * 100)}%`,
                            background: form.meta_description.length > 160 ? '#dc2626' : form.meta_description.length > 110 ? '#16a34a' : '#f59e0b',
                          }} />
                        </div>
                        <span className="text-[10px] flex-shrink-0" style={{ color: form.meta_description.length > 160 ? '#dc2626' : '#6b7280' }}>
                          {form.meta_description.length}/160
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Perplexity AI Citation Simulator */}
                <div>
                  <p className="text-xs font-medium mb-2" style={{ color: 'rgba(255,255,255,0.40)' }}>Perplexity AI Citation Preview</p>
                  <div className="rounded-xl p-4" style={{ background: '#0d1117', border: '1px solid rgba(139,92,246,0.25)' }}>
                    <div className="flex items-start gap-3">
                      <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5" style={{ background: 'linear-gradient(135deg,#6366f1,#8b5cf6)' }}>
                        <Sparkles size={11} className="text-white" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-semibold mb-1" style={{ color: '#e2e8f0' }}>
                          {form.primary_keyword
                            ? `${form.primary_keyword} — AHSEC Study Guide`
                            : form.title || 'Your document title will appear here as the AI answer heading'}
                        </p>
                        <p className="text-[11px] leading-relaxed mb-2" style={{ color: '#94a3b8' }}>
                          {form.meta_description
                            ? form.meta_description.slice(0, 180)
                            : 'Your meta description appears here as the AI-generated answer excerpt. Perplexity cites pages with clear educational intent and board-aligned content.'}
                        </p>
                        <div className="flex items-center gap-2 flex-wrap">
                          <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10px]" style={{ background: 'rgba(139,92,246,0.15)', color: '#a78bfa' }}>
                            <Globe size={9} />
                            syrabit.ai/{form.seo_slug || 'slug'}
                          </div>
                          {form.seo_tags && form.seo_tags.split(',').slice(0, 3).map(tag => (
                            <span key={tag} className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.35)' }}>
                              {tag.trim()}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="flex-shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: 'rgba(139,92,246,0.20)', color: '#a78bfa' }}>
                        [1]
                      </div>
                    </div>
                  </div>
                </div>

                {/* Canonical link if linked */}
                {(editDoc?.canonical_url || editDoc?.linked_scope) && (
                  <div className="p-3 rounded-xl flex items-center gap-3" style={{ background: 'rgba(16,185,129,0.07)', border: '1px solid rgba(16,185,129,0.18)' }}>
                    <Link2 size={14} style={{ color: '#34d399', flexShrink: 0 }} />
                    <div className="flex-1 min-w-0">
                      <p className="text-[10px] font-medium mb-0.5" style={{ color: '#34d399' }}>Canonical URL</p>
                      <p className="text-xs font-mono truncate" style={{ color: 'rgba(255,255,255,0.55)' }}>
                        {'<link rel="canonical" href="' + (editDoc.canonical_url || `/${editDoc.linked_scope?.replace(/\//g, '/')}`) + '" />'}
                      </p>
                    </div>
                    <button onClick={() => { navigator.clipboard.writeText(editDoc.canonical_url || ''); toast.success('Copied'); }} style={{ color: 'rgba(255,255,255,0.30)' }}>
                      <Copy size={12} />
                    </button>
                  </div>
                )}

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
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs" style={{ color: 'rgba(255,255,255,0.45)' }}>Primary Keyword</label>
                    <button onClick={handleAutoKeyword}
                      className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-lg border"
                      style={{ color: '#a78bfa', borderColor: 'rgba(167,139,250,0.25)', background: 'rgba(167,139,250,0.08)' }}>
                      <Zap size={9} /> Auto-fill
                    </button>
                  </div>
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
                      <button key={s} onClick={() => setForm(f => ({ ...f, schema_type: s }))}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium border transition-all"
                        style={form.schema_type === s
                          ? { borderColor: '#9575e0', background: 'rgba(149,117,224,0.18)', color: '#c4b0f0' }
                          : { borderColor: 'rgba(255,255,255,0.10)', background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.40)' }}>
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

          {/* ── GEO Tags Tab ─────────────────────────────────────────── */}
          {seoTab === 'geo' && (
            <div className="flex-1 overflow-y-auto p-6">
              <div className="max-w-2xl mx-auto space-y-5">

                {/* Link to Syllabus Scope */}
                <div className="p-4 rounded-xl" style={{ background: 'rgba(149,117,224,0.06)', border: '1px solid rgba(149,117,224,0.14)' }}>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <Link2 size={13} style={{ color: '#9575e0' }} />
                      <p className="text-xs font-semibold" style={{ color: '#c4b0f0' }}>Link to Syllabus Scope</p>
                    </div>
                    {linkedScopeLabel && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'rgba(16,185,129,0.15)', color: '#34d399' }}>
                        <CheckCircle size={9} className="inline mr-1" />{linkedScopeLabel}
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] mb-3" style={{ color: 'rgba(255,255,255,0.35)' }}>
                    Linking populates canonical URL and GEO tags automatically from the scope hierarchy.
                  </p>
                  <button onClick={() => setScopePickerOpen(v => !v)}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border"
                    style={{ borderColor: 'rgba(149,117,224,0.30)', color: '#c4b0f0', background: 'rgba(149,117,224,0.10)' }}>
                    {scopePickerOpen ? <ChevronDown size={11} /> : <ChevronRightIcon size={11} />}
                    {scopePickerOpen ? 'Close Picker' : 'Choose Scope'}
                  </button>
                  {scopePickerOpen && (
                    <div className="mt-3 flex items-end gap-2 flex-wrap pt-3" style={{ borderTop: '1px solid rgba(149,117,224,0.12)' }}>
                      <div>
                        <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.30)' }}>Board</p>
                        <select value={spBoard} onChange={e => setSpBoard(e.target.value)} style={selectStyle}>
                          <option value="">— Board —</option>
                          {spBoards.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                        </select>
                      </div>
                      <div>
                        <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.30)' }}>Class</p>
                        <select value={spClass} onChange={e => setSpClass(e.target.value)} disabled={!spBoard} style={selectStyle}>
                          <option value="">— Class —</option>
                          {spClasses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                      </div>
                      <div>
                        <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.30)' }}>Stream</p>
                        <select value={spStream} onChange={e => setSpStream(e.target.value)} disabled={!spClass} style={selectStyle}>
                          <option value="">— Stream —</option>
                          {spStreams.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                        </select>
                      </div>
                      <div>
                        <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.30)' }}>Subject</p>
                        <select value={spSubject} onChange={e => setSpSubject(e.target.value)} disabled={!spStream} style={selectStyle}>
                          <option value="">— Subject —</option>
                          {spSubjects.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                        </select>
                      </div>
                      <button onClick={handleLinkSyllabus} disabled={linkingScope || !editDoc || !spBoard || !spClass}
                        className="h-8 px-3 rounded-lg flex items-center gap-1.5 text-xs font-medium disabled:opacity-40"
                        style={{ background: '#9575e0', color: 'white' }}>
                        {linkingScope ? <Loader2 size={11} className="animate-spin" /> : <Link2 size={11} />}
                        Link Scope
                      </button>
                    </div>
                  )}
                </div>

                {/* GEO Tags field */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs" style={{ color: 'rgba(255,255,255,0.45)' }}>GEO Tags <span style={{ color: 'rgba(255,255,255,0.20)' }}>(board/class/subject/topic)</span></label>
                    <button onClick={handleAutoGeoTags}
                      className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-lg border"
                      style={{ color: '#a78bfa', borderColor: 'rgba(167,139,250,0.25)', background: 'rgba(167,139,250,0.08)' }}>
                      <Zap size={9} /> Auto-extract
                    </button>
                  </div>
                  <input
                    value={form.geo_tags}
                    onChange={e => setForm(f => ({ ...f, geo_tags: e.target.value }))}
                    placeholder="ahsec/class-12/pcm/physics"
                    className="w-full h-10 px-4 rounded-xl text-sm font-mono outline-none"
                    style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                  />
                </div>

                {/* Authority phrase chips */}
                {form.geo_tags && (
                  <div>
                    <p className="text-xs font-medium mb-2" style={{ color: 'rgba(255,255,255,0.35)' }}>Authority Phrases</p>
                    <div className="flex flex-wrap gap-2">
                      {[
                        form.title && `${form.title}`,
                        form.geo_tags && `${form.geo_tags} Study Guide`,
                        form.primary_keyword && form.primary_keyword,
                        form.geo_tags && `${form.geo_tags} Board Exam`,
                        form.geo_tags && `${form.geo_tags} Notes`,
                      ].filter(Boolean).map((phrase, i) => (
                        <span key={i} className="flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-medium"
                          style={{ background: 'rgba(16,185,129,0.10)', border: '1px solid rgba(16,185,129,0.20)', color: '#34d399' }}>
                          <CheckCircle size={9} /> {phrase}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* GEO presets */}
                <div className="p-4 rounded-xl text-xs space-y-1" style={{ background: 'rgba(149,117,224,0.06)', border: '1px solid rgba(149,117,224,0.12)', color: 'rgba(232,232,232,0.55)' }}>
                  <p className="font-semibold mb-2" style={{ color: '#c4b0f0' }}>GEO Presets</p>
                  {['ahsec/class-11/arts', 'ahsec/class-12/science', 'ahsec/class-12/commerce', 'du/degree/bcom', 'du/degree/ba'].map(preset => (
                    <button key={preset} onClick={() => setForm(f => ({ ...f, geo_tags: preset }))}
                      className="block w-full text-left py-1.5 px-2.5 rounded-lg font-mono text-xs transition-colors"
                      style={{ color: 'rgba(232,232,232,0.50)' }}
                      onMouseEnter={e => { e.currentTarget.style.background = 'rgba(149,117,224,0.10)'; e.currentTarget.style.color = '#c4b0f0'; }}
                      onMouseLeave={e => { e.currentTarget.style.background = ''; e.currentTarget.style.color = 'rgba(232,232,232,0.50)'; }}>
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
