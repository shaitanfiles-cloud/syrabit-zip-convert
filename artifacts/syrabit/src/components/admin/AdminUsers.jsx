import { useState, useEffect, useCallback } from 'react';
import { Loader2, Search, Ban, CheckCircle, Crown, ChevronDown, AlertTriangle, RefreshCw, TrendingDown, Activity, CreditCard, Plus, Minus, X } from 'lucide-react';
import AdminQuickLinks from './AdminQuickLinks';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { adminGetUsers, adminUpdateUserStatus, adminUpdateUserPlan, churnRisk, adminUpdateUserCredits } from '@/utils/api';
import { toast } from 'sonner';

const PLAN_COLORS = {
  free: 'bg-white/[0.06] text-white/50',
  starter: 'bg-violet-700/30 text-violet-300',
  pro: 'bg-amber-700/30 text-amber-300',
};

const STATUS_COLORS = {
  active: 'bg-emerald-700/30 text-emerald-300',
  suspended: 'bg-orange-700/30 text-orange-300',
  banned: 'bg-red-700/30 text-red-300',
};

const RISK_COLORS = {
  high:   { text: '#ef4444', bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.25)', label: 'High' },
  medium: { text: '#f59e0b', bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.25)', label: 'Medium' },
  low:    { text: '#10b981', bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.25)', label: 'Low' },
};

function RiskBadge({ risk, score }) {
  const c = RISK_COLORS[risk] || RISK_COLORS.low;
  return (
    <span title={`Risk score: ${score}`} style={{ background: c.bg, border: `1px solid ${c.border}`, color: c.text, borderRadius: 20, padding: '2px 8px', fontSize: 11, fontWeight: 700 }}>
      {c.label}
    </span>
  );
}

