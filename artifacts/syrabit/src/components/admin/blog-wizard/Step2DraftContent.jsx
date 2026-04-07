import { useState, useEffect, useRef } from 'react';
import { ChevronRight, ChevronLeft, Loader2, FileUp } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import SharedMdxEditor from '../SharedMdxEditor';
import { API, authHeaders, wordCount } from '@/utils/adminHelpers';

export default function Step2DraftContent({ state, set, goNext, goPrev, adminToken, autoRun }) {
  const [saving, setSaving] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [editorKey, setEditorKey] = useState(0);
  const editorRef = useRef(null);
  const pdfRef = useRef(null);
  const autoRunFired2 = useRef(false);

  const wc = wordCount(state.draftContent);
  const canContinue = wc >= 150;

  const handleContentChange = (val) => {
    set({ draftContent: val });
  };

  useEffect(() => {
    if (!autoRun || autoRunFired2.current || saving) return;
    if (!canContinue || !state.docId) return;
    autoRunFired2.current = true;
    const t = setTimeout(() => handleContinue(), 600);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, canContinue, state.docId, saving]);

  const handlePdfUpload = async () => {
    const file = pdfRef.current?.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) { toast.error('Only PDF files accepted'); return; }
    setPdfLoading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await axios.post(`${API}/admin/content/extract-pdf-text`, formData, {
        ...authHeaders(adminToken),
        headers: { ...authHeaders(adminToken).headers, 'Content-Type': 'multipart/form-data' },
      });
      const extracted = res.data.text || '';
      if (!extracted) { toast.error('No text extracted from PDF'); return; }
      const current = editorRef.current?.getMarkdown() || state.draftContent;
      const updated = current ? `${current}\n\n---\n\n${extracted}` : extracted;
      set({ draftContent: updated });
      setEditorKey(k => k + 1);
      toast.success(`Extracted ${res.data.chars?.toLocaleString() || '?'} chars from ${res.data.pages} pages`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'PDF extraction failed');
    } finally {
      setPdfLoading(false);
      if (pdfRef.current) pdfRef.current.value = '';
    }
  };

  const handleContinue = async () => {
    if (!canContinue || !state.docId) return;
    setSaving(true);
    try {
      const liveContent = editorRef.current?.getMarkdown() || state.draftContent;
      set({ draftContent: liveContent });
      await axios.patch(
        `${API}/admin/content/cms-documents/${state.docId}`,
        { title: state.workingTitle || 'Draft', content: liveContent, status: 'draft', primary_keyword: state.primaryKeyword, schema_type: state.contentType },
        authHeaders(adminToken)
      );
      goNext();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to save draft content');
    } finally { setSaving(false); }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-5 pb-3 flex items-center justify-between flex-shrink-0">
        <div>
          <h2 className="text-base font-bold text-gray-900">Step 2 — Draft Content</h2>
          <p className="text-xs text-gray-400 mt-0.5">Write, paste, or extract content. Need ≥ 150 words to continue.</p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`text-xs font-semibold px-2.5 py-1 rounded-lg ${canContinue ? 'text-emerald-400 bg-emerald-500/10' : 'text-amber-400 bg-amber-500/10'}`}>
            {wc} / 150 words
          </div>
          <input ref={pdfRef} type="file" accept=".pdf" className="hidden" onChange={handlePdfUpload} />
          <button
            onClick={() => pdfRef.current?.click()}
            disabled={pdfLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition disabled:opacity-50"
            style={{ background: 'rgba(139,92,246,0.15)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.25)' }}
          >
            {pdfLoading ? <Loader2 size={12} className="animate-spin" /> : <FileUp size={12} />}
            {pdfLoading ? 'Extracting…' : 'From PDF'}
          </button>
        </div>
      </div>

      <div className="flex-1 mx-6 mb-4 rounded-xl overflow-hidden border" style={{ borderColor: '#e5e7eb', minHeight: 300 }}>
        <SharedMdxEditor
          key={editorKey}
          ref={editorRef}
          markdown={state.draftContent}
          onChange={handleContentChange}
          editorKey={`step2-draft-${editorKey}`}
        />
      </div>

      <div className="px-6 mb-4 flex-shrink-0">
        <div className="h-1.5 rounded-full bg-gray-50 overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${Math.min(100, (wc / 150) * 100)}%`,
              background: canContinue ? '#10b981' : '#f59e0b',
            }}
          />
        </div>
      </div>

      <div className="px-6 pb-5 flex items-center justify-between flex-shrink-0">
        <button onClick={goPrev}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-gray-500 hover:text-gray-700 transition">
          <ChevronLeft size={14} /> Back
        </button>
        <button
          onClick={handleContinue}
          disabled={!canContinue || saving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
          style={{ background: canContinue ? '#7c3aed' : '#e5e7eb', color: canContinue ? 'white' : '#9ca3af' }}
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} />}
          {saving ? 'Saving…' : `Continue to AI Enrichment`}
        </button>
      </div>
    </div>
  );
}
