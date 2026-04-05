import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Sparkles, ChevronRight, Twitter, Github, Mail, Globe } from 'lucide-react';
import { LogoMark, LogoFull } from '@/components/Logo';
import { fadeUp, staggerContainer } from './shared';
import Reveal from './Reveal';
import GlowOrb from './GlowOrb';

const TRUSTPILOT_BU_ID = __TRUSTPILOT_BU_ID__;

function TrustpilotCarousel() {
  const ref = useRef(null);

  useEffect(() => {
    if (typeof window !== 'undefined' && window.Trustpilot && ref.current) {
      window.Trustpilot.loadFromElement(ref.current, true);
    }
  }, []);

  return (
    <div
      ref={ref}
      className="trustpilot-widget"
      data-locale="en-US"
      data-template-id="53aa8912dec7e10d38f59f36"
      data-businessunit-id={TRUSTPILOT_BU_ID}
      data-style-height="140px"
      data-style-width="100%"
      data-theme="dark"
      data-stars="4,5"
      data-review-languages="en"
    >
      <a
        href="https://www.trustpilot.com/review/syrabit.ai"
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 text-sm font-medium"
        style={{ color: 'rgba(255,255,255,0.60)' }}
      >
        See our reviews on Trustpilot
      </a>
    </div>
  );
}

function TrustpilotMini() {
  const ref = useRef(null);

  useEffect(() => {
    if (typeof window !== 'undefined' && window.Trustpilot && ref.current) {
      window.Trustpilot.loadFromElement(ref.current, true);
    }
  }, []);

  return (
    <div className="mt-8 flex justify-center">
      <div
        ref={ref}
        className="trustpilot-widget"
        data-locale="en-US"
        data-template-id="56278e9abfbd13b10015e694"
        data-businessunit-id={TRUSTPILOT_BU_ID}
        data-style-height="52px"
        data-style-width="100%"
      >
        <a
          href="https://www.trustpilot.com/review/syrabit.ai"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 text-sm font-medium"
          style={{ color: 'rgba(255,255,255,0.60)' }}
        >
          Rated on Trustpilot
        </a>
      </div>
    </div>
  );
}

