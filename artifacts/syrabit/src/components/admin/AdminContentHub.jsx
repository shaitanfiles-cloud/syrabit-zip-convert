/**
 * AdminContentHub — Centralized content workflow
 * Tabs: Syllabus → PYQ → Content Editor → AI Studio → CMS/Docs
 *
 * Shared hubContext propagates Board/Class/Stream/Subject selection across
 * all five tabs so the user never has to re-pick the same hierarchy.
 *
 * Cross-tab wiring:
 *   Syllabus  →  Editor  : hubContext + onNavigate('editor')
 *   Syllabus  →  PYQ     : hubContext + onNavigate('pyq')
 *   Syllabus  →  Studio  : hubContext + onNavigate('studio')
 *   PYQ       →  Editor  : hubContext + onNavigate('editor')
 *   Editor    →  Studio  : localStorage(syrabit_studio_prefill) + onNavigate('studio')
 *   Editor    →  CMS     : localStorage(syrabit_cms_prefill)    + onNavigate('cms')   [existing]
 *   Studio    →  CMS     : localStorage(syrabit_cms_prefill)    + onNavigate('cms')   [existing]
 *   CMS       →  Editor  : localStorage(syrabit_content_prefill)+ onNavigate('editor')[existing]
 */
import { useState, useEffect, useCallback } from 'react';
import {
  FolderTree, PenTool, Sparkles, FileText, ArrowRight,
  Loader2, BookMarked, ChevronDown, Globe, Zap,
} from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';

import AdminSyllabusManager  from './AdminSyllabusManager';
import AdminContentEditor    from './AdminContentEditor';
import AdminCmsDocEditor     from './AdminCmsDocEditor';
import AdminContentStudio    from './AdminContentStudio';
import AdminPYQManager       from './AdminPYQManager';
import BlogPublishWizard     from './BlogPublishWizard';
import PipelineProgressPanel from './PipelineProgressPanel';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

const TABS = [
  { id: 'syllabus', label: 'Syllabus',        icon: FolderTree,  color: 'indigo',  desc: 'Manage board/class/stream hierarchy & import PDFs' },
  { id: 'pyq',      label: 'PYQ',             icon: BookMarked,  color: 'amber',   desc: 'Upload & manage previous year question papers' },
  { id: 'editor',   label: 'Content Editor',  icon: PenTool,     color: 'violet',  desc: 'Write & edit chapter-level markdown content' },
  { id: 'studio',   label: 'AI Studio',       icon: Sparkles,    color: 'rose',    desc: 'Generate structured content blocks with AI' },
  { id: 'cms',      label: 'CMS / Docs',      icon: FileText,    color: 'emerald', desc: 'Manage published pages, SEO docs & blog posts' },
  { id: 'blog',     label: 'Blog Publisher',  icon: Globe,       color: 'sky',     desc: 'SEO & GEO-rich 5-step blog publish wizard' },
];

const FLOW = [
  { label: 'Syllabus',      sub: 'Import structure',   tab: 'syllabus', arrow: true  },
  { label: 'PYQ',           sub: 'Upload questions',   tab: 'pyq',      arrow: true  },
  { label: 'Editor',        sub: 'Write content',      tab: 'editor',   arrow: true  },
  { label: 'AI Studio',     sub: 'Generate & enrich',  tab: 'studio',   arrow: true  },
  { label: 'Blog Publisher', sub: 'SEO & publish',     tab: 'blog',     arrow: false },
];

const COLOR_MAP = {
  indigo:  { active: 'border-indigo-500 text-indigo-400',  dot: 'bg-indigo-500', badge: 'bg-indigo-500/20 text-indigo-300' },
  violet:  { active: 'border-violet-500 text-violet-400',  dot: 'bg-violet-500', badge: 'bg-violet-500/20 text-violet-300' },
  amber:   { active: 'border-amber-500 text-amber-400',    dot: 'bg-amber-500',  badge: 'bg-amber-500/20 text-amber-300'  },
  emerald: { active: 'border-emerald-500 text-emerald-400',dot: 'bg-emerald-500',badge: 'bg-emerald-500/20 text-emerald-300'},
  rose:    { active: 'border-rose-500 text-rose-400',      dot: 'bg-rose-500',   badge: 'bg-rose-500/20 text-rose-300'    },
  sky:     { active: 'border-sky-500 text-sky-400',        dot: 'bg-sky-500',    badge: 'bg-sky-500/20 text-sky-300'      },
};

const EMPTY_CTX = {
  boardId: '', boardName: '',
  classId: '', className: '',
  streamId: '', streamName: '',
  subjectId: '', subjectName: '',
};

const HUB_CTX_KEY = 'syrabit_hub_ctx';

