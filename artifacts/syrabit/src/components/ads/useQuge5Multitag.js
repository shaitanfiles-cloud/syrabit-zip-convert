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

// DISABLED 2026-04-19 — Quge5 network turned off site-wide as part of
// the "keep only AdSense" cleanup. The hook is kept (rather than
// deleted) so existing import sites in LearnPage / PYQReplicaPage
// keep building, but it is now a no-op AND it actively removes any
// Quge5 script tag a previously-cached bundle may have injected.
// To restore, `git checkout cdd0d7f5 -- src/components/ads/useQuge5Multitag.js`.
export default function useQuge5Multitag() {
  useEffect(() => {
    // Defensive cleanup: a previously-deployed bundle may have
    // injected the Quge5 script before this hot-update reached the
    // browser. Strip it on mount so live sessions clear immediately
    // instead of waiting for a hard reload.
    removeInjectedQuge5();
  }, []);
}
