import { motion } from 'framer-motion';
import {
  Rocket, Library, GitBranch, BookMarked, MessageSquareText, Users,
  Sparkles,
} from 'lucide-react';
import { fadeUp, staggerContainer } from './shared';
import Reveal from './Reveal';

const SECTIONS = [
  {
    icon: Rocket,
    title: 'Our Mission',
    desc: 'Syrabit.ai is an AI-powered educational platform designed to deliver syllabus-aligned, reliable, and context-aware learning for AHSEC, SEBA, and Degree students across Assam.',
    gradient: 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
    glow: 'rgba(139,92,246,0.18)',
    border: 'rgba(139,92,246,0.15)',
  },
  {
    icon: Library,
    title: 'Platform Architecture',
    desc: 'Academic content is organized into structured subject cards that function as dedicated knowledge hubs — combining structured navigation with intelligent AI assistance for an interactive, verifiable learning experience.',
    gradient: 'linear-gradient(135deg,#2563eb,#06b6d4)',
    glow: 'rgba(59,130,246,0.18)',
    border: 'rgba(59,130,246,0.15)',
  },
  {
    icon: GitBranch,
    title: 'Hierarchical Knowledge Mapping',
    desc: 'Every query is contextually linked from Topic → Chapter → Subject → Course → Board, ensuring all responses are syllabus-aligned with dedicated source citations for transparency.',
    gradient: 'linear-gradient(135deg,#059669,#22c55e)',
    glow: 'rgba(16,185,129,0.18)',
    border: 'rgba(16,185,129,0.15)',
  },
  {
    icon: BookMarked,
    title: 'Subject Cards as Knowledge Hubs',
    desc: 'The Browser page presents each subject as an interactive card — a mini knowledge hub that acts as the structured data source powering context-aware, syllabus-aligned AI responses.',
    gradient: 'linear-gradient(135deg,#f97316,#fbbf24)',
    glow: 'rgba(245,158,11,0.18)',
    border: 'rgba(245,158,11,0.15)',
  },
  {
    icon: MessageSquareText,
    title: 'AI Chat with Source Citations',
    desc: 'The integrated AI chat provides accurate, personalized answers supported by clear source citations. Multi-stage retrieval keeps answers grounded — no hallucination, no off-topic responses.',
    gradient: 'linear-gradient(135deg,#db2777,#f43f5e)',
    glow: 'rgba(244,63,94,0.18)',
    border: 'rgba(244,63,94,0.15)',
  },
  {
    icon: Users,
    title: 'Who We Serve',
    desc: 'Students across Assam preparing for AHSEC, SEBA, Gauhati University, and Dibrugarh University exams — covering Class 11, Class 12, and undergraduate degree programmes.',
    gradient: 'linear-gradient(135deg,#4f46e5,#8b5cf6)',
    glow: 'rgba(99,102,241,0.18)',
    border: 'rgba(99,102,241,0.15)',
  },
];

export default function PlatformSection() {
  return (
    <section id="platform" className="py-28 max-w-6xl mx-auto px-5">
      <Reveal className="text-center mb-14">
        <div
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-5"
          style={{ background: 'rgba(124,58,237,0.08)', border: '1px solid rgba(139,92,246,0.18)' }}
        >
          <Sparkles size={14} className="text-violet-600" />
          <span className="text-xs font-semibold tracking-widest text-violet-600">
            THE PLATFORM
          </span>
        </div>
        <h2 className="text-foreground mb-4" style={{ fontSize: 'clamp(1.8rem,4vw,2.8rem)', fontWeight: 800, letterSpacing: '-0.02em' }}>
          How Syrabit.ai works under the hood
        </h2>
        <p className="max-w-xl mx-auto text-muted-foreground" style={{ fontSize: '1.05rem' }}>
          A purpose-built architecture that maps every answer to your exact syllabus — from board to topic.
        </p>
      </Reveal>

      <motion.div
        initial="hidden"
        whileInView="visible"
        viewport={{ once: true, margin: '-60px' }}
        variants={staggerContainer}
        className="grid md:grid-cols-2 lg:grid-cols-3 gap-5"
      >
        {SECTIONS.map((s) => (
          <motion.div
            key={s.title}
            variants={fadeUp()}
            whileHover={{ y: -6, boxShadow: `0 12px 40px ${s.glow}` }}
            className="group relative rounded-3xl p-6 cursor-default transition-shadow duration-300 glass-card"
            style={{
              border: `1px solid ${s.border}`,
            }}
          >
            <div
              className="absolute inset-0 rounded-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-400 pointer-events-none"
              style={{ background: `radial-gradient(circle at 50% 0%,${s.glow},transparent 70%)` }}
            />
            <div
              className="w-11 h-11 rounded-2xl flex items-center justify-center mb-4 relative z-10"
              style={{ background: s.gradient, boxShadow: `0 6px 20px ${s.glow}` }}
            >
              <s.icon className="w-5 h-5 text-white" />
            </div>
            <h3 className="text-foreground mb-2 relative z-10" style={{ fontWeight: 700, fontSize: '1rem' }}>{s.title}</h3>
            <p className="text-sm leading-relaxed relative z-10 text-muted-foreground">{s.desc}</p>
          </motion.div>
        ))}
      </motion.div>
    </section>
  );
}
