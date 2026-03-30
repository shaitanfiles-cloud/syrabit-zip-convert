import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { motion, useReducedMotion, AnimatePresence } from 'framer-motion';
import {
  Zap, ArrowRight, Sparkles, Play,
  BookOpen, Brain, Layers, Clock, BarChart3, Shield,
  GraduationCap, MessageSquare,
  Star, CheckCircle, Hash,
  Users, TrendingUp, Cpu, Trophy,
  Twitter, Github, Mail, Globe,
  ChevronRight,
} from 'lucide-react';
import PageMeta from '@/components/seo/PageMeta';
import { PublicNavbar } from '@/components/layout/PublicNavbar';
import { useAuth } from '@/context/AuthContext';
import { LogoMark, LogoFull } from '@/components/Logo';

/* ─────────────────────────────────────────────
   Variants
   ───────────────────────────────────────────── */
const fadeUp = (delay = 0) => ({
  hidden:  { opacity: 0, y: 28 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.7, ease: [0.16, 1, 0.3, 1], delay } },
});

const fadeIn = (delay = 0) => ({
  hidden:  { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.6, ease: 'easeOut', delay } },
});

const scaleIn = (delay = 0) => ({
  hidden:  { opacity: 0, scale: 0.92 },
  visible: { opacity: 1, scale: 1, transition: { duration: 0.8, ease: [0.16, 1, 0.3, 1], delay } },
});

const staggerContainer = {
  hidden:  {},
  visible: { transition: { staggerChildren: 0.08 } },
};

/* ─────────────────────────────────────────────
   FloatingParticles — hero background dots
   ───────────────────────────────────────────── */
function FloatingParticles() {
  const reduced = useReducedMotion();
  if (reduced) return null;

  const particles = Array.from({ length: 28 }, (_, i) => ({
    id: i,
    x: Math.random() * 100,
    y: Math.random() * 100,
    size: Math.random() * 3 + 1,
    duration: Math.random() * 12 + 10,
    delay: Math.random() * 5,
    opacity: Math.random() * 0.35 + 0.05,
  }));

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {particles.map((p) => (
        <motion.div
          key={p.id}
          className="absolute rounded-full"
          style={{
            left: `${p.x}%`,
            top: `${p.y}%`,
            width: p.size,
            height: p.size,
            background: `rgba(139,92,246,${p.opacity})`,
          }}
          animate={{
            y: [0, -40, 0],
            x: [0, Math.random() * 20 - 10, 0],
            opacity: [p.opacity, p.opacity * 2.5, p.opacity],
          }}
          transition={{
            duration: p.duration,
            delay: p.delay,
            repeat: Infinity,
            ease: 'easeInOut',
          }}
        />
      ))}
    </div>
  );
}

/* ─────────────────────────────────────────────
   GlowOrb — reusable animated glow blob
   ───────────────────────────────────────────── */
function GlowOrb({ color, size, x, y, blur, opacity = 0.18, animRange = 30, duration = 14 }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className="absolute rounded-full pointer-events-none"
      style={{
        width: size,
        height: size,
        left: x,
        top: y,
        background: color,
        filter: `blur(${blur}px)`,
        opacity,
      }}
      animate={reduced ? {} : {
        x: [0, animRange, -animRange / 2, 0],
        y: [0, -animRange / 2, animRange, 0],
        scale: [1, 1.08, 0.96, 1],
      }}
      transition={{
        duration,
        repeat: Infinity,
        ease: 'easeInOut',
      }}
    />
  );
}

/* ─────────────────────────────────────────────
   AnimatedStat
   ───────────────────────────────────────────── */
