import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Zap, ArrowRight, Sparkles, Play,
  BookOpen, Brain, Layers, Clock, BarChart3, Shield,
  GraduationCap, MessageSquare,
  Star, CheckCircle, Hash,
  Users, TrendingUp, Cpu, Trophy,
  Twitter, Github, Mail, Globe,
  ChevronRight,
} from 'lucide-react';
import { PageMeta } from '@/components/PageMeta';
import { PublicNavbar } from '@/components/layout/PublicNavbar';
import { useAuth } from '@/context/AuthContext';
import { LogoMark, LogoFull } from '@/components/Logo';
import { ScrollReveal } from '@/components/ScrollReveal';

/* ─────────────────────────────────────────────
   AnimatedStat — IntersectionObserver counter
   ───────────────────────────────────────────── */
function AnimatedStat({ value, label, icon: Icon }) {
  const [display, setDisplay] = useState('0');
  const ref = useRef(null);
  const animated = useRef(false);

  useEffect(() => {
    const numeric = parseInt(value, 10);
    const suffix = value.replace(String(numeric), '');

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !animated.current) {
          animated.current = true;
          const duration = 1200;
          const steps = Math.min(numeric, 60); // max 60 animation steps
          const intervalMs = duration / steps;
          const increment = Math.max(1, Math.ceil(numeric / steps));
          let current = 0;
          const timer = setInterval(() => {
            current = Math.min(current + increment, numeric);
            setDisplay(String(current) + suffix);
            if (current >= numeric) clearInterval(timer);
          }, intervalMs);
        }
      },
      { threshold: 0.5 }
    );

    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [value]);

  return (
    <div ref={ref} className="flex flex-col items-center gap-2">
      <div
        className="w-12 h-12 rounded-2xl flex items-center justify-center mb-1"
        style={{
          background: 'rgba(124,58,237,0.10)',
          border: '1px solid rgba(139,92,246,0.20)',
        }}
      >
        <Icon className="w-5 h-5" style={{ color: 'hsl(var(--primary))' }} />
      </div>
      <span className="text-white" style={{ fontSize: '2rem', fontWeight: 800 }}>
        {display}
      </span>
      <span className="text-white/40 text-sm">{label}</span>
    </div>
  );
}

/* ─────────────────────────────────────────────
   Static data
   ───────────────────────────────────────────── */
const STATS = [
  { value: '6+',   label: 'Boards+Streams', icon: BookOpen    },
  { value: '42',   label: 'Subjects',        icon: Layers      },
  { value: '500+', label: 'Students',        icon: Users       },
  { value: '3',    label: 'Plans',           icon: TrendingUp  },
];

const FEATURES = [
  {
    icon: Brain,
    title: 'AI-Powered Answers',
    desc: 'Instant, syllabus-grounded answers from an AI tutor trained on AHSEC content — not generic internet data.',
    gradient: 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
    glow: 'rgba(139,92,246,0.25)',
  },
  {
    icon: BookOpen,
    title: 'Structured Subject Library',
    desc: 'Every chapter of Class 11 & 12 organized by board, stream, and subject — so you always know where to start.',
    gradient: 'linear-gradient(135deg,#2563eb,#06b6d4)',
    glow: 'rgba(59,130,246,0.25)',
  },
  {
    icon: Layers,
    title: 'Multi-format Content',
    desc: 'Notes, solved examples, formulas, PYQ insights, and chapter summaries — all formats exam boards love.',
    gradient: 'linear-gradient(135deg,#059669,#22c55e)',
    glow: 'rgba(16,185,129,0.25)',
  },
  {
    icon: Clock,
    title: 'Chat History',
    desc: 'Every conversation auto-saved and searchable. Revisit any explanation without starting over.',
    gradient: 'linear-gradient(135deg,#f97316,#fbbf24)',
    glow: 'rgba(245,158,11,0.25)',
  },
  {
    icon: BarChart3,
    title: 'Credit System',
    desc: 'Transparent usage tracking. Buy Starter (300 credits, ₹99) or Pro (4000 credits, ₹999) — credits never expire.',
    gradient: 'linear-gradient(135deg,#db2777,#f43f5e)',
    glow: 'rgba(244,63,94,0.25)',
  },
  {
    icon: Shield,
    title: 'Secure & Private',
    desc: 'Your study data is encrypted, never sold, and never shared. Study without surveillance.',
    gradient: 'linear-gradient(135deg,#4f46e5,#8b5cf6)',
    glow: 'rgba(99,102,241,0.25)',
  },
];

