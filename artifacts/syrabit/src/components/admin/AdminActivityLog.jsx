import { useState, useEffect, useCallback } from 'react';
import { Activity, Trash2, RefreshCw, Download, Search, Info, AlertTriangle, AlertOctagon } from 'lucide-react';
import AdminQuickLinks from './AdminQuickLinks';
import { toast } from 'sonner';
import { adminGetActivityLog } from '@/utils/api';
import axios from 'axios';

const API_BASE = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

const adminHeaders = (token) => {
  const isRealJwt = token && typeof token === 'string' && token.split('.').length === 3;
  return isRealJwt ? { Authorization: `Bearer ${token}` } : {};
};

const LEVEL_CONFIG = {
  info:    { icon: Info,         color: 'text-blue-400',    dot: 'bg-blue-400',    border: 'border-blue-500/15'   },
  warning: { icon: AlertTriangle,color: 'text-amber-400',  dot: 'bg-amber-400',   border: 'border-amber-500/15'  },
  danger:  { icon: AlertOctagon, color: 'text-red-400',     dot: 'bg-red-400',     border: 'border-red-500/15'    },
};

function groupByDate(logs) {
  const groups = {};
  logs.forEach((log) => {
    const rawDate = log.created_at || log.timestamp || log.date;
    const date = rawDate
      ? new Date(rawDate).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
      : 'Unknown';
    if (!groups[date]) groups[date] = [];
    groups[date].push(log);
  });
  return groups;
}

export default function AdminActivityLog({ adminToken, onNavigate }) {
  const [logs, setLogs]     = useState([]);
  const [search, setSearch] = useState('');
  const [level, setLevel]   = useState('all');
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    adminGetActivityLog(adminToken)
      .then((r) => {
        const data = r.data;
        const logsArray = Array.isArray(data) ? data : (data?.logs || []);
        setLogs(logsArray);
      })
      .catch(() => {
        setError('Failed to load activity log');
        setLogs([]);
      })
      .finally(() => setLoading(false));
  }, [adminToken]);

  useEffect(() => { load(); }, [load]);

  const handleClear = async () => {
    if (!confirm('Clear activity log?')) return;
    try {
      await axios.delete(`${API_BASE}/admin/activity-log`, {
        headers: adminHeaders(adminToken),
        withCredentials: true,
      });
      setLogs([]);
      toast.success('Activity log cleared');
    } catch { toast.error('Failed to clear log'); }
  };

  const handleExport = () => {
    if (!logs.length) { toast.error('No logs to export'); return; }
    const csv = [
      'Timestamp,Action,Details,Admin,Level',
      ...logs.map((l) => `"${l.created_at || l.timestamp || ''}","${l.action || ''}","${l.details || ''}","${l.admin_name || ''}","${l.level || 'info'}"`)
    ];
    const blob = new Blob([csv.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'activity_log.csv'; a.click();
    URL.revokeObjectURL(url);
  };

  const filtered = logs.filter((l) => {
    const matchSearch = !search ||
      l.action?.toLowerCase().includes(search.toLowerCase()) ||
      l.details?.toLowerCase().includes(search.toLowerCase()) ||
      l.admin_name?.toLowerCase().includes(search.toLowerCase());
    const matchLevel = level === 'all' || l.level === level;
    return matchSearch && matchLevel;
  });

  const groups = groupByDate(filtered);

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-white">Activity Log</h2>
          <p className="text-sm text-white/40 mt-0.5">Admin action audit trail · {logs.length} entries</p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="p-2 rounded-xl text-white/40 hover:text-white/70 hover:bg-white/5 border border-white/8">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
          <button onClick={handleExport} disabled={!logs.length} className="p-2 rounded-xl text-white/40 hover:text-white/70 hover:bg-white/5 border border-white/8 disabled:opacity-30">
            <Download size={14} />
          </button>
          <button onClick={handleClear} disabled={!logs.length} className="p-2 rounded-xl text-red-400/50 hover:text-red-400 hover:bg-red-500/10 border border-red-500/15 disabled:opacity-30">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-sm text-red-400">{error}</div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search actions..."
            className="w-full h-9 pl-8 pr-3 rounded-xl text-sm text-white outline-none"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
          />
        </div>
        {['all','info','warning','danger'].map((l) => (
          <button
            key={l}
            onClick={() => setLevel(l)}
            className={`px-3 py-1.5 rounded-xl text-xs font-medium transition-all border ${
              level === l ? 'bg-white/8 border-white/15 text-white' : 'border-white/6 text-white/40 hover:text-white/60'
            }`}
          >
            {l.charAt(0).toUpperCase() + l.slice(1)}
          </button>
        ))}
        <span className="text-xs text-white/30">{filtered.length}</span>
      </div>

      {/* Log entries */}
      {loading ? (
        <div className="text-center py-16 text-white/20">
          <RefreshCw size={24} className="mx-auto mb-3 animate-spin opacity-40" />
          <p className="text-sm">Loading logs...</p>
        </div>
      ) : Object.keys(groups).length === 0 ? (
        <div className="text-center py-16 text-white/20">
          <Activity size={32} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">No admin actions recorded yet</p>
          <p className="text-xs mt-1 opacity-60">Actions will appear here as admins use the panel</p>
        </div>
      ) : (
        Object.entries(groups).map(([date, entries]) => (
          <div key={date}>
            <div className="flex items-center gap-3 my-3">
              <div className="flex-1 h-px bg-white/6" />
              <span className="text-xs text-white/30 px-2">{date}</span>
              <div className="flex-1 h-px bg-white/6" />
            </div>
            {entries.map((log, idx) => {
              const lc = LEVEL_CONFIG[log.level] || LEVEL_CONFIG.info;
              const Icon = lc.icon;
              const rawDate = log.created_at || log.timestamp;
              return (
                <div
                  key={log.id || idx}
                  className={`flex items-start gap-3 p-3 rounded-xl mb-1.5 border ${lc.border}`}
                  style={{ background: 'rgba(255,255,255,0.02)' }}
                >
                  <div className={`w-1.5 h-1.5 rounded-full ${lc.dot} mt-1.5 flex-shrink-0`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm text-white font-medium">{log.action || 'Action'}</span>
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-white/5 ${lc.color}`}>{log.level || 'info'}</span>
                      <span className="text-xs text-white/30 ml-auto">by {log.admin_name || 'Admin'}</span>
                    </div>
                    {log.details && (
                      <p className="text-xs text-white/40 mt-0.5 truncate">
                        {typeof log.details === 'string' ? log.details : JSON.stringify(log.details)}
                      </p>
                    )}
                  </div>
                  {rawDate && (
                    <span className="text-[10px] text-white/25 font-mono flex-shrink-0">
                      {new Date(rawDate).toLocaleTimeString('en-US', { hour12: false })}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        ))
      )}
      <AdminQuickLinks links={['users','conversations','dashboard','ratelimits']} onNavigate={onNavigate} />
    </div>
  );
}
