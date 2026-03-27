import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import axios from 'axios';
import { Analytics } from './analytics';

const API_BASE = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

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

export function usePageTracking() {
  const location = useLocation();
  const lastPath = useRef(null);

  useEffect(() => {
    const path = location.pathname;
    if (path === lastPath.current) return;
    lastPath.current = path;

    const visitorId = getOrCreateVisitorId();
    const referrer = document.referrer || null;

    // 1. Internal analytics (MongoDB)
    axios.post(
      `${API_BASE}/analytics/page-view`,
      { path, visitor_id: visitorId, referrer },
      { withCredentials: true }
    ).catch(() => {});

    // 2. PostHog + GA4 page view (via unified Analytics util)
    Analytics.pageView(path, document.title);
  }, [location.pathname]);
}

export function PageTracker() {
  usePageTracking();
  return null;
}