export default function TestimonialsFooter({ year }) {
  useEffect(() => {
    if (document.getElementById('trustpilot-widget-script')) return;
    const script = document.createElement('script');
    script.id = 'trustpilot-widget-script';
    script.src = 'https://widget.trustpilot.com/bootstrap/v5/tp.widget.bootstrap.min.js';
    script.async = true;
    script.onload = () => {
      const els = document.querySelectorAll('.trustpilot-widget');
      els.forEach((el) => {
        if (window.Trustpilot) window.Trustpilot.loadFromElement(el, true);
      });
    };
    document.head.appendChild(script);
  }, []);

  return (
    <>
      <section className="py-28 max-w-5xl mx-auto px-5">
        <Reveal className="text-center mb-14">
          <h2 className="text-white mb-3" style={{ fontSize: 'clamp(1.8rem,4vw,2.8rem)', fontWeight: 800, letterSpacing: '-0.02em' }}>
            Students love Syrabit.ai
          </h2>
          <p style={{ color: 'rgba(255,255,255,0.60)' }}>
            Real feedback from students across Assam
          </p>
        </Reveal>

        <motion.div
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, margin: '-60px' }}
          variants={staggerContainer}
        >
          <motion.div variants={fadeUp()}>
            <TrustpilotCarousel />
          </motion.div>
        </motion.div>

        <TrustpilotMini />
      </section>

      <section className="py-28 relative overflow-hidden">
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
          <p className="mb-10 text-lg" style={{ color: 'rgba(255,255,255,0.65)' }}>
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

      <footer
        className="border-t py-12"
        style={{ borderColor: 'rgba(255,255,255,0.06)', background: 'rgba(0,0,0,0.30)' }}
      >
        <div className="max-w-6xl mx-auto px-5">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 sm:gap-6 md:gap-8 mb-12">
            <div className="col-span-2 md:col-span-1 space-y-4">
              <LogoFull size="sm" textClassName="text-white" />
              <p className="text-sm leading-relaxed" style={{ color: 'rgba(255,255,255,0.60)' }}>
                AI-powered exam prep for AssamBoard students in Assam — AHSEC (Class 11–12), DEGREE (B.Com, B.A, B.Sc), and SEBA.
              </p>
              <div className="flex items-center gap-2">
                {[{ icon: Twitter, label: 'Twitter' }, { icon: Github, label: 'GitHub' }, { icon: Mail, label: 'Email' }].map(({ icon: Icon, label }) => (
                  <motion.button
                    key={label}
                    aria-label={label}
                    whileHover={{ scale: 1.1, background: 'rgba(255,255,255,0.10)' }}
                    whileTap={{ scale: 0.95 }}
                    className="w-11 h-11 rounded-lg flex items-center justify-center"
                    style={{ color: 'rgba(255,255,255,0.40)', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                  >
                    <Icon size={16} />
                  </motion.button>
                ))}
              </div>
            </div>

            <div className="space-y-1">
              <p className="text-xs font-bold tracking-[0.10em] pb-1" style={{ color: 'rgba(255,255,255,0.60)' }}>PRODUCT</p>
              <Link to="/home#features" className="block text-sm transition-colors hover:text-white/70 min-h-[44px] flex items-center" style={{ color: 'rgba(255,255,255,0.60)' }}>Features</Link>
              <Link to="/pricing" className="block text-sm transition-colors hover:text-white/70 min-h-[44px] flex items-center" style={{ color: 'rgba(255,255,255,0.60)' }}>Pricing</Link>
              <Link to="/library" className="block text-sm transition-colors hover:text-white/70 min-h-[44px] flex items-center" style={{ color: 'rgba(255,255,255,0.60)' }}>Subjects</Link>
              <Link to="/chat" className="block text-sm transition-colors hover:text-white/70 min-h-[44px] flex items-center" style={{ color: 'rgba(255,255,255,0.60)' }}>Chat</Link>
            </div>

            <div className="space-y-1">
              <p className="text-xs font-bold tracking-[0.10em] pb-1" style={{ color: 'rgba(255,255,255,0.60)' }}>COMPANY</p>
              <Link to="/about" className="block text-sm transition-colors hover:text-white/70 min-h-[44px] flex items-center" style={{ color: 'rgba(255,255,255,0.60)' }}>About Us</Link>
              <Link to="/privacy" className="block text-sm transition-colors hover:text-white/70 min-h-[44px] flex items-center" style={{ color: 'rgba(255,255,255,0.60)' }}>Privacy Policy</Link>
              <Link to="/terms" className="block text-sm transition-colors hover:text-white/70 min-h-[44px] flex items-center" style={{ color: 'rgba(255,255,255,0.60)' }}>Terms of Service</Link>
              <Link to="/status" className="block text-sm transition-colors hover:text-white/70 min-h-[44px] flex items-center" style={{ color: 'rgba(255,255,255,0.60)' }}>System Status</Link>
            </div>

            <div className="space-y-1">
              <p className="text-xs font-bold tracking-[0.10em] pb-1" style={{ color: 'rgba(255,255,255,0.60)' }}>CONTACT</p>
              <div className="flex items-center gap-1.5 text-sm min-h-[44px]" style={{ color: 'rgba(255,255,255,0.60)' }}>
                <Mail size={14} /><span>admin@syrabit.ai</span>
              </div>
              <div className="flex items-center gap-1.5 text-sm min-h-[44px]" style={{ color: 'rgba(255,255,255,0.60)' }}>
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
            <p className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}>
              © {year} Syrabit.ai · Built for AssamBoard students in Assam, India (AHSEC · DEGREE · SEBA)
            </p>
            <p className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}>
              Made with ♥ for Class 11 &amp; 12 exam warriors
            </p>
          </div>
        </div>
      </footer>
    </>
  );
}
