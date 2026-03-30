/**
 * BlogPublishWizard — 5-step locked progressive wizard for publishing SEO & GEO blog pages.
 * Replaces the flat tab-based AdminContentHub for the Content section.
 *
 * Steps:
 *  1. Target & Scope  — board/class/stream/subject, working title, keyword, content type
 *  2. Draft Content   — MDX editor + PDF upload, word count ≥ 150 to unlock next
 *  3. AI Enrichment   — call studio/parse, before/after preview, accept or re-run
 *  4. SEO & GEO Meta  — auto-fill via seo/generate, all fields editable, validation
 *  5. Review & Publish — checklist summary, Save Draft + Publish Now, success banner
 *
 * Wizard state is persisted to localStorage under "syrabit_wpwizard_state".
 * "My Documents" drawer accessible from the wizard header.
 */
import { useReducer, useEffect, useRef, useCallback, useState } from 'react';
import {
  ChevronRight, ChevronLeft, Check, Loader2, Sparkles, FileUp,
  Globe, Lock, Copy, ExternalLink, RefreshCw, FileText, BookOpen,
  Layers, HelpCircle, Calculator, StickyNote, List, X, Plus, Trash2,
  Eye, AlertCircle, CheckCircle2, Target, Edit3, Zap, BarChart3,
} from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import SharedMdxEditor from './SharedMdxEditor';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

function authHeaders(token) {
  const isRealJwt = token && token.split('.').length === 3;
  return { headers: isRealJwt ? { Authorization: `Bearer ${token}` } : {}, withCredentials: true };
}

function autoSlug(text) {
  return (text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '');
}

function wordCount(text) {
  return (text || '').trim().split(/\s+/).filter(Boolean).length;
}

// ── localStorage persistence ───────────────────────────────────────────────
const LS_KEY = 'syrabit_wpwizard_state';

function loadState() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch { return null; }
}

function saveState(state) {
  try { localStorage.setItem(LS_KEY, JSON.stringify({ ...state, _ts: Date.now() })); } catch {}
}

// ── Reducer ────────────────────────────────────────────────────────────────
const INITIAL_STATE = {
  step: 1,           // 1-5
  unlocked: [1],     // steps that are unlocked
  docId: null,       // created CMS document id
  canonicalUrl: '',  // from link-syllabus response

  // Step 1
  boardId: '', boardName: '',
  classId: '', className: '',
  streamId: '', streamName: '',
  subjectId: '', subjectName: '',
  workingTitle: '',
  primaryKeyword: '',
  contentType: 'Article',

  // Step 2
  draftContent: '',

  // Step 3
  enrichedBlocks: null,  // array of blocks from studio/parse
  enrichedContent: '',   // accepted markdown from blocks
  enrichmentAccepted: false,

  // Step 4
  seoSlug: '',
  seoTitle: '',
  metaDescription: '',
  seoTags: '',
  geoTags: '',
  schemaType: 'Article',
  thumbnailUrl: '',
  altText: '',

  // Step 5
  publishedStatus: 'draft', // draft | published
};

function reducer(state, action) {
  switch (action.type) {
    case 'RESET':
      return { ...INITIAL_STATE };
    case 'LOAD':
      return { ...INITIAL_STATE, ...action.payload };
    case 'SET':
      return { ...state, ...action.payload };
    case 'GO_STEP': {
      const step = action.step;
      const unlocked = state.unlocked.includes(step)
        ? state.unlocked
        : [...state.unlocked, step];
      return { ...state, step, unlocked };
    }
    case 'UNLOCK_NEXT': {
      const next = state.step + 1;
      if (next > 5) return state;
      const unlocked = state.unlocked.includes(next) ? state.unlocked : [...state.unlocked, next];
      return { ...state, unlocked };
    }
    default:
      return state;
  }
}

// ── Step definitions ───────────────────────────────────────────────────────
const STEPS = [
  { id: 1, label: 'Target & Scope',   icon: Target },
  { id: 2, label: 'Draft Content',    icon: Edit3  },
  { id: 3, label: 'AI Enrichment',    icon: Sparkles },
  { id: 4, label: 'SEO & GEO Meta',  icon: BarChart3 },
  { id: 5, label: 'Review & Publish', icon: Globe  },
];

const SCHEMA_TYPES = ['Article', 'FAQPage', 'HowTo', 'StudyNotes', 'Course'];
const CONTENT_TYPES = ['Article', 'FAQPage', 'StudyNotes'];

// ── Block type icons for enrichment preview ────────────────────────────────
const BLOCK_ICONS = {
  summary:    { icon: FileText,   color: '#8b5cf6' },
  definition: { icon: BookOpen,   color: '#3b82f6' },
  example:    { icon: Layers,     color: '#10b981' },
  pyq:        { icon: HelpCircle, color: '#f59e0b' },
  formula:    { icon: Calculator, color: '#ec4899' },
  note:       { icon: StickyNote, color: '#64748b' },
  faq:        { icon: HelpCircle, color: '#06b6d4' },
  syllabus:   { icon: List,       color: '#34d399' },
};

