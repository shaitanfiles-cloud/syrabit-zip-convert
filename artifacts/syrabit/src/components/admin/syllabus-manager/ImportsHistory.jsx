import { useState } from 'react';
import { Loader2, BookOpen, ChevronDown, ChevronUp, Pencil, Trash2, X, Plus, Save, RefreshCw } from 'lucide-react';

const PAPER_ICONS = { aec:'🧠', sec:'⚡', mdc:'🌐', vac:'✨', ge:'🔄', cc:'⭐', major:'🎯', minor:'📘' };

export default function ImportsHistory({
  importsOpen, setImportsOpen,
  imports, importsLoading, loadImports,
  onStartEdit, onSaveEdit, onDeleteImport,
  editingImport, setEditingImport,
  editChapters, setEditChapters,
  editGuidelines, setEditGuidelines,
  editSaving,
  deletingImport, setDeletingImport,
}) {
  const [expandedImport, setExpandedImport] = useState(null);

  return (
    <div className="rounded-xl border" style={{ background: 'rgba(99,102,241,0.04)', borderColor: 'rgba(99,102,241,0.18)' }}>
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-left"
        onClick={() => {
          const next = !importsOpen;
          setImportsOpen(next);
          if (next && imports.length === 0) loadImports();
        }}
      >
        <div className="flex items-center gap-2">
          <BookOpen size={14} className="text-indigo-400" />
          <span className="text-sm font-semibold text-white/90">Uploaded Syllabuses</span>
          {imports.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full font-semibold"
              style={{ background: 'rgba(99,102,241,0.20)', color: '#a5b4fc' }}>
              {imports.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {importsOpen && (
            <button onClick={e => { e.stopPropagation(); loadImports(); }}
              className="p-1 rounded hover:bg-white/10 text-white/40 hover:text-white/70 transition-colors">
              <RefreshCw size={12} className={importsLoading ? 'animate-spin' : ''} />
            </button>
          )}
          {importsOpen ? <ChevronUp size={14} className="text-white/40" /> : <ChevronDown size={14} className="text-white/40" />}
        </div>
      </button>

      {importsOpen && (
        <div className="border-t" style={{ borderColor: 'rgba(99,102,241,0.15)' }}>
          {importsLoading ? (
            <div className="flex items-center justify-center py-8 gap-2 text-white/40">
              <Loader2 size={16} className="animate-spin" /> Loading…
            </div>
          ) : imports.length === 0 ? (
            <div className="text-center py-8 text-white/30 text-sm">No uploaded syllabuses yet</div>
          ) : (
            <div className="divide-y" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
              {imports.map(imp => {
                const isExpanded  = expandedImport  === imp.import_id;
                const isEditing   = editingImport   === imp.import_id;
                const isDeleting  = deletingImport  === imp.import_id;
                const dateStr = imp.created_at ? new Date(imp.created_at).toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' }) : '—';

                return (
                  <div key={imp.import_id}>
                    <div className="px-4 py-3 flex items-start gap-3">
                      <button
                        className="mt-0.5 p-0.5 rounded text-white/30 hover:text-white/70 transition-colors flex-shrink-0"
                        onClick={() => setExpandedImport(isExpanded ? null : imp.import_id)}
                      >
                        {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      </button>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-[10px]">{PAPER_ICONS[imp.paper_type] || '📄'}</span>
                          <span className="text-sm font-semibold text-white truncate">
                            {imp.subject_name}{imp.subjects_count > 1 ? ` +${imp.subjects_count - 1} more` : ''}
                          </span>
                          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded uppercase"
                            style={{ background: 'rgba(99,102,241,0.18)', color: '#a5b4fc' }}>
                            {imp.paper_type}
                          </span>
                          <span className="text-[9px] px-1.5 py-0.5 rounded font-medium"
                            style={{ background: imp.status === 'linked' ? 'rgba(52,211,153,0.15)' : 'rgba(251,191,36,0.15)',
                                     color: imp.status === 'linked' ? '#6ee7b7' : '#fcd34d' }}>
                            {imp.status}
                          </span>
                        </div>
                        <p className="text-[10px] text-white/40 mt-0.5">
                          {[imp.board_name, imp.class_year, imp.semester].filter(Boolean).join(' · ')}
                          {imp.course_code ? ` · ${imp.course_code}` : ''}
                          {imp.credits ? ` · ${imp.credits} cr` : ''}
                          &nbsp;·&nbsp;{(imp.chapters || []).length} chapters
                          &nbsp;·&nbsp;{dateStr}
                        </p>
                        <p className="text-[9px] text-white/25 mt-0.5 font-mono truncate">{imp.filename}</p>
                      </div>

                      <div className="flex items-center gap-1 flex-shrink-0">
                        <button
                          title="Edit chapters"
                          onClick={() => {
                            setExpandedImport(imp.import_id);
                            onStartEdit(imp);
                          }}
                          className="p-1.5 rounded-lg transition-colors text-indigo-300 hover:text-indigo-200"
                          style={{ background: 'rgba(99,102,241,0.12)' }}>
                          <Pencil size={12} />
                        </button>
                        <button
                          title="Delete"
                          onClick={() => setDeletingImport(isDeleting ? null : imp.import_id)}
                          className="p-1.5 rounded-lg transition-colors text-rose-400 hover:text-rose-300"
                          style={{ background: 'rgba(244,63,94,0.10)' }}>
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>

                    {isDeleting && (
                      <div className="mx-4 mb-3 p-3 rounded-xl border text-xs space-y-2"
                        style={{ background: 'rgba(244,63,94,0.07)', borderColor: 'rgba(244,63,94,0.25)' }}>
                        <p className="font-semibold text-rose-300">
                          Delete {imp.subjects_count > 1 ? `${imp.subjects_count} subjects from this import` : `"${imp.subject_name}"`}?
                        </p>
                        <p className="text-white/50">Choose what to remove:</p>
                        <div className="flex gap-2 flex-wrap">
                          <button onClick={() => onDeleteImport(imp.import_id, false)}
                            className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors"
                            style={{ background: 'rgba(244,63,94,0.18)', color: '#fca5a5', border: '1px solid rgba(244,63,94,0.30)' }}>
                            Delete record only
                          </button>
                          <button onClick={() => onDeleteImport(imp.import_id, true)}
                            className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors"
                            style={{ background: 'rgba(244,63,94,0.30)', color: '#fca5a5', border: '1px solid rgba(244,63,94,0.50)' }}>
                            Delete record + content cards
                          </button>
                          <button onClick={() => setDeletingImport(null)}
                            className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white/50 hover:text-white/80 transition-colors">
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}

                    {isExpanded && (
                      <div className="mx-4 mb-3 rounded-xl border p-3 space-y-3"
                        style={{ background: 'rgba(15,15,30,0.50)', borderColor: 'rgba(99,102,241,0.15)' }}>

                        {isEditing ? (
                          <>
                            <div className="flex items-center justify-between">
                              <p className="text-xs font-semibold text-indigo-300">Edit Chapters</p>
                              <button onClick={() => setEditingImport(null)}
                                className="p-1 rounded text-white/40 hover:text-white/70"><X size={12} /></button>
                            </div>
                            <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                              {editChapters.map((ch, ci) => (
                                <div key={ci} className="flex items-center gap-2">
                                  <span className="text-[10px] text-white/30 w-5 text-right flex-shrink-0">{ci + 1}.</span>
                                  <input
                                    value={ch}
                                    onChange={e => {
                                      const arr = [...editChapters];
                                      arr[ci] = e.target.value;
                                      setEditChapters(arr);
                                    }}
                                    className="flex-1 text-xs bg-white/5 border border-white/10 rounded-lg px-2 py-1 text-white focus:outline-none focus:border-indigo-400/50"
                                  />
                                  <button onClick={() => setEditChapters(prev => prev.filter((_, i) => i !== ci))}
                                    className="text-rose-400/70 hover:text-rose-300 flex-shrink-0"><X size={11} /></button>
                                </div>
                              ))}
                            </div>
                            <div className="flex gap-2">
                              <input
                                placeholder="Add chapter…"
                                className="flex-1 text-xs bg-white/5 border border-white/10 rounded-lg px-2 py-1 text-white focus:outline-none focus:border-indigo-400/50 placeholder-white/20"
                                onKeyDown={e => {
                                  if (e.key === 'Enter' && e.target.value.trim()) {
                                    setEditChapters(prev => [...prev, e.target.value.trim()]);
                                    e.target.value = '';
                                  }
                                }}
                              />
                              <button
                                onClick={e => {
                                  const inp = e.currentTarget.previousSibling;
                                  if (inp.value.trim()) { setEditChapters(prev => [...prev, inp.value.trim()]); inp.value = ''; }
                                }}
                                className="px-2 py-1 rounded-lg text-xs font-semibold"
                                style={{ background: 'rgba(99,102,241,0.25)', color: '#a5b4fc' }}>
                                <Plus size={12} />
                              </button>
                            </div>
                            <div>
                              <p className="text-[10px] text-white/40 mb-1">Assessment Guidelines</p>
                              <textarea
                                rows={2}
                                value={editGuidelines}
                                onChange={e => setEditGuidelines(e.target.value)}
                                className="w-full text-xs bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-white focus:outline-none focus:border-indigo-400/50 resize-none placeholder-white/20"
                                placeholder="Exam pattern, marks, assessment notes…"
                              />
                            </div>
                            <div className="flex gap-2">
                              <button onClick={() => onSaveEdit(imp.import_id)} disabled={editSaving}
                                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50"
                                style={{ background: 'rgba(99,102,241,0.30)', color: '#c4b5fd', border: '1px solid rgba(99,102,241,0.40)' }}>
                                {editSaving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
                                {editSaving ? 'Saving…' : 'Save & Sync'}
                              </button>
                              <button onClick={() => setEditingImport(null)}
                                className="px-3 py-1.5 rounded-lg text-xs text-white/40 hover:text-white/70">Cancel</button>
                            </div>
                          </>
                        ) : (
                          <>
                            <div className="flex items-center justify-between">
                              <p className="text-[10px] font-semibold text-white/50 uppercase tracking-wide">
                                {(imp.chapters || []).length} Chapters
                              </p>
                              <button onClick={() => onStartEdit(imp)}
                                className="text-[10px] text-indigo-300 hover:text-indigo-200 flex items-center gap-1">
                                <Pencil size={10} /> Edit
                              </button>
                            </div>
                            <ol className="space-y-2 max-h-72 overflow-y-auto pr-1">
                              {(imp.chapter_details || imp.chapters || []).map((ch, ci) => {
                                const title = typeof ch === 'string' ? ch : (ch.title || '');
                                const desc  = typeof ch === 'string' ? '' : (ch.description || '');
                                const topics = typeof ch === 'string' ? [] : (ch.topics || []);
                                return (
                                  <li key={ci} className="flex items-start gap-2 text-xs">
                                    <span className="text-white/25 w-5 text-right flex-shrink-0 mt-0.5">{ci + 1}.</span>
                                    <div className="flex-1 min-w-0">
                                      <span className="text-white/75 font-medium">{title}</span>
                                      {desc && (
                                        <p className="text-white/40 text-[10px] leading-relaxed mt-0.5">{desc}</p>
                                      )}
                                      {!desc && topics.length > 0 && (
                                        <p className="text-white/35 text-[10px] mt-0.5">{topics.slice(0, 5).join(' · ')}</p>
                                      )}
                                    </div>
                                  </li>
                                );
                              })}
                            </ol>
                            {imp.guidelines && (
                              <div className="pt-2 border-t" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
                                <p className="text-[10px] text-white/35 mb-1">Assessment Guidelines</p>
                                <p className="text-[11px] text-white/55 leading-relaxed">{imp.guidelines}</p>
                              </div>
                            )}
                            {(imp.linked_subject_ids || []).length > 0 && (
                              <div className="pt-2 border-t" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
                                <p className="text-[10px] text-white/35 mb-1">Linked Content Subjects</p>
                                <p className="text-[10px] text-indigo-300/70 font-mono">{imp.linked_subject_ids.join(', ')}</p>
                              </div>
                            )}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
