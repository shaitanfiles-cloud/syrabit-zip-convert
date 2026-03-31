import { Globe } from 'lucide-react';

export default function SerpPreview({ title, slug, metaDescription }) {
  return (
    <div className="rounded-xl p-4" style={{ background: '#ffffff' }}>
      <div className="flex items-center gap-2 mb-1.5">
        <div className="w-5 h-5 rounded-full flex-shrink-0" style={{ background: 'linear-gradient(135deg,#7c3aed,#9575e0)' }} />
        <div className="min-w-0">
          <p className="text-xs font-medium" style={{ color: '#202124' }}>syrabit.ai</p>
          <p className="text-[10px] truncate" style={{ color: '#4d5156' }}>https://syrabit.ai/{slug || 'your-slug'}</p>
        </div>
      </div>
      <p className="text-base leading-tight mb-1" style={{ color: '#1a0dab', fontFamily: 'arial,sans-serif' }}>
        {title ? `${title} | Syrabit.ai` : 'Your Page Title — Syrabit.ai'}
      </p>
      <p className="text-sm leading-snug" style={{ color: '#4d5156', fontFamily: 'arial,sans-serif' }}>
        {metaDescription
          ? (metaDescription.length > 160 ? metaDescription.slice(0, 157) + '…' : metaDescription)
          : 'Your meta description will appear here. Write 120–160 characters for best click-through.'}
      </p>
    </div>
  );
}