function AnimatedStat({ value, label, icon: Icon }) {
  const [display, setDisplay] = useState('0');
  const ref = useRef(null);
  const animated = useRef(false);

  useEffect(() => {
    const strValue = String(value);
    const numeric = parseInt(strValue, 10);
    const suffix = strValue.replace(String(numeric), '');
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !animated.current) {
        animated.current = true;
        const duration = 1200;
        const steps = Math.min(numeric, 60);
        const intervalMs = duration / steps;
        const increment = Math.max(1, Math.ceil(numeric / steps));
        let current = 0;
        const timer = setInterval(() => {
          current = Math.min(current + increment, numeric);
          setDisplay(String(current) + suffix);
          if (current >= numeric) clearInterval(timer);
        }, intervalMs);
      }
    }, { threshold: 0.5 });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [value]);

  return (
    <div ref={ref} className="flex flex-col items-center gap-2">
      <motion.div
        whileHover={{ scale: 1.08 }}
        className="w-12 h-12 rounded-2xl flex items-center justify-center mb-1"
        style={{
          background: 'rgba(124,58,237,0.12)',
          border: '1px solid rgba(139,92,246,0.22)',
          boxShadow: '0 0 20px rgba(139,92,246,0.12)',
        }}
      >
        <Icon className="w-5 h-5" style={{ color: '#a78bfa' }} />
      </motion.div>
      <span className="text-white" style={{ fontSize: '2rem', fontWeight: 800 }}>{display}</span>
      <span className="text-white/40 text-sm">{label}</span>
    </div>
  );
}

/* ─────────────────────────────────────────────
   ScrollReveal — Framer Motion version
   ───────────────────────────────────────────── */
function Reveal({ children, delay = 0, className = '' }) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: '-60px' }}
      variants={fadeUp(delay)}
    >
      {children}
    </motion.div>
  );
}

/* ─────────────────────────────────────────────
   Static data
   ───────────────────────────────────────────── */
const STATS = [
  { value: '3',    label: 'AssamBoard Divisions', icon: BookOpen   },
  { value: '500+', label: 'Students',              icon: Users      },
  { value: '3',    label: 'Plans',                 icon: TrendingUp },
];

const FEATURES = [
  {
    icon: Brain,
    title: 'AI-Powered Answers',
    desc: 'Browse and ask questions on any chapter — get instant, syllabus-grounded answers based on AssamBoard content, not generic internet data.',
    gradient: 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
    glow: 'rgba(139,92,246,0.28)',
    border: 'rgba(139,92,246,0.20)',
  },
  {
    icon: BookOpen,
    title: 'Structured Subject Browser',
    desc: 'Every chapter across AssamBoard divisions (AHSEC, DEGREE, SEBA) organized by class and stream — so you always know where to start.',
    gradient: 'linear-gradient(135deg,#2563eb,#06b6d4)',
    glow: 'rgba(59,130,246,0.28)',
    border: 'rgba(59,130,246,0.20)',
  },
  {
    icon: Layers,
    title: 'Multi-format Content',
    desc: 'Notes, solved examples, formulas, PYQ insights, and chapter summaries — all formats exam boards love.',
    gradient: 'linear-gradient(135deg,#059669,#22c55e)',
    glow: 'rgba(16,185,129,0.28)',
    border: 'rgba(16,185,129,0.20)',
  },
  {
    icon: Clock,
    title: 'Chat History',
    desc: 'Every conversation auto-saved and searchable. Revisit any explanation without starting over.',
    gradient: 'linear-gradient(135deg,#f97316,#fbbf24)',
    glow: 'rgba(245,158,11,0.28)',
    border: 'rgba(245,158,11,0.20)',
  },
  {
    icon: BarChart3,
    title: 'Credit System',
    desc: 'Transparent usage tracking. Buy Starter (300 credits, ₹99) or Pro (4000 credits, ₹999) — credits never expire.',
    gradient: 'linear-gradient(135deg,#db2777,#f43f5e)',
    glow: 'rgba(244,63,94,0.28)',
    border: 'rgba(244,63,94,0.20)',
  },
  {
    icon: Shield,
    title: 'Secure & Private',
    desc: 'Your study data is encrypted, never sold, and never shared. Study without surveillance.',
    gradient: 'linear-gradient(135deg,#4f46e5,#8b5cf6)',
    glow: 'rgba(99,102,241,0.28)',
    border: 'rgba(99,102,241,0.20)',
  },
];


const STEPS = [
  { num: '01', title: 'Create your free account',   desc: 'Sign up in under 30 seconds with email — no credit card needed. Get Starter (300 credits) for ₹99 or Pro (4000 credits) for ₹999.', icon: GraduationCap },
  { num: '02', title: 'Pick your subject',           desc: "Browse the library by board, class, and stream. Save subjects you're preparing for and jump straight into the material.",             icon: BookOpen      },
  { num: '03', title: 'Ask Syra — your study companion', desc: 'Ask anything about your syllabus. Syra responds with grounded answers, worked examples, formulas, and PYQ insights — instantly.', icon: MessageSquare },
];

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

