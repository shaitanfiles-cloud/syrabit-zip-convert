import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Mail, Loader2, ArrowLeft, CheckCircle, Lock, Eye, EyeOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';

import axios from 'axios';
import { LogoFull } from '@/components/Logo';

const API_BASE = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

export default function ResetPasswordPage() {
  const [email, setEmail] = useState('');
  const [token, setToken] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [showPass, setShowPass] = useState(false);
  const [step, setStep] = useState('request'); // request | confirm | done
  const [loading, setLoading] = useState(false);

  const handleRequest = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await axios.post(`${API_BASE}/auth/reset-request`, { email });
      setStep('confirm');
      toast.success('Reset token sent! Check your email or ask admin.');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await axios.post(`${API_BASE}/auth/reset-confirm`, { token, new_password: newPassword });
      setStep('done');
      toast.success('Password updated!');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Reset failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#06060e] p-4">
      <div className="w-full max-w-sm">
        <Link to="/login" className="flex items-center gap-2 mb-8">
          <LogoFull size="sm" textClassName="text-white" />
        </Link>

        <div className="glass-card rounded-2xl p-6 border border-white/10">
          {step === 'request' && (
            <>
              <div className="mb-6">
                <h1 className="text-xl font-semibold text-white">Reset Password</h1>
                <p className="text-white/50 text-sm mt-1">Enter your email — we'll send you a reset token</p>
              </div>
              <form onSubmit={handleRequest} className="space-y-4">
                <div className="space-y-1.5">
                  <Label className="text-white/80 text-sm">Email</Label>
                  <div className="relative">
                    <Mail size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
                    <Input
                      type="email"
                      autoComplete="email"
                      placeholder="your@email.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="pl-9 bg-white/5 border-white/15 text-white placeholder:text-white/30"
                      required
                    />
                  </div>
                </div>
                <Button type="submit" disabled={loading} className="w-full bg-violet-600 hover:bg-violet-500 text-white">
                  {loading ? <Loader2 size={16} className="animate-spin mr-2" /> : null}
                  Send Reset Link
                </Button>
              </form>
            </>
          )}

          {step === 'confirm' && (
            <>
              <div className="mb-6">
                <h1 className="text-xl font-semibold text-white">Enter Reset Token</h1>
                <p className="text-white/50 text-sm mt-1">Enter the token sent to your email and choose a new password</p>
                <p className="text-white/35 text-xs mt-2">Didn't receive an email? Contact admin@syrabit.ai with your email address.</p>
              </div>
              <form onSubmit={handleConfirm} className="space-y-4">
                <div className="space-y-1.5">
                  <Label className="text-white/80 text-sm">Reset Token</Label>
                  <Input
                    placeholder="Paste your reset token"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    className="bg-white/5 border-white/15 text-white placeholder:text-white/30"
                    required
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-white/80 text-sm">New Password</Label>
                  <div className="relative">
                    <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
                    <Input
                      type={showPass ? 'text' : 'password'}
                      autoComplete="new-password"
                      placeholder="••••••••"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      className="pl-9 pr-10 bg-white/5 border-white/15 text-white placeholder:text-white/30"
                      required
                      minLength={6}
                    />
                    <button type="button" onClick={() => setShowPass(!showPass)} className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30">
                      {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
                <Button type="submit" disabled={loading} className="w-full bg-violet-600 hover:bg-violet-500 text-white">
                  {loading ? <Loader2 size={16} className="animate-spin mr-2" /> : null}
                  Update Password
                </Button>
              </form>
            </>
          )}

          {step === 'done' && (
            <div className="text-center py-4">
              <CheckCircle size={48} className="text-emerald-400 mx-auto mb-4" />
              <h2 className="text-lg font-semibold text-white mb-2">Password Updated!</h2>
              <p className="text-white/50 text-sm mb-6">You can now sign in with your new password.</p>
              <Link to="/login">
                <Button className="bg-violet-600 hover:bg-violet-500 text-white">Sign In</Button>
              </Link>
            </div>
          )}

          <p className="text-center mt-4">
            <Link to="/login" className="text-violet-400 hover:text-violet-300 text-sm flex items-center justify-center gap-1">
              <ArrowLeft size={14} /> Back to Login
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
