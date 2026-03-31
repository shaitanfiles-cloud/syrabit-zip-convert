import { useState, useRef } from 'react';
import { Loader2, FileUp, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { syllabusExtractPdf, syllabusConfirmImport } from '@/utils/api';
import PreviewEditPanel from './PreviewEditPanel';

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

export default function ManualPdfImport({
  adminToken, selectedBoardId, selectedClassId, selectedStreamId,
  onImportComplete,
}) {
  const pdfRef = useRef(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfResult, setPdfResult] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [expandedIdx, setExpandedIdx] = useState(null);
  const [paperType, setPaperType] = useState('major');

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
      const count = res.data?.subjects_saved || res.data?.subjects_extracted || 0;
      const skipped = res.data?.subjects_skipped_duplicates || 0;
      const skipMsg = skipped > 0 ? ` · ${skipped} duplicate${skipped !== 1 ? 's' : ''} skipped` : '';
      toast.success(`Saved ${count} subject${count !== 1 ? 's' : ''} as ${previewData.paper_type?.toUpperCase()}${skipMsg}`);
      if (onImportComplete) onImportComplete(res.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Save failed');
    } finally { setConfirmLoading(false); }
  };

  return (
    <div className="rounded-xl border p-4 space-y-4" style={{ background: 'rgba(139,92,246,0.05)', borderColor: 'rgba(139,92,246,0.20)' }}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-white flex items-center gap-2">
            <FileUp size={14} className="text-violet-400" /> Manual PDF Importer (Preview mode)
          </p>
          <p className="text-xs mt-0.5 text-white/40">Preview-only: Gemini extracts subjects — review before confirming. Use the Agentic Uploader above for fully automatic import.</p>
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

      {!previewData && pdfResult && pdfResult.success && (
        <div className="rounded-lg border text-xs" style={{ background: 'rgba(52,211,153,0.06)', borderColor: 'rgba(52,211,153,0.20)' }}>
          <div className="p-3 border-b" style={{ borderColor: 'rgba(52,211,153,0.15)' }}>
            <div className="flex items-center gap-2 flex-wrap">
              <p className="font-semibold text-emerald-400">
                ✓ {pdfResult.subjects_saved ?? pdfResult.subjects_extracted ?? 0} subject{(pdfResult.subjects_saved ?? pdfResult.subjects_extracted ?? 0) !== 1 ? 's' : ''} saved as {pdfResult.paper_type?.toUpperCase()}
              </p>
              {(pdfResult.subjects_skipped_duplicates ?? 0) > 0 && (
                <span className="text-[9px] px-1.5 py-0.5 rounded font-semibold"
                  style={{ background: 'rgba(251,191,36,0.15)', color: '#fbbf24' }}>
                  ⟳ {pdfResult.subjects_skipped_duplicates} duplicate{pdfResult.subjects_skipped_duplicates !== 1 ? 's' : ''} skipped
                </span>
              )}
            </div>
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
  );
}
