/**
 * Task #944 — Unified Log Explorer admin panel.
 *
 * One pane of glass for every log-emitting surface in the stack:
 *   - source=edge       Cloudflare worker request samples
 *   - source=cloudflare GraphQL pull (CF-side cache + edge metadata)
 *   - source=backend    FastAPI per-request samples
 *   - source=cron       background job heartbeats / failures
 *   - source=pages      Cloudflare Pages function logs (when wired)
 *
 * Server-side TTL keeps the collection bounded and the API caps every
 * query (``MAX_QUERY_LIMIT``) so a misclick can never page in millions
 * of rows. The UI virtualises by simply rendering only the current
 * page; a "Load older" button grabs the next cursor-paginated page.
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  RefreshCw, Download, Search, Pause, Play, Trash2, Link as LinkIcon,
  Activity, AlertTriangle, AlertOctagon, Info, X, KeyRound, Filter,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  adminLogsList, adminLogsStatus, adminLogsTrace, adminLogsPause,
  adminLogsResume, adminLogsRotateToken, adminLogsClear,
  adminLogsExportUrl, adminLogsDownloadExport,
} from '@/utils/api';
import { SectionErrorBoundary } from '@/components/ErrorBoundary';

const SOURCE_OPTIONS = [
  { id: 'edge',       label: 'Edge worker' },
  { id: 'cloudflare', label: 'Cloudflare GraphQL' },
  { id: 'backend',    label: 'Backend (FastAPI)' },
  { id: 'pages',      label: 'CF Pages' },
  { id: 'cron',       label: 'Cron / jobs' },
];
const LEVEL_OPTIONS = ['debug', 'info', 'warn', 'error'];
const TIME_PRESETS = [
  { id: '15m', label: 'Last 15m', minutes: 15 },
  { id: '1h',  label: 'Last 1h',  minutes: 60 },
  { id: '6h',  label: 'Last 6h',  minutes: 360 },
  { id: '24h', label: 'Last 24h', minutes: 1440 },
  { id: '7d',  label: 'Last 7d',  minutes: 1440 * 7 },
];
const PAGE_SIZE = 200;
const LIVE_TAIL_INTERVAL_MS = 4000;

const SOURCE_BADGE = {
  edge:       'bg-amber-100 text-amber-800 border-amber-200',
  cloudflare: 'bg-orange-100 text-orange-800 border-orange-200',
  backend:    'bg-indigo-100 text-indigo-800 border-indigo-200',
  pages:      'bg-emerald-100 text-emerald-800 border-emerald-200',
  cron:       'bg-violet-100 text-violet-800 border-violet-200',
};
const LEVEL_ICON = {
  debug: { Icon: Info,         color: 'text-slate-500' },
  info:  { Icon: Info,         color: 'text-blue-600'  },
  warn:  { Icon: AlertTriangle,color: 'text-amber-600' },
  error: { Icon: AlertOctagon, color: 'text-red-600'   },
};

function timeWindowFromPreset(preset) {
  const now = new Date();
  const since = new Date(now.getTime() - preset.minutes * 60 * 1000);
  return { since: since.toISOString(), until: now.toISOString() };
}

function fmtTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-IN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      day: '2-digit', month: 'short',
    });
  } catch { return String(iso).slice(0, 19); }
}

function fmtMs(n) {
  if (n == null) return '—';
  if (n < 1000) return `${n}ms`;
  return `${(n / 1000).toFixed(2)}s`;
}

function statusClass(status) {
  if (status == null) return 'text-slate-500';
  if (status >= 500) return 'text-red-600 font-semibold';
  if (status >= 400) return 'text-amber-600 font-semibold';
  if (status >= 300) return 'text-blue-600';
  return 'text-emerald-700';
}

export default function AdminLogsExplorer({ adminToken }) {
  const [filters, setFilters] = useState({
    sources: [],
    levels:  [],
    route_prefix: '',
    correlation_id: '',
    q: '',
    status_min: '',
    status_max: '',
  });
  const [preset, setPreset] = useState('1h');
  const [logs, setLogs]       = useState([]);
  const [total, setTotal]     = useState(0);
  const [totalCapped, setTotalCapped] = useState(false);
  const [nextBefore, setNextBefore]   = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [status, setStatus]   = useState(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [liveTail, setLiveTail] = useState(false);
  const [traceModal, setTraceModal] = useState(null); // { cid, logs[], loading }
  const [confirmClearOpen, setConfirmClearOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [clearing, setClearing] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [rotatedToken, setRotatedToken] = useState(null);
  const [pendingPause, setPendingPause] = useState(false);

  const window_ = useMemo(() => {
    const p = TIME_PRESETS.find((x) => x.id === preset) || TIME_PRESETS[1];
    return timeWindowFromPreset(p);
  }, [preset]);
  const fullFilters = useMemo(() => ({ ...filters, ...window_ }),
    [filters, window_]);

  const load = useCallback(async ({ append = false, before = null } = {}) => {
    setLoading(true);
    setError(null);
    try {
      const r = await adminLogsList(adminToken, {
        filters: fullFilters, limit: PAGE_SIZE,
        before: before || undefined,
      });
      const data = r.data || {};
      const rows = Array.isArray(data.logs) ? data.logs : [];
      setLogs((prev) => append ? [...prev, ...rows] : rows);
      setTotal(data.total ?? rows.length);
      setTotalCapped(!!data.total_capped);
      setNextBefore(data.next_before || null);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load logs');
      if (!append) setLogs([]);
    } finally {
      setLoading(false);
    }
  }, [adminToken, fullFilters]);

  const loadStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const r = await adminLogsStatus(adminToken);
      setStatus(r.data || null);
    } catch {
      setStatus(null);
    } finally {
      setStatusLoading(false);
    }
  }, [adminToken]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadStatus(); }, [loadStatus]);

  // Live tail — re-poll the FIRST page only (no cursor) every 4s.
  // Stops as soon as the user toggles it off or the tab is hidden.
  useEffect(() => {
    if (!liveTail) return undefined;
    const handle = setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      load();
    }, LIVE_TAIL_INTERVAL_MS);
    return () => clearInterval(handle);
  }, [liveTail, load]);

  const toggleArrayFilter = (field, value) => {
    setFilters((f) => {
      const cur = f[field] || [];
      const next = cur.includes(value)
        ? cur.filter((x) => x !== value)
        : [...cur, value];
      return { ...f, [field]: next };
    });
  };

  const handlePauseToggle = async () => {
    if (!status) return;
    setPendingPause(true);
    try {
      const fn = status.paused ? adminLogsResume : adminLogsPause;
      await fn(adminToken);
      toast.success(status.paused ? 'Ingest resumed' : 'Ingest paused');
      await loadStatus();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to toggle pause');
    } finally {
      setPendingPause(false);
    }
  };

  const handleRotateToken = async () => {
    setRotating(true);
    try {
      const r = await adminLogsRotateToken(adminToken);
      setRotatedToken(r.data?.token || '');
      toast.success('Ingest token rotated — copy it now');
      await loadStatus();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to rotate token');
    } finally {
      setRotating(false);
    }
  };

  const handleClearConfirmed = async () => {
    if (confirmText !== 'CLEAR' || clearing) return;
    setClearing(true);
    try {
      const r = await adminLogsClear(adminToken, filters.sources || []);
      toast.success(`Cleared ${r.data?.deleted ?? 0} entries — purge is logged in Activity Log`);
      setConfirmClearOpen(false);
      setConfirmText('');
      load();
      loadStatus();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Failed to clear logs');
    } finally {
      setClearing(false);
    }
  };

  const openTrace = async (cid) => {
    if (!cid) return;
    setTraceModal({ cid, logs: [], loading: true });
    try {
      const r = await adminLogsTrace(adminToken, cid);
      setTraceModal({ cid, logs: r.data?.logs || [], loading: false });
    } catch (e) {
      setTraceModal({ cid, logs: [], loading: false,
        error: e?.response?.data?.detail || 'Failed to fetch trace' });
    }
  };

  // Authenticated downloads — go through the Bearer-authed blob helper
  // so the export works in environments where the admin only has a
  // JWT (no admin cookie). Falls back to a new-tab open if the
  // download itself errors (e.g. CORS) so the admin always has a way
  // to recover the file.
  const exportCsv = async () => {
    try {
      const fname = await adminLogsDownloadExport(adminToken, { filters: fullFilters, fmt: 'csv' });
      toast.success(`Downloaded ${fname}`);
    } catch (e) {
      const url = adminLogsExportUrl({ filters: fullFilters, fmt: 'csv' });
      window.open(url, '_blank', 'noopener');
      toast.error('Bearer download failed — opened legacy URL fallback');
    }
  };
  const exportNdjson = async () => {
    try {
      const fname = await adminLogsDownloadExport(adminToken, { filters: fullFilters, fmt: 'ndjson' });
      toast.success(`Downloaded ${fname}`);
    } catch (e) {
      const url = adminLogsExportUrl({ filters: fullFilters, fmt: 'ndjson' });
      window.open(url, '_blank', 'noopener');
      toast.error('Bearer download failed — opened legacy URL fallback');
    }
  };

  return (
    <SectionErrorBoundary section="Logs Explorer">
      <div className="p-4 md:p-6 space-y-4">
        {/* ── Header bar ─────────────────────────────────────────── */}
        <div className="flex flex-wrap items-center gap-2 justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-indigo-600" />
            <h2 className="text-xl font-semibold">Unified Logs</h2>
            {status && (
              <StatusPill status={status} statusLoading={statusLoading} />
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => load()}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-sm border rounded hover:bg-slate-50"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
            <label className="inline-flex items-center gap-1 px-3 py-1.5 text-sm border rounded cursor-pointer hover:bg-slate-50">
              <input
                type="checkbox"
                className="accent-indigo-600"
                checked={liveTail}
                onChange={(e) => setLiveTail(e.target.checked)}
              />
              Live tail
            </label>
            <button
              type="button"
              onClick={handlePauseToggle}
              disabled={pendingPause || !status}
              className={`inline-flex items-center gap-1 px-3 py-1.5 text-sm border rounded ${
                status?.paused
                  ? 'bg-emerald-50 hover:bg-emerald-100 border-emerald-300 text-emerald-800'
                  : 'bg-amber-50 hover:bg-amber-100 border-amber-300 text-amber-800'
              } disabled:opacity-50`}
            >
              {status?.paused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
              {status?.paused ? 'Resume ingest' : 'Pause ingest'}
            </button>
            <button
              type="button"
              onClick={exportCsv}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-sm border rounded hover:bg-slate-50"
            >
              <Download className="w-4 h-4" />
              CSV
            </button>
            <button
              type="button"
              onClick={exportNdjson}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-sm border rounded hover:bg-slate-50"
            >
              <Download className="w-4 h-4" />
              NDJSON
            </button>
            <button
              type="button"
              onClick={handleRotateToken}
              disabled={rotating}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-sm border rounded hover:bg-slate-50 disabled:opacity-50"
              title="Generate a new ingest token. The plaintext is shown ONCE — copy it to the worker secret store before closing the dialog."
            >
              <KeyRound className="w-4 h-4" />
              Rotate token
            </button>
            <button
              type="button"
              onClick={() => { setConfirmText(''); setConfirmClearOpen(true); }}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-sm border rounded text-red-700 border-red-300 hover:bg-red-50"
            >
              <Trash2 className="w-4 h-4" />
              Clear
            </button>
          </div>
        </div>

        {/* ── Filter bar ──────────────────────────────────────────── */}
        <div className="bg-slate-50 border rounded p-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Filter className="w-4 h-4 text-slate-500" />
            <span className="text-xs uppercase tracking-wider text-slate-500">Time</span>
            {TIME_PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => setPreset(p.id)}
                className={`px-2 py-1 text-xs rounded border ${
                  preset === p.id
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white hover:bg-slate-100'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs uppercase tracking-wider text-slate-500">Source</span>
            {SOURCE_OPTIONS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => toggleArrayFilter('sources', s.id)}
                className={`px-2 py-1 text-xs rounded border ${
                  filters.sources.includes(s.id)
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white hover:bg-slate-100'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs uppercase tracking-wider text-slate-500">Level</span>
            {LEVEL_OPTIONS.map((lv) => (
              <button
                key={lv}
                type="button"
                onClick={() => toggleArrayFilter('levels', lv)}
                className={`px-2 py-1 text-xs rounded border capitalize ${
                  filters.levels.includes(lv)
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white hover:bg-slate-100'
                }`}
              >
                {lv}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <input
              type="text"
              placeholder="Route prefix (e.g. /api/admin/)"
              value={filters.route_prefix}
              onChange={(e) => setFilters((f) => ({ ...f, route_prefix: e.target.value }))}
              className="px-3 py-2 text-sm border rounded"
            />
            <input
              type="text"
              placeholder="Correlation / ray id"
              value={filters.correlation_id}
              onChange={(e) => setFilters((f) => ({ ...f, correlation_id: e.target.value }))}
              className="px-3 py-2 text-sm border rounded"
            />
            <div className="relative">
              <Search className="w-4 h-4 absolute top-2.5 left-2 text-slate-400" />
              <input
                type="text"
                placeholder="Free text (message / route)"
                value={filters.q}
                onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
                className="pl-7 pr-3 py-2 text-sm border rounded w-full"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <input
              type="number"
              min="0" max="999"
              placeholder="Status min (e.g. 400)"
              value={filters.status_min}
              onChange={(e) => setFilters((f) => ({ ...f, status_min: e.target.value }))}
              className="px-3 py-2 text-sm border rounded"
            />
            <input
              type="number"
              min="0" max="999"
              placeholder="Status max (e.g. 599)"
              value={filters.status_max}
              onChange={(e) => setFilters((f) => ({ ...f, status_max: e.target.value }))}
              className="px-3 py-2 text-sm border rounded"
            />
            <button
              type="button"
              onClick={() => load()}
              className="px-3 py-2 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 col-span-2 md:col-span-1"
            >
              Apply filters
            </button>
            <button
              type="button"
              onClick={() => {
                setFilters({
                  sources: [], levels: [], route_prefix: '',
                  correlation_id: '', q: '', status_min: '', status_max: '',
                });
              }}
              className="px-3 py-2 text-sm rounded border hover:bg-slate-100 col-span-2 md:col-span-1"
            >
              Reset
            </button>
          </div>
        </div>

        {/* ── Result count + error ────────────────────────────────── */}
        <div className="flex items-center justify-between text-sm text-slate-600">
          <span>
            Showing {logs.length}
            {total ? ` of ${total}${totalCapped ? '+' : ''}` : ''} entries
          </span>
          {error && <span className="text-red-600">{error}</span>}
        </div>

        {/* ── Table ──────────────────────────────────────────────── */}
        <div className="border rounded overflow-x-auto bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-600 text-xs uppercase">
              <tr>
                <th className="text-left px-3 py-2">Time</th>
                <th className="text-left px-3 py-2">Source</th>
                <th className="text-left px-3 py-2">Level</th>
                <th className="text-left px-3 py-2">Status</th>
                <th className="text-left px-3 py-2">Route</th>
                <th className="text-left px-3 py-2">Country / Colo</th>
                <th className="text-left px-3 py-2">Cache</th>
                <th className="text-right px-3 py-2">Duration</th>
                <th className="text-left px-3 py-2">Correlation</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((row) => {
                const lvl = LEVEL_ICON[row.level] || LEVEL_ICON.info;
                const Icon = lvl.Icon;
                return (
                  <tr key={`${row.timestamp}-${row.correlation_id || row.message}-${Math.random()}`}
                      className="border-t hover:bg-slate-50">
                    <td className="px-3 py-1.5 whitespace-nowrap font-mono text-xs">
                      {fmtTime(row.timestamp)}
                    </td>
                    <td className="px-3 py-1.5 whitespace-nowrap">
                      <span className={`inline-block px-2 py-0.5 text-xs rounded border ${SOURCE_BADGE[row.source] || 'bg-slate-100 text-slate-700'}`}>
                        {row.source}
                      </span>
                    </td>
                    <td className="px-3 py-1.5">
                      <span className={`inline-flex items-center gap-1 text-xs ${lvl.color}`}>
                        <Icon className="w-3 h-3" /> {row.level}
                      </span>
                    </td>
                    <td className={`px-3 py-1.5 font-mono text-xs ${statusClass(row.status)}`}>
                      {row.status ?? '—'}
                    </td>
                    <td className="px-3 py-1.5 max-w-md truncate font-mono text-xs"
                        title={row.message || row.route}>
                      <span className="text-slate-400 mr-1">{row.method || '—'}</span>
                      {row.route || row.message || '—'}
                    </td>
                    <td className="px-3 py-1.5 whitespace-nowrap text-xs">
                      {row.country || '—'}{row.colo ? ` / ${row.colo}` : ''}
                    </td>
                    <td className="px-3 py-1.5 text-xs">{row.cache || '—'}</td>
                    <td className="px-3 py-1.5 text-right font-mono text-xs">
                      {fmtMs(row.duration_ms)}
                    </td>
                    <td className="px-3 py-1.5">
                      {row.correlation_id ? (
                        <button
                          type="button"
                          onClick={() => openTrace(row.correlation_id)}
                          className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:underline font-mono"
                          title="Open trace for this correlation id"
                        >
                          <LinkIcon className="w-3 h-3" />
                          {String(row.correlation_id).slice(0, 14)}
                        </button>
                      ) : '—'}
                    </td>
                  </tr>
                );
              })}
              {!loading && logs.length === 0 && (
                <tr><td colSpan={9} className="text-center py-10 text-slate-400">
                  No log entries match the current filters.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        {nextBefore && (
          <div className="flex justify-center">
            <button
              type="button"
              onClick={() => load({ append: true, before: nextBefore })}
              disabled={loading}
              className="px-4 py-2 text-sm border rounded hover:bg-slate-50 disabled:opacity-50"
            >
              {loading ? 'Loading…' : 'Load older entries'}
            </button>
          </div>
        )}

        {/* ── Trace modal ────────────────────────────────────────── */}
        {traceModal && (
          <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
               onClick={() => setTraceModal(null)}>
            <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[80vh] overflow-hidden flex flex-col"
                 onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between px-4 py-3 border-b">
                <div>
                  <h3 className="font-semibold">Trace</h3>
                  <p className="text-xs text-slate-500 font-mono">{traceModal.cid}</p>
                </div>
                <button
                  type="button"
                  onClick={() => setTraceModal(null)}
                  className="p-1 hover:bg-slate-100 rounded"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="overflow-auto p-4 space-y-2">
                {traceModal.loading && <p className="text-slate-500">Loading trace…</p>}
                {traceModal.error && <p className="text-red-600">{traceModal.error}</p>}
                {!traceModal.loading && !traceModal.error && traceModal.logs.length === 0 && (
                  <p className="text-slate-500">No entries share this correlation id.</p>
                )}
                {traceModal.logs.map((row, i) => (
                  <div key={i} className="border rounded p-2 text-xs font-mono">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`inline-block px-1.5 py-0.5 rounded border ${SOURCE_BADGE[row.source] || 'bg-slate-100'}`}>
                        {row.source}
                      </span>
                      <span className={statusClass(row.status)}>{row.status ?? '—'}</span>
                      <span className="text-slate-400">{fmtTime(row.timestamp)}</span>
                      <span className="ml-auto">{fmtMs(row.duration_ms)}</span>
                    </div>
                    <div className="text-slate-700">{row.method} {row.route}</div>
                    {row.message && row.message !== `${row.method} ${row.route} → ${row.status}` && (
                      <div className="text-slate-500 mt-1">{row.message}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Rotate-token disclosure ─────────────────────────────── */}
        {rotatedToken && (
          <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
               onClick={() => setRotatedToken(null)}>
            <div className="bg-white rounded-lg shadow-xl max-w-lg w-full p-4 space-y-3"
                 onClick={(e) => e.stopPropagation()}>
              <h3 className="font-semibold flex items-center gap-2">
                <KeyRound className="w-4 h-4 text-amber-600" />
                New ingest token
              </h3>
              <p className="text-sm text-slate-600">
                Copy this token now — it will not be shown again. Update the
                ``LOG_INGEST_TOKEN`` secret on the edge worker (and any other
                producer) to start posting under the new credential.
              </p>
              <textarea
                readOnly
                value={rotatedToken}
                className="w-full font-mono text-xs border rounded p-2"
                rows={3}
                onFocus={(e) => e.target.select()}
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard?.writeText(rotatedToken);
                    toast.success('Token copied to clipboard');
                  }}
                  className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
                >
                  Copy
                </button>
                <button
                  type="button"
                  onClick={() => setRotatedToken(null)}
                  className="px-3 py-1.5 text-sm rounded border hover:bg-slate-50"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Clear-with-typed-confirm ────────────────────────────── */}
        {confirmClearOpen && (
          <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
               onClick={() => !clearing && setConfirmClearOpen(false)}>
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-4 space-y-3"
                 onClick={(e) => e.stopPropagation()}>
              <h3 className="font-semibold flex items-center gap-2 text-red-700">
                <Trash2 className="w-4 h-4" />
                Clear unified logs
              </h3>
              <p className="text-sm text-slate-600">
                {(filters.sources && filters.sources.length)
                  ? `This will delete every log entry whose source is one of: ${filters.sources.join(', ')}. `
                  : 'This will delete EVERY log entry across every source. '}
                The action is recorded in the Activity Log.
              </p>
              <p className="text-xs text-slate-500">Type <code className="bg-slate-100 px-1">CLEAR</code> to confirm:</p>
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                className="w-full px-3 py-2 border rounded font-mono"
                autoFocus
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => { setConfirmClearOpen(false); setConfirmText(''); }}
                  disabled={clearing}
                  className="px-3 py-1.5 text-sm rounded border hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleClearConfirmed}
                  disabled={confirmText !== 'CLEAR' || clearing}
                  className="px-3 py-1.5 text-sm rounded bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {clearing ? 'Clearing…' : 'Clear logs'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </SectionErrorBoundary>
  );
}

function StatusPill({ status, statusLoading }) {
  if (statusLoading) {
    return <span className="text-xs text-slate-400 ml-2">loading status…</span>;
  }
  const paused = !!status?.paused;
  return (
    <div className="ml-2 inline-flex items-center gap-2 text-xs">
      <span className={`inline-block w-2 h-2 rounded-full ${paused ? 'bg-amber-500' : 'bg-emerald-500'}`} />
      <span className="text-slate-700">{paused ? 'Paused' : 'Active'}</span>
      {status?.ttl_days != null && (
        <span className="text-slate-400">· TTL {status.ttl_days}d</span>
      )}
      {status?.cf_pull_last_run && (
        <span className="text-slate-400">· last CF pull {fmtTime(status.cf_pull_last_run)}</span>
      )}
      {!status?.ingest_token_configured && (
        <span className="text-amber-600 font-semibold">· ingest token not set</span>
      )}
    </div>
  );
}
