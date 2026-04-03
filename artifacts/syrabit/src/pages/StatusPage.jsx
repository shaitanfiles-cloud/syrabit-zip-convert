import { useState, useEffect, useCallback } from 'react';
import { PublicLayout } from '@/components/layout/PublicLayout';
import { API_BASE } from '@/utils/api';
import axios from 'axios';
import { CheckCircle2, XCircle, AlertTriangle, RefreshCw, Activity } from 'lucide-react';

const SERVICE_CHECKS = [
  { key: 'api', label: 'Backend API', description: 'Core backend services' },
  { key: 'postgresql', label: 'PostgreSQL', description: 'Primary data store' },
  { key: 'mongodb', label: 'RAG Index', description: 'Content & search database' },
  { key: 'redis', label: 'Redis Cache', description: 'Session & response cache' },
  { key: 'llm', label: 'LLM Pool', description: 'AI response generation' },
  { key: 'cdn', label: 'Frontend', description: 'Web application delivery' },
];

function StatusIcon({ status }) {
  if (status === 'operational') return <CheckCircle2 size={18} className="text-emerald-400" />;
  if (status === 'degraded') return <AlertTriangle size={18} className="text-amber-400" />;
  return <XCircle size={18} className="text-red-400" />;
}

function statusLabel(s) {
  if (s === 'operational') return 'Operational';
  if (s === 'degraded') return 'Degraded';
  return 'Down';
}

function statusColor(s) {
  if (s === 'operational') return 'text-emerald-400';
  if (s === 'degraded') return 'text-amber-400';
  return 'text-red-400';
}

export default function StatusPage() {
  const [services, setServices] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastChecked, setLastChecked] = useState(null);
  const [latency, setLatency] = useState(null);

  const checkStatus = useCallback(async () => {
    setLoading(true);
    const t0 = performance.now();
    try {
      const res = await axios.get(`${API_BASE}/health`);
      const ms = Math.round(performance.now() - t0);
      setLatency(ms);
      const data = res.data;
      const deps = data.dependencies || {};
      const mapStatus = (s) => {
        const v = (s || '').toLowerCase();
        if (v === 'ok' || v === 'configured') return 'operational';
        if (v === 'degraded') return 'degraded';
        if (v === 'not_connected' || v === 'not_configured') return 'degraded';
        if (v === 'unavailable' || v === 'error') return 'down';
        return 'down';
      };
      setServices({
        api: 'operational',
        postgresql: mapStatus(deps.postgresql?.status),
        mongodb: mapStatus(deps.mongodb?.status),
        redis: mapStatus(deps.redis?.status),
        llm: mapStatus(deps.llm?.status),
        cdn: 'operational',
      });
    } catch {
      setLatency(null);
      setServices({
        api: 'down',
        postgresql: 'down',
        mongodb: 'down',
        redis: 'down',
        llm: 'down',
        cdn: 'operational',
      });
    }
    setLastChecked(new Date());
    setLoading(false);
  }, []);

  useEffect(() => { checkStatus(); }, [checkStatus]);

  const allOperational = services && Object.values(services).every(s => s === 'operational');
  const anyDown = services && Object.values(services).some(s => s === 'down');

  return (
    <PublicLayout>
      <div className="min-h-screen bg-[#06060e] pt-8 pb-24 px-4">
        <div className="max-w-2xl mx-auto">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-2xl font-semibold text-white flex items-center gap-2">
                <Activity size={22} className="text-primary" />
                System Status
              </h1>
              <p className="text-white/40 text-sm mt-1">
                Real-time health of Syrabit.ai services
              </p>
            </div>
            <button
              onClick={checkStatus}
              disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-white/60 hover:text-white hover:bg-white/5 transition-colors disabled:opacity-40"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>

          <div className="rounded-xl border border-white/10 overflow-hidden mb-6" style={{ background: 'rgba(255,255,255,0.02)' }}>
            <div className="px-5 py-4 border-b border-white/10 flex items-center justify-between">
              <div className="flex items-center gap-2">
                {services && (
                  <div className={`w-2.5 h-2.5 rounded-full ${allOperational ? 'bg-emerald-400' : anyDown ? 'bg-red-400' : 'bg-amber-400'}`}
                    style={{ boxShadow: `0 0 8px ${allOperational ? '#34d399' : anyDown ? '#f87171' : '#fbbf24'}` }} />
                )}
                <span className="text-white font-medium">
                  {!services ? 'Checking…' : allOperational ? 'All Systems Operational' : anyDown ? 'Service Disruption Detected' : 'Partial Degradation'}
                </span>
              </div>
              {latency !== null && (
                <span className="text-white/30 text-xs">
                  {latency}ms response
                </span>
              )}
            </div>

            <div className="divide-y divide-white/5">
              {SERVICE_CHECKS.map(({ key, label, description }) => {
                const s = services?.[key];
                return (
                  <div key={key} className="px-5 py-3.5 flex items-center justify-between">
                    <div>
                      <p className="text-white/90 text-sm font-medium">{label}</p>
                      <p className="text-white/30 text-xs">{description}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {s ? (
                        <>
                          <span className={`text-xs font-medium ${statusColor(s)}`}>{statusLabel(s)}</span>
                          <StatusIcon status={s} />
                        </>
                      ) : (
                        <span className="text-white/20 text-xs">Checking…</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {lastChecked && (
            <p className="text-white/25 text-xs text-center">
              Last checked: {lastChecked.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </p>
          )}
        </div>
      </div>
    </PublicLayout>
  );
}
