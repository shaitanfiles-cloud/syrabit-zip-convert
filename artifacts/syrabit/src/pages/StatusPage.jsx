import { useState, useEffect, useCallback } from 'react';
import { PublicLayout } from '@/components/layout/PublicLayout';
import PageMeta from '@/components/seo/PageMeta';
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
  if (status === 'operational') return <CheckCircle2 size={18} className="text-emerald-500" />;
  if (status === 'degraded') return <AlertTriangle size={18} className="text-amber-500" />;
  return <XCircle size={18} className="text-red-500" />;
}

function statusLabel(s) {
  if (s === 'operational') return 'Operational';
  if (s === 'degraded') return 'Degraded';
  return 'Down';
}

function statusColor(s) {
  if (s === 'operational') return 'text-emerald-500';
  if (s === 'degraded') return 'text-amber-500';
  return 'text-red-500';
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
      <PageMeta
        title="System Status"
        description="Real-time health status of Syrabit.ai services — API, database, AI models, and frontend delivery. Check uptime and service availability."
        url="https://syrabit.ai/status"
      />
      <div className="min-h-screen pt-8 pb-24 px-4">
        <div className="max-w-2xl mx-auto">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-2xl font-semibold text-foreground flex items-center gap-2">
                <Activity size={22} className="text-primary" />
                System Status
              </h1>
              <p className="text-muted-foreground text-sm mt-1">
                Real-time health of Syrabit.ai services
              </p>
            </div>
            <button
              onClick={checkStatus}
              disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>

          <div className="rounded-xl border border-border/30 overflow-hidden mb-6 glass-card">
            <div className="px-5 py-4 border-b border-border/20 flex items-center justify-between">
              <div className="flex items-center gap-2">
                {services && (
                  <div className={`w-2.5 h-2.5 rounded-full ${allOperational ? 'bg-emerald-500' : anyDown ? 'bg-red-500' : 'bg-amber-500'}`}
                    style={{ boxShadow: `0 0 8px ${allOperational ? '#10b981' : anyDown ? '#ef4444' : '#f59e0b'}` }} />
                )}
                <span className="text-foreground font-medium">
                  {!services ? 'Checking…' : allOperational ? 'All Systems Operational' : anyDown ? 'Service Disruption Detected' : 'Partial Degradation'}
                </span>
              </div>
              {latency !== null && (
                <span className="text-muted-foreground/50 text-xs">
                  {latency}ms response
                </span>
              )}
            </div>

            <div className="divide-y divide-border/15">
              {SERVICE_CHECKS.map(({ key, label, description }) => {
                const s = services?.[key];
                return (
                  <div key={key} className="px-5 py-3.5 flex items-center justify-between">
                    <div>
                      <p className="text-foreground text-sm font-medium">{label}</p>
                      <p className="text-muted-foreground/50 text-xs">{description}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {s ? (
                        <>
                          <span className={`text-xs font-medium ${statusColor(s)}`}>{statusLabel(s)}</span>
                          <StatusIcon status={s} />
                        </>
                      ) : (
                        <span className="text-muted-foreground/40 text-xs">Checking…</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {lastChecked && (
            <p className="text-muted-foreground/40 text-xs text-center">
              Last checked: {lastChecked.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </p>
          )}
        </div>
      </div>
    </PublicLayout>
  );
}
