import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, Lock, Eye, EyeOff, Loader2, MessageSquare, BarChart3, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from '@/context/AuthContext';
import { toast } from 'sonner';
import { LogoFull } from '@/components/Logo';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();

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
      {/* Left panel - desktop only */}
      <div className="hidden lg:flex lg:w-1/2 relative futuristic-bg grid-overlay flex-col items-center justify-center p-12">
        <div className="max-w-md anim-slide-left">
          <Link to="/" className="flex items-center gap-3 mb-12">
            <LogoFull size="md" textClassName="text-white text-2xl" />
          </Link>
          <h2 className="text-3xl font-semibold text-white mb-4">Your AI tutor for AHSEC exams</h2>
          <p className="text-white/60 mb-10">Get instant, syllabus-aligned answers for Class 11-12 subjects. Study smarter, not harder.</p>
          <div className="space-y-4">
            {[
              { icon: null,         title: 'Structured Syllabus', desc: 'AHSEC Class 11 & 12, all streams' },
              { icon: MessageSquare, title: 'AI Tutor Chat', desc: 'Ask questions, get exam-ready answers' },
              { icon: BarChart3,    title: 'Track Progress', desc: 'Monitor your learning with credits' },
            ].map(({ icon: Icon, title, desc }, i) => (
              <div key={title} className="flex items-start gap-3 glass-card rounded-xl p-4 hover:border-violet-500/30 transition-all duration-300 hover:-translate-y-0.5" style={{ animationDelay: `${0.2 + i * 0.1}s`, animation: `slideInLeft 0.6s cubic-bezier(0.16,1,0.3,1) both ${0.3 + i * 0.12}s` }}>
                <div className="w-8 h-8 rounded-lg bg-violet-600/20 flex items-center justify-center flex-shrink-0 mt-0.5 overflow-hidden">
                  {Icon ? (
                    <Icon size={16} className="text-violet-400" />
                  ) : (
                    <img src="/logo.png" alt="Syrabit.ai" className="w-6 h-6 rounded object-cover" />
                  )}
                </div>
                <div>
                  <p className="text-white text-sm font-medium">{title}</p>
                  <p className="text-white/50 text-xs mt-0.5">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right panel - auth form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-6">
        <div className="w-full max-w-sm anim-slide-right">
          {/* Mobile logo */}
          <Link to="/" className="flex items-center gap-2 mb-8 lg:hidden">
            <LogoFull size="sm" textClassName="text-white" />
          </Link>

          <div className="glass-card rounded-2xl p-6 border border-white/10 anim-scale-in" style={{ animationDelay: '0.15s' }}>
            <div className="mb-6">
              <h1 className="text-2xl font-semibold text-white">Welcome back</h1>
              <p className="text-white/50 text-sm mt-1">Sign in to your account</p>
            </div>

            {error && (
              <div className="flex items-center gap-2 text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl p-3 mb-4 text-sm">
                <AlertCircle size={16} />
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
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
              </div>

              <div className="flex justify-end">
                <Link to="/reset-password" className="text-xs text-violet-400 hover:text-violet-300">
                  Forgot password?
                </Link>
              </div>

              <Button
                type="submit"
                disabled={loading}
                className="w-full bg-violet-600 hover:bg-violet-500 text-white shadow-lg shadow-violet-500/25 h-11 btn-glow"
                data-testid="auth-submit-button"
              >
                {loading ? <Loader2 size={18} className="animate-spin mr-2" /> : null}
                {loading ? 'Signing in...' : 'Sign In'}
              </Button>
            </form>

            <p className="text-center text-white/50 text-sm mt-4">
              Don't have an account?{' '}
              <Link to="/signup" className="text-violet-400 hover:text-violet-300 font-medium">
                Sign up
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
