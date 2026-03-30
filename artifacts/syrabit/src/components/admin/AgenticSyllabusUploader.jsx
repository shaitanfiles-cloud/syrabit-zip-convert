import { useState, useRef, useCallback } from 'react';
import {
  Upload, Loader2, CheckCircle2, XCircle, ChevronDown, ChevronRight,
  Sparkles, BookOpen, Brain, Layers, Database, Zap, FileText,
  Globe, ArrowRight, RefreshCw, AlertTriangle,
} from 'lucide-react';
import { toast } from 'sonner';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

function authHeaders(token) {
  const isJwt = token && token.split('.').length === 3;
  return isJwt ? { Authorization: `Bearer ${token}` } : {};
}

const PAPER_TYPES = [
  { value: 'major', label: 'Major',  icon: '🎯', desc: 'Core discipline course' },
  { value: 'minor', label: 'Minor',  icon: '📘', desc: 'Minor elective' },
  { value: 'mdc',   label: 'MDC',    icon: '🌐', desc: 'Multidisciplinary' },
  { value: 'vac',   label: 'VAC',    icon: '✨', desc: 'Value-Added Course' },
  { value: 'aec',   label: 'AEC',    icon: '🧠', desc: 'Ability Enhancement' },
  { value: 'sec',   label: 'SEC',    icon: '⚡', desc: 'Skill Enhancement' },
  { value: 'ge',    label: 'GE',     icon: '🔄', desc: 'Generic Elective' },
  { value: 'cc',    label: 'CC',     icon: '⭐', desc: 'Core Course' },
];

// pipeline step definitions per chapter
const CHAPTER_STEPS = [
  { key: 'chapter_content',  icon: Brain,    label: 'AI content generated'  },
  { key: 'chapter_chunked',  icon: Layers,   label: 'Content chunked (RAG)' },
  { key: 'chapter_embedded', icon: Database, label: 'Embedded for AI chat'  },
];

function StepDot({ done, active, error }) {
  if (error)  return <XCircle size={13} style={{ color: '#ef4444' }} />;
  if (done)   return <CheckCircle2 size={13} style={{ color: '#10b981' }} />;
  if (active) return <Loader2 size={13} className="animate-spin" style={{ color: '#8b5cf6' }} />;
  return <div style={{ width: 10, height: 10, borderRadius: '50%', border: '1.5px solid rgba(255,255,255,0.15)' }} />;
}

