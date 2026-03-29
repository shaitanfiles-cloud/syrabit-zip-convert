import { useState, useRef, useEffect, useCallback } from 'react';
import { Upload, Trash2, Loader2, BookOpen, Calendar, X, ChevronDown, ImagePlus, FileImage, ZoomIn, ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { API_BASE } from '../../utils/api';

const PAPER_TYPES = [
  { value: 'major',  label: 'Major' },
  { value: 'minor',  label: 'Minor' },
  { value: 'sec',    label: 'SEC'   },
  { value: 'aec',    label: 'AEC'   },
  { value: 'mdc',    label: 'MDC'   },
  { value: 'vac',    label: 'VAC'   },
  { value: 'ge',     label: 'GE'    },
  { value: 'cc',     label: 'CC'    },
];

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 10 }, (_, i) => CURRENT_YEAR - i);

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

  // Upload state
  const [files,       setFiles]       = useState([]);       // [{file, preview, id}]
  const [uploading,   setUploading]   = useState(false);
  const [dragging,    setDragging]    = useState(false);

  // List state
  const [pyqList,  setPyqList]  = useState([]);
  const [listLoad, setListLoad] = useState(true);
  const [lightbox, setLightbox] = useState(null);   // base64 url to show fullscreen

  const authCfg = { headers: { Authorization: `Bearer ${adminToken}` }, withCredentials: true };

  // ── Load hierarchy ────────────────────────────────────────────────────────
  useEffect(() => {
    axios.get(`${API_BASE}/content/boards`).then(r => setBoards(r.data || [])).catch(() => {});
    loadPyqList();
  }, []);

  // ── Pre-fill from hub context ─────────────────────────────────────────────
  useEffect(() => {
    if (!hubContext?.boardId) return;
    setSelectedBoard(hubContext.boardId);
  }, [hubContext?.boardId]);

  useEffect(() => {
    if (!hubContext?.classId) return;
    setSelectedClass(hubContext.classId);
  }, [hubContext?.classId]);

  useEffect(() => {
    if (!hubContext?.streamId) return;
    setSelectedStream(hubContext.streamId);
  }, [hubContext?.streamId]);

  useEffect(() => {
    if (!hubContext?.subjectId) return;
    setSelectedSubject(hubContext.subjectId);
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
      const r = await axios.get(`${API_BASE}/admin/pyq/list`, authCfg);
      setPyqList(r.data?.pyqs || []);
    } catch { setPyqList([]); }
    finally { setListLoad(false); }
  };

  // ── File handling ─────────────────────────────────────────────────────────
  const addFiles = useCallback((incoming) => {
    const accepted = [...incoming].filter(f =>
      f.type.startsWith('image/') || f.type === 'application/pdf'
    );
    if (!accepted.length) { toast.error('Only images (JPG/PNG/WEBP) or PDFs allowed'); return; }
    const entries = accepted.map(f => ({
      id: crypto.randomUUID(),
      file: f,
      preview: f.type.startsWith('image/') ? URL.createObjectURL(f) : null,
    }));
    setFiles(prev => [...prev, ...entries]);
  }, []);

  const onDrop = (e) => {
    e.preventDefault(); setDragging(false);
    addFiles(e.dataTransfer.files);
  };

  const removeFile = (id) => setFiles(prev => prev.filter(f => f.id !== id));

  // ── Upload ────────────────────────────────────────────────────────────────
  const handleUpload = async () => {
    if (!files.length) { toast.error('Add at least one image or PDF'); return; }
    if (!selectedSubject && !selectedBoard) { toast.error('Select at least a board'); return; }

    setUploading(true);
    try {
      const fd = new FormData();
      files.forEach(({ file }) => fd.append('files', file));
      fd.append('paper_type',   paperType);
      fd.append('exam_year',    examYear);
      fd.append('exam_title',   examTitle || `${paperType.toUpperCase()} ${examYear}`);
      if (selectedBoard)   fd.append('board_id',   selectedBoard);
      if (selectedClass)   fd.append('class_id',   selectedClass);
      if (selectedStream)  fd.append('stream_id',  selectedStream);
      if (selectedSubject) fd.append('subject_id', selectedSubject);

      await axios.post(`${API_BASE}/admin/pyq/upload`, fd, {
        ...authCfg,
        headers: { ...authCfg.headers, 'Content-Type': 'multipart/form-data' },
      });

      toast.success(`${files.length} PYQ file${files.length > 1 ? 's' : ''} uploaded`);
      setFiles([]);
      setExamTitle('');
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
      await axios.delete(`${API_BASE}/admin/pyq/${pyqId}`, authCfg);
      toast.success('Deleted');
      loadPyqList();
    } catch { toast.error('Delete failed'); }
  };

  // ── Select helpers ────────────────────────────────────────────────────────
  const selCls = 'w-full px-3 py-2 rounded-xl border border-white/10 bg-white/5 text-white text-sm focus:border-amber-500 outline-none transition-colors';

  return (
    <div className="space-y-6">

      {/* ── Upload Panel ──────────────────────────────────────────────────── */}
      <div className="rounded-xl border p-5 space-y-5"
        style={{ background: 'rgba(245,158,11,0.05)', borderColor: 'rgba(245,158,11,0.20)' }}>

        <div>
          <p className="text-sm font-semibold text-white flex items-center gap-2">
            <ImagePlus size={14} className="text-amber-400" /> Upload Previous Year Questions
          </p>
          <p className="text-xs mt-0.5 text-white/40">Upload scanned PYQ images or PDFs — stored in Supabase, linked to subject, year, and course type</p>
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
            <label className="text-[10px] text-white/40 uppercase tracking-wide block mb-1">Subject</label>
            <select className={selCls} value={selectedSubject} onChange={e => setSelectedSubject(e.target.value)} disabled={!subjects.length}>
              <option value="">{subjects.length ? 'Select subject…' : '—'}</option>
              {subjects.map(s => <option key={s.id} value={s.id}>{s.name || s.title}</option>)}
            </select>
          </div>
        </div>

        {/* Year + Title row */}
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
              placeholder={`e.g. Mid-sem ${examYear}, End-sem ${examYear}`} />
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
          <p className="text-[11px] text-white/25 mt-1">JPG · PNG · WEBP · PDF — multiple files allowed · up to 50 MB each</p>
        </div>

        {/* Staged file previews */}
        {files.length > 0 && (
          <div className="space-y-2">
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
              {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              {uploading ? 'Uploading…' : `Upload ${files.length} File${files.length > 1 ? 's' : ''}`}
            </button>
          </div>
        )}

        {/* Quick action when subject selected */}
        {selectedSubject && onNavigate && (
          <div className="flex items-center gap-2 pt-1">
            <span className="text-[10px] text-white/25 font-semibold uppercase tracking-widest">Next step:</span>
            <button
              onClick={() => onNavigate('editor')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition hover:opacity-90"
              style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.30)' }}>
              Write Content →
            </button>
            <button
              onClick={() => onNavigate('studio')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition hover:opacity-90"
              style={{ background: 'rgba(244,63,94,0.15)', color: '#fda4af', border: '1px solid rgba(244,63,94,0.30)' }}>
              Generate AI Content →
            </button>
          </div>
        )}
      </div>

      {/* ── Uploaded PYQs list ─────────────────────────────────────────────── */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-white/80">Uploaded PYQs</p>
          <button onClick={loadPyqList} className="text-[10px] text-white/30 hover:text-white/60 transition-colors">↻ Refresh</button>
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
              <PYQCard key={pyq.id} pyq={pyq} onDelete={handleDelete} onPreview={setLightbox} />
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

function PYQCard({ pyq, onDelete, onPreview }) {
  const [expanded, setExpanded] = useState(false);

  // Resolve image URL — prefer Supabase URL, fall back to data_url (legacy)
  const thumbUrl = pyq.pages?.[0]?.file_url || pyq.pages?.[0]?.data_url || null;
  const isPdf    = pyq.is_pdf || pyq.mime_type === 'application/pdf';
  const fileUrl  = pyq.file_url || '';
  const hasFile  = Boolean(fileUrl);

  return (
    <div className="rounded-xl border overflow-hidden transition-all"
      style={{ background: 'rgba(255,255,255,0.03)', borderColor: 'rgba(255,255,255,0.08)' }}>

      {/* Header row */}
      <div className="flex items-center gap-3 px-4 py-3">
        {/* Thumbnail / PDF icon */}
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

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <p className="text-sm font-semibold text-white/85 truncate">{pyq.exam_title}</p>
            {isPdf && hasFile && (
              <a href={fileUrl} target="_blank" rel="noopener noreferrer"
                className="flex-shrink-0 text-white/25 hover:text-amber-400 transition-colors" title="Open PDF">
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
            {pyq.pages?.length > 0 && (
              <span className="text-[10px] text-white/30">{pyq.pages.length} page{pyq.pages.length > 1 ? 's' : ''}</span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 flex-shrink-0">
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

      {/* Expanded page thumbnails (images only) */}
      {expanded && pyq.pages?.length > 1 && (
        <div className="px-4 pb-4 border-t border-white/6 pt-3">
          <p className="text-[10px] text-white/35 mb-2 uppercase tracking-wide">Pages</p>
          <div className="grid grid-cols-4 gap-2">
            {pyq.pages.map((pg, i) => {
              const pgUrl = pg.file_url || pg.data_url || '';
              return (
                <div key={i} className="relative group rounded-lg overflow-hidden border border-white/10 cursor-pointer"
                  onClick={() => pgUrl && onPreview(pgUrl)}>
                  <img src={pgUrl} alt={`Page ${i + 1}`} className="w-full h-20 object-cover" />
                  <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center">
                    <ZoomIn size={14} className="text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                  <div className="absolute bottom-0 inset-x-0 bg-black/50 px-1 py-0.5">
                    <p className="text-[8px] text-white/50">pg {i + 1}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
