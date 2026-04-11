import { useEffect, useRef } from 'react';
import { useLocation, matchPath } from 'react-router-dom';
import axios from 'axios';
import { Analytics } from './analytics';
import { API_BASE } from './api';

const KNOWN_PATTERNS = [
  '/',
  '/pricing',
  '/terms',
  '/privacy',
  '/exam-routine',
  '/payment/success',
  '/payment/cancel',
  '/login',
  '/signup',
  '/reset-password',
  '/onboarding',
  '/library',
  '/curriculum',
  '/subject/:subjectId',
  '/learn/:slug',
  '/chat',
  '/history',
  '/profile',
  '/admin/login',
  '/admin',
  '/:board/:classSlug/:subjectSlug/:topicSlug/:pageType',
  '/:board/:classSlug/:subjectSlug/:topicSlug',
  '/:board/:classSlug/:subjectSlug',
];

function detectIs404(pathname) {
  return !KNOWN_PATTERNS.some((pattern) => matchPath({ path: pattern, end: true }, pathname));
}

function getOrCreateVisitorId() {
  try {
    let vid = localStorage.getItem('syrabit:visitor_id');
    if (!vid) {
      vid = 'v_' + Math.random().toString(36).slice(2, 11) + Date.now().toString(36);
      localStorage.setItem('syrabit:visitor_id', vid);
    }
    return vid;
  } catch {
    return 'v_anon_' + Math.random().toString(36).slice(2, 11);
  }
}

function getOrCreateSessionId() {
  try {
    let sid = sessionStorage.getItem('syrabit:session_id');
    if (!sid) {
      sid = 's_' + Math.random().toString(36).slice(2, 11) + Date.now().toString(36);
      sessionStorage.setItem('syrabit:session_id', sid);
    }
    return sid;
  } catch {
    return 's_anon_' + Math.random().toString(36).slice(2, 11);
  }
}

let heartbeatInterval = null;
let lastSessionId = null;
let hiddenAt = null;

const SESSION_RESUME_WINDOW_MS = 30 * 60 * 1000;

function startHeartbeat(sessionId, visitorId) {
  if (heartbeatInterval) clearInterval(heartbeatInterval);
  lastSessionId = sessionId;

  const sendPing = () => {
    const sid = sessionStorage.getItem('syrabit:session_id') || sessionId;
    const vid = localStorage.getItem('syrabit:visitor_id') || visitorId;
    axios.post(
      `${API_BASE}/analytics/session-ping`,
      { session_id: sid, visitor_id: vid },
      { withCredentials: true }
    ).catch(() => {});
  };

  heartbeatInterval = setInterval(sendPing, 30000);
}

function sendSessionEnd(sessionId, visitorId, endTimestamp) {
  const sid = sessionId || lastSessionId || sessionStorage.getItem('syrabit:session_id');
  const vid = visitorId || localStorage.getItem('syrabit:visitor_id');
  if (sid && vid) {
    const payload = { session_id: sid, visitor_id: vid };
    if (endTimestamp) {
      payload.end_timestamp = new Date(endTimestamp).toISOString();
    }
    const blob = new Blob(
      [JSON.stringify(payload)],
      { type: 'application/json' }
    );
    navigator.sendBeacon(`${API_BASE}/analytics/session-end`, blob);
  }
}

function stopHeartbeatAndSendEnd(sessionId, visitorId) {
  if (heartbeatInterval) {
    clearInterval(heartbeatInterval);
    heartbeatInterval = null;
  }
  sendSessionEnd(sessionId, visitorId);
}

export function usePageTracking() {
  const location = useLocation();
  const lastPath = useRef(null);
  const sessionIdRef = useRef(null);
  const visitorIdRef = useRef(null);

  useEffect(() => {
    const visitorId = getOrCreateVisitorId();
    const sessionId = getOrCreateSessionId();
    visitorIdRef.current = visitorId;
    sessionIdRef.current = sessionId;

    startHeartbeat(sessionId, visitorId);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        if (heartbeatInterval) {
          clearInterval(heartbeatInterval);
          heartbeatInterval = null;
        }
        hiddenAt = Date.now();
      } else {
        const elapsed = hiddenAt ? Date.now() - hiddenAt : 0;
        hiddenAt = null;
        if (elapsed > SESSION_RESUME_WINDOW_MS) {
          const actualEndTime = Date.now() - elapsed;
          sendSessionEnd(sessionIdRef.current, visitorIdRef.current, actualEndTime);
          try { sessionStorage.removeItem('syrabit:session_id'); } catch {}
          const newSid = getOrCreateSessionId();
          sessionIdRef.current = newSid;
          lastSessionId = newSid;

          const currentPath = window.location.pathname;
          axios.post(
            `${API_BASE}/analytics/page-view`,
            {
              path: currentPath,
              visitor_id: visitorIdRef.current,
              session_id: newSid,
              referrer: document.referrer || null,
              user_agent: navigator.userAgent,
              screen_width: window.screen.width,
              is_404_hint: detectIs404(currentPath),
            },
            { withCredentials: true }
          ).catch(() => {});
        }
        startHeartbeat(sessionIdRef.current, visitorIdRef.current);
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      stopHeartbeatAndSendEnd(sessionIdRef.current, visitorIdRef.current);
    };
  }, []);

  useEffect(() => {
    const path = location.pathname;
    if (path === lastPath.current) return;
    lastPath.current = path;

    const visitorId = getOrCreateVisitorId();
    const sessionId = getOrCreateSessionId();
    sessionIdRef.current = sessionId;
    visitorIdRef.current = visitorId;
    const referrer = document.referrer || null;
    const is404Hint = detectIs404(path);

    axios.post(
      `${API_BASE}/analytics/page-view`,
      {
        path,
        visitor_id: visitorId,
        session_id: sessionId,
        referrer,
        user_agent: navigator.userAgent,
        screen_width: window.screen.width,
        is_404_hint: is404Hint,
      },
      { withCredentials: true }
    ).catch(() => {});

    Analytics.pageView(path, document.title);
  }, [location.pathname]);
}

export function PageTracker() {
  usePageTracking();
  return null;
}
