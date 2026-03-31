import { useState, useEffect, useRef } from 'react';
import { ChevronRight, Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { API, authHeaders, autoSlug } from '@/utils/adminHelpers';

const CONTENT_TYPES = ['Article', 'FAQPage', 'StudyNotes'];

export default function Step1TargetScope({ state, set, goNext, boards, classes, streams, subjects, hierarchyLoading, adminToken, autoRun }) {
  const [saving, setSaving] = useState(false);
  const [linkingScope, setLinkingScope] = useState(false);
  const [linkError, setLinkError] = useState(false);
  const autoRunFired1 = useRef(false);

  const filteredClasses = state.boardId ? classes.filter(c => c.board_id === state.boardId) : [];
  const filteredStreams = state.classId ? streams.filter(s => s.class_id === state.classId) : [];
  const classStreamIds = filteredStreams.map(s => s.id);
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
      let docId = state.docId;
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

        <div>
          <label className={lbl}>Working Title</label>
          <input className={inp} placeholder="e.g. Photosynthesis — Complete Notes AHSEC 2024"
            value={state.workingTitle}
            onChange={e => set({ workingTitle: e.target.value })} />
        </div>

        <div>
          <label className={lbl}>Primary Keyword *</label>
          <input className={inp} placeholder="e.g. photosynthesis class 12 ahsec"
            value={state.primaryKeyword}
            onChange={e => set({ primaryKeyword: e.target.value })} />
          <p className="text-[10px] text-white/25 mt-1">4–7 words. This is the core search query you're targeting.</p>
        </div>

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
