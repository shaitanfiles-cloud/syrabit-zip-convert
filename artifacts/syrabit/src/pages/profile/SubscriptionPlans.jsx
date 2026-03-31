import { Link } from 'react-router-dom';
import {
  Check, CheckCircle, Zap, Lock, Sparkles, Loader2,
  FileText, Target, Calendar, ChevronRight, Plus,
} from 'lucide-react';
import { PLANS, PLAN_RANK, PLAN_FEATURES } from './shared';
import { DOC_ACCESS_CONFIG } from '@/utils/plans';

export default function SubscriptionPlans({
  plan, planInfo, profile,
  setPaymentPlan, setShowPaymentModal,
  myPlans, plansLoading, setShowGenModal,
}) {
  return (
    <>
      <div className="glass-card rounded-2xl overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Subscription</p>
          <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${planInfo.badgeColor}`}>
            {plan.toUpperCase()}
          </span>
        </div>

        <div className="p-4 space-y-4">
          <div className="flex items-center justify-between p-3 rounded-xl"
            style={{ background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.15)' }}>
            <div>
              <p className="text-xs text-muted-foreground">Current plan</p>
              <p className="font-bold text-foreground">{planInfo.label}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-muted-foreground">Document access</p>
              <p className={`text-sm font-semibold ${(DOC_ACCESS_CONFIG[profile?.document_access || PLANS[plan]?.docAccess || 'zero'] || DOC_ACCESS_CONFIG.zero).color}`}>
                {(DOC_ACCESS_CONFIG[profile?.document_access || PLANS[plan]?.docAccess || 'zero'] || DOC_ACCESS_CONFIG.zero).icon}{' '}
                {(DOC_ACCESS_CONFIG[profile?.document_access || PLANS[plan]?.docAccess || 'zero'] || DOC_ACCESS_CONFIG.zero).label}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {Object.entries(PLANS).map(([planKey, info]) => {
              const isActive    = plan === planKey;
              const isPro       = planKey === 'pro';
              const cardRank    = PLAN_RANK[planKey] ?? 0;
              const userRank    = PLAN_RANK[plan]    ?? 0;
              const isLower     = cardRank < userRank;
              const docInfo     = DOC_ACCESS_CONFIG[info.docAccess] || DOC_ACCESS_CONFIG.zero;
              return (
                <div
                  key={planKey}
                  className="relative rounded-xl p-3 flex flex-col transition-all duration-200"
                  style={
                    isActive
                      ? { border: '1px solid rgba(139,92,246,0.50)', background: 'rgba(124,58,237,0.08)', boxShadow: '0 0 20px rgba(139,92,246,0.12)' }
                      : isLower
                      ? { border: '1px solid rgba(255,255,255,0.04)', background: 'rgba(255,255,255,0.01)', opacity: 0.6 }
                      : { border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }
                  }
                >
                  <div
                    className="absolute -top-2.5 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full text-[10px] font-bold whitespace-nowrap"
                    style={
                      isActive
                        ? { background: 'rgba(124,58,237,0.25)', color: 'hsl(var(--primary))', border: '1px solid rgba(139,92,246,0.35)' }
                        : isPro
                        ? { background: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.30)' }
                        : planKey === 'starter'
                        ? { background: 'rgba(139,92,246,0.15)', color: '#a78bfa', border: '1px solid rgba(139,92,246,0.30)' }
                        : { background: 'rgba(255,255,255,0.05)', color: 'hsl(var(--muted-foreground))', border: '1px solid rgba(255,255,255,0.08)' }
                    }
                  >
                    {isActive ? 'ACTIVE' : info.badge}
                  </div>

                  <p className="text-sm font-semibold text-foreground mt-1">{info.label}</p>

                  <p className="font-bold text-2xl mt-1"
                    style={{ color: isPro ? '#f59e0b' : isLower ? 'hsl(var(--muted-foreground))' : 'hsl(var(--primary))' }}>
                    {info.credits.toLocaleString()}
                    <span className="text-xs font-normal text-muted-foreground ml-1">credits</span>
                  </p>

                  <p className="text-base font-semibold text-foreground mt-0.5">
                    {info.price}
                    <span className="text-xs font-normal text-muted-foreground ml-1">{info.period}</span>
                  </p>

                  <div className="flex items-center gap-1.5 mt-2 mb-1">
                    <span className={`text-[10px] font-semibold ${docInfo.color}`}>
                      {docInfo.icon} {docInfo.label}
                    </span>
                  </div>

                  <ul className="mt-1 space-y-1 flex-1">
                    {PLAN_FEATURES[planKey].slice(0, 3).map((f) => (
                      <li key={f} className="flex items-center gap-1 text-[10px] text-muted-foreground/70">
                        <Check size={10} className="text-emerald-400 flex-shrink-0" aria-hidden="true" />
                        {f}
                      </li>
                    ))}
                  </ul>

                  {isActive ? (
                    <div className="mt-3 w-full h-8 rounded-lg flex items-center justify-center text-xs font-medium"
                      style={{ background: 'rgba(139,92,246,0.12)', color: 'hsl(var(--primary))' }}>
                      <CheckCircle size={12} className="mr-1" aria-hidden="true" /> Current Plan
                    </div>
                  ) : isLower ? (
                    <div className="mt-3 w-full h-8 rounded-lg flex items-center justify-center text-[10px] font-medium text-muted-foreground/50"
                      style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                      Included in your plan
                    </div>
                  ) : (
                    <button
                      onClick={() => { setPaymentPlan(planKey); setShowPaymentModal(true); }}
                      className="mt-3 w-full h-8 rounded-lg text-xs font-semibold text-white transition-all hover:opacity-90 active:scale-[0.98]"
                      style={isPro
                        ? { background: 'linear-gradient(135deg,#d97706,#f59e0b)', boxShadow: '0 4px 12px rgba(245,158,11,0.25)' }
                        : { background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)', boxShadow: '0 4px 12px rgba(124,58,237,0.25)' }}
                      aria-label={`Upgrade to ${info.label} plan`}
                      data-testid={`upgrade-${planKey}-button`}
                    >
                      Upgrade to {info.label}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="glass-card rounded-2xl overflow-hidden">
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">My Study Plans</p>
            <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold"
              style={{ background: 'rgba(139,92,246,0.12)', color: 'hsl(var(--primary))', border: '1px solid rgba(139,92,246,0.20)' }}>
              AI-Generated
            </span>
          </div>
          {['starter', 'pro'].includes(plan) ? (
            <button
              onClick={() => setShowGenModal(true)}
              className="flex items-center gap-1.5 h-7 px-3 rounded-lg text-xs font-semibold text-white hover:opacity-90 transition-all"
              style={{ background: 'linear-gradient(135deg,#7c3aed,#6d28d9)' }}>
              <Plus size={12} /> Generate Plan
            </button>
          ) : (
            <button
              onClick={() => { setPaymentPlan('starter'); setShowPaymentModal(true); }}
              className="flex items-center gap-1.5 h-7 px-3 rounded-lg text-xs font-semibold hover:opacity-90 transition-all"
              style={{ background: 'rgba(139,92,246,0.12)', color: 'hsl(var(--primary))', border: '1px solid rgba(139,92,246,0.20)' }}>
              <Lock size={11} /> Starter only
            </button>
          )}
        </div>

        <div className="p-4">
          {!['starter', 'pro'].includes(plan) ? (
            <div className="text-center py-6 space-y-3">
              <div className="w-10 h-10 rounded-xl mx-auto flex items-center justify-center" style={{ background: 'rgba(139,92,246,0.10)' }}>
                <Sparkles size={18} className="text-violet-400" />
              </div>
              <p className="text-sm font-medium text-foreground">Personalized Exam Plans</p>
              <p className="text-xs text-muted-foreground max-w-xs mx-auto">
                AI generates a custom day-by-day sprint based on your weak topics.
                Available on Starter &amp; Pro.
              </p>
              <button
                onClick={() => { setPaymentPlan('starter'); setShowPaymentModal(true); }}
                className="inline-flex items-center gap-2 h-9 px-5 rounded-xl text-sm font-semibold text-white hover:opacity-90 transition-all"
                style={{ background: 'linear-gradient(135deg,#7c3aed,#6d28d9)', boxShadow: '0 4px 16px rgba(124,58,237,0.30)' }}>
                <Zap size={13} /> Upgrade — ₹99
              </button>
            </div>
          ) : plansLoading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 size={20} className="animate-spin text-violet-400" />
            </div>
          ) : myPlans.length === 0 ? (
            <div className="text-center py-6 space-y-3">
              <FileText size={28} className="mx-auto text-white/20" />
              <p className="text-sm text-muted-foreground">No plans yet. Generate your first!</p>
              <button
                onClick={() => setShowGenModal(true)}
                className="inline-flex items-center gap-2 h-9 px-5 rounded-xl text-sm font-semibold text-white hover:opacity-90 transition-all"
                style={{ background: 'linear-gradient(135deg,#7c3aed,#6d28d9)', boxShadow: '0 4px 16px rgba(124,58,237,0.30)' }}>
                <Sparkles size={13} /> Generate My First Plan
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {myPlans.slice(0, 5).map(p => (
                <Link
                  key={p.id}
                  to={`/cms/${profile?.id}/${p.slug}`}
                  className="flex items-center gap-3 p-3 rounded-xl hover:opacity-90 transition-all group"
                  style={{ background: 'rgba(139,92,246,0.05)', border: '1px solid rgba(139,92,246,0.12)' }}>
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ background: 'rgba(139,92,246,0.12)' }}>
                    <Target size={14} className="text-violet-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{p.title}</p>
                    <p className="text-xs text-muted-foreground flex items-center gap-2 mt-0.5">
                      {p.subject_name && <span>{p.subject_name}</span>}
                      {p.created_at && (
                        <span className="flex items-center gap-1">
                          <Calendar size={10} />
                          {new Date(p.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                        </span>
                      )}
                    </p>
                  </div>
                  <ChevronRight size={14} className="text-white/20 group-hover:text-white/50 transition-colors flex-shrink-0" />
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
