import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';

const GIS_SRC = 'https://accounts.google.com/gsi/client';

let _scriptPromise = null;
function loadGisScript() {
  if (_scriptPromise) return _scriptPromise;
  _scriptPromise = new Promise((resolve, reject) => {
    if (typeof window === 'undefined') return reject(new Error('window unavailable'));
    if (window.google?.accounts?.id) return resolve();

    const existing = document.querySelector(`script[src="${GIS_SRC}"]`);
    if (existing) {
      existing.addEventListener('load', () => resolve());
      existing.addEventListener('error', () =>
        reject(new Error('Failed to load Google Identity Services'))
      );
      return;
    }

    const s = document.createElement('script');
    s.src = GIS_SRC;
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('Failed to load Google Identity Services'));
    document.head.appendChild(s);
  });
  return _scriptPromise;
}

let _clientIdPromise = null;
function fetchClientId(apiBase) {
  if (_clientIdPromise) return _clientIdPromise;
  _clientIdPromise = axios
    .get(`${apiBase}/auth/google/client-id`)
    .then((r) => r.data?.client_id || null)
    .catch(() => null);
  return _clientIdPromise;
}

export default function GoogleSignInButton({
  text = 'signin_with',
  onSuccess,
  onError,
  getTurnstileToken,
  disabled = false,
}) {
  const { googleLogin, API } = useAuth();
  const containerRef = useRef(null);
  const [state, setState] = useState('loading');
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  busyRef.current = busy;

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const clientId = await fetchClientId(API);
        if (cancelled) return;
        if (!clientId) {
          setState('unavailable');
          return;
        }

        await loadGisScript();
        if (cancelled) return;
        if (!window.google?.accounts?.id || !containerRef.current) {
          setState('error');
          return;
        }

        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: async (response) => {
            if (busyRef.current) return;
            setBusy(true);
            try {
              let ttoken = '';
              if (typeof getTurnstileToken === 'function') {
                try {
                  ttoken = await getTurnstileToken();
                } catch {
                  ttoken = '';
                }
              }
              const user = await googleLogin(response.credential, ttoken);
              if (!cancelled) onSuccess?.(user);
            } catch (err) {
              if (!cancelled) onError?.(err);
            } finally {
              if (!cancelled) setBusy(false);
            }
          },
          ux_mode: 'popup',
          auto_select: false,
          itp_support: true,
          context: text === 'signup_with' ? 'signup' : 'signin',
        });

        const width = Math.max(
          240,
          Math.min(400, containerRef.current.offsetWidth || 320)
        );

        window.google.accounts.id.renderButton(containerRef.current, {
          type: 'standard',
          theme: 'outline',
          size: 'large',
          text,
          shape: 'rectangular',
          logo_alignment: 'left',
          width,
        });

        setState('ready');
      } catch (e) {
        if (!cancelled) setState('error');
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (state === 'unavailable') return null;

  if (state === 'error') {
    return (
      <p className="text-xs text-muted-foreground text-center py-2">
        Google sign-in is temporarily unavailable — please use email and password below.
      </p>
    );
  }

  return (
    <div className="relative w-full flex justify-center">
      <div
        ref={containerRef}
        className={
          disabled || busy
            ? 'pointer-events-none opacity-60 w-full flex justify-center'
            : 'w-full flex justify-center'
        }
        style={{ minHeight: 44 }}
      />
      {(state === 'loading' || busy) && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <Loader2 size={16} className="animate-spin text-muted-foreground" />
        </div>
      )}
    </div>
  );
}