function CreditsModal({ user, adminToken, onClose, onUpdated }) {
  const [mode, setMode] = useState('add');
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (mode !== 'reset') {
      const n = parseInt(amount, 10);
      if (!n || n <= 0) { toast.error('Enter a valid positive number'); return; }
    }
    setSaving(true);
    try {
      const n = mode !== 'reset' ? (parseInt(amount, 10) || 0) : 0;
      const data = { action: mode, ...(mode !== 'reset' && { amount: n }), reason: reason.trim() || undefined };
      await adminUpdateUserCredits(adminToken, user.id, data);
      toast.success(`Credits ${mode === 'add' ? 'added' : mode === 'reset' ? 'reset' : 'deducted'} for ${user.name || user.email}`);
      onUpdated();
      onClose();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to update credits');
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)' }}>
      <div className="w-full max-w-sm mx-4 rounded-2xl p-6 shadow-2xl" style={{
        background: 'rgba(15,15,30,0.95)',
        border: '1px solid rgba(255,255,255,0.08)',
        backdropFilter: 'blur(20px)',
      }}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-white font-semibold text-sm">Credits Management</h3>
            <p className="text-white/25 text-xs mt-0.5">{user.name || user.email}</p>
            <p className="text-white/35 text-xs">Today: {user.credits_used || 0} used (daily reset)</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-white/30 hover:text-white hover:bg-white/[0.06]">
            <X size={16} />
          </button>
        </div>

        <div className="flex gap-1 mb-4 p-1 rounded-xl" style={{ background: 'rgba(255,255,255,0.04)' }}>
          {[
            { id: 'add', label: 'Add Credits', icon: Plus },
            { id: 'deduct', label: 'Deduct', icon: Minus },
            { id: 'reset', label: 'Reset to 0', icon: RefreshCw },
          ].map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setMode(id)}
              className={`flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg text-xs font-medium transition-all ${
                mode === id ? 'text-white' : 'text-white/30 hover:text-white/60'
              }`}
              style={mode === id ? { background: 'linear-gradient(135deg, #7c3aed, #6d28d9)', boxShadow: '0 2px 12px rgba(124,58,237,0.3)' } : {}}>
              <Icon size={10} /> {label}
            </button>
          ))}
        </div>

        {mode === 'add' && <p className="text-xs text-white/25 mb-3">Restores daily credits — reduces today's usage count.</p>}
        {mode === 'deduct' && <p className="text-xs text-white/25 mb-3">Marks credits as consumed — increases today's usage count.</p>}
        {mode === 'reset' && <p className="text-xs text-white/25 mb-3">Resets today's usage to 0 — restores full daily allowance.</p>}

        {mode !== 'reset' && (
          <div className="mb-3">
            <label className="text-xs text-white/30 mb-1 block">Amount</label>
            <input
              type="number"
              min="1"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="e.g. 100"
              className="w-full rounded-xl px-3 py-2 text-sm text-white focus:border-violet-500 outline-none"
              style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
            />
          </div>
        )}

        <div className="mb-4">
          <label className="text-xs text-white/30 mb-1 block">Reason (optional)</label>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Compensation, promo..."
            className="w-full rounded-xl px-3 py-2 text-sm text-white focus:border-violet-500 outline-none"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
          />
        </div>

        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 py-2 rounded-xl text-sm text-white/40 transition-colors hover:text-white/60"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving || (mode !== 'reset' && (!amount || parseInt(amount, 10) <= 0))}
            className="flex-1 py-2 rounded-xl text-sm text-white disabled:opacity-50 flex items-center justify-center gap-1.5 transition-all hover:opacity-90"
            style={{ background: 'linear-gradient(135deg, #7c3aed, #6d28d9)', boxShadow: '0 2px 12px rgba(124,58,237,0.3)' }}>
            {saving && <Loader2 size={12} className="animate-spin" />}
            {mode === 'add' ? 'Add Credits' : mode === 'reset' ? 'Reset Credits' : 'Deduct Credits'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AdminUsers({ adminToken, navContext, onNavigate }) {
  const [users, setUsers]             = useState([]);
  const [loading, setLoading]         = useState(true);
  const [search, setSearch]           = useState('');
  const [searchInput, setSearchInput] = useState(navContext?.search || '');
  const [page, setPage]               = useState(1);
  const [hasMore, setHasMore]         = useState(false);
  const [tab, setTab]                 = useState('all');
  const [riskData, setRiskData]       = useState(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [riskMap, setRiskMap]         = useState({});
  const [creditsUser, setCreditsUser] = useState(null);

  const PAGE_SIZE = 50;

  const loadUsers = useCallback(async (q = '', p = 1) => {
    setLoading(true);
    try {
      const params = { limit: PAGE_SIZE, offset: (p - 1) * PAGE_SIZE };
      if (q.trim()) params.search = q.trim();
      const res = await adminGetUsers(adminToken, params);
      const data = res.data;
      const list = Array.isArray(data) ? data : data.users || [];
      const total = data.total ?? list.length;
      setUsers(p === 1 ? list : prev => [...prev, ...list]);
      setHasMore((p - 1) * PAGE_SIZE + list.length < total);
      setPage(p);
    } catch {
      toast.error('Failed to load users');
    } finally {
      setLoading(false);
    }
  }, [adminToken]);

  useEffect(() => { loadUsers(); }, [loadUsers]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput);
      loadUsers(searchInput, 1);
    }, 400);
    return () => clearTimeout(timer);
  }, [searchInput]);

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

  const atRiskUsers = riskData?.users?.filter(u => u.risk === 'high') || [];

  if (loading && users.length === 0) return <div className="flex justify-center p-10"><Loader2 size={24} className="animate-spin text-violet-400/60" /></div>;

  return (
    <div className="p-6 space-y-4">
      {creditsUser && (
        <CreditsModal
          user={creditsUser}
          adminToken={adminToken}
          onClose={() => setCreditsUser(null)}
          onUpdated={() => loadUsers(search, 1)}
        />
      )}

      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-white/90 font-semibold text-lg">Users ({users.length}{hasMore ? '+' : ''})</h2>
        <div className="flex items-center gap-3">
          <button onClick={loadChurnRisk} disabled={riskLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all"
            style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)', color: '#ef4444' }}>
            {riskLoading ? <Loader2 size={12} className="animate-spin" /> : <TrendingDown size={12} />}
            Churn Risk
          </button>
          <div className="relative w-60">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/25" />
            <input placeholder="Search users (server-side)..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)}
              className="w-full pl-8 h-8 rounded-xl text-sm text-white placeholder-white/25 outline-none focus:border-violet-500"
              style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }} />
          </div>
        </div>
      </div>

      {riskData && (
        <div className="rounded-2xl p-4" style={{ background: 'rgba(239,68,68,0.04)', border: '1px solid rgba(239,68,68,0.12)' }}>
          <div className="flex items-center gap-2 mb-3">
            <TrendingDown size={15} color="#ef4444" />
            <span className="font-bold text-white/90 text-sm">Churn Risk Summary</span>
          </div>
          <div className="grid grid-cols-3 gap-3 mb-3">
            {[
              { label: 'High Risk', count: riskData.summary.high_risk, color: '#ef4444' },
              { label: 'Medium Risk', count: riskData.summary.medium_risk, color: '#f59e0b' },
              { label: 'Low Risk', count: riskData.summary.low_risk, color: '#10b981' },
            ].map(s => (
              <div key={s.label} className="rounded-xl p-3 text-center" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="text-xl font-black" style={{ color: s.color }}>{s.count}</div>
                <div className="text-[11px] text-white/30">{s.label}</div>
              </div>
            ))}
          </div>
          {atRiskUsers.length > 0 && (
            <div>
              <p className="text-[11px] font-bold text-red-400 mb-2 uppercase tracking-wide">High Risk Users (take action)</p>
              {atRiskUsers.slice(0, 5).map(u => (
                <div key={u.id} className="flex items-center gap-3 py-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <div className="flex-1">
                    <span className="text-sm text-white/80 font-semibold">{u.name || u.email}</span>
                    <span className="text-xs text-white/25 ml-2">{u.email}</span>
                  </div>
                  <div className="text-xs text-white/25">{u.factors?.join(' · ')}</div>
                  <RiskBadge risk={u.risk} score={u.risk_score} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="rounded-2xl overflow-hidden" style={{
        background: 'rgba(15,15,30,0.6)',
        border: '1px solid rgba(255,255,255,0.06)',
        backdropFilter: 'blur(12px)',
      }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
              <th className="text-left text-white/30 font-medium px-4 py-3 text-xs">User</th>
              <th className="text-left text-white/30 font-medium px-4 py-3 text-xs">Plan</th>
              <th className="text-left text-white/30 font-medium px-4 py-3 text-xs">Status</th>
              <th className="text-left text-white/30 font-medium px-4 py-3 text-xs">Credits</th>
              {Object.keys(riskMap).length > 0 && <th className="text-left text-white/30 font-medium px-4 py-3 text-xs">Churn Risk</th>}
              <th className="text-left text-white/30 font-medium px-4 py-3 text-xs">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const risk = riskMap[user.id];
              return (
                <tr key={user.id} className="hover:bg-white/[0.02] transition-colors" style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                  <td className="px-4 py-3">
                    <div>
                      <p className="text-white/80 font-medium">{user.name}</p>
                      <p className="text-white/25 text-xs">{user.email}</p>
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
                      <DropdownMenuContent style={{ background: 'rgba(15,15,30,0.95)', border: '1px solid rgba(255,255,255,0.08)' }}>
                        {['free', 'starter', 'pro'].map((p) => (
                          <DropdownMenuItem key={p} className="text-white/60 focus:bg-white/[0.06]" onClick={() => handlePlanChange(user.id, p)}>
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
                    <button
                      onClick={() => setCreditsUser(user)}
                      className="flex items-center gap-1.5 text-white/30 hover:text-violet-300 text-xs transition-colors"
                      title="Manage credits"
                    >
                      <CreditCard size={12} />
                      {user.credits_used || 0} / {user.credits_limit || 0}
                    </button>
                  </td>
                  {Object.keys(riskMap).length > 0 && (
                    <td className="px-4 py-3">
                      {risk ? <RiskBadge risk={risk.risk} score={risk.risk_score} /> : <span className="text-white/15 text-xs">—</span>}
                    </td>
                  )}
                  <td className="px-4 py-3">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button className="h-7 px-2 text-xs text-white/30 hover:text-white/60 rounded-lg hover:bg-white/[0.04] transition-colors flex items-center gap-1">
                          Actions <ChevronDown size={10} />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent style={{ background: 'rgba(15,15,30,0.95)', border: '1px solid rgba(255,255,255,0.08)' }}>
                        <DropdownMenuItem className="text-white/60 focus:bg-white/[0.06]" onClick={() => setCreditsUser(user)}>
                          <CreditCard size={14} className="mr-2 text-violet-400" /> Manage Credits
                        </DropdownMenuItem>
                        <DropdownMenuItem className="text-white/60 focus:bg-white/[0.06]" onClick={() => handleStatusChange(user.id, 'active')}>
                          <CheckCircle size={14} className="mr-2 text-emerald-400" /> Set Active
                        </DropdownMenuItem>
                        <DropdownMenuItem className="text-white/60 focus:bg-white/[0.06]" onClick={() => handleStatusChange(user.id, 'suspended')}>
                          Set Suspended
                        </DropdownMenuItem>
                        <DropdownMenuItem className="text-red-400 focus:bg-white/[0.06]" onClick={() => handleStatusChange(user.id, 'banned')}>
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
        {loading && (
          <div className="flex justify-center p-4">
            <Loader2 size={16} className="animate-spin text-violet-400/40" />
          </div>
        )}
        {hasMore && !loading && (
          <div className="flex justify-center p-4">
            <button onClick={() => loadUsers(search, page + 1)}
              className="text-xs text-white/30 hover:text-violet-300 px-4 py-2 rounded-xl transition-colors"
              style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
              Load more users
            </button>
          </div>
        )}
      </div>
      <AdminQuickLinks links={['conversations','analytics','notifications','monetization']} onNavigate={onNavigate} />
    </div>
  );
}
