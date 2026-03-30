import { useState, useRef, useEffect, useCallback } from 'react';
import {
  X, Sparkles, BookOpen, FileQuestion, Layers, CheckCircle2,
  AlertCircle, Loader2, Zap, Bot, TerminalSquare,
  ArrowRight, CalendarDays,
} from 'lucide-react';
import axios from 'axios';
import { toast } from 'sonner';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

function authHeaders(token) {
  const isJwt = token && token.split('.').length === 3;
  return { headers: isJwt ? { Authorization: `Bearer ${token}` } : {}, withCredentials: true };
}

const STEPS = [
  {
    key: 'notes',
    label: 'Chapter Notes',
    icon: BookOpen,
    color: '#8b5cf6',
    bg: 'rgba(139,92,246,0.12)',
    description: 'Topic-wise structured study notes for each chapter',
    unit: 'notes',
    endpoint: (id) => `/admin/subjects/${id}/generate-notes-bulk`,
    countKey: 'generated',
    outputLabel: (data) => `${data.generated} chapters`,
  },
  {
    key: 'pyqs',
    label: 'Previous Year Questions',
    icon: CalendarDays,
    color: '#f59e0b',
    bg: 'rgba(245,158,11,0.12)',
    description: '12 exam-pattern PYQs per chapter with year tags [2015–2023]',
    unit: 'questions',
    endpoint: (id) => `/admin/subjects/${id}/generate-pyqs-bulk`,
    countKey: 'total_pyqs',
    outputLabel: (data) => `${data.total_pyqs} PYQs`,
  },
  {
    key: 'flashcards',
    label: 'Flashcard Deck',
    icon: Layers,
    color: '#10b981',
    bg: 'rgba(16,185,129,0.12)',
    description: '25 revision flashcards per chapter (definition, concept, formula)',
    unit: 'cards',
    endpoint: (id) => `/admin/subjects/${id}/generate-flashcards-bulk`,
    countKey: 'total_flashcards',
    outputLabel: (data) => `${data.total_flashcards} cards`,
  },
];

const STATE = { idle: 'idle', running: 'running', done: 'done', error: 'error' };

