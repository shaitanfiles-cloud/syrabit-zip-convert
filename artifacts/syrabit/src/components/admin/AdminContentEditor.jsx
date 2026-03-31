import { useState, useEffect, useRef, useCallback } from 'react';
import { Search, Layers, ChevronRight, CheckCircle, Trash2, Globe, Loader2 } from 'lucide-react';
import PipelineProgressPanel from './PipelineProgressPanel';
import AgenticCreatorModal from './AgenticCreatorModal';
import { toast } from 'sonner';
import axios from 'axios';
import { adminSeoExtractTopics } from '@/utils/api';
import { isDegreeBoard } from '@/utils/courseTypes';
import { API, authHeaders, autoSlug } from '@/utils/adminHelpers';

import ContentViewerPopup from './content-editor/ContentViewerPopup';
import InlineCreator from './content-editor/InlineCreator';
import ChapterEditForm from './content-editor/ChapterEditForm';
import HierarchyTree from './content-editor/HierarchyTree';
import ChapterList from './content-editor/ChapterList';
import ContentGapsPanel from './content-editor/ContentGapsPanel';
import ThumbnailStudio from './content-editor/ThumbnailStudio';
import WorkflowTracker from './content-editor/WorkflowTracker';

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
  const [chapterStats, setChapterStats] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [aiParsing, setAiParsing] = useState(false);
  const [generatingNotes, setGeneratingNotes] = useState(new Set());
  const [bulkGenerating, setBulkGenerating] = useState(false);
  const [showAgenticCreator, setShowAgenticCreator] = useState(false);
  const [autoAgentic, setAutoAgentic] = useState(false);
  const fileInputRef = useRef(null);
  const editorRef = useRef(null);

  const [publishingBlog, setPublishingBlog] = useState(false);
  const [selectedChapters, setSelectedChapters] = useState(new Set());
  const [bulkMerging, setBulkMerging] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [mergedSubjectIds, setMergedSubjectIds] = useState(new Set());
  const [seoTopicsGeneratedIds, setSeoTopicsGeneratedIds] = useState(new Set());
  const [assetsGeneratedIds, setAssetsGeneratedIds] = useState(new Set());
  const [chapterAssets, setChapterAssets] = useState({});
  const [generatingSeoTopics, setGeneratingSeoTopics] = useState(false);
  const [editorKey, setEditorKey] = useState(0);
  const [showPipeline, setShowPipeline] = useState(false);

  const [showGapPanel, setShowGapPanel] = useState(false);
  const [gapSubjects, setGapSubjects] = useState([]);
  const [loadingGaps, setLoadingGaps] = useState(false);
  const [gapGenStatus, setGapGenStatus] = useState({});
  const [gapGenSubject, setGapGenSubject] = useState(null);
  const [bulkGapSelected, setBulkGapSelected] = useState(new Set());
  const [bulkGapGenerating, setBulkGapGenerating] = useState(false);
  const [bulkGapProgress, setBulkGapProgress] = useState({ done: 0, total: 0 });

  useEffect(() => { setSelectedChapters(new Set()); }, [selSubject]);

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
  const allChaptersHaveNotes = chapters.length > 0 && chapters.every(ch => ch.notes_generated || (ch.content && ch.content.trim().length > 100));

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

  const handlePublishAsBlog = useCallback(async (subjectId, subjectName) => {
    if (!subjectId) return;
    setPublishingBlog(true);
    try {
      const res = await axios.post(`${API}/admin/cms/merge/${subjectId}`, {}, authHeaders(adminToken));
      const mergedMd = res.data?.merged_md || res.data?.content || '';
      const toSlug = str => (str || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      const subjectSlug = res.data?.slug || toSlug(subjectName || subjectId);
      const classSlug = res.data?.class_slug || '';
      const autoSeoSlug = [subjectSlug, classSlug].filter(Boolean).join('-').replace(/-+/g, '-').replace(/^-|-$/g, '');
      const className = res.data?.class_name || '';
      const resolvedTitle = res.data?.title || subjectName || subjectId;
      const richTitle = [resolvedTitle, className].filter(Boolean).join(' — ');
      const autoKeyword = `${toSlug(resolvedTitle).replace(/-/g, ' ')}${className ? ` ${className.toLowerCase()}` : ' ahsec'} notes`;
      localStorage.setItem('syrabit_blog_prefill', JSON.stringify({ subjectId, subjectName: resolvedTitle, workingTitle: richTitle, primaryKeyword: autoKeyword, draftContent: mergedMd, docId: res.data?.doc_id || null, seoSlug: autoSeoSlug, autoFlow: true, timestamp: Date.now() }));
      localStorage.setItem('syrabit_cms_prefill', JSON.stringify({ subjectId, title: richTitle, content: mergedMd, seo_slug: autoSeoSlug || toSlug(subjectName || subjectId), meta_description: `Complete ${resolvedTitle}${className ? ` (${className})` : ''} notes, chapters, and PYQ for Assam students on Syrabit.`, timestamp: Date.now() }));
      setMergedSubjectIds(s => new Set([...s, subjectId]));
      toast.success(`"${subjectName}" merged — opening Blog Publisher`);
      onNavigate?.('blog');
    } catch (e) { toast.error(e.response?.data?.detail || 'Merge failed'); }
    finally { setPublishingBlog(false); }
  }, [adminToken, onNavigate]);

  const handleBulkMerge = useCallback(async () => {
    if (!selSubject || selectedChapters.size === 0) return;
    setBulkMerging(true);
    try {
      const res = await axios.post(`${API}/admin/cms/merge/${selSubject}`, {}, authHeaders(adminToken));
      const mergedMd = res.data?.merged_md || res.data?.content || '';
      const toSlug = str => (str || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      const subjectSlug = res.data?.slug || toSlug(subjectData?.name || selSubject);
      const classSlug = res.data?.class_slug || '';
      const autoSeoSlug = [subjectSlug, classSlug].filter(Boolean).join('-').replace(/-+/g, '-').replace(/^-|-$/g, '');
      const resolvedTitle = res.data?.title || subjectData?.name || selSubject;
      const className = res.data?.class_name || '';
      const richTitle = [resolvedTitle, className].filter(Boolean).join(' — ');
      localStorage.setItem('syrabit_cms_prefill', JSON.stringify({ subjectId: selSubject, title: richTitle, content: mergedMd, seo_slug: autoSeoSlug || toSlug(subjectData?.name || selSubject), meta_description: `Complete ${resolvedTitle}${className ? ` (${className})` : ''} notes, chapters, and PYQ for Assam students on Syrabit.`, timestamp: Date.now() }));
      setMergedSubjectIds(s => new Set([...s, selSubject]));
      setSelectedChapters(new Set());
      toast.success(`${selectedChapters.size} chapters merged — opening CMS Editor`);
      onNavigate?.('cms');
    } catch (e) { toast.error(e.response?.data?.detail || 'Bulk merge failed'); }
    finally { setBulkMerging(false); }
  }, [adminToken, selSubject, subjectData, selectedChapters, onNavigate]);

  const handleGenerateSeoTopics = useCallback(async () => {
    if (!selSubject) return;
    const subjectName = subjects.find(s => s.id === selSubject)?.name || selSubject;
    setGeneratingSeoTopics(true);
    toast.loading(`Extracting SEO topics for "${subjectName}"…`, { id: 'seo-extract' });
    try {
      const res = await adminSeoExtractTopics(adminToken, selSubject, false);
      const d = res.data || {};
      setSeoTopicsGeneratedIds(prev => new Set([...prev, selSubject]));
      const topicCount = (d.created || 0) + (d.skipped || 0);
      toast.success(`${topicCount} SEO topics ready for "${subjectName}" — now run Full Pipeline to generate ${topicCount * 5}+ pages`, { id: 'seo-extract', duration: 8000, action: { label: 'Run Full Pipeline →', onClick: () => setShowPipeline(true) } });
      onNavigate?.('seomanager', { subjectId: selSubject, subjectName });
    } catch (e) { toast.error(e?.response?.data?.detail || 'SEO topic extraction failed', { id: 'seo-extract' }); }
    finally { setGeneratingSeoTopics(false); }
  }, [adminToken, selSubject, subjects, onNavigate]);

  const loadGapSubjects = useCallback(async () => {
    setLoadingGaps(true);
    try {
      const res = await axios.get(`${API}/content/subjects`);
      setGapSubjects((res.data || []).filter(s => (s.chapter_count || 0) < 3));
    } catch { toast.error('Could not load subjects'); }
    finally { setLoadingGaps(false); }
  }, []);

  const handleAutoGenerateGap = useCallback(async (s) => {
    setGapGenSubject(s.id);
    setGapGenStatus(prev => ({ ...prev, [s.id]: 'generating' }));
    try {
      const prompt = `Generate comprehensive educational notes for AssamBoard students on: ${s.name}.\nInclude: key concepts (with AssamBoard exam frequency), textbook definitions, worked examples, PYQ-style questions with marks, and 2 FAQ blocks.`;
      const res = await axios.post(`${API}/admin/studio/parse`, { raw_text: prompt, subject: s.name, chapter: 'Overview' }, { withCredentials: true });
      const parsed = res.data.blocks || [];
      if (!parsed.length) { setGapGenStatus(prev => ({ ...prev, [s.id]: 'failed' })); return; }
      const markdown = parsed.map(b => `## ${b.title}\n\n${b.content}`).join('\n\n---\n\n');
      await axios.post(`${API}/admin/content/chapters`, { subject_id: s.id, title: `${s.name} — Overview`, slug: s.name.toLowerCase().replace(/[^a-z0-9]+/g, '-') + '-overview', content: markdown, content_type: 'notes', order: 1 }, { headers: adminToken && adminToken.split('.').length === 3 ? { Authorization: `Bearer ${adminToken}` } : {}, withCredentials: true });
      setGapGenStatus(prev => ({ ...prev, [s.id]: 'done' }));
      toast.success(`Auto-generated chapter for "${s.name}"`);
      loadGapSubjects();
    } catch { setGapGenStatus(prev => ({ ...prev, [s.id]: 'failed' })); toast.error(`Auto-generate failed for "${s.name}"`); }
    finally { setGapGenSubject(null); }
  }, [adminToken, loadGapSubjects]);

  const handleMergeGapToCms = async (s) => {
    try {
      await axios.post(`${API}/admin/cms/merge/${s.id}`, {}, { headers: adminToken && adminToken.split('.').length === 3 ? { Authorization: `Bearer ${adminToken}` } : {}, withCredentials: true });
      toast.success(`Merged "${s.name}" → CMS`);
      onNavigate?.('cms');
    } catch (e) { toast.error(e.response?.data?.detail || 'Merge failed'); }
  };

  const handleBulkGapAutoGen = async () => {
    const selected = [...bulkGapSelected].map(id => gapSubjects.find(s => s.id === id)).filter(Boolean);
    if (!selected.length) return;
    setBulkGapGenerating(true);
    setBulkGapProgress({ done: 0, total: selected.length });
    await Promise.allSettled(selected.map(s => handleAutoGenerateGap(s).then(() => setBulkGapProgress(p => ({ ...p, done: p.done + 1 })))));
    setBulkGapGenerating(false);
    setBulkGapSelected(new Set());
    toast.success(`Bulk generation complete (${selected.length} subjects)`);
  };

  const load = useCallback(async (bustCache = false) => {
    try {
      const nc = bustCache ? '?nocache=1' : '';
      const [b, c, s, sub] = await Promise.all([axios.get(`${API}/content/boards${nc}`), axios.get(`${API}/content/classes${nc}`), axios.get(`${API}/content/streams${nc}`), axios.get(`${API}/content/subjects${nc}`)]);
      setBoards(b.data || []); setClasses(c.data || []); setStreams(s.data || []); setSubjects(sub.data || []);
    } catch { toast.error('Failed to load content data'); }
  }, []);

  useEffect(() => { load(true); }, [load]);
  useEffect(() => { if (!selSubject) return; loadGapSubjects(); }, [selSubject, loadGapSubjects]);
  useEffect(() => { if (!selSubject || !seoTopicsGeneratedIds.has(selSubject) || assetsGeneratedIds.has(selSubject)) return; toast(`Topics ready — run "Auto-Generate Full Subject" to produce 300+ assets`, { id: `auto-nudge-${selSubject}`, duration: 5000, action: { label: 'Run Now', onClick: () => setShowPipeline(true) } }); }, [seoTopicsGeneratedIds, selSubject]);
  useEffect(() => { if (!selSubject || !assetsGeneratedIds.has(selSubject)) return; toast.success(`Assets ready — click "Publish as Blog" to go live`, { id: `publish-nudge-${selSubject}`, duration: 6000 }); }, [assetsGeneratedIds, selSubject]);
  useEffect(() => { (async () => { try { const res = await axios.get(`${API}/admin/content/cms-documents/merged-subject-ids`, authHeaders(adminToken)); const ids = new Set((res.data || []).filter(Boolean)); if (ids.size > 0) setMergedSubjectIds(prev => new Set([...prev, ...ids])); } catch {} })(); }, [adminToken]);
  useEffect(() => { (async () => { try { const res = await axios.get(`${API}/admin/content/cms-documents/seo-topics-subject-ids`, authHeaders(adminToken)); const ids = new Set((res.data || []).filter(Boolean)); if (ids.size > 0) setSeoTopicsGeneratedIds(prev => new Set([...prev, ...ids])); } catch {} })(); }, [adminToken]);
  useEffect(() => { (async () => { try { const res = await axios.get(`${API}/admin/content/cms-documents/assets-generated-subject-ids`, authHeaders(adminToken)); const ids = new Set((res.data || []).filter(Boolean)); if (ids.size > 0) setAssetsGeneratedIds(prev => new Set([...prev, ...ids])); } catch {} })(); }, [adminToken]);
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

  const handleDelete = async (type, id) => {
    if (!confirm(`Delete this ${type}?`)) return;
    try {
      await axios.delete(`${API}/admin/content/${type}s/${id}`, authHeaders(adminToken));
      if (type === 'board' && selBoard === id) { setSelBoard(null); setSelClass(null); setSelStream(null); setSelSubject(null); }
      if (type === 'classe' && selClass === id) { setSelClass(null); setSelStream(null); setSelSubject(null); }
      if (type === 'stream' && selStream === id) { setSelStream(null); setSelSubject(null); }
      if (type === 'subject' && selSubject === id) setSelSubject(null);
      await load(true); toast.success(`${type} deleted`);
    } catch { toast.error(`Failed to delete ${type}`); }
  };

  const handleCreateChapter = async () => {
    if (!selSubject || !contentForm.title) return;
    setSaving(true);
    try {
      const slug = contentForm.slug || autoSlug(contentForm.title);
      await axios.post(`${API}/admin/content/chapters`, { subject_id: selSubject, title: contentForm.title, slug, description: contentForm.description, content: contentForm.content, content_type: contentForm.content_type, order: contentForm.order, status: 'published' }, authHeaders(adminToken));
      toast.success('Chapter created'); setEditView(null); setContentForm({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: 1 }); setChapterStats(null); refreshChapters(selSubject);
    } catch { toast.error('Failed to create chapter'); }
    finally { setSaving(false); }
  };

  const handleUpdateChapter = async () => {
    if (!editTarget || !contentForm.title) return;
    setSaving(true);
    try {
      const slug = contentForm.slug || autoSlug(contentForm.title);
      await axios.patch(`${API}/admin/content/chapters/${editTarget.id}`, { title: contentForm.title, slug, description: contentForm.description, content: contentForm.content, content_type: contentForm.content_type, order: contentForm.order }, authHeaders(adminToken));
      toast.success('Chapter updated'); setEditView(null); setEditTarget(null); setContentForm({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: 1 }); setChapterStats(null); refreshChapters(selSubject);
    } catch { toast.error('Failed to update'); }
    finally { setSaving(false); }
  };

  const handleDeleteChapter = async (id) => { if (!confirm('Delete this chapter?')) return; try { await axios.delete(`${API}/admin/content/chapters/${id}`, authHeaders(adminToken)); setChapters(p => p.filter(c => c.id !== id)); toast.success('Chapter deleted'); } catch { toast.error('Failed to delete'); } };

  const handleGenerateNotes = async (chapterId, chapterTitle) => {
    setGeneratingNotes(prev => new Set([...prev, chapterId]));
    try {
      const res = await axios.post(`${API}/admin/content/chapters/${chapterId}/generate-notes`, {}, authHeaders(adminToken));
      const generated = res.data?.content;
      if (generated) {
        setChapters(prev => prev.map(ch => ch.id === chapterId ? { ...ch, content: generated, content_type: 'notes', notes_generated: true, _word_count: res.data?.word_count } : ch));
        toast.success(`Notes generated for "${chapterTitle}"${res.data?.word_count ? ` — ${res.data.word_count.toLocaleString()} words` : ''}`, { action: autoAgentic ? undefined : { label: 'Run Agentic ⚡', onClick: () => setShowAgenticCreator(true) } });
        if (autoAgentic) setShowAgenticCreator(true);
      }
    } catch (e) { toast.error(e?.response?.data?.detail || `Failed to generate notes for "${chapterTitle}"`); }
    finally { setGeneratingNotes(prev => { const next = new Set(prev); next.delete(chapterId); return next; }); }
  };

  const handleGenerateAllNotes = async () => {
    if (!selSubject) return;
    const subjectName = subjects.find(s => s.id === selSubject)?.name || selSubject;
    if (!confirm(`Generate AI notes for all ${chapters.length} chapters in "${subjectName}"? This may take a moment.`)) return;
    setBulkGenerating(true);
    try {
      const res = await axios.post(`${API}/admin/subjects/${selSubject}/generate-notes-bulk`, { skip_existing: allChaptersHaveNotes }, authHeaders(adminToken));
      const ok = res.data?.generated || 0; const skipped = res.data?.skipped || 0;
      toast.success(skipped > 0 ? `Generated ${ok} chapters · ${skipped} already had notes (skipped)` : `Generated notes for ${ok} of ${res.data?.total || chapters.length} chapters`);
      const freshRes = await axios.get(`${API}/content/chapters?subject_id=${selSubject}`, authHeaders(adminToken));
      if (freshRes.data?.chapters) setChapters(freshRes.data.chapters);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Bulk note generation failed'); }
    finally { setBulkGenerating(false); }
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
            <input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search all subjects..." className="w-full h-9 pl-8 pr-3 rounded-xl text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500" data-testid="search-subjects" />
          </div>
        </div>

        {searchQuery && searchFiltered ? (
          <div className="flex-1 overflow-y-auto p-6">
            <p className="text-sm text-white/40 mb-4">{searchFiltered.length} subject(s) matching "{searchQuery}"</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {searchFiltered.map(s => (
                <button key={s.id} onClick={() => { setSearchQuery(''); const st = streams.find(x => x.id === s.stream_id); if (st) { const cl = classes.find(x => x.id === st.class_id); if (cl) setSelBoard(cl.board_id); setSelClass(st.class_id); } setSelStream(s.stream_id); setSelSubject(s.id); }}
                  className="p-4 rounded-xl border border-white/10 hover:border-violet-500/30 bg-white/[0.02] text-left transition-colors">
                  <p className="text-sm font-medium text-white">{s.icon} {s.name}</p>
                  <p className="text-xs text-white/40 truncate mt-1">{s.description}</p>
                </button>
              ))}
              {searchFiltered.length === 0 && <p className="text-white/30 text-sm col-span-3">No subjects found</p>}
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
                    <Layers size={56} className="mx-auto text-white/15 mb-4" />
                    <h3 className="text-xl font-bold text-white mb-2">All-in-One Content Manager</h3>
                    <p className="text-white/50 text-sm mb-2">Navigate the tree on the left: Board → Class → {streamPlaceholder} → Subject</p>
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
                          <button onClick={(e) => { e.stopPropagation(); handlePublishAsBlog(s.id, s.name); }} disabled={publishingBlog}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium disabled:opacity-40 transition-all hover:brightness-110"
                            style={{ background: 'linear-gradient(135deg,rgba(124,58,237,0.30),rgba(79,70,229,0.30))', color: '#c4b0f0' }}>
                            {publishingBlog ? <Loader2 size={10} className="animate-spin" /> : <Globe size={10} />} Publish
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                  <InlineCreator placeholder="Subject" onCreate={handleCreateSubject} icon={Layers} color="violet" />
                </div>
              ) : selSubject ? (
                <div className="p-6 max-w-5xl mx-auto space-y-5">
                  <div className="flex items-start justify-between">
                    <div>
                      <h3 className="text-xl font-bold text-white">{subjectData?.icon} {subjectData?.name}</h3>
                      <p className="text-sm text-white/40">{subjectData?.description}</p>
                    </div>
                  </div>
                  <WorkflowTracker
                    chapters={chapters} selSubject={selSubject} allChaptersHaveNotes={allChaptersHaveNotes}
                    seoTopicsGeneratedIds={seoTopicsGeneratedIds} assetsGeneratedIds={assetsGeneratedIds} mergedSubjectIds={mergedSubjectIds}
                    generatingSeoTopics={generatingSeoTopics} publishingBlog={publishingBlog}
                    onGenerateSeoTopics={handleGenerateSeoTopics} onShowPipeline={() => setShowPipeline(true)} onPublishAsBlog={handlePublishAsBlog}
                    subjectData={subjectData} onNavigate={onNavigate}
                  />
                  <ThumbnailStudio adminToken={adminToken} selSubject={selSubject} subjectData={subjectData} onReload={() => load(true)} />
                  <ChapterList
                    chapters={chapters} chapterAssets={chapterAssets} selectedChapters={selectedChapters} setSelectedChapters={setSelectedChapters}
                    generatingNotes={generatingNotes} bulkGenerating={bulkGenerating}
                    onGenerateNotes={handleGenerateNotes} onDeleteChapter={handleDeleteChapter}
                    onViewChapter={(ch) => setViewerItem(ch)}
                    onEditChapter={(ch) => { setEditTarget(ch); setContentForm({ title: ch.title, slug: ch.slug || '', description: ch.description || '', content: ch.content || '', content_type: ch.content_type || 'notes', order: ch.order || 1 }); setEditView('edit-chapter'); loadChapterStats(ch.id); }}
                    showAgenticCreator={showAgenticCreator} setShowAgenticCreator={setShowAgenticCreator}
                    autoAgentic={autoAgentic} setAutoAgentic={setAutoAgentic}
                    onBulkMerge={handleBulkMerge} bulkMerging={bulkMerging}
                    selSubject={selSubject} subjectData={subjectData}
                    onCreateNew={() => { setEditView('new-chapter'); setContentForm({ title: '', slug: '', description: '', content: '', content_type: 'notes', order: chapters.length + 1 }); setChapterStats(null); }}
                  />
                  <ContentGapsPanel
                    showGapPanel={showGapPanel} setShowGapPanel={setShowGapPanel}
                    gapSubjects={gapSubjects} loadGapSubjects={loadGapSubjects} loadingGaps={loadingGaps}
                    gapGenStatus={gapGenStatus} gapGenSubject={gapGenSubject}
                    bulkGapSelected={bulkGapSelected} setBulkGapSelected={setBulkGapSelected}
                    bulkGapGenerating={bulkGapGenerating} bulkGapProgress={bulkGapProgress}
                    onAutoGenerateGap={handleAutoGenerateGap} onMergeGapToCms={handleMergeGapToCms} onBulkGapAutoGen={handleBulkGapAutoGen}
                  />
                </div>
              ) : null}
            </div>
          </div>
        )}
      </>

      {viewerItem && <ContentViewerPopup item={viewerItem} onClose={() => setViewerItem(null)} />}

      {showPipeline && (
        <PipelineProgressPanel
          adminToken={adminToken} subjectId={selSubject} subjectName={subjectData?.name || selSubject}
          skipExisting={allChaptersHaveNotes} onClose={() => setShowPipeline(false)}
          onComplete={(summary) => {
            const total = (summary.total_blogs || 0) + (summary.total_topic_pyqs || 0) + (summary.total_flashcards || 0) + (summary.total_pyq_pages || 0);
            toast.success(`${total} assets generated for "${subjectData?.name}" — ${summary.total_blogs || 0} blogs live`);
            setAssetsGeneratedIds(prev => new Set([...prev, selSubject]));
            setMergedSubjectIds(prev => new Set([...prev, selSubject]));
            if (summary.chapter_results?.length > 0) {
              setChapterAssets(prev => {
                const next = { ...prev };
                for (const r of summary.chapter_results) {
                  if (r.chapter_id) {
                    next[r.chapter_id] = {
                      ...next[r.chapter_id],
                      notesGenerated: r.notes_generated,
                      pyqCount: r.topic_pyq_count || 0,
                      flashcardCount: r.flashcards_count || 0,
                      blogCount: r.blogs_count || 0,
                      pyqPage: r.pyq_page || false,
                    };
                  }
                }
                return next;
              });
            }
            if (selSubject) loadChapterCards(selSubject);
          }}
        />
      )}

      {showAgenticCreator && selSubject && (
        <AgenticCreatorModal
          adminToken={adminToken} subjectId={selSubject} subjectName={subjectData?.name || selSubject}
          chapterCount={chapters.length} onClose={() => setShowAgenticCreator(false)}
          onComplete={() => { toast.success('Agentic generation complete — refreshing chapters…'); refreshChapters(selSubject); }}
        />
      )}
    </div>
  );
}
