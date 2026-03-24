import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, Lock, Eye, EyeOff, Loader2, User, CheckCircle, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
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
      {/* Left panel */}
      <div className="hidden lg:flex lg:w-1/2 relative futuristic-bg grid-overlay flex-col items-center justify-center p-12">
        <div className="max-w-md anim-slide-left">
          <Link to="/" className="flex items-center gap-3 mb-12">
            <LogoFull size="md" textClassName="text-white text-2xl" />
          </Link>
          <h2 className="text-3xl font-semibold text-white mb-4">For AHSEC & Degree students</h2>
          <p className="text-white/60 mb-10">Start your AI-powered exam prep journey today.</p>
          <div className="space-y-3">
            {[
              'Browse all 42 subjects — free forever',
              'Starter: 300 credits for just ₹99',
              'AI tutor for AHSEC & Degree programs',
              'Upgrade anytime — no lock-in',
            ].map((perk, i) => (
              <div key={perk} className="flex items-center gap-3" style={{ animation: `slideInLeft 0.6s cubic-bezier(0.16,1,0.3,1) both ${0.3 + i * 0.1}s` }}>
                <CheckCircle size={18} className="text-emerald-400 flex-shrink-0" aria-hidden="true" />
                <span className="text-white/80 text-sm">{perk}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right panel */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-6">
        <div className="w-full max-w-sm anim-slide-right">
          <Link to="/" className="flex items-center gap-2 mb-8 lg:hidden">
            <LogoFull size="sm" textClassName="text-white" />
          </Link>

          <div className="glass-card rounded-2xl p-6 border border-white/10 anim-scale-in" style={{ animationDelay: '0.15s' }}>
            <div className="mb-6">
              <h1 className="text-2xl font-semibold text-white">Create your account</h1>
              <p className="text-white/50 text-sm mt-1">Start for free, no credit card required</p>
            </div>

            {error && (
              <div className="flex items-center gap-2 text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl p-3 mb-4 text-sm">
                <AlertCircle size={16} />
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="name" className="text-white/80 text-sm">Full Name</Label>
                <div className="relative">
                  <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
                  <Input
                    id="name"
                    placeholder="Your name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="pl-9 bg-white/5 border-white/15 text-white placeholder:text-white/30 focus:border-violet-500 input-glow"
                    required
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="email" className="text-white/80 text-sm">Email</Label>
                <div className="relative">
                  <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
                  <Input
                    id="email"
                    type="email"
                    placeholder="your@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="pl-9 bg-white/5 border-white/15 text-white placeholder:text-white/30 focus:border-violet-500 input-glow"
                    required
                    data-testid="auth-email-input"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password" className="text-white/80 text-sm">Password</Label>
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
                  <Input
                    id="password"
                    type={showPass ? 'text' : 'password'}
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-9 pr-10 bg-white/5 border-white/15 text-white placeholder:text-white/30 focus:border-violet-500 input-glow"
                    required
                    data-testid="auth-password-input"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPass(!showPass)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60"
                  >
                    {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                {password && (
                  <div className="space-y-1">
                    <div className="flex gap-1">
                      {[1, 2, 3, 4].map((i) => (
                        <div
                          key={i}
                          className={`h-1 flex-1 rounded-full transition-colors ${i <= strength.score ? STRENGTH_COLORS[strength.score] : 'bg-white/10'}`}
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
                <Label htmlFor="confirm" className="text-white/80 text-sm">Confirm Password</Label>
                <div className="relative">
                  <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
                  <Input
                    id="confirm"
                    type={showConfirm ? 'text' : 'password'}
                    placeholder="••••••••"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className={`pl-9 pr-10 bg-white/5 border-white/15 text-white placeholder:text-white/30 focus:border-violet-500 input-glow ${confirmPassword && !passwordsMatch ? 'border-red-500/50' : ''}`}
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirm(!showConfirm)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60"
                  >
                    {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
                {confirmPassword && !passwordsMatch && (
                  <p className="text-xs text-red-400">Passwords don't match</p>
                )}
              </div>

              <div className="flex items-start gap-3">
                <button
                  type="button"
                  onClick={() => setAgreed(!agreed)}
                  className={`mt-0.5 w-4 h-4 rounded flex-shrink-0 border flex items-center justify-center transition-colors cursor-pointer ${agreed ? 'bg-violet-600 border-violet-600' : 'border-white/30 bg-white/5'}`}
                  aria-label="Agree to terms"
                >
                  {agreed && <svg width="10" height="8" viewBox="0 0 10 8" fill="none"><path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                </button>
                <span className="text-xs text-white/50">
                  I agree to the{' '}
                  <Link to="/terms" target="_blank" rel="noopener noreferrer" className="text-violet-400 hover:text-violet-300">Terms</Link>
                  {' '}and{' '}
                  <Link to="/privacy" target="_blank" rel="noopener noreferrer" className="text-violet-400 hover:text-violet-300">Privacy Policy</Link>
                </span>
              </div>

              <Button
                type="submit"
                disabled={loading}
                className="w-full bg-violet-600 hover:bg-violet-500 text-white shadow-lg shadow-violet-500/25 h-11 btn-glow"
                data-testid="auth-submit-button"
              >
                {loading ? <Loader2 size={18} className="animate-spin mr-2" /> : null}
                {loading ? 'Creating account...' : 'Create Account'}
              </Button>
            </form>

            <p className="text-center text-white/50 text-sm mt-4">
              Already have an account?{' '}
              <Link to="/login" className="text-violet-400 hover:text-violet-300 font-medium">
                Sign in
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
