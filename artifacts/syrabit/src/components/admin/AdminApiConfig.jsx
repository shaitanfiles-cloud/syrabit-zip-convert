import { useState, useEffect } from 'react';
import { Key, Zap, CreditCard, Mail, Bell, BarChart3, Shield, CheckCircle2, Eye, EyeOff, TestTube2, Loader2, Database } from 'lucide-react';
import AdminQuickLinks from './AdminQuickLinks';
import { toast } from 'sonner';
import { adminGetApiConfig, adminUpdateApiConfig } from '@/utils/api';
import axios from 'axios';

const API_BASE = `${import.meta.env.VITE_BACKEND_URL || ''}/api`;

const adminHeaders = (token) => {
  const isRealJwt = token && typeof token === 'string' && token.split('.').length === 3;
  return isRealJwt ? { Authorization: `Bearer ${token}` } : {};
};

const SERVICES = [
  { id: 'groq',    icon: Zap,        label: 'Groq AI',          accent: 'violet', desc: 'Llama 3.1 — AI brain' },
  { id: 'supabase',icon: Database,   label: 'Supabase',         accent: 'cyan',   desc: 'Users & conversations DB' },
  { id: 'payment', icon: CreditCard, label: 'Payments',          accent: 'emerald', desc: 'Razorpay / Stripe' },
  { id: 'email',   icon: Mail,       label: 'Email',             accent: 'blue',   desc: 'Resend / SendGrid' },
  { id: 'push',    icon: Bell,       label: 'Push',              accent: 'orange', desc: 'OneSignal / FCM' },
  { id: 'analytics',icon: BarChart3, label: 'Analytics',         accent: 'pink',   desc: 'PostHog / GA4' },
  { id: 'auth',    icon: Shield,     label: 'Google Auth',       accent: 'red',    desc: 'OAuth 2.0' },
];

const ACCENT = {
  violet: { text: 'text-violet-400', bg: 'bg-violet-500/10', border: 'border-violet-500/30', btn: 'bg-violet-600 hover:bg-violet-700' },
  cyan:    { text: 'text-cyan-400',    bg: 'bg-cyan-500/10',    border: 'border-cyan-500/30',    btn: 'bg-cyan-600 hover:bg-cyan-700'    },
  emerald: { text: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', btn: 'bg-emerald-600 hover:bg-emerald-700' },
  blue:    { text: 'text-blue-400',    bg: 'bg-blue-500/10',    border: 'border-blue-500/30',    btn: 'bg-blue-600 hover:bg-blue-700'    },
  orange:  { text: 'text-orange-400',  bg: 'bg-orange-500/10',  border: 'border-orange-500/30',  btn: 'bg-orange-600 hover:bg-orange-700'},
  pink:    { text: 'text-pink-400',    bg: 'bg-pink-500/10',    border: 'border-pink-500/30',    btn: 'bg-pink-600 hover:bg-pink-700'    },
  red:     { text: 'text-red-400',     bg: 'bg-red-500/10',     border: 'border-red-500/30',     btn: 'bg-red-600 hover:bg-red-700'      },
};

function SecretInput({ value, onChange, placeholder }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input type={show ? 'text' : 'password'} value={value} onChange={onChange} placeholder={placeholder}
        className="w-full h-9 px-3 pr-8 rounded-xl text-sm text-white font-mono outline-none" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.10)' }} />
      <button onClick={() => setShow(!show)} className="absolute right-2 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60">
        {show ? <EyeOff size={13} /> : <Eye size={13} />}
      </button>
    </div>
  );
}

