import { useEffect, useRef, useState } from 'react';
import { isAdsAllowed } from './ads/adsConfig';

/**
 * Google AdSense in-article fluid unit.
 *
 * The AdSense loader script is lazy-injected from index.html after LCP,
 * so `window.adsbygoogle` may not exist yet when this component mounts —
 * that's fine: pushing into the array gets consumed by the loader once it
 * arrives.
 *
 * Viewability optimization: we delay calling `push({})` until the slot is
 * within ~400px of the viewport (IntersectionObserver). Ads that get a
 * chance to actually render in view earn materially higher CPMs from
 * AdSense than ads that are pushed but never seen. We still guard against
 * double-push (StrictMode dev / re-renders) with a ref, and key the
 * `<ins>` element by the consumer-supplied `slot`+`adKey` so navigating
 * between chapters re-initializes a fresh slot.
 */
export default function InArticleAd({
  client = 'ca-pub-8958003374183515',
  slot = '8964159403',
  adKey,
  className = '',
  style,
}) {
  const wrapRef = useRef(null);
  const pushed = useRef(false);
  const [intersected, setIntersected] = useState(false);

  // SSR-visibility: render the <ins> tag in the initial / prerendered HTML
  // so AdSense crawlers + Lighthouse see the slot. push() is still deferred
  // until the slot intersects the viewport for higher viewability CPM.
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

  // Client-side denylist gate. SSR is allow-by-default for the loader's
  // benefit; on hydration we hide the slot if the route is denied.
  if (typeof window !== 'undefined' && !isAdsAllowed(window.location?.pathname)) {
    return null;
  }

  return (
    <div
      ref={wrapRef}
      className={`my-8 w-full ${className}`}
      aria-label="Advertisement"
      style={{ minHeight: 250, ...style }}
    >
      <ins
        key={`${slot}-${adKey ?? ''}`}
        className="adsbygoogle"
        style={{ display: 'block', textAlign: 'center' }}
        data-ad-layout="in-article"
        data-ad-format="fluid"
        data-ad-client={client}
        data-ad-slot={slot}
      />
    </div>
  );
}
