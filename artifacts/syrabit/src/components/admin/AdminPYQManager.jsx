import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Upload, Trash2, Loader2, BookOpen, Calendar, X, ChevronDown,
  ImagePlus, FileImage, ZoomIn, ExternalLink, Globe, CheckCircle2,
  AlertCircle, Cpu, Zap, RefreshCw, Brain, Layers,
} from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { API_BASE } from '../../utils/api';

const PAPER_TYPES = [
  { value: 'major', label: 'Major' },
  { value: 'minor', label: 'Minor' },
  { value: 'sec',   label: 'SEC'   },
  { value: 'aec',   label: 'AEC'   },
  { value: 'mdc',   label: 'MDC'   },
  { value: 'vac',   label: 'VAC'   },
  { value: 'ge',    label: 'GE'    },
  { value: 'cc',    label: 'CC'    },
];

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 10 }, (_, i) => CURRENT_YEAR - i);

// ── Pipeline step definitions ─────────────────────────────────────────────────
const STEPS = [
  { key: 'upload',    label: 'Uploaded',        icon: Upload    },
  { key: 'ocr',       label: 'OCR & Extract',   icon: Cpu       },
  { key: 'classify',  label: 'AI Classify',     icon: Brain     },
  { key: 'done',      label: 'Done',            icon: CheckCircle2 },
];

// Map processing_status from backend → UI step
function statusToStep(s) {
  if (!s || s === 'uploaded')         return { step: 0, done: 1, active: false };
  if (s === 'ocr_running')            return { step: 1, done: 1, active: true  };
  if (s === 'ocr_done')               return { step: 2, done: 2, active: false };
  if (s === 'classifying')            return { step: 2, done: 2, active: true  };
  if (s === 'done')                   return { step: 3, done: 4, active: false };
  if (s.endsWith('_error') || s === 'fetch_error') return { step: -1, done: 0, active: false };
  return { step: 0, done: 1, active: false };
}

