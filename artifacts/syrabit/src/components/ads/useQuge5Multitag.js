/**
 * useQuge5Multitag — page-level multitag injector for the Quge5 network.
 *
 * Quge5's "multitag rich" tag is a single page-level script (not a
 * placement) that auto-discovers ad slots once loaded. It must only run
 * on the two monetised routes: Notes (`/learn/:slug`) and PYQ
 * (`/pyq/:slug`). All other routes stay ad-free.
 *
 * Gating mirrors `<AdSlot />`: production build only AND
 * `adsConsentGranted()` true (which also honours the
 * `syrabit_ads_optout` localStorage flag). Dev builds and opted-out
 * users never see this script.
 *
 * The script is appended to <head> at most once per page (de-duped by
 * `src` against both an in-module Set and the live DOM). On unmount,
 * the tag we appended is removed so navigating to an ad-free route
 * does not leave Quge5 loaded in memory.
 */
import { useEffect } from 'react';
import { adsConsentGranted } from '@/utils/adsConfig';

const QUGE5_SRC = 'https://quge5.com/88/tag.min.js';
const QUGE5_ZONE = '231351';

const _injected = new Set();

export default function useQuge5Multitag() {
  useEffect(() => {
    if (typeof document === 'undefined') return;
    if (!adsConsentGranted()) return;

    if (_injected.has(QUGE5_SRC)) return;
    if (document.querySelector(`script[src="${QUGE5_SRC}"]`)) {
      _injected.add(QUGE5_SRC);
      return;
    }

    const s = document.createElement('script');
    s.src = QUGE5_SRC;
    s.async = true;
    s.setAttribute('data-zone', QUGE5_ZONE);
    s.setAttribute('data-cfasync', 'false');
    document.head.appendChild(s);
    _injected.add(QUGE5_SRC);

    return () => {
      try {
        if (s.parentNode) s.parentNode.removeChild(s);
      } catch {
        /* ignore */
      }
      _injected.delete(QUGE5_SRC);
    };
  }, []);
}
