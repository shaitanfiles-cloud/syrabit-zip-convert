import { useState, useEffect, useRef } from 'react';
import { useAuth } from '@/context/AuthContext';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import { API_BASE } from '@/utils/api';
import axios from 'axios';

const GOOGLE_G_SVG = (
  <svg width="18" height="18" viewBox="0 0 48 48">
    <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
    <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
    <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
    <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
  </svg>
);

export default function GoogleSignInButton({ mode = 'login' }) {
  const [loading, setLoading] = useState(false);
  const [clientId, setClientId] = useState(null);
  const [gsiReady, setGsiReady] = useState(false);
  const { googleLogin } = useAuth();
  const navigate = useNavigate();
  const callbackRef = useRef(null);
  const mountedRef = useRef(true);
  const btnContainerRef = useRef(null);

  callbackRef.current = async (response) => {
    if (!mountedRef.current) return;
    setLoading(true);
    try {
      const user = await googleLogin(response.credential);
      if (!mountedRef.current) return;
      toast.success(mode === 'signup' ? 'Account created! Welcome!' : 'Welcome back!');
      if (!user.onboarding_done) {
        navigate('/onboarding');
      } else {
        navigate('/library');
      }
    } catch (err) {
      if (!mountedRef.current) return;
      const detail = err.response?.data?.detail || 'Google sign-in failed. Please try again.';
      toast.error(detail);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    axios.get(`${API_BASE}/auth/google/client-id`).then(res => {
      if (!cancelled && res.data?.client_id) {
        setClientId(res.data.client_id);
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!clientId) return;

    let interval;
    let timeout;

    const stableCallback = (response) => {
      callbackRef.current?.(response);
    };

    const initGsi = () => {
      if (!window.google?.accounts?.id) return false;
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: stableCallback,
        auto_select: false,
        cancel_on_tap_outside: true,
        use_fedcm_for_prompt: false,
        ux_mode: 'popup',
      });
      if (btnContainerRef.current) {
        window.google.accounts.id.renderButton(btnContainerRef.current, {
          type: 'standard',
          size: 'large',
          theme: 'filled_black',
          width: 300,
        });
      }
      setGsiReady(true);
      return true;
    };

    if (!initGsi()) {
      interval = setInterval(() => {
        if (initGsi()) clearInterval(interval);
      }, 200);
      timeout = setTimeout(() => { if (interval) clearInterval(interval); }, 10000);
    }

    return () => {
      if (interval) clearInterval(interval);
      if (timeout) clearTimeout(timeout);
    };
  }, [clientId]);

  if (!clientId) return null;

  const handleClick = () => {
    if (!gsiReady || loading) return;
    try {
      window.google.accounts.id.prompt((notification) => {
        if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
          const rendered = btnContainerRef.current?.querySelector('div[role="button"]');
          if (rendered) rendered.click();
        }
      });
    } catch {
      const rendered = btnContainerRef.current?.querySelector('div[role="button"]');
      if (rendered) rendered.click();
    }
  };

  return (
    <div className="w-full">
      <button
        type="button"
        onClick={handleClick}
        disabled={loading || !gsiReady}
        className="w-full flex items-center justify-center gap-3 h-11 rounded-xl text-sm font-semibold transition-all duration-150 active:scale-[0.97] disabled:opacity-60"
        style={{
          background: 'rgba(255,255,255,0.08)',
          border: '1px solid rgba(255,255,255,0.15)',
          color: 'rgba(255,255,255,0.90)',
        }}
        data-testid="google-signin-button"
      >
        {loading ? (
          <Loader2 size={17} className="animate-spin" />
        ) : (
          GOOGLE_G_SVG
        )}
        {loading ? 'Signing in...' : 'Continue with Google'}
      </button>

      <div className="flex items-center gap-3 mt-4">
        <div className="flex-1 h-px" style={{ background: 'rgba(255,255,255,0.10)' }} />
        <span className="text-xs font-medium" style={{ color: 'rgba(255,255,255,0.40)' }}>or</span>
        <div className="flex-1 h-px" style={{ background: 'rgba(255,255,255,0.10)' }} />
      </div>

      <div
        ref={btnContainerRef}
        className="overflow-hidden"
        style={{ height: 0, width: 0, opacity: 0, position: 'absolute', pointerEvents: 'none' }}
      />
    </div>
  );
}
