import { useState, useEffect } from 'react';
import { CheckCircle2, Eye, EyeOff, TestTube2, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { adminGetApiConfig, adminUpdateApiConfig } from '@/utils/api';
import axios from 'axios';

export default function AdminGoogleAuth({ adminToken }) {
  const [clientId, setClientId]     = useState('');
  const [clientSecret, setSecret]   = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [enabled, setEnabled]       = useState(false);
  const [testing, setTesting]       = useState(false);
  const [result, setResult]         = useState(null);
  const [saving, setSaving]         = useState(false);
  const [loading, setLoading]       = useState(true);
  const [fullConfig, setFullConfig]  = useState(null);

  const redirectUri = `${window.location.origin}/auth/v1/callback`;

  useEffect(() => {
    if (!adminToken) return;
    adminGetApiConfig(adminToken)
      .then((res) => {
        const cfg = res.data;
        setFullConfig(cfg);
        setClientId(cfg.google_auth?.client_id || '');
        setSecret(cfg.google_auth?.client_secret || '');
        setEnabled(cfg.google_auth?.enabled || false);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [adminToken]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = {
        ...(fullConfig || {}),
        google_auth: {
          client_id: clientId,
          client_secret: clientSecret,
          enabled,
        },
      };
      await adminUpdateApiConfig(adminToken, payload);
      setFullConfig(payload);
      toast.success('Google Auth configuration saved');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to save config');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!clientId) { toast.error('Client ID required'); return; }
    setTesting(true); setResult(null);
    try {
      await axios.get('https://accounts.google.com/.well-known/openid-configuration');
      setResult({ ok: true });
      toast.success('Google OAuth endpoint reachable');
    } catch { setResult({ ok: false, error: 'Google endpoint unreachable' }); } finally { setTesting(false); }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-white/40 text-sm py-8">
        <Loader2 size={16} className="animate-spin" /> Loading Google Auth configuration...
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h2 className="text-lg font-bold text-white">Google OAuth Configuration</h2>
        <p className="text-sm text-white/40 mt-0.5">Enable one-click Google login for students</p>
      </div>

      <div className="rounded-xl p-4" style={{ background: 'rgba(59,130,246,0.06)', border: '1px solid rgba(59,130,246,0.15)' }}>
        <p className="text-sm text-blue-300 font-medium mb-3">Setup instructions</p>
        <ol className="space-y-2">
          {[
            'Go to Google Cloud Console → Credentials',
            'Create OAuth 2.0 Client ID (Web application)',
            `Add redirect URI: ${redirectUri}`,
            'Copy Client ID and Client Secret below',
            'Toggle Enable Google Login and click Save',
          ].map((step, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-blue-200/70">
              <span className="w-5 h-5 rounded-full bg-blue-500/20 flex items-center justify-center text-[10px] font-bold text-blue-400 flex-shrink-0 mt-0.5">{i+1}</span>
              {step}
            </li>
          ))}
        </ol>
      </div>

      <div className="rounded-2xl border border-white/6 p-5 space-y-4" style={{ background: 'rgba(255,255,255,0.02)' }}>
        <div>
          <label className="text-xs text-white/40 block mb-1">Google Client ID</label>
          <input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="xxx.apps.googleusercontent.com"
            className="w-full h-9 px-3 rounded-xl text-sm text-white outline-none" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.10)' }} />
        </div>
        <div>
          <label className="text-xs text-white/40 block mb-1">Google Client Secret</label>
          <div className="relative">
            <input type={showSecret ? 'text' : 'password'} value={clientSecret} onChange={(e) => setSecret(e.target.value)} placeholder="GOCSPX-..."
              className="w-full h-9 px-3 pr-8 rounded-xl text-sm text-white font-mono outline-none" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.10)' }} />
            <button onClick={() => setShowSecret(!showSecret)} className="absolute right-2 top-1/2 -translate-y-1/2 text-white/30">
              {showSecret ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
          </div>
        </div>
        <div>
          <label className="text-xs text-white/40 block mb-1">Redirect URI (read-only)</label>
          <input readOnly value={redirectUri} className="w-full h-9 px-3 rounded-xl text-sm text-white/40 font-mono outline-none" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }} />
        </div>
        <div className="flex items-center justify-between py-2 border-t border-white/6">
          <div>
            <p className="text-sm text-white">Enable Google Login</p>
            <p className="text-xs text-white/40">Allow students to sign in with Google</p>
          </div>
          <button onClick={() => setEnabled(!enabled)}
            className="w-11 h-6 rounded-full transition-all" style={{ background: enabled ? '#7c3aed' : 'rgba(255,255,255,0.10)' }}>
            <div className={`w-5 h-5 rounded-full bg-white transition-transform mx-0.5 ${enabled ? 'translate-x-5' : 'translate-x-0'}`} />
          </button>
        </div>
        <div className="flex gap-2">
          <button onClick={handleTest} disabled={testing}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border border-white/10 text-white/60 hover:bg-white/5">
            {testing ? <Loader2 size={12} className="animate-spin" /> : <TestTube2 size={12} />} Test
          </button>
          <button onClick={handleSave} disabled={saving}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white bg-red-600 hover:bg-red-700 transition-colors">
            {saving ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />} Save Config
          </button>
        </div>
        {result && (
          <div className={`rounded-xl p-3 text-xs ${result.ok ? 'bg-emerald-500/8 border border-emerald-500/20 text-emerald-400' : 'bg-red-500/8 border border-red-500/20 text-red-400'}`}>
            {result.ok ? '✓ Google OAuth endpoint reachable' : `✗ ${result.error}`}
          </div>
        )}
      </div>
    </div>
  );
}
