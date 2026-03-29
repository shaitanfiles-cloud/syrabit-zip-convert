/**
 * AdminContentHub — Centralized content workflow
 * Tabs: Syllabus → Content Editor → AI Studio → CMS
 * Shared context: onNavigate(tab) lets any tab deep-link into another.
 */
import { useState, useEffect } from 'react';
import { FolderTree, PenTool, Sparkles, FileText, ArrowRight, Loader2, BookMarked } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';

import AdminSyllabusManager  from './AdminSyllabusManager';
import AdminContentEditor    from './AdminContentEditor';
import AdminCmsDocEditor     from './AdminCmsDocEditor';
import AdminContentStudio    from './AdminContentStudio';
import AdminPYQManager       from './AdminPYQManager';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

const TABS = [
  { id: 'syllabus', label: 'Syllabus',        icon: FolderTree,  color: 'indigo',  desc: 'Manage board/class/stream hierarchy & import PDFs' },
  { id: 'pyq',      label: 'PYQ',             icon: BookMarked,  color: 'amber',   desc: 'Upload & manage previous year question papers' },
  { id: 'editor',   label: 'Content Editor',  icon: PenTool,     color: 'violet',  desc: 'Write & edit chapter-level markdown content' },
  { id: 'studio',   label: 'AI Studio',       icon: Sparkles,    color: 'rose',    desc: 'Generate structured content blocks with AI' },
  { id: 'cms',      label: 'CMS / Docs',      icon: FileText,    color: 'emerald', desc: 'Manage published pages, SEO docs & blog posts' },
];

const FLOW = [
  { label: 'Syllabus',  sub: 'Import structure', tab: 'syllabus', arrow: true },
  { label: 'Editor',    sub: 'Write content',    tab: 'editor',   arrow: true },
  { label: 'AI Studio', sub: 'Generate & enrich', tab: 'studio',  arrow: true },
  { label: 'CMS',       sub: 'Publish & ship',   tab: 'cms',      arrow: false },
];

const COLOR_MAP = {
  indigo:  { active: 'border-indigo-500 text-indigo-400',  dot: 'bg-indigo-500', badge: 'bg-indigo-500/20 text-indigo-300' },
  violet:  { active: 'border-violet-500 text-violet-400',  dot: 'bg-violet-500', badge: 'bg-violet-500/20 text-violet-300' },
  amber:   { active: 'border-amber-500 text-amber-400',    dot: 'bg-amber-500',  badge: 'bg-amber-500/20 text-amber-300'  },
  emerald: { active: 'border-emerald-500 text-emerald-400',dot: 'bg-emerald-500',badge: 'bg-emerald-500/20 text-emerald-300'},
  rose:    { active: 'border-rose-500 text-rose-400',      dot: 'bg-rose-500',   badge: 'bg-rose-500/20 text-rose-300'    },
};

export default function AdminContentHub({ adminToken }) {
  const [activeTab, setActiveTab]   = useState('syllabus');
  const [boards, setBoards]         = useState([]);
  const [classes, setClasses]       = useState([]);
  const [streams, setStreams]       = useState([]);
  const [subjects, setSubjects]     = useState([]);
  const [loading, setLoading]       = useState(true);

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
      <div className="border-b px-6 py-2 flex items-center gap-1 flex-wrap"
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
              <span>{step.label}</span>
            </button>
            {step.arrow && <ArrowRight size={10} className="text-white/15 flex-shrink-0" />}
          </span>
        ))}
        <span className="ml-auto text-[10px] text-white/20">{boards.length} boards · {subjects.length} subjects</span>
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
              <SyllabusTabHeader onNavigate={setActiveTab} />
              <AdminSyllabusManager
                adminToken={adminToken}
                boards={boards}
                classes={classes}
                streams={streams}
                subjects={subjects}
              />
            </div>
          </div>
        )}

        {activeTab === 'pyq' && (
          <div className="h-full overflow-y-auto">
            <div className="p-6 max-w-4xl mx-auto w-full">
              <div className="flex items-center justify-between mb-5">
                <div>
                  <h2 className="text-base font-bold text-white">PYQ Manager</h2>
                  <p className="text-xs text-white/35 mt-0.5">
                    Upload previous year question papers — images or PDFs, linked to subjects
                  </p>
                </div>
              </div>
              <AdminPYQManager adminToken={adminToken} />
            </div>
          </div>
        )}

        {activeTab === 'editor' && (
          <div className="h-full overflow-hidden">
            <AdminContentEditor
              adminToken={adminToken}
              onNavigate={setActiveTab}
            />
          </div>
        )}

        {activeTab === 'studio' && (
          <div className="h-full overflow-y-auto">
            <AdminContentStudio
              adminToken={adminToken}
              onNavigate={setActiveTab}
            />
          </div>
        )}

        {activeTab === 'cms' && (
          <div className="h-full overflow-hidden">
            <AdminCmsDocEditor
              adminToken={adminToken}
              onNavigate={setActiveTab}
            />
          </div>
        )}
      </div>
    </div>
  );
}

/* Cross-tab navigation hint shown at top of Syllabus tab */
function SyllabusTabHeader({ onNavigate }) {
  return (
    <div className="flex items-center justify-between mb-5">
      <div>
        <h2 className="text-base font-bold text-white">Syllabus Manager</h2>
        <p className="text-xs text-white/35 mt-0.5">
          Import PDFs, manage board → class → stream → subject hierarchy
        </p>
      </div>
      <button
        onClick={() => onNavigate('editor')}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition"
        style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd' }}
      >
        Write content <ArrowRight size={12} />
      </button>
    </div>
  );
}
