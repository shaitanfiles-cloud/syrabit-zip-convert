import React from 'react';
import { AlertTriangle, ShieldCheck, Clock, RefreshCw, ExternalLink } from 'lucide-react';
import { formatAlertStateCaption } from './cronCaptionHelpers';

const DEFAULT_PILL_LABELS = {
  healthy: 'CRON HEALTHY',
  silent: 'CRON SILENT',
  degraded: 'CRON DEGRADED',
  never_observed: 'NEVER OBSERVED',
  not_configured: 'NOT CONFIGURED',
};

export const ageLabel = (secs) => {
  if (secs == null) return null;
  const s = Math.max(0, Math.floor(Number(secs)));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
};

export default function CronHealthPill({
  data: rawData,
  loading = false,
  onRefresh,
  testId,
  headerTextByStatus,
  pillLabelByStatus,
  defaultWorkflowUrl,
  renderSubText,
  renderExtraActions,
  // Task #902 — optional alerter-state lock-doc snapshot from
  // `/admin/health/<pill>/cron/alert-state`. When provided, the
  // pill renders a small "last paged Xh ago · in debounce ~Yh
  // remaining" line below subText so admins can distinguish "I'm
  // seeing red because nobody has been paged yet" from "I'm
  // seeing red because we already paged Nh ago and are in
  // debounce" without having to query Mongo. The shape is
  // documented on `formatAlertStateCaption` in cronCaptionHelpers.
  alertState,
}) {
  const data = rawData && !rawData._error ? rawData : null;
  const status = data?.status || 'unknown';
  const isFailed = status === 'silent';
  const isDegraded = status === 'degraded';
  const isUnknown = status === 'never_observed' || status === 'not_configured' || !data;

  const containerCls = isFailed
    ? 'bg-red-50 border-red-200'
    : isDegraded
      ? 'bg-amber-50 border-amber-200'
      : isUnknown
        ? 'bg-gray-50 border-gray-200'
        : 'bg-emerald-50 border-emerald-200';
  const headerColor = isFailed
    ? 'text-red-600'
    : isDegraded
      ? 'text-amber-600'
      : isUnknown
        ? 'text-gray-500'
        : 'text-emerald-600';
  const pillCls = isFailed
    ? 'bg-red-100 text-red-700 border-red-200'
    : isDegraded
      ? 'bg-amber-100 text-amber-700 border-amber-200'
      : isUnknown
        ? 'bg-gray-100 text-gray-600 border-gray-200'
        : 'bg-emerald-100 text-emerald-700 border-emerald-200';

  const pillLabels = { ...DEFAULT_PILL_LABELS, ...(pillLabelByStatus || {}) };
  const pillLabel = pillLabels[status] || 'UNKNOWN';
  const headerText = (headerTextByStatus && headerTextByStatus[status])
    || (headerTextByStatus && headerTextByStatus.unknown)
    || 'Cron — status unknown';

  const workflowUrl = data?.workflowUrl || defaultWorkflowUrl;
  const ctx = { data, status, isFailed, isDegraded, isUnknown, ageLabel };
  const subText = renderSubText ? renderSubText(ctx) : null;
  const extraActions = renderExtraActions ? renderExtraActions(ctx) : null;
  // Task #902 — alerter-state caption (e.g. "last paged 2h ago ·
  // in debounce ~22h remaining"). Returns null when there's no
  // recorded page so we don't render an orphan line on a fresh
  // deployment with a healthy pill.
  const alertCaption = formatAlertStateCaption(alertState);
  // The caption colour follows whether we're inside the debounce
  // window: amber when on-call has been paged but the next re-page
  // is still suppressed (so admins don't expect a new email if the
  // pill stays red), gray otherwise (just informational —
  // e.g. recovery, or a broken state past the debounce so the next
  // poll can re-page).
  const alertCaptionCls = alertState && alertState.inDebounce
    ? 'text-amber-600'
    : 'text-gray-500';

  return (
    <div className={`rounded-2xl p-4 border ${containerCls}`} data-testid={`${testId}-tile`}>
      <div className="flex items-center gap-3">
        {isFailed
          ? <AlertTriangle size={18} className="text-red-500" />
          : isDegraded
            ? <AlertTriangle size={18} className="text-amber-500" />
            : isUnknown
              ? <Clock size={18} className="text-gray-400" />
              : <ShieldCheck size={18} className="text-emerald-500" />}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className={`text-sm font-semibold ${headerColor}`} data-testid={`${testId}-status`}>
              {headerText}
            </p>
            <a
              href={workflowUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-bold border ${pillCls} hover:opacity-80`}
              data-testid={`${testId}-pill`}
              title="Open the GitHub Actions runs page for this workflow"
            >
              {pillLabel}
            </a>
          </div>
          {subText != null && (
            <p className="text-[11px] text-gray-500 mt-0.5">
              {subText}
            </p>
          )}
          {alertCaption && (
            <p
              className={`text-[11px] mt-0.5 ${alertCaptionCls}`}
              data-testid={`${testId}-alert-state`}
            >
              {alertCaption}
            </p>
          )}
        </div>
        {extraActions}
        <a
          href={workflowUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[11px] text-violet-600 hover:text-violet-700 inline-flex items-center gap-1"
          data-testid={`${testId}-run-link`}
          title="Open the GitHub Actions runs page for this workflow"
        >
          Runs <ExternalLink size={11} />
        </a>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-white/60"
          // Task #882 — primary testId follows the AdminHealth cron-pill
          // convention documented in replit.md (`<prefix>-refresh`); the
          // `data-testid-legacy` attribute carries the historical
          // `button-refresh-<prefix>` form so any external selector
          // (Cloudflare Browser Rendering uptime probe, runbook
          // screenshots, etc.) that grew up against the old shape
          // before the convention block was added does not break.
          // Querying by `data-testid` (the React Testing Library
          // default) sees only the convention-correct primary form.
          data-testid={`${testId}-refresh`}
          data-testid-legacy={`button-refresh-${testId}`}
          title="Refresh"
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>
    </div>
  );
}
