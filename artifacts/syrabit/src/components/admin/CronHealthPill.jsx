import React, { useState, useCallback } from 'react';
import {
  AlertTriangle, ShieldCheck, Clock, RefreshCw, ExternalLink,
  ChevronDown, ChevronUp, History,
} from 'lucide-react';
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

// Task #918 — render a single audit-log row inside the history panel.
// One paged-on-call event ("paged Xh ago · failure · run #123") with
// a deep-link to the offending GitHub Actions run when present. Kept
// inline so the panel stays self-contained and the pill's wrappers
// don't need to know anything about the row layout.
function HistoryEventRow({ event, ageLabel: fmt, testId, index }) {
  const pagedAt = event?.pagedAt ? new Date(event.pagedAt) : null;
  // Recompute the "Xh ago" label client-side off the persisted
  // ISO timestamp so it stays accurate as the panel sits open
  // across the 60s polling interval (the backend can't predict
  // when the admin will look at it).
  const ageSecs = pagedAt
    ? Math.max(0, Math.floor((Date.now() - pagedAt.getTime()) / 1000))
    : null;
  const ageStr = fmt(ageSecs);
  const kindRaw = (event?.kind || '').toString();
  const kindLabel = kindRaw === 'recovered'
    ? 'recovered'
    : kindRaw === 'broken' || kindRaw === 'silent'
      ? 'paged'
      : kindRaw || 'event';
  const kindCls = kindRaw === 'recovered'
    ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
    : kindRaw === 'broken' || kindRaw === 'silent'
      ? 'bg-red-100 text-red-700 border-red-200'
      : 'bg-gray-100 text-gray-600 border-gray-200';
  const subKindLabel = event?.subKind ? ` (${event.subKind})` : '';
  const conclusion = event?.lastConclusion;
  const runUrl = event?.lastRunUrl || event?.lastHtmlUrl;
  const runId = event?.lastRunId;
  const tooltipDate = pagedAt ? pagedAt.toISOString() : '';
  return (
    <li
      className="flex items-center gap-2 py-1 text-[11px] text-gray-600"
      data-testid={`${testId}-history-event`}
      data-history-event-index={index}
    >
      <span
        className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold border ${kindCls}`}
      >
        {kindLabel.toUpperCase()}{subKindLabel}
      </span>
      <span title={tooltipDate} className="text-gray-500">
        {ageStr ? `${ageStr} ago` : 'just now'}
      </span>
      {conclusion && (
        <span className="text-gray-400">· {conclusion}</span>
      )}
      {runUrl && (
        <a
          href={runUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto text-violet-600 hover:text-violet-700 inline-flex items-center gap-1"
          title="Open the offending workflow run"
        >
          {runId ? `run #${runId}` : 'run'} <ExternalLink size={10} />
        </a>
      )}
    </li>
  );
}

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
  // Task #918 — optional paged-on-call audit log from
  // `/admin/health/<pill>/cron/alert-history`. When `onLoadAlertHistory`
  // is provided the pill renders a "Show paged history" disclosure
  // button under the alert-state caption; clicking it lazy-fetches
  // (via the parent's loader) and expands an inline panel listing
  // up to ~20 alerter events (page + recovery), most recent first.
  // Decoupled from `alertState` so the wrappers can opt into one,
  // both, or neither without coupling the two contracts. Shape:
  //   { events: [{ pagedAt, kind, subKind, lastRunUrl,
  //                lastConclusion, lastRunId, ... }], lockId, limit }
  // — see _build_alert_history_response in routes/admin_health.py.
  alertHistory,
  onLoadAlertHistory,
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

  // Task #918 — paged-on-call audit-log disclosure. The toggle is
  // only rendered when the wrapper opted in by passing
  // `onLoadAlertHistory`; this keeps existing callers (and the
  // `<CronHealthPill />` snapshot tests above) untouched. The panel
  // is lazy — page load does NOT pre-fetch history (would carry
  // N×20 events nobody asked for) and the parent's 60s polling
  // intentionally skips it too. Instead the loader fires on every
  // open: admin opens → fresh data, admin closes (no fetch),
  // admin reopens → fresh data again. Closing is free; opening
  // is the user's explicit "show me the latest" gesture.
  const [historyOpen, setHistoryOpen] = useState(false);
  const events = alertHistory?.events || [];
  const eventCount = events.length;
  const historyEnabled = typeof onLoadAlertHistory === 'function';
  const onToggleHistory = useCallback(() => {
    setHistoryOpen((prev) => {
      const next = !prev;
      if (next && historyEnabled) {
        try { onLoadAlertHistory(); } catch (_e) { /* best-effort */ }
      }
      return next;
    });
  }, [historyEnabled, onLoadAlertHistory]);

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
          {historyEnabled && (
            <button
              type="button"
              onClick={onToggleHistory}
              className="mt-1 text-[11px] text-violet-600 hover:text-violet-700 inline-flex items-center gap-1"
              data-testid={`${testId}-history-toggle`}
              aria-expanded={historyOpen}
              title={historyOpen
                ? 'Hide the paged-on-call history for this cron'
                : 'Show the recent paged-on-call history for this cron'}
            >
              <History size={11} />
              {historyOpen
                ? 'Hide paged history'
                : (alertHistory && eventCount > 0
                    ? `Show paged history (${eventCount})`
                    : 'Show paged history')}
              {historyOpen
                ? <ChevronUp size={11} />
                : <ChevronDown size={11} />}
            </button>
          )}
          {historyEnabled && historyOpen && (
            <div
              className="mt-1.5 rounded-lg border border-gray-200 bg-white/60 px-2 py-1"
              data-testid={`${testId}-history-panel`}
            >
              {!alertHistory ? (
                <p
                  className="text-[11px] text-gray-400 py-1"
                  data-testid={`${testId}-history-loading`}
                >
                  Loading paged history…
                </p>
              ) : eventCount === 0 ? (
                <p
                  className="text-[11px] text-gray-400 py-1"
                  data-testid={`${testId}-history-empty`}
                >
                  No on-call pages recorded yet for this cron.
                </p>
              ) : (
                <ul className="divide-y divide-gray-100">
                  {events.map((ev, idx) => (
                    <HistoryEventRow
                      key={ev?.id || idx}
                      event={ev}
                      ageLabel={ageLabel}
                      testId={testId}
                      index={idx}
                    />
                  ))}
                </ul>
              )}
            </div>
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