export default function AdminApiConfig({ adminToken, onNavigate }) {
  const [active, setActive] = useState('groq');
  const [creds, setCreds] = useState({ groqKey: '', supabaseUrl: '', supabaseServiceKey: '', supabaseAnonKey: '', razorpayKeyId: '', razorpayKeySecret: '', razorpayWebhookSecret: '', resendKey: '', oneSignalKey: '', posthogKey: '', googleClientId: '', googleClientSecret: '' });
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminGetApiConfig(adminToken)
      .then((res) => {
        const cfg = res.data;
        setCreds({
          groqKey: cfg.groq?.key || '',
          supabaseUrl: cfg.supabase?.url || '',
          supabaseServiceKey: cfg.supabase?.service_key || '',
          supabaseAnonKey: cfg.supabase?.anon_key || '',
          razorpayKeyId: cfg.payment?.razorpay_key_id || '',
          razorpayKeySecret: cfg.payment?.razorpay_key_secret || '',
          razorpayWebhookSecret: cfg.payment?.razorpay_webhook_secret || '',
          resendKey: cfg.email?.resend_key || '',
          oneSignalKey: cfg.push?.onesignal_key || '',
          posthogKey: cfg.analytics?.posthog_key || '',
          googleClientId: cfg.google_auth?.client_id || '',
          googleClientSecret: cfg.google_auth?.client_secret || '',
        });
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [adminToken]);

  const ac = SERVICES.find((s) => s.id === active);
  const colors = ACCENT[ac?.accent || 'violet'];

  const buildPayload = () => ({
    groq: { key: creds.groqKey },
    supabase: { url: creds.supabaseUrl, service_key: creds.supabaseServiceKey, anon_key: creds.supabaseAnonKey },
    payment: { razorpay_key_id: creds.razorpayKeyId, razorpay_key_secret: creds.razorpayKeySecret, razorpay_webhook_secret: creds.razorpayWebhookSecret },
    email: { resend_key: creds.resendKey },
    push: { onesignal_key: creds.oneSignalKey },
    analytics: { posthog_key: creds.posthogKey },
    google_auth: { client_id: creds.googleClientId, client_secret: creds.googleClientSecret },
  });

  const adminAxios = (method, url, data) => axios({ method, url: `${API_BASE}${url}`, data, headers: adminHeaders(adminToken), withCredentials: true });

  const handleSave = async () => {
    setSaving(true);
    try {
      if (active === 'supabase') {
        await adminAxios('post', '/admin/supabase/apply', { url: creds.supabaseUrl, service_key: creds.supabaseServiceKey, anon_key: creds.supabaseAnonKey });
        toast.success('Supabase credentials applied and verified');
      } else {
        await adminUpdateApiConfig(adminToken, buildPayload());
        toast.success(`${ac?.label} config saved`);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to save config');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true); setTestResult(null);
    try {
      if (active === 'supabase') {
        const res = await adminAxios('post', '/admin/supabase/test', { url: creds.supabaseUrl, service_key: creds.supabaseServiceKey });
        setTestResult({ ok: res.data.ok, data: res.data.message, error: res.data.error });
      } else if (active === 'groq') {
        const res = await adminAxios('get', '/health');
        const llmStatus = res.data?.dependencies?.llm?.status;
        const llmOk = llmStatus === 'ok';
        setTestResult({ ok: llmOk, data: llmOk ? 'LLM service is healthy' : `LLM status: ${llmStatus || 'unknown'}` });
      } else if (active === 'payment') {
        const res = await adminAxios('get', '/health');
        const payStatus = res.data?.dependencies?.payment?.status;
        const payOk = payStatus === 'ok';
        setTestResult({ ok: payOk, data: payOk ? 'Payment service reachable' : `Payment status: ${payStatus || 'not_configured'}` });
      } else if (active === 'auth') {
        await axios.get('https://accounts.google.com/.well-known/openid-configuration');
        setTestResult({ ok: true, data: 'Google OAuth endpoint reachable' });
      } else {
        const hasKey = active === 'email' ? creds.resendKey : active === 'push' ? creds.oneSignalKey : creds.posthogKey;
        setTestResult({ ok: !!hasKey, data: hasKey ? 'API key is configured' : 'No API key configured' });
      }
    } catch (e) {
      setTestResult({ ok: false, error: e.message });
    } finally { setTesting(false); }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-white/40 text-sm py-8">
        <Loader2 size={16} className="animate-spin" /> Loading API configuration...
      </div>
    );
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <div>
        <h2 className="text-lg font-bold text-white">API Configuration</h2>
        <p className="text-sm text-white/40 mt-0.5">Configure external service credentials and test connections</p>
      </div>

      <div className="flex gap-2 flex-wrap">
        {SERVICES.map(({id, icon: Icon, label, accent}) => {
          const c = ACCENT[accent];
          return (
            <button key={id} onClick={() => { setActive(id); setTestResult(null); }}
              className={`flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium border transition-all ${active === id ? `${c.bg} ${c.border} ${c.text}` : 'border-white/8 text-white/40 hover:text-white/60 hover:bg-white/3'}`}>
              <Icon size={13} /> {label}
            </button>
          );
        })}
      </div>

      <div className="rounded-2xl border overflow-hidden" style={{ background: 'rgba(255,255,255,0.02)', borderColor: 'rgba(255,255,255,0.07)' }}>
        <div className={`p-4 border-b ${colors.bg} ${colors.border}`}>
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${colors.bg} border ${colors.border}`}>
              {ac && <ac.icon size={18} className={colors.text} />}
            </div>
            <div>
              <p className={`font-bold ${colors.text}`}>{ac?.label}</p>
              <p className="text-xs text-white/40">{ac?.desc}</p>
            </div>
          </div>
        </div>

        <div className="p-4 space-y-4">
          {active === 'supabase' && (
            <div className="space-y-3">
              <p className="text-xs text-white/50">Connect to Supabase for user accounts and conversation storage. Find credentials in your Supabase dashboard under Settings &gt; API.</p>
              <div><label className="text-xs text-white/40 block mb-1" data-testid="label-supabase-url">Project URL</label>
                <input value={creds.supabaseUrl} onChange={(e) => setCreds((c) => ({...c, supabaseUrl: e.target.value}))} placeholder="https://xxxxx.supabase.co" data-testid="input-supabase-url" className="w-full h-9 px-3 rounded-xl text-sm text-white font-mono outline-none" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.10)' }} />
              </div>
              <div><label className="text-xs text-white/40 block mb-1" data-testid="label-supabase-service-key">Service Role Key</label>
                <SecretInput value={creds.supabaseServiceKey} onChange={(e) => setCreds((c) => ({...c, supabaseServiceKey: e.target.value}))} placeholder="eyJhbGci..." />
              </div>
              <div><label className="text-xs text-white/40 block mb-1" data-testid="label-supabase-anon-key">Anon Key (public)</label>
                <SecretInput value={creds.supabaseAnonKey} onChange={(e) => setCreds((c) => ({...c, supabaseAnonKey: e.target.value}))} placeholder="eyJhbGci..." />
              </div>
            </div>
          )}
          {active === 'groq' && (
            <div className="space-y-3">
              <p className="text-xs text-white/50">Groq API key is configured as a backend environment variable. Use the field below to override for testing.</p>
              <div><label className="text-xs text-white/40 block mb-1">GROQ_API_KEY (optional override)</label>
                <SecretInput value={creds.groqKey} onChange={(e) => setCreds((c) => ({...c, groqKey: e.target.value}))} placeholder="gsk_..." />
              </div>
            </div>
          )}
          {active === 'payment' && (
            <div className="space-y-3">
              <div><label className="text-xs text-white/40 block mb-1">Razorpay Key ID</label>
                <input value={creds.razorpayKeyId} onChange={(e) => setCreds((c) => ({...c, razorpayKeyId: e.target.value}))} placeholder="rzp_live_..." className="w-full h-9 px-3 rounded-xl text-sm text-white font-mono outline-none" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.10)' }} />
              </div>
              <div><label className="text-xs text-white/40 block mb-1">Razorpay Key Secret</label>
                <SecretInput value={creds.razorpayKeySecret} onChange={(e) => setCreds((c) => ({...c, razorpayKeySecret: e.target.value}))} placeholder="secret..." />
              </div>
              <div><label className="text-xs text-white/40 block mb-1">Razorpay Webhook Secret</label>
                <SecretInput value={creds.razorpayWebhookSecret} onChange={(e) => setCreds((c) => ({...c, razorpayWebhookSecret: e.target.value}))} placeholder="webhook_secret..." />
              </div>
            </div>
          )}
          {active === 'email' && (
            <div><label className="text-xs text-white/40 block mb-1">Resend API Key</label>
              <SecretInput value={creds.resendKey} onChange={(e) => setCreds((c) => ({...c, resendKey: e.target.value}))} placeholder="re_..." />
            </div>
          )}
          {active === 'push' && (
            <div><label className="text-xs text-white/40 block mb-1">OneSignal API Key</label>
              <SecretInput value={creds.oneSignalKey} onChange={(e) => setCreds((c) => ({...c, oneSignalKey: e.target.value}))} placeholder="os_..." />
            </div>
          )}
          {active === 'analytics' && (
            <div><label className="text-xs text-white/40 block mb-1">PostHog API Key</label>
              <SecretInput value={creds.posthogKey} onChange={(e) => setCreds((c) => ({...c, posthogKey: e.target.value}))} placeholder="phc_..." />
            </div>
          )}
          {active === 'auth' && (
            <div className="space-y-3">
              <div><label className="text-xs text-white/40 block mb-1">Google Client ID</label>
                <input value={creds.googleClientId} onChange={(e) => setCreds((c) => ({...c, googleClientId: e.target.value}))} placeholder="xxx.apps.googleusercontent.com" className="w-full h-9 px-3 rounded-xl text-sm text-white outline-none" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.10)' }} />
              </div>
              <div><label className="text-xs text-white/40 block mb-1">Google Client Secret</label>
                <SecretInput value={creds.googleClientSecret} onChange={(e) => setCreds((c) => ({...c, googleClientSecret: e.target.value}))} placeholder="GOCSPX-..." />
              </div>
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <button onClick={handleTest} disabled={testing}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium border border-white/10 text-white/60 hover:bg-white/5 transition-colors">
              {testing ? <Loader2 size={12} className="animate-spin" /> : <TestTube2 size={12} />} Test Connection
            </button>
            <button onClick={handleSave} disabled={saving}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-white ${colors.btn} transition-colors`}>
              {saving ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />} Deploy
            </button>
          </div>

          {testResult && (
            <div className={`rounded-xl p-3 text-xs ${testResult.ok ? 'bg-emerald-500/8 border border-emerald-500/20 text-emerald-400' : 'bg-red-500/8 border border-red-500/20 text-red-400'}`}>
              {testResult.ok ? `✓ ${testResult.data}` : `✗ Error: ${testResult.error || testResult.data}`}
            </div>
          )}
        </div>
      </div>
      <AdminQuickLinks links={['vertex','health','settings','googleauth','ratelimits']} onNavigate={onNavigate} />
    </div>
  );
}
