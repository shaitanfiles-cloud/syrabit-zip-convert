import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Zap, ArrowRight, Sparkles, CheckCircle, Trophy } from 'lucide-react';
import { fadeUp, staggerContainer } from './shared';
import Reveal from './Reveal';
import GlowOrb from './GlowOrb';

const PLANS = [
  {
    id: 'free', name: 'Free', price: '₹0', period: '/ month', credits: '0 credits',
    renewal: 'No credits included', icon: Zap, highlighted: false, badge: null,
    docAccess: '🔒 Zero document access',
    features: ['30 AI credits/month', 'All subjects access', 'Chat history (limited)', 'Zero document access'],
    ctaText: 'Get Started Free',
  },
  {
    id: 'starter', name: 'Starter', price: '₹99', period: 'one-time', credits: '300 credits',
    renewal: 'Valid for 1 month', icon: Trophy, highlighted: true, badge: 'MOST POPULAR',
    docAccess: '📄 Limited document access',
    features: ['300 AI credits', 'All subjects access', 'Full chat history', 'Limited document access', 'Priority responses'],
    ctaText: 'Buy Starter',
  },
  {
    id: 'pro', name: 'Pro', price: '₹999', period: 'one-time', credits: '4,000 credits',
    renewal: 'Valid for 1 year', icon: Sparkles, highlighted: false, badge: 'BEST VALUE',
    docAccess: '📚 Full document access',
    features: ['4,000 AI credits', 'Unlimited subjects access', 'Unlimited history', 'Full document access', 'All AI models (fastest)', 'Early access to features'],
    ctaText: 'Go Pro',
  },
];

export default function PricingSection() {
  return (
    <section id="pricing" className="py-28 relative overflow-hidden" style={{ background: 'rgba(255,255,255,0.015)' }}>
      <div className="absolute inset-0 pointer-events-none">
        <GlowOrb color="radial-gradient(circle,#7c3aed,transparent)" size={600} x="10%" y="30%" blur={120} opacity={0.08} animRange={20} duration={22} />
      </div>
      <div className="max-w-5xl mx-auto px-5 relative z-10">
        <Reveal className="text-center mb-14">
          <div
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-5"
            style={{ background: 'rgba(124,58,237,0.10)', border: '1px solid rgba(139,92,246,0.22)' }}
          >
            <Zap size={14} style={{ color: '#a78bfa' }} />
            <span className="text-xs font-semibold tracking-widest" style={{ color: '#a78bfa' }}>SIMPLE PRICING</span>
          </div>
          <h2 className="text-white mb-4" style={{ fontSize: 'clamp(1.8rem,4vw,2.8rem)', fontWeight: 800, letterSpacing: '-0.02em' }}>
            Start free. Scale as you need.
          </h2>
          <p className="max-w-lg mx-auto" style={{ color: 'rgba(255,255,255,0.40)' }}>
            No subscriptions. No hidden fees. Buy credits when you need them — they never expire within validity.
          </p>
        </Reveal>

        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
          variants={staggerContainer}
          className="grid grid-cols-1 lg:grid-cols-3 gap-5"
        >
          {PLANS.map((plan) => {
            const isPro = plan.id === 'pro';
            const priceColor = isPro ? '#f59e0b' : '#a78bfa';
            return (
              <motion.div
                key={plan.id}
                variants={fadeUp()}
                whileHover={{ y: -6 }}
                className="relative rounded-3xl p-7 flex flex-col transition-shadow duration-300"
                data-testid="pricing-plan-card"
                style={
                  plan.highlighted
                    ? {
                        border: '1px solid rgba(139,92,246,0.40)',
                        background: 'linear-gradient(135deg,rgba(124,58,237,0.14) 0%,rgba(109,40,217,0.07) 100%)',
                        boxShadow: '0 0 50px rgba(139,92,246,0.14),0 0 0 1px rgba(139,92,246,0.10)',
                      }
                    : {
                        border: '1px solid rgba(255,255,255,0.08)',
                        background: 'linear-gradient(135deg,rgba(255,255,255,0.04) 0%,rgba(255,255,255,0.01) 100%)',
                      }
                }
              >
                {plan.badge && (
                  <div
                    className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full"
                    style={{
                      fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
                      ...(plan.highlighted
                        ? { background: 'rgba(139,92,246,0.22)', color: '#a78bfa', border: '1px solid rgba(139,92,246,0.30)' }
                        : { background: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.30)' }),
                    }}
                  >
                    {plan.badge}
                  </div>
                )}
                <div className="flex items-center gap-3 mb-5">
                  <div
                    className="w-10 h-10 rounded-xl flex items-center justify-center"
                    style={{ background: isPro ? 'rgba(245,158,11,0.10)' : 'rgba(124,58,237,0.10)' }}
                  >
                    <plan.icon className="w-5 h-5" style={{ color: priceColor }} />
                  </div>
                  <div>
                    <p className="text-white" style={{ fontWeight: 700 }}>{plan.name}</p>
                    <p className="text-xs" style={{ color: 'rgba(255,255,255,0.40)' }}>{plan.credits} · {plan.renewal}</p>
                  </div>
                </div>
                <div className="mb-5">
                  <span style={{ fontSize: '2.2rem', fontWeight: 800, color: priceColor }}>{plan.price}</span>
                  <span className="text-sm ml-1" style={{ color: 'rgba(255,255,255,0.30)' }}>{plan.period}</span>
                  {plan.docAccess && (
                    <p className="text-xs font-medium mt-1.5" style={{ color: isPro ? '#34d399' : plan.highlighted ? '#a78bfa' : '#94a3b8' }}>
                      {plan.docAccess}
                    </p>
                  )}
                </div>
                <ul className="space-y-2.5 mb-8 flex-1">
                  {plan.features.map((feat) => (
                    <li key={feat} className="flex items-center gap-2.5 text-sm">
                      <CheckCircle className="w-4 h-4 flex-shrink-0" style={{ color: '#34d399' }} />
                      <span style={{ color: 'rgba(255,255,255,0.65)' }}>{feat}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  to="/signup"
                  className="w-full flex items-center justify-center gap-2 h-11 rounded-xl text-sm font-bold transition-all hover:opacity-90 active:scale-95"
                  style={
                    plan.highlighted
                      ? { background: 'linear-gradient(to right,#7c3aed,#8b5cf6)', color: '#fff', boxShadow: '0 4px 20px rgba(139,92,246,0.35)' }
                      : { background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.70)', border: '1px solid rgba(255,255,255,0.08)' }
                  }
                  data-testid={`pricing-${plan.id}-cta-button`}
                >
                  {plan.ctaText} <ArrowRight size={16} />
                </Link>
              </motion.div>
            );
          })}
        </motion.div>

        <p className="text-center text-sm mt-8" style={{ color: 'rgba(255,255,255,0.25)' }}>
          Credits don't expire before their validity period · use them at your own pace
        </p>
      </div>
    </section>
  );
}
