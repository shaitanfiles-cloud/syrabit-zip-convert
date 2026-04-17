import { useState, useEffect, useCallback } from 'react';
import { Database, Zap, CreditCard, RefreshCw, ShieldCheck, AlertTriangle, Wifi, Copy, Check, Users, Activity, MessageSquare, TrendingUp, DollarSign, BarChart2, RotateCw, Clock } from 'lucide-react';
import { toast } from 'sonner';
import AdminQuickLinks from './AdminQuickLinks';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, BarChart, Bar } from 'recharts';
import axios from 'axios';
import { llmCosts, API_BASE } from '@/utils/api';

const adminHeaders = (token) => {
  const isRealJwt = token && typeof token === 'string' && token.split('.').length === 3;
  return isRealJwt ? { Authorization: `Bearer ${token}` } : {};
};

function LatencyBadge({ ms }) {
  if (!ms && ms !== 0) return <span className="text-xs text-gray-400">—</span>;
  const color = ms < 200 ? 'text-emerald-600' : ms < 600 ? 'text-amber-600' : 'text-red-600';
  return <span className={`text-xs font-mono ${color}`}>{ms}ms</span>;
}

function PeakBadge({ label, value, color = 'violet' }) {
  const colors = {
    violet: 'bg-violet-50 text-violet-600 border-violet-200',
    emerald: 'bg-emerald-50 text-emerald-600 border-emerald-200',
    amber: 'bg-amber-50 text-amber-600 border-amber-200',
    blue: 'bg-blue-50 text-blue-600 border-blue-200',
  };
  return (
    <div className={`rounded-xl border px-4 py-3 ${colors[color]} bg-white`}>
      <p className="text-[10px] uppercase tracking-wider opacity-60 mb-1">{label}</p>
      <p className="text-2xl font-bold font-mono" data-testid={`peak-${label.replace(/\s+/g, '-').toLowerCase()}`}>{value}</p>
    </div>
  );
}

const TOOLTIP_STYLE = { background: '#ffffff', border: '1px solid #e5e7eb', borderRadius: '12px', color: '#374151', fontSize: 12, boxShadow: '0 4px 16px rgba(0,0,0,0.08)' };

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={TOOLTIP_STYLE} className="p-3">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-xs" style={{ color: p.color }}>
          {p.name}: <span className="font-mono font-bold">{p.value}</span>
        </p>
      ))}
    </div>
  );
}

