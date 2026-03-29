import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Search, Plus, Save, Trash2, X, BookOpen, Loader2,
  FolderPlus, FilePlus, Edit2, FileText, Book,
  CheckCircle, Layers, Eye, Upload, Paperclip, Link2, BarChart3, Sparkles, RefreshCw,
  ChevronRight, ChevronLeft, ChevronDown, GraduationCap, Building2, GitBranch, ArrowLeft,
  Globe, LayoutTemplate, Wand2
} from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { TEMPLATES } from '@/utils/editorTemplates';
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


const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

function authHeaders(token) {
  const isRealJwt = token && token.split('.').length === 3;
  return { headers: isRealJwt ? { Authorization: `Bearer ${token}` } : {}, withCredentials: true };
}

function ContentViewerPopup({ item, onClose }) {
  if (!item) return null;
  const wordCount = (item.content || '').trim().split(/\s+/).filter(Boolean).length;
  const readMin = Math.max(1, Math.ceil(wordCount / 200));
  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
      <div
        className="relative flex flex-col rounded-2xl overflow-hidden shadow-2xl"
        style={{ width: '90vw', maxWidth: '860px', height: '92vh', background: '#ffffff', border: '1px solid #e5e7eb' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b" style={{ borderColor: '#e5e7eb', background: '#f9fafb' }}>
          <div className="flex items-center gap-3 min-w-0">
            <Book size={18} className="text-violet-600 flex-shrink-0" />
            <div className="min-w-0">
              <h3 className="text-base font-bold truncate" style={{ color: '#111827' }}>{item.title || 'Untitled'}</h3>
              <p className="text-xs mt-0.5" style={{ color: '#9ca3af' }}>
                {wordCount > 0 ? `${wordCount.toLocaleString()} words · ${readMin} min read` : 'No content yet'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-gray-100 transition-colors"
            style={{ color: '#6b7280' }}
            data-testid="close-viewer"
          >
            <X size={16} />
          </button>
        </div>

        {/* Blog-style content body */}
        <div className="flex-1 overflow-y-auto" style={{ background: '#ffffff' }}>
          <div className="blog-view-tab">
            <div className="px-8 py-10 max-w-[740px] mx-auto">
              {item.description && (
                <p className="text-base italic mb-8 pb-6 border-b" style={{ color: '#6b7280', borderColor: '#e5e7eb' }}>
                  {item.description}
                </p>
              )}
              {item.content ? (
                <div className="learn-article max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {item.content}
                  </ReactMarkdown>
                </div>
              ) : (
                <p className="text-center py-16 italic" style={{ color: '#9ca3af' }}>No content available — generate notes using the ✨ button.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function InlineCreator({ placeholder, onCreate, icon: Icon, color = 'violet' }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [saving, setSaving] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => { if (open && inputRef.current) inputRef.current.focus(); }, [open]);

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className={`w-full p-3 rounded-xl border-2 border-dashed border-white/10 hover:border-${color}-500/40 text-white/40 hover:text-${color}-400 flex items-center gap-2 text-sm transition-colors`} data-testid={`add-${placeholder.toLowerCase()}`}>
        <Plus size={16} /> Add {placeholder}
      </button>
    );
  }

  const submit = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await onCreate(name.trim(), desc.trim());
      setName(''); setDesc(''); setOpen(false);
    } catch (e) {
      toast.error(e.response?.data?.detail || `Failed to create ${placeholder}`);
    } finally { setSaving(false); }
  };

  return (
    <div className="p-3 rounded-xl border border-white/10 bg-white/[0.02] space-y-2">
      <div className="flex items-center gap-2">
        {Icon && <Icon size={16} className={`text-${color}-400`} />}
        <input
          ref={inputRef}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder={`${placeholder} name...`}
          className="flex-1 h-9 px-3 rounded-lg text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
        />
      </div>
      <input
        value={desc}
        onChange={(e) => setDesc(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
        placeholder="Description (optional)"
        className="w-full h-9 px-3 rounded-lg text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
      />
      <div className="flex gap-2">
        <button onClick={() => { setOpen(false); setName(''); setDesc(''); }} className="flex-1 h-8 rounded-lg bg-white/5 hover:bg-white/10 text-white/60 text-xs">Cancel</button>
        <button onClick={submit} disabled={saving || !name.trim()} className={`flex-1 h-8 rounded-lg bg-${color}-600 hover:bg-${color}-500 text-white text-xs font-medium disabled:opacity-40 flex items-center justify-center gap-1`}>
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
          {saving ? 'Creating...' : 'Create'}
        </button>
      </div>
    </div>
  );
}

export default function AdminContentEditor({ adminToken, onNavigate, hubContext, onHubContext }) {
  const [boards, setBoards] = useState([]);
  const [classes, setClasses] = useState([]);
  const [streams, setStreams] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [chapters, setChapters] = useState([]);

  const [selBoard, setSelBoard] = useState(null);
  const [selClass, setSelClass] = useState(null);
  const [selStream, setSelStream] = useState(null);
  const [selSubject, setSelSubject] = useState(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [viewerItem, setViewerItem] = useState(null);

  const [editView, setEditView] = useState(null);
  const [contentForm, setContentForm] = useState({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: 1 });
  const [editTarget, setEditTarget] = useState(null);
  const [saving, setSaving] = useState(false);
  const [contentMode, setContentMode] = useState('preview');
  const [chapterStats, setChapterStats] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [aiParsing, setAiParsing] = useState(false);
  const [thumbnailLoading, setThumbnailLoading] = useState(false);
  const [aiThumbLoading, setAiThumbLoading]     = useState(false);
  const [thumbVariants, setThumbVariants]       = useState([]);
  const [thumbAnalysis, setThumbAnalysis]       = useState(null);
  const [selectedThumbVariant, setSelectedThumbVariant] = useState(0);
  const [generatingNotes, setGeneratingNotes] = useState(new Set());
  const [bulkGenerating, setBulkGenerating] = useState(false);
  const fileInputRef = useRef(null);
  const thumbnailInputRef = useRef(null);
  const contentTextareaRef = useRef(null);
  const editorRef = useRef(null);

  const [publishingBlog, setPublishingBlog]     = useState(false);
  const [selectedChapters, setSelectedChapters] = useState(new Set());
  const [bulkMerging, setBulkMerging]           = useState(false);
  const [showPreview, setShowPreview]           = useState(false);
  const [mergedSubjectIds, setMergedSubjectIds] = useState(new Set());
  const [editorKey, setEditorKey]               = useState(0);

  const CONTENT_TYPES = [
    { value: 'notes', label: 'Notes', color: 'violet' },
    { value: 'pyq', label: 'PYQ', color: 'amber' },
    { value: 'formula', label: 'Formula Sheet', color: 'pink' },
    { value: 'summary', label: 'Summary', color: 'emerald' },
    { value: 'solution', label: 'Solution', color: 'blue' },
    { value: 'reference', label: 'Reference', color: 'slate' },
  ];

  const autoSlug = (title) => title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');

  const loadChapterStats = useCallback(async (chapterId) => {
    try {
      const res = await axios.get(`${API}/admin/content/chapters/${chapterId}/stats`, authHeaders(adminToken));
      setChapterStats(res.data);
    } catch { setChapterStats(null); }
  }, [adminToken]);

  const handleFileAttach = useCallback(async (chapterId) => {
    const file = fileInputRef.current?.files?.[0];
    if (!file || !chapterId) return;
    const MAX_SIZE = 10 * 1024 * 1024;
    if (file.size > MAX_SIZE) { toast.error('File too large (max 10 MB)'); return; }
    const allowed = ['pdf', 'txt', 'md'];
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (!allowed.includes(ext)) { toast.error(`Only ${allowed.join(', ')} files allowed`); return; }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await axios.post(`${API}/admin/content/chapters/${chapterId}/attach-file`, formData, { ...authHeaders(adminToken), headers: { ...authHeaders(adminToken).headers, 'Content-Type': 'multipart/form-data' } });
      toast.success(`File attached (${res.data.text_extracted} chars extracted)`);
      refreshChapters(selSubject);
      if (chapterId) loadChapterStats(chapterId);
      const freshChapter = await axios.get(`${API}/admin/content/chapters/${selSubject}`, authHeaders(adminToken));
      const updated = (freshChapter.data || []).find(c => c.id === chapterId);
      if (updated) setContentForm(f => ({ ...f, content: updated.content || f.content }));
    } catch (e) {
      toast.error(e.response?.data?.detail || 'File upload failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, [adminToken, selSubject, loadChapterStats]);

  const handleAiParse = useCallback(async () => {
    if (!contentForm.content.trim()) return toast.error('Add content first');
    setAiParsing(true);
    try {
      const res = await axios.post(`${API}/admin/studio/parse`, {
        raw_text: contentForm.content,
        subject: subjects.find(s => s.id === selSubject)?.name || '',
        chapter: contentForm.title || '',
      }, authHeaders(adminToken));
      const blocks = res.data.blocks || [];
      if (blocks.length === 0) return toast.error('AI could not parse content');
      const formatted = blocks.map(b => `## ${b.title}\n\n${b.content}`).join('\n\n---\n\n');
      setContentForm(f => ({ ...f, content: formatted }));
      toast.success(`AI structured ${blocks.length} blocks`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'AI parsing failed');
    } finally { setAiParsing(false); }
  }, [contentForm.content, contentForm.title, selSubject, subjects]);

  const formatText = useCallback((type) => {
    const ta = contentTextareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end   = ta.selectionEnd;
    const selected = contentForm.content.slice(start, end);
    const before   = contentForm.content.slice(0, start);
    const after    = contentForm.content.slice(end);

    const lineStart = before.lastIndexOf('\n') + 1;
    const linePrefix = before.slice(lineStart);

    let newContent = contentForm.content;
    let newCursor  = end;

    if (type === 'h1' || type === 'h2' || type === 'h3') {
      const prefix = type === 'h1' ? '# ' : type === 'h2' ? '## ' : '### ';
      const cleanLine = linePrefix.replace(/^#+\s/, '');
      newContent = before.slice(0, lineStart) + prefix + cleanLine + after;
      newCursor  = lineStart + prefix.length + cleanLine.length;
    } else if (type === 'bold') {
      newContent = before + `**${selected || 'bold text'}**` + after;
      newCursor  = start + 2 + (selected || 'bold text').length + 2;
    } else if (type === 'italic') {
      newContent = before + `*${selected || 'italic text'}*` + after;
      newCursor  = start + 1 + (selected || 'italic text').length + 1;
    } else if (type === 'ul') {
      const lines = (selected || 'List item').split('\n').map(l => `- ${l}`).join('\n');
      newContent = before + '\n' + lines + '\n' + after;
      newCursor  = start + 1 + lines.length;
    } else if (type === 'ol') {
      const lines = (selected || 'List item').split('\n').map((l, i) => `${i + 1}. ${l}`).join('\n');
      newContent = before + '\n' + lines + '\n' + after;
      newCursor  = start + 1 + lines.length;
    } else if (type === 'hr') {
      newContent = before + '\n\n---\n\n' + after;
      newCursor  = start + 6;
    }

    setContentForm(f => ({ ...f, content: newContent }));
    setTimeout(() => { ta.focus(); ta.setSelectionRange(newCursor, newCursor); }, 0);
  }, [contentForm.content]);

  const subjectData = subjects.find(s => s.id === selSubject);

  const handlePublishAsBlog = useCallback(async (subjectId, subjectName) => {
    if (!subjectId) return;
    setPublishingBlog(true);
    try {
      const res = await axios.post(`${API}/admin/cms/merge/${subjectId}`, {}, authHeaders(adminToken));
      const mergedMd = res.data?.merged_md || res.data?.content || '';
      const prefill = {
        subjectId,
        title: subjectName || res.data?.title || subjectId,
        content: mergedMd,
        seo_slug: (subjectName || subjectId).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+/g, '-'),
        meta_description: `Complete ${subjectName || subjectId} notes, chapters, and PYQ for AssamBoard students on Syrabit.`,
        timestamp: Date.now(),
      };
      localStorage.setItem('syrabit_cms_prefill', JSON.stringify(prefill));
      setMergedSubjectIds(s => new Set([...s, subjectId]));
      toast.success(`"${subjectName}" merged — opening CMS Editor`);
      onNavigate?.('cms');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Merge failed');
    } finally {
      setPublishingBlog(false);
    }
  }, [adminToken, onNavigate]);

  const handleBulkMerge = useCallback(async () => {
    if (!selSubject || selectedChapters.size === 0) return;
    setBulkMerging(true);
    try {
      const res = await axios.post(`${API}/admin/cms/merge/${selSubject}`, {}, authHeaders(adminToken));
      const mergedMd = res.data?.merged_md || res.data?.content || '';
      const name = subjectData?.name || selSubject;
      const prefill = {
        subjectId: selSubject,
        title: name,
        content: mergedMd,
        seo_slug: name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+/g, '-'),
        meta_description: `Complete ${name} notes, chapters, and PYQ for AssamBoard students on Syrabit.`,
        timestamp: Date.now(),
      };
      localStorage.setItem('syrabit_cms_prefill', JSON.stringify(prefill));
      setMergedSubjectIds(s => new Set([...s, selSubject]));
      setSelectedChapters(new Set());
      toast.success(`${selectedChapters.size} chapters merged — opening CMS Editor`);
      onNavigate?.('cms');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Bulk merge failed');
    } finally {
      setBulkMerging(false);
    }
  }, [adminToken, selSubject, subjectData, selectedChapters, onNavigate]);

  const load = useCallback(async (bustCache = false) => {
    try {
      const nc = bustCache ? '?nocache=1' : '';
      const [b, c, s, sub] = await Promise.all([
        axios.get(`${API}/content/boards${nc}`),
        axios.get(`${API}/content/classes${nc}`),
        axios.get(`${API}/content/streams${nc}`),
        axios.get(`${API}/content/subjects${nc}`),
      ]);
      setBoards(b.data || []);
      setClasses(c.data || []);
      setStreams(s.data || []);
      setSubjects(sub.data || []);
    } catch { toast.error('Failed to load content data'); }
  }, []);

  useEffect(() => { load(true); }, [load]);

  // Read CMS → Editor handoff prefill on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem('syrabit_editor_prefill');
      if (!raw) return;
      const pf = JSON.parse(raw);
      if (Date.now() - (pf.timestamp || 0) > 10 * 60 * 1000) {
        localStorage.removeItem('syrabit_editor_prefill');
        return;
      }
      localStorage.removeItem('syrabit_editor_prefill');
      setContentForm(f => ({
        ...f,
        title:   pf.title || f.title || '',
        content: pf.content || f.content || '',
      }));
      setEditView('new-chapter');
      toast.success(`Pre-filled from CMS Doc "${pf.title || 'Untitled'}" — select a subject and save`);
    } catch {}
  }, []);

  // Pre-fill selectors from hub context (only if nothing selected yet and data is loaded)
  useEffect(() => {
    if (!hubContext?.subjectId || !subjects.length || selSubject) return;
    const sub = subjects.find(s => s.id === hubContext.subjectId);
    if (!sub) return;
    setSelBoard(hubContext.boardId   || null);
    setSelClass(hubContext.classId   || null);
    setSelStream(hubContext.streamId || null);
    setSelSubject(sub.id);
  }, [hubContext?.subjectId, subjects]);

  // Broadcast subject context back to hub when user picks a subject
  useEffect(() => {
    if (!onHubContext || !selSubject) return;
    const sub  = subjects.find(s => s.id === selSubject);
    const str  = streams.find(s => s.id === selStream);
    const cls  = classes.find(c => c.id === selClass);
    const brd  = boards.find(b => b.id === selBoard);
    onHubContext({
      boardId: selBoard || '', boardName: brd?.name || '',
      classId: selClass || '', className: cls?.name || '',
      streamId: selStream || '', streamName: str?.name || '',
      subjectId: selSubject, subjectName: sub?.name || '',
    });
  }, [selSubject]);

  const refreshChapters = (subjectId) => {
    axios.get(`${API}/admin/content/chapters/${subjectId}`, authHeaders(adminToken))
      .then(r => setChapters(r.data || []))
      .catch(() => toast.error('Could not reload chapter list'));
  };

  useEffect(() => {
    if (selSubject) refreshChapters(selSubject);
  }, [selSubject]);

  const filteredClasses = selBoard ? classes.filter(c => c.board_id === selBoard) : [];
  const filteredStreams = selClass ? streams.filter(s => s.class_id === selClass) : [];
  const filteredSubjects = selStream ? subjects.filter(s => s.stream_id === selStream) : subjects;

  const boardData = boards.find(b => b.id === selBoard);
  const classData = classes.find(c => c.id === selClass);
  const streamData = streams.find(s => s.id === selStream);

  const searchFiltered = searchQuery
    ? subjects.filter(s => s.name?.toLowerCase().includes(searchQuery.toLowerCase()) || s.description?.toLowerCase().includes(searchQuery.toLowerCase()))
    : null;

  const handleCreateBoard = async (name, desc) => {
    await axios.post(`${API}/admin/content/boards`, { name, description: desc }, authHeaders(adminToken));
    await load(true);
    toast.success('Board created');
  };

  const handleCreateClass = async (name, desc) => {
    if (!selBoard) return toast.error('Select a board first');
    await axios.post(`${API}/admin/content/classes`, { board_id: selBoard, name, description: desc }, authHeaders(adminToken));
    await load(true);
    toast.success('Class created');
  };

  const handleCreateStream = async (name, desc) => {
    if (!selClass) return toast.error('Select a class first');
    await axios.post(`${API}/admin/content/streams`, { class_id: selClass, name, description: desc }, authHeaders(adminToken));
    await load(true);
    toast.success('Stream created');
  };

  const handleCreateSubject = async (name, desc) => {
    if (!selStream) return toast.error('Select a stream first');
    await axios.post(`${API}/admin/content/subjects`, {
      stream_id: selStream, name, description: desc, tags: '', status: 'published'
    }, authHeaders(adminToken));
    await load(true);
    toast.success('Subject created');
  };

  const handleDelete = async (type, id) => {
    if (!confirm(`Delete this ${type}?`)) return;
    try {
      await axios.delete(`${API}/admin/content/${type}s/${id}`, authHeaders(adminToken));
      if (type === 'board' && selBoard === id) { setSelBoard(null); setSelClass(null); setSelStream(null); setSelSubject(null); }
      if (type === 'classe' && selClass === id) { setSelClass(null); setSelStream(null); setSelSubject(null); }
      if (type === 'stream' && selStream === id) { setSelStream(null); setSelSubject(null); }
      if (type === 'subject' && selSubject === id) setSelSubject(null);
      await load(true);
      toast.success(`${type} deleted`);
    } catch { toast.error(`Failed to delete ${type}`); }
  };

  const handleUploadThumbnail = async (file) => {
    if (!file || !selSubject) return;
    setThumbnailLoading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const h = authHeaders(adminToken);
      const res = await axios.post(
        `${API}/admin/content/subjects/${selSubject}/thumbnail`,
        form,
        { ...h, headers: { ...h.headers, 'Content-Type': 'multipart/form-data' } },
      );
      toast.success('Thumbnail uploaded');
      await load(true);
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Failed to upload thumbnail');
    } finally {
      setThumbnailLoading(false);
      if (thumbnailInputRef.current) thumbnailInputRef.current.value = '';
    }
  };

  const handleGenerateAiThumbnails = useCallback(async (sourceFile = null) => {
    if (!selSubject) return;
    setAiThumbLoading(true);
    setThumbVariants([]);
    try {
      const form = new FormData();
      form.append('subject_id', selSubject);
      if (sourceFile) form.append('file', sourceFile);
      const h = authHeaders(adminToken);
      const res = await axios.post(
        `${API}/admin/thumbnail/generate`,
        form,
        { ...h, headers: { ...h.headers, 'Content-Type': 'multipart/form-data' } },
      );
      setThumbVariants(res.data.variants || []);
      setThumbAnalysis(res.data.analysis || null);
      setSelectedThumbVariant(res.data.auto_selected ?? 0);
      if (res.data.original_url) await load(true);
      toast.success('AI variants generated — pick your favourite!');
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'AI thumbnail generation failed');
    } finally {
      setAiThumbLoading(false);
    }
  }, [selSubject, adminToken]);

  const handleApplyVariant = useCallback(async (variantUrl) => {
    if (!selSubject || !variantUrl) return;
    try {
      await axios.post(
        `${API}/admin/thumbnail/apply`,
        { subject_id: selSubject, thumbnail_url: variantUrl },
        authHeaders(adminToken),
      );
      await load(true);
      toast.success('Variant applied as thumbnail!');
    } catch {
      toast.error('Failed to apply variant');
    }
  }, [selSubject, adminToken]);

  const handleClearThumbnail = async () => {
    if (!selSubject) return;
    try {
      await axios.patch(
        `${API}/admin/content/subjects/${selSubject}`,
        { thumbnail_url: '' },
        authHeaders(adminToken),
      );
      toast.success('Thumbnail removed');
      await load(true);
    } catch { toast.error('Failed to clear thumbnail'); }
  };

  const handleCreateChapter = async () => {
    if (!selSubject || !contentForm.title) return;
    setSaving(true);
    try {
      const slug = contentForm.slug || autoSlug(contentForm.title);
      await axios.post(`${API}/admin/content/chapters`, { subject_id: selSubject, title: contentForm.title, slug, description: contentForm.description, content: contentForm.content, content_type: contentForm.content_type, order: contentForm.order, status: 'published' }, authHeaders(adminToken));
      toast.success('Chapter created');
      setEditView(null);
      setContentForm({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: 1 });
      setChapterStats(null);
      refreshChapters(selSubject);
    } catch { toast.error('Failed to create chapter'); }
    finally { setSaving(false); }
  };

  const handleUpdateChapter = async () => {
    if (!editTarget || !contentForm.title) return;
    setSaving(true);
    try {
      const slug = contentForm.slug || autoSlug(contentForm.title);
      await axios.patch(`${API}/admin/content/chapters/${editTarget.id}`, { title: contentForm.title, slug, description: contentForm.description, content: contentForm.content, content_type: contentForm.content_type, order: contentForm.order }, authHeaders(adminToken));
      toast.success('Chapter updated');
      setEditView(null); setEditTarget(null);
      setContentForm({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: 1 });
      setChapterStats(null);
      refreshChapters(selSubject);
    } catch { toast.error('Failed to update'); }
    finally { setSaving(false); }
  };

  const handleDeleteChapter = async (id) => {
    if (!confirm('Delete this chapter?')) return;
    try {
      await axios.delete(`${API}/admin/content/chapters/${id}`, authHeaders(adminToken));
      setChapters(p => p.filter(c => c.id !== id));
      toast.success('Chapter deleted');
    } catch { toast.error('Failed to delete'); }
  };

  const handleGenerateNotes = async (chapterId, chapterTitle) => {
    setGeneratingNotes(prev => new Set([...prev, chapterId]));
    try {
      const res = await axios.post(`${API}/admin/content/chapters/${chapterId}/generate-notes`, {}, authHeaders(adminToken));
      const generated = res.data?.content;
      if (generated) {
        setChapters(prev => prev.map(ch => ch.id === chapterId ? { ...ch, content: generated, content_type: 'notes', notes_generated: true } : ch));
        toast.success(`Notes generated for "${chapterTitle}"`);
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || `Failed to generate notes for "${chapterTitle}"`);
    } finally {
      setGeneratingNotes(prev => { const next = new Set(prev); next.delete(chapterId); return next; });
    }
  };

  const handleGenerateAllNotes = async () => {
    if (!selSubject) return;
    const subjectName = subjects.find(s => s.id === selSubject)?.name || selSubject;
    if (!confirm(`Generate AI notes for all ${chapters.length} chapters in "${subjectName}"? This may take a moment.`)) return;
    setBulkGenerating(true);
    try {
      const res = await axios.post(`${API}/admin/subjects/${selSubject}/generate-notes-bulk`, {}, authHeaders(adminToken));
      const data = res.data;
      const ok = data?.generated || 0;
      toast.success(`Generated notes for ${ok} of ${data?.total || chapters.length} chapters`);
      // Refresh chapters to pull updated content
      const freshRes = await axios.get(`${API}/content/chapters?subject_id=${selSubject}`, authHeaders(adminToken));
      if (freshRes.data?.chapters) setChapters(freshRes.data.chapters);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Bulk note generation failed');
    } finally {
      setBulkGenerating(false);
    }
  };

  const breadcrumb = [];
  if (selBoard) breadcrumb.push({ label: boardData?.name || selBoard, onClick: () => { setSelClass(null); setSelStream(null); setSelSubject(null); setEditView(null); } });
  if (selClass) breadcrumb.push({ label: classData?.name || selClass, onClick: () => { setSelStream(null); setSelSubject(null); setEditView(null); } });
  if (selStream) breadcrumb.push({ label: streamData?.name || selStream, onClick: () => { setSelSubject(null); setEditView(null); } });
  if (selSubject) breadcrumb.push({ label: subjectData?.name || selSubject, onClick: () => { setEditView(null); } });

  return (
    <div className="h-full flex flex-col bg-[#06060e]">
      <>

          <div className="h-14 border-b border-white/10 flex items-center justify-between px-6" style={{ background: 'rgba(255,255,255,0.02)' }}>
            <div className="flex items-center gap-2 min-w-0">
              {breadcrumb.length > 0 && (
                <div className="flex items-center gap-1 text-sm text-white/40 min-w-0 overflow-hidden">
                  {breadcrumb.map((b, i) => (
                    <span key={i} className="flex items-center gap-1 min-w-0">
                      <ChevronRight size={12} className="flex-shrink-0" />
                      <button onClick={b.onClick} className="hover:text-violet-400 truncate max-w-[120px] transition-colors">{b.label}</button>
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="relative flex-shrink-0 w-64">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search all subjects..."
                className="w-full h-9 pl-8 pr-3 rounded-xl text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
                data-testid="search-subjects"
              />
            </div>
          </div>

          {searchQuery && searchFiltered ? (
            <div className="flex-1 overflow-y-auto p-6">
              <p className="text-sm text-white/40 mb-4">{searchFiltered.length} subject(s) matching "{searchQuery}"</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {searchFiltered.map(s => (
                  <button key={s.id} onClick={() => { setSearchQuery(''); const st = streams.find(x => x.id === s.stream_id); if (st) { const cl = classes.find(x => x.id === st.class_id); if (cl) setSelBoard(cl.board_id); setSelClass(st.class_id); } setSelStream(s.stream_id); setSelSubject(s.id); }}
                    className="p-4 rounded-xl border border-white/10 hover:border-violet-500/30 bg-white/[0.02] text-left transition-colors"
                  >
                    <p className="text-sm font-medium text-white">{s.icon} {s.name}</p>
                    <p className="text-xs text-white/40 truncate mt-1">{s.description}</p>
                    <p className="text-[10px] text-white/30 mt-2">{s.streamName || s.className || ''}</p>
                  </button>
                ))}
                {searchFiltered.length === 0 && <p className="text-white/30 text-sm col-span-3">No subjects found</p>}
              </div>
            </div>
          ) : editView === 'new-chapter' || editView === 'edit-chapter' ? (
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="px-8 pt-7 pb-4 flex-shrink-0">
                <button onClick={() => { setEditView(null); setEditTarget(null); setChapterStats(null); }} className="flex items-center gap-1.5 text-sm text-white/50 hover:text-white mb-5"><ArrowLeft size={16} /> Back</button>
                <h3 className="text-2xl font-bold text-white mb-0.5">{editView === 'edit-chapter' ? 'Edit Chapter' : 'Create Chapter'}</h3>
                <p className="text-white/50 text-sm">for {subjectData?.name}</p>
              </div>
              <div className="flex-1 flex flex-col min-h-0 px-8 pb-8 gap-4">
                <div className="flex-shrink-0 grid grid-cols-1 lg:grid-cols-2 gap-3">
                  <div>
                    <label className="text-sm text-white/60 block mb-1.5">Title *</label>
                    <input value={contentForm.title} onChange={(e) => { const title = e.target.value; setContentForm(f => ({ ...f, title, slug: f.slug === autoSlug(f.title) || !f.slug ? autoSlug(title) : f.slug })); }} placeholder="Chapter title" className="w-full h-11 px-4 rounded-xl text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500" />
                  </div>
                  <div>
                    <label className="text-sm text-white/60 block mb-1.5">URL Slug</label>
                    <div className="flex items-center gap-2">
                      <div className="flex items-center flex-1 h-11 rounded-xl bg-white/5 border border-white/10 overflow-hidden">
                        <span className="px-3 text-xs text-white/30 flex-shrink-0"><Link2 size={12} /></span>
                        <input value={contentForm.slug} onChange={(e) => setContentForm({ ...contentForm, slug: e.target.value })} placeholder="auto-generated-slug" className="flex-1 h-full text-sm text-white bg-transparent outline-none font-mono pr-3" />
                      </div>
                    </div>
                  </div>
                </div>
                <div className="flex-shrink-0 grid grid-cols-1 lg:grid-cols-2 gap-3">
                  <div>
                    <label className="text-sm text-white/60 block mb-1.5">Content Type</label>
                    <div className="flex flex-wrap gap-1.5">
                      {CONTENT_TYPES.map(ct => (
                        <button
                          key={ct.value}
                          onClick={() => setContentForm(f => ({ ...f, content_type: ct.value }))}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${contentForm.content_type === ct.value ? 'border-violet-500 bg-violet-500/20 text-violet-300' : 'border-white/10 bg-white/5 text-white/50 hover:text-white hover:border-white/20'}`}
                        >
                          {ct.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <label className="text-sm text-white/60 block mb-1.5">Description</label>
                    <input value={contentForm.description} onChange={(e) => setContentForm({ ...contentForm, description: e.target.value })} placeholder="Brief description..." className="w-full h-11 px-4 rounded-xl text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500" />
                  </div>
                </div>

                {chapterStats && (
                  <div className="flex-shrink-0 flex items-center gap-4 px-4 py-2.5 rounded-xl bg-white/[0.03] border border-white/10 text-xs">
                    <div className="flex items-center gap-1.5 text-white/60">
                      <BarChart3 size={12} className="text-violet-400" />
                      <span>{chapterStats.chunk_count} chunks</span>
                    </div>
                    <div className="text-white/40">{chapterStats.content_length.toLocaleString()} chars</div>
                    <div className={`${chapterStats.has_slug ? 'text-emerald-400' : 'text-amber-400'}`}>{chapterStats.has_slug ? 'Slug OK' : 'No slug'}</div>
                    {(chapterStats.attached_files || []).length > 0 && (
                      <div className="flex items-center gap-1 text-blue-400"><Paperclip size={11} />{chapterStats.attached_files.length} files</div>
                    )}
                    <button onClick={() => loadChapterStats(editTarget?.id)} className="ml-auto text-white/30 hover:text-white p-1"><RefreshCw size={11} /></button>
                  </div>
                )}
                <div className="flex-1 flex flex-col min-h-0">
                  {/* Template Library row */}
                  <div className="flex items-center gap-1.5 mb-2 flex-shrink-0 flex-wrap">
                    <LayoutTemplate size={11} className="text-white/25 flex-shrink-0" />
                    <span className="text-[10px] text-white/30 flex-shrink-0 mr-0.5">Insert:</span>
                    {TEMPLATES.map(t => (
                      <button
                        key={t.label}
                        onClick={() => {
                          const current = editorRef.current?.getMarkdown?.() ?? contentForm.content;
                          setContentForm(f => ({ ...f, content: current + t.shortcode }));
                          setEditorKey(k => k + 1);
                        }}
                        className="px-2 py-0.5 rounded text-[10px] border border-white/10 bg-white/5 text-white/40 hover:text-violet-300 hover:border-violet-500/40 transition-colors"
                      >
                        {t.label}
                      </button>
                    ))}
                    <div className="ml-auto flex items-center gap-2">
                      <span className="text-[10px] text-white/25">{contentForm.content.length}ch</span>
                      <button
                        onClick={() => setShowPreview(p => !p)}
                        className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-medium border transition-colors ${
                          showPreview
                            ? 'bg-violet-600/25 text-violet-300 border-violet-500/30'
                            : 'bg-white/5 text-white/40 border-white/10 hover:text-white'
                        }`}
                      >
                        <Eye size={10} />
                        {showPreview ? 'Hide Blog Preview' : 'Blog Preview'}
                      </button>
                    </div>
                  </div>

                  {/* MDXEditor + optional split blog preview */}
                  <div className={`flex-1 min-h-0 flex gap-3 ${showPreview ? '' : 'flex-col'}`}>
                    <div
                      className="flex-1 min-h-0 rounded-xl overflow-hidden border border-black/10 cms-light-editor-wrapper flex flex-col"
                      data-color-mode="light"
                      style={{ backgroundColor: '#ffffff', color: '#1a1a1a' }}
                    >
                      <MDXEditor
                        ref={editorRef}
                        key={`${editTarget?.id ?? '__new__'}-${editorKey}`}
                        markdown={contentForm.content}
                        onChange={md => setContentForm(f => ({ ...f, content: md }))}
                        className="mdx-editor-light h-full"
                        contentEditableClassName="cms-editor-content"
                        plugins={[
                          headingsPlugin(),
                          listsPlugin(),
                          quotePlugin(),
                          thematicBreakPlugin(),
                          markdownShortcutPlugin(),
                          codeBlockPlugin({ defaultCodeBlockLanguage: 'text' }),
                          codeMirrorPlugin({
                            codeBlockLanguages: {
                              js: 'JavaScript', ts: 'TypeScript', python: 'Python',
                              text: 'Text', md: 'Markdown', html: 'HTML', css: 'CSS',
                            },
                          }),
                          tablePlugin(),
                          linkPlugin(),
                          diffSourcePlugin({ viewMode: 'rich-text', diffMarkdown: '' }),
                          toolbarPlugin({
                            toolbarContents: () => (
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
                                  onClick={handleAiParse}
                                  disabled={aiParsing}
                                  style={{
                                    display: 'flex', alignItems: 'center', gap: 4,
                                    padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                                    color: '#a78bfa', background: 'rgba(167,139,250,0.10)',
                                    border: '1px solid rgba(167,139,250,0.20)',
                                    cursor: aiParsing ? 'not-allowed' : 'pointer',
                                    opacity: aiParsing ? 0.5 : 1,
                                  }}
                                >
                                  {aiParsing
                                    ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
                                    : <Sparkles size={12} />}
                                  AI
                                </button>
                              </DiffSourceToggleWrapper>
                            ),
                          }),
                        ]}
                      />
                    </div>
                    {showPreview && (
                      <div className="flex-1 min-h-0 overflow-y-auto rounded-xl" style={{ background: '#f0f0f1' }}>
                        <div style={{ background: '#ffffff', color: '#1a1a1a', fontSize: '15px', lineHeight: '1.75', padding: '1.5rem 2rem', minHeight: '100%' }}>
                          {contentForm.content.trim() ? (
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {contentForm.content}
                            </ReactMarkdown>
                          ) : (
                            <p style={{ color: '#aaa', fontStyle: 'italic' }}>Blog preview appears here as you type…</p>
                          )}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Attach file — edit mode only */}
                  {editView === 'edit-chapter' && editTarget?.id && (
                    <div className="flex items-center gap-3 mt-2 flex-shrink-0">
                      <input ref={fileInputRef} type="file" accept=".pdf,.txt,.md" className="hidden" onChange={() => handleFileAttach(editTarget.id)} />
                      <button
                        onClick={() => fileInputRef.current?.click()}
                        disabled={uploading}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 transition-colors text-xs font-medium disabled:opacity-40"
                      >
                        {uploading ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
                        Attach File (PDF / TXT / MD)
                      </button>
                      {chapterStats && (
                        <span className="text-[11px] text-white/30">{chapterStats.chunk_count} chunks · {chapterStats.content_length?.toLocaleString()} chars</span>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex gap-3 flex-shrink-0">
                  <button onClick={() => { setEditView(null); setEditTarget(null); }} className="flex-1 h-12 rounded-xl bg-white/5 hover:bg-white/10 text-white font-medium">Cancel</button>
                  <button
                    onClick={editView === 'edit-chapter' ? handleUpdateChapter : handleCreateChapter}
                    disabled={saving || !contentForm.title}
                    className="flex-1 h-12 rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-semibold disabled:opacity-40 flex items-center justify-center gap-2"
                  >
                    {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                    {saving ? 'Saving...' : editView === 'edit-chapter' ? 'Update Chapter' : 'Create Chapter'}
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex overflow-hidden">
              {/* Left panel — hierarchy tree */}
              <div className="w-72 border-r border-white/10 flex flex-col overflow-y-auto" style={{ background: 'rgba(255,255,255,0.015)' }}>
                <div className="p-3 space-y-1">
                  <p className="text-[10px] uppercase tracking-wider text-white/30 px-2 mb-2 font-semibold">Boards</p>
                  {boards.map(b => (
                    <div key={b.id}>
                      <div className="flex items-center group">
                        <button
                          onClick={() => { setSelBoard(selBoard === b.id ? null : b.id); setSelClass(null); setSelStream(null); setSelSubject(null); }}
                          className={`flex-1 flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${selBoard === b.id ? 'bg-violet-500/15 text-violet-300' : 'text-white/70 hover:bg-white/5'}`}
                        >
                          {selBoard === b.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          <Building2 size={14} />
                          <span className="truncate">{b.name}</span>
                        </button>
                        <button onClick={() => handleDelete('board', b.id)} className="p-1 rounded opacity-0 group-hover:opacity-100 text-white/20 hover:text-red-400"><Trash2 size={12} /></button>
                      </div>

                      {selBoard === b.id && (
                        <div className="ml-5 mt-1 space-y-1 border-l border-white/5 pl-3">
                          <p className="text-[10px] uppercase tracking-wider text-white/25 px-1 font-semibold">Classes</p>
                          {filteredClasses.map(c => (
                            <div key={c.id}>
                              <div className="flex items-center group">
                                <button
                                  onClick={() => { setSelClass(selClass === c.id ? null : c.id); setSelStream(null); setSelSubject(null); }}
                                  className={`flex-1 flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs transition-colors ${selClass === c.id ? 'bg-blue-500/15 text-blue-300' : 'text-white/60 hover:bg-white/5'}`}
                                >
                                  {selClass === c.id ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                                  <GraduationCap size={12} />
                                  <span className="truncate">{c.name}</span>
                                </button>
                                <button onClick={() => handleDelete('classe', c.id)} className="p-1 rounded opacity-0 group-hover:opacity-100 text-white/20 hover:text-red-400"><Trash2 size={10} /></button>
                              </div>

                              {selClass === c.id && (
                                <div className="ml-4 mt-1 space-y-1 border-l border-white/5 pl-3">
                                  <p className="text-[10px] uppercase tracking-wider text-white/25 px-1 font-semibold">Streams</p>
                                  {filteredStreams.map(st => (
                                    <div key={st.id} className="flex items-center group">
                                      <button
                                        onClick={() => { setSelStream(selStream === st.id ? null : st.id); setSelSubject(null); }}
                                        className={`flex-1 flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs transition-colors ${selStream === st.id ? 'bg-emerald-500/15 text-emerald-300' : 'text-white/50 hover:bg-white/5'}`}
                                      >
                                        <GitBranch size={11} />
                                        <span className="truncate">{st.icon || ''} {st.name}</span>
                                      </button>
                                      <button onClick={() => handleDelete('stream', st.id)} className="p-1 rounded opacity-0 group-hover:opacity-100 text-white/20 hover:text-red-400"><Trash2 size={10} /></button>
                                    </div>
                                  ))}
                                  <InlineCreator placeholder="Stream" onCreate={handleCreateStream} icon={GitBranch} color="emerald" />
                                </div>
                              )}
                            </div>
                          ))}
                          <InlineCreator placeholder="Class" onCreate={handleCreateClass} icon={GraduationCap} color="blue" />
                        </div>
                      )}
                    </div>
                  ))}
                  <InlineCreator placeholder="Board" onCreate={handleCreateBoard} icon={Building2} color="violet" />
                </div>
              </div>

              {/* Right panel */}
              <div className="flex-1 overflow-y-auto">
                {!selStream && !selSubject ? (
                  <div className="flex items-center justify-center h-full">
                    <div className="text-center max-w-md">
                      <Layers size={56} className="mx-auto text-white/15 mb-4" />
                      <h3 className="text-xl font-bold text-white mb-2">All-in-One Content Manager</h3>
                      <p className="text-white/50 text-sm mb-2">Navigate the tree on the left: Board → Class → Stream → Subject</p>
                      <p className="text-white/30 text-xs">Or use the search bar to find any subject</p>
                    </div>
                  </div>
                ) : selStream && !selSubject ? (
                  <div className="p-6 max-w-4xl mx-auto space-y-4">
                    <div className="mb-2">
                      <h3 className="text-xl font-bold text-white">{streamData?.icon} {streamData?.name}</h3>
                      <p className="text-sm text-white/40">{streamData?.description}</p>
                    </div>
                    <p className="text-sm font-semibold text-white/60">Subjects ({filteredSubjects.length})</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {filteredSubjects.map(s => (
                        <div key={s.id} className="p-4 rounded-xl border border-white/10 hover:border-violet-500/30 bg-white/[0.02] text-left transition-colors group cursor-pointer" onClick={() => setSelSubject(s.id)}>
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-medium text-white">{s.icon || '📚'} {s.name}</p>
                            <div className="flex items-center gap-1">
                              {mergedSubjectIds.has(s.id) && <CheckCircle size={11} className="text-violet-400" />}
                              <button onClick={(e) => { e.stopPropagation(); handleDelete('subject', s.id); }} className="p-1 rounded opacity-0 group-hover:opacity-100 text-white/20 hover:text-red-400"><Trash2 size={12} /></button>
                            </div>
                          </div>
                          <p className="text-xs text-white/40 truncate mt-1">{s.description}</p>
                          <div className="flex items-center justify-between mt-2">
                            <p className="text-[10px] text-white/25">{s.chapter_count || 0} chapters</p>
                            <button
                              onClick={(e) => { e.stopPropagation(); handlePublishAsBlog(s.id, s.name); }}
                              disabled={publishingBlog}
                              className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-medium opacity-0 group-hover:opacity-100 disabled:opacity-30 transition-all"
                              style={{ background: 'rgba(149,117,224,0.20)', color: '#c4b0f0' }}
                            >
                              <Globe size={9} /> Publish as Blog
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                    <InlineCreator placeholder="Subject" onCreate={handleCreateSubject} icon={BookOpen} color="violet" />
                  </div>
                ) : selSubject ? (
                  <div className="p-6 max-w-5xl mx-auto space-y-6">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-xl font-bold text-white">{subjectData?.icon || '📚'} {subjectData?.name}</h3>
                        <p className="text-sm text-white/40">{subjectData?.description}</p>
                      </div>
                    </div>

                    {/* ── Workflow Tracker ──────────────────────────────── */}
                    <div className="flex items-center gap-2 px-4 py-3 rounded-xl border" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.07)' }}>
                      <div className={`flex items-center gap-1.5 text-xs font-medium ${chapters.length > 0 ? 'text-emerald-400' : 'text-white/30'}`}>
                        {chapters.length > 0
                          ? <CheckCircle size={13} />
                          : <div className="w-3.5 h-3.5 rounded-full border-2 border-white/20" />}
                        <span>{chapters.length} Chapter{chapters.length !== 1 ? 's' : ''}</span>
                      </div>
                      <ChevronRight size={11} className="text-white/20" />
                      <div className={`flex items-center gap-1.5 text-xs font-medium ${mergedSubjectIds.has(selSubject) ? 'text-violet-400' : 'text-white/25'}`}>
                        {mergedSubjectIds.has(selSubject)
                          ? <CheckCircle size={13} />
                          : <div className="w-3.5 h-3.5 rounded-full border-2 border-white/20" />}
                        <span>Blog Merged</span>
                      </div>
                      <ChevronRight size={11} className="text-white/20" />
                      <div className="flex items-center gap-1.5 text-xs font-medium text-white/25">
                        <div className="w-3.5 h-3.5 rounded-full border-2 border-white/20" />
                        <span>Published</span>
                      </div>
                      <div className="ml-auto flex items-center gap-2">
                        {onNavigate && (
                          <>
                            <button
                              onClick={() => {
                                const sub = subjectData;
                                const ch  = editTarget ? chapters.find(c => c.id === editTarget) : null;
                                try {
                                  localStorage.setItem('syrabit_studio_prefill', JSON.stringify({
                                    subject:    sub?.name || '',
                                    subjectId:  selSubject,
                                    boardId:    selBoard  || '',
                                    classId:    selClass  || '',
                                    streamId:   selStream || '',
                                    chapter:    ch?.title || contentForm.title || '',
                                    rawText:    contentForm.content || '',
                                    timestamp:  Date.now(),
                                  }));
                                } catch {}
                                onNavigate('studio');
                              }}
                              disabled={!contentForm.content.trim()}
                              className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-semibold disabled:opacity-40 transition-all hover:opacity-90"
                              style={{ background: 'rgba(244,63,94,0.15)', color: '#fda4af', border: '1px solid rgba(244,63,94,0.30)' }}
                              title="Send chapter content to AI Studio for structured block generation"
                            >
                              <Sparkles size={11} /> Send to AI Studio
                            </button>
                            <button
                              onClick={() => {
                                try {
                                  const ctx = {
                                    subjectId:   selSubject  || '',
                                    subjectName: subjectData?.name || '',
                                    className:   selClass    || '',
                                    boardName:   selBoard    || '',
                                    streamName:  selStream   || '',
                                    _ts: Date.now(),
                                  };
                                  localStorage.setItem('syrabit_hub_ctx', JSON.stringify(ctx));
                                } catch {}
                                onNavigate('seomanager');
                              }}
                              disabled={!selSubject}
                              className="flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-semibold disabled:opacity-40 transition-all hover:opacity-90"
                              style={{ background: 'rgba(6,182,212,0.12)', color: '#67e8f9', border: '1px solid rgba(6,182,212,0.28)' }}
                              title="Generate SEO topics for this subject in SEO Manager"
                            >
                              <Globe size={11} /> Generate SEO Topics →
                            </button>
                          </>
                        )}
                        <button
                          onClick={() => handlePublishAsBlog(selSubject, subjectData?.name || selSubject)}
                          disabled={publishingBlog || chapters.length === 0}
                          className="flex items-center gap-1.5 h-8 px-4 rounded-lg text-xs font-semibold disabled:opacity-40 transition-all hover:opacity-90"
                          style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)', color: 'white', boxShadow: '0 2px 8px rgba(124,58,237,0.28)' }}
                        >
                          {publishingBlog ? <Loader2 size={12} className="animate-spin" /> : <Globe size={12} />}
                          Publish as Blog
                        </button>
                      </div>
                    </div>

                    {/* ── AI Thumbnail Studio ───────────────────────────── */}
                    <div className="rounded-xl border border-white/10 bg-white/[0.02] overflow-hidden">
                      <div className="flex items-center justify-between px-4 py-3 border-b border-white/8">
                        <div className="flex items-center gap-2">
                          <Wand2 size={13} className="text-violet-400" />
                          <span className="text-sm font-semibold text-white">AI Thumbnail Studio</span>
                          <span className="text-[10px] text-white/30 bg-white/5 px-2 py-0.5 rounded-full">background on Library card</span>
                        </div>
                        {subjectData?.thumbnailUrl && (
                          <button onClick={handleClearThumbnail}
                            className="text-[11px] text-red-400/70 hover:text-red-400 transition-colors flex items-center gap-1">
                            <X size={11} /> Remove
                          </button>
                        )}
                      </div>
                      <div className="p-4 space-y-4">
                        {/* Upload row */}
                        <div className="flex items-start gap-4">
                          <div className="w-20 h-[72px] rounded-lg flex-shrink-0 flex items-center justify-center overflow-hidden"
                            style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.03)' }}>
                            {subjectData?.thumbnailUrl ? (
                              <img src={subjectData.thumbnailUrl} alt="thumbnail" className="w-full h-full object-cover" />
                            ) : (
                              <span className="text-white/20 text-[10px] text-center px-1">No image</span>
                            )}
                          </div>
                          <div className="flex-1 space-y-2">
                            <p className="text-xs text-white/40">
                              Upload a book cover (PNG, JPG, WebP — max 2 MB). The AI will extract its color DNA and generate 3 copyright-safe abstract variants.
                            </p>
                            <input ref={thumbnailInputRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
                              onChange={async (e) => {
                                const file = e.target.files?.[0];
                                if (!file) return;
                                await handleUploadThumbnail(file);
                                await handleGenerateAiThumbnails(file);
                              }} />
                            <div className="flex items-center gap-2 flex-wrap">
                              <button onClick={() => thumbnailInputRef.current?.click()} disabled={thumbnailLoading || aiThumbLoading}
                                className="flex items-center gap-2 h-9 px-4 rounded-lg text-xs font-semibold text-white transition-all hover:opacity-90 active:scale-95 disabled:opacity-50"
                                style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)', boxShadow: '0 2px 8px rgba(124,58,237,0.30)' }}>
                                {thumbnailLoading ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
                                {thumbnailLoading ? 'Uploading…' : subjectData?.thumbnailUrl ? 'Replace' : 'Upload Cover'}
                              </button>
                              {subjectData?.thumbnailUrl && (
                                <button onClick={() => handleGenerateAiThumbnails()} disabled={aiThumbLoading}
                                  className="flex items-center gap-2 h-9 px-4 rounded-lg text-xs font-semibold disabled:opacity-50 transition-all hover:opacity-90"
                                  style={{ background: 'rgba(139,92,246,0.20)', border: '1px solid rgba(139,92,246,0.35)', color: '#c4b0f0' }}>
                                  {aiThumbLoading ? <Loader2 size={13} className="animate-spin" /> : <Wand2 size={13} />}
                                  {aiThumbLoading ? 'Analyzing…' : thumbVariants.length > 0 ? 'Regenerate' : 'Generate AI Variants'}
                                </button>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* AI loading state */}
                        {aiThumbLoading && (
                          <div className="rounded-xl p-4 flex items-center gap-3" style={{ background: 'rgba(139,92,246,0.08)', border: '1px solid rgba(139,92,246,0.20)' }}>
                            <Loader2 size={16} className="animate-spin flex-shrink-0" style={{ color: '#a78bfa' }} />
                            <div>
                              <p className="text-xs font-semibold" style={{ color: '#c4b0f0' }}>Groq Vision analyzing color palette…</p>
                              <p className="text-[10px] mt-0.5" style={{ color: 'rgba(167,139,250,0.60)' }}>Extracting dominant colors → generating 3 abstract variants</p>
                            </div>
                          </div>
                        )}

                        {/* AI Variant Carousel */}
                        {thumbVariants.length > 0 && !aiThumbLoading && (
                          <div className="space-y-3">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-semibold" style={{ color: '#c4b0f0' }}>Copyright-Safe Variants</span>
                                {thumbAnalysis?.style && (
                                  <span className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'rgba(139,92,246,0.15)', color: '#a78bfa' }}>
                                    {thumbAnalysis.style} · {thumbAnalysis.mood}
                                  </span>
                                )}
                              </div>
                              <button onClick={() => handleGenerateAiThumbnails()} disabled={aiThumbLoading}
                                className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-lg"
                                style={{ color: 'rgba(255,255,255,0.35)', background: 'rgba(255,255,255,0.06)' }}>
                                <RefreshCw size={9} /> New set
                              </button>
                            </div>

                            {/* Color palette */}
                            {thumbAnalysis?.dominant_colors && (
                              <div className="flex items-center gap-1.5">
                                <span className="text-[10px]" style={{ color: 'rgba(255,255,255,0.30)' }}>Palette:</span>
                                {[...(thumbAnalysis.dominant_colors || []), ...(thumbAnalysis.secondary_colors || [])].slice(0, 5).map((hex, i) => (
                                  <div key={i} title={hex} className="w-4 h-4 rounded-full border border-white/15 flex-shrink-0" style={{ background: hex }} />
                                ))}
                              </div>
                            )}

                            {/* 3 variant cards */}
                            <div className="grid grid-cols-3 gap-2">
                              {thumbVariants.map((varUrl, i) => (
                                <div key={i}
                                  className="relative group rounded-xl overflow-hidden cursor-pointer transition-all"
                                  style={{ border: `2px solid ${selectedThumbVariant === i ? '#7c3aed' : 'rgba(255,255,255,0.08)'}` }}
                                  onClick={() => setSelectedThumbVariant(i)}>
                                  <img src={varUrl} alt={`Variant ${i + 1}`} className="w-full object-cover" style={{ aspectRatio: '2/3' }} />
                                  {/* Hover overlay with "Use This" */}
                                  <div className="absolute inset-0 flex flex-col justify-end p-2 opacity-0 group-hover:opacity-100 transition-opacity"
                                    style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.85) 0%, transparent 60%)' }}>
                                    <button onClick={e => { e.stopPropagation(); handleApplyVariant(varUrl); }}
                                      className="w-full py-1.5 rounded-lg text-[10px] font-bold text-white"
                                      style={{ background: '#7c3aed' }}>
                                      Use This
                                    </button>
                                  </div>
                                  {/* Selected badge */}
                                  {selectedThumbVariant === i && (
                                    <div className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full flex items-center justify-center" style={{ background: '#7c3aed' }}>
                                      <CheckCircle size={11} className="text-white" />
                                    </div>
                                  )}
                                  {/* Variant label */}
                                  <div className="absolute bottom-0 left-0 right-0 text-center py-1 text-[8px] font-medium"
                                    style={{ background: 'rgba(0,0,0,0.65)', color: 'rgba(255,255,255,0.55)' }}>
                                    {['Gradient Wash', 'Geometric', 'Abstract'][i]}
                                  </div>
                                </div>
                              ))}
                            </div>

                            {/* Apply selected */}
                            <button onClick={() => handleApplyVariant(thumbVariants[selectedThumbVariant])}
                              className="w-full py-2.5 rounded-xl text-sm font-semibold text-white"
                              style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)', boxShadow: '0 2px 10px rgba(124,58,237,0.30)' }}>
                              Apply "{['Gradient Wash', 'Geometric', 'Abstract'][selectedThumbVariant]}" as Thumbnail
                            </button>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Create Chapter CTA */}
                    <button
                      onClick={() => { setEditView('new-chapter'); setContentForm({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: chapters.length + 1 }); setChapterStats(null); }}
                      className="w-full p-5 rounded-xl border border-dashed border-violet-500/30 hover:border-violet-500/60 bg-violet-500/5 hover:bg-violet-500/10 text-center transition-colors"
                    >
                      <BookOpen size={28} className="mx-auto text-violet-400 mb-2" />
                      <p className="text-sm font-bold text-white">Create New Chapter</p>
                      <p className="text-[11px] text-white/40 mt-1">Add chapter content with Markdown — slug auto-generated</p>
                    </button>

                    {/* Chapters list */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-semibold text-white">Chapters ({chapters.length})</p>
                        <div className="flex items-center gap-2">
                          {chapters.length > 0 && (
                            <button
                              onClick={() => setSelectedChapters(prev => prev.size === chapters.length ? new Set() : new Set(chapters.map(c => c.id)))}
                              className="text-[10px] text-white/30 hover:text-white transition-colors"
                            >
                              {selectedChapters.size === chapters.length ? 'Deselect all' : 'Select all'}
                            </button>
                          )}
                          {chapters.length > 0 && (
                            <button
                              onClick={handleGenerateAllNotes}
                              disabled={bulkGenerating}
                              className="flex items-center gap-1 h-6 px-2 rounded-lg text-[10px] font-medium transition-colors disabled:opacity-40"
                              style={{ background: 'rgba(149,117,224,0.18)', color: '#c4b0f0' }}
                              title="Generate AI notes for all chapters"
                            >
                              {bulkGenerating ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                              {bulkGenerating ? 'Generating…' : 'Gen All Notes'}
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Bulk action bar */}
                      {selectedChapters.size > 0 && (
                        <div className="flex items-center gap-3 px-3 py-2 rounded-xl" style={{ background: 'rgba(149,117,224,0.10)', border: '1px solid rgba(149,117,224,0.20)' }}>
                          <span className="text-xs text-violet-300 font-medium">{selectedChapters.size} selected</span>
                          <button
                            onClick={handleBulkMerge}
                            disabled={bulkMerging}
                            className="flex items-center gap-1.5 h-7 px-3 rounded-lg text-xs font-medium disabled:opacity-40 transition-colors"
                            style={{ background: 'rgba(149,117,224,0.25)', color: '#c4b0f0' }}
                          >
                            {bulkMerging ? <Loader2 size={11} className="animate-spin" /> : <Globe size={11} />}
                            Merge to Blog
                          </button>
                          <button
                            onClick={() => setSelectedChapters(new Set())}
                            className="ml-auto text-[10px] text-white/30 hover:text-white transition-colors"
                          >
                            Clear
                          </button>
                        </div>
                      )}

                      {chapters.length === 0 && <p className="text-xs text-white/30 py-4 text-center">No chapters yet — create the first one above</p>}
                      {chapters.map(ch => (
                        <div key={ch.id} className="p-3 rounded-xl border hover:border-violet-500/20 bg-white/[0.02] flex items-start justify-between transition-colors"
                          style={{ borderColor: selectedChapters.has(ch.id) ? 'rgba(149,117,224,0.35)' : 'rgba(255,255,255,0.08)', background: selectedChapters.has(ch.id) ? 'rgba(149,117,224,0.06)' : undefined }}>
                          <div className="flex items-center gap-2 min-w-0">
                            <input
                              type="checkbox"
                              checked={selectedChapters.has(ch.id)}
                              onChange={e => setSelectedChapters(prev => {
                                const next = new Set(prev);
                                if (e.target.checked) next.add(ch.id); else next.delete(ch.id);
                                return next;
                              })}
                              className="rounded flex-shrink-0 accent-violet-500 cursor-pointer"
                              onClick={e => e.stopPropagation()}
                            />
                            <Book size={14} className="text-violet-400 flex-shrink-0" />
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <p className="text-sm font-medium text-white truncate">{ch.title}</p>
                                {ch.content_type && ch.content_type !== 'notes' && (
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-white/10 text-white/50 uppercase">{ch.content_type}</span>
                                )}
                              </div>
                              <div className="flex items-center gap-2 mt-0.5">
                                {ch.slug && <span className="text-[10px] text-white/25 font-mono truncate max-w-[180px]">/{ch.slug}</span>}
                                {ch.description && <span className="text-xs text-white/40 truncate">{ch.description}</span>}
                              </div>
                            </div>
                          </div>
                          <div className="flex gap-0.5 flex-shrink-0">
                            <button
                              onClick={() => handleGenerateNotes(ch.id, ch.title)}
                              disabled={generatingNotes.has(ch.id) || bulkGenerating}
                              className="p-1.5 rounded-lg hover:bg-violet-500/10 text-white/30 hover:text-violet-400 disabled:opacity-40 transition-colors"
                              title="Generate AI notes for this chapter"
                            >
                              {generatingNotes.has(ch.id) ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                            </button>
                            <button onClick={() => setViewerItem(ch)} className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-white/30 hover:text-emerald-400" title="Preview" data-testid={`open-chapter-${ch.id}`}><Eye size={14} /></button>
                            <button onClick={() => { setEditTarget(ch); setContentForm({ title: ch.title, slug: ch.slug || '', description: ch.description || '', content: ch.content || '', content_type: ch.content_type || 'notes', order: ch.order || 1 }); setEditView('edit-chapter'); loadChapterStats(ch.id); }}
                              className="p-1.5 rounded-lg hover:bg-violet-500/10 text-white/30 hover:text-violet-400"><Edit2 size={14} /></button>
                            <button onClick={() => handleDeleteChapter(ch.id)} className="p-1.5 rounded-lg hover:bg-red-500/10 text-white/30 hover:text-red-400"><Trash2 size={14} /></button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </>

      {viewerItem && <ContentViewerPopup item={viewerItem} onClose={() => setViewerItem(null)} />}
    </div>
  );
}
