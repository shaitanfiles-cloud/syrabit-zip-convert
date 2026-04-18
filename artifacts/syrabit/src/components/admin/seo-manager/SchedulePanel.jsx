import { Loader2, RefreshCw, Calendar, Clock, AlertTriangle, CheckCircle2 } from 'lucide-react';

function fmtDate(v) {
  if (!v) return '—';
  try {
    const d = typeof v === 'string' ? new Date(v) : new Date(v);
    if (Number.isNaN(d.getTime())) return String(v);
    return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  } catch { return String(v); }
}

function hoursSince(v) {
  if (!v) return null;
  try {
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return null;
    return (Date.now() - d.getTime()) / 3600000;
  } catch { return null; }
}

function nextExpectedRun(cfg, lastIso) {
  if (!cfg) return null;
  const hour = Number(cfg.target_hour_utc ?? 2);
  const freq = cfg.frequency || 'daily';
  const now = new Date();
  const candidate = new Date(Date.UTC(
    now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), hour, 0, 0
  ));
  if (freq === 'weekly') {
    const targetDow = Number(cfg.weekday ?? 1); // 0=Mon ... 6=Sun by Python convention; treat as JS day where 0=Sun, 1=Mon
    // Backend uses Python's weekday(): Mon=0..Sun=6. Convert to JS getUTCDay (Sun=0..Sat=6).
    const jsDow = (targetDow + 1) % 7;
    let diff = (jsDow - candidate.getUTCDay() + 7) % 7;
    if (diff === 0 && candidate <= now) diff = 7;
    candidate.setUTCDate(candidate.getUTCDate() + diff);
  } else {
    if (candidate <= now) candidate.setUTCDate(candidate.getUTCDate() + 1);
  }
  // Ensure we're after last run
  if (lastIso) {
    try {
      const last = new Date(lastIso);
      if (!Number.isNaN(last.getTime()) && candidate <= last) {
        candidate.setUTCDate(candidate.getUTCDate() + (freq === 'weekly' ? 7 : 1));
      }
    } catch { /* ignore */ }
  }
  return candidate.toISOString();
}

