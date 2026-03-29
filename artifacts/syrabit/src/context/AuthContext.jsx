import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API_BASE } from '@/utils/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchMe = useCallback(async () => {
    try {
      const res = await axios.get(`${API_BASE}/auth/me`, { withCredentials: true });
      setUser(res.data);
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    const init = async () => {
      await fetchMe();
      setLoading(false);
    };
    init();
  }, [fetchMe]);

  const login = async (email, password) => {
    const res = await axios.post(`${API_BASE}/auth/login`, { email, password }, { withCredentials: true });
    const { user: userData } = res.data;
    setUser(userData);
    try {
      const { Analytics } = await import('@/utils/analytics');
      Analytics.login(userData.id, userData.email);
    } catch {}
    return userData;
  };

  const signup = async (name, email, password) => {
    const res = await axios.post(`${API_BASE}/auth/signup`, { name, email, password }, { withCredentials: true });
    const { user: userData } = res.data;
    setUser(userData);
    try {
      const { Analytics } = await import('@/utils/analytics');
      Analytics.signup(userData.email, userData.plan);
    } catch {}
    return userData;
  };

  const logout = async () => {
    try {
      await axios.post(`${API_BASE}/auth/logout`, {}, { withCredentials: true });
    } catch {}
    localStorage.removeItem('syrabit:onboarding');
    setUser(null);
    try {
      import('@/utils/analytics').then(({ Analytics }) => Analytics.logout());
    } catch {}
  };

  const refreshUser = async () => {
    await fetchMe();
  };

  return (
    <AuthContext.Provider value={{
      user,
      token: null,
      loading,
      login,
      signup,
      logout,
      refreshUser,
      authHeader: {},
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
