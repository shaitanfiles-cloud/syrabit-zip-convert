import { useEffect, useRef, useState } from 'react';
import { AD_CLIENT, AD_SLOTS, isAdsAllowed } from './adsConfig';

/**
 * Generic AdSense slot (Task #401).
 *
 * Variants are looked up from `adsConfig.js` so all placements share one
 * source of truth. Behaviour:
 *
 *   1. The <ins data-ad-...> element is rendered ON FIRST RENDER, so it
 *      shows up in the SSR / prerender HTML — required by the task spec
 *      (crawlers must see ad markup) and necessary for AdSense's own
 *      crawler to inspect placements without booting React.
 *   2. Calling `(adsbygoogle = adsbygoogle || []).push({})` is deferred
 *      until the slot is within ~400px of the viewport, mirroring the
 *      existing InArticleAd pattern. AdSense pays more for viewable
 *      impressions, and deferring the push avoids racing the lazy-loaded
 *      `adsbygoogle.js` (gated on LCP from index.html).
 *   3. A min-height reservation is applied to the wrapper so the slot
 *      never causes CLS > 0.1 even before the ad fills.
 *   4. The component refuses to render anything on policy-denied routes
 *      (auth/payment/admin/profile) so manual placements never leak onto
 *      surfaces excluded from monetization.
 */
export default function AdSlot({
  variant = 'inArticle',
  adKey,
  className = '',
  style,
  pathname,
  responsive,
  testId,
  eager = false,
}) {
  const cfg = AD_SLOTS[variant];
  const ssr = typeof window === 'undefined';
  const path =
    pathname ||
    (ssr ? '' : window.location && window.location.pathname) ||
    '';
  const allowed = !!cfg && (!path || isAdsAllowed(path));

  const wrapRef = useRef(null);
  const pushed = useRef(false);
  // eager=true: push immediately on mount (above-the-fold units — top
  // leaderboard, initial sidebar). Skips the IntersectionObserver gate
  // so AdSense has the longest possible window to fill before first
  // interaction / scroll.
  const [inView, setInView] = useState(ssr || eager);

  useEffect(() => {
    if (eager) return;
    if (typeof window === 'undefined') return;
    const node = wrapRef.current;
    if (!node) return;
    if (typeof IntersectionObserver === 'undefined') {
      setInView(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setInView(true);
            io.disconnect();
            break;
          }
        }
      },
      { rootMargin: '400px 0px' },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [eager]);

  useEffect(() => {
    if (!inView && !eager) return;
    if (pushed.current) return;
    if (!allowed) return;
    if (typeof window === 'undefined') return;
    pushed.current = true;
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch {
      /* loader script will retry once it arrives */
    }
  }, [inView, adKey, allowed, eager]);

  if (!allowed) return null;
  const minH = cfg.minHeight || 100;
  const wrapStyle = {
    minHeight: minH,
    ...style,
  };

  // Build <ins> attributes per variant.
  const insAttrs = {
    className: 'adsbygoogle',
    style: { display: 'block', textAlign: 'center', minHeight: minH },
    'data-ad-client': AD_CLIENT,
    'data-ad-slot': cfg.slot,
  };
  if (cfg.format) insAttrs['data-ad-format'] = cfg.format;
  if (cfg.layout) insAttrs['data-ad-layout'] = cfg.layout;
  if (cfg.layoutKey) insAttrs['data-ad-layout-key'] = cfg.layoutKey;
  if (cfg.fullWidthResponsive || responsive) {
    insAttrs['data-full-width-responsive'] = 'true';
  }

  return (
    <div
      ref={wrapRef}
      className={`ad-slot ad-slot-${variant} my-6 w-full ${className}`}
      aria-label="Advertisement"
      data-ad-variant={variant}
      data-testid={testId || `ad-slot-${variant}`}
      style={wrapStyle}
    >
      {/* Render <ins> on the server (SSR/prerender) AND once the slot is
          near the viewport on the client. */}
      <ins key={`${cfg.slot}-${adKey ?? ''}`} {...insAttrs} />
    </div>
  );
}
