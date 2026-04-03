import { useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, Lock, Eye, EyeOff, Loader2, User, CheckCircle, AlertCircle, BookOpen, Zap, GraduationCap } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from '@/context/AuthContext';
import { toast } from 'sonner';
import { LogoFull } from '@/components/Logo';


const getPasswordStrength = (password) => {
  if (password.length === 0) return { score: 0, label: '' };
  if (password.length < 6) return { score: 1, label: 'Too short' };
  let score = 1;
  if (password.length >= 8) score++;
  if (/[A-Z]/.test(password)) score++;
  if (/[0-9]/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;
  const labels = ['', 'Weak', 'Fair', 'Good', 'Strong', 'Very Strong'];
  return { score: Math.min(score, 5), label: labels[Math.min(score, 5)] };
};

const STRENGTH_COLORS = ['', 'bg-red-500', 'bg-orange-500', 'bg-yellow-500', 'bg-emerald-500', 'bg-emerald-400'];

const PERKS = [
  { icon: BookOpen, text: 'Browse all 55+ subjects — free forever' },
  { icon: Zap, text: 'Starter: 300 credits for just ₹99' },
  { icon: GraduationCap, text: 'Ask Syra — your Assam board study companion' },
  { icon: CheckCircle, text: 'Upgrade anytime — no lock-in' },
];

export default function SignupPage() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPass, setShowPass] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { signup } = useAuth();
  const navigate = useNavigate();

  const strength = getPasswordStrength(password);
  const passwordsMatch = confirmPassword && password === confirmPassword;

  const handleInputFocus = useCallback((e) => {
    setTimeout(() => {
      e.target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 300);
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (!agreed) {
      setError('Please agree to the Terms of Service');
      return;
    }
    setLoading(true);
    try {
      await signup(name, email, password);
      toast.success('Account created! Welcome to Syrabit.ai!');
      navigate('/onboarding');
    } catch (err) {
      setError(err.response?.data?.detail || 'Signup failed. Please try again.');
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
            style={{ background: 'radial-gradient(circle, rgba(5,150,105,0.16) 0%, transparent 70%)', filter: 'blur(50px)' }} />
          <div className="absolute top-[35%] right-[5%] w-[350px] h-[350px] rounded-full"
            style={{ background: 'radial-gradient(circle, rgba(168,85,247,0.14) 0%, transparent 70%)', filter: 'blur(35px)' }} />
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
              style={{ background: 'rgba(16,185,129,0.14)', border: '1px solid rgba(16,185,129,0.25)' }}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs font-semibold tracking-widest" style={{ color: '#6ee7b7' }}>
                FREE TO START
              </span>
            </div>
            <h2
              className="mb-4 text-white"
              style={{ fontSize: 'clamp(1.6rem, 3vw, 2.2rem)', fontWeight: 800, lineHeight: 1.18, letterSpacing: '-0.02em' }}
            >
              For AHSEC & Degree<br />
              <span style={{ background: 'linear-gradient(135deg,#a78bfa,#7c3aed)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                students
              </span>
            </h2>
            <p className="mb-10 max-w-sm leading-relaxed" style={{ color: 'rgba(255,255,255,0.52)', fontSize: '0.95rem' }}>
              Start your AI-powered exam prep journey today. No credit card required to get started.
            </p>

            <div className="space-y-3.5">
              {PERKS.map(({ icon: Icon, text }, i) => (
                <div
                  key={text}
                  className="flex items-center gap-3.5"
                  style={{ animation: `slideInLeft 0.6s cubic-bezier(0.16,1,0.3,1) both ${0.3 + i * 0.1}s` }}
                >
                  <div
                    className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ background: 'rgba(16,185,129,0.14)', border: '1px solid rgba(16,185,129,0.22)' }}
                  >
                    <Icon size={14} className="text-emerald-400" />
                  </div>
                  <span className="text-sm" style={{ color: 'rgba(255,255,255,0.72)' }}>{text}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Bottom */}
        <div className="relative z-10">
          <p className="text-xs" style={{ color: 'rgba(255,255,255,0.60)' }}>
            Trusted by 500+ Assam board students
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

        <div className="w-full max-w-sm relative z-10 anim-slide-right py-4 lg:py-8">
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
              <h1 className="text-2xl font-bold text-white tracking-tight">Create your account</h1>
              <p className="mt-1.5 text-sm" style={{ color: 'rgba(255,255,255,0.65)' }}>Start for free — no credit card required</p>
            </div>

            {error && (
              <div className="flex items-center gap-2 text-red-400 rounded-xl p-3 mb-5 text-sm"
                style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.18)' }}>
                <AlertCircle size={16} className="flex-shrink-0" />
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="name" className="text-sm font-medium" style={{ color: 'rgba(255,255,255,0.70)' }}>
                  Full Name
                </Label>
                <div className="relative">
                  <User size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2" style={{ color: 'rgba(255,255,255,0.28)' }} />
                  <Input
                    id="name"
                    autoComplete="name"
                    placeholder="Your name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    onFocus={handleInputFocus}
                    className="pl-10 h-11 bg-white/[0.05] border-white/10 text-white placeholder:text-white/25 focus-visible:border-violet-500/50 focus-visible:ring-violet-500/25"
                    style={{ scrollMarginBottom: '4rem' }}
                    required
                  />
                </div>
              </div>

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
                    autoComplete="new-password"
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
                {password && (
                  <div className="space-y-1 pt-1">
                    <div className="flex gap-1">
                      {[1, 2, 3, 4].map((i) => (
                        <div
                          key={i}
                          className={`h-1 flex-1 rounded-full transition-all duration-300 ${i <= strength.score ? STRENGTH_COLORS[strength.score] : 'bg-white/10'}`}
                        />
                      ))}
                    </div>
                    <p className={`text-xs ${strength.score <= 2 ? 'text-orange-400' : 'text-emerald-400'}`}>
                      {strength.label}
                    </p>
                  </div>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="confirm" className="text-sm font-medium" style={{ color: 'rgba(255,255,255,0.70)' }}>
                  Confirm Password
                </Label>
                <div className="relative">
                  <Lock size={15} className="absolute left-3.5 top-1/2 -translate-y-1/2" style={{ color: 'rgba(255,255,255,0.28)' }} />
                  <Input
                    id="confirm"
                    type={showConfirm ? 'text' : 'password'}
                    autoComplete="new-password"
                    placeholder="••••••••"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    onFocus={handleInputFocus}
                    className={`pl-10 pr-11 h-11 bg-white/[0.05] border-white/10 text-white placeholder:text-white/25 focus-visible:border-violet-500/50 focus-visible:ring-violet-500/25 ${confirmPassword && !passwordsMatch ? 'border-red-500/40' : ''}`}
                    style={{ scrollMarginBottom: '4rem' }}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirm(!showConfirm)}
                    className="absolute right-1 top-1/2 -translate-y-1/2 min-w-[44px] min-h-[44px] flex items-center justify-center pass-toggle-btn"
                  >
                    {showConfirm ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
                {confirmPassword && !passwordsMatch && (
                  <p className="text-xs text-red-400">Passwords don't match</p>
                )}
              </div>

              <div className="flex items-start gap-1 py-1">
                <button
                  type="button"
                  onClick={() => setAgreed(!agreed)}
                  className="-ml-3 p-3 min-w-[44px] min-h-[44px] rounded flex-shrink-0 flex items-center justify-center transition-all cursor-pointer"
                  aria-label="Agree to terms"
                >
                  <span
                    className={`w-4 h-4 rounded border flex items-center justify-center transition-all ${agreed ? 'border-violet-500' : 'border-white/25 bg-white/5'}`}
                    style={agreed ? { background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' } : {}}
                  >
                    {agreed && <svg width="10" height="8" viewBox="0 0 10 8" fill="none"><path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                  </span>
                </button>
                <span className="text-xs" style={{ color: 'rgba(255,255,255,0.65)' }}>
                  I agree to the{' '}
                  <Link to="/terms" target="_blank" rel="noopener noreferrer" className="font-medium transition-colors" style={{ color: '#a78bfa' }}>Terms</Link>
                  {' '}and{' '}
                  <Link to="/privacy" target="_blank" rel="noopener noreferrer" className="font-medium transition-colors" style={{ color: '#a78bfa' }}>Privacy Policy</Link>
                </span>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full flex items-center justify-center gap-2 h-11 rounded-xl text-sm font-bold text-white transition-all duration-150 active:scale-[0.97] disabled:opacity-60 btn-gradient"
                data-testid="auth-submit-button"
              >
                {loading ? <Loader2 size={17} className="animate-spin" /> : null}
                {loading ? 'Creating account…' : 'Create Account'}
              </button>
            </form>

            <p className="text-center text-sm mt-6" style={{ color: 'rgba(255,255,255,0.65)' }}>
              Already have an account?{' '}
              <Link to="/login" className="font-semibold auth-link">
                Sign in
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
