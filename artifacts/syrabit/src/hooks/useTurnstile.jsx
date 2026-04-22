import { useEffect, useRef, useCallback, useState } from 'react';

const SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || '';
const SCRIPT_ID = 'cf-turnstile-script';

let scriptLoadPromise = null;

function loadTurnstileScript() {
  if (scriptLoadPromise) return scriptLoadPromise;
  if (window.turnstile) return Promise.resolve();
  scriptLoadPromise = new Promise((resolve, reject) => {
    const existing = document.getElementById(SCRIPT_ID);
    if (existing) { resolve(); return; }
    const script = document.createElement('script');
    script.id = SCRIPT_ID;
    script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    script.async = true;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
  return scriptLoadPromise;
}

/**
 * @param {{ skip?: boolean }} [opts]
 *   skip — when true, do NOT load the Turnstile script or render the widget.
 *          Used to avoid an extra ~50KB script + invisible-widget for
 *          authenticated users (who never have to solve a challenge).
 *          Task #282 T001.
 */
export function useTurnstile({ skip = false } = {}) {
  const widgetIdRef = useRef(null);
  const containerRef = useRef(null);
  const tokenRef = useRef('');
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!SITE_KEY) return;
    if (skip) return;
    let cancelled = false;

    loadTurnstileScript().then(() => {
      if (cancelled || !window.turnstile) return;

      const container = document.createElement('div');
      container.style.display = 'none';
      document.body.appendChild(container);
      containerRef.current = container;

      widgetIdRef.current = window.turnstile.render(container, {
        sitekey: SITE_KEY,
        size: 'invisible',
        execution: 'execute',
        callback: (token) => { tokenRef.current = token; },
        'expired-callback': () => { tokenRef.current = ''; },
        'error-callback': () => { tokenRef.current = ''; },
      });
      setReady(true);
    }).catch(() => {});

    return () => {
      cancelled = true;
      if (widgetIdRef.current != null && window.turnstile) {
        try { window.turnstile.remove(widgetIdRef.current); } catch {}
      }
      if (containerRef.current) {
        try { containerRef.current.remove(); } catch {}
      }
    };
  }, [skip]);

  const getToken = useCallback(async () => {
    if (!SITE_KEY || !window.turnstile || widgetIdRef.current == null) return '';
    try {
      tokenRef.current = '';
      window.turnstile.execute(widgetIdRef.current);
      for (let i = 0; i < 50; i++) {
        if (tokenRef.current) break;
        await new Promise(r => setTimeout(r, 100));
      }
      const t = tokenRef.current;
      tokenRef.current = '';
      if (t) window.turnstile.reset(widgetIdRef.current);
      return t;
    } catch {
      return '';
    }
  }, []);

  const reset = useCallback(() => {
    if (!window.turnstile || widgetIdRef.current == null) return;
    try { window.turnstile.reset(widgetIdRef.current); } catch {}
    tokenRef.current = '';
  }, []);

  // When skipped (authenticated user), report ready=true and enabled=false
  // so call sites don't gate their UX on a widget that was never loaded.
  if (skip) {
    return { getToken: async () => '', ready: true, enabled: false, reset: () => {} };
  }
  return { getToken, ready: SITE_KEY ? ready : true, enabled: !!SITE_KEY, reset };
}
