import { useState, useEffect, useCallback } from 'react';
import {
  Shield, Bot, AlertTriangle, RefreshCw, Loader2,
  Hash, Globe, Clock, TrendingUp, Eye, Ban, Unlock,
} from 'lucide-react';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts';
import { adminGetSpoofedBots, adminGetBlockedIps, adminBlockIp, adminUnblockIp } from '@/utils/api';

function GlassCard({ children, className = '' }) {
  return (
    <div className={`relative rounded-2xl overflow-hidden bg-white border border-gray-200 shadow-sm ${className}`}>
      <div className="relative">{children}</div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, color, pulse }) {
  return (
    <div className="relative rounded-2xl p-5 overflow-hidden bg-white border border-gray-200 shadow-sm">
      {pulse && (
        <span className="absolute top-3 right-3 flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: color }} />
          <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: color }} />
        </span>
      )}
      <div className="flex items-center justify-between mb-3">
        <p className="text-gray-500 text-xs font-medium tracking-wide uppercase">{label}</p>
        <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: `${color}15` }}>
          <Icon size={16} style={{ color }} />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 tracking-tight">
        {typeof value === 'number' ? value.toLocaleString() : (value ?? '—')}
      </p>
    </div>
  );
}

const PERIOD_OPTIONS = [
  { label: '7 days', value: 7 },
  { label: '14 days', value: 14 },
  { label: '30 days', value: 30 },
  { label: '90 days', value: 90 },
];

