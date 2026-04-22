import { useEffect, useState } from 'react';
import { TrendingUp, Eye, Users, DollarSign, Zap, Target,
  AlertTriangle, Calendar, ShieldCheck, RefreshCw,
  AlertOctagon, Star, MousePointerClick, XCircle } from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar,
} from 'recharts';
import { Card, Stat, TT, fmt, fmtInr } from './shared';
import { adminGetHydrateStats, adminAcknowledgeAlert,
  adminGetReviewPromptStats } from '@/utils/api';

const TIME_RANGES = [
  { value: 1,  label: 'Today' },
  { value: 7,  label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
];

export default function OverviewTab({ data, vs, widgetErrors, load, mrr, predicted, growth, arpu, ltv,
  cfConnected, overviewDays, setOverviewDays, adminToken }) {
  const [hydrate, setHydrate] = useState(null);
  const [hydrateLoading, setHydrateLoading] = useState(false);
  const [hydrateError, setHydrateError] = useState(false);
  const loadHydrate = async () => {
    setHydrateLoading(true);
    setHydrateError(false);
    try {
      const r = await adminGetHydrateStats(adminToken, 7);
      setHydrate(r.data);
    } catch {
      setHydrateError(true);
      setHydrate(null);
    } finally {
      setHydrateLoading(false);
    }
  };
  const [reviewPrompt, setReviewPrompt] = useState(null);
  const [reviewPromptLoading, setReviewPromptLoading] = useState(false);
  const [reviewPromptError, setReviewPromptError] = useState(false);
  const loadReviewPrompt = async () => {
    setReviewPromptLoading(true);
    setReviewPromptError(false);
    try {
      // Task #659: 7-day window so per-reason deltas are true
      // week-over-week (vs the prior 7 days), matching the weekly
      // digest email's semantics.
      const r = await adminGetReviewPromptStats(adminToken, 7);
      setReviewPrompt(r.data);
    } catch {
      setReviewPromptError(true);
      setReviewPrompt(null);
    } finally {
      setReviewPromptLoading(false);
    }
  };
  useEffect(() => {
    if (adminToken) {
      loadHydrate();
      loadReviewPrompt();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminToken]);
  const hasDailySignup = data?.daily_signups?.some(d => d.count > 0);
  const hasPlanUsage   = data?.plan_usage && Object.keys(data.plan_usage).length > 0;
  const cf = vs.cloudflare || {};
  const dailyVisitors = cf.daily_visitors || [];
  const hasDailyCf = dailyVisitors.some(d => d.visitors > 0 || d.page_views > 0);
  const rangeLabel = TIME_RANGES.find(t => t.value === overviewDays)?.label || `Last ${overviewDays} days`;
  const cfEmptyMsg = cfConnected
    ? 'No data yet for this range'
    : 'Cloudflare analytics unavailable — check API token and Zone ID';

  return (
    <>
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5 text-gray-600 text-sm">
          <Calendar size={14} />
          <span>Time range:</span>
        </div>
        {TIME_RANGES.map(t => (
          <button key={t.value} onClick={() => setOverviewDays(t.value)}
            className={`px-3.5 py-1.5 rounded-xl text-xs font-medium transition-all ${
              overviewDays === t.value ? 'text-white' : 'text-gray-600 hover:text-gray-800'
            }`}
            style={overviewDays === t.value
              ? { background: 'linear-gradient(135deg, #7c3aed, #6d28d9)', boxShadow: '0 2px 12px rgba(124,58,237,0.3)' }
              : { background: '#f9fafb', border: '1px solid #e5e7eb' }
            }>
            {t.label}
          </button>
        ))}
      </div>

      {widgetErrors.overview && (
        <div className="flex items-center gap-3 p-3.5 rounded-xl" style={{
          background: 'rgba(245,158,11,0.06)',
          border: '1px solid rgba(245,158,11,0.15)',
        }}>
          <AlertTriangle size={14} className="text-amber-700 flex-shrink-0" />
          <p className="text-xs text-amber-700/80 flex-1">Overview data failed to load — some metrics unavailable.</p>
          <button onClick={() => load(true)} className="text-xs text-amber-700 hover:text-gray-900 px-2.5 py-1 rounded-lg transition-colors"
            style={{ background: 'rgba(245,158,11,0.12)' }}>Retry</button>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat icon={TrendingUp} label={`Visitors (${rangeLabel})`}
          value={cfConnected ? (cf.total_visitors ?? 0).toLocaleString() : '—'} color="#f6821f" sub="Cloudflare" />
        <Stat icon={Users} label="Visitors Today"
          value={cfConnected ? (cf.visitors_today ?? 0).toLocaleString() : '—'} color="#06b6d4" sub="Cloudflare" />
        <Stat icon={Eye} label="Page Views Today"
          value={cfConnected ? (cf.page_views_today ?? 0).toLocaleString() : '—'} color="#ec4899" sub="Cloudflare" />
        <Stat icon={Users} label="Active Users" value={data?.active_users ?? 0} color="#8b5cf6" />
      </div>

      {mrr > 0 && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat icon={DollarSign} label="MRR (30d)"       value={fmtInr(mrr)}       color="#10b981" trend={growth} />
          <Stat icon={TrendingUp} label="Predicted MRR"   value={fmtInr(predicted)} color="#7c3aed" />
          <Stat icon={Target}     label="ARPU"            value={fmtInr(arpu)}       color="#f59e0b" />
          <Stat icon={Zap}        label="LTV (12-mo)"     value={fmtInr(ltv)}        color="#06b6d4" />
        </div>
      )}

      <HydrateHealthCard
        hydrate={hydrate}
        loading={hydrateLoading}
        error={hydrateError}
        onRetry={loadHydrate}
        adminToken={adminToken}
      />

      <ReviewPromptFunnelCard
        stats={reviewPrompt}
        loading={reviewPromptLoading}
        error={reviewPromptError}
        onRetry={loadReviewPrompt}
      />

      <Card title={`Daily Visitors — ${rangeLabel}`} empty={!hasDailyCf} emptyMsg={cfEmptyMsg}>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={dailyVisitors} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f9fafb" />
            <XAxis dataKey="date" tick={{ fill: '#4b5563', fontSize: 11 }} tickFormatter={fmt}
              interval={Math.max(0, Math.floor(dailyVisitors.length / 8) - 1)} />
            <YAxis tick={{ fill: '#4b5563', fontSize: 11 }} />
            <Tooltip {...TT} />
            <Area type="monotone" dataKey="visitors" name="Cloudflare Visitors"
              stroke="#f6821f" fill="rgba(246,130,31,0.12)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      <Card title={`Daily Page Views — ${rangeLabel}`} empty={!hasDailyCf} emptyMsg={cfEmptyMsg}>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={dailyVisitors} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f9fafb" />
            <XAxis dataKey="date" tick={{ fill: '#4b5563', fontSize: 11 }} tickFormatter={fmt}
              interval={Math.max(0, Math.floor(dailyVisitors.length / 8) - 1)} />
            <YAxis tick={{ fill: '#4b5563', fontSize: 11 }} />
            <Tooltip {...TT} />
            <Area type="monotone" dataKey="page_views" name="Cloudflare Page Views"
              stroke="#ec4899" fill="rgba(236,72,153,0.10)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      <Card title={`Daily Signups — ${rangeLabel}`} empty={!hasDailySignup} emptyMsg="No signups in this range">
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={data.daily_signups} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f9fafb" />
            <XAxis dataKey="date" tick={{ fill: '#4b5563', fontSize: 11 }} tickFormatter={fmt}
              interval={Math.max(0, Math.floor((data.daily_signups?.length || 0) / 8) - 1)} />
            <YAxis tick={{ fill: '#4b5563', fontSize: 11 }} allowDecimals={false} />
            <Tooltip {...TT} />
            <Bar dataKey="count" name="Signups" fill="#7c3aed" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </Card>

      {hasPlanUsage && (
        <Card title="Credits Used by Plan">
          <ResponsiveContainer width="100%" height={140}>
            <BarChart data={Object.entries(data.plan_usage).map(([plan, used]) => ({ plan, used }))}
              margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f9fafb" />
              <XAxis dataKey="plan" tick={{ fill: '#4b5563', fontSize: 11 }} />
              <YAxis tick={{ fill: '#4b5563', fontSize: 11 }} />
              <Tooltip {...TT} />
              <Bar dataKey="used" name="Credits Used" fill="#7c3aed" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Task #408: ops-health tile for the hydrate-lifecycle telemetry that
// Tasks #405 / #407 emit. Healthy state is intentionally low-key so the
// admin's eye doesn't get drawn to it when nothing's wrong.
// ─────────────────────────────────────────────────────────────────────
function HydrateHealthCard({ hydrate, loading, error, onRetry, adminToken }) {
  const [ackingId, setAckingId] = useState(null);
  const [ackedIds, setAckedIds] = useState(() => new Set());
  const [ackErrors, setAckErrors] = useState({});
  const handleAcknowledge = async (alertId) => {
    if (!alertId || !adminToken) return;
    setAckingId(alertId);
    setAckErrors(prev => {
      if (!prev[alertId]) return prev;
      const { [alertId]: _, ...rest } = prev;
      return rest;
    });
    try {
      await adminAcknowledgeAlert(adminToken, alertId);
      setAckedIds(prev => {
        const next = new Set(prev);
        next.add(alertId);
        return next;
      });
      onRetry?.();
    } catch (e) {
      setAckErrors(prev => ({
        ...prev,
        [alertId]: 'Acknowledge failed — try again or use the Alerts page',
      }));
    } finally {
      setAckingId(null);
    }
  };
  if (loading && !hydrate) {
    return (
      <Card title="Hydration & Stale-Build Recovery (7d)">
        <p className="text-gray-600 text-sm text-center py-6">Loading…</p>
      </Card>
    );
  }
  if (error) {
    return (
      <Card title="Hydration & Stale-Build Recovery (7d)" error onRetry={onRetry} />
    );
  }
  const h = hydrate || {};
  const failed = h.preload_failed_total || 0;
  const attempts = h.auto_reload_attempts || 0;
  const recoveries = h.auto_reload_recoveries || 0;
  const stalled = h.stalled_total || 0;
  const manual = h.manual_failures || 0;
  const successRate = h.auto_reload_success_rate_pct;
  const isHealthy = failed === 0 && stalled === 0;
  const topKinds = Array.isArray(h.top_kinds) ? h.top_kinds : [];
  const topUAs = Array.isArray(h.top_user_agents) ? h.top_user_agents : [];
  const activeAlerts = (Array.isArray(h.active_alerts) ? h.active_alerts : [])
    .filter(a => a && a._id && !ackedIds.has(a._id));

  return (
    <Card
      title="Hydration & Stale-Build Recovery (7d)"
      action={
        <button
          onClick={onRetry}
          className="text-xs text-gray-600 hover:text-gray-700 px-2 py-0.5 rounded-lg flex items-center gap-1"
        >
          <RefreshCw size={10} /> Refresh
        </button>
      }
    >
      {activeAlerts.length > 0 && (
        <div className="space-y-2 mb-4">
          {activeAlerts.map(alert => (
            <HydrateAlertBadge
              key={alert._id}
              alert={alert}
              acking={ackingId === alert._id}
              ackError={ackErrors[alert._id]}
              onAcknowledge={() => handleAcknowledge(alert._id)}
            />
          ))}
        </div>
      )}
      {isHealthy ? (
        <div className="flex items-center gap-3 py-4">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center"
            style={{ background: 'rgba(16,185,129,0.10)' }}>
            <ShieldCheck size={16} className="text-emerald-500" />
          </div>
          <div>
            <p className="text-emerald-600 text-sm font-medium">No stale-build recoveries — healthy</p>
            <p className="text-gray-600 text-xs mt-0.5">No hydration failures or stalls in the last 7 days.</p>
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat icon={AlertOctagon} label="Preload failures"
              value={failed.toLocaleString()} color="#f59e0b"
              sub={manual > 0 ? `${manual} without auto-reload attempt` : 'all auto-reload eligible'} />
            <Stat icon={RefreshCw} label="Auto-reload attempts"
              value={attempts.toLocaleString()} color="#7c3aed" sub="stale-chunk reloads" />
            <Stat icon={ShieldCheck} label="Recovery success"
              value={successRate == null ? '—' : `${successRate}%`}
              color="#10b981"
              sub={`${recoveries.toLocaleString()} healthy hydrations after reload`} />
            <Stat icon={AlertTriangle} label="Stalled hydrations"
              value={stalled.toLocaleString()} color="#ec4899"
              sub="≥5s on Suspense fallback" />
          </div>

          {(topKinds.length > 0 || topUAs.length > 0) && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-4">
              {topKinds.length > 0 && (
                <div className="rounded-xl p-3.5 bg-gray-50 border border-gray-200">
                  <p className="text-gray-500 text-xs font-medium mb-2">Top failing page chunks</p>
                  <ul className="space-y-1">
                    {topKinds.map((row, i) => (
                      <li key={i} className="flex items-center justify-between text-xs">
                        <span className="text-gray-700 truncate mr-2">{row.value || '—'}</span>
                        <span className="text-gray-600 font-mono">{row.count}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {topUAs.length > 0 && (
                <div className="rounded-xl p-3.5 bg-gray-50 border border-gray-200">
                  <p className="text-gray-500 text-xs font-medium mb-2">Top user-agents</p>
                  <ul className="space-y-1">
                    {topUAs.map((row, i) => (
                      <li key={i} className="flex items-center justify-between text-xs">
                        <span className="text-gray-700 truncate mr-2" title={row.value}>
                          {(row.value || '—').slice(0, 60)}
                        </span>
                        <span className="text-gray-600 font-mono">{row.count}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// Task #415: inline badge for fired hydrate-scoped alerts. Shows the
// alert title, when it fired (so admins know an email already went out
// at e.g. 09:14 UTC), and a button that hits the same acknowledge
// endpoint as the main /admin/alerts page.
function HydrateAlertBadge({ alert, acking, ackError, onAcknowledge }) {
  const firedAt = alert.fired_at ? new Date(alert.fired_at) : null;
  const firedLabel = firedAt && !isNaN(firedAt.getTime())
    ? firedAt.toLocaleString(undefined, {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
        timeZoneName: 'short',
      })
    : '—';
  const isRecovery = alert.type === 'hydrate_recovery_low';
  const accent = isRecovery ? '#ec4899' : '#f59e0b';
  return (
    <div
      className="flex items-start gap-3 p-3.5 rounded-xl"
      style={{
        background: isRecovery ? 'rgba(236,72,153,0.06)' : 'rgba(245,158,11,0.06)',
        border: `1px solid ${isRecovery ? 'rgba(236,72,153,0.20)' : 'rgba(245,158,11,0.20)'}`,
      }}
    >
      <AlertOctagon size={16} className="flex-shrink-0 mt-0.5" style={{ color: accent }} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold" style={{ color: accent }}>
          {alert.title || (isRecovery ? 'Stale-build recovery rate low' : 'Stale-build failures spiking')}
        </p>
        <p className="text-xs text-gray-500 mt-0.5">
          Alert fired {firedLabel} — ops already notified by email
        </p>
        {alert.body && (
          <p className="text-xs text-gray-600 mt-1 line-clamp-2" title={alert.body}>
            {alert.body.length > 160 ? `${alert.body.slice(0, 160)}…` : alert.body}
          </p>
        )}
        {ackError && (
          <p className="text-xs text-red-600 mt-1.5" role="alert">{ackError}</p>
        )}
      </div>
      <button
        onClick={onAcknowledge}
        disabled={acking}
        className="text-xs px-2.5 py-1 rounded-lg flex-shrink-0 transition-colors disabled:opacity-50"
        style={{
          background: 'rgba(255,255,255,0.6)',
          border: `1px solid ${accent}`,
          color: accent,
        }}
      >
        {acking ? 'Acknowledging…' : 'Acknowledge'}
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Task #654: Google review-prompt funnel tile. Shows shown / clicked /
// dismissed totals, click-through rate, and a per-trigger-reason
// breakdown so the team can see which surfaces (quiz_high_score,
// chapter_engaged, etc.) actually convert to Google review clicks.
// ─────────────────────────────────────────────────────────────────────
// Task #659 — single per-reason row, including week-over-week delta
// columns. Reasons that newly appeared / disappeared in the current
// window get a "new" / "gone" pill so ops can spot which surface is
// responsible for an overall CTR swing instead of guessing.
function ReviewPromptReasonRow({ row }) {
  const status = row?.status;
  const shownDelta = row?.shown_delta;
  const ctrDelta = row?.ctr_delta_pct;

  let shownDeltaCell;
  if (status === 'new') {
    shownDeltaCell = (
      <span className="inline-block px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 font-semibold text-[10px] uppercase tracking-wide">
        new
      </span>
    );
  } else if (status === 'gone') {
    shownDeltaCell = (
      <span className="inline-block px-1.5 py-0.5 rounded bg-rose-100 text-rose-700 font-semibold text-[10px] uppercase tracking-wide">
        gone
      </span>
    );
  } else if (shownDelta == null) {
    shownDeltaCell = <span className="text-gray-400">—</span>;
  } else if (shownDelta > 0) {
    shownDeltaCell = <span className="text-emerald-600">+{shownDelta.toLocaleString()}</span>;
  } else if (shownDelta < 0) {
    shownDeltaCell = <span className="text-rose-600">{shownDelta.toLocaleString()}</span>;
  } else {
    shownDeltaCell = <span className="text-gray-500">0</span>;
  }

  let ctrDeltaCell;
  if (status === 'new' || status === 'gone') {
    ctrDeltaCell = <span className="text-gray-400">—</span>;
  } else if (ctrDelta == null) {
    ctrDeltaCell = <span className="text-gray-400">n/a</span>;
  } else if (ctrDelta > 0) {
    ctrDeltaCell = <span className="text-emerald-600">▲ +{ctrDelta.toFixed(1)} pp</span>;
  } else if (ctrDelta < 0) {
    ctrDeltaCell = <span className="text-rose-600">▼ {ctrDelta.toFixed(1)} pp</span>;
  } else {
    ctrDeltaCell = <span className="text-gray-500">▬ 0.0 pp</span>;
  }

  return (
    <tr className="border-t border-gray-200">
      <td className="text-left text-gray-700 px-3.5 py-2 truncate" title={row.reason}>
        {row.reason || '—'}
      </td>
      <td className="text-right text-gray-700 font-mono px-3.5 py-2">{row.shown}</td>
      <td className="text-right text-gray-700 font-mono px-3.5 py-2">{row.clicked}</td>
      <td className="text-right text-gray-700 font-mono px-3.5 py-2">{row.dismissed}</td>
      <td className="text-right text-gray-700 font-mono px-3.5 py-2">
        {row.ctr_pct == null ? '—' : `${row.ctr_pct}%`}
      </td>
      <td className="text-right font-mono px-3.5 py-2">{shownDeltaCell}</td>
      <td className="text-right font-mono px-3.5 py-2">{ctrDeltaCell}</td>
    </tr>
  );
}

function ReviewPromptFunnelCard({ stats, loading, error, onRetry }) {
  if (loading && !stats) {
    return (
      <Card title="Google Review Prompt Funnel (7d)">
        <p className="text-gray-600 text-sm text-center py-6">Loading…</p>
      </Card>
    );
  }
  if (error) {
    return (
      <Card title="Google Review Prompt Funnel (7d)" error onRetry={onRetry} />
    );
  }
  const s = stats || {};
  const shown = s.shown || 0;
  const clicked = s.clicked || 0;
  const dismissed = s.dismissed || 0;
  const ctr = s.ctr_pct;
  const dismissRate = s.dismiss_rate_pct;
  const byReason = Array.isArray(s.by_reason) ? s.by_reason : [];
  const isEmpty = shown === 0 && clicked === 0 && dismissed === 0;

  return (
    <Card
      title="Google Review Prompt Funnel (7d)"
      action={
        <button
          onClick={onRetry}
          className="text-xs text-gray-600 hover:text-gray-700 px-2 py-0.5 rounded-lg flex items-center gap-1"
        >
          <RefreshCw size={10} /> Refresh
        </button>
      }
    >
      {isEmpty ? (
        <div className="flex items-center gap-3 py-4">
          <div className="w-9 h-9 rounded-lg flex items-center justify-center"
            style={{ background: 'rgba(124,58,237,0.10)' }}>
            <Star size={16} className="text-violet-500" />
          </div>
          <div>
            <p className="text-gray-700 text-sm font-medium">No review prompts fired yet</p>
            <p className="text-gray-500 text-xs mt-0.5">
              Counters will populate once engaged students hit a happy moment (quiz, chapter read).
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat icon={Star} label="Prompts shown"
              value={shown.toLocaleString()} color="#7c3aed"
              sub="happy-moment triggers" />
            <Stat icon={MousePointerClick} label="Clicked through"
              value={clicked.toLocaleString()} color="#10b981"
              sub="opened Google review form" />
            <Stat icon={ShieldCheck} label="Click-through rate"
              value={ctr == null ? '—' : `${ctr}%`}
              color="#06b6d4"
              sub="closest proxy for Google reviews" />
            <Stat icon={XCircle} label="Dismissed"
              value={dismissed.toLocaleString()} color="#f59e0b"
              sub={dismissRate == null ? 'no shown events' : `${dismissRate}% dismiss rate`} />
          </div>

          {byReason.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-gray-50 mt-4 overflow-hidden">
              <div className="px-3.5 py-2 border-b border-gray-200">
                <p className="text-gray-500 text-xs font-medium">
                  By trigger reason · Δ vs prev week
                </p>
              </div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-500">
                    <th className="text-left font-medium px-3.5 py-2">Reason</th>
                    <th className="text-right font-medium px-3.5 py-2">Shown</th>
                    <th className="text-right font-medium px-3.5 py-2">Clicked</th>
                    <th className="text-right font-medium px-3.5 py-2">Dismissed</th>
                    <th className="text-right font-medium px-3.5 py-2">CTR</th>
                    <th className="text-right font-medium px-3.5 py-2">Δ Shown</th>
                    <th className="text-right font-medium px-3.5 py-2">Δ CTR</th>
                  </tr>
                </thead>
                <tbody>
                  {byReason.map((row, i) => (
                    <ReviewPromptReasonRow key={i} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
