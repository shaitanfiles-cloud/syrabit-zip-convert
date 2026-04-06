import { useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Sparkles, Play, BookOpen, Users, TrendingUp } from 'lucide-react';
import { fadeUp, staggerContainer } from './shared';
import AnimatedStat from './AnimatedStat';
import AnimatedChatDemo from './AnimatedChatDemo';
import { prefetchRoute } from '@/utils/prefetchRoute';

const STATS = [
  { value: '3',    label: 'AssamBoard Divisions', icon: BookOpen   },
  { value: '500+', label: 'Students',              icon: Users      },
  { value: '3',    label: 'Plans',                 icon: TrendingUp },
];

export default function HeroSection() {
  const [browserPath, setBrowserPath] = useState('chat');
  const handleUrlChange = useCallback((path) => setBrowserPath(path), []);

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
          style={{ background: 'radial-gradient(ellipse 80% 50% at 50% -5%,rgba(124,58,237,0.12),transparent)' }}
        />

        <div className="relative z-10 max-w-5xl mx-auto px-5 text-center py-24">
          <motion.h1
            initial={{ opacity: 0, y: 32 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1], delay: 0.2 }}
            className="mb-6"
            style={{ fontSize: 'clamp(1.75rem,5vw,5rem)', fontWeight: 900, lineHeight: 1.06, letterSpacing: '-0.03em' }}
          >
            <span className="text-foreground">Educational Browser</span>
            <br />
            <span>
              <span className="text-foreground">For </span>
              <span style={{
                background: 'linear-gradient(135deg,#7c3aed 0%,#a78bfa 40%,#6d28d9 80%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
                filter: 'drop-shadow(0 0 30px rgba(139,92,246,0.20))',
              }}>
                AssamBoard Students
              </span>
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.35 }}
            className="max-w-2xl mx-auto mb-8 leading-relaxed text-muted-foreground"
            style={{ fontSize: 'clamp(1rem,2vw,1.18rem)', letterSpacing: '0.01em' }}
          >
            Syrabit gives AssamBoard students (AHSEC, DEGREE &amp; SEBA) instant, syllabus-aligned AI answers,
            PYQ insights, and structured subject notes — all in one place.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.48 }}
            className="flex flex-col sm:flex-row items-center justify-center gap-3"
          >
            <motion.div whileHover={{ scale: 1.04, y: -3 }} whileTap={{ scale: 0.97 }}>
              <Link
                to="/signup"
                onMouseEnter={() => prefetchRoute('/signup')}
                onTouchStart={() => prefetchRoute('/signup')}
                className="flex flex-wrap items-center justify-center gap-2.5 text-white font-bold btn-gradient"
                style={{
                  minHeight: 54,
                  padding: '0.75rem 1.5rem',
                  borderRadius: '1rem',
                  fontSize: 'clamp(0.875rem, 2.5vw, 1rem)',
                  boxShadow: '0 8px 36px rgba(139,92,246,0.35), 0 0 0 1px rgba(139,92,246,0.15) inset',
                  textAlign: 'center',
                }}
                data-testid="landing-hero-primary-cta-button"
              >
                <Sparkles size={18} className="flex-shrink-0" />
                <span>Start for Free — No Card Needed</span>
              </Link>
            </motion.div>
            <motion.div whileHover={{ scale: 1.03, y: -2 }} whileTap={{ scale: 0.97 }}>
              <a
                href="#features"
                className="flex items-center gap-2.5 font-semibold transition-all duration-200 hover:bg-violet-500/[0.06]"
                style={{
                  minHeight: 54,
                  padding: '0.75rem 1.5rem',
                  borderRadius: '1rem',
                  fontSize: 'clamp(0.875rem, 2.5vw, 1rem)',
                  color: 'hsl(var(--muted-foreground))',
                  border: '1px solid hsl(var(--border))',
                  background: 'hsl(var(--muted) / 0.3)',
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
            className="text-sm mt-7 text-muted-foreground"
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
              style={{ background: 'rgba(124,58,237,0.08)', filter: 'blur(60px)' }}
            />
            <motion.div
              className="relative rounded-3xl overflow-hidden"
              style={{
                border: '1px solid rgba(139,92,246,0.15)',
                background: 'linear-gradient(135deg, rgba(15,10,30,0.95) 0%, rgba(20,15,40,0.98) 100%)',
                boxShadow: '0 32px 80px rgba(0,0,0,0.25), 0 0 0 1px rgba(139,92,246,0.08)',
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
                  <motion.span
                    key={browserPath}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.3 }}
                    className="text-xs"
                    style={{ color: 'rgba(255,255,255,0.60)' }}
                  >
                    syrabit.ai/{browserPath}
                  </motion.span>
                </div>
              </div>

              <AnimatedChatDemo onUrlChange={handleUrlChange} />
            </motion.div>
          </motion.div>
        </div>
      </section>

      <section
        className="py-16"
        style={{
          background: 'hsl(var(--muted) / 0.3)',
          borderTop: '1px solid hsl(var(--border) / 0.3)',
          borderBottom: '1px solid hsl(var(--border) / 0.3)',
        }}
      >
        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
          variants={staggerContainer}
          className="max-w-4xl mx-auto px-5 grid grid-cols-1 sm:grid-cols-3 gap-8"
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
