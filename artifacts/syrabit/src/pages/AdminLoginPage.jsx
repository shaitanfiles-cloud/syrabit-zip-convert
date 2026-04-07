import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ShieldCheck, Mail, Lock, Eye, EyeOff, Loader2, AlertCircle,
} from 'lucide-react';
import { adminLogin } from '@/utils/api';
import { toast } from 'sonner';

export default function AdminLoginPage() {
  const navigate = useNavigate();
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState('');

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await adminLogin(email, password);
      localStorage.setItem('admin_token', res.data.access_token);
      toast.success(`Welcome back, ${res.data.name || 'Admin'}!`, {
        description: 'Admin session started',
      });
      navigate('/admin');
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid credentials');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4 relative overflow-hidden"
      style={{ background: 'linear-gradient(145deg, #050510 0%, #0a0a1a 50%, #080816 100%)' }}>
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[600px] rounded-full opacity-[0.03]"
          style={{ background: 'radial-gradient(circle, #7c3aed 0%, transparent 70%)' }} />
      </div>

      <div className="w-full max-w-sm space-y-4 relative">
        <div className="text-center mb-8">
          <div className="relative inline-block mb-4">
            <div className="absolute -inset-3 rounded-2xl blur-2xl opacity-20" style={{ background: 'radial-gradient(circle, #7c3aed 0%, transparent 70%)' }} />
            <img src="/logo.webp" alt="Syrabit.ai" width="56" height="56"
              className="relative w-14 h-14 rounded-2xl mx-auto object-cover"
              style={{ boxShadow: '0 0 30px rgba(124,58,237,0.2), 0 0 60px rgba(124,58,237,0.08)' }} />
          </div>
          <h1 className="text-lg font-semibold text-white tracking-tight">Administrator Access</h1>
          <p className="text-white/30 text-sm mt-1">Syrabit.ai Control Center</p>
        </div>

        <div
          className="rounded-2xl p-6"
          style={{
            background: 'rgba(15,15,30,0.7)',
            border: '1px solid rgba(255,255,255,0.06)',
            backdropFilter: 'blur(20px)',
          }}
        >
          {error && (
            <div className="flex items-center gap-2 text-red-400 rounded-xl p-3 mb-4 text-sm"
              style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)' }}>
              <AlertCircle size={15} />
              {error}
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-white/40 text-xs font-medium">Email</label>
              <div className="relative">
                <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/20" />
                <input
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@syrabit.ai"
                  className="w-full pl-9 pr-3 h-10 rounded-xl text-sm text-white outline-none transition-all focus:ring-1 focus:ring-violet-500/30"
                  style={{
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(255,255,255,0.06)',
                  }}
                  required
                  data-testid="admin-email-input"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-white/40 text-xs font-medium">Password</label>
              <div className="relative">
                <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/20" />
                <input
                  type={showPass ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full pl-9 pr-10 h-10 rounded-xl text-sm text-white outline-none transition-all focus:ring-1 focus:ring-violet-500/30"
                  style={{
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(255,255,255,0.06)',
                  }}
                  required
                  data-testid="admin-password-input"
                />
                <button
                  type="button"
                  onClick={() => setShowPass(!showPass)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-white/20 hover:text-white/40 transition-colors"
                >
                  {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 h-11 rounded-xl text-sm font-semibold text-white transition-all hover:opacity-90 active:scale-[0.98] disabled:opacity-50"
              style={{
                background: 'linear-gradient(135deg, #6d28d9, #7c3aed)',
                boxShadow: '0 4px 20px rgba(124,58,237,0.25), 0 0 40px rgba(124,58,237,0.08)',
              }}
              data-testid="admin-login-submit-button"
            >
              {loading
                ? <><Loader2 size={15} className="animate-spin" /> Signing in...</>
                : <><ShieldCheck size={15} /> Sign In Securely</>
              }
            </button>
          </form>

          <p className="text-center text-white/15 text-xs mt-5 flex items-center justify-center gap-1.5">
            <ShieldCheck size={10} />
            Protected by HMAC authentication · 8-hour session
          </p>
        </div>
      </div>
    </div>
  );
}
