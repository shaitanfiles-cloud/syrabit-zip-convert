/**
 * useAdsenseAutoAds — page-level Google AdSense Auto Ads injector.
 *
 * AdSense's Auto Ads tag (`adsbygoogle.js?client=…`) is a single
 * page-level script that auto-discovers ad slots once loaded. It is
 * stacked alongside the existing Quge5 multitag on the only two
 * monetised routes: Notes (`/learn/:slug`) and PYQ (`/pyq/:slug`).
 * All other routes stay ad-free — see `scripts/verify-no-ads.mjs`.
 *
 * Gating mirrors `useQuge5Multitag` and `<AdSlot />`: production
 * build only AND `adsConsentGranted()` true (which also honours the
 * `syrabit_ads_optout` localStorage flag). Dev builds and opted-out
 * users never see this script.
 *
 * The script is appended to <head> at most once per page (de-duped by
 * `src` against both an in-module Set and the live DOM). On unmount,
 * the tag we appended is removed so navigating to an ad-free route
 * does not leave AdSense loaded in memory.
 */
import { useEffect } from 'react';
import { adsConsentGranted } from '@/utils/adsConfig';

const ADSENSE_CLIENT = 'ca-pub-8958003374183515';
const ADSENSE_SRC = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT}`;

const _injected = new Set();

export default function useAdsenseAutoAds() {
  useEffect(() => {
    if (typeof document === 'undefined') return;
    if (!adsConsentGranted()) return;

    if (_injected.has(ADSENSE_SRC)) return;
    if (document.querySelector(`script[src="${ADSENSE_SRC}"]`)) {
      _injected.add(ADSENSE_SRC);
      return;
    }

    const s = document.createElement('script');
    s.src = ADSENSE_SRC;
    s.async = true;
    s.crossOrigin = 'anonymous';
    s.setAttribute('data-ad-client', ADSENSE_CLIENT);
    document.head.appendChild(s);
    _injected.add(ADSENSE_SRC);

    return () => {
      try {
        if (s.parentNode) s.parentNode.removeChild(s);
      } catch {
        /* ignore */
      }
      _injected.delete(ADSENSE_SRC);
    };
  }, []);
}

export { ADSENSE_CLIENT, ADSENSE_SRC };
