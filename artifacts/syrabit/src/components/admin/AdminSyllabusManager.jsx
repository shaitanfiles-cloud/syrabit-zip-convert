import { useState, useEffect, useCallback, useRef } from 'react';
import { Save, Trash2, Plus, Loader2, CheckCircle, BookOpen, GitBranch, Info, Globe, ExternalLink, FileUp, Sparkles } from 'lucide-react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import axios from 'axios';
import { syllabusExtractPdf, syllabusConfirmImport, syllabusImportPdf } from '@/utils/api';

const API = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

function authHeaders(token) {
  const isRealJwt = token && token.split('.').length === 3;
  return { headers: isRealJwt ? { Authorization: `Bearer ${token}` } : {}, withCredentials: true };
}

const EMPTY_FORM = { content: '', chapters: [], topics: [], guidelines: '', geo_phrases: [] };

export default function AdminSyllabusManager({ adminToken, boards = [], classes = [], streams = [], subjects = [] }) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishedSlug, setPublishedSlug] = useState('');
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfResult, setPdfResult] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [expandedIdx, setExpandedIdx] = useState(null);
  const [paperType, setPaperType] = useState('major');
  const pdfRef = useRef(null);

  const PAPER_TYPES = [
    { value: 'major', label: 'Major', desc: 'Core discipline', icon: '🎯' },
    { value: 'minor', label: 'Minor', desc: 'Minor elective',  icon: '📘' },
    { value: 'mdc',   label: 'MDC',   desc: 'Multidisciplinary', icon: '🌐' },
    { value: 'vac',   label: 'VAC',   desc: 'Value-Added', icon: '✨' },
    { value: 'aec',   label: 'AEC',   desc: 'Ability Enhancement', icon: '🧠' },
    { value: 'sec',   label: 'SEC',   desc: 'Skill Enhancement', icon: '⚡' },
    { value: 'ge',    label: 'GE',    desc: 'Generic Elective', icon: '🔄' },
    { value: 'cc',    label: 'CC',    desc: 'Core Course', icon: '⭐' },
  ];

  const [nepStats, setNepStats] = useState(null);

  const [selectedBoardId, setSelectedBoardId] = useState('');
  const [selectedClassId, setSelectedClassId] = useState('');
  const [selectedStreamId, setSelectedStreamId] = useState('');
  const [selectedSubjectId, setSelectedSubjectId] = useState('');

  const [editingSyllabus, setEditingSyllabus] = useState(null);
  const [isFallback, setIsFallback] = useState(false);
  const [formData, setFormData] = useState(EMPTY_FORM);
  const [newChapter, setNewChapter] = useState('');
  const [newTopic, setNewTopic] = useState('');
  const [newGeoPhrase, setNewGeoPhrase] = useState('');

  useEffect(() => {
    axios.get(`${API}/admin/syllabus/nep-stats`, { withCredentials: true })
      .then(r => setNepStats(r.data))
      .catch(() => {});
  }, [pdfResult]);

  const filteredClasses = classes.filter(c => c.board_id === selectedBoardId);
  const filteredStreams = streams.filter(s => s.class_id === selectedClassId);
  const filteredSubjects = selectedStreamId
    ? subjects.filter(s => s.stream_id === selectedStreamId)
    : selectedClassId
    ? subjects
    : [];

  const selectedBoard = boards.find(b => b.id === selectedBoardId);
  const selectedClass = classes.find(c => c.id === selectedClassId);
  const selectedStream = streams.find(s => s.id === selectedStreamId);
  const selectedSubject = subjects.find(s => s.id === selectedSubjectId);

  const canLoad = selectedBoardId && selectedClassId;

  const syllabusEndpoint = useCallback(() => {
    if (selectedStreamId && selectedSubjectId) {
      return `${API}/syllabi/${selectedBoardId}/${selectedClassId}/${selectedStreamId}/${selectedSubjectId}`;
    }
    if (selectedStreamId) {
      return `${API}/syllabi/${selectedBoardId}/${selectedClassId}/${selectedStreamId}`;
    }
    return `${API}/syllabi/${selectedBoardId}/${selectedClassId}`;
  }, [selectedBoardId, selectedClassId, selectedStreamId, selectedSubjectId]);

  const adminSyllabusEndpoint = useCallback(() => {
    if (selectedStreamId && selectedSubjectId) {
      return `${API}/admin/syllabi/${selectedBoardId}/${selectedClassId}/${selectedStreamId}/${selectedSubjectId}`;
    }
    if (selectedStreamId) {
      return `${API}/admin/syllabi/${selectedBoardId}/${selectedClassId}/${selectedStreamId}`;
    }
    return `${API}/admin/syllabi/${selectedBoardId}/${selectedClassId}`;
  }, [selectedBoardId, selectedClassId, selectedStreamId, selectedSubjectId]);

  const fetchSyllabus = useCallback(async () => {
    if (!canLoad) return;
    try {
      setLoading(true);
      setIsFallback(false);
      const res = await axios.get(syllabusEndpoint(), { withCredentials: true });
      const data = res.data;
      if (data && data.content) {
        setEditingSyllabus(data);
        setIsFallback(!!data.is_fallback);
        setFormData({
          content: data.content || '',
          chapters: data.chapters || [],
          topics: data.topics || [],
          guidelines: data.guidelines || '',
          geo_phrases: data.geo_phrases || [],
        });
      } else {
        setEditingSyllabus(null);
        setFormData(EMPTY_FORM);
      }
    } catch (err) {
      console.error('Fetch syllabus error:', err);
      setEditingSyllabus(null);
      setFormData(EMPTY_FORM);
    } finally {
      setLoading(false);
    }
  }, [canLoad, syllabusEndpoint]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    setPublishedSlug('');
    if (canLoad) {
      fetchSyllabus();
    } else {
      setEditingSyllabus(null);
      setFormData(EMPTY_FORM);
      setIsFallback(false);
    }
  }, [selectedBoardId, selectedClassId, selectedStreamId, selectedSubjectId]);

  const saveSyllabus = async () => {
    if (!canLoad) {
      toast.error('Please select Board and Class');
      return;
    }
    if (!formData.content.trim()) {
      toast.error('Syllabus content is required');
      return;
    }
    try {
      setSaving(true);
      await axios.post(adminSyllabusEndpoint(), formData, authHeaders(adminToken));
      toast.success('Syllabus saved successfully!');
      fetchSyllabus();
    } catch (err) {
      console.error('Save error:', err);
      toast.error(err.response?.data?.detail || 'Failed to save syllabus');
    } finally {
      setSaving(false);
    }
  };

  const deleteSyllabus = async () => {
    if (!confirm('Delete this syllabus? This cannot be undone.')) return;
    try {
      setSaving(true);
      await axios.delete(adminSyllabusEndpoint(), authHeaders(adminToken));
      toast.success('Syllabus deleted');
      setEditingSyllabus(null);
      setFormData(EMPTY_FORM);
      setIsFallback(false);
      setPublishedSlug('');
    } catch (err) {
      console.error('Delete error:', err);
      toast.error(err.response?.data?.detail || 'Failed to delete syllabus');
    } finally {
      setSaving(false);
    }
  };

  const publishSyllabus = async () => {
    if (!selectedStreamId || !selectedSubjectId) {
      toast.error('Select a Stream and Subject to publish a syllabus card');
      return;
    }
    try {
      setPublishing(true);
      const res = await axios.post(
        `${API}/admin/syllabus/publish/${selectedBoardId}/${selectedClassId}/${selectedStreamId}/${selectedSubjectId}`,
        {},
        authHeaders(adminToken)
      );
      setPublishedSlug(res.data.seo_slug);
      toast.success('Syllabus card published to library!');
    } catch (err) {
      console.error('Publish error:', err);
      toast.error(err.response?.data?.detail || 'Failed to publish syllabus card');
    } finally {
      setPublishing(false);
    }
  };

  const handlePdfImport = async (file) => {
    if (!file) return;
    setPdfLoading(true);
    setPdfResult(null);
    setPreviewData(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('paper_type', paperType);
      if (selectedBoardId) fd.append('board_id', selectedBoardId);
      if (selectedClassId) fd.append('class_id', selectedClassId);
      if (selectedStreamId) fd.append('stream_id', selectedStreamId);
      const res = await syllabusExtractPdf(adminToken, fd);
      if (res.data?.preview) {
        setPreviewData(res.data);
        toast.success(`Extracted ${res.data.subjects_count} subject${res.data.subjects_count !== 1 ? 's' : ''} — review & save`);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'PDF extraction failed');
    } finally {
      setPdfLoading(false);
      if (pdfRef.current) pdfRef.current.value = '';
    }
  };

  const updatePreviewSubject = (idx, field, value) => {
    setPreviewData(prev => {
      const updated = [...prev.extracted];
      updated[idx] = { ...updated[idx], [field]: value };
      return { ...prev, extracted: updated };
    });
  };

  const removePreviewSubject = (idx) => {
    setPreviewData(prev => {
      const updated = prev.extracted.filter((_, i) => i !== idx);
      return { ...prev, extracted: updated };
    });
    if (expandedIdx === idx) setExpandedIdx(null);
  };

  const addPreviewChapter = (idx, chapter) => {
    if (!chapter.trim()) return;
    setPreviewData(prev => {
      const updated = [...prev.extracted];
      updated[idx] = { ...updated[idx], chapters: [...(updated[idx].chapters || []), chapter.trim()] };
      return { ...prev, extracted: updated };
    });
  };

  const removePreviewChapter = (subjectIdx, chapterIdx) => {
    setPreviewData(prev => {
      const updated = [...prev.extracted];
      updated[subjectIdx] = {
        ...updated[subjectIdx],
        chapters: updated[subjectIdx].chapters.filter((_, i) => i !== chapterIdx),
      };
      return { ...prev, extracted: updated };
    });
  };

  const handleConfirmImport = async () => {
    if (!previewData) return;
    setConfirmLoading(true);
    try {
      const res = await syllabusConfirmImport(adminToken, {
        extracted: previewData.extracted,
        paper_type: previewData.paper_type,
        filename: previewData.filename,
      });
      setPdfResult(res.data);
      setPreviewData(null);
      const count = res.data?.subjects_extracted || 0;
      toast.success(`Saved ${count} subject${count !== 1 ? 's' : ''} as ${previewData.paper_type?.toUpperCase()}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Save failed');
    } finally {
      setConfirmLoading(false);
    }
  };

  const addChapter = () => {
    if (newChapter.trim()) {
      setFormData({ ...formData, chapters: [...formData.chapters, newChapter.trim()] });
      setNewChapter('');
    }
  };

  const removeChapter = (i) => setFormData({ ...formData, chapters: formData.chapters.filter((_, idx) => idx !== i) });

  const addTopic = () => {
    if (newTopic.trim()) {
      setFormData({ ...formData, topics: [...formData.topics, newTopic.trim()] });
      setNewTopic('');
    }
  };

  const removeTopic = (i) => setFormData({ ...formData, topics: formData.topics.filter((_, idx) => idx !== i) });

  const addGeoPhrase = () => {
    if (newGeoPhrase.trim()) {
      setFormData({ ...formData, geo_phrases: [...(formData.geo_phrases || []), newGeoPhrase.trim()] });
      setNewGeoPhrase('');
    }
  };

  const removeGeoPhrase = (i) => setFormData({ ...formData, geo_phrases: (formData.geo_phrases || []).filter((_, idx) => idx !== i) });

  const scopeLabel = selectedSubject
    ? `${selectedBoard?.name || ''} · ${selectedClass?.name || ''} · ${selectedStream?.name || ''} · ${selectedSubject.name}`
    : selectedStream
    ? `${selectedBoard?.name || ''} · ${selectedClass?.name || ''} · ${selectedStream.name}`
    : selectedClass
    ? `${selectedBoard?.name || ''} · ${selectedClass?.name || ''}`
    : '';

  const fallbackNotice = isFallback && editingSyllabus ? (
    selectedSubjectId
      ? `Showing a fallback syllabus — no subject-specific syllabus exists yet for "${selectedSubject?.name}". Save below to create one.`
      : `Showing the general board+class syllabus as a preview — no stream-specific syllabus exists yet for ${selectedStream?.name}. Save below to create one.`
  ) : null;

  const saveButtonLabel = saving
    ? 'Saving...'
    : isFallback && selectedSubjectId
    ? `Create Subject Syllabus for ${selectedSubject?.name || ''}`
    : isFallback && selectedStreamId
    ? `Create Stream Syllabus for ${selectedStream?.name || ''}`
    : 'Save Syllabus';

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BookOpen size={22} className="text-indigo-400" />
        <div>
          <h2 className="text-lg font-bold text-white">Universal Syllabus Manager</h2>
          <p className="text-xs text-white/40 mt-0.5">Create syllabi that auto-inject into every AI answer for a board, class, stream, or specific subject</p>
        </div>
      </div>

      {/* NEP FYUGP Live Banner */}
      <div className="rounded-xl border px-4 py-3 space-y-2"
        style={{ background: 'rgba(52,211,153,0.07)', borderColor: 'rgba(52,211,153,0.22)' }}>
        {/* Top row */}
        <div className="flex items-center gap-3">
          <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm"
            style={{ background: 'rgba(52,211,153,0.15)' }}>🚀</div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-bold text-emerald-400 leading-tight">
              Syrabit.ai Subject Router — NEP FYUGP Live
            </p>
            <p className="text-[11px] text-white/50 mt-0.5">
              Syllabus auto-embed active &nbsp;·&nbsp; 98% plain-query accuracy &nbsp;·&nbsp; zero manual work
            </p>
          </div>
          <span className="flex-shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold"
            style={{ background: 'rgba(52,211,153,0.18)', color: '#6ee7b7' }}>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse inline-block" />
            LIVE
          </span>
        </div>
        {/* Stats row */}
        {nepStats && (
          <div className="flex flex-wrap gap-2 pt-1 border-t" style={{ borderColor: 'rgba(52,211,153,0.12)' }}>
            {['aec','sec','mdc','vac','ge','cc','major','minor'].map(t => {
              const count = nepStats.by_type?.[t] || 0;
              if (!count) return null;
              const icons = { aec:'🧠', sec:'⚡', mdc:'🌐', vac:'✨', ge:'🔄', cc:'⭐', major:'🎯', minor:'📘' };
              return (
                <span key={t} className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                  style={{ background: 'rgba(52,211,153,0.10)', color: '#6ee7b7' }}>
                  {icons[t]} {t.toUpperCase()}: {count}
                </span>
              );
            })}
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded ml-auto"
              style={{ background: 'rgba(99,102,241,0.15)', color: '#a5b4fc' }}>
              📚 {nepStats.total_subjects} subjects · {nepStats.total_embedded_chapters} embedded
            </span>
          </div>
        )}
      </div>

      {/* PDF Import Panel */}
      <div className="rounded-xl border p-4 space-y-4" style={{ background: 'rgba(139,92,246,0.05)', borderColor: 'rgba(139,92,246,0.20)' }}>
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-white flex items-center gap-2">
              <FileUp size={14} className="text-violet-400" /> PDF-to-Syllabus Importer
            </p>
            <p className="text-xs mt-0.5 text-white/40">Upload an official syllabus PDF — Gemini auto-extracts all subjects, chapters, and topics</p>
          </div>
          <input ref={pdfRef} type="file" accept=".pdf" className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) handlePdfImport(f); }} />
          <button onClick={() => pdfRef.current?.click()} disabled={pdfLoading}
            className="flex-shrink-0 flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
            style={{ background: 'rgba(139,92,246,0.20)', border: '1px solid rgba(139,92,246,0.35)', color: '#c4b0f0' }}>
            {pdfLoading ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            {pdfLoading ? 'Importing…' : 'Import PDF'}
          </button>
        </div>

        {/* Paper Type Selector */}
        <div>
          <p className="text-[10px] font-semibold text-white/50 uppercase tracking-wide mb-2">Paper Type <span className="text-violet-400">*</span></p>
          <div className="grid grid-cols-4 gap-2">
            {PAPER_TYPES.map(pt => (
              <button
                key={pt.value}
                onClick={() => setPaperType(pt.value)}
                className="rounded-lg p-2.5 text-left border transition-all"
                style={paperType === pt.value ? {
                  background: 'rgba(139,92,246,0.25)',
                  borderColor: 'rgba(139,92,246,0.70)',
                  color: '#d8b4fe',
                } : {
                  background: 'rgba(255,255,255,0.04)',
                  borderColor: 'rgba(255,255,255,0.10)',
                  color: 'rgba(255,255,255,0.50)',
                }}>
                <p className="text-xs font-bold">{pt.icon} {pt.label}</p>
                <p className="text-[10px] mt-0.5 leading-tight opacity-75">{pt.desc}</p>
              </button>
            ))}
          </div>
          <p className="text-[11px] mt-2 text-white/35">
            The PDF may contain multiple subjects — all will be tagged as <span className="text-violet-300 font-semibold">{paperType.toUpperCase()}</span>. Board and class are auto-detected from the PDF.
          </p>
        </div>

        {/* ── Preview & Edit Panel ─────────────────────────────────────────── */}
        {previewData && (
          <PreviewEditPanel
            previewData={previewData}
            expandedIdx={expandedIdx}
            setExpandedIdx={setExpandedIdx}
            onUpdateSubject={updatePreviewSubject}
            onRemoveSubject={removePreviewSubject}
            onAddChapter={addPreviewChapter}
            onRemoveChapter={removePreviewChapter}
            onConfirm={handleConfirmImport}
            onDiscard={() => { setPreviewData(null); setExpandedIdx(null); }}
            confirmLoading={confirmLoading}
          />
        )}

        {/* ── Saved Results ────────────────────────────────────────────────── */}
        {!previewData && pdfResult && pdfResult.success && (
          <div className="rounded-lg border text-xs" style={{ background: 'rgba(52,211,153,0.06)', borderColor: 'rgba(52,211,153,0.20)' }}>
            <div className="p-3 border-b" style={{ borderColor: 'rgba(52,211,153,0.15)' }}>
              <p className="font-semibold text-emerald-400">
                ✓ {pdfResult.subjects_extracted} subject{pdfResult.subjects_extracted !== 1 ? 's' : ''} saved as {pdfResult.paper_type?.toUpperCase()}
              </p>
              <p className="text-white/40 mt-0.5 font-mono text-[10px]">
                {pdfResult.filename} · import #{pdfResult.import_id?.slice(-6)}
              </p>
            </div>
            <div className="divide-y" style={{ borderColor: 'rgba(255,255,255,0.05)' }}>
              {(pdfResult.subjects || []).map((s, i) => (
                <div key={i} className="p-3 space-y-1.5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold text-white text-[11px]">{s.subject_name}</p>
                      <p className="text-white/40 text-[10px] mt-0.5">
                        {[s.board_name, s.class_name, s.semester].filter(Boolean).join(' · ')}
                        {s.course_code ? ` · ${s.course_code}` : ''}
                        {s.credits ? ` · ${s.credits} cr` : ''}
                      </p>
                    </div>
                    <div className="text-right text-white/40 text-[10px] flex-shrink-0">
                      <p>{s.chapters_count} chapters</p>
                      <p>{s.topics_count} topics</p>
                    </div>
                  </div>
                  {s.streams?.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {s.streams.map((st, j) => (
                        <span key={j} className="px-1.5 py-0.5 rounded text-[9px] font-semibold"
                          style={{ background: 'rgba(99,102,241,0.20)', color: '#a5b4fc' }}>
                          {st.stream_name}
                        </span>
                      ))}
                    </div>
                  )}
                  {s.created_nodes?.length > 0 && (
                    <p className="text-emerald-400/70 text-[9px]">+ {s.created_nodes.join(', ')}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Selectors — 2×2 grid */}
      <div className="grid grid-cols-2 gap-3">
        {/* Board */}
        <div>
          <label className="text-[10px] font-semibold text-white/50 uppercase tracking-wide mb-1.5 block">Board</label>
          <select
            value={selectedBoardId}
            onChange={(e) => {
              setSelectedBoardId(e.target.value);
              setSelectedClassId('');
              setSelectedStreamId('');
              setSelectedSubjectId('');
            }}
            className="w-full px-3 py-2.5 rounded-xl border border-white/10 bg-white/5 text-white text-sm focus:border-indigo-500 outline-none transition-colors"
          >
            <option value="">Select Board</option>
            {boards.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>

        {/* Class */}
        <div>
          <label className="text-[10px] font-semibold text-white/50 uppercase tracking-wide mb-1.5 block">Class</label>
          <select
            value={selectedClassId}
            onChange={(e) => {
              setSelectedClassId(e.target.value);
              setSelectedStreamId('');
              setSelectedSubjectId('');
            }}
            disabled={!selectedBoardId}
            className="w-full px-3 py-2.5 rounded-xl border border-white/10 bg-white/5 text-white text-sm focus:border-indigo-500 outline-none transition-colors disabled:opacity-40"
          >
            <option value="">Select Class</option>
            {filteredClasses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>

        {/* Stream (optional) */}
        <div>
          <label className="text-[10px] font-semibold text-white/50 uppercase tracking-wide mb-1.5 flex items-center gap-1">
            <GitBranch size={10} />
            Stream
            <span className="text-white/25 font-normal normal-case tracking-normal ml-1">(optional)</span>
          </label>
          <select
            value={selectedStreamId}
            onChange={(e) => {
              setSelectedStreamId(e.target.value);
              setSelectedSubjectId('');
            }}
            disabled={!selectedClassId}
            className="w-full px-3 py-2.5 rounded-xl border border-white/10 bg-white/5 text-white text-sm focus:border-indigo-500 outline-none transition-colors disabled:opacity-40"
          >
            <option value="">All Streams (General)</option>
            {filteredStreams.map(s => <option key={s.id} value={s.id}>{s.icon ? `${s.icon} ` : ''}{s.name}</option>)}
          </select>
        </div>

        {/* Subject (optional) */}
        <div>
          <label className="text-[10px] font-semibold text-white/50 uppercase tracking-wide mb-1.5 flex items-center gap-1">
            <BookOpen size={10} />
            Subject
            <span className="text-white/25 font-normal normal-case tracking-normal ml-1">(optional)</span>
          </label>
          <select
            value={selectedSubjectId}
            onChange={(e) => setSelectedSubjectId(e.target.value)}
            disabled={!selectedStreamId}
            className="w-full px-3 py-2.5 rounded-xl border border-white/10 bg-white/5 text-white text-sm focus:border-indigo-500 outline-none transition-colors disabled:opacity-40"
          >
            <option value="">All Subjects in Stream</option>
            {filteredSubjects.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
      </div>

      {/* Scope explanation */}
      {selectedClassId && (
        <div className="flex items-start gap-2 p-3 rounded-xl border border-white/10 bg-white/[0.02]">
          <Info size={14} className="text-indigo-400 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-white/50 leading-relaxed">
            {selectedSubjectId
              ? <>This syllabus applies only to <span className="text-indigo-300 font-medium">{selectedSubject?.name}</span> within {selectedStream?.name}. It takes highest priority — the AI uses it when a student asks about this specific subject.</>
              : selectedStreamId
              ? <>This syllabus applies only to <span className="text-indigo-300 font-medium">{scopeLabel}</span>. The AI will use it when a student from this exact stream asks a question.</>
              : <>This is a <span className="text-indigo-300 font-medium">general syllabus</span> for <span className="text-white/70">{scopeLabel}</span>. The AI uses it as a fallback when no stream- or subject-specific syllabus exists.</>
            }
          </p>
        </div>
      )}

      {/* Loading indicator */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-white/40">
          <Loader2 size={14} className="animate-spin" />
          Loading syllabus...
        </div>
      )}

      {/* Fallback notice */}
      {!loading && fallbackNotice && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-amber-500/20 bg-amber-500/5 text-amber-200 text-xs">
          <Info size={14} className="flex-shrink-0" />
          {fallbackNotice}
        </div>
      )}

      {canLoad && !loading && (
        <>
          {/* Syllabus Content */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">Syllabus Description *</label>
            <textarea
              value={formData.content}
              onChange={(e) => setFormData({ ...formData, content: e.target.value })}
              placeholder={
                selectedSubjectId
                  ? `e.g., ${selectedSubject?.name || 'Physics'} for AssamBoard covers mechanics, thermodynamics, and optics. Emphasis on board exam patterns and numerical problem-solving...`
                  : selectedStreamId
                  ? `e.g., AssamBoard ${selectedStream?.name || 'Science'} covers Physics, Chemistry, and ${selectedStream?.name?.includes('PCM') ? 'Mathematics' : 'Biology'}. Focus on conceptual understanding and AssamBoard exam patterns...`
                  : 'e.g., AssamBoard AHSEC covers Science, Arts, and Commerce streams. This syllabus serves as the general curriculum guide for all AI responses...'
              }
              className="w-full px-4 py-3 rounded-xl border border-white/10 bg-white/5 text-white placeholder-white/20 text-sm focus:border-indigo-500 outline-none transition-colors resize-none"
              rows={6}
            />
            <p className="text-[11px] text-white/30 text-right">{formData.content.length} chars</p>
          </div>

          {/* Guidelines */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">Learning Guidelines <span className="text-white/30 font-normal normal-case">(optional)</span></label>
            <textarea
              value={formData.guidelines}
              onChange={(e) => setFormData({ ...formData, guidelines: e.target.value })}
              placeholder="e.g., Students should focus on deriving formulas, solving numeric problems, and understanding real-world applications. Emphasise AssamBoard exam patterns..."
              className="w-full px-4 py-3 rounded-xl border border-white/10 bg-white/5 text-white placeholder-white/20 text-sm focus:border-indigo-500 outline-none transition-colors resize-none"
              rows={3}
            />
          </div>

          {/* GEO Authority Phrases */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">
              GEO Authority Phrases <span className="text-white/30 font-normal normal-case">(injected into AI answers)</span>
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={newGeoPhrase}
                onChange={(e) => setNewGeoPhrase(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addGeoPhrase()}
                placeholder='e.g., "As per AssamBoard 2024 syllabus, this topic carries 5 marks"'
                className="flex-1 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white placeholder-white/25 text-sm focus:border-emerald-500 outline-none"
              />
              <button
                onClick={addGeoPhrase}
                className="px-3 py-2 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 transition-colors"
              >
                <Plus size={16} />
              </button>
            </div>
            {(formData.geo_phrases || []).length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {formData.geo_phrases.map((phrase, i) => (
                  <div key={i} className="px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-200 text-xs flex items-center gap-2">
                    {phrase}
                    <button onClick={() => removeGeoPhrase(i)} className="hover:text-white transition-colors">
                      <Trash2 size={11} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <p className="text-[10px] text-white/25">These phrases get woven into every AI answer for this syllabus scope. Use exam stats, textbook citations, and board-authority language.</p>
          </div>

          {/* Key Topics */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">Key Topics</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={newTopic}
                onChange={(e) => setNewTopic(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addTopic()}
                placeholder="Type a topic and press Enter..."
                className="flex-1 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white placeholder-white/25 text-sm focus:border-indigo-500 outline-none"
              />
              <button
                onClick={addTopic}
                className="px-3 py-2 rounded-lg bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 transition-colors"
              >
                <Plus size={16} />
              </button>
            </div>
            {formData.topics.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                {formData.topics.map((topic, i) => (
                  <div key={i} className="px-3 py-1.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-200 text-xs flex items-center gap-2">
                    {topic}
                    <button onClick={() => removeTopic(i)} className="hover:text-white transition-colors">
                      <Trash2 size={11} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Chapters */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-white/60 uppercase tracking-wide">
              Chapters <span className="text-white/30 font-normal normal-case">(optional)</span>
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={newChapter}
                onChange={(e) => setNewChapter(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addChapter()}
                placeholder="Chapter name and press Enter..."
                className="flex-1 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white placeholder-white/25 text-sm focus:border-indigo-500 outline-none"
              />
              <button
                onClick={addChapter}
                className="px-3 py-2 rounded-lg bg-violet-500/20 hover:bg-violet-500/30 text-violet-300 transition-colors"
              >
                <Plus size={16} />
              </button>
            </div>
            {formData.chapters.length > 0 && (
              <div className="space-y-1.5 pt-1">
                {formData.chapters.map((ch, i) => (
                  <div key={i} className="px-3 py-2 rounded-lg bg-violet-500/10 border border-violet-500/20 text-violet-200 text-sm flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <span className="text-violet-400/50 text-xs font-mono">{String(i + 1).padStart(2, '0')}.</span>
                      {ch}
                    </span>
                    <button onClick={() => removeChapter(i)} className="hover:text-violet-100 transition-colors ml-4 flex-shrink-0">
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Existing syllabus indicator */}
          {editingSyllabus && !isFallback && (
            <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center gap-2 text-emerald-200 text-sm">
              <CheckCircle size={15} className="flex-shrink-0" />
              <span>
                Syllabus saved for <strong>{scopeLabel}</strong>
                {editingSyllabus.updated_at && (
                  <span className="text-emerald-300/50 text-xs ml-2">
                    · Updated {new Date(editingSyllabus.updated_at).toLocaleDateString()}
                  </span>
                )}
              </span>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <button
              onClick={saveSyllabus}
              disabled={saving || loading || !formData.content.trim()}
              className="flex-1 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-600/40 text-white font-medium text-sm transition-colors flex items-center justify-center gap-2"
            >
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
              {saveButtonLabel}
            </button>
            {editingSyllabus && !isFallback && (
              <button
                onClick={deleteSyllabus}
                disabled={saving || loading}
                className="px-4 py-2.5 rounded-xl bg-red-600/15 hover:bg-red-600/25 disabled:opacity-40 text-red-300 font-medium text-sm transition-colors flex items-center gap-2"
              >
                <Trash2 size={15} />
                Delete
              </button>
            )}
          </div>

          {/* Publish as Syllabus Card — only for subject-level saved syllabi */}
          {editingSyllabus && !isFallback && selectedSubjectId && selectedStreamId && (
            <div className="pt-2 border-t border-white/10">
              <div className="flex items-center gap-2">
                <button
                  onClick={publishSyllabus}
                  disabled={publishing || saving}
                  className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-600/20 hover:bg-emerald-600/30 disabled:opacity-40 text-emerald-300 font-medium text-sm transition-colors border border-emerald-500/20"
                >
                  {publishing ? <Loader2 size={15} className="animate-spin" /> : <Globe size={15} />}
                  {publishing ? 'Publishing...' : 'Publish as Syllabus Card'}
                </button>
                {publishedSlug && (
                  <Link
                    to={`/learn/${publishedSlug}`}
                    target="_blank"
                    className="flex items-center gap-1.5 px-3 py-2.5 rounded-xl text-xs text-emerald-400 hover:text-emerald-300 transition-colors"
                  >
                    <ExternalLink size={13} />
                    View Card
                  </Link>
                )}
              </div>
              <p className="text-[10px] text-white/25 mt-2">
                Creates a discoverable library card at <span className="text-white/40">/learn/…</span> tagged "Syllabus" — visible to all students.
              </p>
            </div>
          )}
        </>
      )}

      {!canLoad && (
        <div className="p-5 rounded-xl bg-white/[0.02] border border-white/10 text-center">
          <BookOpen size={28} className="mx-auto text-white/15 mb-2" />
          <p className="text-white/50 text-sm">Select a Board and Class to manage their syllabus</p>
          <p className="text-white/25 text-xs mt-1">Stream and Subject are optional — use them for more targeted AI guidance</p>
        </div>
      )}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────────
   PreviewEditPanel — review & edit AI-extracted subjects before saving
────────────────────────────────────────────────────────────────────────── */
function PreviewEditPanel({
  previewData, expandedIdx, setExpandedIdx,
  onUpdateSubject, onRemoveSubject, onAddChapter, onRemoveChapter,
  onConfirm, onDiscard, confirmLoading,
}) {
  const [newChapterText, setNewChapterText] = useState({});

  const inputCls = "w-full bg-white/5 border border-white/10 rounded px-2 py-1 text-xs text-white placeholder-white/25 focus:outline-none focus:border-violet-400/50";
  const btnSm    = "px-2 py-0.5 rounded text-[10px] font-semibold transition";

  return (
    <div className="rounded-xl border space-y-3" style={{ background: 'rgba(139,92,246,0.04)', borderColor: 'rgba(139,92,246,0.22)' }}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b" style={{ borderColor: 'rgba(139,92,246,0.15)' }}>
        <div>
          <p className="text-[11px] font-semibold text-violet-300">
            Review extracted syllabus — {previewData.subjects_count} subject{previewData.subjects_count !== 1 ? 's' : ''} from &ldquo;{previewData.filename}&rdquo;
          </p>
          <p className="text-[10px] text-white/35 mt-0.5">
            Edit any field or remove subjects before saving. Chapters and topics guide AI answers.
          </p>
        </div>
        <button onClick={onDiscard} className="text-white/30 hover:text-white/70 transition text-[10px] ml-3">discard</button>
      </div>

      {/* Subject cards */}
      <div className="px-3 space-y-2">
        {previewData.extracted.map((sub, idx) => {
          const isOpen = expandedIdx === idx;
          return (
            <div key={idx} className="rounded-lg border overflow-hidden" style={{ borderColor: 'rgba(255,255,255,0.08)' }}>
              {/* Card header / toggle */}
              <div
                className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-white/[0.03] transition"
                onClick={() => setExpandedIdx(isOpen ? null : idx)}
              >
                <span className="text-[10px] text-white/30 w-5 text-center">{idx + 1}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-semibold text-white truncate">{sub.subject_name || '(unnamed)'}</p>
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

              {/* Expanded edit area */}
              {isOpen && (
                <div className="px-3 pb-3 pt-1 border-t space-y-3" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
                  {/* Metadata row */}
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

                  {/* Chapters */}
                  <div>
                    <label className="text-[9px] text-white/35 uppercase tracking-wide block mb-1">Chapters ({(sub.chapters || []).length})</label>
                    <div className="space-y-1 max-h-40 overflow-y-auto pr-1">
                      {(sub.chapters || []).map((ch, ci) => (
                        <div key={ci} className="flex items-center gap-1 group">
                          <input
                            className={inputCls + ' flex-1'}
                            value={ch}
                            onChange={e => {
                              const chaps = [...(sub.chapters || [])];
                              chaps[ci] = e.target.value;
                              onUpdateSubject(idx, 'chapters', chaps);
                            }}
                          />
                          <button onClick={() => onRemoveChapter(idx, ci)}
                            className="text-red-400/40 hover:text-red-400 transition opacity-0 group-hover:opacity-100 flex-shrink-0">
                            <Trash2 size={10} />
                          </button>
                        </div>
                      ))}
                    </div>
                    {/* Add chapter */}
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

      {/* Footer actions */}
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
