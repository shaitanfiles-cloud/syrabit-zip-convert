import React from 'react';
import CronHealthPill from './CronHealthPill';

// Task #838 — sibling pill for the daily Trustpilot
// aggregate-refresh GitHub Actions cron (Task #751,
// /admin/health/trustpilot/refresh-cron). Same shape as the
// firewall-drift wrapper next to it, but with Trustpilot-specific
// header copy and a TWO-line caption that surfaces both the most
// recent successful heartbeat (the one that actually proves the
// cron ran end-to-end) AND the most recent any-status heartbeat
// (so a flapping cron that pings successfully every other run is
// visible without clicking through to GitHub Actions).
//
// Extracted from AdminHealth.jsx so the colour mapping, header
// copy, and the dual-heartbeat caption can be unit-tested in
// isolation (see TrustpilotRefreshCronPill.test.jsx). The visual
// output is unchanged from the prior inline <CronHealthPill ...>
// block; only the testId moved from "trustpilot-cron" to
// "trustpilot-refresh-cron" so it lines up with the cf-waf-drift
// pill's naming convention and reads correctly in DOM dumps
// (e.g. "trustpilot-refresh-cron-pill" vs "trustpilot-cron-pill").

const HEADER_TEXT_BY_STATUS = {
  healthy: 'Trustpilot refresh cron — checking in',
  silent: 'Trustpilot refresh cron — silent',
  degraded: 'Trustpilot refresh cron — last run failed',
  never_observed: 'Trustpilot refresh cron — no heartbeat yet',
  not_configured: 'Trustpilot refresh cron — not configured',
  unknown: 'Trustpilot refresh cron — status unknown',
};

const DEFAULT_WORKFLOW_URL =
  'https://github.com/syrabit/syrabit/actions/workflows/trustpilot-aggregate-refresh.yml';

const renderSubText = ({ data, ageLabel: fmt }) => {
  const successLbl = fmt(data?.lastSuccessHeartbeatAgeSeconds);
  const anyLbl = fmt(data?.lastHeartbeatAgeSeconds);
  // Two-line caption logic (extracted unchanged from AdminHealth.jsx):
  //   - Always show the last successful heartbeat (or a "no successful
  //     heartbeat recorded" fallback if the cron has never finished
  //     successfully).
  //   - When a more recent ANY-status heartbeat exists (or no
  //     successful one is known), append " · last heartbeat (any) Xm
  //     ago" so admins can tell apart "cron is silent" from "cron
  //     keeps running but keeps failing".
  return (
    <>
      {successLbl
        ? `Last successful heartbeat ${successLbl} ago`
        : 'No successful heartbeat recorded'}
      {anyLbl && (!successLbl || anyLbl !== successLbl)
        ? ` · last heartbeat (any) ${anyLbl} ago`
        : ''}
    </>
  );
};

export default function TrustpilotRefreshCronPill({ data, loading, onRefresh }) {
  return (
    <CronHealthPill
      data={data}
      loading={loading}
      onRefresh={onRefresh}
      testId="trustpilot-refresh-cron"
      defaultWorkflowUrl={DEFAULT_WORKFLOW_URL}
      headerTextByStatus={HEADER_TEXT_BY_STATUS}
      renderSubText={renderSubText}
    />
  );
}
