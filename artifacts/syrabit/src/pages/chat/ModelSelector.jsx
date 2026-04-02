import { ChevronDown, Plus } from 'lucide-react';

const MODELS = [
  { value: 'syrabit-slm',  label: 'Syrabit SLM', badge: '⚡ Fast'         },
  { value: 'syrabit-mlm', label: 'Syrabit MLM', badge: '🔜 Coming Soon', disabled: true },
];

export { MODELS };

export function ModelSelector({ model, setModel, showModelMenu, setShowModelMenu, modelMenuRef, handleNewChat }) {
  const modelLabel = MODELS.find((m) => m.value === model) || MODELS[0];

  return (
    <div className="relative flex items-center gap-2" ref={modelMenuRef}>
      <button
        onClick={() => setShowModelMenu((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold text-foreground hover:text-primary transition-all border border-border/50 hover:border-primary/30 hover:shadow-[0_0_12px_rgba(139,92,246,0.1)]"
        data-testid="model-selector-button"
      >
        <img src="/logo.png" alt="" className="w-4 h-4 rounded-sm" />
        <span>{modelLabel.label}</span>
        {!modelLabel.disabled && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
            {modelLabel.badge.replace(/[🧠⚡🔜]\s*/, '')}
          </span>
        )}
        <ChevronDown size={14} className={`text-muted-foreground transition-transform ${showModelMenu ? 'rotate-180' : ''}`} />
      </button>
      {showModelMenu && (
        <div
          className="absolute top-full left-0 mt-2 z-50 rounded-xl border border-border/60 shadow-2xl min-w-[260px] max-w-[calc(100vw-2rem)] overflow-hidden backdrop-blur-xl"
          style={{ background: 'var(--popover-glass, var(--popover))' }}
        >
          {MODELS.map((m) => (
            <button
              key={m.value}
              onClick={() => { 
                if (!m.disabled) {
                  setModel(m.value); 
                  setShowModelMenu(false);
                }
              }}
              disabled={m.disabled}
              className={`w-full flex items-center gap-3 px-4 py-3 text-sm transition-colors ${
                m.disabled 
                  ? 'opacity-50 cursor-not-allowed bg-muted/20' 
                  : 'hover:bg-accent/40'
              } ${
                model === m.value ? 'text-primary font-semibold bg-primary/5' : 'text-foreground'
              }`}
            >
              <img src="/logo.png" alt="" className="w-5 h-5 rounded-sm flex-shrink-0" />
              <div className="flex flex-col items-start flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate">{m.label}</span>
                  {m.disabled && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/10 text-amber-500 font-medium">
                      Coming Soon
                    </span>
                  )}
                </div>
                <span className="text-[10px] text-muted-foreground">
                  {m.disabled 
                    ? 'Advanced model launching soon' 
                    : (m.badge.replace(/[🧠⚡🔜]\s*/, '') === 'Fast' ? 'Best for quick Q&A, fastest responses' : 'Best for complex problems, deep reasoning')
                  }
                </span>
              </div>
              {model === m.value && !m.disabled && <span className="w-1.5 h-1.5 rounded-full bg-primary flex-shrink-0" />}
            </button>
          ))}
        </div>
      )}

      <button
        onClick={handleNewChat}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-muted-foreground hover:text-foreground border border-border/40 hover:border-primary/30 transition-all"
        title="New chat"
        aria-label="Start new chat"
      >
        <Plus size={13} />
        <span className="hidden sm:inline">New Chat</span>
      </button>
    </div>
  );
}
