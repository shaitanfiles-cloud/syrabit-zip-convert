import { useState, useCallback, useEffect, useRef } from 'react';
import {
  Loader2, Sparkles, Eye, Code, Send, FileText,
  BookOpen, Layers, HelpCircle, Calculator, StickyNote,
  CheckCircle, AlertCircle, Copy, RefreshCw,
  Globe, Zap, AlertTriangle, GitBranch, Save,
  ChevronDown, ChevronRight, Square, CheckSquare,
  ArrowRightLeft, Link2, ExternalLink, List,
  ArrowRight, X, CheckCheck,
} from 'lucide-react';
import axios from 'axios';
import { API_BASE, vertexQualityScore } from '@/utils/api';
import { toast } from 'sonner';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

function authHeaders(token) {
  const isRealJwt = token && token.split('.').length === 3;
  return { headers: isRealJwt ? { Authorization: `Bearer ${token}` } : {}, withCredentials: true };
}

const TRANSLITERATION_MAP = {
  'अ':'a','आ':'a','इ':'i','ई':'i','उ':'u','ऊ':'u','ए':'e','ऐ':'ai','ओ':'o','औ':'au',
  'क':'k','ख':'kh','ग':'g','घ':'gh','च':'ch','छ':'chh','ज':'j','झ':'jh',
  'ट':'t','ठ':'th','ड':'d','ढ':'dh','ण':'n','त':'t','थ':'th','द':'d','ध':'dh',
  'न':'n','प':'p','फ':'ph','ब':'b','भ':'bh','म':'m','य':'y','र':'r','ल':'l',
  'व':'v','श':'sh','ष':'sh','स':'s','ह':'h','ं':'n','ः':'h','ा':'a','ि':'i',
  'ी':'i','ु':'u','ू':'u','े':'e','ै':'ai','ो':'o','ौ':'au','्':'',
  // Bengali/Assamese vowels
  'অ':'a','আ':'a','ই':'i','ঈ':'i','উ':'u','ঊ':'u','এ':'e','ঐ':'ai','ও':'o','ঔ':'au',
  // Bengali/Assamese consonants
  'ক':'k','খ':'kh','গ':'g','ঘ':'gh','ঙ':'ng',
  'চ':'ch','ছ':'chh','জ':'j','ঝ':'jh','ঞ':'n',
  'ট':'t','ঠ':'th','ড':'d','ঢ':'dh','ণ':'n',
  'ত':'t','থ':'th','দ':'d','ধ':'dh','ন':'n',
  'প':'p','ফ':'ph','ব':'b','ভ':'bh','ম':'m',
  'য':'y','র':'r','ল':'l','শ':'sh','ষ':'sh','স':'s','হ':'h','ৱ':'v','ড়':'r','ঢ়':'rh',
  // Bengali/Assamese matras / diacritics
  'া':'a','ি':'i','ী':'i','ু':'u','ূ':'u','ে':'e','ৈ':'ai','ো':'o','ৌ':'au','্':'','ং':'ng','ঃ':'h','ঁ':'n',
};

function slugify(text) {
  const transliterated = (text || '').split('').map(ch => TRANSLITERATION_MAP[ch] ?? ch).join('');
  const cleaned = transliterated
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
  return cleaned || 'content';
}

const BLOCK_ICONS = {
  summary:    { icon: FileText,    color: '#8b5cf6', bg: 'rgba(139,92,246,0.12)' },
  definition: { icon: BookOpen,    color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
  example:    { icon: Layers,      color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
  pyq:        { icon: HelpCircle,  color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  formula:    { icon: Calculator,  color: '#ec4899', bg: 'rgba(236,72,153,0.12)' },
  note:       { icon: StickyNote,  color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
  faq:        { icon: HelpCircle,  color: '#06b6d4', bg: 'rgba(6,182,212,0.12)' },
  syllabus:   { icon: List,        color: '#34d399', bg: 'rgba(52,211,153,0.12)' },
};

function BlockCard({ block, index, onEdit, onRemove }) {
  const cfg = BLOCK_ICONS[block.type] || BLOCK_ICONS.note;
  const Icon = cfg.icon;
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState(block.content);

  return (
    <div className="border rounded-xl p-4 group transition-colors" style={{ borderColor: 'rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.025)' }}>
      <div className="flex items-center gap-2 mb-3">
        <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: cfg.bg }}>
          <Icon size={14} style={{ color: cfg.color }} />
        </div>
        <span className="text-[10px] font-bold uppercase tracking-wider flex-shrink-0" style={{ color: cfg.color }}>{block.type}</span>
        <span className="text-sm font-medium truncate min-w-0" style={{ color: 'rgba(232,232,232,0.80)' }}>{block.title}</span>
        <div className="ml-auto flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button onClick={() => { setEditing(!editing); setEditContent(block.content); }}
            className="px-2 py-0.5 text-[10px] rounded-lg" style={{ background: 'rgba(255,255,255,0.07)', color: 'rgba(255,255,255,0.50)' }}>
            {editing ? 'Cancel' : 'Edit'}
          </button>
          <button onClick={() => onRemove(index)}
            className="px-2 py-0.5 text-[10px] rounded-lg" style={{ background: 'rgba(248,113,113,0.10)', color: '#f87171' }}>
            Remove
          </button>
        </div>
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea value={editContent} onChange={e => setEditContent(e.target.value)} rows={4}
            className="w-full rounded-lg px-3 py-2 text-sm resize-y outline-none"
            style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.10)', color: '#E8E8E8' }} />
          <button onClick={() => { onEdit(index, editContent); setEditing(false); }}
            className="px-3 py-1.5 text-xs rounded-lg" style={{ background: '#7c3aed', color: 'white' }}>Save</button>
        </div>
      ) : (
        <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: 'rgba(232,232,232,0.55)' }}>{block.content}</p>
      )}
    </div>
  );
}

function SerpPreview({ title, slug, metaDescription }) {
  return (
    <div className="rounded-xl p-4" style={{ background: '#ffffff' }}>
      <div className="flex items-center gap-2 mb-1.5">
        <div className="w-5 h-5 rounded-full flex-shrink-0" style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)' }} />
        <div className="min-w-0">
          <p className="text-xs font-medium" style={{ color: '#202124' }}>syrabit.ai</p>
          <p className="text-[10px] truncate" style={{ color: '#4d5156' }}>https://syrabit.ai/{slug || 'your-slug'}</p>
        </div>
      </div>
      <p className="text-base leading-tight mb-1" style={{ color: '#1a0dab', fontFamily: 'arial,sans-serif' }}>
        {title ? `${title} | Syrabit.ai` : 'Your Page Title — Syrabit.ai'}
      </p>
      <p className="text-sm leading-snug" style={{ color: '#4d5156', fontFamily: 'arial,sans-serif' }}>
        {metaDescription
          ? (metaDescription.length > 160 ? metaDescription.slice(0, 157) + '…' : metaDescription)
          : 'Your meta description will appear here. Write 120–160 characters for best click-through.'}
      </p>
    </div>
  );
}

