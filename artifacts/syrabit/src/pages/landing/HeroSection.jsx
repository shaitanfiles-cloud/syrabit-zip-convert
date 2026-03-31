import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Sparkles, Play, GraduationCap, BookOpen, Users, TrendingUp } from 'lucide-react';
import { LogoMark } from '@/components/Logo';
import { fadeUp, staggerContainer } from './shared';
import AnimatedStat from './AnimatedStat';

const STATS = [
  { value: '3',    label: 'AssamBoard Divisions', icon: BookOpen   },
  { value: '500+', label: 'Students',              icon: Users      },
  { value: '3',    label: 'Plans',                 icon: TrendingUp },
];

export default function HeroSection() {
  return (
    <>
      <section className="relative min-h-screen flex items-center justify-center pt-16 overflow-hidden">
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            opacity: 0.035,
            backgroundImage: 'linear-gradient(rgba(139,92,246,1) 1px,transparent 1px),linear-gradient(to right,rgba(139,92,246,1) 1px,transparent 1px)',
            backgroundSize: '60px 60px',
          }}
        />

        <div
          className="absolute inset-0 pointer-events-none"
          style={{ background: 'radial-gradient(ellipse 80% 50% at 50% -5%,rgba(124,58,237,0.20),transparent)' }}
        />

        <div className="relative z-10 max-w-5xl mx-auto px-5 text-center py-24">
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

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.7 }}
            className="text-sm mt-7"
            style={{ color: 'rgba(255,255,255,0.22)' }}
          >
            Free plan · No credits needed to browse · Upgrade from ₹99
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 48, scale: 0.94 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 1, ease: [0.16, 1, 0.3, 1], delay: 0.6 }}
            className="mt-16 relative max-w-3xl mx-auto"
          >
            <div
              className="absolute -inset-4 rounded-3xl pointer-events-none"
              style={{ background: 'rgba(124,58,237,0.14)', filter: 'blur(60px)' }}
            />
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
    </>
  );
}
