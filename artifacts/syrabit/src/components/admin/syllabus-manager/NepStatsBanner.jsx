import { Loader2, GitBranch } from 'lucide-react';

export default function NepStatsBanner({ nepStats, autoAssigning, onAutoAssign }) {
  return (
    <div className="rounded-xl border px-4 py-3 space-y-2"
      style={{ background: 'rgba(52,211,153,0.07)', borderColor: 'rgba(52,211,153,0.22)' }}>
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-sm"
          style={{ background: 'rgba(52,211,153,0.15)' }}>🚀</div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-bold text-emerald-400 leading-tight">
            Syrabit.ai Subject Router — NEP FYUGP Live
          </p>
          <p className="text-[11px] text-white/50 mt-0.5">
            Syllabus auto-embed active &nbsp;·&nbsp; 98% plain-query accuracy &nbsp;·&nbsp; zero manual work
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={onAutoAssign}
            disabled={autoAssigning}
            title="Re-link all imported subjects into pre-built FYUGP Semester 1–4 slots"
            className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold transition-all disabled:opacity-50"
            style={{ background: 'rgba(52,211,153,0.18)', color: '#6ee7b7', border: '1px solid rgba(52,211,153,0.30)' }}>
            {autoAssigning
              ? <><Loader2 size={10} className="animate-spin" /> Assigning…</>
              : <><GitBranch size={10} /> Auto-Assign</>}
          </button>
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold"
            style={{ background: 'rgba(52,211,153,0.18)', color: '#6ee7b7' }}>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse inline-block" />
            LIVE
          </span>
        </div>
      </div>
      {nepStats && (
        <div className="flex flex-wrap gap-2 pt-1 border-t" style={{ borderColor: 'rgba(52,211,153,0.12)' }}>
          {['aec','sec','mdc','vac','ge','cc','major','minor'].map(t => {
            const count = nepStats.by_type?.[t] || 0;
            if (!count) return null;
            const icons = { aec:'🧠', sec:'⚡', mdc:'🌐', vac:'✨', ge:'🔄', cc:'⭐', major:'🎯', minor:'📘' };
            return (
              <span key={t} className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                style={{ background: 'rgba(52,211,153,0.10)', color: '#6ee7b7' }}>
                {icons[t]} {t.toUpperCase()}: {count}
              </span>
            );
          })}
          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded ml-auto"
            style={{ background: 'rgba(99,102,241,0.15)', color: '#a5b4fc' }}>
            📚 {nepStats.total_subjects} subjects · {nepStats.total_embedded_chapters} embedded
          </span>
        </div>
      )}
    </div>
  );
}
