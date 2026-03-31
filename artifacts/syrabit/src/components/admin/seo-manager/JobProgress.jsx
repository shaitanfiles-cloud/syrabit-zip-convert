import { Loader2, CheckCheck, AlertTriangle } from 'lucide-react';

export default function JobProgress({ job, onDismiss }) {
  if (!job) return null;
  const pct = job.total > 0 ? Math.min(100, Math.round((job.done / job.total) * 100)) : 0;
  const isDone = job.status === 'done';
  const isErr  = job.status === 'error';
  const barColor = isErr ? '#f87171' : isDone ? '#34d399' : '#7c3aed';
  return (
    <div className="rounded-xl p-4 border" style={{ background: 'rgba(124,58,237,0.06)', borderColor: 'rgba(124,58,237,0.25)' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {isDone ? <CheckCheck size={14} style={{ color: '#34d399' }} />
           : isErr ? <AlertTriangle size={14} style={{ color: '#f87171' }} />
           : <Loader2 size={14} className="animate-spin" style={{ color: '#a78bfa' }} />}
          <span className="text-xs font-semibold" style={{ color: isDone ? '#34d399' : isErr ? '#f87171' : '#c4b0f0' }}>
            {isDone ? 'Pipeline Complete' : isErr ? 'Pipeline Error' : 'Pipeline Running…'}
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.35)' }}>
            {job.job_id}
          </span>
        </div>
        {(isDone || isErr) && (
          <button onClick={onDismiss} className="text-[10px]" style={{ color: 'rgba(255,255,255,0.30)' }}>Dismiss</button>
        )}
      </div>
      <div className="flex items-center gap-3 mb-2">
        <div className="flex-1 h-2 rounded-full" style={{ background: 'rgba(255,255,255,0.06)' }}>
          <div className="h-2 rounded-full transition-all duration-300" style={{ width: `${isDone ? 100 : pct}%`, background: barColor }} />
        </div>
        <span className="text-[11px] font-mono flex-shrink-0" style={{ color: 'rgba(255,255,255,0.45)' }}>
          {isDone ? '100%' : `${pct}%`}
        </span>
      </div>
      <div className="flex items-center gap-4 text-[10px]" style={{ color: 'rgba(255,255,255,0.35)' }}>
        <span>✓ {job.done ?? 0} done</span>
        {job.skipped > 0 && <span>⟳ {job.skipped} skipped</span>}
        {job.errors > 0 && <span style={{ color: '#f87171' }}>✗ {job.errors} errors</span>}
        {job.total > 0 && <span>of {job.total}</span>}
      </div>
      {job.current && (
        <p className="text-[10px] truncate mt-1.5" style={{ color: 'rgba(255,255,255,0.25)' }}>{job.current}</p>
      )}
    </div>
  );
}
