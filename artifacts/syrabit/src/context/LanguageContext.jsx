import { createContext, useContext, useState, useCallback, useEffect } from 'react';

const LanguageContext = createContext(null);

const STORAGE_KEY = 'syrabit:content_lang';

export function LanguageProvider({ children }) {
  // IMPORTANT: initialize to a deterministic constant ('en') so the SSR-prerendered
  // HTML matches the client's first render — otherwise reading localStorage during
  // initial state causes hydration mismatch (React error #418) on prerendered pages
  // such as /:board/:classSlug/:subjectSlug/:chapterSlug. Rehydrate from localStorage
  // in useEffect after mount.
  const [contentLang, setContentLang] = useState('en');

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === 'as' || stored === 'en') setContentLang(stored);
    } catch {}
  }, []);

  const switchLang = useCallback((lang) => {
    const val = lang === 'as' ? 'as' : 'en';
    setContentLang(val);
    try { localStorage.setItem(STORAGE_KEY, val); } catch {}
  }, []);

  const toggleLang = useCallback(() => {
    setContentLang((prev) => {
      const next = prev === 'en' ? 'as' : 'en';
      try { localStorage.setItem(STORAGE_KEY, next); } catch {}
      return next;
    });
  }, []);

  return (
    <LanguageContext.Provider value={{ contentLang, switchLang, toggleLang }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useContentLang() {
  const ctx = useContext(LanguageContext);
  if (!ctx) return { contentLang: 'en', switchLang: () => {}, toggleLang: () => {} };
  return ctx;
}
