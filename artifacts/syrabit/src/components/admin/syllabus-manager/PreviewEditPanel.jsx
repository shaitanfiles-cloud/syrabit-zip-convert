import { useState } from 'react';
import { Trash2, Plus, Loader2, CheckCircle } from 'lucide-react';

export default function PreviewEditPanel({
  previewData, expandedIdx, setExpandedIdx,
  onUpdateSubject, onRemoveSubject, onAddChapter, onRemoveChapter,
  onConfirm, onDiscard, confirmLoading,
}) {
  const [newChapterText, setNewChapterText] = useState({});

  const inputCls = "w-full bg-white/5 border border-white/10 rounded px-2 py-1 text-xs text-white placeholder-white/25 focus:outline-none focus:border-violet-400/50";
  const btnSm    = "px-2 py-0.5 rounded text-[10px] font-semibold transition";

  return (
    <div className="rounded-xl border space-y-3" style={{ background: 'rgba(139,92,246,0.04)', borderColor: 'rgba(139,92,246,0.22)' }}>
      <div className="flex items-center justify-between p-3 border-b" style={{ borderColor: 'rgba(139,92,246,0.15)' }}>
        <div>
          <p className="text-[11px] font-semibold text-violet-300">
            Review extracted syllabus — {previewData.subjects_count} subject{previewData.subjects_count !== 1 ? 's' : ''} from &ldquo;{previewData.filename}&rdquo;
          </p>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            {previewData.new_count > 0 && (
              <span className="text-[9px] px-1.5 py-0.5 rounded font-semibold"
                style={{ background: 'rgba(52,211,153,0.15)', color: '#34d399' }}>
                ✓ {previewData.new_count} new
              </span>
            )}
            {previewData.duplicate_count > 0 && (
              <span className="text-[9px] px-1.5 py-0.5 rounded font-semibold"
                style={{ background: 'rgba(251,191,36,0.15)', color: '#fbbf24' }}>
                ⟳ {previewData.duplicate_count} already active — will be skipped
              </span>
            )}
            <p className="text-[10px] text-white/35">Edit or remove subjects before saving.</p>
          </div>
        </div>
        <button onClick={onDiscard} className="text-white/30 hover:text-white/70 transition text-[10px] ml-3">discard</button>
      </div>

      <div className="px-3 space-y-2">
        {previewData.extracted.map((sub, idx) => {
          const isOpen = expandedIdx === idx;
          return (
            <div key={idx} className="rounded-lg border overflow-hidden" style={{ borderColor: 'rgba(255,255,255,0.08)' }}>
              <div
                className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-white/[0.03] transition"
                style={sub._is_duplicate ? { opacity: 0.55 } : {}}
                onClick={() => setExpandedIdx(isOpen ? null : idx)}
              >
                <span className="text-[10px] text-white/30 w-5 text-center">{idx + 1}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <p className="text-[11px] font-semibold text-white truncate">{sub.subject_name || '(unnamed)'}</p>
                    {sub._is_duplicate && (
                      <span className="flex-shrink-0 text-[8px] px-1 py-0.5 rounded font-bold uppercase tracking-wide"
                        style={{ background: 'rgba(251,191,36,0.18)', color: '#fbbf24' }}>
                        already active
                      </span>
                    )}
                  </div>
                  <p className="text-[9px] text-white/35 truncate">
                    {[sub.semester, sub.course_code, sub.credits ? `${sub.credits} cr` : ''].filter(Boolean).join(' · ')}
                    {' · '}{(sub.chapters || []).length} chapters
                  </p>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold"
                    style={{ background: 'rgba(99,102,241,0.2)', color: '#a5b4fc' }}>
                    {(sub.stream_target || 'All').slice(0, 10)}
                  </span>
                  <button
                    onClick={e => { e.stopPropagation(); onRemoveSubject(idx); }}
                    className="text-red-400/50 hover:text-red-400 transition"
                  >
                    <Trash2 size={11} />
                  </button>
                  <span className="text-white/25 text-[10px]">{isOpen ? '▲' : '▼'}</span>
                </div>
              </div>

              {isOpen && (
                <div className="px-3 pb-3 pt-1 border-t space-y-3" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-[9px] text-white/35 uppercase tracking-wide">Subject Name</label>
                      <input className={inputCls} value={sub.subject_name || ''} onChange={e => onUpdateSubject(idx, 'subject_name', e.target.value)} />
                    </div>
                    <div>
                      <label className="text-[9px] text-white/35 uppercase tracking-wide">Course Code</label>
                      <input className={inputCls} value={sub.course_code || ''} onChange={e => onUpdateSubject(idx, 'course_code', e.target.value)} placeholder="e.g. MAJ-101" />
                    </div>
                    <div>
                      <label className="text-[9px] text-white/35 uppercase tracking-wide">Semester</label>
                      <input className={inputCls} value={sub.semester || ''} onChange={e => onUpdateSubject(idx, 'semester', e.target.value)} placeholder="e.g. Semester 1" />
                    </div>
                    <div>
                      <label className="text-[9px] text-white/35 uppercase tracking-wide">Credits</label>
                      <input className={inputCls} type="number" min="0" value={sub.credits || ''} onChange={e => onUpdateSubject(idx, 'credits', parseInt(e.target.value) || 0)} />
                    </div>
                    <div className="col-span-2">
                      <label className="text-[9px] text-white/35 uppercase tracking-wide">Stream Target</label>
                      <input className={inputCls} value={sub.stream_target || 'All'} onChange={e => onUpdateSubject(idx, 'stream_target', e.target.value)} placeholder="Arts / Science / Commerce / All" />
                    </div>
                  </div>

                  <div>
                    <label className="text-[9px] text-white/35 uppercase tracking-wide block mb-1">Chapters ({(sub.chapters || []).length})</label>
                    <div className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
                      {(sub.chapters || []).map((ch, ci) => {
                        const chTitle = typeof ch === 'string' ? ch : (ch.title || '');
                        const chDesc  = typeof ch === 'string' ? '' : (ch.description || '');
                        const chTopics = typeof ch === 'string' ? [] : (ch.topics || []);
                        return (
                          <div key={ci} className="group">
                            <div className="flex items-center gap-1">
                              <input
                                className={inputCls + ' flex-1'}
                                value={chTitle}
                                onChange={e => {
                                  const chaps = [...(sub.chapters || [])];
                                  if (typeof chaps[ci] === 'string') {
                                    chaps[ci] = e.target.value;
                                  } else {
                                    chaps[ci] = { ...chaps[ci], title: e.target.value };
                                  }
                                  onUpdateSubject(idx, 'chapters', chaps);
                                }}
                              />
                              <button onClick={() => onRemoveChapter(idx, ci)}
                                className="text-red-400/40 hover:text-red-400 transition opacity-0 group-hover:opacity-100 flex-shrink-0">
                                <Trash2 size={10} />
                              </button>
                            </div>
                            {chDesc && (
                              <p className="text-[9px] text-white/35 leading-relaxed mt-0.5 ml-1 line-clamp-2">{chDesc}</p>
                            )}
                            {!chDesc && chTopics.length > 0 && (
                              <p className="text-[9px] text-white/25 mt-0.5 ml-1 truncate">{chTopics.slice(0, 4).join(' · ')}</p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                    <div className="flex items-center gap-1 mt-1.5">
                      <input
                        className={inputCls + ' flex-1'}
                        value={newChapterText[idx] || ''}
                        onChange={e => setNewChapterText(p => ({ ...p, [idx]: e.target.value }))}
                        onKeyDown={e => {
                          if (e.key === 'Enter') {
                            onAddChapter(idx, newChapterText[idx] || '');
                            setNewChapterText(p => ({ ...p, [idx]: '' }));
                          }
                        }}
                        placeholder="Add chapter title…"
                      />
                      <button
                        onClick={() => { onAddChapter(idx, newChapterText[idx] || ''); setNewChapterText(p => ({ ...p, [idx]: '' })); }}
                        className={btnSm + " bg-violet-500/20 hover:bg-violet-500/30 text-violet-300 flex-shrink-0"}
                      >
                        <Plus size={10} />
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2 px-3 pb-3">
        <button
          onClick={onConfirm}
          disabled={confirmLoading || previewData.extracted.length === 0}
          className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold transition"
          style={{ background: 'rgba(139,92,246,0.25)', color: '#c4b5fd', opacity: (confirmLoading || previewData.extracted.length === 0) ? 0.5 : 1 }}
        >
          {confirmLoading
            ? <><Loader2 size={12} className="animate-spin" /> Saving…</>
            : <><CheckCircle size={12} /> Save {previewData.extracted.length} subject{previewData.extracted.length !== 1 ? 's' : ''}</>}
        </button>
        <button
          onClick={onDiscard}
          className="px-4 py-2 rounded-lg text-xs font-semibold text-white/40 hover:text-white/70 transition"
        >
          Discard
        </button>
      </div>
    </div>
  );
}
