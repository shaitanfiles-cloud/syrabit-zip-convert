import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Zap, ArrowRight, Sparkles, CheckCircle, Trophy } from 'lucide-react';
import { fadeUp, staggerContainer } from './shared';
import Reveal from './Reveal';
import GlowOrb from './GlowOrb';

const PLANS = [
  {
    id: 'free', name: 'Free', price: '₹0', period: 'forever', credits: '30/day',
    renewal: '30 credits/day · resets daily', icon: Zap, highlighted: false, badge: null,
    docAccess: '🔒 Zero document access',
    features: ['30 AI credits/day', '5 messages/min', 'All subjects access', 'Chat history (limited)', 'Zero document access'],
    ctaText: 'Get Started Free',
  },
  {
    id: 'starter', name: 'Starter', price: '₹99', period: 'one-time', credits: '500/day',
    renewal: '500 credits/day · resets daily', icon: Trophy, highlighted: true, badge: 'MOST POPULAR',
    docAccess: '📄 Limited document access',
    features: ['500 AI credits/day', '10 messages/min', 'All subjects access', 'Full chat history', 'Limited document access', 'Priority responses'],
    ctaText: 'Buy Starter',
  },
  {
    id: 'pro', name: 'Pro', price: '₹999', period: 'one-time', credits: '4,000/day',
    renewal: '4,000 credits/day · resets daily', icon: Sparkles, highlighted: false, badge: 'BEST VALUE',
    docAccess: '📚 Full document access',
    features: ['4,000 AI credits/day', '15 messages/min', 'Unlimited subjects access', 'Unlimited history', 'Full document access', 'All AI models (fastest)', 'Early access to features'],
    ctaText: 'Go Pro',
  },
];

export default function PricingSection() {
  return (
    <section id="pricing" className="py-28 relative overflow-hidden" style={{ background: 'hsl(var(--muted) / 0.15)' }}>
      <div className="absolute inset-0 pointer-events-none">
        <GlowOrb color="radial-gradient(circle,#7c3aed,transparent)" size={600} x="10%" y="30%" blur={120} opacity={0.05} animRange={20} duration={22} />
      </div>
      <div className="max-w-5xl mx-auto px-5 relative z-10">
        <Reveal className="text-center mb-14">
          <div
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-5"
            style={{ background: 'rgba(124,58,237,0.08)', border: '1px solid rgba(139,92,246,0.18)' }}
          >
            <Zap size={14} className="text-violet-600" />
            <span className="text-xs font-semibold tracking-widest text-violet-600">SIMPLE PRICING</span>
          </div>
          <h2 className="text-foreground mb-4" style={{ fontSize: 'clamp(1.8rem,4vw,2.8rem)', fontWeight: 800, letterSpacing: '-0.02em' }}>
            Start free. Scale as you need.
          </h2>
          <p className="max-w-lg mx-auto text-muted-foreground">
            No subscriptions. No hidden fees. All plans include daily credits that reset at midnight UTC.
          </p>
        </Reveal>

        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
          variants={staggerContainer}
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5"
        >
          {PLANS.map((plan) => {
            const isPro = plan.id === 'pro';
            const priceColor = isPro ? '#d97706' : '#7c3aed';
            return (
              <motion.div
                key={plan.id}
                variants={fadeUp()}
                whileHover={{ y: -6 }}
                className="relative rounded-3xl p-7 flex flex-col transition-shadow duration-300 glass-card"
                data-testid="pricing-plan-card"
                style={
                  plan.highlighted
                    ? {
                        border: '1px solid rgba(139,92,246,0.30)',
                        boxShadow: '0 0 50px rgba(139,92,246,0.08)',
                      }
                    : {}
                }
              >
                {plan.badge && (
                  <div
                    className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full"
                    style={{
                      fontSize: 10, fontWeight: 700, letterSpacing: '0.08em',
                      ...(plan.highlighted
                        ? { background: 'rgba(139,92,246,0.15)', color: '#7c3aed', border: '1px solid rgba(139,92,246,0.25)' }
                        : { background: 'rgba(245,158,11,0.10)', color: '#d97706', border: '1px solid rgba(245,158,11,0.25)' }),
                    }}
                  >
                    {plan.badge}
                  </div>
                )}
                <div className="flex items-center gap-3 mb-5">
                  <div
                    className="w-10 h-10 rounded-xl flex items-center justify-center"
                    style={{ background: isPro ? 'rgba(245,158,11,0.08)' : 'rgba(124,58,237,0.08)' }}
                  >
                    <plan.icon className="w-5 h-5" style={{ color: priceColor }} />
                  </div>
                  <div>
                    <p className="text-foreground" style={{ fontWeight: 700 }}>{plan.name}</p>
                    <p className="text-xs text-muted-foreground">{plan.credits} · {plan.renewal}</p>
                  </div>
                </div>
                <div className="mb-5">
                  <span style={{ fontSize: '2.2rem', fontWeight: 800, color: priceColor }}>{plan.price}</span>
                  <span className="text-sm ml-1 text-muted-foreground/50">{plan.period}</span>
                  {plan.docAccess && (
                    <p className="text-xs font-medium mt-1.5" style={{ color: isPro ? '#059669' : plan.highlighted ? '#7c3aed' : '#64748b' }}>
                      {plan.docAccess}
                    </p>
                  )}
                </div>
                <ul className="space-y-2.5 mb-8 flex-1">
                  {plan.features.map((feat) => (
                    <li key={feat} className="flex items-center gap-2.5 text-sm">
                      <CheckCircle className="w-4 h-4 flex-shrink-0 text-emerald-500" />
                      <span className="text-foreground/70">{feat}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  to="/signup"
                  className="w-full flex items-center justify-center gap-2 h-11 rounded-xl text-sm font-bold transition-all hover:opacity-90 active:scale-95"
                  style={
                    plan.highlighted
                      ? { background: 'linear-gradient(to right,#7c3aed,#8b5cf6)', color: '#fff', boxShadow: '0 4px 20px rgba(139,92,246,0.25)' }
                      : { background: 'hsl(var(--muted) / 0.5)', color: 'hsl(var(--foreground))', border: '1px solid hsl(var(--border))' }
                  }
                  data-testid={`pricing-${plan.id}-cta-button`}
                >
                  {plan.ctaText} <ArrowRight size={16} />
                </Link>
              </motion.div>
            );
          })}
        </motion.div>

        <p className="text-center text-sm mt-8 text-muted-foreground/50">
          All credits reset daily at midnight UTC · fresh allowance every day
        </p>
      </div>
    </section>
  );
}
