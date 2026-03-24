import { Link } from 'react-router-dom';
import { PublicLayout } from '@/components/layout/PublicLayout';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Check, X, Zap, Trophy, Sparkles } from 'lucide-react';
import { DOC_ACCESS_CONFIG } from '@/utils/plans';

const PLANS = [
  {
    id: 'free',
    icon: Zap,
    name: 'Free',
    price: '0',
    period: '/month',
    credits: '30 credits/month',
    docAccess: 'zero',
    description: 'Start exploring, no card needed',
    features: [
      { label: '30 AI credits/month',         included: true  },
      { label: 'All subjects access',         included: true  },
      { label: 'Chat history (limited)',      included: true  },
      { label: 'Zero document access',        included: true  },
      { label: 'Priority responses',          included: false },
      { label: 'Advanced AI models',          included: false },
    ],
    cta: 'Get Started Free',
    ctaLink: '/signup',
    highlighted: false,
  },
  {
    id: 'starter',
    icon: Trophy,
    name: 'Starter',
    price: '99',
    period: ' one-time',
    credits: '300 credits',
    docAccess: 'limited',
    description: 'Best for regular students',
    badge: 'MOST POPULAR',
    features: [
      { label: '300 AI credits',             included: true  },
      { label: 'All subjects access',        included: true  },
      { label: 'Full chat history',          included: true  },
      { label: 'Limited document access',    included: true  },
      { label: 'Priority responses',         included: true  },
      { label: 'Advanced AI models',         included: true  },
    ],
    cta: 'Buy Starter — ₹99',
    ctaLink: '/signup',
    highlighted: true,
  },
  {
    id: 'pro',
    icon: Sparkles,
    name: 'Pro',
    price: '999',
    period: ' one-time',
    credits: '4,000 credits',
    docAccess: 'full',
    description: 'For serious exam prep',
    badge: 'BEST VALUE',
    features: [
      { label: '4,000 AI credits',           included: true  },
      { label: 'Unlimited subjects access',  included: true  },
      { label: 'Unlimited history',          included: true  },
      { label: 'Full document access',       included: true  },
      { label: 'All AI models (fastest)',    included: true  },
      { label: 'Early access to features',   included: true  },
    ],
    cta: 'Go Pro — ₹999',
    ctaLink: '/signup',
    highlighted: false,
  },
];

export default function PricingPage() {
  return (
    <PublicLayout>
      <div className="min-h-screen bg-[#06060e] py-24 px-4">
        {/* Header */}
        <div className="text-center max-w-2xl mx-auto mb-16">
          <Badge className="bg-violet-500/15 text-violet-400 border-violet-500/25 mb-4">
            Simple Pricing
          </Badge>
          <h1 className="text-4xl sm:text-5xl font-semibold text-white mb-4">
            Affordable exam prep
          </h1>
          <p className="text-white/60 text-lg">
            Start free, upgrade when you need more. No subscriptions, no lock-in.
          </p>
        </div>

        {/* Plans */}
        <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-6" data-testid="pricing-page">
          {PLANS.map((plan) => {
            const Icon = plan.icon;
            return (
              <div
                key={plan.id}
                className={`relative rounded-2xl p-6 glass-card ${
                  plan.highlighted
                    ? 'ring-1 ring-violet-500/50 shadow-[0_26px_90px_rgba(124,58,237,0.18)]'
                    : ''
                }`}
                data-testid="pricing-plan-card"
              >
                {plan.badge && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="text-xs font-bold text-violet-300 bg-violet-600/30 border border-violet-500/40 px-3 py-1 rounded-full">
                      {plan.badge}
                    </span>
                  </div>
                )}

                <div className="flex items-center gap-3 mb-4">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                    plan.highlighted ? 'bg-violet-600/20' : 'bg-white/8'
                  }`}>
                    <Icon size={20} className={plan.highlighted ? 'text-violet-400' : 'text-white/60'} />
                  </div>
                  <div>
                    <h3 className="text-white font-semibold">{plan.name}</h3>
                    <p className="text-white/50 text-xs">{plan.description}</p>
                  </div>
                </div>

                <div className="mb-6">
                  <div className="flex items-baseline gap-1">
                    <span className="text-white/50 text-sm">₹</span>
                    <span className="text-4xl font-bold text-white">{plan.price}</span>
                    <span className="text-white/50 text-sm">{plan.period}</span>
                  </div>
                  <p className="text-violet-400 text-sm font-semibold mt-1">{plan.credits}</p>
                  {/* Document access row */}
                  {plan.docAccess && (() => {
                    const da = DOC_ACCESS_CONFIG[plan.docAccess];
                    return da ? (
                      <p className={`text-xs font-medium mt-1 ${da.color}`}>
                        {da.icon} {da.label}
                      </p>
                    ) : null;
                  })()}
                </div>

                <ul className="space-y-3 mb-8">
                  {plan.features.map((feature) => (
                    <li key={feature.label} className="flex items-center gap-2.5">
                      {feature.included ? (
                        <Check size={16} className="text-emerald-400 flex-shrink-0" />
                      ) : (
                        <X size={16} className="text-white/20 flex-shrink-0" />
                      )}
                      <span className={`text-sm ${
                        feature.included ? 'text-white/80' : 'text-white/30'
                      }`}>{feature.label}</span>
                    </li>
                  ))}
                </ul>

                <Link to={plan.ctaLink}>
                  <Button
                    className={`w-full ${
                      plan.highlighted
                        ? 'bg-violet-600 hover:bg-violet-500 text-white shadow-lg shadow-violet-500/25'
                        : 'bg-white/8 hover:bg-white/12 text-white border border-white/15'
                    }`}
                    data-testid={`pricing-${plan.id}-cta-button`}
                  >
                    {plan.cta}
                  </Button>
                </Link>
              </div>
            );
          })}
        </div>

        {/* FAQ */}
        <div className="max-w-2xl mx-auto mt-20">
          <h2 className="text-2xl font-semibold text-white text-center mb-8">FAQs</h2>
          <div className="space-y-4">
            {[
              { q: 'What are credits?', a: 'Each AI response costs 1 credit. Free users get 30 per day. Starter and Pro plans have credits that never expire.' },
              { q: 'Do credits expire?', a: 'Free credits reset daily. Starter and Pro credits are one-time purchases that never expire.' },
              { q: 'Can I upgrade later?', a: 'Yes! You can upgrade anytime. Your existing credits will be preserved.' },
              { q: 'Which AHSEC classes are supported?', a: 'We support both Class 11 and Class 12 for Science (PCM, PCB) and Arts streams.' },
            ].map(({ q, a }) => (
              <div key={q} className="glass-card rounded-xl p-5">
                <h3 className="text-white font-medium mb-2">{q}</h3>
                <p className="text-white/60 text-sm">{a}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </PublicLayout>
  );
}