const SUBJECTS = [
  { emoji: '∑',  name: 'Mathematics',   classLabel: 'Class 11 · PCM',  chapters: 16, gradient: 'linear-gradient(135deg,rgba(124,58,237,0.2),rgba(139,92,246,0.1))',  border: 'rgba(139,92,246,0.20)' },
  { emoji: '⚡', name: 'Physics',       classLabel: 'Class 12 · PCM',  chapters: 14, gradient: 'linear-gradient(135deg,rgba(37,99,235,0.2),rgba(6,182,212,0.1))',    border: 'rgba(59,130,246,0.20)' },
  { emoji: '⚗️', name: 'Chemistry',     classLabel: 'Class 11 · PCM',  chapters: 14, gradient: 'linear-gradient(135deg,rgba(5,150,105,0.2),rgba(34,197,94,0.1))',    border: 'rgba(16,185,129,0.20)' },
  { emoji: '🧬', name: 'Biology',       classLabel: 'Class 12 · PCB',  chapters: 16, gradient: 'linear-gradient(135deg,rgba(22,163,74,0.2),rgba(20,184,166,0.1))',   border: 'rgba(34,197,94,0.20)'  },
  { emoji: '📚', name: 'English Lit.',  classLabel: 'Class 12 · Arts', chapters: 12, gradient: 'linear-gradient(135deg,rgba(217,119,6,0.2),rgba(249,115,22,0.1))',   border: 'rgba(245,158,11,0.20)' },
  { emoji: '🏛️', name: 'History',       classLabel: 'Class 12 · Arts', chapters: 10, gradient: 'linear-gradient(135deg,rgba(190,18,60,0.2),rgba(236,72,153,0.1))',   border: 'rgba(244,63,94,0.20)'  },
];

const STEPS = [
  {
    num: '01',
    title: 'Create your free account',
    desc: 'Sign up in under 30 seconds with email — no credit card needed. Get Starter (300 credits) for ₹99 or Pro (4000 credits) for ₹999.',
    icon: GraduationCap,
  },
  {
    num: '02',
    title: 'Pick your subject',
    desc: 'Browse the library by board, class, and stream. Save subjects you\'re preparing for and jump straight into the material.',
    icon: BookOpen,
  },
  {
    num: '03',
    title: 'Chat with your AI Tutor',
    desc: 'Ask anything. The AI responds with syllabus-grounded answers, worked examples, formulas, and PYQ insights — instantly.',
    icon: MessageSquare,
  },
];

const PLANS = [
  {
    id: 'free',
    name: 'Free',
    price: '₹0',
    period: '/ month',
    credits: '0 credits',
    renewal: 'No credits included',
    icon: Zap,
    highlighted: false,
    badge: null,
    docAccess: '🔒 Zero document access',
    features: ['30 AI credits/month', 'All subjects access', 'Chat history (limited)', 'Zero document access'],
    ctaText: 'Get Started Free',
  },
  {
    id: 'starter',
    name: 'Starter',
    price: '₹99',
    period: 'one-time',
    credits: '300 credits',
    renewal: 'Valid for 1 month',
    icon: Trophy,
    highlighted: true,
    badge: 'MOST POPULAR',
    docAccess: '📄 Limited document access',
    features: ['300 AI credits', 'All subjects access', 'Full chat history', 'Limited document access', 'Priority responses'],
    ctaText: 'Buy Starter',
  },
  {
    id: 'pro',
    name: 'Pro',
    price: '₹999',
    period: 'one-time',
    credits: '4,000 credits',
    renewal: 'Valid for 1 year',
    icon: Sparkles,
    highlighted: false,
    badge: 'BEST VALUE',
    docAccess: '📚 Full document access',
    features: ['4,000 AI credits', 'Unlimited subjects access', 'Unlimited history', 'Full document access', 'All AI models (fastest)', 'Early access to features'],
    ctaText: 'Go Pro',
  },
];

const TESTIMONIALS = [
  {
    name: 'Priya Das',
    classLabel: 'Class 12 · Science (PCM)',
    school: 'Cotton College, Guwahati',
    initials: 'PD',
    gradient: 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
    quote: 'Syrabit.ai made complex Physics concepts crystal clear. I stopped spending hours on textbooks and started getting exam-ready answers in minutes. Scored 94 in my boards!',
  },
  {
    name: 'Rahul Bora',
    classLabel: 'Class 11 · Science (PCB)',
    school: 'HS School, Jorhat',
    initials: 'RB',
    gradient: 'linear-gradient(135deg,#2563eb,#06b6d4)',
    quote: 'The AI explains every step so clearly — better than most teachers. I use it daily for Biology and Chemistry. The credit system is fair; free tier is more than enough to start.',
  },
  {
    name: 'Ankita Gogoi',
    classLabel: 'Class 12 · Arts',
    school: "Handique Girls' College",
    initials: 'AG',
    gradient: 'linear-gradient(135deg,#059669,#14b8a6)',
    quote: 'As an Arts student I was skeptical, but the History PYQ insights are incredible. It knows exactly what topics AHSEC repeats. Wish I had this in Class 11 too!',
  },
];

/* ─────────────────────────────────────────────
   LandingPage
   ───────────────────────────────────────────── */