function PerplexityPreview({ title, slug, metaDescription, blocks }) {
  const tags = blocks.filter(b => ['definition', 'summary', 'pyq'].includes(b.type)).slice(0, 3);
  return (
    <div className="rounded-xl p-4" style={{ background: '#0d1117', border: '1px solid rgba(139,92,246,0.25)' }}>
      <div className="flex items-start gap-3">
        <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5" style={{ background: 'linear-gradient(135deg,#6366f1,#8b5cf6)' }}>
          <Sparkles size={11} className="text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold mb-1" style={{ color: '#e2e8f0' }}>
            {title || 'Your page title as the AI answer heading'}
          </p>
          <p className="text-[11px] leading-relaxed mb-2" style={{ color: '#94a3b8' }}>
            {metaDescription || 'Your meta description appears as the AI-generated excerpt. Perplexity cites pages with clear educational intent and AHSEC-aligned content.'}
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10px]" style={{ background: 'rgba(139,92,246,0.15)', color: '#a78bfa' }}>
              <Globe size={9} /> syrabit.ai/{slug || 'slug'}
            </div>
            {tags.map((b, i) => (
              <span key={i} className="text-[10px] px-2 py-0.5 rounded-full" style={{ background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.35)' }}>
                {b.type}
              </span>
            ))}
          </div>
        </div>
        <div className="flex-shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: 'rgba(139,92,246,0.20)', color: '#a78bfa' }}>
          [1]
        </div>
      </div>
    </div>
  );
}

const selStyle = {
  color: '#E8E8E8', background: 'rgba(255,255,255,0.05)',
  border: '1px solid rgba(255,255,255,0.10)', borderRadius: 8,
  padding: '6px 10px', fontSize: 12, outline: 'none', width: '100%',
};

