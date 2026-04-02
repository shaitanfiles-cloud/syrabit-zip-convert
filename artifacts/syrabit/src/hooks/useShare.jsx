import { useState, useCallback } from 'react';
import { toast } from 'sonner';

export function useShare() {
  const [sharing, setSharing] = useState(false);

  const share = useCallback(async (title, url) => {
    if (sharing) return;
    setSharing(true);
    const siteOrigin = import.meta.env.VITE_SITE_URL || window.location.origin;
    const shareUrl = url.startsWith('http') ? url : `${siteOrigin}${url}`;
    try {
      if (navigator.share) {
        await navigator.share({ title, url: shareUrl });
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

  return { sharing, share };
}
