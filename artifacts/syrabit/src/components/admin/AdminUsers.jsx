import { useState, useEffect } from 'react';
import { Loader2, Search, Ban, CheckCircle, Crown, ChevronDown, AlertTriangle, RefreshCw, TrendingDown, Activity } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { adminGetUsers, adminUpdateUserStatus, adminUpdateUserPlan, churnRisk } from '@/utils/api';
import { toast } from 'sonner';

const PLAN_COLORS = {
  free: 'bg-slate-700 text-slate-300',
  starter: 'bg-violet-700/30 text-violet-300',
  pro: 'bg-amber-700/30 text-amber-300',
};

const STATUS_COLORS = {
  active: 'bg-emerald-700/30 text-emerald-300',
  suspended: 'bg-orange-700/30 text-orange-300',
  banned: 'bg-red-700/30 text-red-300',
};

const RISK_COLORS = {
  high:   { text: '#ef4444', bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.25)', label: '🔴 High' },
  medium: { text: '#f59e0b', bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.25)', label: '🟡 Medium' },
  low:    { text: '#10b981', bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.25)', label: '🟢 Low' },
};

function RiskBadge({ risk, score }) {
  const c = RISK_COLORS[risk] || RISK_COLORS.low;
  return (
    <span title={`Risk score: ${score}`} style={{ background: c.bg, border: `1px solid ${c.border}`, color: c.text, borderRadius: 20, padding: '2px 8px', fontSize: 11, fontWeight: 700 }}>
      {c.label}
    </span>
  );
}