export default function AdminContentStudio({ adminToken, onNavigate, hubContext, onHubContext }) {
  const [rawText, setRawText]       = useState('');
  const [subject, setSubject]       = useState('');
  const [subjectId, setSubjectId]   = useState('');
  const [chapter, setChapter]       = useState('');
  const [blocks, setBlocks]         = useState([]);
  const [parsing, setParsing]       = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [published, setPublished]   = useState(null);
  const [qualityChecking, setQualityChecking] = useState(false);
  const [qualityScore, setQualityScore] = useState(null);
  const [qualityWarning, setQualityWarning] = useState(false);
  const [view, setView]             = useState('editor');
  const [title, setTitle]           = useState('');
  const [slug, setSlug]             = useState('');
  const [metaDescription, setMetaDescription] = useState('');
  const [seoGenerating, setSeoGenerating]     = useState(false);
  const [seoResult, setSeoResult]             = useState(null);
  const [isRevision, setIsRevision] = useState(false);
  const [draftId, setDraftId]       = useState('');
  const [draftSaving, setDraftSaving]   = useState(false);
  const [drafts, setDrafts]         = useState([]);
  const [showDrafts, setShowDrafts] = useState(false);

  const [boards, setBoards]         = useState([]);
  const [classes, setClasses]       = useState([]);
  const [streams, setStreams]       = useState([]);
  const [sylSubjects, setSylSubjects] = useState([]);
  const [selectedBoardId, setSelectedBoardId]       = useState('');
  const [selectedClassId, setSelectedClassId]       = useState('');
  const [selectedStreamId, setSelectedStreamId]     = useState('');
  const [selectedSylSubjectId, setSelectedSylSubjectId] = useState('');
  const [syllabusOpen, setSyllabusOpen]             = useState(false);
  const [syllabusLoading, setSyllabusLoading]       = useState(false);

  const [allSubjects, setAllSubjects]   = useState([]);
  const [gapSubjects, setGapSubjects]   = useState([]);
  const [loadingGaps, setLoadingGaps]   = useState(false);
  const [gapGenSubject, setGapGenSubject] = useState(null);
  const [gapGenStatus, setGapGenStatus]   = useState({});
  const [bulkSelected, setBulkSelected]   = useState(new Set());
  const [bulkGenerating, setBulkGenerating] = useState(false);
  const [bulkProgress, setBulkProgress]   = useState({ done: 0, total: 0 });
  const [mergingToCms, setMergingToCms]   = useState({});
  const [fromEditor, setFromEditor]       = useState(false);
  const [nextStepsDismissed, setNextStepsDismissed] = useState(false);

  const headers = { withCredentials: true };

  const selectedBoard = boards.find(b => b.id === selectedBoardId) || boards[0];
  const selectedClass = classes.find(c => c.id === selectedClassId) || classes[0];
  const boardSlug  = selectedBoard?.slug || slugify(selectedBoard?.name || '') || '';
  const classSlug  = selectedClass?.slug || slugify(selectedClass?.name || '') || '';
  const subjectSlug = slugify(subject || 'subject');
  const publishPath = `/${boardSlug}/${classSlug}/${subjectSlug}/${slug || 'chapter-slug'}`;

  useEffect(() => {
    axios.get(`${API}/content/boards`).then(r => setBoards(r.data || [])).catch(() => {});
  }, []);

  // ── Read Editor→Studio prefill ────────────────────────────────────────────
  useEffect(() => {
    try {
      const raw = localStorage.getItem('syrabit_studio_prefill');
      if (!raw) return;
      const pf = JSON.parse(raw);
      if (Date.now() - (pf.timestamp || 0) > 10 * 60 * 1000) {
        localStorage.removeItem('syrabit_studio_prefill');
        return;
      }
      localStorage.removeItem('syrabit_studio_prefill');
      if (pf.subject)   setSubject(pf.subject);
      if (pf.subjectId) setSubjectId(pf.subjectId);
      if (pf.chapter)   setChapter(pf.chapter);
      if (pf.rawText)   setRawText(pf.rawText);
      if (pf.boardId)   setSelectedBoardId(pf.boardId);
      if (pf.classId)   setSelectedClassId(pf.classId);
      if (pf.streamId)  setSelectedStreamId(pf.streamId);
      setFromEditor(true);
      setNextStepsDismissed(false);
      if (pf.subject)   toast.success(`Pre-filled with "${pf.subject}" chapter content — review and generate`);
    } catch {}
  }, []);

  // ── Pre-fill from hub context ─────────────────────────────────────────────
  useEffect(() => {
    if (!hubContext?.subjectName || subject) return;
    if (hubContext.subjectName) setSubject(hubContext.subjectName);
    if (hubContext.subjectId)   setSubjectId(hubContext.subjectId);
    if (hubContext.boardId)     setSelectedBoardId(hubContext.boardId);
    if (hubContext.classId)     setSelectedClassId(hubContext.classId);
    if (hubContext.streamId)    setSelectedStreamId(hubContext.streamId);
  }, [hubContext?.subjectId]);

  // ── Broadcast subject selection back to hub ───────────────────────────────
  useEffect(() => {
    if (!onHubContext || !subjectId) return;
    onHubContext(ctx => ({ ...ctx, subjectId, subjectName: subject }));
  }, [subjectId]);

  useEffect(() => {
    if (!selectedBoardId) { setClasses([]); setSelectedClassId(''); return; }
    axios.get(`${API}/content/classes?board_id=${selectedBoardId}`).then(r => setClasses(r.data || [])).catch(() => {});
    setSelectedClassId('');
  }, [selectedBoardId]);

  useEffect(() => {
    if (!selectedClassId) { setStreams([]); setSelectedStreamId(''); return; }
    axios.get(`${API}/content/streams?class_id=${selectedClassId}`).then(r => setStreams(r.data || [])).catch(() => {});
    setSelectedStreamId('');
  }, [selectedClassId]);

  useEffect(() => {
    if (!selectedStreamId) { setSylSubjects([]); setSelectedSylSubjectId(''); return; }
    axios.get(`${API}/content/subjects?stream_id=${selectedStreamId}`).then(r => setSylSubjects(r.data || [])).catch(() => {});
    setSelectedSylSubjectId('');
  }, [selectedStreamId]);

  const loadDrafts = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/admin/studio/drafts`, authHeaders(adminToken));
      setDrafts(res.data || []);
    } catch {}
  }, [adminToken]);

  useEffect(() => { loadDrafts(); }, [loadDrafts]);

  const handleGenerateSeoMeta = useCallback(async () => {
    if (!title && blocks.length === 0) {
      toast.error('Add a title or parse some content first');
      return;
    }
    setSeoGenerating(true);
    setSeoResult(null);
    try {
      const contentSnippet = blocks.map(b => `${b.title}: ${b.content}`).join('\n').slice(0, 3000);
      const sylSubj = sylSubjects.find(s => s._id === selectedSylSubjectId || s.id === selectedSylSubjectId);
      const payload = {
        title,
        content: contentSnippet,
        primary_keyword: '',
        seo_tags: '',
        subject: sylSubj?.name || subjectId,
        linked_scope: sylSubj?.name ? `${sylSubj.name}` : '',
        board: boards.find(b => b._id === selectedBoardId || b.id === selectedBoardId)?.name || 'AHSEC',
        class_name: classes.find(c => c._id === selectedClassId || c.id === selectedClassId)?.name || '',
      };
      const { data } = await axios.post(`${API}/admin/seo/generate`, payload, authHeaders(adminToken));
      setSeoResult(data);
      toast.success('SEO metadata generated');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'AI SEO generation failed');
    } finally {
      setSeoGenerating(false);
    }
  }, [title, blocks, sylSubjects, selectedSylSubjectId, boards, selectedBoardId, classes, selectedClassId, subjectId, adminToken]);

  const applyStudioSeoResult = useCallback(() => {
    if (!seoResult) return;
    if (seoResult.seo_title) setTitle(seoResult.seo_title.replace(/\s*\|\s*Syrabit.*$/i, '').trim());
    if (seoResult.meta_description) setMetaDescription(seoResult.meta_description);
    setSeoResult(null);
    toast.success('Applied — update the title field in Publish Pipeline too');
  }, [seoResult]);

  const loadGapSubjects = useCallback(async () => {
    setLoadingGaps(true);
    try {
      const res = await axios.get(`${API}/content/subjects`);
      const subs = res.data || [];
      setAllSubjects(subs);
      setGapSubjects(subs.filter(s => (s.chapter_count || 0) < 3));
    } catch { toast.error('Could not load subjects'); }
    finally { setLoadingGaps(false); }
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
        setSlug(slugify((subject + '-' + chapter)));
      if (!metaDescription) {
        const summaryBlock = parsed.find(b => b.type === 'summary' || b.type === 'note');
        if (summaryBlock) setMetaDescription(summaryBlock.content.slice(0, 160));
      }
    } catch (e) {
      setBlocks([]);
      toast.error(e.response?.data?.detail || 'AI parse failed — previous content cleared');
    }
    finally { setParsing(false); }
  }, [rawText, subject, chapter, title, slug, metaDescription]);

  const handleLoadSyllabus = async () => {
    if (!selectedBoardId || !selectedClassId) { toast.error('Select Board and Class first'); return; }
    setSyllabusLoading(true);
    try {
      let url = `${API}/syllabi/${selectedBoardId}/${selectedClassId}`;
      if (selectedStreamId && selectedSylSubjectId)
        url = `${API}/syllabi/${selectedBoardId}/${selectedClassId}/${selectedStreamId}/${selectedSylSubjectId}`;
      else if (selectedStreamId)
        url = `${API}/syllabi/${selectedBoardId}/${selectedClassId}/${selectedStreamId}`;
      const res = await axios.get(url, { withCredentials: true });
      const syl = res.data;
      if (!syl?.content && !syl?.chapters?.length && !syl?.topics?.length) {
        toast.error('No syllabus found for this scope'); return;
      }
      const parts = [];
      if (syl.content) parts.push(syl.content);
      if (syl.topics?.length)   parts.push(`Key Topics: ${syl.topics.join(', ')}`);
      if (syl.chapters?.length) parts.push(`Chapters: ${syl.chapters.join(', ')}`);
      if (syl.guidelines)       parts.push(`Guidelines: ${syl.guidelines}`);
      const sylBlock = {
        type: 'syllabus',
        title: `${subject || selectedClass?.name || 'Subject'} — Syllabus Scope`,
        content: parts.filter(Boolean).join('\n\n'),
      };
      setBlocks(prev => [sylBlock, ...prev.filter(b => b.type !== 'syllabus')]);
      setSyllabusOpen(false);
      toast.success('Syllabus context loaded as first block');
    } catch { toast.error('Failed to load syllabus'); }
    finally { setSyllabusLoading(false); }
  };

  const handlePublish = useCallback(async (asRevision = false) => {
    if (!blocks.length || !slug.trim()) return;

    // Quality Gate — auto-score before publish
    if (!asRevision && !qualityWarning) {
      setQualityChecking(true);
      try {
        const contentSnippet = blocks.map(b => b.content).join('\n').slice(0, 3000);
        const qRes = await vertexQualityScore(adminToken, contentSnippet, 'notes', title, subject || '');
        const score = qRes.data?.score || qRes.data?.overall_score || 0;
        setQualityScore(score);
        if (score < 7) {
          setQualityWarning(true);
          setQualityChecking(false);
          toast.warning(`Quality score ${score}/10 is below threshold. Review content or publish anyway.`);
          return;
        }
      } catch { /* skip on error */ }
      finally { setQualityChecking(false); }
    }
    setQualityWarning(false);

    setPublishing(true);
    try {
      const res = await axios.post(`${API_BASE}/admin/studio/publish`, {
        title: title || 'Untitled',
        slug: slug.trim(),
        blocks,
        subject_id:   subjectId,
        subject_slug: subjectSlug,
        meta_description: metaDescription,
        board_id:  selectedBoardId,
        class_id:  selectedClassId,
        stream_id: selectedStreamId,
        is_revision: asRevision,
        parent_revision_id: asRevision ? (draftId || slug) : '',
      }, headers);
      setPublished(res.data);
      setQualityScore(null);
      toast.success(asRevision ? 'Revision published!' : 'Published to live pages!');
    } catch { toast.error('Publish failed'); }
    finally { setPublishing(false); }
  }, [blocks, title, slug, subjectId, subjectSlug, metaDescription, selectedBoardId, selectedClassId, selectedStreamId, draftId, qualityWarning, adminToken, subject]);

  const handleSaveDraft = async () => {
    if (!blocks.length && !rawText.trim()) { toast.error('Nothing to save'); return; }
    setDraftSaving(true);
    try {
      const res = await axios.post(`${API}/admin/studio/drafts`, {
        id:           draftId || undefined,
        title, slug, blocks,
        subject_id:   subjectId,
        subject_slug: subjectSlug,
        board_id:     selectedBoardId,
        class_id:     selectedClassId,
        stream_id:    selectedStreamId,
      }, authHeaders(adminToken));
      setDraftId(res.data.id);
      await loadDrafts();
      toast.success('Draft saved');
    } catch { toast.error('Draft save failed'); }
    finally { setDraftSaving(false); }
  };

  const handleLoadDraft = (draft) => {
    setDraftId(draft.id);
    setTitle(draft.title || '');
    setSlug(draft.slug || '');
    setBlocks(draft.blocks || []);
    setSubjectId(draft.subject_id || '');
    if (draft.board_id) setSelectedBoardId(draft.board_id);
    if (draft.class_id) setSelectedClassId(draft.class_id);
    setView('editor');
    setShowDrafts(false);
    toast.success(`Loaded draft: ${draft.title}`);
  };

  const handleMergeToCms = async (s) => {
    setMergingToCms(prev => ({ ...prev, [s.id]: true }));
    try {
      await axios.post(`${API}/admin/cms/merge/${s.id}`, {}, authHeaders(adminToken));
      localStorage.setItem('syrabit_cms_prefill', JSON.stringify({
        title:     `${s.name} — Blog`,
        timestamp: Date.now(),
      }));
      toast.success(`Merged "${s.name}" → CMS Editor`);
      onNavigate?.('cms');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Merge failed');
    } finally {
      setMergingToCms(prev => ({ ...prev, [s.id]: false }));
    }
  };

  const handleAutoGenerate = useCallback(async (s) => {
    setGapGenSubject(s.id);
    setGapGenStatus(prev => ({ ...prev, [s.id]: 'generating' }));
    try {
      let syllabusContext = '';
      if (selectedBoardId && selectedClassId) {
        try {
          const sr = await axios.get(`${API}/syllabi/${selectedBoardId}/${selectedClassId}`, { withCredentials: true });
          const syl = sr.data;
          if (syl?.topics?.length) syllabusContext = `\nSyllabus topics: ${syl.topics.slice(0, 10).join(', ')}`;
          if (syl?.chapters?.length) syllabusContext += `\nChapters: ${syl.chapters.slice(0, 8).join(', ')}`;
        } catch {}
      }
      const prompt = `Generate comprehensive educational notes for AssamBoard students on: ${s.name}.${syllabusContext}\nInclude: key concepts (with AssamBoard exam frequency), textbook definitions, worked examples, PYQ-style questions with marks, and 2 FAQ blocks.`;
      const res = await axios.post(`${API_BASE}/admin/studio/parse`, {
        raw_text: prompt, subject: s.name, chapter: 'Overview',
      }, headers);
      const parsed = res.data.blocks || [];
      if (!parsed.length) { setGapGenStatus(prev => ({ ...prev, [s.id]: 'failed' })); return; }
      const markdown = parsed.map(b => `## ${b.title}\n\n${b.content}`).join('\n\n---\n\n');
      await axios.post(
        `${API}/admin/content/chapters`,
        {
          subject_id:   s.id,
          title:        `${s.name} — Overview`,
          slug:         slugify(s.name) + '-overview',
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
  }, [adminToken, loadGapSubjects, selectedBoardId, selectedClassId]);

  const handleBulkAutoGen = async () => {
    const selected = [...bulkSelected]
      .map(id => gapSubjects.find(s => s.id === id))
      .filter(Boolean);
    if (!selected.length) return;
    setBulkGenerating(true);
    setBulkProgress({ done: 0, total: selected.length });
    const tasks = selected.map(s =>
      handleAutoGenerate(s).then(() => setBulkProgress(p => ({ ...p, done: p.done + 1 })))
    );
    await Promise.allSettled(tasks);
    setBulkGenerating(false);
    setBulkSelected(new Set());
    loadGapSubjects();
    toast.success(`Bulk generation complete (${selected.length} subjects)`);
  };

  const handleGapFill = (s) => {
    setSubject(s.name); setSubjectId(s.id);
    setView('editor');
    setRawText(''); setBlocks([]);
    setTitle(s.name);
    setSlug(slugify(s.name));
    toast.success(`Loaded "${s.name}" — paste notes then Parse`);
  };

  const handleEditBlock   = (index, newContent) => setBlocks(prev => prev.map((b, i) => i === index ? { ...b, content: newContent } : b));
  const handleRemoveBlock = (index)              => setBlocks(prev => prev.filter((_, i) => i !== index));

  const toggleBulkSelect = (id) => {
    setBulkSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectAllGaps = () => {
    if (bulkSelected.size === gapSubjects.length) setBulkSelected(new Set());
    else setBulkSelected(new Set(gapSubjects.map(s => s.id)));
  };

  const hasSyllabusBlock = blocks.some(b => b.type === 'syllabus');

  return (
    <div className="p-6 space-y-5 min-h-full" style={{ background: '#121212' }}>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="font-bold text-lg flex items-center gap-2" style={{ color: '#E8E8E8' }}>
            <Sparkles size={18} style={{ color: '#a78bfa' }} />
            AI Content Studio
          </h2>
          <p className="text-sm mt-1" style={{ color: 'rgba(255,255,255,0.35)' }}>
            Paste raw notes → AI categorizes → Edit → Publish to SEO pages
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowDrafts(v => !v)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border"
            style={showDrafts
              ? { background: 'rgba(245,158,11,0.15)', color: '#fbbf24', borderColor: 'rgba(245,158,11,0.25)' }
              : { background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.40)', borderColor: 'rgba(255,255,255,0.10)' }}>
            <Save size={11} /> Drafts {drafts.length > 0 && `(${drafts.length})`}
          </button>
          <div className="flex gap-1 rounded-xl p-1" style={{ background: 'rgba(255,255,255,0.05)' }}>
            {[
              { id: 'editor',  label: 'Editor',   icon: Code },
              { id: 'preview', label: 'Preview',  icon: Eye },
              { id: 'gaps',    label: 'Gap Fill',  icon: AlertTriangle },
            ].map(t => (
              <button key={t.id} onClick={() => setView(t.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                style={view === t.id
                  ? { background: '#7c3aed', color: 'white' }
                  : { color: 'rgba(255,255,255,0.40)' }}>
                <t.icon size={12} />
                {t.label}
                {t.id === 'gaps' && gapSubjects.length > 0 && (
                  <span className="ml-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold" style={{ background: 'rgba(245,158,11,0.25)', color: '#fbbf24' }}>
                    {gapSubjects.length}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Drafts panel ────────────────────────────────────────────────── */}
      {showDrafts && (
        <div className="rounded-xl p-4 border" style={{ background: 'rgba(255,255,255,0.025)', borderColor: 'rgba(245,158,11,0.15)' }}>
          <p className="text-xs font-semibold mb-3" style={{ color: '#fbbf24' }}>Saved Drafts</p>
          {drafts.length === 0 ? (
            <p className="text-xs" style={{ color: 'rgba(255,255,255,0.25)' }}>No drafts yet. Use "Save Draft" in the Publish Pipeline.</p>
          ) : (
            <div className="space-y-1.5 max-h-48 overflow-y-auto">
              {drafts.map(d => (
                <div key={d.id} className="flex items-center gap-3 px-3 py-2 rounded-lg" style={{ background: 'rgba(255,255,255,0.03)' }}>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium truncate" style={{ color: '#E8E8E8' }}>{d.title}</p>
                    <p className="text-[10px] font-mono truncate" style={{ color: 'rgba(255,255,255,0.25)' }}>{d.slug} · {d.blocks?.length || 0} blocks</p>
                  </div>
                  <button onClick={() => handleLoadDraft(d)}
                    className="text-[10px] px-2 py-1 rounded-lg flex-shrink-0" style={{ background: '#7c3aed', color: 'white' }}>
                    Load
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════
          GAP FILL TAB
      ══════════════════════════════════════════════════════════════ */}
      {view === 'gaps' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h3 className="text-sm font-semibold" style={{ color: '#E8E8E8' }}>Subjects with &lt; 3 Chapters</h3>
              <p className="text-xs mt-0.5" style={{ color: 'rgba(255,255,255,0.30)' }}>Auto-generate or manually fill content for under-resourced subjects.</p>
            </div>
            <div className="flex items-center gap-2">
              {bulkSelected.size > 0 && !bulkGenerating && (
                <button onClick={handleBulkAutoGen}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg"
                  style={{ background: 'rgba(139,92,246,0.25)', color: '#c4b0f0', border: '1px solid rgba(139,92,246,0.35)' }}>
                  <Sparkles size={11} /> Bulk Auto-Gen ({bulkSelected.size})
                </button>
              )}
              {bulkGenerating && (
                <div className="flex items-center gap-2 text-xs" style={{ color: '#fbbf24' }}>
                  <Loader2 size={12} className="animate-spin" />
                  Generating {bulkProgress.done}/{bulkProgress.total}…
                  <div className="w-24 h-1.5 rounded-full" style={{ background: 'rgba(255,255,255,0.10)' }}>
                    <div className="h-1.5 rounded-full transition-all" style={{ background: '#fbbf24', width: `${(bulkProgress.done / bulkProgress.total) * 100}%` }} />
                  </div>
                </div>
              )}
              <button onClick={loadGapSubjects} disabled={loadingGaps}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg disabled:opacity-50"
                style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.50)', border: '1px solid rgba(255,255,255,0.08)' }}>
                {loadingGaps ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                Refresh
              </button>
            </div>
          </div>

          {/* Select-all row */}
          {gapSubjects.length > 0 && !loadingGaps && (
            <div className="flex items-center gap-2 px-1">
              <button onClick={selectAllGaps} className="flex items-center gap-1.5 text-xs" style={{ color: 'rgba(255,255,255,0.40)' }}>
                {bulkSelected.size === gapSubjects.length
                  ? <CheckSquare size={13} style={{ color: '#a78bfa' }} />
                  : <Square size={13} />}
                {bulkSelected.size === gapSubjects.length ? 'Deselect All' : 'Select All'}
              </button>
              <span className="text-[10px]" style={{ color: 'rgba(255,255,255,0.20)' }}>{gapSubjects.length} subjects need content</span>
            </div>
          )}

          {loadingGaps ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {[...Array(6)].map((_, i) => <div key={i} className="h-28 rounded-xl animate-pulse" style={{ background: 'rgba(255,255,255,0.04)' }} />)}
            </div>
          ) : gapSubjects.length === 0 ? (
            <div className="text-center py-16">
              <CheckCircle size={36} className="mx-auto mb-3" style={{ color: '#34d399' }} />
              <p className="text-sm font-semibold" style={{ color: '#E8E8E8' }}>All subjects have 3+ chapters!</p>
              <p className="text-xs mt-1" style={{ color: 'rgba(255,255,255,0.30)' }}>No gaps detected in the curriculum.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {gapSubjects.map(s => {
                const status = gapGenStatus[s.id];
                const isGen  = gapGenSubject === s.id;
                const isSel  = bulkSelected.has(s.id);
                return (
                  <div key={s.id} className="p-4 rounded-xl border transition-all"
                    style={{
                      borderColor: isSel ? 'rgba(139,92,246,0.35)' : status === 'done' ? 'rgba(52,211,153,0.30)' : 'rgba(255,255,255,0.07)',
                      background:  isSel ? 'rgba(139,92,246,0.07)' : 'rgba(255,255,255,0.02)',
                    }}>
                    <div className="flex items-start gap-2 mb-2">
                      <button onClick={() => toggleBulkSelect(s.id)} className="mt-0.5 flex-shrink-0">
                        {isSel ? <CheckSquare size={13} style={{ color: '#a78bfa' }} /> : <Square size={13} style={{ color: 'rgba(255,255,255,0.20)' }} />}
                      </button>
                      <p className="text-sm font-medium flex-1 min-w-0" style={{ color: '#E8E8E8' }}>{s.icon || '📚'} {s.name}</p>
                      {status === 'done'   && <CheckCircle size={13} style={{ color: '#34d399', flexShrink: 0 }} />}
                      {status === 'failed' && <AlertCircle size={13} style={{ color: '#f87171', flexShrink: 0 }} />}
                    </div>
                    <p className="text-xs ml-5 mb-3" style={{ color: '#fbbf24' }}>{s.chapter_count || 0} / 3 chapters</p>
                    <div className="flex gap-1.5 flex-wrap ml-5">
                      <button onClick={() => handleGapFill(s)}
                        className="px-2 py-1 rounded-lg text-[10px] font-medium flex-1 min-w-[70px]"
                        style={{ background: 'rgba(255,255,255,0.07)', color: 'rgba(232,232,232,0.65)' }}>
                        Load Editor
                      </button>
                      <button onClick={() => handleAutoGenerate(s)} disabled={isGen || status === 'done'}
                        className="px-2 py-1 rounded-lg text-[10px] font-medium disabled:opacity-40 flex items-center justify-center gap-1 flex-1 min-w-[70px]"
                        style={{ background: 'rgba(139,92,246,0.20)', color: '#a78bfa' }}>
                        {isGen ? <Loader2 size={9} className="animate-spin" /> : <Sparkles size={9} />}
                        {status === 'done' ? 'Done!' : isGen ? 'Gen…' : 'Auto-Gen'}
                      </button>
                      <button onClick={() => handleMergeToCms(s)} disabled={!!mergingToCms[s.id]}
                        className="px-2 py-1 rounded-lg text-[10px] font-medium disabled:opacity-40 flex items-center justify-center gap-1 flex-1 min-w-[70px]"
                        style={{ background: 'rgba(99,102,241,0.18)', color: '#818cf8' }}>
                        {mergingToCms[s.id] ? <Loader2 size={9} className="animate-spin" /> : <ArrowRightLeft size={9} />}
                        CMS Blog
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════
          NEXT STEPS GUIDE (from Content Editor)
      ══════════════════════════════════════════════════════════════ */}
      {fromEditor && !nextStepsDismissed && view !== 'gaps' && (() => {
        const steps = [
          {
            num: 1,
            label: 'Content Ready',
            sub: 'Chapter loaded from Editor',
            done: !!(chapter.trim() || rawText.trim()),
          },
          {
            num: 2,
            label: 'Parse with AI',
            sub: 'Click "Parse with AI" below',
            done: blocks.length > 0,
          },
          {
            num: 3,
            label: 'SEO & Title',
            sub: 'Generate metadata for ranking',
            done: !!(title.trim() && metaDescription.trim()),
          },
          {
            num: 4,
            label: 'Publish Page',
            sub: 'Go live on Syrabit.ai',
            done: !!published,
          },
        ];
        const activeIdx = steps.findIndex(s => !s.done);
        const allDone = activeIdx === -1;

        return (
          <div className="rounded-xl border overflow-hidden"
            style={{ background: 'rgba(124,58,237,0.06)', borderColor: 'rgba(124,58,237,0.22)' }}>
            <div className="flex items-center justify-between px-4 py-2.5 border-b" style={{ borderColor: 'rgba(124,58,237,0.15)', background: 'rgba(124,58,237,0.09)' }}>
              <div className="flex items-center gap-2">
                {allDone
                  ? <CheckCheck size={13} style={{ color: '#34d399' }} />
                  : <Sparkles size={13} style={{ color: '#a78bfa' }} />}
                <span className="text-xs font-semibold" style={{ color: allDone ? '#34d399' : '#c4b0f0' }}>
                  {allDone ? 'All steps complete — page is live!' : 'Next Steps in AI Studio'}
                </span>
                {!allDone && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
                    style={{ background: 'rgba(124,58,237,0.20)', color: '#a78bfa' }}>
                    Step {(activeIdx + 1)} of {steps.length}
                  </span>
                )}
              </div>
              <button onClick={() => setNextStepsDismissed(true)}
                className="w-5 h-5 rounded flex items-center justify-center hover:bg-white/10 transition-colors"
                style={{ color: 'rgba(255,255,255,0.30)' }}>
                <X size={11} />
              </button>
            </div>
            <div className="flex items-stretch divide-x" style={{ divideColor: 'rgba(124,58,237,0.15)' }}>
              {steps.map((step, i) => {
                const isActive = i === activeIdx;
                const isFuture = !step.done && i > activeIdx;
                return (
                  <div key={step.num} className="flex-1 flex items-start gap-2 px-3 py-3 min-w-0"
                    style={{ borderRight: i < steps.length - 1 ? '1px solid rgba(124,58,237,0.13)' : 'none' }}>
                    <div className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 text-[10px] font-bold transition-all"
                      style={step.done
                        ? { background: 'rgba(52,211,153,0.20)', color: '#34d399' }
                        : isActive
                          ? { background: 'rgba(124,58,237,0.35)', color: '#c4b0f0', boxShadow: '0 0 0 2px rgba(124,58,237,0.25)' }
                          : { background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.25)' }}>
                      {step.done ? <CheckCircle size={11} /> : step.num}
                    </div>
                    <div className="min-w-0">
                      <p className="text-[11px] font-semibold truncate leading-tight"
                        style={{ color: step.done ? '#34d399' : isActive ? '#e0d4ff' : 'rgba(255,255,255,0.30)' }}>
                        {step.label}
                      </p>
                      <p className="text-[10px] leading-tight mt-0.5 truncate"
                        style={{ color: step.done ? 'rgba(52,211,153,0.60)' : isActive ? 'rgba(196,176,240,0.60)' : 'rgba(255,255,255,0.18)' }}>
                        {step.sub}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* ══════════════════════════════════════════════════════════════
          EDITOR + PREVIEW TABS
      ══════════════════════════════════════════════════════════════ */}
      {view !== 'gaps' && (
        <>
          {/* Board / Class row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <div>
              <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.35)' }}>Board</p>
              <select value={selectedBoardId} onChange={e => setSelectedBoardId(e.target.value)} style={selStyle}>
                <option value="">— Board —</option>
                {boards.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            <div>
              <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.35)' }}>Class</p>
              <select value={selectedClassId} onChange={e => setSelectedClassId(e.target.value)} disabled={!selectedBoardId} style={selStyle}>
                <option value="">— Class —</option>
                {classes.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.35)' }}>Subject</p>
              <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="e.g. Physics"
                style={{ ...selStyle, padding: '6px 10px' }} />
            </div>
            <div>
              <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.35)' }}>Chapter</p>
              <input value={chapter} onChange={e => setChapter(e.target.value)} placeholder="e.g. Optics"
                style={{ ...selStyle, padding: '6px 10px' }} />
            </div>
          </div>

          {/* Parse button + Syllabus loader toggle */}
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={handleParse} disabled={parsing || !rawText.trim()}
              className="flex items-center gap-2 disabled:opacity-50 text-white rounded-lg px-5 py-2 text-sm font-medium transition-colors"
              style={{ background: '#7c3aed' }}>
              {parsing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              {parsing ? 'AI Parsing…' : 'Parse with AI'}
            </button>

            {(selectedBoardId && selectedClassId) && (
              <button onClick={() => setSyllabusOpen(v => !v)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium border"
                style={syllabusOpen
                  ? { background: 'rgba(52,211,153,0.12)', color: '#34d399', borderColor: 'rgba(52,211,153,0.30)' }
                  : { background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.40)', borderColor: 'rgba(255,255,255,0.10)' }}>
                <BookOpen size={12} />
                {hasSyllabusBlock ? 'Syllabus Loaded ✓' : 'Load Subject Syllabus'}
                {syllabusOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
              </button>
            )}

            {publishPath && selectedBoardId && (
              <div className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[10px] font-mono ml-auto"
                style={{ background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.35)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <Globe size={10} style={{ color: '#9575e0' }} />
                {publishPath}
              </div>
            )}
          </div>

          {/* Syllabus context picker */}
          {syllabusOpen && (
            <div className="rounded-xl p-4 border space-y-3" style={{ background: 'rgba(52,211,153,0.04)', borderColor: 'rgba(52,211,153,0.15)' }}>
              <p className="text-xs font-semibold" style={{ color: '#34d399' }}>Load Subject Syllabus as Context Block</p>
              <div className="flex items-end gap-2 flex-wrap">
                <div>
                  <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.30)' }}>Stream</p>
                  <select value={selectedStreamId} onChange={e => setSelectedStreamId(e.target.value)} style={{ ...selStyle, width: 'auto' }}>
                    <option value="">— Stream —</option>
                    {streams.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </div>
                <div>
                  <p className="text-[10px] mb-1" style={{ color: 'rgba(255,255,255,0.30)' }}>Subject</p>
                  <select value={selectedSylSubjectId} onChange={e => setSelectedSylSubjectId(e.target.value)} disabled={!selectedStreamId} style={{ ...selStyle, width: 'auto' }}>
                    <option value="">— Subject —</option>
                    {sylSubjects.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </div>
                <button onClick={handleLoadSyllabus} disabled={syllabusLoading}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-40"
                  style={{ background: '#34d399', color: '#064e3b' }}>
                  {syllabusLoading ? <Loader2 size={13} className="animate-spin" /> : <BookOpen size={13} />}
                  Insert Scope
                </button>
              </div>
              <p className="text-[10px]" style={{ color: 'rgba(52,211,153,0.60)' }}>
                Inserts a syllabus block at position 1. On publish, auto-creates a CMS syllabus stub if subject ID is set.
              </p>
            </div>
          )}

          {subjectId && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs" style={{ background: 'rgba(139,92,246,0.10)', border: '1px solid rgba(139,92,246,0.20)' }}>
              <Link2 size={12} style={{ color: '#a78bfa' }} />
              <span style={{ color: '#c4b0f0' }}>Subject linked: <span className="font-mono">{subjectId}</span> — {subject}</span>
              <button onClick={() => { setSubjectId(''); }} className="ml-auto text-[10px]" style={{ color: 'rgba(255,255,255,0.25)' }}>Unlink</button>
            </div>
          )}

          {/* ── EDITOR VIEW ──────────────────────────────────────────── */}
          {view === 'editor' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <div className="space-y-3">
                <label className="text-xs" style={{ color: 'rgba(255,255,255,0.35)' }}>Raw Text Input</label>
                <textarea value={rawText} onChange={e => setRawText(e.target.value)}
                  placeholder="Paste your raw educational notes, textbook content, or study material here…"
                  rows={18}
                  className="w-full rounded-xl px-4 py-3 text-sm resize-y outline-none font-mono"
                  style={{ color: '#E8E8E8', background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.08)' }} />
                <p className="text-[10px]" style={{ color: 'rgba(255,255,255,0.20)' }}>{rawText.length} chars · max 8,000 sent to AI</p>
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <label className="text-xs" style={{ color: 'rgba(255,255,255,0.35)' }}>
                    Structured Blocks {blocks.length > 0 && <span style={{ color: '#a78bfa' }}>({blocks.length})</span>}
                  </label>
                  {blocks.length > 0 && (
                    <button onClick={() => setBlocks([])} className="text-[10px]" style={{ color: 'rgba(255,255,255,0.25)' }}>Clear all</button>
                  )}
                </div>
                <div className="space-y-2.5 max-h-[500px] overflow-y-auto pr-1">
                  {blocks.map((block, i) => (
                    <BlockCard key={i} block={block} index={i} onEdit={handleEditBlock} onRemove={handleRemoveBlock} />
                  ))}
                  {blocks.length === 0 && (
                    <div className="rounded-xl p-10 text-center border border-dashed" style={{ borderColor: 'rgba(255,255,255,0.08)' }}>
                      <Sparkles size={24} className="mx-auto mb-3" style={{ color: 'rgba(255,255,255,0.10)' }} />
                      <p className="text-sm" style={{ color: 'rgba(255,255,255,0.25)' }}>AI-parsed blocks will appear here</p>
                      <p className="text-xs mt-1" style={{ color: 'rgba(255,255,255,0.15)' }}>Paste text and click "Parse with AI"</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ── PREVIEW VIEW ─────────────────────────────────────────── */}
          {view === 'preview' && (
            <div className="space-y-4">
              {/* Live page iframe */}
              {slug ? (
                <div className="rounded-xl overflow-hidden border" style={{ borderColor: 'rgba(255,255,255,0.08)' }}>
                  <div className="flex items-center gap-2 px-3 py-2 border-b" style={{ background: '#1a1a1a', borderColor: 'rgba(255,255,255,0.07)' }}>
                    <Eye size={11} style={{ color: '#9575e0' }} />
                    <span className="text-[10px] font-mono" style={{ color: 'rgba(255,255,255,0.40)' }}>/learn/{slug}</span>
                    <a href={`/learn/${slug}`} target="_blank" rel="noreferrer" className="ml-auto">
                      <ExternalLink size={10} style={{ color: 'rgba(255,255,255,0.25)' }} />
                    </a>
                  </div>
                  <iframe src={`/learn/${slug}`} className="w-full border-0" style={{ height: 340 }} title="Live Preview" />
                </div>
              ) : (
                <div className="rounded-xl p-6 text-center border border-dashed" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
                  <p className="text-xs" style={{ color: 'rgba(255,255,255,0.25)' }}>Set a URL slug in the Publish Pipeline to see live preview</p>
                </div>
              )}

              {/* SEO simulators */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <p className="text-xs font-medium mb-2" style={{ color: 'rgba(255,255,255,0.35)' }}>Google SERP Preview</p>
                  <SerpPreview title={title} slug={slug} metaDescription={metaDescription} />
                </div>
                <div>
                  <p className="text-xs font-medium mb-2" style={{ color: 'rgba(255,255,255,0.35)' }}>Perplexity AI Citation</p>
                  <PerplexityPreview title={title} slug={slug} metaDescription={metaDescription} blocks={blocks} />
                </div>
              </div>

              {/* ── AI SEO + GEO Generator ─────────────────────────────── */}
              <div className="rounded-xl p-4 border" style={{ background: 'rgba(139,92,246,0.06)', borderColor: 'rgba(139,92,246,0.20)' }}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Sparkles size={12} style={{ color: '#a78bfa' }} />
                    <span className="text-xs font-semibold" style={{ color: '#c4b0f0' }}>AI SEO &amp; GEO Generator</span>
                  </div>
                  <button onClick={handleGenerateSeoMeta} disabled={seoGenerating}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-50"
                    style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)', color: '#fff' }}>
                    {seoGenerating
                      ? <><Loader2 size={10} className="animate-spin" /> Generating…</>
                      : <><Zap size={10} /> Generate Title + Meta</>}
                  </button>
                </div>
                <p className="text-[11px]" style={{ color: 'rgba(255,255,255,0.30)' }}>
                  AI generates a 55–65 char SEO title + 148–158 char GEO-rich meta description using your parsed blocks, subject, board, and class as context.
                </p>

                {seoResult && (
                  <div className="mt-3 pt-3 border-t space-y-2.5" style={{ borderColor: 'rgba(139,92,246,0.18)' }}>
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] font-semibold uppercase" style={{ color: 'rgba(255,255,255,0.35)' }}>SEO Title</span>
                        <span className="text-[10px]" style={{ color: (seoResult.char_counts?.title || 0) > 65 ? '#dc2626' : '#16a34a' }}>
                          {seoResult.char_counts?.title || seoResult.seo_title?.length || 0}/65
                        </span>
                      </div>
                      <p className="text-xs font-medium px-3 py-2 rounded-lg" style={{ background: 'rgba(255,255,255,0.05)', color: '#e8e8e8' }}>
                        {seoResult.seo_title}
                      </p>
                    </div>
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] font-semibold uppercase" style={{ color: 'rgba(255,255,255,0.35)' }}>Meta Description</span>
                        <span className="text-[10px]" style={{ color: (seoResult.char_counts?.meta || 0) >= 140 ? '#16a34a' : '#f59e0b' }}>
                          {seoResult.char_counts?.meta || seoResult.meta_description?.length || 0}/160
                        </span>
                      </div>
                      <p className="text-[11px] leading-relaxed px-3 py-2 rounded-lg" style={{ background: 'rgba(255,255,255,0.05)', color: 'rgba(232,232,232,0.70)' }}>
                        {seoResult.meta_description}
                      </p>
                    </div>
                    {seoResult.geo_phrases?.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {seoResult.geo_phrases.map((p, i) => (
                          <span key={i} className="text-[10px] px-2 py-0.5 rounded-lg" style={{ background: 'rgba(16,185,129,0.10)', color: '#34d399', border: '1px solid rgba(16,185,129,0.18)' }}>
                            {p}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="flex gap-2 pt-0.5">
                      <button onClick={applyStudioSeoResult}
                        className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-semibold"
                        style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)', color: '#fff' }}>
                        <CheckCircle size={11} /> Apply Title + Meta
                      </button>
                      <button onClick={() => setSeoResult(null)}
                        className="px-3 rounded-lg text-xs"
                        style={{ background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.40)' }}>
                        Dismiss
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Meta description editor */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs" style={{ color: 'rgba(255,255,255,0.35)' }}>Meta Description <span style={{ color: 'rgba(255,255,255,0.18)' }}>({metaDescription.length}/160)</span></label>
                  {blocks.length > 0 && (
                    <button onClick={() => {
                      const b = blocks.find(b => b.type === 'summary' || b.type === 'note' || b.type === 'definition');
                      if (b) setMetaDescription(b.content.slice(0, 160));
                    }} className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-lg border"
                      style={{ color: '#a78bfa', borderColor: 'rgba(167,139,250,0.25)', background: 'rgba(167,139,250,0.08)' }}>
                      <Zap size={9} /> Auto-fill from block
                    </button>
                  )}
                </div>
                <textarea value={metaDescription} onChange={e => setMetaDescription(e.target.value.slice(0, 160))} rows={2}
                  placeholder="Write a 120–160 char description for Google snippets…"
                  className="w-full px-4 py-2.5 rounded-xl text-sm outline-none resize-none"
                  style={{ color: '#E8E8E8', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }} />
              </div>

              {/* Block list preview */}
              {blocks.length > 0 && (
                <div>
                  <p className="text-xs font-medium mb-2" style={{ color: 'rgba(255,255,255,0.35)' }}>Content Blocks Preview</p>
                  <div className="space-y-3">
                    {blocks.map((block, i) => {
                      const cfg = BLOCK_ICONS[block.type] || BLOCK_ICONS.note;
                      return (
                        <div key={i} className="pb-3 border-b" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
                          <div className="flex items-center gap-2 mb-1.5">
                            <span className="text-[10px] font-bold uppercase" style={{ color: cfg.color }}>{block.type}</span>
                            <span className="text-sm font-semibold" style={{ color: 'rgba(232,232,232,0.80)' }}>{block.title}</span>
                          </div>
                          <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: 'rgba(232,232,232,0.50)' }}>{block.content}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Publish Pipeline ─────────────────────────────────────── */}
          {blocks.length > 0 && (
            <div className="rounded-xl p-5 border" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.08)' }}>
              <p className="text-sm font-semibold mb-4" style={{ color: 'rgba(232,232,232,0.70)' }}>Publish Pipeline</p>

              <div className="grid grid-cols-2 gap-3 mb-3">
                <div>
                  <label className="text-[10px] block mb-1" style={{ color: 'rgba(255,255,255,0.35)' }}>Page Title</label>
                  <input value={title} onChange={e => setTitle(e.target.value)} placeholder="Page title"
                    className="w-full h-9 px-3 rounded-lg text-sm outline-none"
                    style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.10)', color: '#E8E8E8' }} />
                </div>
                <div>
                  <label className="text-[10px] block mb-1" style={{ color: 'rgba(255,255,255,0.35)' }}>URL Slug</label>
                  <input value={slug} onChange={e => setSlug(e.target.value)} placeholder="url-slug"
                    className="w-full h-9 px-3 rounded-lg text-sm font-mono outline-none"
                    style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.10)', color: '#E8E8E8' }} />
                </div>
              </div>

              {/* Computed URL display */}
              {selectedBoardId && slug && (
                <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg text-[10px] font-mono"
                  style={{ background: 'rgba(149,117,224,0.07)', border: '1px solid rgba(149,117,224,0.15)', color: 'rgba(196,176,240,0.70)' }}>
                  <Globe size={10} style={{ color: '#9575e0' }} />
                  syrabit.ai{publishPath}
                  {hasSyllabusBlock && <span className="ml-2 px-1.5 py-0.5 rounded text-[9px]" style={{ background: 'rgba(52,211,153,0.15)', color: '#34d399' }}>+ syllabus stub</span>}
                </div>
              )}

              {/* Quality Gate warning banner */}
              {qualityWarning && qualityScore !== null && (
                <div className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl mb-2 text-sm"
                  style={{ background: 'rgba(245,158,11,0.10)', border: '1px solid rgba(245,158,11,0.30)' }}>
                  <div className="flex items-center gap-2 text-amber-400">
                    <AlertTriangle size={14} />
                    <span>Quality score <strong>{qualityScore}/10</strong> is below the 7-point threshold. Improve content or override.</span>
                  </div>
                  <button onClick={() => handlePublish(false)}
                    className="shrink-0 px-3 py-1 rounded-lg text-xs font-semibold"
                    style={{ background: 'rgba(245,158,11,0.20)', border: '1px solid rgba(245,158,11,0.40)', color: '#fbbf24' }}>
                    Publish Anyway
                  </button>
                </div>
              )}

              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={() => handlePublish(false)} disabled={publishing || qualityChecking || !slug.trim()}
                  className="flex items-center gap-2 disabled:opacity-50 text-white rounded-lg px-5 py-2.5 text-sm font-medium"
                  style={{ background: '#059669' }}>
                  {qualityChecking ? <Loader2 size={14} className="animate-spin" /> : publishing && !qualityWarning ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                  {qualityChecking ? 'Checking quality…' : publishing && !qualityWarning ? 'Publishing…' : 'Publish Page'}
                </button>

                {published && (
                  <button onClick={() => handlePublish(true)} disabled={publishing}
                    className="flex items-center gap-2 disabled:opacity-50 text-white rounded-lg px-4 py-2.5 text-sm font-medium"
                    style={{ background: 'rgba(245,158,11,0.20)', border: '1px solid rgba(245,158,11,0.30)', color: '#fbbf24' }}>
                    {publishing && isRevision ? <Loader2 size={14} className="animate-spin" /> : <GitBranch size={14} />}
                    Publish Revision
                  </button>
                )}

                <button onClick={handleSaveDraft} disabled={draftSaving}
                  className="flex items-center gap-2 disabled:opacity-50 rounded-lg px-4 py-2.5 text-sm font-medium"
                  style={{ background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.20)', color: '#fbbf24' }}>
                  {draftSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  {draftSaving ? 'Saving…' : draftId ? 'Update Draft' : 'Save Draft'}
                </button>

                {published && (
                  <div className="flex items-center gap-2 text-sm" style={{ color: '#34d399' }}>
                    <CheckCircle size={14} />
                    Live at <code className="text-xs px-2 py-0.5 rounded" style={{ background: 'rgba(52,211,153,0.10)', color: '#6ee7b7' }}>{published.url}</code>
                    <a href={published.url} target="_blank" rel="noreferrer"><ExternalLink size={12} /></a>
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
