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
      // Token is automatically set in httpOnly cookie by backend
      // No need to store in sessionStorage (security best practice)
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
    <div className="min-h-screen flex items-center justify-center bg-slate-950 p-4">
      <div className="w-full max-w-sm space-y-4">
        {/* Header mark */}
        <div className="text-center mb-6">
          <img src="/logo.png" alt="Syrabit.ai" className="w-14 h-14 rounded-2xl mx-auto mb-3 object-cover" style={{ boxShadow: '0 0 24px rgba(99,102,241,0.15)' }} />
          <h1 className="text-lg font-semibold text-white">Administrator Access</h1>
          <p className="text-slate-500 text-sm mt-0.5">Syrabit.ai Control Panel</p>
        </div>

        {/* Login form */}
        <div
          className="rounded-2xl p-6"
          style={{
            background: '#111827',
            border: '1px solid rgba(255,255,255,0.07)',
          }}
        >
          {error && (
            <div className="flex items-center gap-2 text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl p-3 mb-4 text-sm">
              <AlertCircle size={15} />
              {error}
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-4">
            {/* Email */}
            <div className="space-y-1.5">
              <label className="text-slate-400 text-xs font-medium">Email</label>
              <div className="relative">
                <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-600" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="admin@syrabit.ai"
                  className="w-full pl-9 pr-3 h-10 rounded-lg text-sm text-white outline-none transition-all"
                  style={{
                    background: '#1f2937',
                    border: '1px solid rgba(255,255,255,0.08)',
                  }}
                  required
                  data-testid="admin-email-input"
                />
              </div>
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label className="text-slate-400 text-xs font-medium">Password</label>
              <div className="relative">
                <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-600" />
                <input
                  type={showPass ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full pl-9 pr-10 h-10 rounded-lg text-sm text-white outline-none transition-all"
                  style={{
                    background: '#1f2937',
                    border: '1px solid rgba(255,255,255,0.08)',
                  }}
                  required
                  data-testid="admin-password-input"
                />
                <button
                  type="button"
                  onClick={() => setShowPass(!showPass)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400 transition-colors"
                >
                  {showPass ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 h-10 rounded-xl text-sm font-semibold text-white transition-all hover:opacity-90 active:scale-[0.98] disabled:opacity-60"
              style={{
                background: 'linear-gradient(135deg, #4338ca, #6366f1)',
                boxShadow: '0 4px 16px rgba(99,102,241,0.3)',
              }}
              data-testid="admin-login-submit-button"
            >
              {loading
                ? <><Loader2 size={15} className="animate-spin" /> Signing in...</>
                : <><ShieldCheck size={15} /> Sign In Securely</>
              }
            </button>
          </form>

          <p className="text-center text-slate-700 text-xs mt-4 flex items-center justify-center gap-1.5">
            <ShieldCheck size={11} />
            Protected by HMAC authentication · 8-hour session
          </p>
        </div>
      </div>
    </div>
  );
}