// ─────────────────────────────────────────────────────────────────────────────
export default function BlogPublishWizard({ adminToken, hubContext, onHubContext }) {
  const [state, dispatch] = useReducer(reducer, null, () => {
    const saved = loadState();
    return saved ? { ...INITIAL_STATE, ...saved } : INITIAL_STATE;
  });

  // Hierarchy data
  const [boards, setBoards] = useState([]);
  const [classes, setClasses] = useState([]);
  const [streams, setStreams] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [hierarchyLoading, setHierarchyLoading] = useState(true);

  // My Documents drawer
  const [docsOpen, setDocsOpen] = useState(false);
  const [docs, setDocs] = useState([]);
  const [docsLoading, setDocsLoading] = useState(false);

  // Auto-flow flag — set when arriving from Content Editor handoff
  const autoFlowRef = useRef(false);
  const [autoFlow, setAutoFlow] = useState(false);

  // Save state to localStorage whenever it changes
  useEffect(() => { saveState(state); }, [state]);

  // ── Content Editor handoff: read syrabit_blog_prefill on mount ───────────────
  useEffect(() => {
    try {
      const raw = localStorage.getItem('syrabit_blog_prefill');
      if (!raw) return;
      const pf = JSON.parse(raw);
      if (Date.now() - (pf.timestamp || 0) > 10 * 60 * 1000) {
        localStorage.removeItem('syrabit_blog_prefill');
        return;
      }
      localStorage.removeItem('syrabit_blog_prefill');
      if (!pf.subjectId) return;
      autoFlowRef.current = !!pf.autoFlow;
      if (pf.autoFlow) setAutoFlow(true);
      dispatch({ type: 'SET', payload: {
        subjectId:      pf.subjectId      || '',
        subjectName:    pf.subjectName    || '',
        workingTitle:   pf.workingTitle   || '',
        primaryKeyword: pf.primaryKeyword || '',
        draftContent:   pf.draftContent   || '',
        // Reset doc/steps so wizard starts fresh for this subject
        docId:    null,
        step:     1,
        unlocked: [1],
        enrichedBlocks: null,
        enrichedContent: '',
        enrichmentAccepted: false,
        seoSlug: '', seoTitle: '', metaDescription: '',
        seoTags: '', geoTags: '',
        publishedStatus: 'draft',
      }});
      toast.success('Content Editor handoff — scope & draft pre-filled!');
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Resolve full hierarchy IDs once data is loaded ───────────────────────────
  // When prefill only has subjectId, look up board/class/stream IDs from loaded lists
  useEffect(() => {
    if (!state.subjectId || state.boardId) return;   // already resolved or nothing to resolve
    if (!subjects.length || !streams.length) return; // data not yet loaded
    const subj    = subjects.find(s => s.id === state.subjectId);
    if (!subj) return;
    const stream  = streams.find(s => s.id === subj.stream_id);
    const cls     = stream ? classes.find(c => c.id === stream.class_id) : null;
    const board   = cls    ? boards.find(b => b.id === cls.board_id)     : null;
    dispatch({ type: 'SET', payload: {
      boardId:   board?.id   || '',  boardName:  board?.name  || '',
      classId:   cls?.id     || '',  className:  cls?.name    || '',
      streamId:  stream?.id  || '',  streamName: stream?.name || '',
    }});
  }, [state.subjectId, subjects, streams, classes, boards]);

  // ── Hub context IN: pre-fill scope from other Content Hub tabs ──────────────
  // Fires when the user switches to Blog Publisher from Syllabus / Editor / PYQ
  // tabs that already have a subject selected. Only applies when the wizard has
  // no scope of its own so we never stomp over the user's in-progress work.
  useEffect(() => {
    if (!hubContext?.subjectId) return;
    if (state.subjectId) return; // wizard already has a scope — leave it alone
    dispatch({ type: 'SET', payload: {
      boardId:     hubContext.boardId    || '',
      boardName:   hubContext.boardName  || '',
      classId:     hubContext.classId    || '',
      className:   hubContext.className  || '',
      streamId:    hubContext.streamId   || '',
      streamName:  hubContext.streamName || '',
      subjectId:   hubContext.subjectId  || '',
      subjectName: hubContext.subjectName|| '',
    }});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hubContext?.subjectId]);

  // ── Hub context OUT: broadcast scope back to other tabs ─────────────────────
  // When the user picks a subject inside the wizard, update hub context so that
  // switching to Editor / AI Studio / PYQ reflects the same subject.
  useEffect(() => {
    if (!onHubContext || !state.subjectId) return;
    onHubContext({
      boardId:     state.boardId,
      boardName:   state.boardName,
      classId:     state.classId,
      className:   state.className,
      streamId:    state.streamId,
      streamName:  state.streamName,
      subjectId:   state.subjectId,
      subjectName: state.subjectName,
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.subjectId]);

  // Load hierarchy data
  useEffect(() => {
    setHierarchyLoading(true);
    const nc = `?_=${Date.now()}`;
    Promise.all([
      axios.get(`${API}/content/boards${nc}`),
      axios.get(`${API}/content/classes${nc}`),
      axios.get(`${API}/content/streams${nc}`),
      axios.get(`${API}/content/subjects${nc}`),
    ])
      .then(([b, c, s, sub]) => {
        setBoards(b.data || []);
        setClasses(c.data || []);
        setStreams(s.data || []);
        setSubjects(sub.data || []);
      })
      .catch(() => toast.error('Failed to load content hierarchy'))
      .finally(() => setHierarchyLoading(false));
  }, []);

  const loadDocs = useCallback(async () => {
    setDocsLoading(true);
    try {
      const res = await axios.get(`${API}/admin/content/cms-documents`, authHeaders(adminToken));
      setDocs(res.data || []);
    } catch { toast.error('Failed to load documents'); }
    finally { setDocsLoading(false); }
  }, [adminToken]);

  const openDocs = () => { setDocsOpen(true); loadDocs(); };

  const loadExistingDoc = (doc) => {
    dispatch({ type: 'SET', payload: {
      step: 4,
      unlocked: [1, 2, 3, 4, 5],
      docId: doc.id,
      workingTitle: doc.title || '',
      primaryKeyword: doc.primary_keyword || '',
      contentType: doc.schema_type || 'Article',
      draftContent: doc.content || '',
      enrichedContent: doc.content || '',
      enrichmentAccepted: true,
      // Reconstruct scope from linked_* fields stored by link-syllabus endpoint
      boardId:     doc.linked_board_id   || '',
      boardName:   doc.linked_board_name || '',
      classId:     doc.linked_class_id   || '',
      className:   doc.linked_class_name || '',
      streamId:    doc.linked_stream_id  || '',
      streamName:  doc.linked_stream_name|| '',
      subjectId:   doc.linked_subject_id || '',
      subjectName: doc.linked_subject_name || '',
      seoSlug: doc.seo_slug || '',
      seoTitle: doc.title || '',
      metaDescription: doc.meta_description || '',
      seoTags: doc.seo_tags || '',
      geoTags: doc.geo_tags || '',
      schemaType: doc.schema_type || 'Article',
      thumbnailUrl: doc.thumbnail_url || '',
      altText: doc.alt_text || '',
      publishedStatus: doc.status || 'draft',
      canonicalUrl: doc.canonical_url || '',
    }});
    setDocsOpen(false);
    toast.success(`Loaded "${doc.title}" — continuing from SEO step`);
  };

  const resetWizard = () => {
    if (!confirm('Start a new document? Your current progress will be saved in "My Documents".')) return;
    dispatch({ type: 'RESET' });
    localStorage.removeItem(LS_KEY);
    toast.success('Wizard reset — start fresh!');
  };

  const set = (patch) => dispatch({ type: 'SET', payload: patch });
  const goStep = (step) => {
    if (!state.unlocked.includes(step)) return;
    dispatch({ type: 'GO_STEP', step });
  };

  const goNext = () => {
    dispatch({ type: 'UNLOCK_NEXT' });
    dispatch({ type: 'GO_STEP', step: state.step + 1 });
  };

  const goPrev = () => {
    if (state.step > 1) dispatch({ type: 'GO_STEP', step: state.step - 1 });
  };

  return (
    <div className="h-full flex flex-col" style={{ background: '#06060e' }}>

      {/* ── Wizard Header ─────────────────────────────────────────────── */}
      <div className="border-b flex-shrink-0 px-4 py-2 flex items-center justify-between gap-3"
        style={{ borderColor: 'rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.02)' }}>
        <div className="flex items-center gap-2">
          <Globe size={14} className="text-violet-400" />
          <span className="text-xs font-bold text-white/60 uppercase tracking-widest">Blog Publish Wizard</span>
          {state.docId && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full font-semibold"
              style={{ background: 'rgba(139,92,246,0.18)', color: '#c4b5fd' }}>
              doc #{state.docId.slice(-6)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={openDocs}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition"
            style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.50)' }}
          >
            <FileText size={12} /> My Documents
          </button>
          <button
            onClick={resetWizard}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition"
            style={{ background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.35)' }}
          >
            <RefreshCw size={11} /> New Doc
          </button>
        </div>
      </div>

      {/* ── Step Tracker ──────────────────────────────────────────────── */}
      <div className="border-b flex-shrink-0 px-4 py-3"
        style={{ borderColor: 'rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.015)' }}>
        <div className="flex items-center gap-0">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            const isActive = state.step === s.id;
            const isDone = state.unlocked.includes(s.id + 1) || (state.step > s.id);
            const isLocked = !state.unlocked.includes(s.id);
            return (
              <div key={s.id} className="flex items-center flex-1 min-w-0">
                <button
                  onClick={() => goStep(s.id)}
                  disabled={isLocked}
                  className="flex items-center gap-1.5 min-w-0 transition-all"
                  style={{ opacity: isLocked ? 0.35 : 1, cursor: isLocked ? 'not-allowed' : 'pointer' }}
                >
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 transition-all ${
                    isActive
                      ? 'bg-violet-600'
                      : isDone
                      ? 'bg-emerald-500/80'
                      : 'bg-white/10'
                  }`}>
                    {isDone && !isActive
                      ? <Check size={12} className="text-white" />
                      : <Icon size={11} className={isActive ? 'text-white' : 'text-white/50'} />}
                  </div>
                  <div className="min-w-0 hidden sm:block">
                    <p className={`text-[10px] font-bold truncate ${isActive ? 'text-violet-300' : isDone ? 'text-emerald-400' : 'text-white/35'}`}>
                      Step {s.id}
                    </p>
                    <p className={`text-[10px] truncate ${isActive ? 'text-white/70' : 'text-white/30'}`}>{s.label}</p>
                  </div>
                </button>
                {i < STEPS.length - 1 && (
                  <div className="flex-1 h-px mx-2 hidden sm:block"
                    style={{ background: state.unlocked.includes(s.id + 1) ? 'rgba(52,211,153,0.40)' : 'rgba(255,255,255,0.08)' }} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Auto-flow banner ──────────────────────────────────────────── */}
      {autoFlow && (
        <div className="flex-shrink-0 flex items-center gap-2 px-4 py-2"
          style={{ background: 'rgba(139,92,246,0.10)', borderBottom: '1px solid rgba(139,92,246,0.18)' }}>
          <Sparkles size={12} className="text-violet-400 flex-shrink-0" />
          <span className="text-[11px] text-violet-300 font-medium">
            Auto-flow active — scope & draft pre-filled from Content Editor. AI steps will run automatically.
          </span>
          <button onClick={() => setAutoFlow(false)}
            className="ml-auto text-white/30 hover:text-white/60 transition flex-shrink-0">
            <X size={11} />
          </button>
        </div>
      )}

      {/* ── Step Content ──────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto">
        {state.step === 1 && (
          <Step1TargetScope
            state={state} set={set} goNext={goNext}
            boards={boards} classes={classes} streams={streams} subjects={subjects}
            hierarchyLoading={hierarchyLoading}
            adminToken={adminToken}
            autoRun={autoFlow}
          />
        )}
        {state.step === 2 && (
          <Step2DraftContent
            state={state} set={set} goNext={goNext} goPrev={goPrev}
            adminToken={adminToken}
            autoRun={autoFlow}
          />
        )}
        {state.step === 3 && (
          <Step3AiEnrichment
            state={state} set={set} goNext={goNext} goPrev={goPrev}
            adminToken={adminToken}
            autoRun={autoFlow}
          />
        )}
        {state.step === 4 && (
          <Step4SeoMeta
            state={state} set={set} goNext={goNext} goPrev={goPrev}
            adminToken={adminToken}
            autoRun={autoFlow}
          />
        )}
        {state.step === 5 && (
          <Step5ReviewPublish
            state={state} set={set} goPrev={goPrev}
            adminToken={adminToken}
            autoRun={autoFlow}
          />
        )}
      </div>

      {/* ── My Documents Drawer ───────────────────────────────────────── */}
      {docsOpen && (
        <DocsDrawer
          docs={docs}
          loading={docsLoading}
          onClose={() => setDocsOpen(false)}
          onLoad={loadExistingDoc}
          adminToken={adminToken}
          onRefresh={loadDocs}
        />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 1 — Target & Scope
// ─────────────────────────────────────────────────────────────────────────────
function Step1TargetScope({ state, set, goNext, boards, classes, streams, subjects, hierarchyLoading, adminToken, autoRun }) {
  const [saving, setSaving] = useState(false);
  const [linkingScope, setLinkingScope] = useState(false);
  const [linkError, setLinkError] = useState(false);
  const autoRunFired1 = useRef(false);

  const filteredClasses = state.boardId ? classes.filter(c => c.board_id === state.boardId) : [];
  const filteredStreams = state.classId ? streams.filter(s => s.class_id === state.classId) : [];
  const classStreamIds = filteredStreams.map(s => s.id);
  // If a specific stream is selected, filter by it; otherwise show all subjects under any
  // stream of this class (handles classes that have no stream level in their hierarchy).
  const filteredSubjects = state.classId
    ? (state.streamId
        ? subjects.filter(s => s.stream_id === state.streamId)
        : subjects.filter(s => classStreamIds.includes(s.stream_id)))
    : [];

  const canContinue = state.subjectId && state.primaryKeyword.trim();

  useEffect(() => {
    if (!autoRun || autoRunFired1.current || saving || linkingScope) return;
    if (!canContinue || !state.boardId) return;
    autoRunFired1.current = true;
    const t = setTimeout(() => handleContinue(), 600);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, canContinue, state.boardId, saving, linkingScope]);

  const handleContinue = async () => {
    if (!canContinue) return;
    setSaving(true);
    try {
      // Create or update CMS document draft
      let docId = state.docId;
      // For a new document, initialise all fields; for an existing doc, only update
      // scope/title/keyword/schema — never overwrite previously written content/metadata.
      const newDocPayload = {
        title: state.workingTitle || `${state.subjectName} — Draft`,
        primary_keyword: state.primaryKeyword,
        schema_type: state.contentType,
        status: 'draft',
        content: '',
        meta_description: '',
        seo_slug: autoSlug(state.workingTitle || state.subjectName),
      };
      const updatePayload = {
        title: state.workingTitle || `${state.subjectName} — Draft`,
        primary_keyword: state.primaryKeyword,
        schema_type: state.contentType,
        seo_slug: state.seoSlug || autoSlug(state.workingTitle || state.subjectName),
      };

      if (!docId) {
        const res = await axios.post(`${API}/admin/content/cms-documents`, newDocPayload, authHeaders(adminToken));
        docId = res.data.id;
        set({ docId });
      } else {
        await axios.patch(`${API}/admin/content/cms-documents/${docId}`, updatePayload, authHeaders(adminToken));
      }

      // Auto link-syllabus when scope is set
      if (state.subjectId) {
        setLinkingScope(true);
        setLinkError(false);
        try {
          const linkRes = await axios.post(
            `${API}/admin/content/cms-documents/${docId}/link-syllabus`,
            {
              board_id: state.boardId,
              class_id: state.classId,
              stream_id: state.streamId,
              subject_id: state.subjectId,
            },
            authHeaders(adminToken)
          );
          set({
            docId,
            canonicalUrl: linkRes.data.canonical_url || '',
            geoTags: linkRes.data.geo_tags || state.geoTags,
          });
          goNext();
        } catch (e) {
          toast.error(e.response?.data?.detail || 'Scope link failed — please retry');
          setLinkError(true);
          set({ docId });
        } finally {
          setLinkingScope(false);
        }
      } else {
        set({ docId });
        goNext();
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to create document draft');
    } finally { setSaving(false); }
  };

  const inp = 'w-full h-9 px-3 rounded-lg text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500 transition';
  const sel = 'w-full h-9 px-3 rounded-lg text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500 transition cursor-pointer';
  const lbl = 'text-xs font-semibold text-white/50 mb-1 block';

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h2 className="text-base font-bold text-white">Step 1 — Target & Scope</h2>
        <p className="text-xs text-white/40 mt-1">Select the board/class/subject scope and define the primary keyword.</p>
      </div>

      <div className="space-y-4">
        {/* Board */}
        <div>
          <label className={lbl}>Board *</label>
          <select className={sel} value={state.boardId}
            onChange={e => {
              const b = boards.find(x => x.id === e.target.value);
              set({ boardId: e.target.value, boardName: b?.name || '', classId: '', className: '', streamId: '', streamName: '', subjectId: '', subjectName: '' });
            }}>
            <option value="">Select Board…</option>
            {boards.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>

        {/* Class */}
        <div>
          <label className={lbl}>Class *</label>
          <select className={sel} value={state.classId} disabled={!state.boardId}
            onChange={e => {
              const c = filteredClasses.find(x => x.id === e.target.value);
              set({ classId: e.target.value, className: c?.name || '', streamId: '', streamName: '', subjectId: '', subjectName: '' });
            }}>
            <option value="">Select Class…</option>
            {filteredClasses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>

        {/* Stream */}
        {filteredStreams.length > 0 && (
          <div>
            <label className={lbl}>Stream</label>
            <select className={sel} value={state.streamId}
              onChange={e => {
                const s = filteredStreams.find(x => x.id === e.target.value);
                set({ streamId: e.target.value, streamName: s?.name || '', subjectId: '', subjectName: '' });
              }}>
              <option value="">Select Stream…</option>
              {filteredStreams.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
        )}

        {/* Subject */}
        <div>
          <label className={lbl}>Subject *</label>
          <select className={sel} value={state.subjectId} disabled={!state.classId}
            onChange={e => {
              const s = filteredSubjects.find(x => x.id === e.target.value);
              set({ subjectId: e.target.value, subjectName: s?.name || '' });
            }}>
            <option value="">Select Subject…</option>
            {filteredSubjects.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>

        {/* Working Title */}
        <div>
          <label className={lbl}>Working Title</label>
          <input className={inp} placeholder="e.g. Photosynthesis — Complete Notes AHSEC 2024"
            value={state.workingTitle}
            onChange={e => set({ workingTitle: e.target.value })} />
        </div>

        {/* Primary Keyword */}
        <div>
          <label className={lbl}>Primary Keyword *</label>
          <input className={inp} placeholder="e.g. photosynthesis class 12 ahsec"
            value={state.primaryKeyword}
            onChange={e => set({ primaryKeyword: e.target.value })} />
          <p className="text-[10px] text-white/25 mt-1">4–7 words. This is the core search query you're targeting.</p>
        </div>

        {/* Content Type */}
        <div>
          <label className={lbl}>Content Type</label>
          <div className="flex gap-2 flex-wrap">
            {CONTENT_TYPES.map(t => (
              <button key={t}
                onClick={() => set({ contentType: t })}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${state.contentType === t ? 'bg-violet-600 text-white' : 'bg-white/5 text-white/50 hover:bg-white/10'}`}>
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Scope summary */}
        {state.subjectId && (
          <div className="rounded-xl p-3" style={{ background: 'rgba(139,92,246,0.10)', border: '1px solid rgba(139,92,246,0.20)' }}>
            <p className="text-xs font-semibold text-violet-300 mb-1">Selected Scope</p>
            <p className="text-xs text-white/60">
              {[state.boardName, state.className, state.streamName, state.subjectName].filter(Boolean).join(' → ')}
            </p>
          </div>
        )}
      </div>

      {linkError && (
        <div className="mt-3 flex items-center justify-between gap-3 rounded-xl px-3 py-2"
          style={{ background: 'rgba(239,68,68,0.10)', border: '1px solid rgba(239,68,68,0.25)' }}>
          <span className="text-xs text-red-400">Scope link failed. Please retry to proceed.</span>
          <button onClick={handleContinue} disabled={saving || linkingScope}
            className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold transition"
            style={{ background: 'rgba(239,68,68,0.18)', color: '#fca5a5' }}>
            {linkingScope ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
            Retry
          </button>
        </div>
      )}

      <div className="mt-6 flex justify-end">
        <button
          onClick={handleContinue}
          disabled={!canContinue || saving || linkingScope}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
          style={{ background: canContinue ? '#7c3aed' : 'rgba(255,255,255,0.08)', color: canContinue ? 'white' : 'rgba(255,255,255,0.4)' }}
        >
          {(saving || linkingScope) ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} />}
          {saving ? 'Creating document…' : linkingScope ? 'Linking scope…' : 'Continue to Draft'}
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 2 — Draft Content
// ─────────────────────────────────────────────────────────────────────────────
function Step2DraftContent({ state, set, goNext, goPrev, adminToken, autoRun }) {
  const [saving, setSaving] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [editorKey, setEditorKey] = useState(0);
  const editorRef = useRef(null);
  const pdfRef = useRef(null);
  const autoRunFired2 = useRef(false);

  const wc = wordCount(state.draftContent);
  const canContinue = wc >= 150;

  const handleContentChange = (val) => {
    set({ draftContent: val });
  };

  useEffect(() => {
    if (!autoRun || autoRunFired2.current || saving) return;
    if (!canContinue || !state.docId) return;
    autoRunFired2.current = true;
    const t = setTimeout(() => handleContinue(), 600);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, canContinue, state.docId, saving]);

  const handlePdfUpload = async () => {
    const file = pdfRef.current?.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) { toast.error('Only PDF files accepted'); return; }
    setPdfLoading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await axios.post(`${API}/admin/content/extract-pdf-text`, formData, {
        ...authHeaders(adminToken),
        headers: { ...authHeaders(adminToken).headers, 'Content-Type': 'multipart/form-data' },
      });
      const extracted = res.data.text || '';
      if (!extracted) { toast.error('No text extracted from PDF'); return; }
      const current = editorRef.current?.getMarkdown() || state.draftContent;
      const updated = current ? `${current}\n\n---\n\n${extracted}` : extracted;
      set({ draftContent: updated });
      setEditorKey(k => k + 1);
      toast.success(`Extracted ${res.data.chars?.toLocaleString() || '?'} chars from ${res.data.pages} pages`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'PDF extraction failed');
    } finally {
      setPdfLoading(false);
      if (pdfRef.current) pdfRef.current.value = '';
    }
  };

  const handleContinue = async () => {
    if (!canContinue || !state.docId) return;
    setSaving(true);
    try {
      const liveContent = editorRef.current?.getMarkdown() || state.draftContent;
      set({ draftContent: liveContent });
      await axios.patch(
        `${API}/admin/content/cms-documents/${state.docId}`,
        { title: state.workingTitle || 'Draft', content: liveContent, status: 'draft', primary_keyword: state.primaryKeyword, schema_type: state.contentType },
        authHeaders(adminToken)
      );
      goNext();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to save draft content');
    } finally { setSaving(false); }
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header bar */}
      <div className="px-6 pt-5 pb-3 flex items-center justify-between flex-shrink-0">
        <div>
          <h2 className="text-base font-bold text-white">Step 2 — Draft Content</h2>
          <p className="text-xs text-white/40 mt-0.5">Write, paste, or extract content. Need ≥ 150 words to continue.</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Word count indicator */}
          <div className={`text-xs font-semibold px-2.5 py-1 rounded-lg ${canContinue ? 'text-emerald-400 bg-emerald-500/10' : 'text-amber-400 bg-amber-500/10'}`}>
            {wc} / 150 words
          </div>
          {/* PDF upload */}
          <input ref={pdfRef} type="file" accept=".pdf" className="hidden" onChange={handlePdfUpload} />
          <button
            onClick={() => pdfRef.current?.click()}
            disabled={pdfLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition disabled:opacity-50"
            style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.25)' }}
          >
            {pdfLoading ? <Loader2 size={12} className="animate-spin" /> : <FileUp size={12} />}
            {pdfLoading ? 'Extracting…' : 'From PDF'}
          </button>
        </div>
      </div>

      {/* Editor (flexible height) */}
      <div className="flex-1 mx-6 mb-4 rounded-xl overflow-hidden border" style={{ borderColor: 'rgba(255,255,255,0.10)', minHeight: 300 }}>
        <SharedMdxEditor
          key={editorKey}
          ref={editorRef}
          markdown={state.draftContent}
          onChange={handleContentChange}
          editorKey={`step2-draft-${editorKey}`}
        />
      </div>

      {/* Word count progress bar */}
      <div className="px-6 mb-4 flex-shrink-0">
        <div className="h-1.5 rounded-full bg-white/5 overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${Math.min(100, (wc / 150) * 100)}%`,
              background: canContinue ? '#10b981' : '#f59e0b',
            }}
          />
        </div>
      </div>

      {/* Navigation */}
      <div className="px-6 pb-5 flex items-center justify-between flex-shrink-0">
        <button onClick={goPrev}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-white/50 hover:text-white/80 transition">
          <ChevronLeft size={14} /> Back
        </button>
        <button
          onClick={handleContinue}
          disabled={!canContinue || saving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
          style={{ background: canContinue ? '#7c3aed' : 'rgba(255,255,255,0.08)', color: canContinue ? 'white' : 'rgba(255,255,255,0.4)' }}
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} />}
          {saving ? 'Saving…' : `Continue to AI Enrichment`}
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 3 — AI Enrichment
// ─────────────────────────────────────────────────────────────────────────────
function Step3AiEnrichment({ state, set, goNext, goPrev, adminToken, autoRun }) {
  const [enriching, setEnriching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [localBlocks, setLocalBlocks] = useState(state.enrichedBlocks || null);
  const autoRunFired3 = useRef(false);

  const handleEnrich = async () => {
    if (!state.draftContent.trim()) { toast.error('No draft content to enrich'); return; }
    setEnriching(true);
    try {
      const res = await axios.post(`${API}/admin/studio/parse`, {
        raw_text: state.draftContent,
        subject: state.subjectName || '',
        chapter: state.workingTitle || '',
      }, authHeaders(adminToken));
      const blocks = res.data.blocks || [];
      if (!blocks.length) { toast.error('AI could not parse content — try re-running'); return; }
      setLocalBlocks(blocks);
      set({ enrichedBlocks: blocks });
      toast.success(`AI structured ${blocks.length} content blocks`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'AI enrichment failed — retry');
    } finally { setEnriching(false); }
  };

  const handleAccept = async () => {
    if (!localBlocks?.length) return;
    setSaving(true);
    setSaveError(false);
    try {
      const enrichedMd = localBlocks.map(b => `## ${b.title}\n\n${b.content}`).join('\n\n---\n\n');
      set({ enrichedContent: enrichedMd, enrichmentAccepted: true, enrichedBlocks: localBlocks });
      await axios.patch(
        `${API}/admin/content/cms-documents/${state.docId}`,
        { title: state.workingTitle || 'Draft', content: enrichedMd, status: 'draft' },
        authHeaders(adminToken)
      );
      goNext();
      toast.success('Enriched content accepted and saved');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to save enriched content');
      setSaveError(true);
    } finally { setSaving(false); }
  };

  const removeBlock = (idx) => {
    const updated = localBlocks.filter((_, i) => i !== idx);
    setLocalBlocks(updated);
  };

  // Auto-trigger enrichment when arriving from Content Editor handoff
  useEffect(() => {
    if (!autoRun || autoRunFired3.current || localBlocks || !state.draftContent) return;
    autoRunFired3.current = true;
    const t = setTimeout(() => handleEnrich(), 400);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-accept enrichment once blocks are ready in autoRun mode
  const autoAcceptFired = useRef(false);
  useEffect(() => {
    if (!autoRun || autoAcceptFired.current || !localBlocks?.length || enriching || saving) return;
    autoAcceptFired.current = true;
    const t = setTimeout(() => handleAccept(), 800);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, localBlocks, enriching, saving]);

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-white">Step 3 — AI Enrichment</h2>
          <p className="text-xs text-white/40 mt-1">Let AI restructure your draft into rich GEO-optimized content blocks.</p>
        </div>
        <button
          onClick={handleEnrich}
          disabled={enriching}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition flex-shrink-0"
          style={{ background: 'rgba(139,92,246,0.20)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.30)' }}
        >
          {enriching ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {enriching ? 'Enriching…' : localBlocks ? 'Re-run AI' : 'Enrich with AI'}
        </button>
      </div>

      {/* Before — raw draft stats */}
      <div className="rounded-xl p-4 mb-4" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}>
        <p className="text-xs font-semibold text-white/40 mb-2">BEFORE (Raw Draft)</p>
        <p className="text-xs text-white/50">{wordCount(state.draftContent)} words · {state.draftContent.length} chars</p>
        <p className="text-xs text-white/30 mt-1 line-clamp-2">{state.draftContent.slice(0, 200)}…</p>
      </div>

      {/* After — enriched blocks */}
      {localBlocks && localBlocks.length > 0 && (
        <>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-semibold text-white/40">AFTER (AI-Enriched — {localBlocks.length} blocks)</span>
          </div>
          <div className="space-y-3 mb-5">
            {localBlocks.map((block, i) => {
              const cfg = BLOCK_ICONS[block.type] || BLOCK_ICONS.note;
              const Icon = cfg.icon;
              return (
                <div key={i} className="rounded-xl p-4 border group" style={{ borderColor: 'rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.025)' }}>
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ background: `${cfg.color}18` }}>
                      <Icon size={12} style={{ color: cfg.color }} />
                    </div>
                    <span className="text-[10px] font-bold uppercase tracking-wider flex-shrink-0" style={{ color: cfg.color }}>{block.type}</span>
                    <span className="text-sm font-medium text-white/70 truncate min-w-0">{block.title}</span>
                    <button onClick={() => removeBlock(i)}
                      className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity text-red-400/70 hover:text-red-400 flex-shrink-0">
                      <X size={12} />
                    </button>
                  </div>
                  <p className="text-xs text-white/40 leading-relaxed line-clamp-3">{block.content}</p>
                </div>
              );
            })}
          </div>
        </>
      )}

      {!localBlocks && !enriching && (
        <div className="rounded-xl p-8 text-center mb-5" style={{ background: 'rgba(255,255,255,0.02)', border: '1px dashed rgba(255,255,255,0.08)' }}>
          <Sparkles size={24} className="text-violet-400 mx-auto mb-2" />
          <p className="text-sm text-white/40">Click "Enrich with AI" to restructure your content into definitions, FAQs, examples, and GEO authority phrases.</p>
        </div>
      )}

      {saveError && (
        <div className="mb-3 flex items-center justify-between gap-3 rounded-xl px-3 py-2"
          style={{ background: 'rgba(239,68,68,0.10)', border: '1px solid rgba(239,68,68,0.25)' }}>
          <span className="text-xs text-red-400">Save failed. Click "Accept & Continue" again to retry.</span>
          <RefreshCw size={12} className="text-red-400 flex-shrink-0" />
        </div>
      )}
      <div className="flex items-center justify-between">
        <button onClick={goPrev}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-white/50 hover:text-white/80 transition">
          <ChevronLeft size={14} /> Back
        </button>
        <button
          onClick={handleAccept}
          disabled={!localBlocks?.length || saving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
          style={{ background: localBlocks?.length ? '#7c3aed' : 'rgba(255,255,255,0.08)', color: localBlocks?.length ? 'white' : 'rgba(255,255,255,0.4)' }}
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
          {saving ? 'Saving…' : saveError ? 'Retry Save' : 'Accept & Continue'}
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tag Chips — reusable chip-input for comma-separated string values
// ─────────────────────────────────────────────────────────────────────────────
function TagChips({ value, onChange, placeholder }) {
  const [input, setInput] = useState('');
  const tags = value ? value.split(',').map(t => t.trim()).filter(Boolean) : [];
  const addTag = () => {
    if (!input.trim()) return;
    onChange([...tags, input.trim()].join(', '));
    setInput('');
  };
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-1.5">
        {tags.map((t, i) => (
          <span key={i} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs"
            style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd' }}>
            {t}
            <button onClick={() => onChange(tags.filter((_, idx) => idx !== i).join(', '))}
              className="text-white/40 hover:text-white/70"><X size={10} /></button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addTag()}
          placeholder={placeholder}
          className="flex-1 h-8 px-3 rounded-lg text-xs text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500" />
        <button onClick={addTag} className="px-2 h-8 rounded-lg text-xs font-semibold"
          style={{ background: 'rgba(139,92,246,0.20)', color: '#c4b5fd' }}>Add</button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Thumbnail Uploader — upload cover → color DNA → 3 abstract variants
// ─────────────────────────────────────────────────────────────────────────────
const VARIANT_LABELS = ['Gradient Wash', 'Geometric', 'Abstract Circles'];

function ThumbnailUploader({ docId, value, onChange, altText, onAltChange, adminToken }) {
  const [loading, setLoading]   = useState(false);
  const [original, setOriginal] = useState(null);
  const [variants, setVariants] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [selected, setSelected] = useState(null);
  const inputRef = useRef(null);

  const handleFile = async (file) => {
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/webp', 'image/jpg'].includes(file.type)) {
      toast.error('PNG, JPG or WebP only'); return;
    }
    if (file.size > 2 * 1024 * 1024) { toast.error('Max file size is 2 MB'); return; }
    if (!docId) { toast.error('Complete Step 1 first to create a document'); return; }
    setLoading(true);
    try {
      const form = new FormData();
      form.append('doc_id', docId);
      form.append('file', file);
      const { data } = await axios.post(`${API}/admin/thumbnail/generate-cms`, form, {
        ...authHeaders(adminToken),
        headers: { ...authHeaders(adminToken).headers, 'Content-Type': 'multipart/form-data' },
      });
      setOriginal(data.original_url);
      setVariants(data.variants);
      setAnalysis(data.analysis);
      setSelected(0);
      onChange(data.variants[0]);
      toast.success('Color DNA extracted — 3 abstract variants ready');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Cover analysis failed');
    } finally {
      setLoading(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const file = e.dataTransfer?.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <div className="space-y-3">
      {/* Upload zone — shown when no variants yet */}
      {!variants && (
        <div
          onDrop={handleDrop}
          onDragOver={e => e.preventDefault()}
          className="relative w-full rounded-xl border-2 border-dashed transition cursor-pointer"
          style={{ borderColor: loading ? 'rgba(139,92,246,0.50)' : 'rgba(255,255,255,0.10)' }}
          onClick={() => !loading && inputRef.current?.click()}
        >
          <input ref={inputRef} type="file" accept=".png,.jpg,.jpeg,.webp"
            className="hidden" onChange={e => handleFile(e.target.files?.[0])} />
          <div className="flex flex-col items-center justify-center py-6 gap-2">
            {loading
              ? <>
                  <Loader2 size={24} className="text-violet-400 animate-spin" />
                  <p className="text-xs text-violet-300 font-medium">Analyzing cover & extracting color DNA…</p>
                  <p className="text-[10px] text-white/30">Generating 3 abstract variants</p>
                </>
              : <>
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-1"
                    style={{ background: 'rgba(139,92,246,0.15)' }}>
                    <FileUp size={18} className="text-violet-400" />
                  </div>
                  <p className="text-sm font-semibold text-white/70">Upload a book cover</p>
                  <p className="text-[11px] text-white/35 text-center max-w-xs">
                    PNG, JPG, WebP — max 2 MB. The AI will extract its color DNA and generate 3 copyright-safe abstract variants.
                  </p>
                  {!docId && (
                    <p className="text-[10px] text-amber-400 mt-1">Complete Step 1 first to enable upload</p>
                  )}
                </>
            }
          </div>
        </div>
      )}

      {/* Results panel */}
      {variants && original && (
        <div>
          {/* Color DNA strip */}
          {analysis?.dominant_colors?.length > 0 && (
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <span className="text-[10px] font-bold uppercase tracking-wider text-white/30">Color DNA</span>
              {analysis.dominant_colors.slice(0, 5).map((c, i) => (
                <div key={i} title={c}
                  className="w-5 h-5 rounded-full border-2 border-white/10 flex-shrink-0"
                  style={{ background: c }} />
              ))}
              {analysis.style && (
                <span className="text-[10px] text-white/30 italic">
                  {analysis.style}{analysis.mood ? ` · ${analysis.mood}` : ''}
                </span>
              )}
            </div>
          )}

          {/* Original + 3 variants grid */}
          <div className="grid grid-cols-4 gap-2">
            {/* Original upload */}
            <div className="space-y-1.5">
              <p className="text-[10px] font-semibold text-white/30 text-center uppercase tracking-wider">Original</p>
              <div className="relative rounded-xl overflow-hidden border border-white/10"
                style={{ aspectRatio: '2/3', background: 'rgba(255,255,255,0.03)' }}>
                <img src={original} alt="original cover" className="w-full h-full object-cover" />
              </div>
            </div>

            {/* 3 AI variants */}
            {variants.map((v, i) => (
              <div key={i} className="space-y-1.5">
                <p className="text-[10px] font-semibold text-center uppercase tracking-wider"
                  style={{ color: selected === i ? '#a78bfa' : 'rgba(255,255,255,0.30)' }}>
                  {VARIANT_LABELS[i]}
                </p>
                <button
                  onClick={() => { setSelected(i); onChange(v); }}
                  className="relative w-full rounded-xl overflow-hidden border-2 transition"
                  style={{
                    borderColor: selected === i ? '#7c3aed' : 'rgba(255,255,255,0.08)',
                    aspectRatio: '2/3',
                    display: 'block',
                  }}
                >
                  <img src={v} alt={`variant ${i + 1}`} className="w-full h-full object-cover" />
                  {selected === i && (
                    <div className="absolute inset-0 flex items-center justify-center"
                      style={{ background: 'rgba(124,58,237,0.28)' }}>
                      <div className="w-7 h-7 rounded-full bg-violet-600 flex items-center justify-center shadow-lg">
                        <Check size={14} className="text-white" />
                      </div>
                    </div>
                  )}
                </button>
              </div>
            ))}
          </div>

          {/* Footer actions */}
          <div className="mt-2 flex items-center justify-between">
            <button
              onClick={() => { setVariants(null); setOriginal(null); setSelected(null); onChange(''); }}
              className="flex items-center gap-1.5 text-[11px] text-white/30 hover:text-white/60 transition"
            >
              <RefreshCw size={10} /> Upload different cover
            </button>
            {value && (
              <span className="flex items-center gap-1 text-[11px] text-emerald-400 font-semibold">
                <Check size={11} /> Variant {selected + 1} selected
              </span>
            )}
          </div>
        </div>
      )}

      {/* Alt text — always visible */}
      <div>
        <label className="text-xs font-semibold text-white/50 mb-1 block">Alt Text</label>
        <input
          className="w-full h-9 px-3 rounded-lg text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500 transition"
          placeholder="Descriptive alt text for accessibility and SEO"
          value={altText}
          onChange={e => onAltChange(e.target.value)}
        />
      </div>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────────────
// Step 4 — SEO & GEO Metadata
// ─────────────────────────────────────────────────────────────────────────────
function Step4SeoMeta({ state, set, goNext, goPrev, adminToken, autoRun }) {
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const autoRunFired4 = useRef(false);

  const metaLen = (state.metaDescription || '').length;
  const metaValid = metaLen >= 148 && metaLen <= 158;
  const metaColor = metaLen === 0 ? 'text-white/30' : metaValid ? 'text-emerald-400' : 'text-red-400';

  const requiredFilled = state.seoSlug && state.seoTitle && state.metaDescription && state.primaryKeyword && metaValid && state.seoTags && state.geoTags;

  const handleAutoFill = async () => {
    setGenerating(true);
    try {
      const payload = {
        title: state.workingTitle || state.seoTitle,
        content: (state.enrichedContent || state.draftContent).slice(0, 3000),
        primary_keyword: state.primaryKeyword,
        seo_tags: state.seoTags,
        linked_scope: [state.boardName, state.className, state.streamName, state.subjectName].filter(Boolean).join('/'),
        board: state.boardName || 'AHSEC',
        class_name: state.className,
        subject: state.subjectName,
      };
      const { data } = await axios.post(`${API}/admin/seo/generate`, payload, authHeaders(adminToken));
      set({
        seoTitle: data.seo_title || state.seoTitle,
        metaDescription: data.meta_description || state.metaDescription,
        primaryKeyword: data.primary_keyword || state.primaryKeyword,
        seoTags: data.seo_tags || state.seoTags,
        geoTags: Array.isArray(data.geo_phrases) ? data.geo_phrases.join('; ') : (state.geoTags || ''),
        seoSlug: state.seoSlug || autoSlug(data.seo_title || state.workingTitle || state.subjectName),
        schemaType: data.schema_type || state.schemaType,
      });
      toast.success('SEO & GEO metadata generated — review and edit below');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'AI SEO generation failed');
    } finally { setGenerating(false); }
  };

  const handleContinue = async () => {
    if (!requiredFilled || !state.docId) return;
    setSaving(true);
    setSaveError(false);
    try {
      await axios.patch(
        `${API}/admin/content/cms-documents/${state.docId}`,
        {
          title: state.seoTitle || state.workingTitle,
          seo_slug: state.seoSlug,
          meta_description: state.metaDescription,
          primary_keyword: state.primaryKeyword,
          seo_tags: state.seoTags,
          geo_tags: state.geoTags,
          schema_type: state.schemaType,
          thumbnail_url: state.thumbnailUrl,
          alt_text: state.altText,
          status: 'draft',
        },
        authHeaders(adminToken)
      );
      goNext();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to save metadata');
      setSaveError(true);
    } finally { setSaving(false); }
  };

  // Auto-trigger SEO generation when arriving from Content Editor handoff
  useEffect(() => {
    if (!autoRun || autoRunFired4.current || state.seoTitle || !state.enrichedContent) return;
    autoRunFired4.current = true;
    const t = setTimeout(() => handleAutoFill(), 400);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-continue to Step 5 once SEO fields are filled in autoRun mode
  const autoContFired4 = useRef(false);
  useEffect(() => {
    if (!autoRun || autoContFired4.current || !requiredFilled || !state.docId || generating || saving) return;
    autoContFired4.current = true;
    const t = setTimeout(() => handleContinue(), 800);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, requiredFilled, state.docId, generating, saving]);

  const inp = (err) => `w-full h-9 px-3 rounded-lg text-sm text-white bg-white/5 border outline-none focus:border-violet-500 transition ${err ? 'border-red-500/50' : 'border-white/10'}`;
  const lbl = 'text-xs font-semibold text-white/50 mb-1 block';

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-white">Step 4 — SEO & GEO Metadata</h2>
          <p className="text-xs text-white/40 mt-1">Fill all fields for maximum search and AI visibility.</p>
        </div>
        <button
          onClick={handleAutoFill}
          disabled={generating}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition flex-shrink-0"
          style={{ background: 'rgba(139,92,246,0.20)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.30)' }}
        >
          {generating ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
          {generating ? 'Generating…' : 'Auto-fill with AI'}
        </button>
      </div>

      <div className="space-y-4">
        {/* SEO Slug */}
        <div>
          <label className={lbl}>SEO Slug *</label>
          <input className={inp(!state.seoSlug && saving)}
            placeholder="my-topic-ahsec-class-12"
            value={state.seoSlug}
            onChange={e => set({ seoSlug: autoSlug(e.target.value) })} />
          {state.canonicalUrl && (
            <p className="text-[10px] text-white/30 mt-1">Canonical: {state.canonicalUrl}</p>
          )}
        </div>

        {/* SEO Title */}
        <div>
          <label className={lbl}>SEO Title * <span className="text-white/25 font-normal">({(state.seoTitle || '').length}/65 chars)</span></label>
          <input className={inp(!state.seoTitle && saving)}
            placeholder="Primary Keyword — Board Content Type | Syrabit"
            value={state.seoTitle}
            onChange={e => set({ seoTitle: e.target.value })} />
        </div>

        {/* Meta Description */}
        <div>
          <label className={lbl}>
            Meta Description * <span className={`font-semibold ml-1 ${metaColor}`}>{metaLen} chars {metaLen > 0 && `(target: 148–158)`}</span>
          </label>
          <textarea
            className={`w-full px-3 py-2 rounded-lg text-sm text-white bg-white/5 border outline-none focus:border-violet-500 transition resize-none ${!metaValid && metaLen > 0 ? 'border-red-500/50' : 'border-white/10'}`}
            rows={3}
            placeholder="Primary keyword opens. Notes, definitions, PYQ covered. Per AHSEC syllabus. Free on Syrabit."
            value={state.metaDescription}
            onChange={e => set({ metaDescription: e.target.value })}
          />
          <div className="h-1 rounded-full bg-white/5 mt-1.5 overflow-hidden">
            <div className="h-full rounded-full transition-all"
              style={{
                width: `${Math.min(100, (metaLen / 158) * 100)}%`,
                background: metaValid ? '#10b981' : metaLen > 158 ? '#ef4444' : '#f59e0b',
              }} />
          </div>
        </div>

        {/* Primary Keyword */}
        <div>
          <label className={lbl}>Primary Keyword *</label>
          <input className={inp(!state.primaryKeyword && saving)}
            placeholder="photosynthesis class 12 ahsec notes"
            value={state.primaryKeyword}
            onChange={e => set({ primaryKeyword: e.target.value })} />
        </div>

        {/* SEO Tags */}
        <div>
          <label className={lbl}>SEO Tags (comma-separated)</label>
          <TagChips value={state.seoTags} onChange={v => set({ seoTags: v })} placeholder="Add tag…" />
        </div>

        {/* GEO Tags / Authority Phrases */}
        <div>
          <label className={lbl}>GEO Tags / Authority Phrases</label>
          <TagChips value={state.geoTags} onChange={v => set({ geoTags: v })} placeholder="e.g. As per AHSEC 2024 syllabus…" />
        </div>

        {/* Schema Type */}
        <div>
          <label className={lbl}>Schema Type</label>
          <select className="w-full h-9 px-3 rounded-lg text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500 transition cursor-pointer"
            value={state.schemaType}
            onChange={e => set({ schemaType: e.target.value })}>
            {SCHEMA_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        {/* Thumbnail Cover Uploader */}
        <div>
          <label className={lbl}>Cover Thumbnail</label>
          <ThumbnailUploader
            docId={state.docId}
            value={state.thumbnailUrl}
            onChange={url => set({ thumbnailUrl: url })}
            altText={state.altText}
            onAltChange={alt => set({ altText: alt })}
            adminToken={adminToken}
          />
        </div>

        {/* Canonical URL (read-only) */}
        {state.canonicalUrl && (
          <div>
            <label className={lbl}>Canonical URL (from syllabus link)</label>
            <input className={inp(false)} value={state.canonicalUrl} readOnly
              style={{ opacity: 0.6, cursor: 'default' }} />
          </div>
        )}
      </div>

      <div className="mt-6 flex items-center justify-between">
        <button onClick={goPrev}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-white/50 hover:text-white/80 transition">
          <ChevronLeft size={14} /> Back
        </button>
        <button
          onClick={handleContinue}
          disabled={!requiredFilled || saving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
          style={{ background: requiredFilled ? '#7c3aed' : 'rgba(255,255,255,0.08)', color: requiredFilled ? 'white' : 'rgba(255,255,255,0.4)' }}
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : saveError ? <RefreshCw size={14} /> : <ChevronRight size={14} />}
          {saving ? 'Saving…' : saveError ? 'Retry Save' : 'Continue to Review'}
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 5 — Review & Publish
// ─────────────────────────────────────────────────────────────────────────────
function Step5ReviewPublish({ state, set, goPrev, adminToken, autoRun }) {
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [copied, setCopied] = useState(false);
  const autoRunFired5 = useRef(false);

  const wc = wordCount(state.enrichedContent || state.draftContent);
  const metaLen = (state.metaDescription || '').length;
  const metaValid = metaLen >= 148 && metaLen <= 158;

  const checks = [
    { label: 'Content ≥ 150 words', ok: wc >= 150, value: `${wc} words` },
    { label: 'SEO title filled', ok: !!state.seoTitle, value: state.seoTitle ? `${state.seoTitle.length} chars` : 'Missing' },
    { label: 'Meta description 148–158 chars', ok: metaValid, value: metaLen ? `${metaLen} chars` : 'Missing' },
    { label: 'Primary keyword set', ok: !!state.primaryKeyword, value: state.primaryKeyword || 'Missing' },
    { label: 'SEO slug set', ok: !!state.seoSlug, value: state.seoSlug || 'Missing' },
    { label: 'SEO tags added', ok: !!state.seoTags, value: state.seoTags || 'Missing' },
    { label: 'GEO tags added', ok: !!state.geoTags, value: state.geoTags || 'Missing' },
    { label: 'Scope linked', ok: !!state.subjectId, value: state.subjectName || state.subjectId || 'Not linked' },
  ];

  const allGreen = checks.every(c => c.ok);

  useEffect(() => {
    if (!autoRun || autoRunFired5.current || publishing) return;
    if (!allGreen || !state.docId) return;
    autoRunFired5.current = true;
    const t = setTimeout(() => handlePublishToggle(), 800);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, allGreen, state.docId, publishing]);

  const handleSaveDraft = async () => {
    if (!state.docId) return;
    setSaving(true);
    try {
      await axios.patch(
        `${API}/admin/content/cms-documents/${state.docId}`,
        { status: 'draft' },
        authHeaders(adminToken)
      );
      set({ publishedStatus: 'draft' });
      toast.success('Saved as draft');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Save failed');
    } finally { setSaving(false); }
  };

  const handlePublishToggle = async () => {
    if (!state.docId) return;
    setPublishing(true);
    try {
      const res = await axios.post(`${API}/admin/content/cms-documents/${state.docId}/publish`, {}, authHeaders(adminToken));
      const newStatus = res.data.status;
      set({ publishedStatus: newStatus });
      toast.success(newStatus === 'published' ? 'Published! 🎉' : 'Moved back to draft');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Publish toggle failed');
    } finally { setPublishing(false); }
  };

  const liveUrl = state.canonicalUrl || (state.seoSlug ? `/learn/${state.seoSlug}` : '');

  const copyUrl = () => {
    if (!liveUrl) return;
    navigator.clipboard.writeText(`https://syrabit.ai${liveUrl}`).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-5">
        <h2 className="text-base font-bold text-white">Step 5 — Review & Publish</h2>
        <p className="text-xs text-white/40 mt-1">Check all fields, then publish or save as draft.</p>
      </div>

      {/* Summary Card */}
      <div className="rounded-xl border p-4 mb-5" style={{ background: 'rgba(255,255,255,0.025)', borderColor: 'rgba(255,255,255,0.08)' }}>
        <p className="text-xs font-bold text-white/50 uppercase tracking-wider mb-3">Document Summary</p>
        <div className="space-y-2">
          {[
            ['Scope', [state.boardName, state.className, state.streamName, state.subjectName].filter(Boolean).join(' → ')],
            ['Title', state.seoTitle || state.workingTitle],
            ['Slug', state.seoSlug],
            ['Meta Description', state.metaDescription],
            ['Primary Keyword', state.primaryKeyword],
            ['SEO Tags', state.seoTags],
            ['GEO Tags', state.geoTags],
            ['Schema', state.schemaType],
            ['Word Count', `${wc} words`],
            ['Status', state.publishedStatus],
          ].map(([k, v]) => (
            <div key={k} className="flex gap-2 text-xs">
              <span className="text-white/35 flex-shrink-0 w-28">{k}</span>
              <span className="text-white/65 min-w-0 break-words">{v || '—'}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Checklist */}
      <div className="rounded-xl border p-4 mb-5" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.07)' }}>
        <p className="text-xs font-bold text-white/50 uppercase tracking-wider mb-3">Completeness Checklist</p>
        <div className="space-y-2">
          {checks.map(({ label, ok, value }) => (
            <div key={label} className="flex items-center gap-3 text-xs">
              {ok
                ? <CheckCircle2 size={14} className="text-emerald-400 flex-shrink-0" />
                : <AlertCircle size={14} className="text-amber-400 flex-shrink-0" />}
              <span className={ok ? 'text-white/60' : 'text-amber-300/70'}>{label}</span>
              <span className="ml-auto text-white/30 truncate max-w-[120px]">{value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Published success banner */}
      {state.publishedStatus === 'published' && (
        <div className="rounded-xl border p-4 mb-5" style={{ background: 'rgba(16,185,129,0.08)', borderColor: 'rgba(16,185,129,0.25)' }}>
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 size={16} className="text-emerald-400" />
            <span className="text-sm font-bold text-emerald-400">Published & Live!</span>
          </div>
          {liveUrl && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-white/50 truncate flex-1">https://syrabit.ai{liveUrl}</span>
              <button onClick={copyUrl}
                className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold transition flex-shrink-0"
                style={{ background: 'rgba(16,185,129,0.18)', color: '#34d399' }}>
                {copied ? <Check size={11} /> : <Copy size={11} />}
                {copied ? 'Copied!' : 'Copy'}
              </button>
              <a href={liveUrl} target="_blank" rel="noreferrer"
                className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold flex-shrink-0"
                style={{ background: 'rgba(16,185,129,0.10)', color: '#34d399' }}>
                <ExternalLink size={11} /> View
              </a>
            </div>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center justify-between gap-3">
        <button onClick={goPrev}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-white/50 hover:text-white/80 transition">
          <ChevronLeft size={14} /> Back
        </button>
        <div className="flex gap-2">
          <button
            onClick={handleSaveDraft}
            disabled={saving || publishing}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
            style={{ background: 'rgba(255,255,255,0.07)', color: 'rgba(255,255,255,0.70)', border: '1px solid rgba(255,255,255,0.10)' }}
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Lock size={14} />}
            {saving ? 'Saving…' : 'Save Draft'}
          </button>
          <button
            onClick={handlePublishToggle}
            disabled={(state.publishedStatus !== 'published' && !allGreen) || publishing || saving}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
            style={{
              background: state.publishedStatus === 'published'
                ? 'rgba(239,68,68,0.18)'
                : (allGreen ? '#10b981' : 'rgba(255,255,255,0.08)'),
              color: state.publishedStatus === 'published'
                ? '#f87171'
                : (allGreen ? 'white' : 'rgba(255,255,255,0.4)'),
            }}
          >
            {publishing ? <Loader2 size={14} className="animate-spin" /> : <Globe size={14} />}
            {publishing ? (state.publishedStatus === 'published' ? 'Unpublishing…' : 'Publishing…') : state.publishedStatus === 'published' ? 'Unpublish' : 'Publish Now'}
          </button>
        </div>
      </div>

      {!allGreen && state.publishedStatus !== 'published' && (
        <p className="text-xs text-amber-400/70 mt-3 text-right">Fix checklist items above to enable "Publish Now"</p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// My Documents Drawer
// ─────────────────────────────────────────────────────────────────────────────
function DocsDrawer({ docs, loading, onClose, onLoad, adminToken, onRefresh }) {
  const [search, setSearch] = useState('');
  const [deleting, setDeleting] = useState(null);

  const filtered = search
    ? docs.filter(d => d.title?.toLowerCase().includes(search.toLowerCase()) || d.seo_slug?.toLowerCase().includes(search.toLowerCase()))
    : docs;

  const handleDelete = async (doc, e) => {
    e.stopPropagation();
    if (!confirm(`Delete "${doc.title}"?`)) return;
    setDeleting(doc.id);
    try {
      await axios.delete(`${API}/admin/content/cms-documents/${doc.id}`, authHeaders(adminToken));
      toast.success('Deleted');
      onRefresh();
    } catch { toast.error('Delete failed'); }
    finally { setDeleting(null); }
  };

  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      <div
        className="relative ml-auto w-full max-w-sm h-full flex flex-col"
        style={{ background: '#0f0f1e', borderLeft: '1px solid rgba(255,255,255,0.08)' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <h3 className="text-sm font-bold text-white">My Documents</h3>
          <div className="flex items-center gap-2">
            <button onClick={onRefresh} className="text-white/40 hover:text-white/70 transition"><RefreshCw size={13} /></button>
            <button onClick={onClose} className="text-white/40 hover:text-white/70 transition"><X size={16} /></button>
          </div>
        </div>

        <div className="px-3 py-2 border-b flex-shrink-0" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <input
            value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search documents…"
            className="w-full h-8 px-3 rounded-lg text-sm text-white bg-white/5 border border-white/10 outline-none focus:border-violet-500"
          />
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading && (
            <div className="flex items-center justify-center py-8 gap-2 text-white/30 text-sm">
              <Loader2 size={16} className="animate-spin" /> Loading…
            </div>
          )}
          {!loading && filtered.length === 0 && (
            <p className="text-center py-8 text-white/30 text-sm">No documents found</p>
          )}
          {filtered.map(doc => (
            <div key={doc.id}
              onClick={() => onLoad(doc)}
              className="rounded-xl p-3 cursor-pointer border transition group hover:border-violet-500/30"
              style={{ background: 'rgba(255,255,255,0.025)', borderColor: 'rgba(255,255,255,0.07)' }}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-white/80 truncate">{doc.title || 'Untitled'}</p>
                  <p className="text-[10px] text-white/35 truncate mt-0.5">{doc.seo_slug || doc.id}</p>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${
                    doc.status === 'published' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-white/8 text-white/30'}`}>
                    {doc.status}
                  </span>
                  <button
                    onClick={e => handleDelete(doc, e)}
                    disabled={deleting === doc.id}
                    className="opacity-0 group-hover:opacity-100 transition text-red-400/50 hover:text-red-400"
                  >
                    {deleting === doc.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                  </button>
                </div>
              </div>
              {doc.word_count && (
                <p className="text-[10px] text-white/25 mt-1">{doc.word_count} words · {doc.schema_type}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
