import { useNavigate } from 'react-router-dom';
import { PublicLayout } from '@/components/layout/PublicLayout';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Check, X, Zap, Trophy, Sparkles } from 'lucide-react';
import { DOC_ACCESS_CONFIG } from '@/utils/plans';
import { useAuth } from '@/context/AuthContext';

const PLANS = [
  {
    id: 'free',
    icon: Zap,
    name: 'Free',
    price: '0',
    period: 'forever',
    credits: '30 credits/day',
    docAccess: 'zero',
    description: 'Start exploring, no card needed',
    features: [
      { label: '30 AI credits/day',           included: true  },
      { label: '5 messages/min',              included: true  },
      { label: 'All subjects access',         included: true  },
      { label: 'Chat history (limited)',      included: true  },
      { label: 'Zero document access',        included: true  },
      { label: 'Priority responses',          included: false },
      { label: 'Advanced AI models',          included: false },
    ],
    cta: 'Get Started Free',
    ctaPath: '/signup',
    highlighted: false,
    isPaid: false,
  },
  {
    id: 'starter',
    icon: Trophy,
    name: 'Starter',
    price: '99',
    period: 'one-time',
    credits: '500 credits/day',
    docAccess: 'limited',
    description: 'Best for regular students',
    badge: 'MOST POPULAR',
    features: [
      { label: '500 AI credits/day',         included: true  },
      { label: '10 messages/min',            included: true  },
      { label: 'All subjects access',        included: true  },
      { label: 'Full chat history',          included: true  },
      { label: 'Limited document access',    included: true  },
      { label: 'Priority responses',         included: true  },
      { label: 'Advanced AI models',         included: true  },
    ],
    cta: 'Buy Starter — ₹99',
    ctaPath: '/signup',
    highlighted: true,
    isPaid: true,
  },
  {
    id: 'pro',
    icon: Sparkles,
    name: 'Pro',
    price: '999',
    period: 'one-time',
    credits: '4,000 credits/day',
    docAccess: 'full',
    description: 'For serious exam prep',
    badge: 'BEST VALUE',
    features: [
      { label: '4,000 AI credits/day',       included: true  },
      { label: '15 messages/min',            included: true  },
      { label: 'Unlimited subjects access',  included: true  },
      { label: 'Unlimited history',          included: true  },
      { label: 'Full document access',       included: true  },
      { label: 'All AI models (fastest)',    included: true  },
      { label: 'Early access to features',   included: true  },
    ],
    cta: 'Go Pro — ₹999',
    ctaPath: '/signup',
    highlighted: false,
    isPaid: true,
  },
];

export default function PricingPage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const handleCtaClick = (plan) => {
    if (!plan.isPaid) {
      navigate(user ? '/chat' : '/signup');
      return;
    }
    if (user) {
      navigate(`/profile?upgrade=${plan.id}`);
    } else {
      navigate('/signup');
    }
  };

  return (
    <PublicLayout>
      <div className="min-h-screen pt-8 pb-24 px-4">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <Badge className="bg-violet-500/10 text-violet-600 border-violet-500/25 mb-4">
            Simple Pricing
          </Badge>
          <h1 className="text-3xl sm:text-5xl font-semibold text-foreground mb-4">
            Affordable exam prep
          </h1>
          <p className="text-muted-foreground text-lg">
            Start free, upgrade when you need more. No subscriptions, no lock-in.
          </p>
        </div>

        <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6" data-testid="pricing-page">
          {PLANS.map((plan) => {
            const Icon = plan.icon;
            return (
              <div
                key={plan.id}
                className={`relative rounded-2xl p-6 glass-card ${
                  plan.highlighted
                    ? 'ring-1 ring-violet-500/40 shadow-[0_26px_90px_rgba(124,58,237,0.10)]'
                    : ''
                }`}
                data-testid="pricing-plan-card"
              >
                {plan.badge && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <span className="text-xs font-bold text-white bg-violet-600 border border-violet-500/40 px-3 py-1 rounded-full">
                      {plan.badge}
                    </span>
                  </div>
                )}

                <div className="flex items-center gap-3 mb-4">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                    plan.highlighted ? 'bg-violet-600/15' : 'bg-muted'
                  }`}>
                    <Icon size={20} className={plan.highlighted ? 'text-violet-600' : 'text-muted-foreground'} />
                  </div>
                  <div>
                    <h3 className="text-foreground font-semibold">{plan.name}</h3>
                    <p className="text-muted-foreground text-xs">{plan.description}</p>
                  </div>
                </div>

                <div className="mb-6">
                  <div className="flex items-baseline gap-1">
                    <span className="text-muted-foreground text-sm">₹</span>
                    <span className="text-4xl font-bold text-foreground">{plan.price}</span>
                    <span className="text-muted-foreground text-sm">{plan.period}</span>
                  </div>
                  <p className="text-violet-600 text-sm font-semibold mt-1">{plan.credits}</p>
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
                        <Check size={16} className="text-emerald-500 flex-shrink-0" />
                      ) : (
                        <X size={16} className="text-muted-foreground/30 flex-shrink-0" />
                      )}
                      <span className={`text-sm ${
                        feature.included ? 'text-foreground/80' : 'text-muted-foreground/40'
                      }`}>{feature.label}</span>
                    </li>
                  ))}
                </ul>

                <Button
                  onClick={() => handleCtaClick(plan)}
                  className={`w-full ${
                    plan.highlighted
                      ? 'bg-violet-600 hover:bg-violet-500 text-white shadow-lg shadow-violet-500/20'
                      : 'bg-muted hover:bg-muted/80 text-foreground border border-border/30'
                  }`}
                  data-testid={`pricing-${plan.id}-cta-button`}
                >
                  {plan.isPaid && user ? `Upgrade to ${plan.name} →` : plan.cta}
                </Button>
              </div>
            );
          })}
        </div>

        {user && (
          <p className="text-center text-muted-foreground/50 text-sm mt-8">
            Signed in as <span className="text-violet-600">{user.email}</span> — upgrading will activate immediately.
          </p>
        )}

        <div className="max-w-2xl mx-auto mt-20">
          <h2 className="text-2xl font-semibold text-foreground text-center mb-8">FAQs</h2>
          <div className="space-y-4">
            {[
              { q: 'What are credits?', a: 'Each AI response costs 1 credit. Free users get 30/day, Starter 500/day, Pro 4,000/day. All credits reset at midnight UTC.' },
              { q: 'Do credits expire?', a: 'All plan credits reset daily at midnight UTC. You get a fresh allowance every day based on your plan.' },
              { q: 'Can I upgrade later?', a: 'Yes! You can upgrade anytime. Your existing credits will be preserved.' },
              { q: 'Which AHSEC classes are supported?', a: 'We support both Class 11 and Class 12 for Science (PCM, PCB) and Arts streams.' },
            ].map(({ q, a }) => (
              <div key={q} className="glass-card rounded-xl p-5">
                <h3 className="text-foreground font-medium mb-2">{q}</h3>
                <p className="text-muted-foreground text-sm">{a}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </PublicLayout>
  );
}
