import { createContext, useContext, useState, useCallback } from 'react';

const LanguageContext = createContext(null);

const STORAGE_KEY = 'syrabit:content_lang';

function getInitialLang() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'as' || stored === 'en') return stored;
  } catch {}
  return 'en';
}

export function LanguageProvider({ children }) {
  const [contentLang, setContentLang] = useState(getInitialLang);

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
