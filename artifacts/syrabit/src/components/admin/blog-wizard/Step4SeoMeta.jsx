import { useState, useEffect, useRef } from 'react';
import { ChevronRight, ChevronLeft, Loader2, Zap, AlertCircle, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { API, authHeaders, autoSlug } from '@/utils/adminHelpers';
import SerpPreview from './SerpPreview';
import PerplexityPreview from './PerplexityPreview';
import TagChips from './TagChips';
import ThumbnailUploader from './ThumbnailUploader';

const SCHEMA_TYPES = ['Article', 'FAQPage', 'HowTo', 'StudyNotes', 'Course'];

export default function Step4SeoMeta({ state, set, goNext, goPrev, adminToken, autoRun }) {
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const autoRunFired4 = useRef(false);

  const metaLen = (state.metaDescription || '').length;
  const metaValid = metaLen >= 120 && metaLen <= 160;
  const metaColor = metaLen === 0 ? 'text-gray-400' : metaValid ? 'text-emerald-400' : 'text-red-400';
  const metaErrorMsg = metaLen > 0 && !metaValid
    ? (metaLen < 120 ? `Too short (${metaLen}/120 min)` : `Too long (${metaLen}/160 max)`)
    : '';

  const requiredFilled = state.seoSlug && state.seoTitle && state.metaDescription && state.primaryKeyword && metaValid && state.seoTags && state.geoTags;

  const handleAutoFill = async () => {
    setGenerating(true);
    try {
      const payload = {
        title: state.workingTitle || state.seoTitle,
        content: (state.enrichedContent || state.draftContent).slice(0, 3000),
        primary_keyword: state.primaryKeyword,
        seo_tags: state.seoTags,
        linked_scope: [state.boardName, state.className, state.streamName, state.subjectName].filter(Boolean).join('/'),
        board: state.boardName || 'Assamboard',
        class_name: state.className,
        subject: state.subjectName,
      };
      const { data } = await axios.post(`${API}/admin/seo/generate`, payload, authHeaders(adminToken));
      set({
        seoTitle: data.seo_title || state.seoTitle,
        metaDescription: data.meta_description || state.metaDescription,
        primaryKeyword: data.primary_keyword || state.primaryKeyword,
        seoTags: data.seo_tags || state.seoTags,
        geoTags: Array.isArray(data.geo_phrases) ? data.geo_phrases.join('; ') : (state.geoTags || ''),
        seoSlug: state.seoSlug || autoSlug(data.seo_title || state.workingTitle || state.subjectName),
        schemaType: data.schema_type || state.schemaType,
      });
      toast.success('SEO & GEO metadata generated — review and edit below');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'AI SEO generation failed');
    } finally { setGenerating(false); }
  };

  const handleContinue = async () => {
    if (!requiredFilled || !state.docId) return;
    setSaving(true);
    setSaveError(false);
    try {
      await axios.patch(
        `${API}/admin/content/cms-documents/${state.docId}`,
        {
          title: state.seoTitle || state.workingTitle,
          seo_slug: state.seoSlug,
          meta_description: state.metaDescription,
          primary_keyword: state.primaryKeyword,
          seo_tags: state.seoTags,
          geo_tags: state.geoTags,
          schema_type: state.schemaType,
          thumbnail_url: state.thumbnailUrl,
          alt_text: state.altText,
          status: 'draft',
        },
        authHeaders(adminToken)
      );
      goNext();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to save metadata');
      setSaveError(true);
    } finally { setSaving(false); }
  };

  useEffect(() => {
    if (!autoRun || autoRunFired4.current || state.seoTitle || !state.enrichedContent) return;
    autoRunFired4.current = true;
    const t = setTimeout(() => handleAutoFill(), 400);
    return () => clearTimeout(t);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const autoContFired4 = useRef(false);
  useEffect(() => {
    if (!autoRun || autoContFired4.current || !requiredFilled || !state.docId || generating || saving) return;
    autoContFired4.current = true;
    handleContinue();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, requiredFilled, state.docId, generating, saving]);

  const inp = (err) => `w-full h-9 px-3 rounded-lg text-sm text-gray-900 bg-gray-50 border outline-none focus:border-violet-500 transition ${err ? 'border-red-500/50' : 'border-gray-200'}`;
  const lbl = 'text-xs font-semibold text-gray-500 mb-1 block';

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-gray-900">Step 4 — SEO & GEO Metadata</h2>
          <p className="text-xs text-gray-400 mt-1">Fill all fields for maximum search and AI visibility.</p>
        </div>
        <button
          onClick={handleAutoFill}
          disabled={generating}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition flex-shrink-0"
          style={{ background: 'rgba(139,92,246,0.20)', color: '#c4b5fd', border: '1px solid rgba(139,92,246,0.30)' }}
        >
          {generating ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
          {generating ? 'Generating…' : 'Auto-fill with AI'}
        </button>
      </div>

      <div className="space-y-4">
        <div>
          <label className={lbl}>SEO Slug *</label>
          <input className={inp(!state.seoSlug && saving)}
            placeholder="my-topic-assamboard-class-12"
            value={state.seoSlug}
            onChange={e => set({ seoSlug: autoSlug(e.target.value) })} />
          {state.canonicalUrl && (
            <p className="text-[10px] text-gray-400 mt-1">Canonical: {state.canonicalUrl}</p>
          )}
        </div>

        <div>
          <label className={lbl}>SEO Title * <span className="text-gray-300 font-normal">({(state.seoTitle || '').length}/65 chars)</span></label>
          <input className={inp(!state.seoTitle && saving)}
            placeholder="Topic Complete Notes Assamboard Class 12 | Syrabit"
            value={state.seoTitle}
            onChange={e => set({ seoTitle: e.target.value })} />
        </div>

        <div>
          <label className={lbl}>
            Meta Description * <span className={`font-semibold ml-1 ${metaColor}`}>{metaLen} chars {metaLen > 0 && `(target: 120–160)`}</span>
          </label>
          <textarea
            className={`w-full px-3 py-2 rounded-lg text-sm text-gray-900 bg-gray-50 border outline-none focus:border-violet-500 transition resize-none ${!metaValid && metaLen > 0 ? 'border-red-500/50' : 'border-gray-200'}`}
            rows={3}
            placeholder="Topic covers definitions, solved PYQ, MCQs per Assamboard syllabus. Free on Syrabit."
            value={state.metaDescription}
            onChange={e => set({ metaDescription: e.target.value })}
          />
          <div className="h-1 rounded-full bg-gray-50 mt-1.5 overflow-hidden">
            <div className="h-full rounded-full transition-all"
              style={{
                width: `${Math.min(100, (metaLen / 160) * 100)}%`,
                background: metaValid ? '#10b981' : metaLen > 160 ? '#ef4444' : '#f59e0b',
              }} />
          </div>
          {metaErrorMsg && (
            <p className="text-xs text-red-400 mt-1 flex items-center gap-1">
              <AlertCircle size={11} /> {metaErrorMsg}
            </p>
          )}
        </div>

        <div>
          <label className={lbl}>Primary Keyword *</label>
          <input className={inp(!state.primaryKeyword && saving)}
            placeholder="photosynthesis class 12 assamboard notes"
            value={state.primaryKeyword}
            onChange={e => set({ primaryKeyword: e.target.value })} />
        </div>

        <div>
          <label className={lbl}>SEO Tags (comma-separated)</label>
          <TagChips value={state.seoTags} onChange={v => set({ seoTags: v })} placeholder="Add tag…" />
        </div>

        <div>
          <label className={lbl}>GEO Tags / Authority Phrases</label>
          <TagChips value={state.geoTags} onChange={v => set({ geoTags: v })} placeholder="e.g. As per Assamboard 2024-25 syllabus…" />
        </div>

        <div>
          <label className={lbl}>Schema Type</label>
          <select className="w-full h-9 px-3 rounded-lg text-sm text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-500 transition cursor-pointer"
            value={state.schemaType}
            onChange={e => set({ schemaType: e.target.value })}>
            {SCHEMA_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        <div>
          <label className={lbl}>Cover Thumbnail</label>
          <ThumbnailUploader
            docId={state.docId}
            value={state.thumbnailUrl}
            onChange={url => set({ thumbnailUrl: url })}
            altText={state.altText}
            onAltChange={alt => set({ altText: alt })}
            adminToken={adminToken}
          />
        </div>

        {state.canonicalUrl && (
          <div>
            <label className={lbl}>Canonical URL (from syllabus link)</label>
            <input className={inp(false)} value={state.canonicalUrl} readOnly
              style={{ opacity: 0.6, cursor: 'default' }} />
          </div>
        )}
      </div>

      <div className="mt-6 space-y-3">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Live Previews</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <p className="text-[10px] text-gray-400 mb-1.5 font-medium">Google SERP</p>
            <SerpPreview
              title={state.seoTitle}
              slug={state.seoSlug}
              metaDescription={state.metaDescription}
            />
          </div>
          <div>
            <p className="text-[10px] text-gray-400 mb-1.5 font-medium">Perplexity / AI Overview</p>
            <PerplexityPreview
              title={state.seoTitle}
              slug={state.seoSlug}
              metaDescription={state.metaDescription}
            />
          </div>
        </div>
      </div>

      <div className="mt-6 flex items-center justify-between">
        <button onClick={goPrev}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-gray-500 hover:text-gray-700 transition">
          <ChevronLeft size={14} /> Back
        </button>
        <button
          onClick={handleContinue}
          disabled={!requiredFilled || saving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition disabled:opacity-40"
          style={{ background: requiredFilled ? '#7c3aed' : '#e5e7eb', color: requiredFilled ? 'white' : '#9ca3af' }}
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : saveError ? <RefreshCw size={14} /> : <ChevronRight size={14} />}
          {saving ? 'Saving…' : saveError ? 'Retry Save' : 'Continue to Review'}
        </button>
      </div>
    </div>
  );
}