export default function AdminBotSecurity({ adminToken }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(7);
  const [blockedIps, setBlockedIps] = useState([]);
  const [actionLoading, setActionLoading] = useState({});

  const blockedSet = new Set(blockedIps.map((b) => b.ip_hash));

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [spoofRes, blockedRes] = await Promise.all([
        adminGetSpoofedBots(adminToken, days),
        adminGetBlockedIps(adminToken),
      ]);
      setData(spoofRes.data);
      setBlockedIps(blockedRes.data?.blocked_ips || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load spoofed bot data');
    } finally {
      setLoading(false);
    }
  }, [adminToken, days]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleBlock = async (ipHash) => {
    setActionLoading((prev) => ({ ...prev, [ipHash]: 'blocking' }));
    try {
      await adminBlockIp(adminToken, ipHash);
      setBlockedIps((prev) => [...prev, { ip_hash: ipHash, blocked_at: new Date().toISOString(), reason: 'repeat_spoof_offender' }]);
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to block IP');
    } finally {
      setActionLoading((prev) => ({ ...prev, [ipHash]: null }));
    }
  };

  const handleUnblock = async (ipHash) => {
    setActionLoading((prev) => ({ ...prev, [ipHash]: 'unblocking' }));
    try {
      await adminUnblockIp(adminToken, ipHash);
      setBlockedIps((prev) => prev.filter((b) => b.ip_hash !== ipHash));
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to unblock IP');
    } finally {
      setActionLoading((prev) => ({ ...prev, [ipHash]: null }));
    }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-40 gap-3">
        <Loader2 className="w-5 h-5 animate-spin text-violet-500" />
        <span className="text-sm text-gray-400">Loading bot security data...</span>
      </div>
    );
  }

  if (error && !data) {
    return (
      <GlassCard className="p-6">
        <div className="flex items-center gap-3 text-red-500">
          <AlertTriangle size={18} />
          <p className="text-sm">{error}</p>
        </div>
        <button
          onClick={fetchData}
          className="mt-3 text-sm text-violet-600 hover:text-violet-800 flex items-center gap-1.5"
        >
          <RefreshCw size={13} /> Retry
        </button>
      </GlassCard>
    );
  }

  const realtime = data?.realtime || {};
  const dailyCounts = data?.daily_counts || [];
  const topBots = data?.by_claimed_bot || [];
  const offenders = data?.repeat_offender_ips || [];
  const recent = data?.recent_attempts || [];

  const rpmColor = (realtime.spoof_rpm || 0) > 10 ? '#ef4444' : (realtime.spoof_rpm || 0) > 3 ? '#f59e0b' : '#10b981';

  return (
    <div className="space-y-6 max-w-7xl">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-red-50">
            <Shield size={20} className="text-red-500" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-gray-900">Bot Security</h2>
            <p className="text-xs text-gray-400">Spoofed bot detection & monitoring</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="text-xs border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-violet-200"
          >
            {PERIOD_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-violet-50 text-violet-600 hover:bg-violet-100 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard
          label="Spoof RPM"
          value={realtime.spoof_rpm ?? 0}
          icon={TrendingUp}
          color={rpmColor}
          pulse={(realtime.spoof_rpm || 0) > 0}
        />
        <StatCard
          label="Session Total"
          value={realtime.session_total ?? 0}
          icon={Shield}
          color="#8b5cf6"
        />
        <StatCard
          label={`Period Total (${days}d)`}
          value={data?.period_total ?? 0}
          icon={AlertTriangle}
          color="#f59e0b"
        />
        <StatCard
          label="Repeat Offenders"
          value={offenders.length}
          icon={Hash}
          color="#ef4444"
        />
        <StatCard
          label="Blocked IPs"
          value={blockedIps.length}
          icon={Ban}
          color="#dc2626"
        />
      </div>

      <GlassCard>
        <div className="p-5 pb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <TrendingUp size={14} className="text-violet-500" />
            Daily Spoof Attempts
          </h3>
          <span className="text-[10px] text-gray-400 uppercase tracking-wider">Last {days} days</span>
        </div>
        <div className="px-3 pb-4" style={{ height: 260 }}>
          {dailyCounts.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={dailyCounts}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: '#94a3b8' }}
                  tickFormatter={(v) => {
                    const d = new Date(v);
                    return `${d.getMonth() + 1}/${d.getDate()}`;
                  }}
                />
                <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }}
                  labelFormatter={(v) => new Date(v).toLocaleDateString()}
                />
                <Line
                  type="monotone"
                  dataKey="count"
                  stroke="#8b5cf6"
                  strokeWidth={2}
                  dot={{ r: 3, fill: '#8b5cf6' }}
                  activeDot={{ r: 5, fill: '#7c3aed' }}
                  name="Attempts"
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-full text-sm text-gray-400">
              No data for this period
            </div>
          )}
        </div>
      </GlassCard>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <GlassCard>
          <div className="p-5 pb-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Bot size={14} className="text-violet-500" />
              Top Claimed Bots
            </h3>
          </div>
          {topBots.length > 0 ? (
            <>
              <div className="px-3 pb-2" style={{ height: 220 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={topBots.slice(0, 10)} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 10, fill: '#94a3b8' }} allowDecimals={false} />
                    <YAxis
                      type="category"
                      dataKey="bot"
                      tick={{ fontSize: 10, fill: '#64748b' }}
                      width={120}
                    />
                    <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' }} />
                    <Bar dataKey="count" fill="#8b5cf6" radius={[0, 4, 4, 0]} name="Attempts" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="border-t border-gray-100 max-h-48 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-400 uppercase tracking-wider">
                      <th className="text-left px-5 py-2 font-medium">Bot Name</th>
                      <th className="text-right px-5 py-2 font-medium">Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {topBots.map((b, i) => (
                      <tr key={i} className="border-t border-gray-50 hover:bg-gray-50">
                        <td className="px-5 py-2 text-gray-700 font-medium">{b.bot}</td>
                        <td className="px-5 py-2 text-right text-gray-500">{b.count.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="px-5 pb-5 text-sm text-gray-400">No spoofed bots detected</div>
          )}
        </GlassCard>

        <GlassCard>
          <div className="p-5 pb-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Hash size={14} className="text-red-500" />
              Repeat Offender IPs
            </h3>
            <p className="text-[10px] text-gray-400 mt-0.5">IPs with 5+ spoofing attempts</p>
          </div>
          {offenders.length > 0 ? (
            <div className="border-t border-gray-100 max-h-[380px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-400 uppercase tracking-wider">
                    <th className="text-left px-5 py-2 font-medium">IP Hash</th>
                    <th className="text-right px-5 py-2 font-medium">Attempts</th>
                    <th className="text-left px-5 py-2 font-medium">Claimed Bots</th>
                    <th className="text-center px-5 py-2 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {offenders.map((o, i) => {
                    const isBlocked = blockedSet.has(o.ip_hash);
                    const busy = actionLoading[o.ip_hash];
                    return (
                      <tr key={i} className="border-t border-gray-50 hover:bg-gray-50">
                        <td className="px-5 py-2 text-gray-600 font-mono text-[11px]">
                          {o.ip_hash ? `${o.ip_hash.slice(0, 12)}...` : '—'}
                        </td>
                        <td className="px-5 py-2 text-right">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                            o.attempts >= 50 ? 'bg-red-100 text-red-700' :
                            o.attempts >= 20 ? 'bg-amber-100 text-amber-700' :
                            'bg-gray-100 text-gray-600'
                          }`}>
                            {o.attempts ?? 0}
                          </span>
                        </td>
                        <td className="px-5 py-2">
                          <div className="flex flex-wrap gap-1">
                            {(o.claimed_bots || []).slice(0, 3).map((bot, j) => (
                              <span key={j} className="inline-flex items-center px-1.5 py-0.5 rounded bg-violet-50 text-violet-600 text-[10px]">
                                {bot}
                              </span>
                            ))}
                            {(o.claimed_bots || []).length > 3 && (
                              <span className="text-[10px] text-gray-400">+{o.claimed_bots.length - 3}</span>
                            )}
                          </div>
                        </td>
                        <td className="px-5 py-2 text-center">
                          {isBlocked ? (
                            <button
                              onClick={() => handleUnblock(o.ip_hash)}
                              disabled={!!busy}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-colors disabled:opacity-50"
                            >
                              {busy === 'unblocking' ? <Loader2 size={10} className="animate-spin" /> : <Unlock size={10} />}
                              Unblock
                            </button>
                          ) : (
                            <button
                              onClick={() => handleBlock(o.ip_hash)}
                              disabled={!!busy}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium bg-red-50 text-red-700 hover:bg-red-100 transition-colors disabled:opacity-50"
                            >
                              {busy === 'blocking' ? <Loader2 size={10} className="animate-spin" /> : <Ban size={10} />}
                              Block
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-5 pb-5 text-sm text-gray-400">No repeat offenders found</div>
          )}
        </GlassCard>
      </div>

      {blockedIps.length > 0 && (
        <GlassCard>
          <div className="p-5 pb-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Ban size={14} className="text-red-500" />
              Blocked IPs
            </h3>
            <p className="text-[10px] text-gray-400 mt-0.5">{blockedIps.length} IP{blockedIps.length !== 1 ? 's' : ''} currently blocked</p>
          </div>
          <div className="border-t border-gray-100 max-h-[300px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-400 uppercase tracking-wider">
                  <th className="text-left px-5 py-2 font-medium">IP Hash</th>
                  <th className="text-left px-5 py-2 font-medium">Reason</th>
                  <th className="text-left px-5 py-2 font-medium">Blocked At</th>
                  <th className="text-left px-5 py-2 font-medium">Blocked By</th>
                  <th className="text-center px-5 py-2 font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {blockedIps.map((b, i) => {
                  const busy = actionLoading[b.ip_hash];
                  return (
                    <tr key={i} className="border-t border-gray-50 hover:bg-gray-50">
                      <td className="px-5 py-2 text-gray-600 font-mono text-[11px]">
                        {b.ip_hash ? `${b.ip_hash.slice(0, 12)}...` : '—'}
                      </td>
                      <td className="px-5 py-2 text-gray-500">{b.reason || '—'}</td>
                      <td className="px-5 py-2 text-gray-500 whitespace-nowrap">
                        {b.blocked_at ? new Date(b.blocked_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-5 py-2 text-gray-500">{b.blocked_by || '—'}</td>
                      <td className="px-5 py-2 text-center">
                        <button
                          onClick={() => handleUnblock(b.ip_hash)}
                          disabled={!!busy}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-colors disabled:opacity-50"
                        >
                          {busy === 'unblocking' ? <Loader2 size={10} className="animate-spin" /> : <Unlock size={10} />}
                          Unblock
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </GlassCard>
      )}

      <GlassCard>
        <div className="p-5 pb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Clock size={14} className="text-violet-500" />
            Recent Spoof Attempts
          </h3>
          <span className="text-[10px] text-gray-400">Latest 50</span>
        </div>
        {recent.length > 0 ? (
          <div className="border-t border-gray-100 max-h-[420px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white">
                <tr className="text-gray-400 uppercase tracking-wider">
                  <th className="text-left px-5 py-2 font-medium">Time</th>
                  <th className="text-left px-5 py-2 font-medium">Claimed Bot</th>
                  <th className="text-left px-5 py-2 font-medium">IP Hash</th>
                  <th className="text-left px-5 py-2 font-medium">Path</th>
                  <th className="text-left px-5 py-2 font-medium">User Agent</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r, i) => (
                  <tr key={i} className="border-t border-gray-50 hover:bg-gray-50">
                    <td className="px-5 py-2 text-gray-500 whitespace-nowrap">
                      {r.timestamp ? new Date(r.timestamp).toLocaleString() : r.date || '—'}
                    </td>
                    <td className="px-5 py-2">
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-red-50 text-red-600 text-[10px] font-medium">
                        {r.claimed_bot || 'Unknown'}
                      </span>
                    </td>
                    <td className="px-5 py-2 text-gray-600 font-mono text-[11px]">
                      {r.ip_hash ? `${r.ip_hash.slice(0, 12)}...` : '—'}
                    </td>
                    <td className="px-5 py-2 text-gray-600 max-w-[200px] truncate" title={r.path}>
                      {r.path || '—'}
                    </td>
                    <td className="px-5 py-2 text-gray-400 max-w-[200px] truncate" title={r.user_agent}>
                      {r.user_agent || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-5 pb-5 text-sm text-gray-400">No recent attempts</div>
        )}
      </GlassCard>

      {realtime.session_by_bot && Object.keys(realtime.session_by_bot).length > 0 && (
        <GlassCard>
          <div className="p-5 pb-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Eye size={14} className="text-amber-500" />
              Real-time Session Breakdown
            </h3>
            <p className="text-[10px] text-gray-400 mt-0.5">Spoofed requests in current server session</p>
          </div>
          <div className="border-t border-gray-100">
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 p-5">
              {Object.entries(realtime.session_by_bot)
                .sort(([, a], [, b]) => b - a)
                .map(([bot, count]) => (
                  <div key={bot} className="rounded-xl border border-gray-100 p-3 bg-gray-50">
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider truncate">{bot}</p>
                    <p className="text-lg font-bold text-gray-900 mt-1">{count.toLocaleString()}</p>
                  </div>
                ))}
            </div>
          </div>
        </GlassCard>
      )}
    </div>
  );
}