export default function AdminUsers({ adminToken }) {
  const [users, setUsers]         = useState([]);
  const [loading, setLoading]     = useState(true);
  const [search, setSearch]       = useState('');
  const [tab, setTab]             = useState('all');
  const [riskData, setRiskData]   = useState(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [riskMap, setRiskMap]     = useState({});

  useEffect(() => {
    adminGetUsers(adminToken)
      .then((res) => setUsers(res.data))
      .catch(() => toast.error('Failed to load users'))
      .finally(() => setLoading(false));
  }, [adminToken]);

  const loadChurnRisk = async () => {
    setRiskLoading(true);
    try {
      const r = await churnRisk(adminToken);
      setRiskData(r.data);
      const map = {};
      (r.data.users || []).forEach(u => { map[u.id] = u; });
      setRiskMap(map);
      toast.success('Churn risk scores loaded');
    } catch {
      toast.error('Failed to load churn risk');
    } finally { setRiskLoading(false); }
  };

  const handleStatusChange = async (userId, newStatus) => {
    try {
      await adminUpdateUserStatus(adminToken, userId, newStatus);
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, status: newStatus } : u));
      toast.success('Status updated');
    } catch { toast.error('Failed to update status'); }
  };

  const handlePlanChange = async (userId, newPlan) => {
    try {
      await adminUpdateUserPlan(adminToken, userId, newPlan);
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, plan: newPlan } : u));
      toast.success('Plan updated');
    } catch { toast.error('Failed to update plan'); }
  };

  const filtered = users.filter(
    (u) => !search || u.name?.toLowerCase().includes(search.toLowerCase()) || u.email?.toLowerCase().includes(search.toLowerCase())
  );

  const atRiskUsers = riskData?.users?.filter(u => u.risk === 'high') || [];

  if (loading) return <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-slate-400" /></div>;

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-slate-200 font-semibold">Users ({users.length})</h2>
        <div className="flex items-center gap-3">
          <button onClick={loadChurnRisk} disabled={riskLoading}
            style={{ background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.25)', color: '#ef4444', borderRadius: 8, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
            {riskLoading ? <Loader2 size={12} className="animate-spin" /> : <TrendingDown size={12} />}
            Churn Risk
          </button>
          <div className="relative w-60">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <Input placeholder="Search users..." value={search} onChange={(e) => setSearch(e.target.value)}
              className="pl-8 bg-slate-800 border-slate-700 text-white text-sm h-8" />
          </div>
        </div>
      </div>

      {/* Churn Risk Summary */}
      {riskData && (
        <div style={{ background: 'rgba(239,68,68,0.05)', border: '1px solid rgba(239,68,68,0.15)', borderRadius: 12, padding: 16 }}>
          <div className="flex items-center gap-2 mb-3">
            <TrendingDown size={15} color="#ef4444" />
            <span style={{ fontWeight: 700, color: '#e8e8e8', fontSize: 14 }}>Churn Risk Summary</span>
          </div>
          <div className="grid grid-cols-3 gap-3 mb-3">
            {[
              { label: 'High Risk', count: riskData.summary.high_risk, color: '#ef4444' },
              { label: 'Medium Risk', count: riskData.summary.medium_risk, color: '#f59e0b' },
              { label: 'Low Risk', count: riskData.summary.low_risk, color: '#10b981' },
            ].map(s => (
              <div key={s.label} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 8, padding: '10px 14px', textAlign: 'center' }}>
                <div style={{ fontSize: 22, fontWeight: 900, color: s.color }}>{s.count}</div>
                <div style={{ fontSize: 11, color: 'rgba(232,232,232,0.5)' }}>{s.label}</div>
              </div>
            ))}
          </div>
          {atRiskUsers.length > 0 && (
            <div>
              <p style={{ fontSize: 11, fontWeight: 700, color: '#ef4444', marginBottom: 6, textTransform: 'uppercase' }}>High Risk Users (take action now)</p>
              {atRiskUsers.slice(0, 5).map(u => (
                <div key={u.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <div style={{ flex: 1 }}>
                    <span style={{ fontSize: 13, color: '#e8e8e8', fontWeight: 600 }}>{u.name || u.email}</span>
                    <span style={{ fontSize: 11, color: 'rgba(232,232,232,0.45)', marginLeft: 8 }}>{u.email}</span>
                  </div>
                  <div style={{ fontSize: 11, color: 'rgba(232,232,232,0.45)' }}>{u.factors?.join(' · ')}</div>
                  <RiskBadge risk={u.risk} score={u.risk_score} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* User Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800">
              <th className="text-left text-slate-500 font-medium px-4 py-3">User</th>
              <th className="text-left text-slate-500 font-medium px-4 py-3">Plan</th>
              <th className="text-left text-slate-500 font-medium px-4 py-3">Status</th>
              <th className="text-left text-slate-500 font-medium px-4 py-3">Credits</th>
              {Object.keys(riskMap).length > 0 && <th className="text-left text-slate-500 font-medium px-4 py-3">Churn Risk</th>}
              <th className="text-left text-slate-500 font-medium px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((user) => {
              const risk = riskMap[user.id];
              return (
                <tr key={user.id} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                  <td className="px-4 py-3">
                    <div>
                      <p className="text-slate-200 font-medium">{user.name}</p>
                      <p className="text-slate-500 text-xs">{user.email}</p>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button className={`text-xs px-2 py-1 rounded-full flex items-center gap-1 ${PLAN_COLORS[user.plan] || PLAN_COLORS.free}`}>
                          <Crown size={10} /> {user.plan}
                          <ChevronDown size={10} />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent className="bg-slate-900 border-slate-800">
                        {['free', 'starter', 'pro'].map((p) => (
                          <DropdownMenuItem key={p} className="text-slate-300 focus:bg-slate-800" onClick={() => handlePlanChange(user.id, p)}>
                            {p}
                          </DropdownMenuItem>
                        ))}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-1 rounded-full ${STATUS_COLORS[user.status] || STATUS_COLORS.active}`}>
                      {user.status || 'active'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-slate-400 text-xs">{user.credits_used || 0} / {user.credits_limit || 0}</span>
                  </td>
                  {Object.keys(riskMap).length > 0 && (
                    <td className="px-4 py-3">
                      {risk ? <RiskBadge risk={risk.risk} score={risk.risk_score} /> : <span className="text-slate-600 text-xs">—</span>}
                    </td>
                  )}
                  <td className="px-4 py-3">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800">
                          Actions <ChevronDown size={10} className="ml-1" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent className="bg-slate-900 border-slate-800">
                        <DropdownMenuItem className="text-slate-300 focus:bg-slate-800" onClick={() => handleStatusChange(user.id, 'active')}>
                          <CheckCircle size={14} className="mr-2 text-emerald-400" /> Set Active
                        </DropdownMenuItem>
                        <DropdownMenuItem className="text-slate-300 focus:bg-slate-800" onClick={() => handleStatusChange(user.id, 'suspended')}>
                          Set Suspended
                        </DropdownMenuItem>
                        <DropdownMenuItem className="text-red-400 focus:bg-slate-800" onClick={() => handleStatusChange(user.id, 'banned')}>
                          <Ban size={14} className="mr-2" /> Ban User
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
