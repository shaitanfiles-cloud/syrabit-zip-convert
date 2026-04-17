import { useEffect, useRef, useState } from 'react';
import { isAdsAllowed } from './ads/adsConfig';

/**
 * Google AdSense in-feed native unit.
 *
 * Mirrors the lazy-init pattern of `InArticleAd`: the AdSense loader script
 * is deferred from `index.html` until LCP, so `window.adsbygoogle` may not
 * exist when this component first mounts. Pushing into the queue is safe —
 * the loader drains it once it arrives.
 *
 * Viewability optimization: rather than push immediately on mount, we wait
 * until the `<ins>` element is within ~400px of the viewport before calling
 * `adsbygoogle.push({})`. AdSense weights viewable impressions higher, so
 * deferring the push until the slot is actually about to be seen lifts both
 * viewability rate and effective CPM. Pushes still happen exactly once per
 * mount (guarded by a ref) so StrictMode + route-change re-renders don't
 * trigger duplicate-push errors.
 */
export default function InFeedAd({
  client = 'ca-pub-8958003374183515',
  slot = '5324297294',
  layoutKey = '-ef+6k-30-ac+ty',
  adKey,
  className = '',
  style,
}) {
  const wrapRef = useRef(null);
  const pushed = useRef(false);
  const [intersected, setIntersected] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const node = wrapRef.current;
    if (!node) return;
    if (typeof IntersectionObserver === 'undefined') {
      setIntersected(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setIntersected(true);
            io.disconnect();
            break;
          }
        }
      },
      { rootMargin: '400px 0px' },
    );
    io.observe(node);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!intersected || pushed.current) return;
    pushed.current = true;
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch {
      /* AdSense will retry once the loader script arrives. */
    }
  }, [intersected, adKey]);

  if (typeof window !== 'undefined' && !isAdsAllowed(window.location?.pathname)) {
    return null;
  }

  return (
    <div
      ref={wrapRef}
      className={`w-full ${className}`}
      aria-label="Advertisement"
      style={{ minHeight: 200, ...style }}
    >
      <ins
        key={`${slot}-${adKey ?? ''}`}
        className="adsbygoogle"
        style={{ display: 'block' }}
        data-ad-format="fluid"
        data-ad-layout-key={layoutKey}
        data-ad-client={client}
        data-ad-slot={slot}
      />
    </div>
  );
}