function hourLabel(hour) {
  if (hour == null || Number.isNaN(Number(hour))) return '—';
  const h = Number(hour);
  const utc = `${String(h).padStart(2, '0')}:00 UTC`;
  // IST = UTC + 5:30
  const istMin = h * 60 + 330;
  const istH = Math.floor((istMin / 60) % 24);
  const istM = istMin % 60;
  const ist = `${String(istH).padStart(2, '0')}:${String(istM).padStart(2, '0')} IST`;
  return `${utc} · ${ist}`;
}

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export default function SchedulePanel({ schedule, scheduleLoading, loadSchedule }) {
  const cfg = schedule?.config || null;
  const lastMarker = schedule?.last_marker || null;
  const recent = (schedule?.recent_runs || []).slice(0, 5);
  const enabled = Boolean(cfg?.enabled);
  const freq = cfg?.frequency || 'daily';
  const lastRunIso = recent[0]?.completed_at || lastMarker?.claimed_at || lastMarker?.last_run_at || null;
  const lastAgeH = hoursSince(lastRunIso);
  const staleThresholdH = freq === 'weekly' ? 24 * 8 : 36;
  const isStale = enabled && (lastAgeH == null || lastAgeH > staleThresholdH);
  const next = nextExpectedRun(cfg, lastRunIso);

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-gray-900">Scheduled auto-publish</p>
          <p className="text-xs mt-0.5" style={{ color: '#9ca3af' }}>
            Status of the background job that generates SEO pages on a {freq} cadence.
          </p>
        </div>
        <button onClick={loadSchedule} disabled={scheduleLoading}
          className="p-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors text-gray-400">
          <RefreshCw size={14} className={scheduleLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {scheduleLoading && !schedule && (
        <div className="rounded-xl p-6 border border-gray-200 bg-gray-50 flex items-center gap-2 text-sm text-gray-500">
          <Loader2 size={14} className="animate-spin" /> Loading schedule…
        </div>
      )}

      {schedule && (
        <>
          {isStale && (
            <div className="rounded-xl p-4 border flex items-start gap-3"
              style={{ background: 'rgba(239,68,68,0.06)', borderColor: 'rgba(239,68,68,0.25)' }}>
              <AlertTriangle size={16} className="mt-0.5" style={{ color: '#ef4444' }} />
              <div>
                <p className="text-sm font-semibold" style={{ color: '#b91c1c' }}>
                  Scheduled job may have stopped firing
                </p>
                <p className="text-xs mt-0.5" style={{ color: '#7f1d1d' }}>
                  {lastRunIso
                    ? `Last scheduled run was ${Math.round(lastAgeH)}h ago — expected at most every ${staleThresholdH}h for a ${freq} cadence.`
                    : `No scheduled run has been recorded yet — expected at least one within ${staleThresholdH}h.`}
                </p>
              </div>
            </div>
          )}

          {!isStale && enabled && (
            <div className="rounded-xl p-4 border flex items-start gap-3"
              style={{ background: 'rgba(16,185,129,0.06)', borderColor: 'rgba(16,185,129,0.20)' }}>
              <CheckCircle2 size={16} className="mt-0.5" style={{ color: '#10b981' }} />
              <div>
                <p className="text-sm font-semibold" style={{ color: '#047857' }}>Scheduler healthy</p>
                <p className="text-xs mt-0.5" style={{ color: '#065f46' }}>
                  {lastRunIso
                    ? `Most recent scheduled run completed ${Math.round(lastAgeH)}h ago.`
                    : 'Scheduler is enabled and waiting for its first run.'}
                </p>
              </div>
            </div>
          )}

          {!enabled && (
            <div className="rounded-xl p-4 border flex items-start gap-3"
              style={{ background: 'rgba(245,158,11,0.07)', borderColor: 'rgba(245,158,11,0.25)' }}>
              <AlertTriangle size={16} className="mt-0.5" style={{ color: '#d97706' }} />
              <div>
                <p className="text-sm font-semibold" style={{ color: '#92400e' }}>Scheduler disabled</p>
                <p className="text-xs mt-0.5" style={{ color: '#78350f' }}>
                  Set <code className="font-mono">SEO_AUTO_PUBLISH_ENABLED=1</code> in the backend env to turn it on.
                </p>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-xl p-4 border" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
              <p className="text-[10px] uppercase tracking-wider" style={{ color: '#9ca3af' }}>Status</p>
              <p className="text-sm font-semibold mt-1" style={{ color: enabled ? '#10b981' : '#9ca3af' }}>
                {enabled ? 'Enabled' : 'Disabled'}
              </p>
            </div>
            <div className="rounded-xl p-4 border" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
              <p className="text-[10px] uppercase tracking-wider" style={{ color: '#9ca3af' }}>Frequency</p>
              <p className="text-sm font-semibold mt-1 capitalize text-gray-900">
                {freq}
                {freq === 'weekly' && cfg?.weekday != null
                  ? ` · ${WEEKDAY_LABELS[Number(cfg.weekday) % 7] || ''}`
                  : ''}
              </p>
            </div>
            <div className="rounded-xl p-4 border" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
              <p className="text-[10px] uppercase tracking-wider" style={{ color: '#9ca3af' }}>Target hour</p>
              <p className="text-sm font-semibold mt-1 text-gray-900">{hourLabel(cfg?.target_hour_utc)}</p>
            </div>
            <div className="rounded-xl p-4 border" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
              <p className="text-[10px] uppercase tracking-wider" style={{ color: '#9ca3af' }}>Next expected run</p>
              <p className="text-sm font-semibold mt-1 text-gray-900 flex items-center gap-1">
                <Clock size={12} className="text-gray-400" />
                {enabled ? fmtDate(next) : '—'}
              </p>
            </div>
          </div>

          {Array.isArray(cfg?.page_types) && cfg.page_types.length > 0 && (
            <div className="text-xs" style={{ color: '#6b7280' }}>
              Page types: {cfg.page_types.map((pt) => (
                <span key={pt} className="inline-block px-2 py-0.5 mr-1 rounded-md font-mono"
                  style={{ background: '#f3f4f6', border: '1px solid #e5e7eb', color: '#374151' }}>{pt}</span>
              ))}
            </div>
          )}

          <div className="rounded-xl border overflow-hidden" style={{ borderColor: '#e5e7eb' }}>
            <div className="px-4 py-3 flex items-center gap-2 border-b" style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}>
              <Calendar size={14} className="text-gray-400" />
              <p className="text-sm font-semibold text-gray-900">Recent scheduled runs</p>
              <span className="text-xs" style={{ color: '#9ca3af' }}>(last {recent.length})</span>
            </div>
            {recent.length === 0 ? (
              <div className="p-6 text-center text-sm" style={{ color: '#9ca3af' }}>
                No scheduled runs recorded yet.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead style={{ background: '#fafafa', color: '#6b7280' }}>
                    <tr className="text-left">
                      <th className="px-4 py-2 font-medium">When</th>
                      <th className="px-4 py-2 font-medium">Generated</th>
                      <th className="px-4 py-2 font-medium">Skipped</th>
                      <th className="px-4 py-2 font-medium">Errors</th>
                      <th className="px-4 py-2 font-medium">Avg SEO</th>
                      <th className="px-4 py-2 font-medium">Avg GEO</th>
                      <th className="px-4 py-2 font-medium">Job</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recent.map((r, idx) => {
                      const errors = Number(r.errors || 0);
                      return (
                        <tr key={r.job_id || idx} className="border-t" style={{ borderColor: '#f3f4f6' }}>
                          <td className="px-4 py-2 text-gray-700">{fmtDate(r.completed_at)}</td>
                          <td className="px-4 py-2 font-semibold" style={{ color: '#10b981' }}>{r.total_generated ?? 0}</td>
                          <td className="px-4 py-2 text-gray-600">{r.skipped ?? 0}</td>
                          <td className="px-4 py-2 font-semibold" style={{ color: errors > 0 ? '#ef4444' : '#9ca3af' }}>{errors}</td>
                          <td className="px-4 py-2 text-gray-700">{r.avg_seo_score != null ? Math.round(r.avg_seo_score) : '—'}</td>
                          <td className="px-4 py-2 text-gray-700">{r.avg_geo_score != null ? Math.round(r.avg_geo_score) : '—'}</td>
                          <td className="px-4 py-2 font-mono text-[10px]" style={{ color: '#9ca3af' }}>{r.job_id || '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
