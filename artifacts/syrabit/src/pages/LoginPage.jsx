import { useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, Lock, Eye, EyeOff, Loader2, MessageSquare, BarChart3, AlertCircle, Sparkles } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from '@/context/AuthContext';
import { toast } from 'sonner';
import { LogoFull } from '@/components/Logo';
import GoogleSignInButton from '@/components/GoogleSignInButton';

const BENEFITS = [
  {
    icon: Sparkles,
    title: 'AI-Powered Tutor',
    desc: 'Instant, syllabus-aligned answers for AssamBoard students',
    color: '#a78bfa',
    bg: 'rgba(124,58,237,0.14)',
    border: 'rgba(139,92,246,0.22)',
  },
  {
    icon: MessageSquare,
    title: 'Chat History',
    desc: 'Every conversation saved and searchable — never start over',
    color: '#67e8f9',
    bg: 'rgba(6,182,212,0.10)',
    border: 'rgba(6,182,212,0.18)',
  },
  {
    icon: BarChart3,
    title: 'Track Progress',
    desc: 'Transparent credit system — see exactly how much you use',
    color: '#86efac',
    bg: 'rgba(16,185,129,0.10)',
    border: 'rgba(16,185,129,0.18)',
  },
];

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleInputFocus = useCallback((e) => {
    setTimeout(() => {
      e.target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 300);
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const user = await login(email, password);
      toast.success('Welcome back!');
      if (!user.onboarding_done) {
        navigate('/onboarding');
      } else {
        navigate('/library');
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-[#06060e]">

      {/* ── Left panel — branded visual (desktop only) ── */}
      <div
        className="hidden lg:flex lg:w-[52%] relative flex-col justify-between p-12 overflow-hidden"
        style={{
          background: 'linear-gradient(135deg, #0e0620 0%, #130928 40%, #0e0e22 100%)',
        }}
      >
        {/* Layered glow orbs */}
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-[-15%] left-[-10%] w-[600px] h-[600px] rounded-full"
            style={{ background: 'radial-gradient(circle, rgba(124,58,237,0.28) 0%, transparent 70%)', filter: 'blur(40px)' }} />
          <div className="absolute bottom-[-10%] right-[-15%] w-[500px] h-[500px] rounded-full"
            style={{ background: 'radial-gradient(circle, rgba(99,102,241,0.20) 0%, transparent 70%)', filter: 'blur(50px)' }} />
          <div className="absolute top-[40%] right-[10%] w-[300px] h-[300px] rounded-full"
            style={{ background: 'radial-gradient(circle, rgba(168,85,247,0.16) 0%, transparent 70%)', filter: 'blur(30px)' }} />
        </div>

        {/* Grid overlay */}
        <div className="absolute inset-0 pointer-events-none opacity-[0.04]"
          style={{
            backgroundImage: 'linear-gradient(rgba(139,92,246,1) 1px,transparent 1px),linear-gradient(to right,rgba(139,92,246,1) 1px,transparent 1px)',
            backgroundSize: '60px 60px',
          }} />

        {/* Content */}
        <div className="relative z-10">
          <Link to="/" className="inline-block mb-14">
            <LogoFull size="md" textClassName="text-white text-2xl" />
          </Link>

          <div className="anim-slide-left">
            <div
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-6"
              style={{ background: 'rgba(124,58,237,0.16)', border: '1px solid rgba(139,92,246,0.28)' }}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
              <span className="text-xs font-semibold tracking-widest" style={{ color: '#a78bfa' }}>
                AI EXAM PREP
              </span>
            </div>
            <h2
              className="mb-4 text-white"
              style={{ fontSize: 'clamp(1.6rem, 3vw, 2.2rem)', fontWeight: 800, lineHeight: 1.18, letterSpacing: '-0.02em' }}
            >
              Educational Browser For<br />
              <span style={{ background: 'linear-gradient(135deg,#a78bfa,#7c3aed)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                AssamBoard Students
              </span>
            </h2>
            <p className="mb-10 max-w-sm leading-relaxed" style={{ color: 'rgba(255,255,255,0.52)', fontSize: '0.95rem' }}>
              Get instant, syllabus-aligned answers for Class 11–12 subjects. Study smarter, not harder.
            </p>

            <div className="space-y-3">
              {BENEFITS.map(({ icon: Icon, title, desc, color, bg, border }, i) => (
                <div
                  key={title}
                  className="flex items-start gap-3.5 rounded-2xl p-4 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lg"
                  style={{
                    background: bg,
                    border: `1px solid ${border}`,
                    animation: `slideInLeft 0.6s cubic-bezier(0.16,1,0.3,1) both ${0.3 + i * 0.12}s`,
                  }}
                >
                  <div
                    className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 mt-0.5"
                    style={{ background: 'rgba(255,255,255,0.06)', border: `1px solid ${border}` }}
                  >
                    <Icon size={16} style={{ color }} />
                  </div>
                  <div>
                    <p className="text-white text-sm font-semibold">{title}</p>
                    <p className="text-xs mt-0.5 leading-relaxed" style={{ color: 'rgba(255,255,255,0.48)' }}>{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Bottom tagline */}
        <div className="relative z-10">
          <p className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}>
            Trusted by 500+ Assam board students · Free to start
          </p>
        </div>
      </div>

      {/* ── Right panel — auth form ── */}
      <div className="w-full lg:w-[48%] flex items-center justify-center p-4 sm:p-6 relative overflow-y-auto" style={{ scrollPaddingBottom: '2rem' }}>
        {/* Subtle background glow */}
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-[20%] right-[10%] w-[300px] h-[300px] rounded-full opacity-60"
            style={{ background: 'radial-gradient(circle, rgba(124,58,237,0.08) 0%, transparent 70%)', filter: 'blur(40px)' }} />
        </div>

        <div className="w-full max-w-sm relative z-10 anim-slide-right">
          {/* Mobile logo */}
          <Link to="/" className="flex items-center gap-2 mb-4 lg:hidden">
            <LogoFull size="sm" textClassName="text-white" />
          </Link>

          {/* Form card */}
          <div
            className="rounded-2xl p-5 sm:p-7 overflow-y-auto auth-form-card"
            style={{
              background: 'rgba(255,255,255,0.04)',
              backdropFilter: 'blur(24px)',
              WebkitBackdropFilter: 'blur(24px)',
              border: '1px solid rgba(255,255,255,0.10)',
              boxShadow: '0 16px 48px rgba(0,0,0,0.30), 0 0 0 1px rgba(255,255,255,0.04) inset',
            }}
          >
            <div className="mb-7">
              <h1 className="text-2xl font-bold text-white tracking-tight">Welcome back</h1>
              <p className="mt-1.5 text-sm" style={{ color: 'rgba(255,255,255,0.65)' }}>Sign in to your account to continue</p>
            </div>

            {error && (
              <div className="flex items-center gap-2 text-red-400 rounded-xl p-3 mb-5 text-sm"
                style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.18)' }}>
                <AlertCircle size={16} className="flex-shrink-0" />
                {error}
              </div>
            )}

            <GoogleSignInButton mode="login" />

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="email" className="text-sm font-medium" style={{ color: 'rgba(255,255,255,0.70)' }}>
                  Email address
                </Label>
                <div className="relative">
                  <Mail size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2" style={{ color: 'rgba(255,255,255,0.28)' }} />
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    placeholder="your@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    onFocus={handleInputFocus}
                    className="pl-10 h-11 bg-white/[0.05] border-white/10 text-white placeholder:text-white/25 focus-visible:border-violet-500/50 focus-visible:ring-violet-500/25"
                    style={{ scrollMarginBottom: '4rem' }}
                    required
                    data-testid="auth-email-input"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password" className="text-sm font-medium" style={{ color: 'rgba(255,255,255,0.70)' }}>
                  Password
                </Label>
                <div className="relative">
                  <Lock size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2" style={{ color: 'rgba(255,255,255,0.28)' }} />
                  <Input
                    id="password"
                    type={showPass ? 'text' : 'password'}
                    autoComplete="current-password"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    onFocus={handleInputFocus}
                    className="pl-10 pr-11 h-11 bg-white/[0.05] border-white/10 text-white placeholder:text-white/25 focus-visible:border-violet-500/50 focus-visible:ring-violet-500/25"
                    style={{ scrollMarginBottom: '4rem' }}
                    required
                    data-testid="auth-password-input"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPass(!showPass)}
                    className="absolute right-1 top-1/2 -translate-y-1/2 min-w-[44px] min-h-[44px] flex items-center justify-center pass-toggle-btn"
                  >
                    {showPass ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
              </div>

              <div className="flex justify-end">
                <Link to="/reset-password" className="text-xs font-medium auth-link">
                  Forgot password?
                </Link>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 h-11 rounded-xl text-sm font-bold text-white transition-all duration-150 active:scale-[0.97] disabled:opacity-60 btn-gradient"
                data-testid="auth-submit-button"
              >
                {loading ? <Loader2 size={17} className="animate-spin" /> : null}
                {loading ? 'Signing in…' : 'Sign In'}
              </button>
            </form>

            <p className="text-center text-sm mt-6" style={{ color: 'rgba(255,255,255,0.65)' }}>
              Don't have an account?{' '}
              <Link to="/signup" className="font-semibold auth-link">
                Sign up free
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
