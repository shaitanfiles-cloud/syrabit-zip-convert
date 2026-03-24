import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  Search, Plus, Save, Trash2, Upload, X, BookOpen, Loader2,
  FolderPlus, FilePlus, Edit2, FileText, File, Calendar,
  Book, HelpCircle, CheckCircle, Layers, Eye, FileUp,
  ChevronRight, ChevronDown, GraduationCap, Building2, GitBranch, ArrowLeft,
  Scroll
} from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { Viewer, Worker } from '@react-pdf-viewer/core';
import { defaultLayoutPlugin } from '@react-pdf-viewer/default-layout';
import '@react-pdf-viewer/core/lib/styles/index.css';
import '@react-pdf-viewer/default-layout/lib/styles/index.css';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import AdminSyllabusManager from './AdminSyllabusManager';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

const CONTENT_TYPES = [
  { id: 'pyq', label: 'Question Paper', icon: HelpCircle, color: 'rose' },
  { id: 'notes', label: 'Notes', icon: FileText, color: 'blue' },
  { id: 'document', label: 'Document', icon: FilePlus, color: 'emerald' },
];

function authHeaders(token) {
  const isRealJwt = token && token.split('.').length === 3;
  return { headers: isRealJwt ? { Authorization: `Bearer ${token}` } : {}, withCredentials: true };
}

const PDF_WORKER_URL = 'https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.min.js';

function PdfViewerInner({ fileUrl }) {
  const layoutPlugin = useMemo(() => defaultLayoutPlugin({
    sidebarTabs: () => [],
    toolbarPlugin: {
      downloadPlugin: { enableShortcuts: false },
      printPlugin: { enableShortcuts: false },
      getFilePlugin: { enableShortcuts: false },
    },
    renderToolbar: (Toolbar) => (
      <Toolbar>
        {(slots) => {
          const { CurrentPageInput, NumberOfPages, ZoomIn, ZoomOut, GoToNextPage, GoToPreviousPage } = slots;
          return (
            <div className="rpv-toolbar" style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 8px', width: '100%' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <GoToPreviousPage />
                <CurrentPageInput /> / <NumberOfPages />
                <GoToNextPage />
              </div>
              <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 2 }}>
                <ZoomOut />
                <ZoomIn />
              </div>
            </div>
          );
        }}
      </Toolbar>
    ),
  }), []);

  return (
    <Worker workerUrl={PDF_WORKER_URL}>
      <Viewer fileUrl={fileUrl} plugins={[layoutPlugin]} />
    </Worker>
  );
}

