import { useState, useEffect, useRef } from 'react';
import {
  ChevronLeft, Check, Loader2, Globe, Lock, Copy, ExternalLink,
  AlertCircle, CheckCircle2,
} from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { API, authHeaders, wordCount } from '@/utils/adminHelpers';

export default function Step5ReviewPublish({ state, set, goPrev, adminToken, autoRun }) {
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [copied, setCopied] = useState(false);
  const autoRunFired5 = useRef(false);

  const wc = wordCount(state.enrichedContent || state.draftContent);
  const metaLen = (state.metaDescription || '').length;
  const metaValid = metaLen >= 120 && metaLen <= 160;

  const checks = [
    { label: 'Content ≥ 150 words', ok: wc >= 150, value: `${wc} words` },
    { label: 'SEO title filled', ok: !!state.seoTitle, value: state.seoTitle ? `${state.seoTitle.length} chars` : 'Missing' },
    { label: 'Meta description 120–160 chars', ok: metaValid, value: metaLen ? `${metaLen} chars` : 'Missing' },
    { label: 'Primary keyword set', ok: !!state.primaryKeyword, value: state.primaryKeyword || 'Missing' },
    { label: 'SEO slug set', ok: !!state.seoSlug, value: state.seoSlug || 'Missing' },
    { label: 'SEO tags added', ok: !!state.seoTags, value: state.seoTags || 'Missing' },
    { label: 'GEO tags added', ok: !!state.geoTags, value: state.geoTags || 'Missing' },
    { label: 'Scope linked', ok: !!state.subjectId, value: state.subjectName || state.subjectId || 'Not linked' },
  ];

  const allGreen = checks.every(c => c.ok);

  useEffect(() => {
    if (!autoRun || autoRunFired5.current || publishing) return;
    if (!allGreen || !state.docId) return;
    autoRunFired5.current = true;
    handlePublishToggle();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, allGreen, state.docId, publishing]);

  const handleSaveDraft = async () => {
    if (!state.docId) return;
    setSaving(true);
    try {
      await axios.patch(
        `${API}/admin/content/cms-documents/${state.docId}`,
        { status: 'draft' },
        authHeaders(adminToken)
      );
      set({ publishedStatus: 'draft' });
      toast.success('Saved as draft');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Save failed');
    } finally { setSaving(false); }
  };

  const handlePublishToggle = async () => {
    if (!state.docId) return;
    setPublishing(true);
    try {
      const res = await axios.post(`${API}/admin/content/cms-documents/${state.docId}/publish`, {}, authHeaders(adminToken));
      const newStatus = res.data.status;
      set({ publishedStatus: newStatus });
      toast.success(newStatus === 'published' ? 'Published! 🎉' : 'Moved back to draft');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Publish toggle failed');
    } finally { setPublishing(false); }
  };

  const liveUrl = state.canonicalUrl || (state.seoSlug ? `/learn/${state.seoSlug}` : '');

  const copyUrl = () => {
    if (!liveUrl) return;
    navigator.clipboard.writeText(`https://syrabit.ai${liveUrl}`).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-5">
        <h2 className="text-base font-bold text-gray-900">Step 5 — Review & Publish</h2>
        <p className="text-xs text-gray-400 mt-1">Check all fields, then publish or save as draft.</p>
      </div>

      <div className="rounded-xl border p-4 mb-5" style={{ background: '#ffffff', borderColor: '#e5e7eb' }}>
        <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">Document Summary</p>
        <div className="space-y-2">
          {[
            ['Scope', [state.boardName, state.className, state.streamName, state.subjectName].filter(Boolean).join(' → ')],
            ['Title', state.seoTitle || state.workingTitle],
            ['Slug', state.seoSlug],
            ['Meta Description', state.metaDescription],
            ['Primary Keyword', state.primaryKeyword],
            ['SEO Tags', state.seoTags],
            ['GEO Tags', state.geoTags],
            ['Schema', state.schemaType],
            ['Word Count', `${wc} words`],
            ['Status', state.publishedStatus],
          ].map(([k, v]) => (
            <div key={k} className="flex gap-2 text-xs">
              <span className="text-white/35 flex-shrink-0 w-28">{k}</span>
              <span className="text-white/65 min-w-0 break-words">{v || '—'}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border p-4 mb-5" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
        <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">Completeness Checklist</p>
        <div className="space-y-2">
          {checks.map(({ label, ok, value }) => (
            <div key={label} className="flex items-center gap-3 text-xs">
              {ok
                ? <CheckCircle2 size={14} className="text-emerald-400 flex-shrink-0" />
                : <AlertCircle size={14} className="text-amber-400 flex-shrink-0" />}
              <span className={ok ? 'text-gray-500' : 'text-amber-300/70'}>{label}</span>
              <span className="ml-auto text-gray-400 truncate max-w-[120px]">{value}</span>
            </div>
          ))}
        </div>
      </div>

      {state.publishedStatus === 'published' && (
        <div className="rounded-xl border p-4 mb-5" style={{ background: 'rgba(16,185,129,0.08)', borderColor: 'rgba(16,185,129,0.25)' }}>
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 size={16} className="text-emerald-400" />
            <span className="text-sm font-bold text-emerald-400">Published & Live!</span>
          </div>
          {liveUrl && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 truncate flex-1">https://syrabit.ai{liveUrl}</span>
              <button onClick={copyUrl}
                className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold transition flex-shrink-0"
                style={{ background: 'rgba(16,185,129,0.18)', color: '#34d399' }}>
                {copied ? <Check size={11} /> : <Copy size={11} />}
                {copied ? 'Copied!' : 'Copy'}
              </button>
              <a href={liveUrl} target="_blank" rel="noreferrer"
                className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold flex-shrink-0"
                style={{ background: 'rgba(16,185,129,0.10)', color: '#34d399' }}>
                <ExternalLink size={11} /> View
              </a>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <button onClick={goPrev}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-gray-500 hover:text-gray-700 transition">
          <ChevronLeft size={14} /> Back
        </button>
        <div className="flex gap-2">
          <button
            onClick={handleSaveDraft}
            disabled={saving || publishing}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
            style={{ background: '#e5e7eb', color: '#374151', border: '1px solid #e5e7eb' }}
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Lock size={14} />}
            {saving ? 'Saving…' : 'Save Draft'}
          </button>
          <button
            onClick={handlePublishToggle}
            disabled={(state.publishedStatus !== 'published' && !allGreen) || publishing || saving}
            className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
            style={{
              background: state.publishedStatus === 'published'
                ? 'rgba(239,68,68,0.18)'
                : (allGreen ? '#10b981' : '#e5e7eb'),
              color: state.publishedStatus === 'published'
                ? '#f87171'
                : (allGreen ? 'white' : '#9ca3af'),
            }}
          >
            {publishing ? <Loader2 size={14} className="animate-spin" /> : <Globe size={14} />}
            {publishing ? (state.publishedStatus === 'published' ? 'Unpublishing…' : 'Publishing…') : state.publishedStatus === 'published' ? 'Unpublish' : 'Publish Now'}
          </button>
        </div>
      </div>

      {!allGreen && state.publishedStatus !== 'published' && (
        <p className="text-xs text-amber-400/70 mt-3 text-right">Fix checklist items above to enable "Publish Now"</p>
      )}
    </div>
  );
}
