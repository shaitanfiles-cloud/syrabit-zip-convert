import { useState, useEffect, useCallback } from 'react';
import {
  Loader2, DollarSign, Users, TrendingUp, CreditCard,
  RefreshCw, ArrowUp, ArrowDown, Gift, Percent,
  BarChart2, Wallet, Crown, Star,
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, PieChart, Pie, Cell,
} from 'recharts';
import axios from 'axios';
import { API_BASE } from '@/utils/api';

const TOOLTIP_STYLE = {
  contentStyle: {
    background: '#0f172a',
    border: '1px solid #1e293b',
    borderRadius: '8px',
    color: '#e2e8f0',
    fontSize: 12,
  },
};

const PLAN_COLORS = { free: '#64748b', starter: '#8b5cf6', pro: '#f59e0b' };

function MetricCard({ icon: Icon, label, value, change, color, prefix = '' }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: `${color}18` }}>
          <Icon size={18} style={{ color }} />
        </div>
        {change !== undefined && (
          <div className={`flex items-center gap-1 text-xs font-medium ${change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {change >= 0 ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
            {Math.abs(change)}%
          </div>
        )}
      </div>
      <p className="text-2xl font-bold text-white">{prefix}{typeof value === 'number' ? value.toLocaleString() : value}</p>
      <p className="text-slate-500 text-xs mt-1">{label}</p>
    </div>
  );
}

export default function AdminMonetization({ adminToken }) {
  const [overview, setOverview] = useState(null);
  const [revenue, setRevenue] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [predictor, setPredictor] = useState(null);
  const [referralCfg, setReferralCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('overview');
  const [savingRef, setSavingRef] = useState(false);

  const headers = { withCredentials: true };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ovRes, revRes, funRes, predRes, refRes] = await Promise.allSettled([
        axios.get(`${API_BASE}/admin/monetization/overview`, headers),
        axios.get(`${API_BASE}/admin/analytics/revenue?days=30`, headers),
        axios.get(`${API_BASE}/admin/analytics/funnel`, headers),
        axios.get(`${API_BASE}/admin/analytics/predictor`, headers),
        axios.get(`${API_BASE}/admin/monetization/referral-config`, headers),
      ]);
      if (ovRes.status === 'fulfilled') setOverview(ovRes.value.data);
      if (revRes.status === 'fulfilled') setRevenue(revRes.value.data);
      if (funRes.status === 'fulfilled') setFunnel(funRes.value.data);
      if (predRes.status === 'fulfilled') setPredictor(predRes.value.data);
      if (refRes.status === 'fulfilled') setReferralCfg(refRes.value.data);
    } catch {}
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const saveReferralConfig = async () => {
    setSavingRef(true);
    try {
      await axios.put(`${API_BASE}/admin/monetization/referral-config`, referralCfg, headers);
    } catch {}
    finally { setSavingRef(false); }
  };

  if (loading) return (
    <div className="flex justify-center p-10">
      <Loader2 size={24} className="animate-spin text-slate-400" />
    </div>
  );

  const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'revenue', label: 'Revenue' },
    { id: 'funnel', label: 'Funnel' },
    { id: 'referrals', label: 'Referrals' },
  ];

  const cohortData = revenue?.cohorts
    ? Object.entries(revenue.cohorts).map(([name, value]) => ({ name: name.charAt(0).toUpperCase() + name.slice(1), value, fill: PLAN_COLORS[name] || '#64748b' }))
    : [];

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-white font-bold text-lg flex items-center gap-2">
            <Crown size={18} className="text-amber-400" />
            Monetization
          </h2>
          <p className="text-slate-500 text-sm mt-1">Revenue analytics, cohorts, referrals, and pricing</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs text-slate-400 hover:text-white bg-slate-800 border border-slate-700"
        >
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      <div className="flex gap-1 bg-slate-800/50 rounded-xl p-1 w-fit">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              tab === t.id ? 'bg-violet-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && overview && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricCard icon={DollarSign} label="Revenue (30d)" value={overview.revenue_30d_inr} prefix="₹" color="#10b981" />
            <MetricCard icon={Wallet} label="Revenue (7d)" value={overview.revenue_7d_inr} prefix="₹" color="#3b82f6" />
            <MetricCard icon={Users} label="Paid Users" value={overview.total_paid_users} color="#8b5cf6" />
            <MetricCard icon={Percent} label="Conversion Rate" value={overview.conversion_rate + '%'} color="#f59e0b" />
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricCard icon={Star} label="ARPU (INR)" value={overview.arpu_inr} prefix="₹" color="#ec4899" />
            <MetricCard icon={CreditCard} label="Starter Users" value={overview.starter_users} color="#8b5cf6" />
            <MetricCard icon={Crown} label="Pro Users" value={overview.pro_users} color="#f59e0b" />
            <MetricCard icon={Users} label="Free Users" value={overview.total_free_users} color="#64748b" />
          </div>

          {overview.recent_transactions?.length > 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <h3 className="text-slate-400 text-sm font-medium mb-4">Recent Transactions</h3>
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {overview.recent_transactions.map((txn, i) => (
                  <div key={i} className="flex items-center gap-3 p-2.5 bg-slate-800/50 rounded-lg">
                    <DollarSign size={14} className="text-emerald-400 flex-shrink-0" />
                    <span className="text-slate-300 text-xs font-mono flex-shrink-0">{txn.user_id?.slice(0, 8)}...</span>
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                      txn.plan === 'pro' ? 'bg-amber-500/15 text-amber-400' : 'bg-violet-500/15 text-violet-400'
                    }`}>
                      {txn.plan}
                    </span>
                    <span className="text-white text-sm font-medium ml-auto">
                      {txn.currency === 'INR' ? '₹' : '$'}{txn.amount}
                    </span>
                    <span className="text-slate-600 text-xs">{txn.date}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {predictor && (
            <div className="bg-gradient-to-r from-violet-500/10 to-amber-500/10 border border-violet-500/20 rounded-xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp size={16} className="text-violet-400" />
                <h3 className="text-white font-semibold text-sm">30-Day Predictor</h3>
              </div>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <div>
                  <p className="text-slate-500 text-xs">Current MRR</p>
                  <p className="text-white font-bold text-lg">₹{predictor.current_mrr_inr}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs">Predicted MRR</p>
                  <p className="text-emerald-400 font-bold text-lg">₹{predictor.predicted_mrr_inr}</p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs">Growth Rate</p>
                  <p className={`font-bold text-lg ${predictor.growth_rate_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {predictor.growth_rate_pct >= 0 ? '+' : ''}{predictor.growth_rate_pct}%
                  </p>
                </div>
                <div>
                  <p className="text-slate-500 text-xs">Signups This Month</p>
                  <p className="text-white font-bold text-lg">{predictor.signups_this_month}</p>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {tab === 'revenue' && revenue && (
        <>
          {revenue.daily_revenue?.length > 0 ? (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <h3 className="text-slate-400 text-sm font-medium mb-4">Daily Revenue (Last 30 Days)</h3>
              <ResponsiveContainer width="100%" height={250}>
                <AreaChart data={revenue.daily_revenue} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickFormatter={d => d?.slice(5)} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                  <Tooltip {...TOOLTIP_STYLE} />
                  <Area type="monotone" dataKey="revenue_inr" name="Revenue (₹)" stroke="#10b981" fill="rgba(16,185,129,0.15)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 text-center">
              <DollarSign size={32} className="text-slate-700 mx-auto mb-3" />
              <p className="text-slate-500 text-sm">No revenue data yet</p>
            </div>
          )}

          {cohortData.length > 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
              <h3 className="text-slate-400 text-sm font-medium mb-4">User Cohorts by Plan</h3>
              <div className="flex items-center justify-center">
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={cohortData} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                    <Tooltip {...TOOLTIP_STYLE} />
                    <Bar dataKey="value" name="Users" radius={[4, 4, 0, 0]}>
                      {cohortData.map((entry, i) => (
                        <Cell key={i} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </>
      )}

      {tab === 'funnel' && funnel && (
        <div className="space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h3 className="text-slate-400 text-sm font-medium mb-4">Conversion Funnel</h3>
            <div className="space-y-3">
              {funnel.funnel?.map((stage, i) => (
                <div key={i} className="relative">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-white text-sm font-medium">{stage.stage}</span>
                    <span className="text-slate-400 text-sm">{stage.count} ({stage.pct}%)</span>
                  </div>
                  <div className="h-8 rounded-lg overflow-hidden bg-slate-800">
                    <div
                      className="h-full rounded-lg transition-all duration-500"
                      style={{
                        width: `${stage.pct}%`,
                        background: i === 0 ? 'linear-gradient(90deg,#3b82f6,#60a5fa)' :
                                   i === 1 ? 'linear-gradient(90deg,#8b5cf6,#a78bfa)' :
                                            'linear-gradient(90deg,#10b981,#34d399)',
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <MetricCard icon={DollarSign} label="Revenue per Paid User" value={funnel.revenue_per_user} prefix="₹" color="#10b981" />
            <MetricCard icon={Percent} label="Overall Conversion" value={funnel.conversion_rate + '%'} color="#8b5cf6" />
          </div>
        </div>
      )}

      {tab === 'referrals' && (
        <div className="space-y-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h3 className="text-white font-semibold text-sm mb-4 flex items-center gap-2">
              <Gift size={16} className="text-pink-400" />
              Referral Program Configuration
            </h3>
            {referralCfg && (
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <label className="text-slate-400 text-sm w-32">Enabled</label>
                  <button
                    onClick={() => setReferralCfg(prev => ({ ...prev, enabled: !prev.enabled }))}
                    className={`w-12 h-6 rounded-full transition-colors ${referralCfg.enabled ? 'bg-emerald-500' : 'bg-slate-700'}`}
                  >
                    <div className={`w-5 h-5 bg-white rounded-full transition-transform ${referralCfg.enabled ? 'translate-x-6' : 'translate-x-0.5'}`} />
                  </button>
                </div>
                <div className="flex items-center gap-3">
                  <label className="text-slate-400 text-sm w-32">Reward (credits)</label>
                  <input
                    type="number"
                    value={referralCfg.reward_credits}
                    onChange={(e) => setReferralCfg(prev => ({ ...prev, reward_credits: parseInt(e.target.value) || 0 }))}
                    className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white w-24"
                  />
                </div>
                <div className="flex items-center gap-3">
                  <label className="text-slate-400 text-sm w-32">Referrer (credits)</label>
                  <input
                    type="number"
                    value={referralCfg.referrer_credits}
                    onChange={(e) => setReferralCfg(prev => ({ ...prev, referrer_credits: parseInt(e.target.value) || 0 }))}
                    className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white w-24"
                  />
                </div>
                <button
                  onClick={saveReferralConfig}
                  disabled={savingRef}
                  className="flex items-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white rounded-lg px-4 py-2 text-sm font-medium"
                >
                  {savingRef ? <Loader2 size={14} className="animate-spin" /> : null}
                  Save Configuration
                </button>
              </div>
            )}
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5">
            <h3 className="text-white font-semibold text-sm mb-3">Pricing Tiers</h3>
            <div className="grid grid-cols-3 gap-3">
              {[
                { plan: 'Free', price: '₹0', credits: '30', color: '#64748b' },
                { plan: 'Starter', price: '₹99', credits: '300', color: '#8b5cf6' },
                { plan: 'Pro', price: '₹999', credits: '4,000', color: '#f59e0b' },
              ].map(tier => (
                <div key={tier.plan} className="p-4 bg-slate-800/50 rounded-xl text-center">
                  <p className="font-bold text-lg" style={{ color: tier.color }}>{tier.plan}</p>
                  <p className="text-white text-xl font-bold mt-1">{tier.price}</p>
                  <p className="text-slate-500 text-xs mt-1">{tier.credits} credits</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
