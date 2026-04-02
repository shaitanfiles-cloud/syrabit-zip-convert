import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Menu, X, ArrowRight, Shield } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { LogoFull } from '@/components/Logo';

export const PublicNavbar = () => {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const { user } = useAuth();

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 30);
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const handleEscape = useCallback((e) => {
    if (e.key === 'Escape' && menuOpen) setMenuOpen(false);
  }, [menuOpen]);

  useEffect(() => {
    if (menuOpen) {
      document.addEventListener('keydown', handleEscape);
      return () => document.removeEventListener('keydown', handleEscape);
    }
  }, [menuOpen, handleEscape]);

  const navLinks = [
    { label: 'Curriculum',   href: '/curriculum',   internal: true  },
    { label: 'Exam Routine', href: '/exam-routine', internal: true  },
    { label: 'Pricing',      href: '/pricing',      internal: true  },
  ];

  return (
    <nav
      className="fixed top-0 left-0 right-0 z-50 transition-all duration-400"
      style={
        scrolled
          ? {
              background: 'rgba(5,4,14,0.88)',
              backdropFilter: 'blur(28px) saturate(1.6)',
              WebkitBackdropFilter: 'blur(28px) saturate(1.6)',
              borderBottom: '1px solid rgba(139,92,246,0.14)',
              boxShadow: '0 4px 32px rgba(0,0,0,0.28), 0 0 0 1px rgba(255,255,255,0.03) inset',
            }
          : { background: 'transparent' }
      }
      data-testid="public-navbar"
    >
      <div className="max-w-6xl mx-auto px-5">
        <div className="flex items-center justify-between h-16">

          {/* ─── Logo ─── */}
          <Link to="/" onClick={() => setMenuOpen(false)}>
            <LogoFull size="sm" textClassName="text-white" hideText={false} hideIcon={true} />
          </Link>

          {/* ─── Desktop Nav Links ─── */}
          <div className="hidden lg:flex items-center gap-0.5">
            {navLinks.map((link) =>
              link.internal ? (
                <Link
                  key={link.label}
                  to={link.href}
                  className="px-4 py-2 rounded-xl text-sm font-medium text-white/55 hover:text-white hover:bg-white/[0.07] transition-all duration-150"
                >
                  {link.label}
                </Link>
              ) : (
                <a
                  key={link.label}
                  href={link.href}
                  className="px-4 py-2 rounded-xl text-sm font-medium text-white/55 hover:text-white hover:bg-white/[0.07] transition-all duration-150"
                >
                  {link.label}
                </a>
              )
            )}
          </div>

          {/* ─── Desktop CTAs ─── */}
          <div className="hidden lg:flex items-center gap-2">
            <Link
              to="/admin/login"
              className="flex items-center gap-1.5 h-9 px-4 rounded-xl text-sm text-violet-400/80 border border-violet-500/20 hover:bg-violet-500/10 hover:border-violet-500/40 hover:text-violet-300 transition-all duration-150"
            >
              <Shield size={13} /> Admin
            </Link>

            {user ? (
              <Link
                to="/library"
                className="flex items-center gap-1.5 h-9 px-4 rounded-xl text-sm text-white font-semibold transition-all duration-150 hover:opacity-90 active:scale-95 hover:-translate-y-px btn-gradient"
              >
                Go to App <ArrowRight size={14} />
              </Link>
            ) : (
              <>
                <Link
                  to="/login"
                  className="h-9 px-4 rounded-xl text-sm font-medium text-white/65 hover:text-white hover:bg-white/[0.08] transition-all duration-150"
                >
                  Sign In
                </Link>
                <Link
                  to="/signup"
                  className="flex items-center gap-1.5 h-9 px-4 rounded-xl text-sm text-white font-semibold transition-all duration-150 active:scale-95 btn-gradient"
                  data-testid="landing-nav-cta-button"
                >
                  Get Started Free <ArrowRight size={14} />
                </Link>
              </>
            )}
          </div>

          {/* ─── Mobile Hamburger ─── */}
          <button
            className="lg:hidden min-w-[44px] min-h-[44px] rounded-xl text-white/70 hover:text-white hover:bg-white/[0.08] flex items-center justify-center transition-all"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-label="Toggle menu"
            data-testid="mobile-menu-button"
          >
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </div>

      {/* ─── Mobile Menu ─── */}
      {menuOpen && (
        <div
          className="lg:hidden px-5 py-4 space-y-1 mobile-menu-slide"
          style={{
            background: 'rgba(5,4,14,0.97)',
            backdropFilter: 'blur(28px)',
            WebkitBackdropFilter: 'blur(28px)',
            borderTop: '1px solid rgba(139,92,246,0.12)',
          }}
        >
          {navLinks.map((link) =>
            link.internal ? (
              <Link
                key={link.label}
                to={link.href}
                className="block px-3 py-3 rounded-xl text-sm text-white/60 hover:text-white hover:bg-white/[0.06] transition-all min-h-[44px] flex items-center"
                onClick={() => setMenuOpen(false)}
              >
                {link.label}
              </Link>
            ) : (
              <a
                key={link.label}
                href={link.href}
                className="block px-3 py-3 rounded-xl text-sm text-white/60 hover:text-white hover:bg-white/[0.06] transition-all min-h-[44px] flex items-center"
                onClick={() => setMenuOpen(false)}
              >
                {link.label}
              </a>
            )
          )}
          <div className="pt-3 space-y-2 mt-2" style={{ borderTop: '1px solid rgba(139,92,246,0.10)' }}>
            {user?.is_admin && (
              <Link
                to="/admin/login"
                className="flex items-center gap-2 w-full px-3 min-h-[44px] rounded-xl text-sm text-violet-400 border border-violet-500/25 hover:bg-violet-500/10 transition-all"
                onClick={() => setMenuOpen(false)}
              >
                <Shield size={14} /> Admin Panel
              </Link>
            )}
            {user ? (
              <Link
                to="/library"
                className="flex items-center justify-center gap-2 w-full min-h-[44px] rounded-xl text-sm text-white font-semibold btn-gradient"
                onClick={() => setMenuOpen(false)}
              >
                Go to App <ArrowRight size={14} />
              </Link>
            ) : (
              <>
                <Link
                  to="/login"
                  className="flex items-center justify-center w-full min-h-[44px] rounded-xl text-sm text-white/70 border border-white/10 hover:bg-white/[0.06] transition-all"
                  onClick={() => setMenuOpen(false)}
                >
                  Sign In
                </Link>
                <Link
                  to="/signup"
                  className="flex items-center justify-center gap-2 w-full min-h-[44px] rounded-xl text-sm text-white font-semibold btn-gradient"
                  onClick={() => setMenuOpen(false)}
                >
                  Get Started Free <ArrowRight size={14} />
                </Link>
              </>
            )}
          </div>
        </div>
      )}
    </nav>
  );
};

export default PublicNavbar;
