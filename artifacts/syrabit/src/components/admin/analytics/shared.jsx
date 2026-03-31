import { RefreshCw, ArrowUpRight, ArrowDownRight, AlertTriangle, Flame } from 'lucide-react';

export const TT = {
  contentStyle: {
    background: '#0f172a', border: '1px solid #1e293b',
    borderRadius: '8px', color: '#e2e8f0', fontSize: 12,
  },
};

export const PLAN_COLORS = { free: '#475569', starter: '#7c3aed', pro: '#10b981' };
export const FUNNEL_COLORS = ['#3b82f6', '#8b5cf6', '#10b981'];

export const fmt = (d) => d?.slice(5) ?? d;
export const fmtInr = (n) => n >= 100000 ? `₹${(n / 100000).toFixed(1)}L` : n >= 1000 ? `₹${(n / 1000).toFixed(1)}k` : `₹${n}`;

export function Card({ title, children, empty, emptyMsg, action, error, onRetry }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-slate-400 text-sm font-medium">{title}</h3>
        <div className="flex items-center gap-2">
          {error && onRetry && (
            <button onClick={onRetry} className="text-xs text-amber-400 hover:text-white px-2 py-0.5 rounded bg-amber-500/10 hover:bg-amber-500/20 transition-colors flex items-center gap-1">
              <RefreshCw size={10} /> Retry
            </button>
          )}
          {action}
        </div>
      </div>
      {error
        ? (
          <div className="flex items-center gap-2 py-6 justify-center">
            <AlertTriangle size={14} className="text-amber-400" />
            <p className="text-amber-400 text-sm">Failed to load — data unavailable</p>
          </div>
        )
        : empty
          ? <p className="text-slate-600 text-sm text-center py-6">{emptyMsg || 'No data yet'}</p>
          : children}
    </div>
  );
}

export function Stat({ icon: Icon, label, value, color, sub, trend }) {
  const up = trend > 0;
  return (
    <div className="flex items-center gap-3 p-3 bg-slate-800/50 rounded-xl">
      <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: `${color}22` }}>
        <Icon size={15} style={{ color }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-white font-bold text-lg leading-none truncate">{value ?? '—'}</p>
        <p className="text-slate-500 text-xs mt-0.5">{label}</p>
        {sub && <p className="text-slate-600 text-[10px] mt-0.5">{sub}</p>}
      </div>
      {trend !== undefined && (
        <div className={`flex items-center gap-0.5 text-xs font-semibold flex-shrink-0 ${up ? 'text-emerald-400' : 'text-red-400'}`}>
          {up ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
          {Math.abs(trend)}%
        </div>
      )}
    </div>
  );
}

export function InsightBar({ label, value, max, color }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  const heat = pct > 70 ? '#ef4444' : pct > 40 ? '#f59e0b' : '#3b82f6';
  const c = color || heat;
  return (
    <div className="flex items-center gap-2">
      <Flame size={11} style={{ color: c }} className="flex-shrink-0" />
      <span className="text-slate-300 text-sm flex-1 truncate">{label}</span>
      <div className="w-20 h-2 rounded-full bg-slate-800 overflow-hidden flex-shrink-0">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: c }} />
      </div>
      <span className="text-slate-500 text-xs w-8 text-right flex-shrink-0">{value}</span>
    </div>
  );
}
