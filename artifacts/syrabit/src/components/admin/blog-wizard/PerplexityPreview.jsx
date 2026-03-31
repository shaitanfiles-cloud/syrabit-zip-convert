import { Sparkles, Globe } from 'lucide-react';

export default function PerplexityPreview({ title, slug, metaDescription }) {
  return (
    <div className="rounded-xl p-4" style={{ background: '#0d1117', border: '1px solid rgba(139,92,246,0.25)' }}>
      <div className="flex items-start gap-3">
        <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5" style={{ background: 'linear-gradient(135deg,#6366f1,#8b5cf6)' }}>
          <Sparkles size={11} className="text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs font-semibold mb-1" style={{ color: '#e2e8f0' }}>
            {title || 'Your page title as the AI answer heading'}
          </p>
          <p className="text-[11px] leading-relaxed mb-2" style={{ color: '#94a3b8' }}>
            {metaDescription || 'Your meta description appears as the AI-generated excerpt. Perplexity cites pages with clear educational intent and Assamboard-aligned content.'}
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10px]" style={{ background: 'rgba(139,92,246,0.15)', color: '#a78bfa' }}>
              <Globe size={9} /> syrabit.ai/{slug || 'slug'}
            </div>
          </div>
        </div>
        <div className="flex-shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: 'rgba(139,92,246,0.20)', color: '#a78bfa' }}>
          [1]
        </div>
      </div>
    </div>
  );
}