const TESTIMONIALS = [
  {
    name: 'Priya Das', classLabel: 'Class 12 · Science (PCM)', school: 'Cotton College, Guwahati',
    initials: 'PD', gradient: 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
    quote: 'Syrabit.ai made complex Physics concepts crystal clear. I stopped spending hours on textbooks and started getting exam-ready answers in minutes. Scored 94 in my boards!',
  },
  {
    name: 'Rahul Bora', classLabel: 'Class 11 · Science (PCB)', school: 'HS School, Jorhat',
    initials: 'RB', gradient: 'linear-gradient(135deg,#2563eb,#06b6d4)',
    quote: 'The AI explains every step so clearly — better than most teachers. I use it daily for Biology and Chemistry. The credit system is fair; free tier is more than enough to start.',
  },
  {
    name: 'Ankita Gogoi', classLabel: 'Class 12 · Arts', school: "Handique Girls' College",
    initials: 'AG', gradient: 'linear-gradient(135deg,#059669,#14b8a6)',
    quote: 'As an Arts student I was skeptical, but the History PYQ insights are incredible. It knows exactly what topics AHSEC repeats. Wish I had this in Class 11 too!',
  },
];

/* ─────────────────────────────────────────────
   LandingPage
   ───────────────────────────────────────────── */
export default function LandingPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  // Redirect logged-in users to the library
  useEffect(() => {
    if (user) navigate('/library', { replace: true });
  }, [user, navigate]);

  const year = new Date().getFullYear();

  return (
    <div className="min-h-screen text-white overflow-x-hidden" style={{ background: '#06060e' }}>
      <PageMeta
        title="Syrabit.ai — Educational Browser For AssamBoard Students"
        description="Syrabit.ai is the educational browser for AssamBoard students. Browse AHSEC Class 11-12, Degree (B.Com, B.A, B.Sc), and SEBA syllabus content, get instant answers, PYQs, notes, and MCQs — free to start. Trusted by 500+ students."
        url="https://syrabit.ai/"
        keywords="AssamBoard educational browser, AHSEC study app, SEBA study tool, Class 11 12 exam prep, AHSEC syllabus browser, degree exam prep Assam, B.Com B.A B.Sc notes, AssamBoard 2025 study tool, free educational browser India"
      />
      <PublicNavbar />


      {/* ══════════════════════════════════════════
          SECTION 1 — HERO
          ══════════════════════════════════════════ */}
      <section className="relative min-h-screen flex items-center justify-center pt-16 overflow-hidden">

        {/* ── Grid overlay ── */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            opacity: 0.035,
            backgroundImage: 'linear-gradient(rgba(139,92,246,1) 1px,transparent 1px),linear-gradient(to right,rgba(139,92,246,1) 1px,transparent 1px)',
            backgroundSize: '60px 60px',
          }}
        />

        {/* ── Top vignette radial ── */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{ background: 'radial-gradient(ellipse 80% 50% at 50% -5%,rgba(124,58,237,0.20),transparent)' }}
        />

        {/* ── Content ── */}
        <div className="relative z-10 max-w-5xl mx-auto px-5 text-center py-24">

          {/* Badge */}
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full mb-8"
            style={{
              background: 'rgba(124,58,237,0.12)',
              border: '1px solid rgba(139,92,246,0.30)',
              boxShadow: '0 0 20px rgba(139,92,246,0.12)',
            }}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
            <span className="text-xs font-semibold tracking-widest" style={{ color: '#a78bfa' }}>
              AI-POWERED EXAM PREP FOR ASSAMBOARD STUDENTS
            </span>
          </motion.div>

          {/* Headline */}
          <motion.h1
            initial={{ opacity: 0, y: 32 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1], delay: 0.2 }}
            className="mb-6"
            style={{ fontSize: 'clamp(2.5rem,6.5vw,5rem)', fontWeight: 900, lineHeight: 1.06, letterSpacing: '-0.03em' }}
          >
            <span className="text-white">Educational Browser For </span>
            <span style={{
              background: 'linear-gradient(135deg,#c4b5fd 0%,#a78bfa 40%,#7c3aed 80%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
              filter: 'drop-shadow(0 0 30px rgba(139,92,246,0.30))',
            }}>
              AssamBoard Students
            </span>
          </motion.h1>

          {/* Subheadline */}
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.35 }}
            className="max-w-2xl mx-auto mb-10 leading-relaxed"
            style={{ fontSize: 'clamp(1rem,2vw,1.18rem)', color: 'rgba(255,255,255,0.50)', letterSpacing: '0.01em' }}
          >
            Syrabit gives AssamBoard students (AHSEC, DEGREE &amp; SEBA) instant, syllabus-aligned AI answers,
            PYQ insights, and structured subject notes — all in one place.
          </motion.p>

          {/* CTA buttons */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.48 }}
            className="flex flex-col sm:flex-row items-center justify-center gap-4"
          >
            <motion.div whileHover={{ scale: 1.04, y: -3 }} whileTap={{ scale: 0.97 }}>
              <Link
                to="/signup"
                className="flex items-center gap-2.5 text-white font-bold btn-gradient"
                style={{
                  height: 54,
                  padding: '0 2.25rem',
                  borderRadius: '1rem',
                  fontSize: '1rem',
                  boxShadow: '0 8px 36px rgba(139,92,246,0.50), 0 0 0 1px rgba(255,255,255,0.08) inset',
                }}
                data-testid="landing-hero-primary-cta-button"
              >
                <Sparkles size={18} />
                Start for Free — No Card Needed
              </Link>
            </motion.div>
            <motion.div whileHover={{ scale: 1.03, y: -2 }} whileTap={{ scale: 0.97 }}>
              <a
                href="#features"
                className="flex items-center gap-2.5 font-semibold transition-all duration-200 hover:border-white/22 hover:bg-white/[0.07]"
                style={{
                  height: 54,
                  padding: '0 2.25rem',
                  borderRadius: '1rem',
                  fontSize: '1rem',
                  color: 'rgba(255,255,255,0.68)',
                  border: '1px solid rgba(255,255,255,0.14)',
                  background: 'rgba(255,255,255,0.05)',
                  backdropFilter: 'blur(8px)',
                }}
                data-testid="landing-hero-secondary-cta-button"
              >
                <Play size={15} />
                See how it works
              </a>
            </motion.div>
          </motion.div>

          {/* Trust line */}
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.7 }}
            className="text-sm mt-7"
            style={{ color: 'rgba(255,255,255,0.22)' }}
          >
            Free plan · No credits needed to browse · Upgrade from ₹99
          </motion.p>

          {/* Hero mockup card */}
          <motion.div
            initial={{ opacity: 0, y: 48, scale: 0.94 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 1, ease: [0.16, 1, 0.3, 1], delay: 0.6 }}
            className="mt-16 relative max-w-3xl mx-auto"
          >
            {/* Glow behind card */}
            <div
              className="absolute -inset-4 rounded-3xl pointer-events-none"
              style={{ background: 'rgba(124,58,237,0.14)', filter: 'blur(60px)' }}
            />
            {/* Card */}
            <motion.div
              className="relative rounded-3xl overflow-hidden"
              style={{
                border: '1px solid rgba(255,255,255,0.10)',
                background: 'linear-gradient(135deg,rgba(255,255,255,0.06) 0%,rgba(255,255,255,0.02) 100%)',
                backdropFilter: 'blur(24px)',
                WebkitBackdropFilter: 'blur(24px)',
                boxShadow: '0 0 0 1px rgba(255,255,255,0.06),0 32px 80px rgba(0,0,0,0.55)',
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
                  <span className="text-xs" style={{ color: 'rgba(255,255,255,0.30)' }}>{window.location.hostname}/chat</span>
                </div>
              </div>

              {/* Chat messages */}
              <div className="p-6 space-y-4 text-left">
                <div className="flex items-start gap-3">
                  <div
                    className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center"
                    style={{ background: 'rgba(124,58,237,0.20)', border: '1px solid rgba(139,92,246,0.30)' }}
                  >
                    <GraduationCap size={14} className="text-violet-400" />
                  </div>
                  <div
                    className="px-4 py-3 text-sm max-w-xs"
                    style={{ background: 'rgba(255,255,255,0.06)', borderRadius: '0 1rem 1rem 1rem', color: 'rgba(255,255,255,0.80)' }}
                  >
                    Explain the photoelectric effect with the Einstein equation for my AHSEC Class 12 Physics exam.
                  </div>
                </div>
                <div className="flex items-start gap-3 flex-row-reverse">
                  <div
                    className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center"
                    style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' }}
                  >
                    <LogoMark size="xs" style={{ filter: 'none' }} />
                  </div>
                  <div
                    className="px-4 py-3 text-sm max-w-sm"
                    style={{
                      background: 'linear-gradient(135deg,rgba(124,58,237,0.22),rgba(109,40,217,0.16))',
                      border: '1px solid rgba(139,92,246,0.22)',
                      borderRadius: '1rem 0 1rem 1rem',
                    }}
                  >
                    <p className="font-semibold mb-1 text-white">Photoelectric Effect — AHSEC Class 12</p>
                    <p className="text-xs leading-relaxed mb-2" style={{ color: 'rgba(255,255,255,0.68)' }}>
                      The photoelectric effect occurs when light strikes a metal surface and ejects electrons. Einstein's equation:
                    </p>
                    <code
                      className="text-xs px-1.5 py-0.5 rounded"
                      style={{ color: '#a78bfa', background: 'rgba(139,92,246,0.14)' }}
                    >
                      E = hν = φ + ½mv²
                    </code>
                    <div className="flex items-center gap-2 mt-3">
                      <span
                        className="px-2 py-0.5 rounded-full"
                        style={{ fontSize: 10, background: 'rgba(139,92,246,0.20)', color: '#a78bfa', border: '1px solid rgba(139,92,246,0.22)' }}
                      >
                        2 credits
                      </span>
                      <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.30)' }}>Chapter 11 · Wave Optics</span>
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 2 — STATS BAND
          ══════════════════════════════════════════ */}
      <section
        className="py-16"
        style={{
          background: 'rgba(255,255,255,0.025)',
          borderTop: '1px solid rgba(255,255,255,0.06)',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
          variants={staggerContainer}
          className="max-w-4xl mx-auto px-5 grid grid-cols-2 md:grid-cols-4 gap-8"
        >
          {STATS.map((s, i) => (
            <motion.div key={s.label} variants={fadeUp(i * 0.07)}>
              <AnimatedStat value={s.value} label={s.label} icon={s.icon} />
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 3 — FEATURES
          ══════════════════════════════════════════ */}
      <section id="features" className="py-28 max-w-6xl mx-auto px-5">
        <Reveal className="text-center mb-14">
          <div
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-5"
            style={{ background: 'rgba(124,58,237,0.10)', border: '1px solid rgba(139,92,246,0.22)' }}
          >
            <Sparkles size={14} style={{ color: '#a78bfa' }} />
            <span className="text-xs font-semibold tracking-widest" style={{ color: '#a78bfa' }}>
              EVERYTHING YOU NEED
            </span>
          </div>
          <h2 className="text-white mb-4" style={{ fontSize: 'clamp(1.8rem,4vw,2.8rem)', fontWeight: 800, letterSpacing: '-0.02em' }}>
            Built for AssamBoard. Optimised for results.
          </h2>
          <p className="max-w-xl mx-auto" style={{ fontSize: '1.05rem', color: 'rgba(255,255,255,0.40)' }}>
            Every feature is purpose-built for AHSEC, DEGREE, and SEBA students preparing for their AssamBoard exams.
          </p>
        </Reveal>

        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
          variants={staggerContainer}
          className="grid md:grid-cols-2 lg:grid-cols-3 gap-5"
        >
          {FEATURES.map((f) => (
            <motion.div
              key={f.title}
              variants={fadeUp()}
              whileHover={{ y: -6, boxShadow: `0 12px 40px ${f.glow}` }}
              className="group relative rounded-3xl p-6 cursor-default transition-shadow duration-300"
              style={{
                border: `1px solid ${f.border}`,
                background: 'linear-gradient(135deg,rgba(255,255,255,0.04) 0%,rgba(255,255,255,0.01) 100%)',
                backdropFilter: 'blur(12px)',
                WebkitBackdropFilter: 'blur(12px)',
              }}
            >
              {/* Hover glow overlay */}
              <div
                className="absolute inset-0 rounded-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-400 pointer-events-none"
                style={{ background: `radial-gradient(circle at 50% 0%,${f.glow},transparent 70%)` }}
              />
              <div
                className="w-11 h-11 rounded-2xl flex items-center justify-center mb-4 relative z-10"
                style={{ background: f.gradient, boxShadow: `0 6px 20px ${f.glow}` }}
              >
                <f.icon className="w-5 h-5 text-white" />
              </div>
              <h3 className="text-white mb-2 relative z-10" style={{ fontWeight: 700, fontSize: '1rem' }}>{f.title}</h3>
              <p className="text-sm leading-relaxed relative z-10" style={{ color: 'rgba(255,255,255,0.45)' }}>{f.desc}</p>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 5 — HOW IT WORKS
          ══════════════════════════════════════════ */}
      <section id="how-it-works" className="py-28 max-w-5xl mx-auto px-5">
        <Reveal className="text-center mb-14">
          <div
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-5"
            style={{ background: 'rgba(124,58,237,0.10)', border: '1px solid rgba(139,92,246,0.22)' }}
          >
            <Cpu size={14} style={{ color: '#a78bfa' }} />
            <span className="text-xs font-semibold tracking-widest" style={{ color: '#a78bfa' }}>HOW IT WORKS</span>
          </div>
          <h2 className="text-white" style={{ fontSize: 'clamp(1.8rem,4vw,2.8rem)', fontWeight: 800, letterSpacing: '-0.02em' }}>
            Up and running in 3 steps
          </h2>
        </Reveal>

        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
          variants={staggerContainer}
          className="grid md:grid-cols-3 gap-8 relative"
        >
          {/* Connector line */}
          <div
            className="hidden md:block absolute top-8 left-[20%] right-[20%] h-px pointer-events-none"
            style={{ background: 'linear-gradient(to right,transparent,rgba(139,92,246,0.25),transparent)' }}
          />

          {STEPS.map((step, i) => (
            <motion.div
              key={step.num}
              variants={fadeUp(i * 0.12)}
              className="relative flex flex-col items-center text-center"
            >
              <div className="relative mb-6">
                <motion.div
                  whileHover={{ scale: 1.08, boxShadow: '0 0 40px rgba(139,92,246,0.30)' }}
                  className="w-16 h-16 rounded-2xl flex items-center justify-center transition-shadow duration-300"
                  style={{
                    background: 'linear-gradient(135deg,rgba(124,58,237,0.22),rgba(109,40,217,0.12))',
                    border: '1px solid rgba(139,92,246,0.28)',
                    boxShadow: '0 0 30px rgba(139,92,246,0.15)',
                  }}
                >
                  <step.icon className="w-7 h-7" style={{ color: '#a78bfa' }} />
                </motion.div>
                <div
                  className="absolute -top-2 -right-2 w-6 h-6 rounded-full flex items-center justify-center text-white"
                  style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)', fontSize: 10, fontWeight: 800 }}
                >
                  {i + 1}
                </div>
              </div>
              <h3 className="text-white mb-3" style={{ fontWeight: 700, fontSize: '1.05rem' }}>{step.title}</h3>
              <p className="text-sm leading-relaxed" style={{ color: 'rgba(255,255,255,0.45)' }}>{step.desc}</p>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 6 — PRICING PREVIEW
          ══════════════════════════════════════════ */}
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
            className="grid md:grid-cols-3 gap-5"
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

      {/* ══════════════════════════════════════════
          SECTION 7 — TESTIMONIALS
          ══════════════════════════════════════════ */}
      <section className="py-28 max-w-5xl mx-auto px-5">
        <Reveal className="text-center mb-14">
          <h2 className="text-white mb-3" style={{ fontSize: 'clamp(1.8rem,4vw,2.8rem)', fontWeight: 800, letterSpacing: '-0.02em' }}>
            Students love Syrabit.ai
          </h2>
          <p style={{ color: 'rgba(255,255,255,0.40)' }}>Real feedback from AssamBoard students across Assam</p>
        </Reveal>

        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
          variants={staggerContainer}
          className="grid md:grid-cols-3 gap-5"
        >
          {TESTIMONIALS.map((t) => (
            <motion.div
              key={t.name}
              variants={fadeUp()}
              whileHover={{ y: -5 }}
              className="relative rounded-3xl p-6 flex flex-col gap-4 transition-shadow duration-300"
              style={{
                border: '1px solid rgba(255,255,255,0.08)',
                background: 'linear-gradient(135deg,rgba(255,255,255,0.04) 0%,rgba(255,255,255,0.01) 100%)',
              }}
            >
              <div className="flex items-center gap-0.5">
                {[...Array(5)].map((_, i) => (
                  <Star key={i} className="w-4 h-4 fill-amber-400 text-amber-400" />
                ))}
              </div>
              <p className="text-sm leading-relaxed flex-1" style={{ color: 'rgba(255,255,255,0.65)' }}>"{t.quote}"</p>
              <div className="flex items-center gap-3 pt-1 border-t" style={{ borderColor: 'rgba(255,255,255,0.08)' }}>
                <div
                  className="w-9 h-9 rounded-full flex items-center justify-center text-white flex-shrink-0"
                  style={{ background: t.gradient, fontSize: 12, fontWeight: 700 }}
                >
                  {t.initials}
                </div>
                <div>
                  <p className="text-white text-sm font-semibold">{t.name}</p>
                  <p className="text-xs" style={{ color: 'rgba(255,255,255,0.35)' }}>{t.classLabel}</p>
                </div>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* ══════════════════════════════════════════
          SECTION 8 — FINAL CTA
          ══════════════════════════════════════════ */}
      <section className="py-28 relative overflow-hidden">
        {/* Background orbs */}
        <div className="absolute inset-0 pointer-events-none">
          <GlowOrb color="radial-gradient(circle,#7c3aed,transparent)" size={700} x="20%" y="0%" blur={140} opacity={0.12} animRange={20} duration={20} />
          <GlowOrb color="radial-gradient(circle,#4f46e5,transparent)" size={500} x="60%" y="40%" blur={120} opacity={0.08} animRange={15} duration={16} />
        </div>

        <Reveal className="relative z-10 max-w-2xl mx-auto px-5 text-center">
          <motion.div
            animate={{ y: [0, -8, 0] }}
            transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
            className="flex justify-center mb-8"
          >
            <LogoMark size="lg" />
          </motion.div>

          <h2 className="text-white mb-4" style={{ fontSize: 'clamp(2rem,4vw,3rem)', fontWeight: 900, letterSpacing: '-0.02em' }}>
            Ready to ace your boards?
          </h2>
          <p className="mb-10 text-lg" style={{ color: 'rgba(255,255,255,0.45)' }}>
            Join hundreds of AssamBoard students (AHSEC, DEGREE &amp; SEBA) who study smarter with Syrabit.ai. Free forever — no credit card required.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <motion.div whileHover={{ scale: 1.04, y: -2 }} whileTap={{ scale: 0.97 }}>
              <Link
                to="/signup"
                className="flex items-center gap-2 text-white font-bold"
                style={{
                  height: 56,
                  padding: '0 2.5rem',
                  borderRadius: '1rem',
                  fontSize: '1.125rem',
                  background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
                  boxShadow: '0 8px 40px rgba(139,92,246,0.40)',
                }}
                data-testid="landing-final-cta-button"
              >
                <Sparkles size={20} />
                Create Free Account
              </Link>
            </motion.div>
            <motion.div whileHover={{ scale: 1.04, y: -2 }} whileTap={{ scale: 0.97 }}>
              <Link
                to="/pricing"
                className="flex items-center gap-2 font-semibold"
                style={{
                  height: 56,
                  padding: '0 2rem',
                  borderRadius: '1rem',
                  fontSize: '1rem',
                  color: 'rgba(255,255,255,0.60)',
                  border: '1px solid rgba(255,255,255,0.10)',
                  background: 'rgba(255,255,255,0.04)',
                }}
              >
                View all plans <ChevronRight size={18} />
              </Link>
            </motion.div>
          </div>
        </Reveal>
      </section>

      {/* ══════════════════════════════════════════
          FOOTER
          ══════════════════════════════════════════ */}
      <footer
        className="border-t py-12"
        style={{ borderColor: 'rgba(255,255,255,0.06)', background: 'rgba(0,0,0,0.30)' }}
      >
        <div className="max-w-6xl mx-auto px-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-12">
            <div className="col-span-2 md:col-span-1 space-y-4">
              <LogoFull size="sm" textClassName="text-white" />
              <p className="text-sm leading-relaxed" style={{ color: 'rgba(255,255,255,0.30)' }}>
                AI-powered exam prep for AssamBoard students in Assam — AHSEC (Class 11–12), DEGREE (B.Com, B.A, B.Sc), and SEBA.
              </p>
              <div className="flex items-center gap-2">
                {[{ icon: Twitter, label: 'Twitter' }, { icon: Github, label: 'GitHub' }, { icon: Mail, label: 'Email' }].map(({ icon: Icon, label }) => (
                  <motion.button
                    key={label}
                    aria-label={label}
                    whileHover={{ scale: 1.1, background: 'rgba(255,255,255,0.10)' }}
                    whileTap={{ scale: 0.95 }}
                    className="w-8 h-8 rounded-lg flex items-center justify-center"
                    style={{ color: 'rgba(255,255,255,0.40)', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                  >
                    <Icon size={16} />
                  </motion.button>
                ))}
              </div>
            </div>

            <div className="space-y-3">
              <p className="text-xs font-bold tracking-[0.10em]" style={{ color: 'rgba(255,255,255,0.60)' }}>PRODUCT</p>
              {['Features', 'Pricing', 'Subjects', 'Chat'].map((item) => (
                <a
                  key={item}
                  href={item === 'Features' ? '/#features' : item === 'Pricing' ? '/pricing' : '#'}
                  className="block text-sm transition-colors hover:text-white/70"
                  style={{ color: 'rgba(255,255,255,0.35)' }}
                >
                  {item}
                </a>
              ))}
            </div>

            <div className="space-y-3">
              <p className="text-xs font-bold tracking-[0.10em]" style={{ color: 'rgba(255,255,255,0.60)' }}>LEGAL</p>
              <Link to="/privacy" className="block text-sm transition-colors hover:text-white/70" style={{ color: 'rgba(255,255,255,0.35)' }}>Privacy Policy</Link>
              <Link to="/terms" className="block text-sm transition-colors hover:text-white/70" style={{ color: 'rgba(255,255,255,0.35)' }}>Terms of Service</Link>
            </div>

            <div className="space-y-3">
              <p className="text-xs font-bold tracking-[0.10em]" style={{ color: 'rgba(255,255,255,0.60)' }}>CONTACT</p>
              <div className="flex items-center gap-1.5 text-sm" style={{ color: 'rgba(255,255,255,0.35)' }}>
                <Mail size={14} /><span>support@syrabit.ai</span>
              </div>
              <div className="flex items-center gap-1.5 text-sm" style={{ color: 'rgba(255,255,255,0.35)' }}>
                <Globe size={14} /><span>syrabit.ai</span>
              </div>
              <div className="mt-4">
                <Link
                  to="/admin/login"
                  className="text-xs transition-colors hover:text-white/35"
                  style={{ color: 'rgba(255,255,255,0.15)' }}
                >
                  Admin Portal →
                </Link>
              </div>
            </div>
          </div>

          <div
            className="border-t pt-6 flex flex-col md:flex-row items-center justify-between gap-3"
            style={{ borderColor: 'rgba(255,255,255,0.06)' }}
          >
            <p className="text-xs" style={{ color: 'rgba(255,255,255,0.20)' }}>
              © {year} Syrabit.ai · Built for AssamBoard students in Assam, India (AHSEC · DEGREE · SEBA)
            </p>
            <p className="text-xs" style={{ color: 'rgba(255,255,255,0.15)' }}>
              Made with ♥ for Class 11 &amp; 12 exam warriors
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