export default function AgenticCreatorModal({
  adminToken, subjectId, subjectName, chapterCount, onClose, onComplete,
}) {
  const [phase, setPhase]             = useState('plan');
  const [enabled, setEnabled]         = useState(new Set(['notes', 'pyqs', 'flashcards']));
  const [stepStates, setStepStates]   = useState({ notes: STATE.idle, pyqs: STATE.idle, flashcards: STATE.idle });
  const [stepResults, setStepResults] = useState({});
  const [log, setLog]                 = useState([]);
  const [currentStep, setCurrentStep] = useState(null);
  const logRef                        = useRef(null);

  const push = useCallback((msg, type = 'info') => {
    setLog(prev => [...prev, { msg, type, ts: Date.now() }]);
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  const toggleStep = (key) => {
    setEnabled(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const setStepStatus = (key, state) =>
    setStepStates(prev => ({ ...prev, [key]: state }));

  const launch = async () => {
    if (enabled.size === 0) { toast.error('Select at least one step'); return; }
    setPhase('running');
    push(`Agent initialized for "${subjectName}" — ${chapterCount} chapters`, 'system');
    push(`Steps queued: ${[...enabled].map(k => STEPS.find(s => s.key === k).label).join(' → ')}`, 'system');

    const steps = STEPS.filter(s => enabled.has(s.key));

    for (const step of steps) {
      setCurrentStep(step.key);
      setStepStatus(step.key, STATE.running);
      push(`▶ Starting: ${step.label}…`, 'run');
      try {
        const res = await axios.post(
          `${API}${step.endpoint(subjectId)}`,
          {},
          { ...authHeaders(adminToken), timeout: 600_000 },
        );
        const data = res.data;
        setStepResults(prev => ({ ...prev, [step.key]: data }));

        // PYQ step: if no papers were found, treat as a warning not a hard error
        if (step.key === 'pyqs' && data.total_pyqs === 0 && data.message?.startsWith('no_papers_found')) {
          setStepStatus(step.key, STATE.error);
          push(`⚠ Web search found no questions and no uploaded PYQ papers exist`, 'warn');
          push(`  → This may be a very niche subject — try uploading actual PYQ PDFs`, 'warn');
          push(`  → PYQ Manager tab → upload PDF → run "HTML Replica" → re-run Agentic Generate`, 'warn');
          continue;
        }

        setStepStatus(step.key, STATE.done);

        // Extra stats for PYQ step
        if (step.key === 'pyqs') {
          const webN   = data.web_found   ?? 0;
          const localN = data.local_found ?? 0;
          const poolN  = data.pool_size   ?? 0;
          const parts  = [];
          if (webN > 0)   parts.push(`${webN} from web search`);
          if (localN > 0) parts.push(`${localN} from uploaded papers`);
          if (parts.length)
            push(`  Sources: ${parts.join(' · ')} (${poolN} unique in pool)`, 'detail');
        }

        const skipped = (data.results || []).filter(r => r.status === 'skipped').length;
        const errors  = (data.results || []).filter(r => r.status === 'error').length;
        push(`✓ ${step.outputLabel(data)} generated`, 'ok');
        if (skipped > 0) push(`  ${skipped} chapter(s) skipped (missing content)`, 'warn');
        if (errors > 0)  push(`  ${errors} chapter(s) failed`, 'warn');

        (data.results || []).filter(r => r.status === 'ok').slice(0, 5).forEach(r => {
          const count = r.count ? ` (${r.count})` : '';
          push(`  · ${r.title}${count}`, 'detail');
        });
        if ((data.results || []).filter(r => r.status === 'ok').length > 5) {
          push(`  · … and ${(data.results || []).filter(r => r.status === 'ok').length - 5} more`, 'detail');
        }
      } catch (e) {
        setStepStatus(step.key, STATE.error);
        const msg = e?.response?.data?.detail || e.message || 'Request failed';
        push(`✗ ${step.label} failed: ${msg}`, 'error');
      }
    }

    setCurrentStep(null);
    setPhase('done');
    push('── Agent complete ──', 'system');
    onComplete?.();
  };

  const allDone        = phase === 'done';
  const totalNotes     = stepResults.notes?.generated || 0;
  const totalPyqs      = stepResults.pyqs?.total_pyqs || 0;
  const totalFlashcards = stepResults.flashcards?.total_flashcards || 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)' }}
    >
      <div
        className="w-full max-w-xl rounded-2xl flex flex-col overflow-hidden"
        style={{ background: '#0f0f1a', border: '1px solid rgba(139,92,246,0.25)', maxHeight: '90vh' }}
      >

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b flex-shrink-0"
          style={{ borderColor: 'rgba(139,92,246,0.18)', background: 'rgba(139,92,246,0.06)' }}>
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center"
              style={{ background: 'rgba(139,92,246,0.20)' }}>
              <Bot size={15} style={{ color: '#a78bfa' }} />
            </div>
            <div>
              <p className="text-sm font-bold" style={{ color: '#e8e8e8' }}>Agentic Content Creator</p>
              <p className="text-[10px]" style={{ color: 'rgba(255,255,255,0.35)' }}>
                {subjectName} · {chapterCount} chapters
              </p>
            </div>
          </div>
          <button onClick={onClose}
            className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-white/10 transition-colors"
            style={{ color: 'rgba(255,255,255,0.40)' }}>
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto min-h-0">

          {/* PLAN PHASE */}
          {phase === 'plan' && (
            <div className="p-5 space-y-4">
              <div>
                <p className="text-xs font-semibold mb-1" style={{ color: 'rgba(255,255,255,0.50)' }}>
                  SELECT WHAT TO GENERATE
                </p>
                <p className="text-[11px]" style={{ color: 'rgba(255,255,255,0.28)' }}>
                  The agent runs each step in sequence, building on prior output.
                </p>
              </div>

              <div className="space-y-2">
                {STEPS.map((step, i) => {
                  const Icon = step.icon;
                  const on = enabled.has(step.key);
                  return (
                    <button
                      key={step.key}
                      onClick={() => toggleStep(step.key)}
                      className="w-full text-left rounded-xl p-3.5 border transition-all"
                      style={{
                        background: on ? step.bg : 'rgba(255,255,255,0.025)',
                        borderColor: on ? `${step.color}55` : 'rgba(255,255,255,0.07)',
                      }}
                    >
                      <div className="flex items-start gap-3">
                        <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
                          style={{ background: on ? `${step.color}22` : 'rgba(255,255,255,0.05)' }}>
                          <Icon size={15} style={{ color: on ? step.color : 'rgba(255,255,255,0.30)' }} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold" style={{ color: on ? '#e8e8e8' : 'rgba(255,255,255,0.40)' }}>
                              Step {i + 1} — {step.label}
                            </span>
                            {step.key === 'pyqs' && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                                style={{ background: 'rgba(245,158,11,0.12)', color: '#fbbf24' }}>
                                with year tags
                              </span>
                            )}
                            {step.key === 'flashcards' && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                                style={{ background: 'rgba(255,255,255,0.07)', color: 'rgba(255,255,255,0.30)' }}>
                                uses notes
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] mt-0.5" style={{ color: 'rgba(255,255,255,0.38)' }}>
                            {step.description}
                          </p>
                        </div>
                        <div className="flex-shrink-0 w-4 h-4 rounded border flex items-center justify-center mt-1"
                          style={{
                            borderColor: on ? step.color : 'rgba(255,255,255,0.20)',
                            background: on ? step.color : 'transparent',
                          }}>
                          {on && <CheckCircle2 size={10} className="text-white" />}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>

              {/* Estimated output */}
              {enabled.size > 0 && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs flex-wrap"
                  style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>
                  <span style={{ color: 'rgba(255,255,255,0.35)' }}>Estimated output:</span>
                  {enabled.has('notes') && (
                    <span className="font-mono" style={{ color: '#8b5cf6' }}>{chapterCount} notes</span>
                  )}
                  {enabled.has('pyqs') && (
                    <span className="font-mono" style={{ color: '#f59e0b' }}>{chapterCount * 12} PYQs</span>
                  )}
                  {enabled.has('flashcards') && (
                    <span className="font-mono" style={{ color: '#10b981' }}>{chapterCount * 25} flashcards</span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* RUNNING / DONE PHASE */}
          {(phase === 'running' || phase === 'done') && (
            <div className="p-5 space-y-4">

              {/* Step tracker */}
              <div className="space-y-2">
                {STEPS.filter(s => enabled.has(s.key)).map((step) => {
                  const Icon = step.icon;
                  const st = stepStates[step.key];
                  const res = stepResults[step.key];
                  const isActive = currentStep === step.key;

                  return (
                    <div key={step.key}
                      className="flex items-center gap-3 px-3 py-2.5 rounded-xl"
                      style={{
                        background: isActive ? step.bg : st === STATE.done ? 'rgba(52,211,153,0.06)' : 'rgba(255,255,255,0.03)',
                        border: `1px solid ${isActive ? `${step.color}40` : st === STATE.done ? 'rgba(52,211,153,0.20)' : 'rgba(255,255,255,0.06)'}`,
                      }}>
                      <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                        style={{ background: isActive ? `${step.color}22` : 'rgba(255,255,255,0.05)' }}>
                        {st === STATE.running && <Loader2 size={13} className="animate-spin" style={{ color: step.color }} />}
                        {st === STATE.done && <CheckCircle2 size={13} style={{ color: '#34d399' }} />}
                        {st === STATE.error && <AlertCircle size={13} style={{ color: '#ef4444' }} />}
                        {st === STATE.idle && <Icon size={13} style={{ color: 'rgba(255,255,255,0.25)' }} />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-semibold" style={{
                          color: st === STATE.done ? '#34d399' : isActive ? '#e8e8e8' : 'rgba(255,255,255,0.35)',
                        }}>
                          {step.label}
                        </p>
                        {res && st === STATE.done && (
                          <p className="text-[10px] font-mono" style={{ color: 'rgba(52,211,153,0.70)' }}>
                            {step.outputLabel(res)} · {res.generated}/{res.total} chapters
                          </p>
                        )}
                        {isActive && (
                          <p className="text-[10px]" style={{ color: `${step.color}cc` }}>
                            Running…
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Agent log */}
              <div>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <TerminalSquare size={11} style={{ color: 'rgba(255,255,255,0.30)' }} />
                  <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'rgba(255,255,255,0.30)' }}>
                    Agent Log
                  </p>
                </div>
                <div ref={logRef}
                  className="rounded-xl p-3 font-mono text-[11px] space-y-0.5 overflow-y-auto"
                  style={{ background: 'rgba(0,0,0,0.40)', border: '1px solid rgba(255,255,255,0.07)', maxHeight: '180px' }}>
                  {log.map((entry, i) => (
                    <p key={i} style={{
                      color: entry.type === 'ok'     ? '#34d399'
                           : entry.type === 'error'  ? '#ef4444'
                           : entry.type === 'warn'   ? '#fbbf24'
                           : entry.type === 'run'    ? '#a78bfa'
                           : entry.type === 'system' ? 'rgba(255,255,255,0.35)'
                           : 'rgba(255,255,255,0.45)',
                    }}>
                      {entry.msg}
                    </p>
                  ))}
                  {phase === 'running' && (
                    <p className="animate-pulse" style={{ color: 'rgba(139,92,246,0.60)' }}>▋</p>
                  )}
                </div>
              </div>

              {/* Done summary */}
              {allDone && (
                <div className="grid grid-cols-3 gap-2">
                  {enabled.has('notes') && (
                    <div className="rounded-xl p-3 text-center" style={{ background: 'rgba(139,92,246,0.10)', border: '1px solid rgba(139,92,246,0.20)' }}>
                      <p className="text-xl font-bold" style={{ color: '#a78bfa' }}>{totalNotes}</p>
                      <p className="text-[10px]" style={{ color: 'rgba(255,255,255,0.40)' }}>chapters<br />with notes</p>
                    </div>
                  )}
                  {enabled.has('pyqs') && (
                    <div className="rounded-xl p-3 text-center" style={{ background: 'rgba(245,158,11,0.10)', border: '1px solid rgba(245,158,11,0.20)' }}>
                      <p className="text-xl font-bold" style={{ color: '#fbbf24' }}>{totalPyqs}</p>
                      <p className="text-[10px]" style={{ color: 'rgba(255,255,255,0.40)' }}>PYQs<br />generated</p>
                    </div>
                  )}
                  {enabled.has('flashcards') && (
                    <div className="rounded-xl p-3 text-center" style={{ background: 'rgba(16,185,129,0.10)', border: '1px solid rgba(16,185,129,0.20)' }}>
                      <p className="text-xl font-bold" style={{ color: '#34d399' }}>{totalFlashcards}</p>
                      <p className="text-[10px]" style={{ color: 'rgba(255,255,255,0.40)' }}>flashcards<br />generated</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t flex items-center gap-3 flex-shrink-0"
          style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          {phase === 'plan' && (
            <>
              <button onClick={onClose}
                className="px-4 py-2 rounded-xl text-sm border"
                style={{ borderColor: 'rgba(255,255,255,0.10)', color: 'rgba(255,255,255,0.40)' }}>
                Cancel
              </button>
              <button onClick={launch} disabled={enabled.size === 0}
                className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold disabled:opacity-40 transition-all"
                style={{ background: 'linear-gradient(135deg,#7c3aed,#4f46e5)', color: 'white' }}>
                <Zap size={14} />
                Launch Agent
                <ArrowRight size={13} />
              </button>
            </>
          )}
          {phase === 'running' && (
            <div className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm"
              style={{ background: 'rgba(139,92,246,0.10)', color: '#a78bfa' }}>
              <Loader2 size={13} className="animate-spin" />
              Agent is working — do not close this window
            </div>
          )}
          {phase === 'done' && (
            <>
              <div className="flex items-center gap-1.5 flex-1 text-xs" style={{ color: '#34d399' }}>
                <CheckCircle2 size={13} />
                All steps complete
              </div>
              <button onClick={onClose}
                className="px-5 py-2.5 rounded-xl text-sm font-semibold"
                style={{ background: 'rgba(52,211,153,0.15)', color: '#34d399', border: '1px solid rgba(52,211,153,0.25)' }}>
                Done
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
