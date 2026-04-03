import { useState, useRef, useEffect } from 'react';
import { Languages } from 'lucide-react';
import { useSarvamStatus, getLangLabel, getTTSLang, setTTSLang } from '@/hooks/useTTS';

export function TTSLanguagePicker() {
  const { enabled, languages } = useSarvamStatus();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(getTTSLang());
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  if (!enabled || languages.length === 0) return null;

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors"
        title="TTS Language"
        aria-label={`TTS Language: ${getLangLabel(selected)}`}
      >
        <Languages size={14} />
        <span className="hidden sm:inline">{getLangLabel(selected)}</span>
      </button>
      {open && (
        <div
          className="absolute bottom-full mb-1 left-0 z-50 min-w-[160px] max-h-[240px] overflow-y-auto rounded-xl border border-border/60 shadow-lg py-1"
          style={{ background: 'var(--card)' }}
        >
          {languages.map(lang => (
            <button
              key={lang}
              onClick={() => {
                setSelected(lang);
                setTTSLang(lang);
                setOpen(false);
              }}
              className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                lang === selected
                  ? 'text-primary bg-primary/10 font-medium'
                  : 'text-foreground/80 hover:bg-muted/50'
              }`}
            >
              {getLangLabel(lang)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
