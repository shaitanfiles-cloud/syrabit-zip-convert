import { useState, useEffect } from 'react';
import { Edit2, X, CheckCircle2, Cpu, Zap, Globe, AlertTriangle } from 'lucide-react';
import AdminQuickLinks from './AdminQuickLinks';
import { toast } from 'sonner';
import axios from 'axios';

const API_BASE = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

const adminHeaders = (token) => {
  const isRealJwt = token && typeof token === 'string' && token.split('.').length === 3;
  return isRealJwt ? { Authorization: `Bearer ${token}` } : {};
};

const TIERS = [
  { id: 'free',       label: 'Free',       color: 'text-slate-300',  bg: 'bg-slate-500/10', border: 'border-slate-500/20' },
  { id: 'starter',    label: 'Starter',    color: 'text-violet-300', bg: 'bg-violet-500/10',border: 'border-violet-500/20' },
  { id: 'pro',        label: 'Pro',        color: 'text-amber-300',  bg: 'bg-amber-500/10', border: 'border-amber-500/20'  },
  { id: 'enterprise', label: 'Enterprise', color: 'text-cyan-300',   bg: 'bg-cyan-500/10',  border: 'border-cyan-500/20'  },
];

const DEFAULT_POLICIES = {
  free:       { req_per_min: 5,  credits_per_day: 30,   max_tokens: 1024, req_per_min_ip: 20 },
  starter:    { req_per_min: 15, credits_per_day: 500,  max_tokens: 2048, req_per_min_ip: 50 },
  pro:        { req_per_min: 30, credits_per_day: 4000, max_tokens: 4096, req_per_min_ip: 100},
  enterprise: { req_per_min: 60, credits_per_day: 99999,max_tokens: 8192, req_per_min_ip: 200},
};

function TierCard({ tier, policy, onSave }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({...policy});
  const c = TIERS.find((t) => t.id === tier);
  return (
    <div className={`rounded-xl border ${c.border} overflow-hidden`} style={{ background: 'rgba(255,255,255,0.02)' }}>
      <div className={`flex items-center justify-between p-3 ${c.bg}`}>
        <span className={`text-sm font-bold ${c.color}`}>{c.label}</span>
        <button onClick={() => setEditing(!editing)} className="text-white/30 hover:text-white/60 p-1">
          {editing ? <X size={14} /> : <Edit2 size={14} />}
        </button>
      </div>
      <div className="p-3 space-y-2">
        {[['req_per_min','Req/min (user)'],['credits_per_day','Credits/day'],['max_tokens','Max tokens'],['req_per_min_ip','Req/min (IP)']].map(([k,l]) => (
          <div key={k} className="flex items-center justify-between">
            <span className="text-xs text-white/40">{l}</span>
            {editing ? (
              <input type="number" value={draft[k]} onChange={(e) => setDraft((d) => ({...d,[k]:Number(e.target.value)}))}
                className="h-7 w-24 px-2 rounded-lg text-xs text-right text-white outline-none" style={{ background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.12)' }} />
            ) : (
              <span className="text-xs text-white font-mono">{policy[k]?.toLocaleString()}</span>
            )}
          </div>
        ))}
        {editing && (
          <button onClick={() => { onSave(tier, draft); setEditing(false); }}
            className={`w-full h-8 rounded-xl text-xs font-semibold text-white mt-1 ${c.bg.replace('/10','/20')} border ${c.border}`}>
            <CheckCircle2 size={12} className="inline mr-1" /> Save {c.label}
          </button>
        )}
      </div>
    </div>
  );
}

export default function AdminRateLimits({ adminToken, onNavigate }) {
  const [policies, setPolicies] = useState(DEFAULT_POLICIES);
  const [stats, setStats]       = useState({ active_requests: 0, tokens_today: 0, daily_budget: 2000000, cost_degraded: false });
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    const h = adminHeaders(adminToken);
    Promise.all([
      axios.get(`${API_BASE}/admin/rate-policies`, { headers: h, withCredentials: true }),
      axios.get(`${API_BASE}/admin/rate-stats`,    { headers: h, withCredentials: true }),
    ]).then(([polRes, statRes]) => {
      setPolicies(polRes.data);
      setStats(statRes.data);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [adminToken]);

  const handleSave = async (tier, draft) => {
    const updated = { ...policies, [tier]: draft };
    try {
      await axios.put(`${API_BASE}/admin/rate-policies`, updated, { headers: adminHeaders(adminToken), withCredentials: true });
      setPolicies(updated);
      toast.success(`${tier} policy saved`);
    } catch { toast.error('Failed to save'); }
  };

  const budgetPct = Math.min(100, (stats.tokens_today / stats.daily_budget) * 100);
  const budgetColor = budgetPct < 50 ? 'bg-emerald-500' : budgetPct < 80 ? 'bg-amber-500' : 'bg-red-500';

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h2 className="text-lg font-bold text-white">Rate Limits</h2>
        <p className="text-sm text-white/40 mt-0.5">Tier-based rate policies and daily token budget</p>
      </div>
      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[[Cpu,'Active Requests',stats.active_requests,'text-white'],[Zap,'Tokens Today',(stats.tokens_today/1000).toFixed(0)+'K','text-amber-400'],[Globe,'Budget Used',budgetPct.toFixed(1)+'%',budgetPct>80?'text-red-400':'text-emerald-400'],[CheckCircle2,'Cost Mode',stats.cost_degraded?'Degraded':'Normal',stats.cost_degraded?'text-red-400':'text-emerald-400']].map(([Icon,label,val,color]) => (
          <div key={label} className="rounded-xl p-3 border border-white/6" style={{ background: 'rgba(255,255,255,0.02)' }}>
            <Icon size={16} className={`${color} mb-2`} />
            <p className={`text-xl font-bold ${color}`}>{val}</p>
            <p className="text-[10px] text-white/30">{label}</p>
          </div>
        ))}
      </div>
      {/* Budget bar */}
      <div>
        <div className="flex justify-between text-xs text-white/40 mb-2">
          <span>Daily Token Budget</span>
          <span>{stats.tokens_today.toLocaleString()} / {stats.daily_budget.toLocaleString()}</span>
        </div>
        <div className="h-2 rounded-full bg-white/5 overflow-hidden">
          <div className={`h-full rounded-full transition-all ${budgetColor}`} style={{ width: `${budgetPct}%` }} />
        </div>
        {stats.cost_degraded && (
          <p className="text-xs text-red-400 mt-1 flex items-center gap-1">
            <AlertTriangle size={11} /> Model degraded to gemini-1.5-flash (reduced capacity)
          </p>
        )}
      </div>
      {/* Tier cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {TIERS.map(({id}) => <TierCard key={id} tier={id} policy={policies[id] || DEFAULT_POLICIES[id]} onSave={handleSave} />)}
      </div>
      <AdminQuickLinks links={['health','apiconfig','activitylog','settings']} onNavigate={onNavigate} />
    </div>
  );
}
