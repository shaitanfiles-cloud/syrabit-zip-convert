import { useState, useRef } from 'react';
import { FileUp, Loader2, Check, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import axios from 'axios';
import { API, authHeaders } from '@/utils/adminHelpers';

const VARIANT_LABELS = ['Gradient Wash', 'Geometric', 'Abstract Circles'];

export default function ThumbnailUploader({ docId, value, onChange, altText, onAltChange, adminToken }) {
  const [loading, setLoading]   = useState(false);
  const [original, setOriginal] = useState(null);
  const [variants, setVariants] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [selected, setSelected] = useState(null);
  const inputRef = useRef(null);

  const handleFile = async (file) => {
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/webp', 'image/jpg'].includes(file.type)) {
      toast.error('PNG, JPG or WebP only'); return;
    }
    if (file.size > 2 * 1024 * 1024) { toast.error('Max file size is 2 MB'); return; }
    if (!docId) { toast.error('Complete Step 1 first to create a document'); return; }
    setLoading(true);
    try {
      const form = new FormData();
      form.append('doc_id', docId);
      form.append('file', file);
      const { data } = await axios.post(`${API}/admin/thumbnail/generate-cms`, form, {
        ...authHeaders(adminToken),
        headers: { ...authHeaders(adminToken).headers, 'Content-Type': 'multipart/form-data' },
      });
      setOriginal(data.original_url);
      setVariants(data.variants);
      setAnalysis(data.analysis);
      setSelected(0);
      onChange(data.variants[0]);
      toast.success('Color DNA extracted — 3 abstract variants ready');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Cover analysis failed');
    } finally {
      setLoading(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const file = e.dataTransfer?.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <div className="space-y-3">
      {!variants && (
        <div
          onDrop={handleDrop}
          onDragOver={e => e.preventDefault()}
          className="relative w-full rounded-xl border-2 border-dashed transition cursor-pointer"
          style={{ borderColor: loading ? 'rgba(139,92,246,0.50)' : '#e5e7eb' }}
          onClick={() => !loading && inputRef.current?.click()}
        >
          <input ref={inputRef} type="file" accept=".png,.jpg,.jpeg,.webp"
            className="hidden" onChange={e => handleFile(e.target.files?.[0])} />
          <div className="flex flex-col items-center justify-center py-6 gap-2">
            {loading
              ? <>
                  <Loader2 size={24} className="text-violet-600 animate-spin" />
                  <p className="text-xs text-violet-700 font-medium">Analyzing cover & extracting color DNA…</p>
                  <p className="text-[10px] text-gray-600">Generating 3 abstract variants</p>
                </>
              : <>
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center mb-1"
                    style={{ background: 'rgba(139,92,246,0.15)' }}>
                    <FileUp size={18} className="text-violet-600" />
                  </div>
                  <p className="text-sm font-semibold text-gray-600">Upload a book cover</p>
                  <p className="text-[11px] text-gray-600 text-center max-w-xs">
                    PNG, JPG, WebP — max 2 MB. The AI will extract its color DNA and generate 3 copyright-safe abstract variants.
                  </p>
                  {!docId && (
                    <p className="text-[10px] text-amber-700 mt-1">Complete Step 1 first to enable upload</p>
                  )}
                </>
            }
          </div>
        </div>
      )}

      {variants && original && (
        <div>
          {analysis?.dominant_colors?.length > 0 && (
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <span className="text-[10px] font-bold uppercase tracking-wider text-gray-600">Color DNA</span>
              {analysis.dominant_colors.slice(0, 5).map((c, i) => (
                <div key={i} title={c}
                  className="w-5 h-5 rounded-full border-2 border-gray-200 flex-shrink-0"
                  style={{ background: c }} />
              ))}
              {analysis.style && (
                <span className="text-[10px] text-gray-600 italic">
                  {analysis.style}{analysis.mood ? ` · ${analysis.mood}` : ''}
                </span>
              )}
            </div>
          )}

          <div className="grid grid-cols-4 gap-2">
            <div className="space-y-1.5">
              <p className="text-[10px] font-semibold text-gray-600 text-center uppercase tracking-wider">Original</p>
              <div className="relative rounded-xl overflow-hidden border border-gray-200"
                style={{ aspectRatio: '2/3', background: '#f9fafb' }}>
                <img src={original} alt="original cover" className="w-full h-full object-cover" />
              </div>
            </div>

            {variants.map((v, i) => (
              <div key={i} className="space-y-1.5">
                <p className="text-[10px] font-semibold text-center uppercase tracking-wider"
                  style={{ color: selected === i ? '#7c3aed' : '#4b5563' }}>
                  {VARIANT_LABELS[i]}
                </p>
                <button
                  onClick={() => { setSelected(i); onChange(v); }}
                  className="relative w-full rounded-xl overflow-hidden border-2 transition"
                  style={{
                    borderColor: selected === i ? '#7c3aed' : '#e5e7eb',
                    aspectRatio: '2/3',
                    display: 'block',
                  }}
                >
                  <img src={v} alt={`variant ${i + 1}`} className="w-full h-full object-cover" />
                  {selected === i && (
                    <div className="absolute inset-0 flex items-center justify-center"
                      style={{ background: 'rgba(124,58,237,0.28)' }}>
                      <div className="w-7 h-7 rounded-full bg-violet-600 flex items-center justify-center shadow-lg">
                        <Check size={14} className="text-white" />
                      </div>
                    </div>
                  )}
                </button>
              </div>
            ))}
          </div>

          <div className="mt-2 flex items-center justify-between">
            <button
              onClick={() => { setVariants(null); setOriginal(null); setSelected(null); onChange(''); }}
              className="flex items-center gap-1.5 text-[11px] text-gray-600 hover:text-gray-800 transition"
            >
              <RefreshCw size={10} /> Upload different cover
            </button>
            {value && (
              <span className="flex items-center gap-1 text-[11px] text-emerald-600 font-semibold">
                <Check size={11} /> Variant {selected + 1} selected
              </span>
            )}
          </div>
        </div>
      )}

      <div>
        <label className="text-xs font-semibold text-gray-500 mb-1 block">Alt Text</label>
        <input
          className="w-full h-9 px-3 rounded-lg text-sm text-gray-900 bg-gray-50 border border-gray-200 outline-none focus:border-violet-500 transition"
          placeholder="Descriptive alt text for accessibility and SEO"
          value={altText}
          onChange={e => onAltChange(e.target.value)}
        />
      </div>
    </div>
  );
}
