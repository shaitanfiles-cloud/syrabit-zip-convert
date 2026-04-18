import { useState, useEffect, useRef } from 'react';
import {
  ChevronLeft, Check, Loader2, Sparkles, RefreshCw, X,
  FileText, BookOpen, Layers, HelpCircle, Calculator, StickyNote, List,
} from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { API, authHeaders, wordCount } from '@/utils/adminHelpers';

const BLOCK_ICONS = {
  summary:    { icon: FileText,   color: '#8b5cf6' },
  definition: { icon: BookOpen,   color: '#3b82f6' },
  example:    { icon: Layers,     color: '#10b981' },
  pyq:        { icon: HelpCircle, color: '#f59e0b' },
  formula:    { icon: Calculator, color: '#ec4899' },
  note:       { icon: StickyNote, color: '#64748b' },
  faq:        { icon: HelpCircle, color: '#06b6d4' },
  syllabus:   { icon: List,       color: '#047857' },
};

export default function Step3AiEnrichment({ state, set, goNext, goPrev, adminToken, autoRun }) {
  const [enriching, setEnriching] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [localBlocks, setLocalBlocks] = useState(state.enrichedBlocks || null);
  const autoRunFired3 = useRef(false);

  const handleEnrich = async () => {
    if (!state.draftContent.trim()) { toast.error('No draft content to enrich'); return; }
    setEnriching(true);
    try {
      const res = await axios.post(`${API}/admin/studio/parse`, {
        raw_text: state.draftContent,
        subject: state.subjectName || '',
        chapter: state.workingTitle || '',
      }, authHeaders(adminToken));
      const blocks = res.data.blocks || [];
      if (!blocks.length) { toast.error('AI could not parse content — try re-running'); return; }
      setLocalBlocks(blocks);
      set({ enrichedBlocks: blocks });
      toast.success(`AI structured ${blocks.length} content blocks`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'AI enrichment failed — retry');
    } finally { setEnriching(false); }
  };

  const handleAccept = async () => {
    if (!localBlocks?.length) return;
    setSaving(true);
    setSaveError(false);
    try {
      const enrichedMd = localBlocks.map(b => `## ${b.title}\n\n${b.content}`).join('\n\n---\n\n');
      set({ enrichedContent: enrichedMd, enrichmentAccepted: true, enrichedBlocks: localBlocks });
      await axios.patch(
        `${API}/admin/content/cms-documents/${state.docId}`,
        { title: state.workingTitle || 'Draft', content: enrichedMd, status: 'draft' },
        authHeaders(adminToken)
      );
      goNext();
      toast.success('Enriched content accepted and saved');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to save enriched content');
      setSaveError(true);
    } finally { setSaving(false); }
  };

  const removeBlock = (idx) => {
    const updated = localBlocks.filter((_, i) => i !== idx);
    setLocalBlocks(updated);
  };

  useEffect(() => {
    if (!autoRun || autoRunFired3.current || localBlocks || !state.draftContent) return;
    autoRunFired3.current = true;
    const t = setTimeout(() => handleEnrich(), 400);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const autoAcceptFired = useRef(false);
  useEffect(() => {
    if (!autoRun || autoAcceptFired.current || !localBlocks?.length || enriching || saving) return;
    autoAcceptFired.current = true;
    handleAccept();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, localBlocks, enriching, saving]);

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-gray-900">Step 3 — AI Enrichment</h2>
          <p className="text-xs text-gray-600 mt-1">Let AI restructure your draft into rich GEO-optimized content blocks.</p>
        </div>
        <button
          onClick={handleEnrich}
          disabled={enriching}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition flex-shrink-0"
          style={{ background: 'rgba(139,92,246,0.20)', color: '#5b21b6', border: '1px solid rgba(139,92,246,0.30)' }}
        >
          {enriching ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {enriching ? 'Enriching…' : localBlocks ? 'Re-run AI' : 'Enrich with AI'}
        </button>
      </div>

      <div className="rounded-xl p-4 mb-4" style={{ background: '#f9fafb', border: '1px solid #e5e7eb' }}>
        <p className="text-xs font-semibold text-gray-600 mb-2">BEFORE (Raw Draft)</p>
        <p className="text-xs text-gray-500">{wordCount(state.draftContent)} words · {state.draftContent.length} chars</p>
        <p className="text-xs text-gray-600 mt-1 line-clamp-2">{state.draftContent.slice(0, 200)}…</p>
      </div>

      {localBlocks && localBlocks.length > 0 && (
        <>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-semibold text-gray-600">AFTER (AI-Enriched — {localBlocks.length} blocks)</span>
          </div>
          <div className="space-y-3 mb-5">
            {localBlocks.map((block, i) => {
              const cfg = BLOCK_ICONS[block.type] || BLOCK_ICONS.note;
              const Icon = cfg.icon;
              return (
                <div key={i} className="rounded-xl p-4 border group" style={{ borderColor: '#e5e7eb', background: '#ffffff' }}>
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ background: `${cfg.color}18` }}>
                      <Icon size={12} style={{ color: cfg.color }} />
                    </div>
                    <span className="text-[10px] font-bold uppercase tracking-wider flex-shrink-0" style={{ color: cfg.color }}>{block.type}</span>
                    <span className="text-sm font-medium text-gray-600 truncate min-w-0">{block.title}</span>
                    <button onClick={() => removeBlock(i)}
                      className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity text-red-600/70 hover:text-red-600 flex-shrink-0">
                      <X size={12} />
                    </button>
                  </div>
                  <p className="text-xs text-gray-600 leading-relaxed line-clamp-3">{block.content}</p>
                </div>
              );
            })}
          </div>
        </>
      )}

      {!localBlocks && !enriching && (
        <div className="rounded-xl p-8 text-center mb-5" style={{ background: '#f9fafb', border: '1px dashed #e5e7eb' }}>
          <Sparkles size={24} className="text-violet-600 mx-auto mb-2" />
          <p className="text-sm text-gray-600">Click "Enrich with AI" to restructure your content into definitions, FAQs, examples, and GEO authority phrases.</p>
        </div>
      )}

      {saveError && (
        <div className="mb-3 flex items-center justify-between gap-3 rounded-xl px-3 py-2"
          style={{ background: 'rgba(239,68,68,0.10)', border: '1px solid rgba(239,68,68,0.25)' }}>
          <span className="text-xs text-red-600">Save failed. Click "Accept & Continue" again to retry.</span>
          <RefreshCw size={12} className="text-red-600 flex-shrink-0" />
        </div>
      )}
      <div className="flex items-center justify-between">
        <button onClick={goPrev}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-gray-500 hover:text-gray-700 transition">
          <ChevronLeft size={14} /> Back
        </button>
        <button
          onClick={handleAccept}
          disabled={!localBlocks?.length || saving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
          style={{ background: localBlocks?.length ? '#7c3aed' : '#e5e7eb', color: localBlocks?.length ? 'white' : '#9ca3af' }}
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
          {saving ? 'Saving…' : saveError ? 'Retry Save' : 'Accept & Continue'}
        </button>
      </div>
    </div>
  );
}
