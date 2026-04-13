import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Layers, ChevronRight, Trash2, Loader2, Edit2, AlignLeft } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { isDegreeBoard } from '@/utils/courseTypes';
import { API, authHeaders, autoSlug } from '@/utils/adminHelpers';

import ContentViewerPopup from './content-editor/ContentViewerPopup';
import InlineCreator from './content-editor/InlineCreator';
import ChapterEditForm from './content-editor/ChapterEditForm';
import HierarchyTree from './content-editor/HierarchyTree';
import ChapterList from './content-editor/ChapterList';
import ThumbnailStudio from './content-editor/ThumbnailStudio';
import ConfirmDialog from './content-editor/ConfirmDialog';

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
  const [contentForm, setContentForm] = useState({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: 1, topics: [], content_as: '' });
  const [editTarget, setEditTarget] = useState(null);
  const [saving, setSaving] = useState(false);
  const [chapterStats, setChapterStats] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [aiParsing, setAiParsing] = useState(false);
  const [generatingNotes, setGeneratingNotes] = useState(new Set());
  const fileInputRef = useRef(null);
  const editorRef = useRef(null);

  const [showPreview, setShowPreview] = useState(false);
  const [chapterAssets, setChapterAssets] = useState({});
  const [editorKey, setEditorKey] = useState(0);
  const [editingSubject, setEditingSubject] = useState(null);
  const [subjectEditForm, setSubjectEditForm] = useState({ name: '', description: '' });
  const [savingSubject, setSavingSubject] = useState(false);
  const [bulkGenerating, setBulkGenerating] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState({ open: false, title: '', message: '', onConfirm: null });

  const subjectData = subjects.find(s => s.id === selSubject);
  const boardData = boards.find(b => b.id === selBoard);
  const classData = classes.find(c => c.id === selClass);
  const streamData = streams.find(s => s.id === selStream);
  const isBoardDegree = isDegreeBoard(boardData?.name);
  const streamNodeLabel = isBoardDegree ? 'Courses' : 'Streams';
  const streamPlaceholder = isBoardDegree ? 'Course Type' : 'Stream';
  const filteredClasses = selBoard ? classes.filter(c => c.board_id === selBoard) : [];
  const filteredStreams = selClass ? streams.filter(s => s.class_id === selClass) : [];
  const filteredSubjects = selStream ? subjects.filter(s => s.stream_id === selStream) : subjects;
  const searchFiltered = searchQuery
    ? subjects.filter(s => s.name?.toLowerCase().includes(searchQuery.toLowerCase()) || s.description?.toLowerCase().includes(searchQuery.toLowerCase()))
    : null;

  const loadChapterCards = useCallback(async (subjectId) => {
    if (!subjectId) return;
    try {
      const res = await axios.get(`${API}/admin/content/subject/${subjectId}/chapter-cards`, authHeaders(adminToken));
      const cardsMap = {};
      for (const c of (res.data?.cards || [])) {
        cardsMap[c.chapter_id] = {
          notesGenerated: c.notes_generated,
          pyqCount: c.pyq_count,
          markWiseCounts: c.mark_wise_counts || {},
          flashcardCount: c.flashcard_count,
          blogCount: c.blog_count,
          seoTopicCount: c.seo_topic_count || 0,
          linkedTopics: c.linked_topics || [],
          seoPageTypes: c.seo_page_types || {},
          seoPagesPublished: c.seo_pages_published || 0,
          pyqPage: false,
          wordCount: c.word_count || 0,
        };
      }
      setChapterAssets(cardsMap);
    } catch { /* fallback: individual stats calls via loadChapterStats */ }
  }, [adminToken]);

  useEffect(() => { if (selSubject) loadChapterCards(selSubject); }, [selSubject, loadChapterCards]);

  const loadChapterStats = useCallback(async (chapterId) => {
    try {
      const res = await axios.get(`${API}/admin/content/chapters/${chapterId}/stats`, authHeaders(adminToken));
      setChapterStats(res.data);
      if (chapterId) {
        setChapterAssets(prev => ({ ...prev, [chapterId]: {
          ...prev[chapterId],
          notesGenerated: res.data.notes_generated,
          pyqCount: res.data.pyq_count || 0,
          markWiseCounts: res.data.mark_wise_counts || {},
          flashcardCount: res.data.flashcard_count || 0,
          blogCount: res.data.geo_blog_count || 0,
          pyqPage: res.data.pyq_html_count > 0,
          seoTopicCount: res.data.seo_topic_count || 0,
          linkedTopics: res.data.linked_topics || [],
          seoPageTypes: res.data.seo_page_types || {},
          seoPagesPublished: res.data.seo_pages_published || 0,
        }}));
      }
    } catch { setChapterStats(null); }
  }, [adminToken]);

  const handleFileAttach = useCallback(async (chapterId) => {
    const file = fileInputRef.current?.files?.[0];
    if (!file || !chapterId) return;
    if (file.size > 10 * 1024 * 1024) { toast.error('File too large (max 10 MB)'); return; }
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (!['pdf', 'txt', 'md'].includes(ext)) { toast.error('Only pdf, txt, md files allowed'); return; }
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
    } catch (e) { toast.error(e.response?.data?.detail || 'File upload failed'); }
    finally { setUploading(false); if (fileInputRef.current) fileInputRef.current.value = ''; }
  }, [adminToken, selSubject, loadChapterStats]);

  const handleAiParse = useCallback(async () => {
    if (!contentForm.content.trim()) return toast.error('Add content first');
    setAiParsing(true);
    try {
      const res = await axios.post(`${API}/admin/studio/parse`, { raw_text: contentForm.content, subject: subjects.find(s => s.id === selSubject)?.name || '', chapter: contentForm.title || '' }, authHeaders(adminToken));
      const blocks = res.data.blocks || [];
      if (blocks.length === 0) return toast.error('AI could not parse content');
      setContentForm(f => ({ ...f, content: blocks.map(b => `## ${b.title}\n\n${b.content}`).join('\n\n---\n\n') }));
      toast.success(`AI structured ${blocks.length} blocks`);
    } catch (e) { toast.error(e.response?.data?.detail || 'AI parsing failed'); }
    finally { setAiParsing(false); }
  }, [contentForm.content, contentForm.title, selSubject, subjects]);

  const load = useCallback(async (bustCache = false) => {
    try {
      const nc = bustCache ? '?nocache=1' : '';
      const [b, c, s, sub] = await Promise.all([axios.get(`${API}/content/boards${nc}`), axios.get(`${API}/content/classes${nc}`), axios.get(`${API}/content/streams${nc}`), axios.get(`${API}/content/subjects${nc}`)]);
      setBoards(b.data || []); setClasses(c.data || []); setStreams(s.data || []); setSubjects(sub.data || []);
    } catch { toast.error('Failed to load content data'); }
  }, []);

  useEffect(() => { load(true); }, [load]);
  useEffect(() => { try { const raw = localStorage.getItem('syrabit_editor_prefill'); if (!raw) return; const pf = JSON.parse(raw); if (Date.now() - (pf.timestamp || 0) > 10 * 60 * 1000) { localStorage.removeItem('syrabit_editor_prefill'); return; } localStorage.removeItem('syrabit_editor_prefill'); setContentForm(f => ({ ...f, title: pf.title || f.title || '', content: pf.content || f.content || '' })); setEditView('new-chapter'); toast.success(`Pre-filled from CMS Doc "${pf.title || 'Untitled'}" — select a subject and save`); } catch {} }, []);
  useEffect(() => { if (!hubContext?.subjectId || !subjects.length || selSubject) return; const sub = subjects.find(s => s.id === hubContext.subjectId); if (!sub) return; setSelBoard(hubContext.boardId || null); setSelClass(hubContext.classId || null); setSelStream(hubContext.streamId || null); setSelSubject(sub.id); }, [hubContext?.subjectId, subjects]);
  useEffect(() => { if (!onHubContext || !selSubject) return; const sub = subjects.find(s => s.id === selSubject); const str = streams.find(s => s.id === selStream); const cls = classes.find(c => c.id === selClass); const brd = boards.find(b => b.id === selBoard); onHubContext({ boardId: selBoard || '', boardName: brd?.name || '', classId: selClass || '', className: cls?.name || '', streamId: selStream || '', streamName: str?.name || '', subjectId: selSubject, subjectName: sub?.name || '' }); }, [selSubject]);

  const refreshChapters = (subjectId) => {
    axios.get(`${API}/admin/content/chapters/${subjectId}`, authHeaders(adminToken))
      .then(r => { setChapters(r.data || []); axios.get(`${API}/admin/content/chapters/${subjectId}/coverage`, authHeaders(adminToken)).then(covRes => { const covMap = {}; (covRes.data?.chapters || []).forEach(c => { covMap[c.chapter_id] = c.coverage_score; }); setChapters(prev => prev.map(ch => ({ ...ch, coverage_score: covMap[ch.id] ?? ch.coverage_score ?? null }))); }).catch(() => {}); })
      .catch(() => toast.error('Could not reload chapter list'));
  };

  useEffect(() => { if (selSubject) refreshChapters(selSubject); }, [selSubject]);

  const handleCreateBoard = async (name, desc) => { await axios.post(`${API}/admin/content/boards`, { name, description: desc }, authHeaders(adminToken)); await load(true); toast.success('Board created'); };
  const handleCreateClass = async (name, desc) => { if (!selBoard) return toast.error('Select a board first'); await axios.post(`${API}/admin/content/classes`, { board_id: selBoard, name, description: desc }, authHeaders(adminToken)); await load(true); toast.success('Class created'); };
  const handleCreateStream = async (name, desc) => { if (!selClass) return toast.error('Select a class first'); await axios.post(`${API}/admin/content/streams`, { class_id: selClass, name, description: desc }, authHeaders(adminToken)); await load(true); toast.success('Stream created'); };
  const handleCreateSubject = async (name, desc) => { if (!selStream) return toast.error('Select a stream first'); await axios.post(`${API}/admin/content/subjects`, { stream_id: selStream, name, description: desc, tags: '', status: 'published' }, authHeaders(adminToken)); await load(true); toast.success('Subject created'); };

  const handleDelete = (type, id) => {
    const label = type === 'classe' ? 'class' : type;
    setConfirmDialog({
      open: true,
      title: `Delete ${label}?`,
      message: `This will permanently delete this ${label} and all content inside it. This action cannot be undone.`,
      onConfirm: async () => {
        setConfirmDialog(d => ({ ...d, open: false }));
        try {
          await axios.delete(`${API}/admin/content/${type}s/${id}`, authHeaders(adminToken));
          if (type === 'board') { if (selBoard === id) { setSelBoard(null); setSelClass(null); setSelStream(null); setSelSubject(null); } }
          if (type === 'classe') { if (selClass === id) { setSelClass(null); setSelStream(null); setSelSubject(null); } }
          if (type === 'stream') { setSelStream(null); setSelSubject(null); }
          if (type === 'subject') { if (selSubject === id) setSelSubject(null); }
          await load(true); toast.success(`${label} deleted`);
        } catch (e) { toast.error(e.response?.data?.detail || `Failed to delete ${label}`); }
      },
    });
  };

  const handleCreateChapter = async () => {
    if (!selSubject || !contentForm.title) return;
    setSaving(true);
    try {
      const slug = contentForm.slug || autoSlug(contentForm.title);
      const topics = (contentForm.topics || []).filter(Boolean);
      const createPayload = { subject_id: selSubject, title: contentForm.title, slug, description: contentForm.description, content: contentForm.content, content_type: contentForm.content_type, order: contentForm.order, status: 'published', topics };
      if (contentForm.content_as) createPayload.content_as = contentForm.content_as;
      await axios.post(`${API}/admin/content/chapters`, createPayload, authHeaders(adminToken));
      toast.success('Chapter created successfully'); setEditView(null); setContentForm({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: 1, topics: [], content_as: '' }); setChapterStats(null); refreshChapters(selSubject);
    } catch { toast.error('Failed to create chapter'); }
    finally { setSaving(false); }
  };

  const handleUpdateChapter = async () => {
    if (!editTarget || !contentForm.title) return;
    setSaving(true);
    try {
      const slug = contentForm.slug || autoSlug(contentForm.title);
      const topics = (contentForm.topics || []).filter(Boolean);
      const updatePayload = { title: contentForm.title, slug, description: contentForm.description, content: contentForm.content, content_type: contentForm.content_type, order: contentForm.order, topics };
      if (contentForm.content_as !== undefined) updatePayload.content_as = contentForm.content_as;
      await axios.patch(`${API}/admin/content/chapters/${editTarget.id}`, updatePayload, authHeaders(adminToken));
      toast.success('Chapter updated successfully'); setEditView(null); setEditTarget(null); setContentForm({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: 1, topics: [], content_as: '' }); setChapterStats(null); refreshChapters(selSubject);
    } catch { toast.error('Failed to update'); }
    finally { setSaving(false); }
  };

  const handleDeleteChapter = (id) => {
    setConfirmDialog({
      open: true,
      title: 'Delete chapter?',
      message: 'This will permanently delete this chapter and all its associated data.',
      onConfirm: async () => {
        setConfirmDialog(d => ({ ...d, open: false }));
        try { await axios.delete(`${API}/admin/content/chapters/${id}`, authHeaders(adminToken)); setChapters(p => p.filter(c => c.id !== id)); toast.success('Chapter deleted'); } catch { toast.error('Failed to delete'); }
      },
    });
  };

  const handleGenerateNotes = async (chapterId, chapterTitle, { silent = false } = {}) => {
    setGeneratingNotes(prev => new Set([...prev, chapterId]));
    try {
      const res = await axios.post(`${API}/admin/content/chapters/${chapterId}/generate-notes`, {}, authHeaders(adminToken));
      const generated = res.data?.content;
      if (generated) {
        const freshChapters = await axios.get(`${API}/admin/content/chapters/${selSubject}`, authHeaders(adminToken));
        const freshChapter = (freshChapters.data || []).find(c => c.id === chapterId);
        setChapters(prev => prev.map(ch => ch.id === chapterId ? { ...ch, content: generated, content_as: freshChapter?.content_as || ch.content_as || '', content_type: 'notes', notes_generated: true, _word_count: res.data?.word_count } : ch));
        const asMsg = res.data?.content_as_words ? ` + ${res.data.content_as_words} অসমীয়া words` : '';
        if (!silent) toast.success(`Notes generated for "${chapterTitle}"${res.data?.word_count ? ` — ${res.data.word_count.toLocaleString()} words${asMsg}` : ''}`);
        return true;
      }
      return false;
    } catch (e) {
      if (!silent) toast.error(e?.response?.data?.detail || `Failed to generate notes for "${chapterTitle}"`);
      return false;
    } finally { setGeneratingNotes(prev => { const next = new Set(prev); next.delete(chapterId); return next; }); }
  };

  const handleUpdateSubject = async () => {
    if (!editingSubject || !subjectEditForm.name.trim()) return;
    setSavingSubject(true);
    try {
      await axios.patch(`${API}/admin/content/subjects/${editingSubject}`, { name: subjectEditForm.name.trim(), description: subjectEditForm.description.trim() }, authHeaders(adminToken));
      toast.success('Subject updated');
      setEditingSubject(null);
      await load(true);
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed to update subject'); }
    finally { setSavingSubject(false); }
  };

  const handleBulkFormatNotes = async () => {
    if (!selSubject || chapters.length === 0) return;
    const withContent = chapters.filter(ch => ch.content && ch.content.trim().length > 30);
    if (withContent.length === 0) { toast.info('No chapters with content to format'); return; }
    const confirmed = await new Promise((resolve) => {
      setConfirmDialog({
        open: true,
        title: 'Format all notes?',
        message: `Re-format ${withContent.length} chapter(s) for mobile-responsive textbook layout. No content will be generated — only structural formatting and alignment.`,
        confirmLabel: 'Format',
        destructive: false,
        onConfirm: () => { setConfirmDialog(d => ({ ...d, open: false })); resolve(true); },
        onCancel: () => { setConfirmDialog(d => ({ ...d, open: false })); resolve(false); },
      });
    });
    if (!confirmed) return;
    setBulkGenerating(true);
    try {
      const res = await axios.post(`${API}/admin/content/subject/${selSubject}/format-notes`, {}, authHeaders(adminToken));
      const data = res.data;
      toast.success(data.message || `Formatted ${data.chapters_formatted} chapters`);
      refreshChapters(selSubject);
      loadChapterCards(selSubject);
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to format notes');
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
    <div className="h-full flex flex-col" style={{ background: '#f8f9fc' }}>
      <>
        <div className="h-14 border-b border-gray-200 flex items-center justify-between px-6 bg-white">
          <div className="flex items-center gap-2 min-w-0">
            {breadcrumb.length > 0 && (
              <div className="flex items-center gap-1 text-sm text-gray-400 min-w-0 overflow-hidden">
                {breadcrumb.map((b, i) => (
                  <span key={i} className="flex items-center gap-1 min-w-0">
                    <ChevronRight size={12} className="flex-shrink-0" />
                    <button onClick={b.onClick} className="hover:text-violet-600 truncate max-w-[120px] transition-colors">{b.label}</button>
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="relative flex-shrink-0 w-64">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search all subjects..." className="w-full h-9 pl-8 pr-3 rounded-xl text-sm text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-500/20" data-testid="search-subjects" />
          </div>
        </div>

        {searchQuery && searchFiltered ? (
          <div className="flex-1 overflow-y-auto p-6">
            <p className="text-sm text-gray-400 mb-4">{searchFiltered.length} subject(s) matching "{searchQuery}"</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {searchFiltered.map(s => (
                <button key={s.id} onClick={() => { setSearchQuery(''); const st = streams.find(x => x.id === s.stream_id); if (st) { const cl = classes.find(x => x.id === st.class_id); if (cl) setSelBoard(cl.board_id); setSelClass(st.class_id); } setSelStream(s.stream_id); setSelSubject(s.id); }}
                  className="p-4 rounded-xl border border-gray-200 hover:border-violet-300 bg-white text-left transition-colors shadow-sm">
                  <p className="text-sm font-medium text-gray-900">{s.icon} {s.name}</p>
                  <p className="text-xs text-gray-400 truncate mt-1">{s.description}</p>
                </button>
              ))}
              {searchFiltered.length === 0 && <p className="text-gray-400 text-sm col-span-3">No subjects found</p>}
            </div>
          </div>
        ) : editView === 'new-chapter' || editView === 'edit-chapter' ? (
          <ChapterEditForm
            editView={editView} editTarget={editTarget} contentForm={contentForm} setContentForm={setContentForm}
            subjectData={subjectData} saving={saving} chapterStats={chapterStats}
            onSave={editView === 'edit-chapter' ? handleUpdateChapter : handleCreateChapter}
            onCancel={() => { setEditView(null); setEditTarget(null); setChapterStats(null); }}
            onFileAttach={handleFileAttach} uploading={uploading}
            onAiParse={handleAiParse} aiParsing={aiParsing} onLoadChapterStats={loadChapterStats}
            editorRef={editorRef} editorKey={editorKey} setEditorKey={setEditorKey}
            showPreview={showPreview} setShowPreview={setShowPreview}
            fileInputRef={fileInputRef}
            adminToken={adminToken} boardId={selBoard} classId={selClass} streamId={selStream}
          />
        ) : (
          <div className="flex-1 flex overflow-hidden">
            <HierarchyTree
              boards={boards} filteredClasses={filteredClasses} filteredStreams={filteredStreams}
              selBoard={selBoard} setSelBoard={setSelBoard} selClass={selClass} setSelClass={setSelClass}
              selStream={selStream} setSelStream={setSelStream} setSelSubject={setSelSubject} setEditView={setEditView}
              streamNodeLabel={streamNodeLabel} streamPlaceholder={streamPlaceholder}
              onDelete={handleDelete} onCreateBoard={handleCreateBoard} onCreateClass={handleCreateClass} onCreateStream={handleCreateStream}
            />
            <div className="flex-1 overflow-y-auto">
              {!selStream && !selSubject ? (
                <div className="flex items-center justify-center h-full">
                  <div className="text-center max-w-md">
                    <Layers size={56} className="mx-auto text-gray-200 mb-4" />
                    <h3 className="text-xl font-bold text-gray-900 mb-2">All-in-One Content Manager</h3>
                    <p className="text-gray-500 text-sm mb-2">Navigate the tree on the left: Board → Class → {streamPlaceholder} → Subject</p>
                    <p className="text-gray-400 text-xs">Or use the search bar to find any subject</p>
                  </div>
                </div>
              ) : selStream && !selSubject ? (
                <div className="p-6 max-w-4xl mx-auto space-y-4">
                  <div className="mb-2">
                    <h3 className="text-xl font-bold text-gray-900">{streamData?.icon} {streamData?.name}</h3>
                    <p className="text-sm text-gray-400">{streamData?.description}</p>
                  </div>
                  <p className="text-sm font-semibold text-gray-500">Subjects ({filteredSubjects.length})</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {filteredSubjects.map(s => (
                      <div key={s.id} className="p-4 rounded-xl border border-gray-200 hover:border-violet-300 bg-white text-left transition-colors group cursor-pointer shadow-sm" onClick={() => setSelSubject(s.id)}>
                        <div className="flex items-center justify-between">
                          <p className="text-sm font-medium text-gray-900">{s.icon || '📚'} {s.name}</p>
                          <div className="flex items-center gap-1">
                            <button onClick={(e) => { e.stopPropagation(); setEditingSubject(s.id); setSubjectEditForm({ name: s.name || '', description: s.description || '' }); }} className="p-1 rounded opacity-0 group-hover:opacity-100 text-gray-300 hover:text-violet-600"><Edit2 size={12} /></button>
                            <button onClick={(e) => { e.stopPropagation(); handleDelete('subject', s.id); }} className="p-1 rounded opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-500"><Trash2 size={12} /></button>
                          </div>
                        </div>
                        {editingSubject === s.id ? (
                          <div className="mt-2 space-y-2" onClick={(e) => e.stopPropagation()}>
                            <input value={subjectEditForm.name} onChange={(e) => setSubjectEditForm(f => ({ ...f, name: e.target.value }))} className="w-full h-8 px-3 rounded-lg text-sm text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-400" autoFocus />
                            <input value={subjectEditForm.description} onChange={(e) => setSubjectEditForm(f => ({ ...f, description: e.target.value }))} placeholder="Description" className="w-full h-8 px-3 rounded-lg text-sm text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-400" />
                            <div className="flex gap-2">
                              <button onClick={() => setEditingSubject(null)} className="flex-1 h-7 rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-600 text-xs">Cancel</button>
                              <button onClick={handleUpdateSubject} disabled={savingSubject || !subjectEditForm.name.trim()} className="flex-1 h-7 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-xs font-medium disabled:opacity-40 flex items-center justify-center gap-1">
                                {savingSubject ? <Loader2 size={10} className="animate-spin" /> : null} Save
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <p className="text-xs text-gray-400 truncate mt-1">{s.description}</p>
                            <div className="flex items-center justify-between mt-2">
                              <p className="text-[10px] text-gray-400">{s.chapter_count || 0} chapters</p>
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                  <InlineCreator placeholder="Subject" onCreate={handleCreateSubject} icon={Layers} color="violet" />
                </div>
              ) : selSubject ? (
                <div className="p-6 max-w-5xl mx-auto space-y-5">
                  <div className="flex items-start justify-between">
                    {editingSubject === selSubject ? (
                      <div className="flex-1 max-w-md space-y-2">
                        <input value={subjectEditForm.name} onChange={(e) => setSubjectEditForm(f => ({ ...f, name: e.target.value }))} className="w-full h-10 px-4 rounded-xl text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-400 text-lg font-bold" autoFocus />
                        <input value={subjectEditForm.description} onChange={(e) => setSubjectEditForm(f => ({ ...f, description: e.target.value }))} placeholder="Description" className="w-full h-9 px-4 rounded-xl text-sm text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-400" />
                        <div className="flex gap-2">
                          <button onClick={() => setEditingSubject(null)} className="h-8 px-4 rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-600 text-xs">Cancel</button>
                          <button onClick={handleUpdateSubject} disabled={savingSubject || !subjectEditForm.name.trim()} className="h-8 px-4 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-xs font-medium disabled:opacity-40 flex items-center justify-center gap-1">
                            {savingSubject ? <Loader2 size={10} className="animate-spin" /> : null} Save
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-xl font-bold text-gray-900">{subjectData?.icon} {subjectData?.name}</h3>
                          <button onClick={() => { setEditingSubject(selSubject); setSubjectEditForm({ name: subjectData?.name || '', description: subjectData?.description || '' }); }} className="p-1 rounded text-gray-300 hover:text-violet-600"><Edit2 size={14} /></button>
                        </div>
                        <p className="text-sm text-gray-400">{subjectData?.description}</p>
                      </div>
                    )}
                    {chapters.length > 0 && (
                      <button
                        onClick={handleBulkFormatNotes}
                        disabled={bulkGenerating || generatingNotes.size > 0}
                        className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold disabled:opacity-40 transition-all bg-violet-50 text-violet-600 border border-violet-200 hover:bg-violet-100"
                      >
                        {bulkGenerating ? <Loader2 size={12} className="animate-spin" /> : <AlignLeft size={12} />}
                        {bulkGenerating ? 'Formatting...' : 'Format Notes'}
                      </button>
                    )}
                  </div>
                  <ThumbnailStudio adminToken={adminToken} selSubject={selSubject} subjectData={subjectData} onReload={() => load(true)} />
                  <ChapterList
                    chapters={chapters} chapterAssets={chapterAssets}
                    generatingNotes={generatingNotes}
                    onGenerateNotes={handleGenerateNotes} onDeleteChapter={handleDeleteChapter}
                    onViewChapter={(ch) => setViewerItem(ch)}
                    onEditChapter={(ch) => { setEditTarget(ch); setContentForm({ title: ch.title, slug: ch.slug || '', description: ch.description || '', content: ch.content || '', content_type: ch.content_type || 'notes', order: ch.order || 1, topics: ch.topics || [], content_as: ch.content_as || '' }); setEditView('edit-chapter'); loadChapterStats(ch.id); }}
                    selSubject={selSubject} subjectData={subjectData}
                    onCreateNew={() => { setEditView('new-chapter'); setContentForm({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: chapters.length + 1, topics: [], content_as: '' }); setChapterStats(null); }}
                  />
                </div>
              ) : null}
            </div>
          </div>
        )}
      </>

      {viewerItem && <ContentViewerPopup item={viewerItem} onClose={() => setViewerItem(null)} />}
      <ConfirmDialog
        open={confirmDialog.open}
        title={confirmDialog.title}
        message={confirmDialog.message}
        confirmLabel={confirmDialog.confirmLabel || 'Delete'}
        destructive={confirmDialog.destructive !== false}
        onConfirm={confirmDialog.onConfirm || (() => setConfirmDialog(d => ({ ...d, open: false })))}
        onCancel={confirmDialog.onCancel || (() => setConfirmDialog(d => ({ ...d, open: false })))}
      />
    </div>
  );
}