function formatRelative(epochSec) {
  if (!epochSec) return 'never';
  const d = new Date(epochSec * 1000);
  const diff = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// Backend contract from artifacts/syrabit-backend/pages_deploy.py status():
//   configured: bool
//   last_triggered_at: float epoch seconds | null
//   last_status: "ok" | "http_NNN" | "error" | "not_configured" | null
//   last_reason: string | null
//   last_error: string | null
//   pending_reasons: string[]
//   pending: bool
//   trigger_count: int
//   coalesce_window_sec / min_interval_sec / nightly_interval_sec: int
function classifyStatus(s) {
  if (s === 'ok') return 'ok';
  if (s === null || s === undefined) return 'idle';
  // "error", "not_configured", or any "http_NNN" — all failure modes.
  return 'fail';
}

function PrerenderStatusBody({ status }) {
  const {
    configured,
    last_triggered_at: last,
    last_status: lastStatus,
    last_reason: lastReason,
    last_error: lastError,
    pending_reasons: pendingReasons = [],
    pending,
    trigger_count: triggerCount,
    coalesce_window_sec: coalesceSec,
    min_interval_sec: minIntervalSec,
    nightly_interval_sec: nightlySec,
  } = status;

  const klass = classifyStatus(lastStatus);
  const statusColor =
    klass === 'ok'   ? 'text-emerald-600 bg-emerald-50 border-emerald-200'
    : klass === 'fail' ? 'text-red-600 bg-red-50 border-red-200'
    : 'text-gray-500 bg-gray-50 border-gray-200';
  const statusLabel = lastStatus ?? 'never fired';

  return (
    <div className="space-y-3">
      {configured === false && (
        <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-700">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span><span className="font-mono font-semibold">CF_PAGES_DEPLOY_HOOK_URL</span> is not configured on the backend. Refresh requests will fail.</span>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="rounded-xl p-3 border border-gray-200 bg-white">
          <p className="text-[10px] uppercase tracking-wider text-gray-400 mb-1 flex items-center gap-1">
            <Clock size={10} /> Last fired
          </p>
          <p className="text-sm font-mono font-semibold text-gray-900" data-testid="prerender-last-fired">
            {formatRelative(last)}
          </p>
          {last && (
            <p className="text-[10px] text-gray-400 mt-0.5">
              {new Date(last * 1000).toLocaleString()}
            </p>
          )}
        </div>

        <div className={`rounded-xl p-3 border ${statusColor}`}>
          <p className="text-[10px] uppercase tracking-wider opacity-60 mb-1">Last status</p>
          <p className="text-sm font-mono font-semibold" data-testid="prerender-last-status">{statusLabel}</p>
          {lastReason && <p className="text-[10px] opacity-70 mt-0.5 truncate" title={lastReason}>{lastReason}</p>}
        </div>

        <div className="rounded-xl p-3 border border-gray-200 bg-white">
          <p className="text-[10px] uppercase tracking-wider text-gray-400 mb-1">Pending reasons</p>
          <p className="text-sm font-mono font-semibold text-gray-900" data-testid="prerender-queued-count">
            {pendingReasons.length}{pending ? ' · queued' : ''}
          </p>
          {pendingReasons.length > 0 && (
            <p className="text-[10px] text-gray-400 mt-0.5 truncate" title={pendingReasons.join(', ')}>
              {pendingReasons.slice(0, 3).join(', ')}{pendingReasons.length > 3 ? '…' : ''}
            </p>
          )}
        </div>
      </div>

      {lastError && (
        <div className="flex items-start gap-2 p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <div>
            <p className="font-semibold mb-0.5">Last error</p>
            <p className="font-mono break-all">{String(lastError)}</p>
          </div>
        </div>
      )}

      <div className="text-[11px] text-gray-400 leading-relaxed border-t border-gray-100 pt-3 mt-1">
        Total triggers: <span className="font-mono text-gray-600">{triggerCount ?? 0}</span>
        {' · '}
        coalesce window <span className="font-mono text-gray-600">{coalesceSec ?? '?'}s</span>
        {' · '}
        cooldown <span className="font-mono text-gray-600">{minIntervalSec ?? '?'}s</span>
        {' · '}
        nightly safety-net every <span className="font-mono text-gray-600">{nightlySec ?? '?'}s</span>.
      </div>
    </div>
  );
}

export default function AdminHealth({ adminToken, onNavigate }) {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [metricsData, setMetricsData] = useState(null);
  const [metricsLoading, setMetricsLoading] = useState(true);
  const [timeRange, setTimeRange] = useState(60);
  const [llmData, setLlmData] = useState(null);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmDays, setLlmDays] = useState(7);
  const [healthTab, setHealthTab] = useState('infra');
  const [prerender, setPrerender] = useState(null);
  const [prerenderLoading, setPrerenderLoading] = useState(false);
  const [prerenderTriggering, setPrerenderTriggering] = useState(false);

  // Task #422 — Assamese purity admin override controls.
  const [asmCfg, setAsmCfg] = useState(null);
  const [asmLoading, setAsmLoading] = useState(false);
  const [asmSaving, setAsmSaving] = useState(false);
  const [asmTesting, setAsmTesting] = useState(false);
  const [asmDraft, setAsmDraft] = useState({ behaviour: '', threshold: '' });
  const [asmTestResult, setAsmTestResult] = useState(null);
  const [asmTestSample, setAsmTestSample] = useState('');

  const loadAsmCfg = useCallback(() => {
    setAsmLoading(true);
    axios.get(`${API_BASE}/admin/assamese-purity`, {
      headers: adminHeaders(adminToken), withCredentials: true,
    })
      .then((r) => {
        setAsmCfg(r.data);
        const cfg = r.data?.config || {};
        setAsmDraft({
          behaviour: cfg.behaviour || '',
          threshold: cfg.threshold != null ? String(cfg.threshold) : '',
        });
        setAsmTestSample(r.data?.test_sample || '');
      })
      .catch((e) => {
        const msg = e?.response?.data?.detail || 'Failed to load purity config';
        toast.error(msg);
      })
      .finally(() => setAsmLoading(false));
  }, [adminToken]);

  const saveAsmOverride = useCallback(async () => {
    const body = {};
    const cfgNow = asmCfg?.config || {};
    if (asmDraft.behaviour && asmDraft.behaviour !== cfgNow.behaviour) {
      body.behaviour = asmDraft.behaviour;
    }
    const t = asmDraft.threshold === '' ? null : Number(asmDraft.threshold);
    if (t != null && Number.isFinite(t) && t !== cfgNow.threshold) {
      body.threshold = t;
    }
    if (!Object.keys(body).length) {
      toast.info('No changes to save');
      return;
    }
    setAsmSaving(true);
    try {
      await axios.patch(`${API_BASE}/admin/assamese-purity`, body, {
        headers: adminHeaders(adminToken), withCredentials: true,
      });
      toast.success('Override saved — applied immediately');
      loadAsmCfg();
    } catch (e) {
      const msg = e?.response?.data?.detail || 'Failed to save override';
      toast.error(msg);
    } finally {
      setAsmSaving(false);
    }
  }, [adminToken, asmDraft, asmCfg, loadAsmCfg]);

  const clearAsmOverride = useCallback(async () => {
    setAsmSaving(true);
    try {
      await axios.delete(`${API_BASE}/admin/assamese-purity`, {
        headers: adminHeaders(adminToken), withCredentials: true,
      });
      toast.success('Override cleared — env vars now in effect');
      setAsmTestResult(null);
      loadAsmCfg();
    } catch (e) {
      const msg = e?.response?.data?.detail || 'Failed to clear override';
      toast.error(msg);
    } finally {
      setAsmSaving(false);
    }
  }, [adminToken, loadAsmCfg]);

  const fireAsmTest = useCallback(async () => {
    setAsmTesting(true);
    setAsmTestResult(null);
    try {
      const r = await axios.post(
        `${API_BASE}/admin/assamese-purity/test`,
        asmTestSample ? { sample: asmTestSample } : {},
        { headers: adminHeaders(adminToken), withCredentials: true },
      );
      setAsmTestResult(r.data);
    } catch (e) {
      const msg = e?.response?.data?.detail || 'Test fire failed';
      toast.error(msg);
    } finally {
      setAsmTesting(false);
    }
  }, [adminToken, asmTestSample]);

  const loadPrerender = useCallback(() => {
    setPrerenderLoading(true);
    axios.get(`${API_BASE}/admin/prerender/status`, {
      headers: adminHeaders(adminToken),
      withCredentials: true,
    })
      .then((r) => setPrerender(r.data))
      .catch((e) => setPrerender({ _error: e?.response?.data?.detail || 'Failed to load prerender status' }))
      .finally(() => setPrerenderLoading(false));
  }, [adminToken]);

  const triggerPrerender = useCallback(() => {
    setPrerenderTriggering(true);
    axios.post(`${API_BASE}/admin/prerender/refresh?immediate=true`, null, {
      headers: adminHeaders(adminToken),
      withCredentials: true,
    })
      .then((r) => {
        setPrerender(r.data?.status || null);
        toast.success(r.data?.queued ? 'Cloudflare Pages rebuild queued' : 'Refresh requested (not queued)');
      })
      .catch((e) => {
        const msg = e?.response?.data?.detail || 'Failed to trigger refresh';
        toast.error(msg);
      })
      .finally(() => {
        setPrerenderTriggering(false);
        setTimeout(loadPrerender, 800);
      });
  }, [adminToken, loadPrerender]);

  useEffect(() => { if (healthTab === 'prerender') loadPrerender(); }, [healthTab, loadPrerender]);
  useEffect(() => { if (healthTab === 'asm') loadAsmCfg(); }, [healthTab, loadAsmCfg]);

  const healthUrl = `${import.meta.env.VITE_BACKEND_URL || ''}/health`;

  const loadHealth = () => {
    setLoading(true);
    axios.get(`${API_BASE.replace('/api','')}/api/health`)
      .then((r) => setHealth(r.data))
      .catch(() => setHealth({ status: 'error', dependencies: {} }))
      .finally(() => setLoading(false));
  };

  const loadMetrics = useCallback(() => {
    setMetricsLoading(true);
    axios.get(`${API_BASE}/metrics/history?minutes=${timeRange}`, {
      headers: adminHeaders(adminToken),
      withCredentials: true,
    })
      .then((r) => setMetricsData(r.data))
      .catch(() => setMetricsData(null))
      .finally(() => setMetricsLoading(false));
  }, [adminToken, timeRange]);

  const loadLlmCosts = useCallback(async () => {
    setLlmLoading(true);
    try {
      const r = await llmCosts(adminToken, llmDays);
      setLlmData(r.data);
    } catch {} finally { setLlmLoading(false); }
  }, [adminToken, llmDays]);

  useEffect(() => { loadHealth(); }, []);
  useEffect(() => { loadMetrics(); }, [loadMetrics]);
  useEffect(() => { if (healthTab === 'llm') loadLlmCosts(); }, [healthTab, loadLlmCosts]);

  useEffect(() => {
    const interval = setInterval(loadMetrics, 60000);
    return () => clearInterval(interval);
  }, [loadMetrics]);

  const handleCopy = () => {
    navigator.clipboard.writeText(healthUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const deps = health?.dependencies || {};
  const allOk = Object.values(deps).every((d) => d.status === 'ok' || d.status === 'not_configured' || d.status === 'unavailable');
  const hasError = Object.values(deps).some((d) => d.status === 'error' || d.status === 'not_configured');

  const chartData = (metricsData?.history || []).map((s) => ({
    ...s,
    time: s.t ? new Date(s.t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '',
  }));

  const peaks = metricsData?.peaks || {};
  const current = metricsData?.current || {};

  return (
    <div className="space-y-5 max-w-4xl">
      <div className="flex gap-1 p-1 rounded-xl w-fit bg-gray-100">
        {[
          { id: 'infra',     label: 'Infrastructure' },
          { id: 'llm',       label: 'LLM Cost Tracker' },
          { id: 'prerender', label: 'Prerender Refresh' },
          { id: 'asm',       label: 'Sarvam Purity' },
        ].map(t => (
          <button key={t.id} onClick={() => setHealthTab(t.id)}
            className={`px-4 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              healthTab === t.id
                ? 'bg-violet-600 text-white shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {healthTab === 'llm' && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 mb-2">
            {[7, 14, 30].map(d => (
              <button key={d} onClick={() => { setLlmDays(d); setLlmLoading(true); llmCosts(adminToken, d).then(r => setLlmData(r.data)).catch(() => {}).finally(() => setLlmLoading(false)); }}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all border ${
                  llmDays === d ? 'bg-violet-50 border-violet-200 text-violet-600' : 'border-gray-200 text-gray-400 hover:text-gray-600'
                }`}>
                {d}d
              </button>
            ))}
            <button onClick={loadLlmCosts} disabled={llmLoading}
              className="ml-2 px-3 py-1.5 rounded-lg text-xs border border-gray-200 text-gray-400 hover:text-gray-600">
              {llmLoading ? 'Loading…' : '↻ Refresh'}
            </button>
          </div>
          {llmLoading ? (
            <div className="flex justify-center p-10"><RefreshCw size={20} className="animate-spin text-gray-300" /></div>
          ) : llmData ? (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: `Total Cost (${llmDays}d)`, value: `$${llmData.total_cost_usd || '0.000000'}`, color: 'amber' },
                  { label: 'Total Cost (INR)', value: `₹${llmData.total_cost_inr || '0.0000'}`, color: 'emerald' },
                  { label: 'Total Tokens', value: (llmData.total_tokens || 0).toLocaleString(), color: 'violet' },
                  { label: 'Cost/Page', value: `$${llmData.cost_per_published_page_usd || '0.000000'}`, color: 'blue' },
                ].map(s => <PeakBadge key={s.label} label={s.label} value={s.value} color={s.color} />)}
              </div>

              {(llmData.by_model?.length > 0) && (
                <div className="rounded-xl p-5 bg-white border border-gray-200 shadow-sm">
                  <h3 className="text-sm font-semibold text-gray-900 mb-4">Cost by Model</h3>
                  <div className="space-y-3">
                    {llmData.by_model.map(m => {
                      const pct = llmData.total_cost_usd > 0 ? Math.round(m.cost_usd / llmData.total_cost_usd * 100) : 0;
                      return (
                        <div key={m.model}>
                          <div className="flex justify-between mb-1">
                            <span className="text-xs text-gray-600 font-mono">{m.model}</span>
                            <span className="text-xs text-violet-600">${m.cost_usd} ({m.calls} calls)</span>
                          </div>
                          <div className="h-1 rounded-full overflow-hidden bg-gray-100">
                            <div style={{ width: `${pct}%`, height: '100%', background: 'linear-gradient(90deg,#7c3aed,#a78bfa)', borderRadius: 2 }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {(llmData.daily?.length > 0) && (
                <div className="rounded-xl p-5 bg-white border border-gray-200 shadow-sm">
                  <h3 className="text-sm font-semibold text-gray-900 mb-4">Daily LLM Spend</h3>
                  <ResponsiveContainer width="100%" height={160}>
                    <BarChart data={llmData.daily}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
                      <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 10 }} tickFormatter={d => d?.slice(5)} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} axisLine={false} tickLine={false} />
                      <Tooltip content={<CustomTooltip />} />
                      <Bar dataKey="cost_usd" name="Cost (USD)" fill="#7c3aed" radius={[3, 3, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {llmData.total_calls === 0 && (
                <div className="text-center py-12 text-gray-400">
                  <DollarSign size={32} className="mx-auto mb-3 opacity-30" />
                  <p className="text-sm">No LLM calls recorded yet — costs will appear here as content is generated</p>
                </div>
              )}
            </>
          ) : null}
        </div>
      )}

      {healthTab === 'prerender' && (
        <div className="space-y-4">
          <div className="rounded-2xl p-5 bg-white border border-gray-200 shadow-sm">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                  <RotateCw size={14} className="text-violet-500" />
                  Cloudflare Pages prerender refresh
                </h3>
                <p className="text-xs text-gray-500 mt-1">
                  Rebuilds the prerendered subject &amp; chapter HTML so admin edits go live for crawlers and first paint.
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={loadPrerender}
                  disabled={prerenderLoading}
                  className="px-3 py-1.5 rounded-lg text-xs border border-gray-200 text-gray-500 hover:text-gray-700 disabled:opacity-50"
                  data-testid="button-prerender-reload"
                >
                  <RefreshCw size={12} className={`inline mr-1 ${prerenderLoading ? 'animate-spin' : ''}`} />
                  Reload
                </button>
                <button
                  onClick={triggerPrerender}
                  disabled={prerenderTriggering}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
                  data-testid="button-prerender-refresh-now"
                >
                  <RotateCw size={12} className={`inline mr-1 ${prerenderTriggering ? 'animate-spin' : ''}`} />
                  {prerenderTriggering ? 'Queueing…' : 'Refresh now'}
                </button>
              </div>
            </div>

            {prerenderLoading && !prerender ? (
              <div className="flex justify-center p-8">
                <RefreshCw size={20} className="animate-spin text-gray-300" />
              </div>
            ) : prerender?._error ? (
              <div className="flex items-start gap-2 p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <span>{prerender._error}</span>
              </div>
            ) : prerender ? (
              <PrerenderStatusBody status={prerender} />
            ) : (
              <p className="text-xs text-gray-400">No status loaded.</p>
            )}
          </div>

          <p className="text-[11px] text-gray-400 leading-relaxed">
            Admin edits trigger debounced refreshes automatically. “Refresh now” bypasses the debounce/cooldown and fires the Cloudflare Pages deploy hook immediately.
          </p>
        </div>
      )}

      {healthTab === 'asm' && (
        <div className="space-y-4" data-testid="asm-purity-tab">
          <div className="rounded-2xl p-5 bg-white border border-gray-200 shadow-sm">
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                  <Zap size={16} className="text-violet-500" />
                  Assamese Purity Override
                </h3>
                <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                  Live behaviour and threshold for Sarvam Assamese leakage cleanup. Changes apply immediately and survive restarts (persisted in <code className="font-mono text-[11px] text-gray-600">db.api_config</code>).
                </p>
              </div>
              <button
                onClick={loadAsmCfg}
                disabled={asmLoading}
                className="p-2 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100"
                data-testid="button-refresh-asm"
                title="Refresh"
              >
                <RefreshCw size={14} className={asmLoading ? 'animate-spin' : ''} />
              </button>
            </div>

            {asmLoading && !asmCfg ? (
              <div className="flex justify-center py-10"><RefreshCw size={20} className="animate-spin text-gray-300" /></div>
            ) : asmCfg ? (
              <>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
                  <PeakBadge label="Active behaviour" value={asmCfg.config?.behaviour || '—'} color="violet" />
                  <PeakBadge label="Active threshold" value={asmCfg.config?.threshold != null ? Number(asmCfg.config.threshold).toFixed(3) : '—'} color="emerald" />
                  <PeakBadge label="Behaviour source" value={asmCfg.config?.behaviour_source || '—'} color={asmCfg.config?.behaviour_source === 'override' ? 'amber' : 'blue'} />
                  <PeakBadge label="Threshold source" value={asmCfg.config?.threshold_source || '—'} color={asmCfg.config?.threshold_source === 'override' ? 'amber' : 'blue'} />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Behaviour</label>
                    <select
                      value={asmDraft.behaviour}
                      onChange={(e) => setAsmDraft(d => ({ ...d, behaviour: e.target.value }))}
                      className="w-full text-sm font-mono px-3 py-2 rounded-lg border border-gray-200 focus:border-violet-300 focus:ring-1 focus:ring-violet-200 outline-none"
                      data-testid="select-asm-behaviour"
                    >
                      {(asmCfg.config?.valid_behaviours || []).map(b => (
                        <option key={b} value={b}>{b}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Threshold (0–1)</label>
                    <input
                      type="number"
                      min="0.001"
                      max="0.999"
                      step="0.005"
                      value={asmDraft.threshold}
                      onChange={(e) => setAsmDraft(d => ({ ...d, threshold: e.target.value }))}
                      className="w-full text-sm font-mono px-3 py-2 rounded-lg border border-gray-200 focus:border-violet-300 focus:ring-1 focus:ring-violet-200 outline-none"
                      data-testid="input-asm-threshold"
                    />
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={saveAsmOverride}
                    disabled={asmSaving}
                    className="px-4 py-2 rounded-lg bg-violet-600 text-white text-xs font-semibold shadow-sm hover:bg-violet-700 disabled:opacity-50"
                    data-testid="button-save-asm"
                  >
                    {asmSaving ? 'Saving…' : 'Save override'}
                  </button>
                  <button
                    onClick={clearAsmOverride}
                    disabled={asmSaving || !asmCfg.persisted}
                    className="px-4 py-2 rounded-lg border border-gray-200 text-gray-500 text-xs font-semibold hover:bg-gray-50 disabled:opacity-40"
                    data-testid="button-clear-asm"
                    title={asmCfg.persisted ? 'Drop the override and revert to env vars' : 'No override to clear'}
                  >
                    Clear override
                  </button>
                  {asmCfg.persisted?.updated_at && (
                    <span className="text-[11px] text-gray-400 ml-auto font-mono">
                      Last edit by {asmCfg.persisted.updated_by || 'admin'} · {new Date(asmCfg.persisted.updated_at).toLocaleString()}
                    </span>
                  )}
                </div>

                <p className="text-[11px] text-gray-400 leading-relaxed mt-4">
                  Defaults: behaviour <code className="font-mono">{asmCfg.config?.default_behaviour}</code> · threshold <code className="font-mono">{asmCfg.config?.default_threshold}</code>. <span className="text-amber-600">Override</span> beats env vars; env vars beat defaults. Source columns above tell you what's currently winning.
                </p>
              </>
            ) : null}
          </div>

          <div className="rounded-2xl p-5 bg-white border border-gray-200 shadow-sm">
            <h3 className="text-sm font-semibold text-gray-900 mb-1 flex items-center gap-2">
              <ShieldCheck size={16} className="text-emerald-500" />
              Test fire
            </h3>
            <p className="text-xs text-gray-500 mb-3 leading-relaxed">
              Sends the sample below through the LIVE sanitiser using the currently active behaviour. Use this to validate a new override before letting real users hit it.
            </p>
            {asmCfg?.config?.behaviour && (asmCfg.config.behaviour === 'regenerate' || asmCfg.config.behaviour === 'translate+regenerate') && (
              <div className="mb-3 px-3 py-2 rounded-lg bg-amber-50 border border-amber-200 text-[11px] text-amber-800 leading-relaxed" data-testid="asm-regenerate-warning">
                <strong>Heads up:</strong> the active behaviour includes <code className="font-mono">regenerate</code>, but the test-fire route does not have a real chat context, so the regenerate step will be skipped here (you'll see <code className="font-mono">regenerated: false</code> in the diagnostic). Translate / strip behaviour IS exercised. Use a real chat query in Assamese to fully validate regenerate end-to-end.
              </div>
            )}

            <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Sample (Assamese with English leakage)</label>
            <textarea
              value={asmTestSample}
              onChange={(e) => setAsmTestSample(e.target.value)}
              rows={3}
              className="w-full text-sm font-mono px-3 py-2 rounded-lg border border-gray-200 focus:border-violet-300 focus:ring-1 focus:ring-violet-200 outline-none mb-3"
              data-testid="input-asm-sample"
            />

            <button
              onClick={fireAsmTest}
              disabled={asmTesting || !asmTestSample.trim()}
              className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-xs font-semibold shadow-sm hover:bg-emerald-700 disabled:opacity-50"
              data-testid="button-fire-asm"
            >
              {asmTesting ? 'Running…' : 'Fire test'}
            </button>

            {asmTestResult && (
              <div className="mt-4 space-y-3" data-testid="asm-test-result">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="rounded-xl border border-gray-200 p-3 bg-gray-50">
                    <p className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-2">Raw input</p>
                    <p className="text-xs text-gray-800 font-mono whitespace-pre-wrap break-words">{asmTestResult.raw}</p>
                  </div>
                  <div className="rounded-xl border border-emerald-200 p-3 bg-emerald-50">
                    <p className="text-[10px] uppercase tracking-wider text-emerald-700 font-bold mb-2">Cleaned output</p>
                    <p className="text-xs text-gray-800 font-mono whitespace-pre-wrap break-words">{asmTestResult.cleaned}</p>
                  </div>
                </div>
                <div className="rounded-xl border border-gray-200 p-3 bg-white">
                  <p className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-2">Diagnostic</p>
                  <pre className="text-[11px] font-mono text-gray-700 overflow-x-auto">{JSON.stringify(asmTestResult.diag, null, 2)}</pre>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {healthTab === 'infra' && (<>
      <div className={`rounded-2xl p-4 flex items-center gap-3 ${
        loading ? 'bg-gray-50 border border-gray-200' : hasError ? 'bg-red-50 border border-red-200' : 'bg-emerald-50 border border-emerald-200'
      }`}>
        {loading ? <Wifi size={20} className="text-gray-400 animate-pulse" /> :
         hasError ? <AlertTriangle size={20} className="text-red-500" /> :
         <ShieldCheck size={20} className="text-emerald-500" />}
        <div className="flex-1">
          <p className={`text-sm font-semibold ${
            loading ? 'text-gray-500' : hasError ? 'text-red-600' : 'text-emerald-600'
          }`}>
            {loading ? 'Running health probes...' : hasError ? 'Degraded — Check Dependencies' : 'All Systems Operational'}
          </p>
          {health && (
            <p className="text-xs text-gray-400 mt-0.5">
              v{health.version || '1.0.0'} · {health.workers} workers · uptime {Math.floor((health.uptime_seconds || 0) / 60)}m
            </p>
          )}
        </div>
        <button onClick={() => { loadHealth(); loadMetrics(); }} className="p-2 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100" data-testid="button-refresh-health">
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <PeakBadge label="Active Now (5m)" value={current.active_5m ?? 0} color="emerald" />
        <PeakBadge label="Peak Users (5m)" value={peaks.active_users_5m ?? 0} color="violet" />
        <PeakBadge label="Current RPS" value={current.rps ?? 0} color="blue" />
        <PeakBadge label="Peak RPS" value={peaks.rps ?? 0} color="amber" />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <PeakBadge label="Active (15m)" value={current.active_15m ?? 0} color="emerald" />
        <PeakBadge label="Active (60m)" value={current.active_60m ?? 0} color="emerald" />
        <PeakBadge label="Total Requests" value={current.requests ?? 0} color="blue" />
        <PeakBadge label="AI Chats" value={current.chats ?? 0} color="violet" />
      </div>

      <div className="rounded-xl p-5 bg-white border border-gray-200 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Users size={16} className="text-violet-500" />
            <h3 className="text-sm font-semibold text-gray-900">Active Users Over Time</h3>
          </div>
          <div className="flex gap-1">
            {[
              { label: '1h', val: 60 },
              { label: '6h', val: 360 },
              { label: '24h', val: 1440 },
            ].map(({ label, val }) => (
              <button
                key={val}
                onClick={() => setTimeRange(val)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                  timeRange === val
                    ? 'bg-violet-50 text-violet-600 border border-violet-200'
                    : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50 border border-transparent'
                }`}
                data-testid={`button-range-${label}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        {metricsLoading ? (
          <div className="flex justify-center py-10">
            <RefreshCw size={20} className="animate-spin text-gray-300" />
          </div>
        ) : chartData.length < 2 ? (
          <div className="flex flex-col items-center justify-center py-10 text-gray-400">
            <Activity size={32} className="mb-2 opacity-40" />
            <p className="text-sm">Collecting data... Graph will appear after 2+ minutes.</p>
            <p className="text-xs mt-1 text-gray-300">Snapshots are taken every 60 seconds.</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="grad5m" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#7c3aed" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#7c3aed" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="grad15m" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.1} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="grad60m" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.1} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="time" tick={{ fill: '#9ca3af', fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ fontSize: 11, color: '#6b7280', paddingTop: 8 }}
                iconType="circle"
                iconSize={8}
              />
              <Area type="monotone" dataKey="active_5m" name="Active (5m)" stroke="#7c3aed" fill="url(#grad5m)" strokeWidth={2} dot={false} />
              <Area type="monotone" dataKey="active_15m" name="Active (15m)" stroke="#10b981" fill="url(#grad15m)" strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
              <Area type="monotone" dataKey="active_60m" name="Active (60m)" stroke="#3b82f6" fill="url(#grad60m)" strokeWidth={1.5} dot={false} strokeDasharray="6 3" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="rounded-xl p-5 bg-white border border-gray-200 shadow-sm">
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp size={16} className="text-blue-500" />
          <h3 className="text-sm font-semibold text-gray-900">Requests Per Second</h3>
        </div>
        {metricsLoading ? (
          <div className="flex justify-center py-10">
            <RefreshCw size={20} className="animate-spin text-gray-300" />
          </div>
        ) : chartData.length < 2 ? (
          <div className="flex flex-col items-center justify-center py-8 text-gray-400">
            <p className="text-sm">Waiting for data points...</p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="gradRps" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
              <XAxis dataKey="time" tick={{ fill: '#9ca3af', fontSize: 10 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip content={<CustomTooltip />} />
              <Area type="monotone" dataKey="rps" name="RPS" stroke="#f59e0b" fill="url(#gradRps)" strokeWidth={2} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="space-y-3">
        {(() => {
          const KNOWN_SERVICES = [
            { key: 'mongodb',  icon: Database, label: 'Syrabit DB (MongoDB)', desc: 'User data, sessions, content, rate limits' },
            { key: 'redis',    icon: Wifi,     label: 'Redis Cache (Upstash)', desc: 'Shared content cache & session store' },
            { key: 'llm',      icon: Zap,      label: 'AI Provider Pool',      desc: 'Multi-provider SLM pool — Groq, Cerebras, Sarvam, OpenRouter, Fireworks' },
            { key: 'supabase', icon: Database, label: 'Supabase',              desc: 'Auth, user profiles, persistent storage' },
          ];
          const knownKeys = new Set(KNOWN_SERVICES.map(s => s.key));
          const extraKeys = Object.keys(deps).filter(k => !knownKeys.has(k));
          const allServices = [
            ...KNOWN_SERVICES,
            ...extraKeys.map(k => ({ key: k, icon: Activity, label: k.charAt(0).toUpperCase() + k.slice(1), desc: '' })),
          ];
          return allServices.map(({ key, icon: Icon, label, desc }) => {
            const dep = deps[key] || {};
            const isOk = dep.status === 'ok';
            const isNotConfigured = dep.status === 'not_configured';
            const isError = dep.status === 'error';
            return (
              <div key={key} className={`rounded-xl p-4 flex items-center gap-3 bg-white border border-gray-200 shadow-sm`} data-testid={`dep-${key}`}>
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                  isOk ? 'bg-emerald-50' : isNotConfigured ? 'bg-gray-100' : isError ? 'bg-red-50' : 'bg-amber-50'
                }`}>
                  <Icon size={18} className={isOk ? 'text-emerald-500' : isNotConfigured ? 'text-gray-400' : isError ? 'text-red-500' : 'text-amber-500'} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900">{label}</p>
                  {desc && <p className="text-xs text-gray-400">{desc}</p>}
                  {dep.error && <p className="text-xs text-red-500 mt-0.5">{dep.error}</p>}
                </div>
                <div className="flex items-center gap-2">
                  <LatencyBadge ms={dep.latencyMs} />
                  <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                    isOk ? 'bg-emerald-50 text-emerald-600' :
                    isNotConfigured ? 'bg-gray-100 text-gray-500' :
                    isError ? 'bg-red-50 text-red-600' :
                    'bg-amber-50 text-amber-600 animate-pulse'
                  }`}>
                    {loading ? 'PROBING...' : dep.status?.toUpperCase().replace('_', ' ') || 'UNKNOWN'}
                  </span>
                </div>
              </div>
            );
          });
        })()}
      </div>

      <div className="rounded-xl p-4 bg-white border border-gray-200 shadow-sm">
        <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Health Endpoint URL</p>
        <div className="flex items-center gap-2">
          <code className="flex-1 text-xs font-mono text-gray-600 bg-gray-50 px-3 py-2 rounded-lg truncate border border-gray-200">{healthUrl}</code>
          <button onClick={handleCopy} className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 flex-shrink-0" data-testid="button-copy-url">
            {copied ? <Check size={14} className="text-emerald-500" /> : <Copy size={14} />}
          </button>
        </div>
      </div>

      <div className="rounded-xl p-4 bg-white border border-gray-200 shadow-sm">
        <p className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">UptimeRobot Setup</p>
        <ol className="space-y-2">
          {['Create free UptimeRobot account at uptimerobot.com','Add new HTTP(s) monitor','Paste the health URL above','Enable keyword monitoring: \'"status":"ok"\'','Configure alert contacts (email/Slack)','Save — you\'ll get 5-minute uptime checks'].map((s, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-gray-500">
              <span className="w-5 h-5 rounded-full bg-violet-50 flex items-center justify-center text-[10px] font-bold text-violet-600 flex-shrink-0 mt-0.5">{i+1}</span>{s}
            </li>
          ))}
        </ol>
      </div>
      </>)}
      <AdminQuickLinks links={['apiconfig','settings','dashboard','ratelimits']} onNavigate={onNavigate} />
    </div>
  );
}
