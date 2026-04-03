import { useState, useCallback } from 'react';
import { toast } from 'sonner';

export function useShare() {
  const [sharing, setSharing] = useState(false);
  const [serpPreview, setSerpPreview] = useState(null);

  const share = useCallback(async (title, url, options = {}) => {
    if (sharing) return;
    const siteOrigin = import.meta.env.VITE_SITE_URL || window.location.origin;
    const shareUrl = url.startsWith('http') ? url : `${siteOrigin}${url}`;

    if (options.showSerpPreview) {
      setSerpPreview({
        title: title || 'Syrabit.ai',
        url: shareUrl,
        description: options.description || '',
      });
      return;
    }

    setSharing(true);
    try {
      if (navigator.share) {
        const shareData = { title, url: shareUrl };
        if (options.text) shareData.text = options.text;
        await navigator.share(shareData);
      } else {
        await navigator.clipboard.writeText(shareUrl);
        toast.success('Link copied to clipboard!');
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        try {
          await navigator.clipboard.writeText(shareUrl);
          toast.success('Link copied to clipboard!');
        } catch {
          toast.error('Unable to share');
        }
      }
    } finally {
      setSharing(false);
    }
  }, [sharing]);

  const confirmShare = useCallback(async () => {
    if (!serpPreview) return;
    const { title, url } = serpPreview;
    setSerpPreview(null);
    setSharing(true);
    try {
      if (navigator.share) {
        await navigator.share({ title, url });
      } else {
        await navigator.clipboard.writeText(url);
        toast.success('Link copied to clipboard!');
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        try {
          await navigator.clipboard.writeText(url);
          toast.success('Link copied to clipboard!');
        } catch {
          toast.error('Unable to share');
        }
      }
    } finally {
      setSharing(false);
    }
  }, [serpPreview]);

  const dismissPreview = useCallback(() => {
    setSerpPreview(null);
  }, []);

  return { sharing, share, serpPreview, confirmShare, dismissPreview };
}

export function SerpPreviewModal({ preview, onConfirm, onDismiss }) {
  if (!preview) return null;
  const displayUrl = preview.url.replace(/^https?:\/\//, '').replace(/\/$/, '');
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onDismiss}>
      <div
        className="w-full max-w-lg rounded-2xl overflow-hidden"
        style={{ background: '#1a1a2e', border: '1px solid rgba(139,92,246,0.2)' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="p-4 border-b border-white/5">
          <p className="text-xs font-semibold text-white/40 uppercase tracking-wider">SERP Preview</p>
        </div>
        <div className="p-5">
          <div className="rounded-xl p-4" style={{ background: '#fff' }}>
            <p className="text-xs text-[#202124] mb-0.5" style={{ fontFamily: 'Arial, sans-serif' }}>{displayUrl}</p>
            <p className="text-lg leading-tight mb-1" style={{ color: '#1a0dab', fontFamily: 'Arial, sans-serif' }}>
              {preview.title}
            </p>
            {preview.description && (
              <p className="text-sm leading-relaxed line-clamp-2" style={{ color: '#4d5156', fontFamily: 'Arial, sans-serif' }}>
                {preview.description}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 p-4 border-t border-white/5">
          <button
            onClick={onDismiss}
            className="flex-1 h-10 rounded-xl text-sm font-medium text-white/60 hover:text-white transition-colors"
            style={{ border: '1px solid rgba(255,255,255,0.1)' }}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 h-10 rounded-xl text-sm font-semibold text-white transition-all hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)' }}
          >
            Share
          </button>
        </div>
      </div>
    </div>
  );
}
