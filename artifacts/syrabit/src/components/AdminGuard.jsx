import { useState, useEffect } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { adminVerify } from '@/utils/api';

const MAX_VERIFY_ATTEMPTS = 3;
const RETRY_DELAY_MS = 800;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const AdminGuard = ({ children }) => {
  const [status, setStatus] = useState('checking'); // 'checking' | 'ok' | 'denied'

  useEffect(() => {
    let cancelled = false;

    const verify = async () => {
      // Small delay to ensure localStorage is fully hydrated after a redirect
      // from the login page (e.g. React Router navigation + storage flush).
      await sleep(50);

      const token = localStorage.getItem('admin_token');

      if (!token) {
        console.warn('[AdminGuard] No admin_token found in localStorage — redirecting to login.');
        if (!cancelled) setStatus('denied');
        return;
      }

      const parts = token.split('.');
      if (parts.length !== 3) {
        console.warn('[AdminGuard] admin_token does not look like a valid JWT (expected 3 parts, got %d) — redirecting to login.', parts.length);
        if (!cancelled) setStatus('denied');
        return;
      }

      for (let attempt = 1; attempt <= MAX_VERIFY_ATTEMPTS; attempt++) {
        try {
          await adminVerify(token);
          console.info('[AdminGuard] Token verified successfully on attempt %d.', attempt);
          if (!cancelled) setStatus('ok');
          return;
        } catch (err) {
          const status = err?.response?.status;
          console.warn('[AdminGuard] Verify attempt %d/%d failed — status: %s, message: %s', attempt, MAX_VERIFY_ATTEMPTS, status ?? 'network error', err?.message);

          // A 401/403 means the token is definitively rejected by the server.
          // No point retrying — redirect immediately.
          if (status === 401 || status === 403) {
            console.error('[AdminGuard] Server rejected token (HTTP %d) — redirecting to login.', status);
            if (!cancelled) setStatus('denied');
            return;
          }

          if (attempt < MAX_VERIFY_ATTEMPTS) {
            await sleep(RETRY_DELAY_MS * attempt);
          }
        }
      }

      console.error('[AdminGuard] All %d verify attempts failed — redirecting to login.', MAX_VERIFY_ATTEMPTS);
      if (!cancelled) setStatus('denied');
    };

    verify();

    return () => {
      cancelled = true;
    };
  }, []);

  if (status === 'checking') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-6 h-6 border-2 rounded-full animate-spin" style={{ borderColor: 'hsl(var(--primary))', borderTopColor: 'transparent' }} />
      </div>
    );
  }

  if (status === 'denied') {
    return <Navigate to="/admin/login" replace />;
  }

  return children || <Outlet />;
};
