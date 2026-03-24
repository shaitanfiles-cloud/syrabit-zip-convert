import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Menu, X, ArrowRight, Shield } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { LogoFull } from '@/components/Logo';

export const PublicNavbar = () => {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const { user } = useAuth();

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const navLinks = [
    { label: 'Features',     href: '/#features',    internal: false },
    { label: 'How it works', href: '/#how-it-works',internal: false },
    { label: 'Exam Routine', href: '/exam-routine', internal: true  },
    { label: 'Pricing',      href: '/pricing',      internal: true  },
  ];

  return (
    <nav
      className="fixed top-0 left-0 right-0 z-50 transition-all duration-300"
      style={
        scrolled
          ? {
              background: 'rgba(6,6,14,0.9)',
              backdropFilter: 'blur(24px)',
              WebkitBackdropFilter: 'blur(24px)',
              borderBottom: '1px solid rgba(255,255,255,0.08)',
              boxShadow: '0 4px 24px rgba(0,0,0,0.2)',
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
          <div className="hidden md:flex items-center gap-1">
            {navLinks.map((link) =>
              link.internal ? (
                <Link
                  key={link.label}
                  to={link.href}
                  className="px-4 py-2 rounded-xl text-sm text-white/60 hover:text-white hover:bg-white/[0.06] transition-all"
                  style={{ fontWeight: 500 }}
                >
                  {link.label}
                </Link>
              ) : (
                <a
                  key={link.label}
                  href={link.href}
                  className="px-4 py-2 rounded-xl text-sm text-white/60 hover:text-white hover:bg-white/[0.06] transition-all"
                  style={{ fontWeight: 500 }}
                >
                  {link.label}
                </a>
              )
            )}
          </div>

          {/* ─── Desktop CTAs ─── */}
          <div className="hidden md:flex items-center gap-2">
            <Link
              to="/admin/login"
              className="flex items-center gap-1.5 h-9 px-4 rounded-xl text-sm text-violet-400 border border-violet-500/30 hover:bg-violet-500/10 transition-all"
            >
              <Shield size={14} /> Admin
            </Link>

            {user ? (
              <Link
                to="/library"
                className="flex items-center gap-1.5 h-9 px-4 rounded-xl text-sm text-white font-semibold transition-all hover:opacity-90 active:scale-95"
                style={{
                  background: 'linear-gradient(to right, #7c3aed, #8b5cf6)',
                  boxShadow: '0 4px 16px rgba(139,92,246,0.3)',
                }}
              >
                Go to App <ArrowRight size={14} />
              </Link>
            ) : (
              <>
                <Link
                  to="/login"
                  className="h-9 px-4 rounded-xl text-sm text-white/70 hover:text-white hover:bg-white/[0.08] transition-all"
                  style={{ fontWeight: 500 }}
                >
                  Sign In
                </Link>
                <Link
                  to="/signup"
                  className="flex items-center gap-1.5 h-9 px-4 rounded-xl text-sm text-white font-semibold transition-all hover:opacity-90 active:scale-95"
                  style={{
                    background: 'linear-gradient(to right, #7c3aed, #8b5cf6)',
                    boxShadow: '0 4px 16px rgba(139,92,246,0.3)',
                  }}
                  data-testid="landing-nav-cta-button"
                >
                  Get Started Free <ArrowRight size={14} />
                </Link>
              </>
            )}
          </div>

          {/* ─── Mobile Hamburger ─── */}
          <button
            className="md:hidden w-9 h-9 rounded-xl text-white/70 hover:text-white hover:bg-white/[0.08] flex items-center justify-center transition-all"
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
          className="md:hidden border-t border-white/[0.08] px-5 py-4 space-y-1"
          style={{
            background: 'rgba(6,6,14,0.97)',
            backdropFilter: 'blur(24px)',
            WebkitBackdropFilter: 'blur(24px)',
          }}
        >
          {navLinks.map((link) =>
            link.internal ? (
              <Link
                key={link.label}
                to={link.href}
                className="block px-3 py-2.5 rounded-xl text-sm text-white/60 hover:text-white hover:bg-white/[0.06] transition-all"
                onClick={() => setMenuOpen(false)}
              >
                {link.label}
              </Link>
            ) : (
              <a
                key={link.label}
                href={link.href}
                className="block px-3 py-2.5 rounded-xl text-sm text-white/60 hover:text-white hover:bg-white/[0.06] transition-all"
                onClick={() => setMenuOpen(false)}
              >
                {link.label}
              </a>
            )
          )}
          <div className="pt-3 space-y-2 border-t border-white/[0.06] mt-2">
            <Link
              to="/admin/login"
              className="flex items-center gap-2 w-full px-3 py-2.5 rounded-xl text-sm text-violet-400 border border-violet-500/30 hover:bg-violet-500/10 transition-all"
              onClick={() => setMenuOpen(false)}
            >
              <Shield size={14} /> Admin Panel
            </Link>
            {user ? (
              <Link
                to="/library"
                className="flex items-center justify-center gap-2 w-full h-10 rounded-xl text-sm text-white font-semibold"
                style={{ background: 'linear-gradient(to right, #7c3aed, #8b5cf6)' }}
                onClick={() => setMenuOpen(false)}
              >
                Go to App <ArrowRight size={14} />
              </Link>
            ) : (
              <>
                <Link
                  to="/login"
                  className="flex items-center justify-center w-full h-10 rounded-xl text-sm text-white/70 border border-white/10 hover:bg-white/[0.06] transition-all"
                  onClick={() => setMenuOpen(false)}
                >
                  Sign In
                </Link>
                <Link
                  to="/signup"
                  className="flex items-center justify-center gap-2 w-full h-10 rounded-xl text-sm text-white font-semibold"
                  style={{ background: 'linear-gradient(to right, #7c3aed, #8b5cf6)' }}
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
