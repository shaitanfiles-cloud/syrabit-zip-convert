import { useState, useEffect, useCallback } from 'react';
import { Zap, Crown, Sparkles, Edit2, X, CheckCircle2, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { adminGetDashboard, adminGetPlanConfig, adminUpdatePlanConfig } from '@/utils/api';

const PLAN_UI = {
  free:    { icon: Zap,      gradient: 'from-slate-600 to-slate-700',   docAccess: 'zero',    docLabel: '🔒 Zero document access',    color: 'text-slate-300'  },
  starter: { icon: Crown,    gradient: 'from-violet-600 to-purple-700', docAccess: 'limited', docLabel: '📄 Limited document access', color: 'text-violet-300' },
  pro:     { icon: Sparkles, gradient: 'from-amber-500 to-orange-600',  docAccess: 'full',    docLabel: '📚 Full document access',    color: 'text-amber-300'  },
};

function PlanCard({ planKey, ui, config, dist, onSave, saving }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ price: config.price, credits: config.credits, validity: config.validity });
  const Icon = ui.icon;
  const count = dist[planKey] || 0;
  const revenue = planKey !== 'free' ? (count * Number(draft.price)) : 0;

  useEffect(() => {
    setDraft({ price: config.price, credits: config.credits, validity: config.validity });
  }, [config]);

  const handleSave = async () => {
    await onSave(planKey, draft);
    setEditing(false);
  };

  return (
    <div className="rounded-2xl border border-white/6 overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)' }}>
      <div className={`h-1.5 bg-gradient-to-r ${ui.gradient}`} />
      <div className="p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className={`w-9 h-9 rounded-xl flex items-center justify-center bg-gradient-to-br ${ui.gradient}`}>
              <Icon size={16} className="text-white" />
            </div>
            <div>
              <p className={`font-bold text-sm ${ui.color}`}>{planKey.charAt(0).toUpperCase() + planKey.slice(1)}</p>
              <p className="text-[10px] text-white/30">{count} users</p>
            </div>
          </div>
          <button onClick={() => setEditing(!editing)} className="p-1.5 rounded-lg hover:bg-white/5 text-white/30 hover:text-white/60">
            {editing ? <X size={14} /> : <Edit2 size={14} />}
          </button>
        </div>
        <div className="space-y-2">
          {[{k:'price',l:'Price (₹)',type:'number'},{k:'credits',l:'Credits',type:'number'},{k:'validity',l:'Validity',type:'text'}].map(({k,l,type}) => (
            <div key={k} className="flex items-center justify-between">
              <span className="text-xs text-white/40">{l}</span>
              {editing ? (
                <input type={type} value={draft[k]} onChange={(e) => setDraft((d) => ({...d,[k]:e.target.value}))}
                  className="h-7 w-28 px-2 rounded-lg text-xs text-white text-right outline-none" style={{ background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.12)' }} />
              ) : (
                <span className="text-xs text-white font-mono">{k === 'price' ? `₹${draft[k]}` : k === 'credits' ? Number(draft[k]).toLocaleString() : draft[k]}</span>
              )}
            </div>
          ))}
          <div className="flex items-center justify-between pt-1 border-t border-white/6">
            <span className="text-xs text-white/30">Document access</span>
            <span className={`text-xs font-medium ${ui.color}`}>{ui.docLabel}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-xs text-white/30">Est. revenue</span>
            <span className="text-xs text-white/60 font-mono">₹{revenue.toLocaleString()}</span>
          </div>
        </div>
        {editing && (
          <button onClick={handleSave} disabled={saving}
            className="w-full mt-3 h-8 rounded-xl text-xs font-semibold text-white flex items-center justify-center" style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' }}>
            {saving ? <Loader2 size={12} className="animate-spin mr-1" /> : <CheckCircle2 size={12} className="inline mr-1" />} Save
          </button>
        )}
      </div>
    </div>
  );
}

export default function AdminPlans({ adminToken }) {
  const [dist, setDist] = useState({ free: 0, starter: 0, pro: 0 });
  const [planConfig, setPlanConfig] = useState({
    free:    { price: 0,   credits: 30,   validity: 'monthly' },
    starter: { price: 99,  credits: 300,  validity: '30 days' },
    pro:     { price: 999, credits: 4000, validity: '365 days' },
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [dashRes, configRes] = await Promise.all([
        adminGetDashboard(adminToken),
        adminGetPlanConfig(adminToken),
      ]);
      const dashData = dashRes.data;
      if (dashData.plan_distribution) {
        setDist(dashData.plan_distribution);
      }
      const cfgData = configRes.data;
      if (cfgData && typeof cfgData === 'object') {
        setPlanConfig(prev => ({ ...prev, ...cfgData }));
      }
    } catch (err) {
      toast.error('Failed to load plan data');
    } finally {
      setLoading(false);
    }
  }, [adminToken]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSave = async (planKey, draft) => {
    setSaving(true);
    try {
      const updated = { ...planConfig, [planKey]: { price: Number(draft.price), credits: Number(draft.credits), validity: draft.validity } };
      await adminUpdatePlanConfig(adminToken, updated);
      setPlanConfig(updated);
      toast.success(`${planKey.charAt(0).toUpperCase() + planKey.slice(1)} plan updated`);
    } catch (err) {
      toast.error('Failed to save plan config');
    } finally {
      setSaving(false);
    }
  };

  const totalUsers = Object.values(dist).reduce((a, b) => a + b, 0);
  const paidUsers = (dist.starter || 0) + (dist.pro || 0);
  const estRevenue = (dist.starter || 0) * Number(planConfig.starter.price) + (dist.pro || 0) * Number(planConfig.pro.price);
  const creditsIssued = (dist.starter || 0) * Number(planConfig.starter.credits) + (dist.pro || 0) * Number(planConfig.pro.credits);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin text-white/40" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h2 className="text-lg font-bold text-white">Plans & Credits</h2>
        <p className="text-sm text-white/40 mt-0.5">Configure subscription plans and review revenue metrics</p>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[['Est. Revenue',`₹${estRevenue.toLocaleString()}`,'text-emerald-400'],['Total Users',totalUsers.toLocaleString(),'text-white'],['Paid Users',paidUsers.toLocaleString(),'text-violet-400'],['Credits Issued',creditsIssued.toLocaleString(),'text-amber-400']].map(([label,val,color]) => (
          <div key={label} className="rounded-xl p-3 border border-white/6" style={{ background: 'rgba(255,255,255,0.02)' }}>
            <p className={`text-xl font-bold ${color}`}>{val}</p>
            <p className="text-[10px] text-white/30 mt-0.5">{label}</p>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {Object.entries(PLAN_UI).map(([k, ui]) => (
          <PlanCard key={k} planKey={k} ui={ui} config={planConfig[k]} dist={dist} onSave={handleSave} saving={saving} />
        ))}
      </div>
      <div className="rounded-xl p-4" style={{ background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.15)' }}>
        <p className="text-sm text-violet-300 font-medium">💳 Enable live payments</p>
        <p className="text-xs text-white/50 mt-1">Configure Razorpay or Stripe credentials in the API Config section to activate real payment checkout and automatic plan upgrades.</p>
      </div>
    </div>
  );
}