export default function LandingPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  // Auth redirect
  useEffect(() => {
    if (user) navigate('/library', { replace: true });
  }, [user, navigate]);

  const year = new Date().getFullYear();

  return (
    <div
      className="min-h-screen text-white overflow-x-hidden"
      style={{ background: '#06060e' }}
    >
      <PageMeta />
      <PublicNavbar />

      {/* ══════════════════════════════════════════
          SECTION 1 — HERO
          ══════════════════════════════════════════ */}
      <section
        className="relative min-h-screen flex items-center justify-center pt-16 overflow-hidden"
        data-testid="hero-section"
      >
        {/* Background layers */}
        <div
          className="absolute inset-0 pointer-events-none futuristic-bg"
          style={{
            background: 'radial-gradient(ellipse 80% 50% at 50% -10%, rgba(124,58,237,0.25), transparent)',
          }}
        />
        <div className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full pointer-events-none"
          style={{ background: 'rgba(109,40,217,0.10)', filter: 'blur(120px)' }} />
        <div className="absolute bottom-1/4 right-1/4 w-80 h-80 rounded-full pointer-events-none"
          style={{ background: 'rgba(79,70,229,0.10)', filter: 'blur(100px)' }} />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[300px] rounded-full pointer-events-none"
          style={{ background: 'rgba(124,58,237,0.05)', filter: 'blur(80px)' }} />
        {/* Grid overlay */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            opacity: 0.04,
            backgroundImage:
              'linear-gradient(rgba(139,92,246,1) 1px, transparent 1px), linear-gradient(to right, rgba(139,92,246,1) 1px, transparent 1px)',
            backgroundSize: '60px 60px',
          }}
        />

        {/* Content */}
        <div className="relative z-10 max-w-5xl mx-auto px-5 text-center py-24" style={{ animation: 'fadeIn 0.8s ease-out both' }}>
          {/* Badge pill */}
          <div
            className="inline-flex items-center gap-2 px-4 py-2 rounded-full mb-8"
            style={{
              background: 'rgba(124,58,237,0.10)',
              border: '1px solid rgba(139,92,246,0.25)',
              animation: 'slideUp 0.6s cubic-bezier(0.16,1,0.3,1) both 0.1s',
            }}
          >
            <span
              className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"
              aria-hidden="true"
            />
            <span className="text-sm font-semibold" style={{ color: 'hsl(var(--primary))' }}>
              AHSEC (Class 11–12) &amp; Degree (B.Com · B.A · B.Sc) — Assam
            </span>
          </div>

          {/* Headline */}
          <h1
            className="mb-6"
            style={{ animation: 'slideUp 0.7s cubic-bezier(0.16,1,0.3,1) both 0.2s',
              fontSize: 'clamp(2.4rem, 6vw, 4.5rem)',
              fontWeight: 900,
              lineHeight: 1.1,
            }}
          >
            <span className="shimmer-text">Ace your AHSEC</span>
            <br />
            <span className="text-white">exams with AI</span>
          </h1>

          {/* Subheadline */}
          <p
            className="text-white/50 max-w-2xl mx-auto mb-10 leading-relaxed"
            style={{ fontSize: 'clamp(1rem, 2vw, 1.2rem)', animation: 'slideUp 0.7s cubic-bezier(0.16,1,0.3,1) both 0.35s' }}
          >
            Syrabit.ai is an AI-powered exam prep platform for AHSEC (Class 11–12) and
            Degree students (B.Com, B.A, B.Sc — 2nd &amp; 4th Sem). Get instant,
            syllabus-aligned answers, PYQ insights, and a credit system tailored for Assam students.
          </p>

          {/* CTA buttons */}
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4" style={{ animation: 'slideUp 0.7s cubic-bezier(0.16,1,0.3,1) both 0.5s' }}>
            <Link
              to="/signup"
              className="flex items-center gap-2 text-white transition-all hover:opacity-90 active:scale-95 btn-glow"
              style={{
                height: 52,
                padding: '0 2rem',
                borderRadius: '1rem',
                fontWeight: 700,
                background: 'linear-gradient(to right, #7c3aed, #8b5cf6)',
                boxShadow: '0 6px 30px rgba(139,92,246,0.4), 0 0 0 1px rgba(255,255,255,0.06)',
                fontSize: '1rem',
              }}
              data-testid="landing-hero-primary-cta-button"
            >
              <Sparkles size={20} />
              Start for Free — No Card Needed
            </Link>
            <a
              href="#features"
              className="flex items-center gap-2 text-white/70 hover:text-white transition-all"
              style={{
                height: 52,
                padding: '0 2rem',
                borderRadius: '1rem',
                fontWeight: 600,
                border: '1px solid rgba(255,255,255,0.10)',
                fontSize: '1rem',
              }}
              data-testid="landing-hero-secondary-cta-button"
            >
              <Play size={16} />
              See how it works
            </a>
          </div>

          {/* Trust line */}
          <p className="text-white/25 text-sm mt-8" style={{ animation: 'fadeIn 1s ease-out both 0.7s' }}>
            Free plan · No credits needed to browse · Upgrade from ₹99
          </p>

          {/* Hero mockup card */}
          <div className="mt-16 relative max-w-3xl mx-auto" style={{ animation: 'scaleFadeIn 0.8s cubic-bezier(0.16,1,0.3,1) both 0.6s' }}>
            {/* Glow behind card */}
            <div
              className="absolute inset-0 rounded-3xl scale-95 pointer-events-none"
              style={{ background: 'rgba(124,58,237,0.10)', filter: 'blur(48px)' }}
            />
            {/* Card */}
            <div
              className="relative rounded-3xl overflow-hidden"
              style={{
                border: '1px solid rgba(255,255,255,0.10)',
                background: 'linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%)',
                backdropFilter: 'blur(24px)',
                WebkitBackdropFilter: 'blur(24px)',
                boxShadow: '0 0 0 1px rgba(255,255,255,0.06), 0 32px 80px rgba(0,0,0,0.5)',
              }}
            >
              {/* Fake browser bar */}
              <div
                className="flex items-center gap-2 px-4 py-3 border-b"
                style={{ borderColor: 'rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.02)' }}
              >
                <span className="w-3 h-3 rounded-full" style={{ background: 'rgba(239,68,68,0.6)' }} />
                <span className="w-3 h-3 rounded-full" style={{ background: 'rgba(234,179,8,0.6)' }} />
                <span className="w-3 h-3 rounded-full" style={{ background: 'rgba(34,197,94,0.6)' }} />
                <div
                  className="flex-1 mx-4 h-6 rounded-lg flex items-center px-3"
                  style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                >
                  <span className="text-xs text-white/30">syrabit.ai/chat</span>
                </div>
              </div>

              {/* Fake chat messages */}
              <div className="p-6 space-y-4 text-left">
                {/* Student message */}
                <div className="flex items-start gap-3">
                  <div
                    className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center"
                    style={{
                      background: 'rgba(124,58,237,0.20)',
                      border: '1px solid rgba(139,92,246,0.30)',
                    }}
                  >
                    <GraduationCap size={14} className="text-violet-400" />
                  </div>
                  <div
                    className="px-4 py-3 text-sm text-white/80 max-w-xs rounded-2xl"
                    style={{
                      background: 'rgba(255,255,255,0.06)',
                      borderRadius: '0 1rem 1rem 1rem',
                    }}
                  >
                    Explain the photoelectric effect with the Einstein equation for my AHSEC Class 12 Physics exam.
                  </div>
                </div>

                {/* AI message */}
                <div className="flex items-start gap-3 flex-row-reverse">
                  <div
                    className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center"
                    style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)', flexShrink: 0 }}
                  >
                    <LogoMark size="xs" style={{ filter: 'none' }} />
                  </div>
                  <div
                    className="px-4 py-3 text-sm text-white/90 max-w-sm"
                    style={{
                      background: 'linear-gradient(135deg,rgba(124,58,237,0.20),rgba(109,40,217,0.15))',
                      border: '1px solid rgba(139,92,246,0.20)',
                      borderRadius: '1rem 0 1rem 1rem',
                    }}
                  >
                    <p className="font-semibold mb-1">Photoelectric Effect — AHSEC Class 12</p>
                    <p className="text-white/70 text-xs leading-relaxed mb-2">
                      The photoelectric effect occurs when light strikes a metal surface and ejects electrons.
                      Einstein's equation:
                    </p>
                    <code
                      className="text-xs px-1.5 py-0.5 rounded"
                      style={{ color: 'hsl(var(--primary))', background: 'rgba(139,92,246,0.12)' }}
                    >
                      E = hν = φ + ½mv²
                    </code>
                    <div className="flex items-center gap-2 mt-3">
                      <span
                        className="px-2 py-0.5 rounded-full"
                        style={{
                          fontSize: 10,
                          background: 'rgba(139,92,246,0.20)',
                          color: 'hsl(var(--primary))',
                          border: '1px solid rgba(139,92,246,0.20)',
                        }}
                      >
                        2 credits
                      </span>
                      <span className="text-white/30" style={{ fontSize: 10 }}>Chapter 11 · Wave Optics</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 2 — STATS BAND
          ══════════════════════════════════════════ */}
      <section
        className="py-16"
        style={{ background: 'rgba(255,255,255,0.02)', borderTop: '1px solid rgba(255,255,255,0.06)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}
      >
        <ScrollReveal>
          <div className="max-w-4xl mx-auto px-5 grid grid-cols-2 md:grid-cols-4 gap-8">
            {STATS.map((s) => (
              <AnimatedStat key={s.label} value={s.value} label={s.label} icon={s.icon} />
            ))}
          </div>
        </ScrollReveal>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 3 — FEATURES
          ══════════════════════════════════════════ */}
      <section id="features" className="py-28 max-w-6xl mx-auto px-5">
        {/* Header */}
        <ScrollReveal>
          <div className="text-center mb-14">
            <div
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-5"
              style={{ background: 'rgba(124,58,237,0.10)', border: '1px solid rgba(139,92,246,0.20)' }}
            >
              <Sparkles size={14} style={{ color: 'hsl(var(--primary))' }} />
              <span className="text-xs font-semibold tracking-widest" style={{ color: 'hsl(var(--primary))' }}>
                EVERYTHING YOU NEED
              </span>
            </div>
            <h2
              className="text-white mb-4"
              style={{ fontSize: 'clamp(1.8rem, 4vw, 2.8rem)', fontWeight: 800 }}
            >
              Built for AHSEC. Optimised for results.
            </h2>
            <p className="text-white/40 max-w-xl mx-auto" style={{ fontSize: '1.05rem' }}>
              Every feature is purpose-built for Class 11 &amp; 12 students preparing for the Assam Board exam.
            </p>
          </div>
        </ScrollReveal>

        {/* Cards grid */}
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((f, fi) => (
            <ScrollReveal key={f.title} delay={fi * 0.08}>
            <div
              className="group relative rounded-3xl border border-white/[0.08] p-6 transition-all duration-300 hover:border-white/[0.16] hover:-translate-y-1 hover:shadow-[0_8px_30px_rgba(139,92,246,0.12)]"
              style={{
                background: 'linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)',
                backdropFilter: 'blur(12px)',
                WebkitBackdropFilter: 'blur(12px)',
              }}
            >
              {/* Hover glow overlay */}
              <div
                className="absolute inset-0 rounded-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"
                style={{ background: `radial-gradient(circle at 50% 0%, ${f.glow}, transparent 70%)` }}
              />

              <div
                className="w-11 h-11 rounded-2xl flex items-center justify-center mb-4 relative z-10"
                style={{ background: f.gradient, boxShadow: `0 6px 20px ${f.glow}` }}
              >
                <f.icon className="w-5 h-5 text-white" />
              </div>
              <h3 className="text-white mb-2 relative z-10" style={{ fontWeight: 700, fontSize: '1rem' }}>
                {f.title}
              </h3>
              <p className="text-white/45 text-sm leading-relaxed relative z-10">{f.desc}</p>
            </div>
            </ScrollReveal>
          ))}
        </div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 4 — SUBJECTS PREVIEW
          ══════════════════════════════════════════ */}
      <section className="py-20" style={{ background: 'rgba(255,255,255,0.015)' }}>
        <div className="max-w-6xl mx-auto px-5">
          <ScrollReveal>
            <div className="text-center mb-10">
              <h2
                className="text-white mb-3"
                style={{ fontSize: 'clamp(1.6rem, 4vw, 2.4rem)', fontWeight: 800 }}
              >
                Content covering every subject
              </h2>
              <p className="text-white/40">AHSEC Class 11 &amp; 12 · Science (PCM/PCB) · Arts</p>
            </div>
          </ScrollReveal>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {SUBJECTS.map((s, si) => (
              <ScrollReveal key={s.name} delay={si * 0.06}>
              <div
                className="relative p-5 rounded-2xl border transition-all duration-200 hover:-translate-y-1 hover:shadow-xl cursor-pointer group"
                style={{
                  background: s.gradient,
                  borderColor: s.border,
                  border: `1px solid ${s.border}`,
                }}
              >
                <div className="text-3xl mb-3">{s.emoji}</div>
                <p className="text-white mb-1" style={{ fontWeight: 700 }}>{s.name}</p>
                <p className="text-white/50 text-xs mb-2">{s.classLabel}</p>
                <div className="flex items-center gap-1">
                  <Hash size={12} className="text-white/30" />
                  <span className="text-white/40 text-xs">{s.chapters} chapters</span>
                </div>
                <ChevronRight
                  size={16}
                  className="absolute top-4 right-4 text-white/50 opacity-0 group-hover:opacity-100 transition-opacity"
                />
              </div>
              </ScrollReveal>
            ))}
          </div>

          <div className="text-center mt-8">
            <Link
              to="/signup"
              className="inline-flex items-center gap-1.5 text-sm font-semibold hover:opacity-80 transition-opacity"
              style={{ color: 'hsl(var(--primary))' }}
            >
              View all subjects after sign up
              <ArrowRight size={16} />
            </Link>
          </div>
        </div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 5 — HOW IT WORKS
          ══════════════════════════════════════════ */}
      <section id="how-it-works" className="py-28 max-w-5xl mx-auto px-5">
        {/* Header */}
        <ScrollReveal>
          <div className="text-center mb-14">
            <div
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-5"
              style={{ background: 'rgba(124,58,237,0.10)', border: '1px solid rgba(139,92,246,0.20)' }}
            >
              <Cpu size={14} style={{ color: 'hsl(var(--primary))' }} />
              <span className="text-xs font-semibold tracking-widest" style={{ color: 'hsl(var(--primary))' }}>
                HOW IT WORKS
              </span>
            </div>
            <h2
              className="text-white"
              style={{ fontSize: 'clamp(1.8rem, 4vw, 2.8rem)', fontWeight: 800 }}
            >
              Up and running in 3 steps
            </h2>
          </div>
        </ScrollReveal>

        {/* Steps grid */}
        <div className="grid md:grid-cols-3 gap-8 relative">
          {/* Connector line — desktop only */}
          <div className="connector-line hidden md:block" />

          {STEPS.map((step, i) => (
            <ScrollReveal key={step.num} delay={i * 0.12}>
            <div className="relative flex flex-col items-center text-center">
              <div className="relative mb-6">
                <div
                  className="w-16 h-16 rounded-2xl flex items-center justify-center"
                  style={{
                    background: 'linear-gradient(135deg, rgba(124,58,237,0.20), rgba(109,40,217,0.10))',
                    border: '1px solid rgba(139,92,246,0.25)',
                    boxShadow: '0 0 30px rgba(139,92,246,0.15)',
                  }}
                >
                  <step.icon className="w-7 h-7" style={{ color: 'hsl(var(--primary))' }} />
                </div>
                {/* Step number badge */}
                <div
                  className="absolute -top-2 -right-2 w-6 h-6 rounded-full flex items-center justify-center text-white"
                  style={{
                    background: 'hsl(var(--primary))',
                    fontSize: 10,
                    fontWeight: 800,
                  }}
                >
                  {i + 1}
                </div>
              </div>
              <h3 className="text-white mb-3" style={{ fontWeight: 700, fontSize: '1.05rem' }}>
                {step.title}
              </h3>
              <p className="text-white/45 text-sm leading-relaxed">{step.desc}</p>
            </div>
            </ScrollReveal>
          ))}
        </div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 6 — PRICING PREVIEW
          ══════════════════════════════════════════ */}
      <section id="pricing" className="py-28" style={{ background: 'rgba(255,255,255,0.015)' }}>
        <div className="max-w-5xl mx-auto px-5">
          {/* Header */}
          <ScrollReveal>
            <div className="text-center mb-14">
              <div
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-5"
                style={{ background: 'rgba(124,58,237,0.10)', border: '1px solid rgba(139,92,246,0.20)' }}
              >
                <Zap size={14} style={{ color: 'hsl(var(--primary))' }} />
                <span className="text-xs font-semibold tracking-widest" style={{ color: 'hsl(var(--primary))' }}>
                  SIMPLE PRICING
                </span>
              </div>
              <h2
                className="text-white mb-4"
                style={{ fontSize: 'clamp(1.8rem, 4vw, 2.8rem)', fontWeight: 800 }}
              >
                Start free. Scale as you need.
              </h2>
              <p className="text-white/40 max-w-lg mx-auto">
                No subscriptions. No hidden fees. Buy credits when you need them — they never expire within validity.
              </p>
            </div>
          </ScrollReveal>

          {/* Plan cards */}
          <div className="grid md:grid-cols-3 gap-5">
            {PLANS.map((plan, pi) => {
              const isHighlighted = plan.highlighted;
              const isPro = plan.id === 'pro';
              const priceColor = isPro ? '#f59e0b' : 'hsl(var(--primary))';

              return (
                <ScrollReveal key={plan.id} delay={pi * 0.1}>
                <div
                  className="relative rounded-3xl p-7 flex flex-col transition-all duration-200 hover:-translate-y-1 hover:shadow-[0_8px_30px_rgba(139,92,246,0.12)]"
                  style={
                    isHighlighted
                      ? {
                          border: '1px solid rgba(139,92,246,0.4)',
                          background: 'linear-gradient(135deg, rgba(124,58,237,0.12) 0%, rgba(109,40,217,0.06) 100%)',
                          boxShadow: '0 0 40px rgba(139,92,246,0.12), 0 0 0 1px rgba(139,92,246,0.10)',
                        }
                      : {
                          border: '1px solid rgba(255,255,255,0.08)',
                          background: 'linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)',
                        }
                  }
                  data-testid="pricing-plan-card"
                >
                  {/* Badge */}
                  {plan.badge && (
                    <div
                      className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full"
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: '0.08em',
                        ...(isHighlighted
                          ? { background: 'rgba(139,92,246,0.2)', color: 'hsl(var(--primary))', border: '1px solid rgba(139,92,246,0.3)' }
                          : { background: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.3)' }),
                      }}
                    >
                      {plan.badge}
                    </div>
                  )}

                  {/* Header row */}
                  <div className="flex items-center gap-3 mb-5">
                    <div
                      className="w-10 h-10 rounded-xl flex items-center justify-center"
                      style={{ background: isPro ? 'rgba(245,158,11,0.10)' : 'rgba(124,58,237,0.10)' }}
                    >
                      <plan.icon
                        className="w-5 h-5"
                        style={{ color: isPro ? '#f59e0b' : 'hsl(var(--primary))' }}
                      />
                    </div>
                    <div>
                      <p className="text-white" style={{ fontWeight: 700 }}>{plan.name}</p>
                      <p className="text-white/40 text-xs">{plan.credits} · {plan.renewal}</p>
                    </div>
                  </div>

                  {/* Price */}
                  <div className="mb-5">
                    <span style={{ fontSize: '2.2rem', fontWeight: 800, color: priceColor }}>
                      {plan.price}
                    </span>
                    <span className="text-white/30 text-sm ml-1">{plan.period}</span>
                    {/* Document access */}
                    {plan.docAccess && (
                      <p className="text-xs font-medium mt-1.5" style={{ color: isPro ? '#34d399' : isHighlighted ? '#a78bfa' : '#94a3b8' }}>
                        {plan.docAccess}
                      </p>
                    )}
                  </div>

                  {/* Features */}
                  <ul className="space-y-2.5 mb-8 flex-1">
                    {plan.features.map((feat) => (
                      <li key={feat} className="flex items-center gap-2.5 text-sm">
                        <CheckCircle className="w-4 h-4 flex-shrink-0" style={{ color: '#34d399' }} />
                        <span className="text-white/65">{feat}</span>
                      </li>
                    ))}
                  </ul>

                  {/* CTA */}
                  <Link
                    to="/signup"
                    className="w-full flex items-center justify-center gap-2 h-11 rounded-xl text-sm font-bold transition-all hover:opacity-90 active:scale-95"
                    style={
                      isHighlighted
                        ? {
                            background: 'linear-gradient(to right, #7c3aed, #8b5cf6)',
                            color: '#fff',
                            boxShadow: '0 4px 20px rgba(139,92,246,0.35)',
                          }
                        : {
                            background: 'rgba(255,255,255,0.06)',
                            color: 'rgba(255,255,255,0.7)',
                            border: '1px solid rgba(255,255,255,0.08)',
                          }
                    }
                    data-testid={`pricing-${plan.id}-cta-button`}
                  >
                    {plan.ctaText}
                    <ArrowRight size={16} />
                  </Link>
                </div>
                </ScrollReveal>
              );
            })}
          </div>

          <p className="text-center text-white/25 text-sm mt-8">
            Credits don't expire before their validity period · use them at your own pace
          </p>
        </div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 7 — TESTIMONIALS
          ══════════════════════════════════════════ */}
      <section className="py-28 max-w-5xl mx-auto px-5">
        <ScrollReveal>
          <div className="text-center mb-14">
            <h2
              className="text-white mb-3"
              style={{ fontSize: 'clamp(1.8rem, 4vw, 2.8rem)', fontWeight: 800 }}
            >
              Students love Syrabit.ai
            </h2>
            <p className="text-white/40">Real feedback from AHSEC students across Assam</p>
          </div>
        </ScrollReveal>

        <div className="grid md:grid-cols-3 gap-5">
          {TESTIMONIALS.map((t, ti) => (
            <ScrollReveal key={t.name} delay={ti * 0.1}>
            <div
              className="relative rounded-3xl border border-white/[0.08] p-6 flex flex-col gap-4 transition-all duration-200 hover:-translate-y-1 hover:shadow-[0_8px_30px_rgba(139,92,246,0.08)]"
              style={{
                background: 'linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)',
              }}
            >
              {/* Stars */}
              <div className="flex items-center gap-0.5">
                {[...Array(5)].map((_, i) => (
                  <Star key={i} className="w-4 h-4 fill-amber-400 text-amber-400" />
                ))}
              </div>

              {/* Quote */}
              <p className="text-white/65 text-sm leading-relaxed flex-1">
                "{t.quote}"
              </p>

              {/* Author */}
              <div
                className="flex items-center gap-3 pt-1 border-t"
                style={{ borderColor: 'rgba(255,255,255,0.08)' }}
              >
                <div
                  className="w-9 h-9 rounded-full flex items-center justify-center text-white flex-shrink-0"
                  style={{
                    background: t.gradient,
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  {t.initials}
                </div>
                <div>
                  <p className="text-white text-sm font-semibold">{t.name}</p>
                  <p className="text-white/35 text-xs">{t.classLabel}</p>
                </div>
              </div>
            </div>
            </ScrollReveal>
          ))}
        </div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 8 — FINAL CTA
          ══════════════════════════════════════════ */}
      <section className="py-28 relative overflow-hidden">
        {/* Violet blur orb */}
        <div
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[300px] rounded-full pointer-events-none"
          style={{ background: 'rgba(124,58,237,0.10)', filter: 'blur(100px)' }}
        />

        <ScrollReveal className="relative z-10 max-w-2xl mx-auto px-5 text-center">
          {/* Pulsing logo mark */}
          <div className="flex justify-center mb-8">
            <LogoMark size="lg" className="anim-pulse anim-float" />
          </div>

          <h2
            className="text-white mb-4"
            style={{ fontSize: 'clamp(2rem, 4vw, 3rem)', fontWeight: 900 }}
          >
            Ready to ace your boards?
          </h2>
          <p className="text-white/45 mb-10 text-lg">
            Join hundreds of AHSEC students who study smarter with Syrabit.ai. Free forever — no credit card required.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              to="/signup"
              className="flex items-center gap-2 text-white transition-all hover:opacity-90 active:scale-95"
              style={{
                height: 56,
                padding: '0 2.5rem',
                borderRadius: '1rem',
                fontWeight: 700,
                fontSize: '1.125rem',
                background: 'linear-gradient(to right, #7c3aed, #8b5cf6)',
                boxShadow: '0 8px 40px rgba(139,92,246,0.4)',
              }}
              data-testid="landing-final-cta-button"
            >
              <Sparkles size={20} />
              Create Free Account
            </Link>
            <Link
              to="/pricing"
              className="flex items-center gap-2 text-white/60 hover:text-white transition-all"
              style={{
                height: 56,
                padding: '0 2rem',
                borderRadius: '1rem',
                fontWeight: 600,
                fontSize: '1rem',
                border: '1px solid rgba(255,255,255,0.10)',
              }}
            >
              View all plans
              <ChevronRight size={18} />
            </Link>
          </div>
        </ScrollReveal>
      </section>

      {/* ══════════════════════════════════════════
          FOOTER
          ══════════════════════════════════════════ */}
      <footer
        className="border-t py-12"
        style={{
          borderColor: 'rgba(255,255,255,0.06)',
          background: 'rgba(0,0,0,0.3)',
        }}
      >
        <div className="max-w-6xl mx-auto px-5">
          {/* 4-column grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-12">
            {/* Brand */}
            <div className="col-span-2 md:col-span-1 space-y-4">
              <LogoFull size="sm" textClassName="text-white" />
              <p className="text-white/30 text-sm leading-relaxed">
                AI-powered exam prep for AHSEC &amp; Degree students in Assam. Class 11–12 + B.Com, B.A, B.Sc.
              </p>
              <div className="flex items-center gap-2">
                {[
                  { icon: Twitter, label: 'Twitter' },
                  { icon: Github, label: 'GitHub' },
                  { icon: Mail, label: 'Email' },
                ].map(({ icon: Icon, label }) => (
                  <button
                    key={label}
                    aria-label={label}
                    className="w-8 h-8 rounded-lg flex items-center justify-center text-white/40 hover:text-white hover:bg-white/10 transition-all"
                    style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                  >
                    <Icon size={16} />
                  </button>
                ))}
              </div>
            </div>

            {/* Product */}
            <div className="space-y-3">
              <p className="text-white/60 text-xs font-bold tracking-[0.1em]">PRODUCT</p>
              {['Features', 'Pricing', 'Subjects', 'Chat'].map((item) => (
                <a
                  key={item}
                  href={item === 'Features' ? '/#features' : item === 'Pricing' ? '/pricing' : '#'}
                  className="block text-sm text-white/35 hover:text-white/70 transition-colors"
                >
                  {item}
                </a>
              ))}
            </div>

            {/* Legal */}
            <div className="space-y-3">
              <p className="text-white/60 text-xs font-bold tracking-[0.1em]">LEGAL</p>
              <Link to="/privacy" className="block text-sm text-white/35 hover:text-white/70 transition-colors">
                Privacy Policy
              </Link>
              <Link to="/terms" className="block text-sm text-white/35 hover:text-white/70 transition-colors">
                Terms of Service
              </Link>
            </div>

            {/* Contact */}
            <div className="space-y-3">
              <p className="text-white/60 text-xs font-bold tracking-[0.1em]">CONTACT</p>
              <div className="flex items-center gap-1.5 text-sm text-white/35">
                <Mail size={14} />
                <span>support@syrabit.ai</span>
              </div>
              <div className="flex items-center gap-1.5 text-sm text-white/35">
                <Globe size={14} />
                <span>syrabit.ai</span>
              </div>
              {/* Hidden admin link */}
              <div className="mt-4">
                <Link
                  to="/admin/login"
                  className="text-xs hover:text-white/35 transition-colors"
                  style={{ color: 'rgba(255,255,255,0.15)' }}
                >
                  Admin Portal →
                </Link>
              </div>
            </div>
          </div>

          {/* Copyright bar */}
          <div
            className="border-t pt-6 flex flex-col md:flex-row items-center justify-between gap-3"
            style={{ borderColor: 'rgba(255,255,255,0.06)' }}
          >
            <p className="text-white/20 text-xs">
              © {year} Syrabit.ai · Built for AHSEC &amp; Degree students in Assam, India
            </p>
            <p className="text-white/15 text-xs">
              Made with ♥ for Class 11 &amp; 12 exam warriors
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
