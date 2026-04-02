import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { API_BASE, setAuthToken } from '@/utils/api';

const AuthContext = createContext(null);

let _inMemoryToken = null;

export const getInMemoryToken = () => _inMemoryToken;

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
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
    }
  }, []);

  useEffect(() => {
    const init = async () => {
      const savedToken = sessionStorage.getItem('syrabit_token');
      if (savedToken) {
        _inMemoryToken = savedToken;
        setAuthToken(savedToken);
      }
      await fetchMe();
      setLoading(false);
    };
    init();
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
    try {
      const { Analytics } = await import('@/utils/analytics');
      Analytics.login(userData.id, userData.email);
    } catch {}
    return userData;
  };

  const signup = async (name, email, password) => {
    const res = await axios.post(`${API_BASE}/auth/signup`, {
      name, email, password,
    }, { withCredentials: true });
    const { user: userData, access_token } = res.data;
    if (access_token) _storeToken(access_token);
    justAuthenticated.current = true;
    setUser(userData);
    try {
      const { Analytics } = await import('@/utils/analytics');
      Analytics.signup(userData.email, userData.plan);
    } catch {}
    return userData;
  };

  const googleLogin = async (credential) => {
    const res = await axios.post(`${API_BASE}/auth/google`, { credential }, { withCredentials: true });
    const { user: userData, access_token } = res.data;
    if (access_token) _storeToken(access_token);
    justAuthenticated.current = true;
    setUser(userData);
    try {
      const { Analytics } = await import('@/utils/analytics');
      Analytics.login(userData.id, userData.email);
    } catch {}
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
    try {
      import('@/utils/analytics').then(({ Analytics }) => Analytics.logout());
    } catch {}
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