export default function AdminPYQManager({ adminToken, hubContext, onNavigate }) {
  const fileRef = useRef(null);

  // Hierarchy selectors
  const [boards,   setBoards]   = useState([]);
  const [classes,  setClasses]  = useState([]);
  const [streams,  setStreams]  = useState([]);
  const [subjects, setSubjects] = useState([]);

  const [selectedBoard,   setSelectedBoard]   = useState('');
  const [selectedClass,   setSelectedClass]   = useState('');
  const [selectedStream,  setSelectedStream]  = useState('');
  const [selectedSubject, setSelectedSubject] = useState('');
  const [paperType,       setPaperType]       = useState('major');
  const [examYear,        setExamYear]        = useState(CURRENT_YEAR);
  const [examTitle,       setExamTitle]       = useState('');

  // Staged files (not yet uploaded)
  const [files,     setFiles]     = useState([]);
  const [dragging,  setDragging]  = useState(false);
  const [uploading, setUploading] = useState(false);

  // Pipeline items — each has {id, filename, is_pdf, subject_id, processing_status, seo_url, question_count, classify_result, error_msg}
  const [pipelineItems, setPipelineItems] = useState([]);

  // Legacy list (already uploaded, not in pipeline)
  const [pyqList,  setPyqList]  = useState([]);
  const [listLoad, setListLoad] = useState(true);
  const [lightbox, setLightbox] = useState(null);

  // Ref to always have fresh adminToken for intervals
  const tokenRef = useRef(adminToken);
  useEffect(() => { tokenRef.current = adminToken; }, [adminToken]);

  const authCfg = useCallback(() => ({
    headers: { Authorization: `Bearer ${tokenRef.current}` },
    withCredentials: true,
  }), []);

  // ── Session keep-alive: ping every 30s while any pipeline item is processing ─
  useEffect(() => {
    const anyActive = pipelineItems.some(
      it => it.processing_status === 'ocr_running' || it.processing_status === 'classifying'
    );
    if (!anyActive) return;
    const id = setInterval(() => {
      axios.get(`${API_BASE}/admin/verify`, authCfg()).catch(() => {});
    }, 30000);
    return () => clearInterval(id);
  }, [pipelineItems, authCfg]);

  // ── Load hierarchy ────────────────────────────────────────────────────────
  useEffect(() => {
    axios.get(`${API_BASE}/content/boards`).then(r => setBoards(r.data || [])).catch(() => {});
    loadPyqList();
  }, []);

  useEffect(() => {
    if (hubContext?.boardId)   setSelectedBoard(hubContext.boardId);
  }, [hubContext?.boardId]);
  useEffect(() => {
    if (hubContext?.classId)   setSelectedClass(hubContext.classId);
  }, [hubContext?.classId]);
  useEffect(() => {
    if (hubContext?.streamId)  setSelectedStream(hubContext.streamId);
  }, [hubContext?.streamId]);
  useEffect(() => {
    if (hubContext?.subjectId) setSelectedSubject(hubContext.subjectId);
  }, [hubContext?.subjectId]);

  useEffect(() => {
    setClasses([]); setStreams([]); setSubjects([]);
    setSelectedClass(''); setSelectedStream(''); setSelectedSubject('');
    if (!selectedBoard) return;
    axios.get(`${API_BASE}/content/classes?board_id=${selectedBoard}`).then(r => setClasses(r.data || [])).catch(() => {});
  }, [selectedBoard]);

  useEffect(() => {
    setStreams([]); setSubjects([]);
    setSelectedStream(''); setSelectedSubject('');
    if (!selectedClass) return;
    axios.get(`${API_BASE}/content/streams?class_id=${selectedClass}`).then(r => setStreams(r.data || [])).catch(() => {});
  }, [selectedClass]);

  useEffect(() => {
    setSubjects([]); setSelectedSubject('');
    if (!selectedStream) return;
    axios.get(`${API_BASE}/content/subjects?stream_id=${selectedStream}`).then(r => setSubjects(r.data || [])).catch(() => {});
  }, [selectedStream]);

  const loadPyqList = async () => {
    setListLoad(true);
    try {
      const r = await axios.get(`${API_BASE}/admin/pyq/list`, authCfg());
      setPyqList(r.data?.pyqs || []);
    } catch { setPyqList([]); }
    finally { setListLoad(false); }
  };

  // ── File staging ──────────────────────────────────────────────────────────
  const addFiles = useCallback((incoming) => {
    const accepted = [...incoming].filter(f =>
      f.type.startsWith('image/') || f.type === 'application/pdf'
    );
    if (!accepted.length) { toast.error('Only images (JPG/PNG/WEBP) or PDFs allowed'); return; }
    setFiles(prev => [
      ...prev,
      ...accepted.map(f => ({
        id: crypto.randomUUID(),
        file: f,
        preview: f.type.startsWith('image/') ? URL.createObjectURL(f) : null,
      })),
    ]);
  }, []);

  const onDrop = (e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); };
  const removeFile = (id) => setFiles(prev => prev.filter(f => f.id !== id));

  // ── Update a single pipeline item ─────────────────────────────────────────
  const updateItem = (id, patch) =>
    setPipelineItems(prev => prev.map(it => it.id === id ? { ...it, ...patch } : it));

  // ── Agentic OCR step ──────────────────────────────────────────────────────
  const runAgenticOCR = useCallback(async (item) => {
    updateItem(item.id, { processing_status: 'ocr_running' });
    // Refresh session before long operation
    await axios.get(`${API_BASE}/admin/verify`, authCfg()).catch(() => {});
    try {
      const res = await axios.post(
        `${API_BASE}/admin/pyq/agentic-process`,
        { pyq_id: item.id },
        { ...authCfg(), timeout: 300000 },
      );
      const { seo_url, question_count, subject_id } = res.data;
      updateItem(item.id, {
        processing_status: 'ocr_done',
        seo_url,
        question_count,
      });
      // Auto-classify if subject is linked
      const sid = subject_id || item.subject_id;
      if (sid) {
        runClassify(item.id, sid);
      }
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'OCR failed';
      updateItem(item.id, { processing_status: 'ocr_error', error_msg: msg });
      toast.error(`OCR failed for ${item.filename}: ${msg}`);
    }
  }, [authCfg]);

  // ── Agentic classify step ─────────────────────────────────────────────────
  const runClassify = useCallback(async (itemId, subjectId) => {
    updateItem(itemId, { processing_status: 'classifying' });
    await axios.get(`${API_BASE}/admin/verify`, authCfg()).catch(() => {});
    try {
      const res = await axios.post(
        `${API_BASE}/admin/subjects/${subjectId}/generate-pyqs-bulk`,
        {},
        { ...authCfg(), timeout: 300000 },
      );
      const { generated, total_pyqs, message } = res.data;
      updateItem(itemId, {
        processing_status: 'done',
        classify_result: { generated, total_pyqs, message },
      });
      toast.success(`PYQ pipeline complete — ${generated || 0} chapters classified`);
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Classify failed';
      updateItem(itemId, { processing_status: 'classify_error', error_msg: msg });
      toast.error(`Classify failed: ${msg}`);
    }
  }, [authCfg]);

  // ── Upload + auto-trigger pipeline ────────────────────────────────────────
  const handleUpload = async () => {
    if (!files.length) { toast.error('Add at least one file'); return; }
    if (!selectedBoard) { toast.error('Select at least a board'); return; }

    setUploading(true);
    // Refresh session before upload
    await axios.get(`${API_BASE}/admin/verify`, authCfg()).catch(() => {});

    try {
      const fd = new FormData();
      files.forEach(({ file }) => fd.append('files', file));
      fd.append('paper_type', paperType);
      fd.append('exam_year',  examYear);
      fd.append('exam_title', examTitle || `${paperType.toUpperCase()} ${examYear}`);
      if (selectedBoard)   fd.append('board_id',   selectedBoard);
      if (selectedClass)   fd.append('class_id',   selectedClass);
      if (selectedStream)  fd.append('stream_id',  selectedStream);
      if (selectedSubject) fd.append('subject_id', selectedSubject);

      const res = await axios.post(`${API_BASE}/admin/pyq/upload`, fd, {
        ...authCfg(),
        headers: { ...authCfg().headers, 'Content-Type': 'multipart/form-data' },
        timeout: 120000,
      });

      const uploadedIds = res.data?.ids || [];
      toast.success(`${uploadedIds.length} file${uploadedIds.length > 1 ? 's' : ''} uploaded — starting AI pipeline…`);

      // Build pipeline items from uploaded IDs mapped to staged files
      const newItems = files.map((f, idx) => ({
        id:                uploadedIds[idx] || crypto.randomUUID(),
        filename:          f.file.name,
        is_pdf:            f.file.type === 'application/pdf' || f.file.name?.toLowerCase().endsWith('.pdf'),
        preview:           f.preview,
        subject_id:        selectedSubject || '',
        processing_status: 'uploaded',
        seo_url:           null,
        question_count:    null,
        classify_result:   null,
        error_msg:         null,
      }));

      setPipelineItems(prev => [...newItems, ...prev]);
      setFiles([]);
      setExamTitle('');

      // Auto-trigger agentic OCR for each PDF
      newItems.forEach(item => {
        if (item.is_pdf) {
          setTimeout(() => runAgenticOCR(item), 300);
        }
      });

      loadPyqList();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (pyqId) => {
    if (!confirm('Delete this PYQ?')) return;
    try {
      await axios.delete(`${API_BASE}/admin/pyq/${pyqId}`, authCfg());
      toast.success('Deleted');
      setPipelineItems(prev => prev.filter(it => it.id !== pyqId));
      loadPyqList();
    } catch { toast.error('Delete failed'); }
  };

  const selCls = 'w-full px-3 py-2 rounded-xl border border-white/10 bg-white/5 text-white text-sm focus:border-amber-500 outline-none transition-colors';

  const anyProcessing = pipelineItems.some(
    it => it.processing_status === 'ocr_running' || it.processing_status === 'classifying'
  );

  return (
    <div className="space-y-6">

      {/* ── Upload Panel ──────────────────────────────────────────────────── */}
      <div className="rounded-xl border p-5 space-y-5"
        style={{ background: 'rgba(245,158,11,0.05)', borderColor: 'rgba(245,158,11,0.20)' }}>

        <div className="flex items-center gap-2">
          <Zap size={14} className="text-amber-400" />
          <div>
            <p className="text-sm font-semibold text-white">Agentic PYQ Uploader</p>
            <p className="text-xs text-white/40 mt-0.5">Upload PDFs → AI auto-extracts questions → AI classifies per chapter</p>
          </div>
          {anyProcessing && (
            <div className="ml-auto flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold"
              style={{ background: 'rgba(99,102,241,0.15)', color: '#a5b4fc', border: '1px solid rgba(99,102,241,0.30)' }}>
              <Loader2 size={11} className="animate-spin" />
              Pipeline running…
            </div>
          )}
        </div>

        {/* Hierarchy selectors */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-white/40 uppercase tracking-wide block mb-1">Board</label>
            <select className={selCls} value={selectedBoard} onChange={e => setSelectedBoard(e.target.value)}>
              <option value="">Select board…</option>
              {boards.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-white/40 uppercase tracking-wide block mb-1">Semester / Class</label>
            <select className={selCls} value={selectedClass} onChange={e => setSelectedClass(e.target.value)} disabled={!classes.length}>
              <option value="">{classes.length ? 'Select semester…' : '—'}</option>
              {classes.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-white/40 uppercase tracking-wide block mb-1">Course Type</label>
            <select className={selCls} value={selectedStream} onChange={e => setSelectedStream(e.target.value)} disabled={!streams.length}>
              <option value="">{streams.length ? 'Select course type…' : '—'}</option>
              {streams.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-white/40 uppercase tracking-wide block mb-1">
              Subject <span className="text-amber-400/60 normal-case">(links classify step)</span>
            </label>
            <select className={selCls} value={selectedSubject} onChange={e => setSelectedSubject(e.target.value)} disabled={!subjects.length}>
              <option value="">{subjects.length ? 'Select subject…' : '—'}</option>
              {subjects.map(s => <option key={s.id} value={s.id}>{s.name || s.title}</option>)}
            </select>
          </div>
        </div>

        {/* Year + Title */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-white/40 uppercase tracking-wide block mb-1">Exam Year <span className="text-amber-400">*</span></label>
            <select className={selCls} value={examYear} onChange={e => setExamYear(parseInt(e.target.value))}>
              {YEARS.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          <div>
            <label className="text-[10px] text-white/40 uppercase tracking-wide block mb-1">Exam Title (optional)</label>
            <input className={selCls} value={examTitle} onChange={e => setExamTitle(e.target.value)}
              placeholder={`e.g. Mid-sem ${examYear}`} />
          </div>
        </div>

        {/* Paper type pills */}
        <div>
          <label className="text-[10px] text-white/40 uppercase tracking-wide block mb-1.5">Paper Type</label>
          <div className="flex flex-wrap gap-1.5">
            {PAPER_TYPES.map(pt => (
              <button key={pt.value} onClick={() => setPaperType(pt.value)}
                className="px-3 py-1 rounded-lg text-xs font-semibold border transition-all"
                style={paperType === pt.value ? {
                  background: 'rgba(245,158,11,0.25)', borderColor: 'rgba(245,158,11,0.60)', color: '#fcd34d',
                } : {
                  background: 'rgba(255,255,255,0.04)', borderColor: 'rgba(255,255,255,0.10)', color: 'rgba(255,255,255,0.45)',
                }}>
                {pt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Drop zone */}
        <div
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => fileRef.current?.click()}
          className="relative rounded-xl border-2 border-dashed cursor-pointer transition-all p-6 text-center"
          style={{
            borderColor: dragging ? 'rgba(245,158,11,0.7)' : 'rgba(255,255,255,0.12)',
            background:  dragging ? 'rgba(245,158,11,0.08)' : 'rgba(255,255,255,0.02)',
          }}>
          <input ref={fileRef} type="file" multiple accept="image/*,.pdf" className="hidden"
            onChange={e => addFiles(e.target.files)} />
          <Upload size={22} className="mx-auto mb-2 text-white/30" />
          <p className="text-sm text-white/50">Drop PYQ images or PDFs here, or <span className="text-amber-400">click to browse</span></p>
          <p className="text-[11px] text-white/25 mt-1">JPG · PNG · WEBP · PDF — multiple files · up to 50 MB each</p>
        </div>

        {/* Staged file previews */}
        {files.length > 0 && (
          <div className="space-y-3">
            <p className="text-[10px] text-white/40 uppercase tracking-wide">{files.length} file{files.length > 1 ? 's' : ''} staged</p>
            <div className="grid grid-cols-3 gap-2">
              {files.map(({ id, file, preview }) => (
                <div key={id} className="relative group rounded-lg overflow-hidden border border-white/10"
                  style={{ background: 'rgba(255,255,255,0.04)' }}>
                  {preview ? (
                    <img src={preview} alt={file.name} className="w-full h-24 object-cover" />
                  ) : (
                    <div className="h-24 flex flex-col items-center justify-center gap-1">
                      <FileImage size={20} className="text-amber-400/60" />
                      <p className="text-[9px] text-white/30 text-center px-1 truncate w-full">{file.name}</p>
                    </div>
                  )}
                  <button onClick={e => { e.stopPropagation(); removeFile(id); }}
                    className="absolute top-1 right-1 bg-black/60 rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <X size={10} className="text-red-400" />
                  </button>
                  <div className="absolute bottom-0 inset-x-0 px-1.5 py-1 bg-black/50">
                    <p className="text-[9px] text-white/50 truncate">{file.name}</p>
                  </div>
                </div>
              ))}
            </div>

            <button onClick={handleUpload} disabled={uploading}
              className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-semibold transition-all disabled:opacity-40"
              style={{ background: 'rgba(245,158,11,0.20)', border: '1px solid rgba(245,158,11,0.40)', color: '#fcd34d' }}>
              {uploading ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
              {uploading ? 'Uploading…' : `Upload & Start Pipeline (${files.length} file${files.length > 1 ? 's' : ''})`}
            </button>
          </div>
        )}

        {/* Next steps */}
        {selectedSubject && onNavigate && (
          <div className="flex items-center gap-2 pt-1">
            <span className="text-[10px] text-white/25 font-semibold uppercase tracking-widest">Also:</span>
            <button onClick={() => onNavigate('editor')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition hover:opacity-90"
              style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.30)' }}>
              Write Content →
            </button>
            <button onClick={() => onNavigate('editor')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition hover:opacity-90"
              style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.30)' }}>
              Content Editor →
            </button>
          </div>
        )}
      </div>

      {/* ── Active Pipeline Panel ─────────────────────────────────────────── */}
      {pipelineItems.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-white/80 flex items-center gap-2">
              <Layers size={13} className="text-indigo-400" /> Active Pipeline
            </p>
            <button onClick={() => setPipelineItems([])}
              className="text-[10px] text-white/25 hover:text-white/50 transition-colors">
              Clear
            </button>
          </div>
          <div className="space-y-2">
            {pipelineItems.map(item => (
              <PipelineCard
                key={item.id}
                item={item}
                onRetryOCR={() => runAgenticOCR(item)}
                onRetryClassify={() => item.subject_id && runClassify(item.id, item.subject_id)}
                onDelete={() => handleDelete(item.id)}
                onPreview={setLightbox}
              />
            ))}
          </div>
        </div>
      )}

      {/* ── Existing PYQs list ────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-white/80">Uploaded PYQs</p>
          <button onClick={loadPyqList} className="text-[10px] text-white/30 hover:text-white/60 transition-colors flex items-center gap-1">
            <RefreshCw size={10} /> Refresh
          </button>
        </div>

        {listLoad ? (
          <div className="flex items-center gap-2 py-6 justify-center text-white/30">
            <Loader2 size={14} className="animate-spin" /><span className="text-xs">Loading…</span>
          </div>
        ) : pyqList.length === 0 ? (
          <div className="rounded-xl border border-white/8 py-10 text-center"
            style={{ background: 'rgba(255,255,255,0.02)' }}>
            <BookOpen size={22} className="mx-auto mb-2 text-white/15" />
            <p className="text-xs text-white/30">No PYQs uploaded yet</p>
          </div>
        ) : (
          <div className="space-y-2">
            {pyqList.map(pyq => (
              <LegacyPYQCard
                key={pyq.id}
                pyq={pyq}
                onDelete={handleDelete}
                onPreview={setLightbox}
                onRunPipeline={(id) => {
                  const item = {
                    id, filename: pyq.filename || pyq.exam_title,
                    is_pdf: pyq.is_pdf, subject_id: pyq.subject_id || '',
                    processing_status: pyq.processing_status || 'uploaded',
                    seo_url: pyq.seo_url || null,
                    question_count: pyq.question_count || null,
                    classify_result: null, error_msg: null,
                  };
                  setPipelineItems(prev => {
                    if (prev.find(p => p.id === id)) return prev;
                    return [item, ...prev];
                  });
                  if (pyq.is_pdf) runAgenticOCR(item);
                }}
                authCfg={authCfg}
              />
            ))}
          </div>
        )}
      </div>

      {/* Lightbox */}
      {lightbox && (
        <div className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-4"
          onClick={() => setLightbox(null)}>
          <button className="absolute top-4 right-4 text-white/60 hover:text-white">
            <X size={24} />
          </button>
          <img src={lightbox} alt="PYQ Preview"
            className="max-w-full max-h-full object-contain rounded-lg"
            onClick={e => e.stopPropagation()} />
        </div>
      )}
    </div>
  );
}

// ── Pipeline Progress Card ─────────────────────────────────────────────────
function PipelineCard({ item, onRetryOCR, onRetryClassify, onDelete, onPreview }) {
  const { step, done, active } = statusToStep(item.processing_status);
  const isError = item.processing_status?.endsWith('_error') || item.processing_status === 'fetch_error';
  const isDone  = item.processing_status === 'done';

  return (
    <div className="rounded-xl border overflow-hidden transition-all"
      style={{
        background: isDone
          ? 'rgba(16,185,129,0.05)'
          : isError
            ? 'rgba(239,68,68,0.05)'
            : 'rgba(99,102,241,0.05)',
        borderColor: isDone
          ? 'rgba(16,185,129,0.20)'
          : isError
            ? 'rgba(239,68,68,0.20)'
            : 'rgba(99,102,241,0.20)',
      }}>

      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3">
        <div className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center"
          style={{
            background: isDone ? 'rgba(16,185,129,0.15)' : isError ? 'rgba(239,68,68,0.10)' : 'rgba(99,102,241,0.12)',
          }}>
          {isDone ? <CheckCircle2 size={14} className="text-emerald-400" />
           : isError ? <AlertCircle size={14} className="text-red-400" />
           : item.is_pdf ? <FileImage size={14} className="text-indigo-400" />
           : <ImagePlus size={14} className="text-amber-400" />}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-white/85 truncate">{item.filename}</p>
          <p className="text-[10px] mt-0.5"
            style={{ color: isDone ? '#6ee7b7' : isError ? '#fca5a5' : '#a5b4fc' }}>
            {isError ? (item.error_msg || 'Processing failed') : statusLabel(item.processing_status)}
          </p>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {item.seo_url && (
            <a href={item.seo_url} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold transition-all"
              style={{ background: 'rgba(245,158,11,0.15)', color: '#fbbf24', border: '1px solid rgba(245,158,11,0.25)' }}>
              <Globe size={10} /> SEO Page
            </a>
          )}
          {isError && item.is_pdf && (
            <button onClick={onRetryOCR}
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold"
              style={{ background: 'rgba(99,102,241,0.15)', color: '#a5b4fc', border: '1px solid rgba(99,102,241,0.25)' }}>
              <RefreshCw size={10} /> Retry
            </button>
          )}
          {item.processing_status === 'ocr_done' && item.subject_id && (
            <button onClick={onRetryClassify}
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold"
              style={{ background: 'rgba(16,185,129,0.12)', color: '#6ee7b7', border: '1px solid rgba(16,185,129,0.25)' }}>
              <Brain size={10} /> Classify
            </button>
          )}
          <button onClick={onDelete}
            className="p-1 rounded-lg text-red-400/30 hover:text-red-400 transition-colors">
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {/* Step progress bar */}
      {item.is_pdf && (
        <div className="px-4 pb-3">
          <div className="flex items-center gap-0">
            {STEPS.map((s, idx) => {
              const isStepDone   = done > idx;
              const isStepActive = active && idx === step;
              const isStepError  = isError && idx === step;
              return (
                <div key={s.key} className="flex items-center flex-1 min-w-0">
                  <div className="flex flex-col items-center gap-1 flex-shrink-0">
                    <div className="w-6 h-6 rounded-full flex items-center justify-center transition-all"
                      style={{
                        background: isStepError  ? 'rgba(239,68,68,0.25)'
                                  : isStepActive ? 'rgba(99,102,241,0.30)'
                                  : isStepDone   ? 'rgba(16,185,129,0.25)'
                                  :                'rgba(255,255,255,0.06)',
                        border: `1px solid ${isStepError  ? 'rgba(239,68,68,0.50)'
                                           : isStepActive ? 'rgba(99,102,241,0.60)'
                                           : isStepDone   ? 'rgba(16,185,129,0.50)'
                                           :                'rgba(255,255,255,0.12)'}`,
                      }}>
                      {isStepActive
                        ? <Loader2 size={10} className="animate-spin text-indigo-400" />
                        : isStepError
                          ? <AlertCircle size={10} className="text-red-400" />
                          : isStepDone
                            ? <CheckCircle2 size={10} className="text-emerald-400" />
                            : <s.icon size={10} className="text-white/25" />}
                    </div>
                    <span className="text-[8px] leading-none text-center whitespace-nowrap"
                      style={{
                        color: isStepError  ? '#fca5a5'
                             : isStepActive ? '#a5b4fc'
                             : isStepDone   ? '#6ee7b7'
                             :               'rgba(255,255,255,0.25)',
                      }}>
                      {s.label}
                    </span>
                  </div>
                  {idx < STEPS.length - 1 && (
                    <div className="flex-1 h-px mx-1 transition-all"
                      style={{ background: done > idx + 1 ? 'rgba(16,185,129,0.40)' : 'rgba(255,255,255,0.08)' }} />
                  )}
                </div>
              );
            })}
          </div>

          {/* Result stats */}
          {(item.question_count != null || item.classify_result) && (
            <div className="mt-2 flex items-center gap-3 flex-wrap">
              {item.question_count != null && (
                <span className="text-[10px] px-2 py-0.5 rounded-md"
                  style={{ background: 'rgba(245,158,11,0.10)', color: '#fbbf24' }}>
                  {item.question_count} questions extracted
                </span>
              )}
              {item.classify_result?.generated != null && (
                <span className="text-[10px] px-2 py-0.5 rounded-md"
                  style={{ background: 'rgba(16,185,129,0.10)', color: '#6ee7b7' }}>
                  {item.classify_result.generated} chapters classified
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function statusLabel(s) {
  const map = {
    uploaded:       'Queued for processing',
    ocr_running:    'Gemini OCR in progress…',
    ocr_done:       'OCR complete',
    classifying:    'AI classifying questions by chapter…',
    done:           'Pipeline complete ✓',
    fetch_error:    'Could not fetch PDF from storage',
    ocr_error:      'Gemini OCR failed',
    classify_error: 'Chapter classification failed',
  };
  return map[s] || s;
}

// ── Legacy PYQ card (existing uploads not in pipeline) ─────────────────────
function LegacyPYQCard({ pyq, onDelete, onPreview, onRunPipeline, authCfg }) {
  const [expanded, setExpanded] = useState(false);

  const thumbUrl = pyq.pages?.[0]?.file_url || pyq.pages?.[0]?.data_url || null;
  const isPdf    = pyq.is_pdf || pyq.mime_type === 'application/pdf';
  const fileUrl  = pyq.file_url || '';
  const hasFile  = Boolean(fileUrl);
  const alreadyDone = pyq.processing_status === 'done' || pyq.seo_url;

  return (
    <div className="rounded-xl border overflow-hidden transition-all"
      style={{ background: 'rgba(255,255,255,0.03)', borderColor: 'rgba(255,255,255,0.08)' }}>

      <div className="flex items-center gap-3 px-4 py-3">
        <div className="flex-shrink-0 w-10 h-10 rounded-lg overflow-hidden border border-white/10 flex items-center justify-center"
          style={{ background: isPdf ? 'rgba(239,68,68,0.08)' : 'rgba(245,158,11,0.08)' }}>
          {!isPdf && thumbUrl ? (
            <img src={thumbUrl} alt="" className="w-full h-full object-cover cursor-pointer"
              onClick={() => onPreview(thumbUrl)} />
          ) : isPdf ? (
            <a href={fileUrl} target="_blank" rel="noopener noreferrer" title="Open PDF">
              <FileImage size={16} className="text-red-400/70 hover:text-red-400 transition-colors" />
            </a>
          ) : (
            <FileImage size={16} className="text-amber-400/50" />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <p className="text-sm font-semibold text-white/85 truncate">{pyq.exam_title}</p>
            {isPdf && hasFile && (
              <a href={fileUrl} target="_blank" rel="noopener noreferrer"
                className="flex-shrink-0 text-white/25 hover:text-amber-400 transition-colors">
                <ExternalLink size={11} />
              </a>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            {pyq.subject_name && <span className="text-[10px] text-white/40">{pyq.subject_name}</span>}
            {pyq.board_name  && <span className="text-[10px] text-white/30">{pyq.board_name}</span>}
            <span className="text-[10px] px-1.5 py-0.5 rounded-md font-semibold uppercase"
              style={{ background: 'rgba(245,158,11,0.15)', color: '#fbbf24' }}>
              {pyq.paper_type}
            </span>
            <span className="text-[10px] text-white/35 flex items-center gap-0.5">
              <Calendar size={9} /> {pyq.exam_year}
            </span>
            <span className="text-[10px] px-1 rounded font-mono"
              style={{ background: isPdf ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.10)',
                       color: isPdf ? '#f87171' : '#fbbf24' }}>
              {isPdf ? 'PDF' : 'IMG'}
            </span>
            {pyq.storage === 'supabase' && (
              <span className="text-[9px] text-emerald-400/50">☁ Supabase</span>
            )}
            {alreadyDone && (
              <span className="text-[9px] text-emerald-400/60 flex items-center gap-0.5">
                <CheckCircle2 size={8} /> Processed
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1 flex-shrink-0">
          {isPdf && hasFile && !alreadyDone && (
            <button
              onClick={() => onRunPipeline(pyq.id)}
              title="Run Agentic Pipeline"
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold transition-all"
              style={{ background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.30)', color: '#a5b4fc' }}>
              <Zap size={11} /> Run Pipeline
            </button>
          )}
          {pyq.seo_url && (
            <a href={pyq.seo_url} target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold"
              style={{ background: 'rgba(245,158,11,0.10)', color: '#fbbf24', border: '1px solid rgba(245,158,11,0.20)' }}>
              <Globe size={10} /> SEO
            </a>
          )}
          {pyq.pages?.length > 1 && (
            <button onClick={() => setExpanded(p => !p)}
              className="p-1.5 rounded-lg text-white/30 hover:text-white/70 transition-colors">
              <ChevronDown size={14} className={`transition-transform ${expanded ? 'rotate-180' : ''}`} />
            </button>
          )}
          <button onClick={() => onDelete(pyq.id)}
            className="p-1.5 rounded-lg text-red-400/30 hover:text-red-400 transition-colors">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {expanded && pyq.pages?.length > 1 && (
        <div className="px-4 pb-3 grid grid-cols-4 gap-2">
          {pyq.pages.map((pg, i) => (
            <div key={i} className="rounded-lg overflow-hidden border border-white/8 cursor-pointer"
              onClick={() => onPreview(pg.file_url || pg.data_url)}>
              <img src={pg.file_url || pg.data_url} alt={`Page ${i + 1}`}
                className="w-full h-16 object-cover" />
              <p className="text-[8px] text-center text-white/25 py-0.5">p.{i + 1}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