function ContentViewerPopup({ item, onClose }) {
  if (!item) return null;
  const isPdf = item.file_ext === 'pdf' && item.file_url;
  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/80 backdrop-blur-sm" />
      <div
        className="relative flex flex-col rounded-2xl border border-white/10 overflow-hidden"
        style={{ width: '90vw', height: '90vh', background: '#0a0a14' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10" style={{ background: 'rgba(255,255,255,0.03)' }}>
          <div className="flex items-center gap-3 min-w-0">
            {isPdf ? <FileText size={20} className="text-rose-400 flex-shrink-0" /> : <Book size={20} className="text-violet-400 flex-shrink-0" />}
            <div className="min-w-0">
              <h3 className="text-lg font-bold text-white truncate">{item.title || item.file_name || 'Untitled'}</h3>
              <p className="text-xs text-white/40">
                {item.year && `Year: ${item.year} · `}
                {item.file_ext && `${item.file_ext.toUpperCase()} · `}
                {item.file_size ? `${(item.file_size / 1024).toFixed(0)} KB` : `${(item.content || '').length} chars`}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="w-9 h-9 rounded-xl flex items-center justify-center bg-white/5 hover:bg-white/10 text-white/60 hover:text-white" data-testid="close-viewer">
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-hidden bg-white">
          {isPdf ? (
            <div className="h-full">
              <PdfViewerInner fileUrl={item.file_url} />
            </div>
          ) : (
            <div className="h-full overflow-y-auto" style={{ background: '#0a0a14' }}>
              <div className="p-8 max-w-4xl mx-auto">
                {item.description && <p className="text-white/60 text-sm mb-6 pb-4 border-b border-white/10">{item.description}</p>}
                <div className="md-content max-w-none text-sm">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {item.content || '*No content available.*'}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          )}
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

export default function AdminContentEditor({ adminToken }) {
  const [activeTab, setActiveTab] = useState('content'); // 'content' | 'syllabus'
  
  const [boards, setBoards] = useState([]);
  const [classes, setClasses] = useState([]);
  const [streams, setStreams] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [chapters, setChapters] = useState([]);
  const [uploads, setUploads] = useState([]);

  const [selBoard, setSelBoard] = useState(null);
  const [selClass, setSelClass] = useState(null);
  const [selStream, setSelStream] = useState(null);
  const [selSubject, setSelSubject] = useState(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [contentType, setContentType] = useState('pyq');
  const [uploading, setUploading] = useState(false);
  const [viewerItem, setViewerItem] = useState(null);

  const [editView, setEditView] = useState(null);
  const [contentForm, setContentForm] = useState({ title: '', description: '', content: '', order: 1 });
  const [editTarget, setEditTarget] = useState(null);
  const [saving, setSaving] = useState(false);

  const docRef = useRef(null);

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

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (selSubject) {
      axios.get(`${API}/content/chapters/${selSubject}`).then(r => setChapters(r.data || [])).catch(() => setChapters([]));
      
      // Load documents from both sources
      Promise.all([
        axios.get(`${API}/admin/content/uploads?subject_id=${selSubject}`, authHeaders(adminToken)).catch(() => ({ data: [] })),
        axios.get(`${API}/content/subject-documents/${selSubject}`, authHeaders(adminToken)).catch(() => ({ data: [] }))
      ]).then(([oldDocs, newDocs]) => {
        const merged = [...(oldDocs.data || []), ...(newDocs.data || [])];
        setUploads(merged);
      }).catch(() => setUploads([]));
    }
  }, [selSubject, adminToken]);

  const filteredClasses = selBoard ? classes.filter(c => c.board_id === selBoard) : [];
  const filteredStreams = selClass ? streams.filter(s => s.class_id === selClass) : [];
  const filteredSubjects = selStream ? subjects.filter(s => s.stream_id === selStream) : subjects;

  const boardData = boards.find(b => b.id === selBoard);
  const classData = classes.find(c => c.id === selClass);
  const streamData = streams.find(s => s.id === selStream);
  const subjectData = subjects.find(s => s.id === selSubject);

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
    if (!window.confirm(`Delete this ${type}?`)) return;
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

  const handleFileUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length || !selSubject) return;
    setUploading(true);
    let ok = 0;
    
    for (const file of files) {
      try {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('subject_id', selSubject);
        
        // Use new PDF endpoint for PDF files
        if (file.name.toLowerCase().endsWith('.pdf')) {
          fd.append('title', file.name.replace(/\.[^/.]+$/, ''));
          await axios.post(`${API}/admin/content/upload-pdf`, fd, authHeaders(adminToken));
        } else {
          // Use old endpoint for other files
          fd.append('content_type', contentType);
          fd.append('title', file.name.replace(/\.[^/.]+$/, ''));
          const ym = file.name.match(/20\d{2}/);
          if (ym) fd.append('year', ym[0]);
          await axios.post(`${API}/admin/content/upload`, fd, authHeaders(adminToken));
        }
        ok++;
      } catch (err) {
        console.error('Upload failed:', err);
      }
    }
    
    setUploading(false);
    if (docRef.current) docRef.current.value = '';
    
    if (ok) { 
      toast.success(`${ok} file(s) uploaded`); 
      // Reload documents - check both old and new collections
      try {
        const [oldDocs, newDocs] = await Promise.all([
          axios.get(`${API}/admin/content/uploads?subject_id=${selSubject}`, authHeaders(adminToken)).catch(() => ({ data: [] })),
          axios.get(`${API}/content/subject-documents/${selSubject}`, authHeaders(adminToken)).catch(() => ({ data: [] }))
        ]);
        
        // Merge both document sources
        const merged = [...(oldDocs.data || []), ...(newDocs.data || [])];
        setUploads(merged);
      } catch {
        setUploads([]);
      }
    } else {
      toast.error('Upload failed');
    }
  };

  const handleCreateChapter = async () => {
    if (!selSubject || !contentForm.title) return;
    setSaving(true);
    try {
      await axios.post(`${API}/admin/content/chapters`, { subject_id: selSubject, title: contentForm.title, description: contentForm.description, content: contentForm.content, order: contentForm.order, status: 'published' }, authHeaders(adminToken));
      toast.success('Chapter created');
      setEditView(null);
      setContentForm({ title: '', description: '', content: '', order: 1 });
      axios.get(`${API}/content/chapters/${selSubject}`).then(r => setChapters(r.data || []));
    } catch { toast.error('Failed to create chapter'); }
    finally { setSaving(false); }
  };

  const handleUpdateChapter = async () => {
    if (!editTarget || !contentForm.title) return;
    setSaving(true);
    try {
      await axios.patch(`${API}/admin/content/chapters/${editTarget.id}`, { title: contentForm.title, description: contentForm.description, content: contentForm.content, order: contentForm.order }, authHeaders(adminToken));
      toast.success('Chapter updated');
      setEditView(null); setEditTarget(null);
      setContentForm({ title: '', description: '', content: '', order: 1 });
      axios.get(`${API}/content/chapters/${selSubject}`).then(r => setChapters(r.data || []));
    } catch { toast.error('Failed to update'); }
    finally { setSaving(false); }
  };

  const handleDeleteChapter = async (id) => {
    if (!window.confirm('Delete this chapter?')) return;
    try {
      await axios.delete(`${API}/admin/content/chapters/${id}`, authHeaders(adminToken));
      setChapters(p => p.filter(c => c.id !== id));
      toast.success('Chapter deleted');
    } catch { toast.error('Failed to delete'); }
  };

  const handleDeleteUpload = async (id) => {
    if (!window.confirm('Delete this document?')) return;
    try {
      await axios.delete(`${API}/admin/content/uploads/${id}`, authHeaders(adminToken));
      setUploads(p => p.filter(u => u.id !== id));
      toast.success('Document deleted');
    } catch { toast.error('Failed to delete'); }
  };

  const breadcrumb = [];
  if (selBoard) breadcrumb.push({ label: boardData?.name || selBoard, onClick: () => { setSelClass(null); setSelStream(null); setSelSubject(null); setEditView(null); } });
  if (selClass) breadcrumb.push({ label: classData?.name || selClass, onClick: () => { setSelStream(null); setSelSubject(null); setEditView(null); } });
  if (selStream) breadcrumb.push({ label: streamData?.name || selStream, onClick: () => { setSelSubject(null); setEditView(null); } });
  if (selSubject) breadcrumb.push({ label: subjectData?.name || selSubject, onClick: () => { setEditView(null); } });

  return (
    <div className="h-full flex flex-col bg-[#06060e]">
      {/* Tabs */}
      <div className="border-b border-white/10" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <div className="h-14 flex items-center px-6 gap-6">
          <button
            onClick={() => setActiveTab('content')}
            className={`flex items-center gap-2 pb-1 border-b-2 transition-colors font-medium text-sm ${
              activeTab === 'content'
                ? 'border-violet-500 text-violet-400'
                : 'border-transparent text-white/50 hover:text-white'
            }`}
          >
            <Layers size={16} />
            Content Manager
          </button>
          <button
            onClick={() => setActiveTab('syllabus')}
            className={`flex items-center gap-2 pb-1 border-b-2 transition-colors font-medium text-sm ${
              activeTab === 'syllabus'
                ? 'border-indigo-500 text-indigo-400'
                : 'border-transparent text-white/50 hover:text-white'
            }`}
          >
            <Scroll size={16} />
            Syllabus Manager
          </button>
        </div>
      </div>

      {/* Content Manager Tab */}
      {activeTab === 'content' && (
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
          {/* Fixed header */}
          <div className="px-8 pt-7 pb-4 flex-shrink-0">
            <button onClick={() => { setEditView(null); setEditTarget(null); }} className="flex items-center gap-1.5 text-sm text-white/50 hover:text-white mb-5"><ArrowLeft size={16} /> Back</button>
            <h3 className="text-2xl font-bold text-white mb-0.5">{editView === 'edit-chapter' ? 'Edit Chapter' : 'Create Chapter'}</h3>
            <p className="text-white/50 text-sm">for {subjectData?.name}</p>
          </div>
          {/* Scrollable form body that fills remaining space */}
          <div className="flex-1 flex flex-col min-h-0 px-8 pb-8 gap-4">
            <div className="flex-shrink-0">
              <label className="text-sm text-white/60 block mb-1.5">Title *</label>
              <input value={contentForm.title} onChange={(e) => setContentForm({ ...contentForm, title: e.target.value })} placeholder="Chapter title" className="w-full h-11 px-4 rounded-xl text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500" />
            </div>
            <div className="flex-shrink-0">
              <label className="text-sm text-white/60 block mb-1.5">Description</label>
              <textarea value={contentForm.description} onChange={(e) => setContentForm({ ...contentForm, description: e.target.value })} rows={2} placeholder="Brief description..." className="w-full px-4 py-3 rounded-xl text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500 resize-none" />
            </div>
            <div className="flex-1 flex flex-col min-h-0">
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-sm text-white/60">Content (Markdown)</label>
                <span className="text-xs text-white/25">{contentForm.content.length} chars</span>
              </div>
              <textarea
                value={contentForm.content}
                onChange={(e) => setContentForm({ ...contentForm, content: e.target.value })}
                placeholder={"# Chapter Title\n\nWrite your content here using **Markdown**.\n\n## Section\n- Bullet points\n- work great\n\n> Blockquotes for definitions\n\n```\nCode blocks supported\n```"}
                className="flex-1 w-full px-4 py-3 rounded-xl text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500 resize-none font-mono text-sm leading-relaxed"
                style={{ minHeight: '200px' }}
              />
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

          {/* Right panel — content area */}
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
                    <button key={s.id} onClick={() => setSelSubject(s.id)} className="p-4 rounded-xl border border-white/10 hover:border-violet-500/30 bg-white/[0.02] text-left transition-colors group">
                      <div className="flex items-center justify-between">
                        <p className="text-sm font-medium text-white">{s.icon || '📚'} {s.name}</p>
                        <button onClick={(e) => { e.stopPropagation(); handleDelete('subject', s.id); }} className="p-1 rounded opacity-0 group-hover:opacity-100 text-white/20 hover:text-red-400"><Trash2 size={12} /></button>
                      </div>
                      <p className="text-xs text-white/40 truncate mt-1">{s.description}</p>
                      <p className="text-[10px] text-white/25 mt-2">{s.chapter_count || 0} chapters</p>
                    </button>
                  ))}
                </div>
                <InlineCreator placeholder="Subject" onCreate={handleCreateSubject} icon={BookOpen} color="violet" />
              </div>
            ) : selSubject ? (
              <div className="p-6 max-w-5xl mx-auto space-y-6">
                <div>
                  <h3 className="text-xl font-bold text-white">{subjectData?.icon || '📚'} {subjectData?.name}</h3>
                  <p className="text-sm text-white/40">{subjectData?.description}</p>
                </div>

                {/* Actions row */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <button onClick={() => { setEditView('new-chapter'); setContentForm({ title: '', description: '', content: '', order: chapters.length + 1 }); }}
                    className="p-5 rounded-xl border border-white/10 hover:border-violet-500/30 bg-white/[0.02] text-center transition-colors">
                    <BookOpen size={28} className="mx-auto text-violet-400 mb-2" />
                    <p className="text-sm font-bold text-white">Create Chapter</p>
                    <p className="text-[11px] text-white/40 mt-1">Add content with markdown</p>
                  </button>
                  <div className="p-5 rounded-xl border border-white/10 hover:border-rose-500/30 bg-white/[0.02] text-center transition-colors">
                    <input ref={docRef} type="file" accept=".pdf,.doc,.docx,.txt,.md" multiple className="hidden" onChange={handleFileUpload} />
                    <FileUp size={28} className="mx-auto text-rose-400 mb-2" />
                    <p className="text-sm font-bold text-white">Upload Documents</p>
                    <div className="flex items-center gap-1.5 justify-center my-2">
                      {CONTENT_TYPES.map(ct => (
                        <button key={ct.id} onClick={() => setContentType(ct.id)}
                          className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${contentType === ct.id ? 'bg-rose-500/20 text-rose-300 border border-rose-500/40' : 'bg-white/5 text-white/40 border border-white/10'}`}
                        >{ct.label}</button>
                      ))}
                    </div>
                    <button onClick={() => docRef.current?.click()} disabled={uploading}
                      className="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold disabled:opacity-40 flex items-center gap-1.5 mx-auto" data-testid="upload-document-btn"
                    >
                      {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                      {uploading ? 'Uploading...' : 'Choose Files'}
                    </button>
                  </div>
                </div>

                {/* Chapters */}
                <div className="space-y-2">
                  <p className="text-sm font-semibold text-white">Chapters ({chapters.length})</p>
                  {chapters.length === 0 && <p className="text-xs text-white/30 py-4 text-center">No chapters yet</p>}
                  {chapters.map(ch => (
                    <div key={ch.id} className="p-3 rounded-xl border border-white/10 hover:border-violet-500/20 bg-white/[0.02] flex items-start justify-between transition-colors">
                      <div className="flex items-center gap-2 min-w-0">
                        <Book size={14} className="text-violet-400 flex-shrink-0" />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-white truncate">{ch.title}</p>
                          {ch.description && <p className="text-xs text-white/40 truncate">{ch.description}</p>}
                        </div>
                      </div>
                      <div className="flex gap-0.5 flex-shrink-0">
                        <button onClick={() => setViewerItem(ch)} className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-white/30 hover:text-emerald-400" title="Open" data-testid={`open-chapter-${ch.id}`}><Eye size={14} /></button>
                        <button onClick={() => { setEditTarget(ch); setContentForm({ title: ch.title, description: ch.description || '', content: ch.content || '', order: ch.order || 1 }); setEditView('edit-chapter'); }}
                          className="p-1.5 rounded-lg hover:bg-violet-500/10 text-white/30 hover:text-violet-400"><Edit2 size={14} /></button>
                        <button onClick={() => handleDeleteChapter(ch.id)} className="p-1.5 rounded-lg hover:bg-red-500/10 text-white/30 hover:text-red-400"><Trash2 size={14} /></button>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Uploaded documents */}
                <div className="space-y-2">
                  <p className="text-sm font-semibold text-white">Documents ({uploads.length})</p>
                  {uploads.length === 0 && <p className="text-xs text-white/30 py-4 text-center">No documents yet</p>}
                  {uploads.map(doc => (
                    <div key={doc.id} className="p-3 rounded-xl border border-white/10 hover:border-rose-500/20 bg-white/[0.02] flex items-start justify-between transition-colors">
                      <div className="flex items-center gap-2 min-w-0">
                        {doc.file_ext === 'pdf' ? <FileText size={14} className="text-rose-400 flex-shrink-0" /> : <File size={14} className="text-blue-400 flex-shrink-0" />}
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium text-white truncate">{doc.title || doc.file_name}</p>
                            <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-white/30 uppercase flex-shrink-0">{doc.content_type || doc.file_ext}</span>
                          </div>
                          <div className="flex gap-2 text-[11px] text-white/30 mt-0.5">
                            {doc.year && <span>Year: {doc.year}</span>}
                            {doc.file_size && <span>{(doc.file_size / 1024).toFixed(0)} KB</span>}
                          </div>
                        </div>
                      </div>
                      <div className="flex gap-0.5 flex-shrink-0">
                        <button onClick={() => setViewerItem(doc)} className="p-1.5 rounded-lg hover:bg-emerald-500/10 text-white/30 hover:text-emerald-400" title="Open" data-testid={`open-doc-${doc.id}`}><Eye size={14} /></button>
                        <button onClick={() => handleDeleteUpload(doc.id)} className="p-1.5 rounded-lg hover:bg-red-500/10 text-white/30 hover:text-red-400"><Trash2 size={14} /></button>
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
      )}

      {/* Syllabus Manager Tab */}
      {activeTab === 'syllabus' && (
        <div className="flex-1 overflow-y-auto p-6 max-w-4xl mx-auto w-full">
          <AdminSyllabusManager
            adminToken={adminToken}
            boards={boards}
            classes={classes}
            streams={streams}
          />
        </div>
      )}

      {viewerItem && <ContentViewerPopup item={viewerItem} onClose={() => setViewerItem(null)} />}
    </div>
  );
}
