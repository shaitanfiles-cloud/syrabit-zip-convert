import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { API_BASE, setAuthToken } from '@/utils/api';
import { Analytics } from '@/utils/analytics';
import { hydrateAdsOptOutFromServer } from '@/utils/adsConfig';

const AuthContext = createContext(null);

let _inMemoryToken = null;

export const getInMemoryToken = () => _inMemoryToken;

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authChecked, setAuthChecked] = useState(false);
  const justAuthenticated = useRef(false);

  const fetchMe = useCallback(async () => {
    try {
      const headers = _inMemoryToken
        ? { Authorization: `Bearer ${_inMemoryToken}` }
        : {};
      const res = await axios.get(`${API_BASE}/auth/me`, {
        withCredentials: true,
        headers,
      });
      const userData = res.data;
      if (userData && userData.id) {
        setUser(userData);
        // Task #530: rehydrate the local ad opt-out flag from the
        // server so cookie-restored sessions and signed-in returning
        // users immediately apply their cross-device choice on every
        // ad-bearing route, not just /profile.
        hydrateAdsOptOutFromServer(userData.ads_opt_out);
      } else {
        setUser(null);
      }
      justAuthenticated.current = false;
      return !!(userData && userData.id);
    } catch {
      if (!justAuthenticated.current) {
        setUser(null);
      }
      return false;
    } finally {
      setAuthChecked(true);
    }
  }, []);

  useEffect(() => {
    const savedToken = sessionStorage.getItem('syrabit_token');
    setLoading(false);
    if (savedToken) {
      _inMemoryToken = savedToken;
      setAuthToken(savedToken);
      // Returning logged-in user this session — fetch immediately so
      // user-gated UI (profile menu, credits) is correct on first paint.
      fetchMe();
      return;
    }
    // No in-memory token. Could be a brand-new anonymous visitor OR a
    // returning visitor whose only credential is an httpOnly cookie
    // (which we can't read from JS). The landing page UI does not need
    // user state for first paint — only the navbar login/profile
    // toggle does, and that can flip after LCP.
    //
    // So mark auth as checked synchronously (treat as anonymous) and
    // probe /auth/me lazily after first paint. If a valid cookie
    // exists, the navbar will hydrate to the logged-in state shortly
    // after; if not, no extra round-trip was paid.
    setAuthChecked(true);
    const probe = () => { fetchMe(); };
    if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
      window.requestIdleCallback(probe, { timeout: 1500 });
    } else {
      setTimeout(probe, 600);
    }
  }, [fetchMe]);

  const _storeToken = (token) => {
    _inMemoryToken = token;
    setAuthToken(token);
    if (token) {
      sessionStorage.setItem('syrabit_token', token);
    } else {
      sessionStorage.removeItem('syrabit_token');
    }
  };

  const login = async (email, password) => {
    const res = await axios.post(`${API_BASE}/auth/login`, { email, password }, { withCredentials: true });
    const { user: userData, access_token } = res.data;
    if (access_token) _storeToken(access_token);
    justAuthenticated.current = true;
    setUser(userData);
    hydrateAdsOptOutFromServer(userData?.ads_opt_out);
    try { Analytics.login(userData.id, userData.email); } catch {}
    return userData;
  };

  const signup = async (name, email, password, consent_dpdp = false) => {
    const res = await axios.post(`${API_BASE}/auth/signup`, {
      name, email, password, consent_dpdp,
    }, { withCredentials: true });
    const { user: userData, access_token } = res.data;
    if (access_token) _storeToken(access_token);
    justAuthenticated.current = true;
    setUser(userData);
    hydrateAdsOptOutFromServer(userData?.ads_opt_out);
    try { Analytics.signup(userData.email, userData.plan); } catch {}
    return userData;
  };

  const googleLogin = async (credential) => {
    const res = await axios.post(`${API_BASE}/auth/google`, { credential }, { withCredentials: true });
    const { user: userData, access_token } = res.data;
    if (access_token) _storeToken(access_token);
    justAuthenticated.current = true;
    setUser(userData);
    hydrateAdsOptOutFromServer(userData?.ads_opt_out);
    try { Analytics.login(userData.id, userData.email); } catch {}
    return userData;
  };

  const logout = async () => {
    try {
      await axios.post(`${API_BASE}/auth/logout`, {}, { withCredentials: true });
    } catch {}
    _storeToken(null);
    justAuthenticated.current = false;
    localStorage.removeItem('syrabit:onboarding');
    setUser(null);
    try { Analytics.logout(); } catch {}
  };

  const refreshUser = async () => {
    return await fetchMe();
  };

  const updateUser = useCallback((updates) => {
    setUser((prev) => (prev ? { ...prev, ...updates } : prev));
  }, []);

  return (
    <AuthContext.Provider value={{
      user,
      token: _inMemoryToken,
      loading,
      authChecked,
      login,
      signup,
      googleLogin,
      logout,
      refreshUser,
      updateUser,
      justAuthenticated,
      authHeader: _inMemoryToken ? { Authorization: `Bearer ${_inMemoryToken}` } : {},
      API: API_BASE,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
};