function loadPersistedCtx() {
  try {
    const raw = localStorage.getItem(HUB_CTX_KEY);
    if (!raw) return EMPTY_CTX;
    const parsed = JSON.parse(raw);
    if (Date.now() - (parsed._ts || 0) > 2 * 60 * 60 * 1000) {
      localStorage.removeItem(HUB_CTX_KEY);
      return EMPTY_CTX;
    }
    const { _ts, ...ctx } = parsed;
    return ctx;
  } catch { return EMPTY_CTX; }
}

const INTERNAL_TABS = new Set(['editor', 'syllabus', 'studio', 'pyq', 'cms', 'blog']);

export default function AdminContentHub({ adminToken, onNavigate: topNavigate }) {
  const [activeTab, setActiveTab] = useState('syllabus');
  const [boards, setBoards]       = useState([]);
  const [classes, setClasses]     = useState([]);
  const [streams, setStreams]     = useState([]);
  const [subjects, setSubjects]   = useState([]);
  const [loading, setLoading]     = useState(true);

  const [hubContext, setHubContextRaw] = useState(loadPersistedCtx);
  const [showPipeline, setShowPipeline] = useState(false);

  const setHubContext = useCallback((ctxOrFn) => {
    setHubContextRaw(prev => {
      const next = typeof ctxOrFn === 'function'
        ? { ...EMPTY_CTX, ...prev, ...ctxOrFn(prev) }
        : { ...EMPTY_CTX, ...prev, ...ctxOrFn };
      try { localStorage.setItem(HUB_CTX_KEY, JSON.stringify({ ...next, _ts: Date.now() })); } catch {}
      return next;
    });
  }, []);

  const navigate = useCallback((tab, ctxPatch) => {
    if (ctxPatch) setHubContext(ctxPatch);
    if (INTERNAL_TABS.has(tab)) {
      setActiveTab(tab);
    } else if (topNavigate) {
      topNavigate(tab);
    }
  }, [setHubContext, topNavigate]);

  useEffect(() => {
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
      .finally(() => setLoading(false));
  }, []);

  const activeColor = COLOR_MAP[TABS.find(t => t.id === activeTab)?.color || 'violet'];

  return (
    <div className="h-full flex flex-col" style={{ background: '#06060e' }}>

      {/* ── Delegated workflow banner ─────────────────────────────────── */}
      <div className="border-b px-4 py-1.5 flex items-center gap-1 flex-wrap"
        style={{ background: 'rgba(255,255,255,0.015)', borderColor: 'rgba(255,255,255,0.07)' }}>
        <span className="text-[10px] font-semibold text-white/25 uppercase tracking-widest mr-2">Workflow</span>
        {FLOW.map((step, i) => (
          <span key={i} className="flex items-center gap-1">
            <button
              onClick={() => setActiveTab(step.tab)}
              className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold transition-all ${
                activeTab === step.tab
                  ? COLOR_MAP[TABS.find(t => t.id === step.tab)?.color]?.badge
                  : 'text-white/30 hover:text-white/60'
              }`}
            >
              {step.label}
            </button>
            {step.arrow && <ArrowRight size={10} className="text-white/15 flex-shrink-0" />}
          </span>
        ))}

        {/* Hub context pill — shows currently active subject */}
        {hubContext.subjectName && (
          <span className="ml-auto flex items-center gap-1.5 flex-wrap">
            <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px]"
              style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd' }}>
              <span className="text-white/25">subject:</span>
              <span className="font-semibold truncate max-w-[120px]">{hubContext.subjectName}</span>
              <button
                onClick={() => setHubContext(EMPTY_CTX)}
                className="text-white/30 hover:text-white/70 ml-0.5"
                title="Clear context"
              >×</button>
            </span>
            <button
              onClick={() => setShowPipeline(true)}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-bold transition hover:opacity-90"
              style={{ background: 'linear-gradient(135deg,#7c3aed,#5b21b6)', color: '#fff' }}
              title="Auto-Generate Full Subject — 1 click generates all content, MCQs, blogs & PYQ pages"
            >
              <Zap size={11} /> Auto-Generate Full Subject
            </button>
          </span>
        )}
        {!hubContext.subjectName && (
          <span className="ml-auto text-[10px] text-white/20">{boards.length} boards · {subjects.length} subjects</span>
        )}
      </div>

      {/* ── Tab bar ──────────────────────────────────────────────────── */}
      <div className="border-b flex-shrink-0" style={{ borderColor: 'rgba(255,255,255,0.07)', background: 'rgba(255,255,255,0.02)' }}>
        <div className="flex px-4 gap-1 h-12 items-end">
          {TABS.map(tab => {
            const colors = COLOR_MAP[tab.color];
            const isActive = activeTab === tab.id;
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 h-10 px-4 rounded-t-lg border-b-2 transition-all text-sm font-medium ${
                  isActive
                    ? `${colors.active} bg-white/[0.04]`
                    : 'border-transparent text-white/40 hover:text-white/70 hover:bg-white/[0.02]'
                }`}
              >
                <Icon size={14} />
                <span className="hidden sm:inline">{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Tab content ──────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-[#06060e]/80 z-10">
            <div className="flex items-center gap-2 text-white/40 text-sm">
              <Loader2 size={16} className="animate-spin" /> Loading content data…
            </div>
          </div>
        )}

        {activeTab === 'syllabus' && (
          <div className="h-full overflow-y-auto">
            <div className="p-6 max-w-4xl mx-auto w-full">
              <SyllabusTabHeader onNavigate={navigate} hubContext={hubContext} />
              <AdminSyllabusManager
                adminToken={adminToken}
                boards={boards}
                classes={classes}
                streams={streams}
                subjects={subjects}
                onNavigate={navigate}
                onHubContext={setHubContext}
              />
            </div>
          </div>
        )}

        {activeTab === 'pyq' && (
          <div className="h-full overflow-y-auto">
            <div className="p-6 max-w-4xl mx-auto w-full">
              <PYQTabHeader onNavigate={navigate} hubContext={hubContext} />
              <AdminPYQManager
                adminToken={adminToken}
                hubContext={hubContext}
                onNavigate={navigate}
              />
            </div>
          </div>
        )}

        {activeTab === 'editor' && (
          <div className="h-full overflow-hidden">
            <AdminContentEditor
              adminToken={adminToken}
              onNavigate={navigate}
              hubContext={hubContext}
              onHubContext={setHubContext}
            />
          </div>
        )}

        {activeTab === 'studio' && (
          <div className="h-full overflow-y-auto">
            <AdminContentStudio
              adminToken={adminToken}
              onNavigate={navigate}
              hubContext={hubContext}
              onHubContext={setHubContext}
            />
          </div>
        )}

        {activeTab === 'cms' && (
          <div className="h-full overflow-hidden">
            <AdminCmsDocEditor
              adminToken={adminToken}
              onNavigate={navigate}
              hubContext={hubContext}
            />
          </div>
        )}

        {activeTab === 'blog' && (
          <div className="h-full overflow-y-auto">
            <BlogPublishWizard
              adminToken={adminToken}
              onNavigate={navigate}
              hubContext={hubContext}
              onHubContext={setHubContext}
            />
          </div>
        )}
      </div>

      {/* ── Pipeline Progress Panel ───────────────────────────────────── */}
      {showPipeline && (
        <PipelineProgressPanel
          adminToken={adminToken}
          subjectId={hubContext.subjectId}
          subjectName={hubContext.subjectName}
          onClose={() => setShowPipeline(false)}
          onComplete={(summary) => {
            toast.success(`${summary.total_blogs} blogs published for "${hubContext.subjectName}"`);
          }}
        />
      )}
    </div>
  );
}

/* ── Tab header components ─────────────────────────────────────────── */

function SyllabusTabHeader({ onNavigate, hubContext }) {
  return (
    <div className="flex items-center justify-between mb-5 flex-wrap gap-2">
      <div>
        <h2 className="text-base font-bold text-white">Syllabus Manager</h2>
        <p className="text-xs text-white/35 mt-0.5">
          Import PDFs, manage board → class → stream → subject hierarchy
        </p>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        {hubContext?.subjectName && (
          <>
            <QuickActionBtn
              label="Write Content"
              color="#8b5cf6"
              onClick={() => onNavigate('editor')}
            />
            <QuickActionBtn
              label="Upload PYQ"
              color="#f59e0b"
              onClick={() => onNavigate('pyq')}
            />
            <QuickActionBtn
              label="Generate AI"
              color="#f43f5e"
              onClick={() => onNavigate('studio')}
            />
          </>
        )}
        {!hubContext?.subjectName && (
          <button
            onClick={() => onNavigate('editor')}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition"
            style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd' }}
          >
            Write content <ArrowRight size={12} />
          </button>
        )}
      </div>
    </div>
  );
}

function PYQTabHeader({ onNavigate, hubContext }) {
  return (
    <div className="flex items-center justify-between mb-5 flex-wrap gap-2">
      <div>
        <h2 className="text-base font-bold text-white">PYQ Manager</h2>
        <p className="text-xs text-white/35 mt-0.5">
          Upload previous year question papers — images or PDFs, linked to subjects
          {hubContext?.subjectName && (
            <span className="ml-2 px-1.5 py-0.5 rounded-full text-[10px] font-semibold"
              style={{ background: 'rgba(245,158,11,0.18)', color: '#fcd34d' }}>
              {hubContext.subjectName}
            </span>
          )}
        </p>
      </div>
      {hubContext?.subjectName && (
        <QuickActionBtn
          label="Write Content"
          color="#8b5cf6"
          onClick={() => onNavigate('editor')}
        />
      )}
    </div>
  );
}

function QuickActionBtn({ label, color, onClick }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition hover:opacity-90"
      style={{ background: `${color}22`, color, border: `1px solid ${color}44` }}
    >
      {label} <ArrowRight size={11} />
    </button>
  );
}
