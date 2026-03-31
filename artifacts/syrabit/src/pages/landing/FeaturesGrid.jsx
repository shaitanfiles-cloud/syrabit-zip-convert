import { motion } from 'framer-motion';
import {
  Brain, BookOpen, Layers, Clock, BarChart3, Shield,
  Sparkles, Cpu, GraduationCap, MessageSquare,
} from 'lucide-react';
import { fadeUp, staggerContainer } from './shared';
import Reveal from './Reveal';

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

export default function FeaturesGrid() {
  return (
    <>
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
    </>
  );
}
