/**
 * <AdSlot placement="..." /> — the only component allowed to inject a
 * third-party ad script on Syrabit.ai. All wiring lives in
 * `src/utils/adsConfig.js`.
 *
 * Behavior:
 *   - Reserves a fixed height before any script loads (no CLS).
 *   - Renders nothing when the placement is disabled (missing env var)
 *     OR consent is not granted OR the build is not production.
 *   - Lazy-loads the network's script with IntersectionObserver — the
 *     script tag is appended to <head> only once the slot is within
 *     ~200px of the viewport.
 *   - De-dupes scripts by URL so two slots on the same page never
 *     load the same script twice.
 */
import { useEffect, useRef, useState } from 'react';
import { getAdConfig, adsConsentGranted } from '@/utils/adsConfig';

// Scripts injected this session, keyed by URL. Survives across mounts
// because it lives on the module, not on a component instance.
const _injected = new Set();

function injectScript(url) {
  if (typeof document === 'undefined') return;
  if (_injected.has(url)) return;
  // Also de-dupe against any matching script already in the DOM (e.g.
  // injected by a sibling slot before this module's Set was hydrated).
  const existing = document.querySelector(`script[src="${url}"]`);
  if (existing) { _injected.add(url); return; }
  const s = document.createElement('script');
  s.src = url;
  s.async = true;
  s.dataset.syrabitAd = '1';
  document.head.appendChild(s);
  _injected.add(url);
}

export default function AdSlot({ placement, className = '', style = {} }) {
  const cfg = getAdConfig(placement);
  const ref = useRef(null);
  const [shouldLoad, setShouldLoad] = useState(false);
  const [consentOk, setConsentOk] = useState(false);

  // Resolve consent on the client. Avoids SSR/hydration mismatch
  // because `adsConsentGranted()` reads localStorage and import.meta.env.PROD.
  useEffect(() => {
    setConsentOk(adsConsentGranted());
  }, []);

  // Lazy-load the network script once the slot scrolls near the viewport.
  useEffect(() => {
    if (!cfg.enabled || !consentOk) return;
    const el = ref.current;
    if (!el || typeof window === 'undefined') return;
    if (typeof IntersectionObserver === 'undefined') {
      setShouldLoad(true);
      return;
    }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setShouldLoad(true);
        io.disconnect();
      }
    }, { rootMargin: '200px' });
    io.observe(el);
    return () => io.disconnect();
  }, [cfg.enabled, consentOk]);

  useEffect(() => {
    if (!shouldLoad || !cfg.enabled) return;
    injectScript(cfg.scriptUrl);
  }, [shouldLoad, cfg.enabled, cfg.scriptUrl]);

  // Disabled placements collapse completely — no reserved space, no DOM
  // beyond an empty fragment. Required so /chat, /library, /browser, and
  // chapter routes never reserve ad real-estate even if a contributor
  // accidentally drops an <AdSlot /> there. Same collapse policy applies
  // when consent is denied / build is not production: per the task spec
  // ("when disabled, the slot collapses with no reserved space"), a
  // user who has not granted ad consent must see zero reserved height.
  if (!cfg.enabled || !consentOk) return null;

  return (
    <div
      ref={ref}
      className={className}
      data-ad-placement={placement}
      data-ad-network={cfg.network}
      aria-label={cfg.label || 'Advertisement'}
      style={{
        minHeight: `${cfg.height}px`,
        width: '100%',
        display: 'block',
        margin: '16px 0',
        ...style,
      }}
    >
      {/* The network's injected script populates this container. We
          give it a deterministic id so the network can target it. */}
      <div
        id={`syrabit-ad-${placement.replace(/\./g, '-')}`}
        data-slot-id={cfg.slotId}
        data-publisher-id={cfg.publisherId || undefined}
        style={{ minHeight: `${cfg.height}px`, width: '100%' }}
      />
    </div>
  );
}
