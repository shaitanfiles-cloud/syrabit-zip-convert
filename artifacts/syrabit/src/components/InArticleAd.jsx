import { useEffect, useRef } from 'react';

/**
 * Google AdSense in-article fluid unit.
 *
 * The AdSense loader script is lazy-injected from index.html after the
 * first user interaction, so `window.adsbygoogle` may not exist yet when
 * this component mounts — that's fine: pushing into the array gets
 * consumed by the loader once it arrives.
 *
 * We guard against double-push (StrictMode dev / re-renders) with a ref,
 * and key the `<ins>` element by the consumer-supplied `slot`+`adKey`
 * so navigating between chapters re-initializes a fresh slot.
 */
export default function InArticleAd({
  client = 'ca-pub-8958003374183515',
  slot = '8964159403',
  adKey,
  className = '',
  style,
}) {
  const pushed = useRef(false);

  useEffect(() => {
    if (pushed.current) return;
    pushed.current = true;
    try {
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch {
      /* AdSense will retry once the loader script arrives. */
    }
  }, [adKey]);

  return (
    <div
      className={`my-8 w-full ${className}`}
      aria-label="Advertisement"
      style={style}
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