function SubjectCard({ subj, isActive }) {
  const [open, setOpen] = useState(false);
  const status = subj.status;
  const borderColor = status === 'done' ? '#10b981' : status === 'error' ? '#ef4444' : isActive ? '#8b5cf6' : 'rgba(255,255,255,0.07)';
  const bgColor = isActive ? 'rgba(139,92,246,0.06)' : status === 'done' ? 'rgba(16,185,129,0.04)' : 'rgba(255,255,255,0.02)';

  return (
    <div style={{ border: `1px solid ${borderColor}`, borderRadius: 10, background: bgColor, marginBottom: 8, transition: 'all 0.3s' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', cursor: 'pointer' }} onClick={() => setOpen(o => !o)}>
        {status === 'done'    && <CheckCircle2 size={16} style={{ color: '#10b981', flexShrink: 0 }} />}
        {status === 'active'  && <Loader2 size={16} className="animate-spin" style={{ color: '#8b5cf6', flexShrink: 0 }} />}
        {status === 'error'   && <XCircle size={16} style={{ color: '#ef4444', flexShrink: 0 }} />}
        {status === 'pending' && <div style={{ width: 16, height: 16, borderRadius: '50%', border: '2px solid rgba(255,255,255,0.15)', flexShrink: 0 }} />}

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e8e8e8', truncate: true }}>{subj.name}</div>
          <div style={{ fontSize: 10, color: 'rgba(232,232,232,0.35)', marginTop: 1 }}>
            {subj.board && <span>{subj.board} · </span>}
            {subj.semester && <span>{subj.semester} · </span>}
            {subj.chapters?.length > 0 && <span>{subj.chapters.length} chapters</span>}
            {subj.chunks_created > 0 && <span> · {subj.chunks_created} chunks</span>}
          </div>
        </div>

        {/* Chapter progress bar */}
        {status === 'active' && subj.chapters?.length > 0 && (
          <div style={{ width: 80 }}>
            <div style={{ height: 3, borderRadius: 2, background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
              <div style={{ height: '100%', borderRadius: 2, background: '#8b5cf6', width: `${(subj.doneCh / subj.chapters.length) * 100}%`, transition: 'width 0.4s' }} />
            </div>
            <div style={{ fontSize: 9, color: 'rgba(232,232,232,0.3)', marginTop: 2, textAlign: 'right' }}>
              {subj.doneCh || 0}/{subj.chapters.length}
            </div>
          </div>
        )}

        {open ? <ChevronDown size={12} style={{ color: 'rgba(255,255,255,0.3)', flexShrink: 0 }} /> : <ChevronRight size={12} style={{ color: 'rgba(255,255,255,0.2)', flexShrink: 0 }} />}
      </div>

      {open && subj.chapters?.length > 0 && (
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.05)', padding: '8px 14px 10px' }}>
          {subj.chapters.map((ch, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', borderBottom: i < subj.chapters.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none' }}>
              <StepDot done={ch.done} active={ch.active} error={ch.error} />
              <span style={{ fontSize: 11, color: ch.done ? '#e8e8e8' : ch.active ? '#c4b5fd' : 'rgba(232,232,232,0.4)', flex: 1 }}>{ch.title}</span>
              <div style={{ display: 'flex', gap: 6 }}>
                {CHAPTER_STEPS.map(s => {
                  const stepDone = ch.steps?.[s.key];
                  const Icon = s.icon;
                  return (
                    <div key={s.key} title={s.label} style={{ opacity: stepDone ? 1 : 0.25 }}>
                      <Icon size={10} style={{ color: stepDone ? '#10b981' : 'rgba(232,232,232,0.4)' }} />
                    </div>
                  );
                })}
                {ch.chunks != null && (
                  <span style={{ fontSize: 9, color: 'rgba(232,232,232,0.3)' }}>{ch.chunks}c</span>
                )}
              </div>
            </div>
          ))}
          {subj.geo_phrase && (
            <div style={{ marginTop: 6, fontSize: 10, color: 'rgba(232,232,232,0.3)' }}>
              <Globe size={9} style={{ display: 'inline', marginRight: 4 }} />{subj.geo_phrase}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function AgenticSyllabusUploader({ adminToken, onComplete }) {
  const [phase, setPhase]             = useState('upload');   // upload | running | done
  const [file, setFile]               = useState(null);
  const [paperType, setPaperType]     = useState('major');
  const [dragging, setDragging]       = useState(false);
  const [running, setRunning]         = useState(false);
  const [subjects, setSubjects]       = useState([]);
  const [log, setLog]                 = useState([]);
  const [summary, setSummary]         = useState(null);
  const [scanTotal, setScanTotal]     = useState(0);
  const [activeSubjIdx, setActiveSubjIdx] = useState(-1);
  const fileRef   = useRef(null);
  const logEndRef = useRef(null);
  const abortRef  = useRef(null);

  const addLog = useCallback((msg, color = 'rgba(232,232,232,0.45)') => {
    setLog(prev => [...prev.slice(-120), { msg, color, ts: Date.now() }]);
    setTimeout(() => logEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50);
  }, []);

  const handleFile = useCallback((f) => {
    if (!f || !f.name.toLowerCase().endsWith('.pdf')) {
      toast.error('Only PDF files are supported');
      return;
    }
    setFile(f);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, [handleFile]);

  const startRun = useCallback(async () => {
    if (!file) { toast.error('Please select a PDF first'); return; }
    setRunning(true);
    setPhase('running');
    setSubjects([]);
    setLog([]);
    setSummary(null);
    setActiveSubjIdx(-1);

    const form = new FormData();
    form.append('file', file);
    form.append('paper_type', paperType);

    const controller = new AbortController();
    abortRef.current = controller;

    addLog(`Starting agentic import: ${file.name}`, '#c4b5fd');
    addLog(`Paper type: ${paperType.toUpperCase()}`, 'rgba(232,232,232,0.3)');

    try {
      const resp = await fetch(`${API}/admin/agentic-syllabus/run`, {
        method: 'POST',
        headers: { ...authHeaders(adminToken) },
        body: form,
        signal: controller.signal,
        credentials: 'include',
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || 'Request failed');
      }

      const reader  = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      // State held in ref to avoid stale closure issues
      const subjMapRef = { current: {} };  // name → subject obj

      const processEvent = (eventName, data) => {
        switch (eventName) {
          case 'scan_start':
            addLog(`📄 Scanning PDF: ${data.filename}`, '#60a5fa');
            addLog(`   Extracting subjects with Gemini Vision…`, 'rgba(232,232,232,0.3)');
            break;

          case 'scan_complete': {
            setScanTotal(data.total);
            addLog(`✅ Found ${data.total} subject(s): ${data.subjects.join(', ')}`, '#34d399');
            // Pre-populate subjects list
            const newSubjs = (data.subjects || []).map(name => ({
              name,
              status: 'pending',
              chapters: [],
              doneCh: 0,
              chunks_created: 0,
            }));
            newSubjs.forEach(s => { subjMapRef.current[s.name] = s; });
            setSubjects([...newSubjs]);
            break;
          }

          case 'subject_start': {
            addLog(`\n📚 [${data.index + 1}/${data.total}] ${data.name}`, '#a78bfa');
            addLog(`   ${data.board || 'DEGREE'} · ${data.semester || 'Semester ?'} · ${data.chapters} chapters`, 'rgba(232,232,232,0.3)');
            setActiveSubjIdx(data.index);
            setSubjects(prev => {
              const copy = [...prev];
              const idx  = copy.findIndex(s => s.name === data.name);
              if (idx >= 0) {
                copy[idx] = { ...copy[idx], status: 'active', chapters: Array.from({ length: data.chapters }, (_, i) => ({ title: `Chapter ${i+1}`, active: false, done: false, steps: {} })) };
                subjMapRef.current[data.name] = copy[idx];
              }
              return copy;
            });
            break;
          }

          case 'hierarchy':
            addLog(`   🏗️  ${data.board} → ${data.class} → ${data.stream} → ${data.subject}`, '#fcd34d');
            if (data.created_nodes?.length)
              addLog(`   ✨ Created: ${data.created_nodes.join(', ')}`, '#86efac');
            break;

          case 'chapter_start':
            addLog(`   📖 Chapter ${data.index + 1}/${data.total}: ${data.chapter}`, 'rgba(232,232,232,0.5)');
            setSubjects(prev => {
              const copy  = [...prev];
              const si    = copy.findIndex(s => s.name === data.subject);
              if (si >= 0) {
                const chs = [...(copy[si].chapters || [])];
                const ci  = data.index;
                if (chs[ci]) chs[ci] = { ...chs[ci], title: data.chapter, active: true };
                else chs[ci] = { title: data.chapter, active: true, done: false, steps: {} };
                copy[si] = { ...copy[si], chapters: chs };
              }
              return copy;
            });
            break;

          case 'chapter_content':
            addLog(`      🧠 AI content: ${data.length} chars${data.existing ? ' (existing)' : ''}`, '#86efac');
            updateChapterStep(setSubjects, data.chapter, 'chapter_content');
            break;

          case 'chapter_chunked':
            addLog(`      📦 Chunked: ${data.chunks} RAG chunks`, '#86efac');
            updateChapterStep(setSubjects, data.chapter, 'chapter_chunked', data.chunks);
            break;

          case 'chapter_embedded':
            addLog(`      🔗 Embedded: ${data.ok ? 'ok' : 'skipped'}`, data.ok ? '#86efac' : 'rgba(232,232,232,0.3)');
            updateChapterStep(setSubjects, data.chapter, 'chapter_embedded');
            // Mark chapter done
            setSubjects(prev => {
              const copy = [...prev];
              for (let si = 0; si < copy.length; si++) {
                const chs = copy[si].chapters || [];
                const ci  = chs.findIndex(c => c.title === data.chapter);
                if (ci >= 0) {
                  const newChs = [...chs];
                  newChs[ci] = { ...newChs[ci], active: false, done: true };
                  const doneCh = newChs.filter(c => c.done).length;
                  copy[si] = { ...copy[si], chapters: newChs, doneCh };
                  break;
                }
              }
              return copy;
            });
            break;

          case 'seo_tagged':
            addLog(`   🌐 SEO tagged: ${data.geo_phrase}`, '#67e8f9');
            setSubjects(prev => {
              const copy = [...prev];
              const idx  = copy.findIndex(s => s.name === data.subject);
              if (idx >= 0) copy[idx] = { ...copy[idx], geo_phrase: data.geo_phrase };
              return copy;
            });
            break;

          case 'subject_done':
            addLog(`   ✅ ${data.name} done — ${data.chapters_done} chapters, ${data.chunks_created} chunks`, '#34d399');
            setSubjects(prev => {
              const copy = [...prev];
              const idx  = copy.findIndex(s => s.name === data.name);
              if (idx >= 0) copy[idx] = { ...copy[idx], status: 'done', chunks_created: data.chunks_created };
              return copy;
            });
            break;

          case 'complete':
            addLog(`\n🎉 Import complete!`, '#34d399');
            addLog(`   ${data.total_subjects} subjects · ${data.total_chapters} chapters · ${data.total_chunks} RAG chunks · ${data.total_embedded} embeddings`, '#86efac');
            setSummary(data);
            setPhase('done');
            setRunning(false);
            if (onComplete) onComplete(data);
            break;

          case 'error':
            addLog(`❌ Error: ${data.message}`, '#fca5a5');
            toast.error(data.message);
            break;

          default:
            break;
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop() || '';
        for (const part of parts) {
          const lines = part.trim().split('\n');
          let eventName = 'message';
          let dataStr   = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) eventName = line.slice(7).trim();
            else if (line.startsWith('data: '))  dataStr  = line.slice(6).trim();
          }
          if (dataStr) {
            try {
              processEvent(eventName, JSON.parse(dataStr));
            } catch (pe) {
              console.warn('SSE parse error', pe, dataStr);
            }
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        addLog('⛔ Import cancelled', '#fca5a5');
      } else {
        addLog(`❌ ${err.message}`, '#fca5a5');
        toast.error('Import failed: ' + err.message);
      }
      setRunning(false);
      setPhase('upload');
    }
  }, [file, paperType, adminToken, addLog, onComplete]);

  const reset = () => {
    abortRef.current?.abort();
    setPhase('upload');
    setFile(null);
    setSubjects([]);
    setLog([]);
    setSummary(null);
    setRunning(false);
  };

  // ── Upload Phase ──────────────────────────────────────────────────────────
  if (phase === 'upload') return (
    <div style={{ background: 'rgba(139,92,246,0.04)', border: '1px solid rgba(139,92,246,0.18)', borderRadius: 14, padding: 20 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <div style={{ width: 32, height: 32, borderRadius: 8, background: 'linear-gradient(135deg,#7c3aed,#a855f7)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Sparkles size={16} style={{ color: '#fff' }} />
        </div>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#e8e8e8' }}>Agentic Syllabus Uploader</div>
          <div style={{ fontSize: 11, color: 'rgba(232,232,232,0.4)' }}>
            PDF → AI scan → auto-import all subjects → chapters → RAG embeddings → SEO tags
          </div>
        </div>
      </div>

      {/* Pipeline steps diagram */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
        {[
          { icon: FileText,  label: 'Upload PDF'      },
          { icon: Brain,     label: 'AI Scans'        },
          { icon: BookOpen,  label: 'Builds Hierarchy' },
          { icon: Layers,    label: 'Chunks Content'  },
          { icon: Database,  label: 'Embeds RAG'      },
          { icon: Globe,     label: 'SEO Tags'        },
        ].map((s, i, arr) => {
          const Icon = s.icon;
          return (
            <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 8px', borderRadius: 6, background: 'rgba(139,92,246,0.1)', fontSize: 10, fontWeight: 600, color: '#c4b5fd' }}>
                <Icon size={10} />{s.label}
              </span>
              {i < arr.length - 1 && <ArrowRight size={10} style={{ color: 'rgba(255,255,255,0.2)' }} />}
            </span>
          );
        })}
      </div>

      {/* Drop zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        style={{
          border: `2px dashed ${dragging ? '#8b5cf6' : file ? '#10b981' : 'rgba(255,255,255,0.12)'}`,
          borderRadius: 10, padding: '24px 20px', textAlign: 'center', cursor: 'pointer',
          background: dragging ? 'rgba(139,92,246,0.08)' : file ? 'rgba(16,185,129,0.05)' : 'rgba(255,255,255,0.01)',
          transition: 'all 0.2s', marginBottom: 14,
        }}
      >
        <input ref={fileRef} type="file" accept=".pdf" style={{ display: 'none' }} onChange={e => handleFile(e.target.files[0])} />
        {file ? (
          <>
            <CheckCircle2 size={28} style={{ color: '#10b981', margin: '0 auto 8px' }} />
            <div style={{ fontSize: 13, fontWeight: 600, color: '#10b981' }}>{file.name}</div>
            <div style={{ fontSize: 11, color: 'rgba(232,232,232,0.35)', marginTop: 4 }}>
              {(file.size / 1024).toFixed(0)} KB · Click to change
            </div>
          </>
        ) : (
          <>
            <Upload size={28} style={{ color: 'rgba(255,255,255,0.25)', margin: '0 auto 8px' }} />
            <div style={{ fontSize: 13, fontWeight: 600, color: 'rgba(232,232,232,0.6)' }}>Drop syllabus PDF here</div>
            <div style={{ fontSize: 11, color: 'rgba(232,232,232,0.3)', marginTop: 4 }}>or click to browse · max 20 MB</div>
          </>
        )}
      </div>

      {/* Paper type selector */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'rgba(232,232,232,0.5)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Course / Paper Type
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {PAPER_TYPES.map(pt => (
            <button
              key={pt.value}
              onClick={() => setPaperType(pt.value)}
              style={{
                padding: '5px 11px', borderRadius: 7, fontSize: 11, fontWeight: 600, cursor: 'pointer',
                border: `1px solid ${paperType === pt.value ? '#8b5cf6' : 'rgba(255,255,255,0.1)'}`,
                background: paperType === pt.value ? 'rgba(139,92,246,0.2)' : 'rgba(255,255,255,0.03)',
                color: paperType === pt.value ? '#c4b5fd' : 'rgba(232,232,232,0.45)',
              }}
              title={pt.desc}
            >
              {pt.icon} {pt.label}
            </button>
          ))}
        </div>
      </div>

      <button
        onClick={startRun}
        disabled={!file}
        style={{
          width: '100%', padding: '10px 0', borderRadius: 9, border: 'none', cursor: file ? 'pointer' : 'not-allowed',
          background: file ? 'linear-gradient(135deg,#7c3aed,#a855f7)' : 'rgba(255,255,255,0.06)',
          color: file ? '#fff' : 'rgba(232,232,232,0.25)', fontWeight: 700, fontSize: 14,
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
        }}
      >
        <Zap size={15} /> Start Agentic Import
      </button>
    </div>
  );

  // ── Running / Done Phase ──────────────────────────────────────────────────
  return (
    <div style={{ background: 'rgba(6,6,14,0.9)', border: '1px solid rgba(139,92,246,0.2)', borderRadius: 14 }}>
      {/* Header bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        {phase === 'done'
          ? <CheckCircle2 size={16} style={{ color: '#10b981' }} />
          : <Loader2 size={16} className="animate-spin" style={{ color: '#8b5cf6' }} />
        }
        <span style={{ fontSize: 13, fontWeight: 700, color: '#e8e8e8', flex: 1 }}>
          {phase === 'done' ? '✅ Import Complete' : `Agentic Import Running — ${file?.name}`}
        </span>
        <button onClick={reset}
          style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid rgba(255,255,255,0.1)', background: 'rgba(255,255,255,0.04)', color: 'rgba(232,232,232,0.45)', fontSize: 11, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5 }}>
          <RefreshCw size={10} /> {phase === 'done' ? 'Import Another' : 'Cancel'}
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, minHeight: 360 }}>
        {/* Left: Subjects list */}
        <div style={{ borderRight: '1px solid rgba(255,255,255,0.06)', padding: 14, overflowY: 'auto', maxHeight: 480 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'rgba(232,232,232,0.3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
            Subjects ({subjects.length}{scanTotal ? ` of ${scanTotal}` : ''})
          </div>
          {subjects.length === 0 && phase === 'running' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'rgba(232,232,232,0.35)', fontSize: 12 }}>
              <Loader2 size={14} className="animate-spin" /> Scanning PDF…
            </div>
          )}
          {subjects.map((s, i) => (
            <SubjectCard key={i} subj={s} isActive={i === activeSubjIdx && phase === 'running'} />
          ))}

          {/* Summary card when done */}
          {summary && (
            <div style={{ marginTop: 10, padding: '12px 14px', borderRadius: 10, background: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#34d399', marginBottom: 8 }}>🎉 Import Summary</div>
              {[
                { label: 'Subjects',   value: summary.total_subjects  },
                { label: 'Chapters',   value: summary.total_chapters  },
                { label: 'RAG Chunks', value: summary.total_chunks    },
                { label: 'Embeddings', value: summary.total_embedded  },
              ].map(r => (
                <div key={r.label} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span style={{ fontSize: 11, color: 'rgba(232,232,232,0.5)' }}>{r.label}</span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#e8e8e8' }}>{r.value}</span>
                </div>
              ))}
              <div style={{ marginTop: 8, fontSize: 10, color: 'rgba(232,232,232,0.3)' }}>
                AI chat RAG and SEO tags active immediately
              </div>
            </div>
          )}
        </div>

        {/* Right: Live log */}
        <div style={{ padding: 14, display: 'flex', flexDirection: 'column', maxHeight: 480 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'rgba(232,232,232,0.3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
            Live Log
          </div>
          <div style={{ flex: 1, overflowY: 'auto', fontFamily: 'monospace', fontSize: 10.5, lineHeight: 1.6 }}>
            {log.map((l, i) => (
              <div key={i} style={{ color: l.color, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{l.msg}</div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      </div>
    </div>
  );
}

// Helper: update step status for a chapter by title
function updateChapterStep(setSubjects, chapterTitle, stepKey, chunks) {
  setSubjects(prev => {
    const copy = [...prev];
    for (let si = 0; si < copy.length; si++) {
      const chs = copy[si].chapters || [];
      const ci  = chs.findIndex(c => c.title === chapterTitle);
      if (ci >= 0) {
        const newChs = [...chs];
        newChs[ci] = {
          ...newChs[ci],
          steps: { ...(newChs[ci].steps || {}), [stepKey]: true },
          ...(chunks != null ? { chunks } : {}),
        };
        copy[si] = { ...copy[si], chapters: newChs };
        break;
      }
    }
    return copy;
  });
}
