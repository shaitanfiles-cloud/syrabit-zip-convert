import { useReducer, useEffect, useRef, useCallback, useState } from 'react';
import {
  ChevronRight, Check, Sparkles, Globe, RefreshCw, FileText, X,
  Target, Edit3, Zap, BarChart3,
} from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { API, authHeaders } from '@/utils/adminHelpers';
import Step1TargetScope from './blog-wizard/Step1TargetScope';
import Step2DraftContent from './blog-wizard/Step2DraftContent';
import Step3AiEnrichment from './blog-wizard/Step3AiEnrichment';
import Step4SeoMeta from './blog-wizard/Step4SeoMeta';
import Step5ReviewPublish from './blog-wizard/Step5ReviewPublish';
import DocsDrawer from './blog-wizard/DocsDrawer';

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

const INITIAL_STATE = {
  step: 1,
  unlocked: [1],
  docId: null,
  canonicalUrl: '',
  boardId: '', boardName: '',
  classId: '', className: '',
  streamId: '', streamName: '',
  subjectId: '', subjectName: '',
  workingTitle: '',
  primaryKeyword: '',
  contentType: 'Article',
  draftContent: '',
  enrichedBlocks: null,
  enrichedContent: '',
  enrichmentAccepted: false,
  seoSlug: '',
  seoTitle: '',
  metaDescription: '',
  seoTags: '',
  geoTags: '',
  schemaType: 'Article',
  thumbnailUrl: '',
  altText: '',
  publishedStatus: 'draft',
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

const STEPS = [
  { id: 1, label: 'Target & Scope',   icon: Target },
  { id: 2, label: 'Draft Content',    icon: Edit3  },
  { id: 3, label: 'AI Enrichment',    icon: Sparkles },
  { id: 4, label: 'SEO & GEO Meta',  icon: BarChart3 },
  { id: 5, label: 'Review & Publish', icon: Globe  },
];

export default function BlogPublishWizard({ adminToken, hubContext, onHubContext }) {
  const [state, dispatch] = useReducer(reducer, null, () => {
    const saved = loadState();
    return saved ? { ...INITIAL_STATE, ...saved } : INITIAL_STATE;
  });

  const [boards, setBoards] = useState([]);
  const [classes, setClasses] = useState([]);
  const [streams, setStreams] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [hierarchyLoading, setHierarchyLoading] = useState(true);

  const [docsOpen, setDocsOpen] = useState(false);
  const [docs, setDocs] = useState([]);
  const [docsLoading, setDocsLoading] = useState(false);

  const autoFlowRef = useRef(false);
  const [autoFlow, setAutoFlow] = useState(false);

  useEffect(() => { saveState(state); }, [state]);

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
        docId:          pf.docId          || null,
        seoSlug:        pf.seoSlug        || '',
        step:     1,
        unlocked: [1],
        enrichedBlocks: null,
        enrichedContent: '',
        enrichmentAccepted: false,
        seoTitle: '', metaDescription: '',
        seoTags: '', geoTags: '',
        publishedStatus: 'draft',
      }});
      toast.success('Content Editor handoff — scope & draft pre-filled!');
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!state.subjectId || state.boardId) return;
    if (!subjects.length || !streams.length) return;
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

  useEffect(() => {
    if (!hubContext?.subjectId) return;
    if (state.subjectId) return;
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
