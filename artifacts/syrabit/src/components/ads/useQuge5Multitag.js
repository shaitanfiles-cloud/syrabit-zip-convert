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
 * `syrabit_ads_optout` localStorage flag and the Task #552 paid-plan
 * gate). Dev builds, opted-out users, and paying subscribers never
 * see this script.
 *
 * Consent is reactive: the hook listens for
 * `syrabit:ads-consent-changed` and re-evaluates. If consent flips
 * to false mid-session, the previously injected script tag is removed.
 * If it later flips back to true, the script is re-injected.
 *
 * The script is appended to <head> at most once per page (de-duped by
 * `src` against both an in-module Set and the live DOM).
 */
import { useEffect } from 'react';
import { adsConsentGranted } from '@/utils/adsConfig';

const QUGE5_SRC = 'https://quge5.com/88/tag.min.js';
const QUGE5_ZONE = '231351';

const _injected = new Set();

function removeInjectedQuge5() {
  if (typeof document === 'undefined') return;
  const tags = document.querySelectorAll(`script[src="${QUGE5_SRC}"]`);
  tags.forEach((t) => {
    try {
      if (t.parentNode) t.parentNode.removeChild(t);
    } catch {
      /* ignore */
    }
  });
  _injected.delete(QUGE5_SRC);
}

function injectQuge5() {
  if (typeof document === 'undefined') return null;
  if (_injected.has(QUGE5_SRC)) return null;
  if (document.querySelector(`script[src="${QUGE5_SRC}"]`)) {
    _injected.add(QUGE5_SRC);
    return null;
  }
  const s = document.createElement('script');
  s.src = QUGE5_SRC;
  s.async = true;
  s.setAttribute('data-zone', QUGE5_ZONE);
  s.setAttribute('data-cfasync', 'false');
  document.head.appendChild(s);
  _injected.add(QUGE5_SRC);
  return s;
}

export default function useQuge5Multitag() {
  useEffect(() => {
    if (typeof document === 'undefined') return undefined;
    let mounted = true;

    const apply = () => {
      if (!mounted) return;
      if (adsConsentGranted()) {
        injectQuge5();
      } else {
        removeInjectedQuge5();
      }
    };

    apply();
    window.addEventListener('syrabit:ads-consent-changed', apply);

    return () => {
      mounted = false;
      window.removeEventListener('syrabit:ads-consent-changed', apply);
      removeInjectedQuge5();
    };
  }, []);
}
