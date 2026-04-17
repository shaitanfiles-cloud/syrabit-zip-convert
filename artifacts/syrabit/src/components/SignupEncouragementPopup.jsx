import { useState, useEffect } from 'react';
import { useAuth } from '@/context/AuthContext';
import { X, History, Zap, Sparkles } from 'lucide-react';

const VISIT_COUNT_KEY = 'syrabit:visit_count';
const SESSION_COUNTED_KEY = 'syrabit:session_counted';
const DISMISSED_KEY = 'syrabit:signup_popup_dismissed';

function getVisitCount() {
  try {
    return parseInt(localStorage.getItem(VISIT_COUNT_KEY) || '0', 10);
  } catch {
    return 0;
  }
}

function getOrCreateVisitorId() {
  try {
    let vid = localStorage.getItem('syrabit:visitor_id');
    if (!vid) {
      vid = 'v_' + Math.random().toString(36).slice(2, 11) + Date.now().toString(36);
      localStorage.setItem('syrabit:visitor_id', vid);
    }
    return vid;
  } catch {
    return null;
  }
}

function incrementVisitIfNewSession() {
  try {
    const vid = getOrCreateVisitorId();
    if (!vid) return;
    const alreadyCounted = sessionStorage.getItem(SESSION_COUNTED_KEY);
    if (!alreadyCounted) {
      const current = getVisitCount();
      localStorage.setItem(VISIT_COUNT_KEY, String(current + 1));
      sessionStorage.setItem(SESSION_COUNTED_KEY, '1');
    }
  } catch {}
}

function isDismissedThisSession() {
  try {
    return sessionStorage.getItem(DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

function dismissThisSession() {
  try {
    sessionStorage.setItem(DISMISSED_KEY, '1');
  } catch {}
}

incrementVisitIfNewSession();

const benefits = [
  { icon: History, text: 'Save your chat history across devices' },
  { icon: Zap, text: 'Get more daily credits for free' },
  { icon: Sparkles, text: 'Personalized learning experience' },
];

export default function SignupEncouragementPopup() {
  const { user, authChecked } = useAuth();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!authChecked) return;
    if (user) return;
    if (isDismissedThisSession()) return;
    if (getVisitCount() < 2) return;

    const timer = setTimeout(() => setVisible(true), 1500);
    return () => clearTimeout(timer);
  }, [user, authChecked]);

  if (!visible || !authChecked || user) return null;

  const handleDismiss = () => {
    dismissThisSession();
    setVisible(false);
  };

  const handleSignup = () => {
    dismissThisSession();
    window.location.href = '/signup';
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) handleDismiss(); }}
    >
      <div
        className="w-full max-w-sm rounded-2xl p-6 animate-in slide-in-from-bottom-4 fade-in duration-300"
        style={{ background: 'hsl(var(--card))', border: '1px solid rgba(139,92,246,0.25)' }}
      >
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center overflow-hidden"
              style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' }}
            >
              <img src="/logo-144.webp" alt="" width="36" height="36" className="w-9 h-9 object-cover" />
            </div>
            <h3 className="font-semibold text-foreground text-base">Welcome back!</h3>
          </div>
          <button
            onClick={handleDismiss}
            className="text-muted-foreground hover:text-foreground p-1 rounded-lg hover:bg-accent/40 transition-colors"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <p className="text-sm text-muted-foreground mb-4">
          Create a free account to unlock the full Syrabit experience.
        </p>

        <div className="space-y-2.5 mb-5">
          {benefits.map(({ icon: Icon, text }, i) => (
            <div key={i} className="flex items-center gap-3">
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                style={{ background: 'rgba(139,92,246,0.12)' }}
              >
                <Icon size={16} className="text-primary" />
              </div>
              <span className="text-sm text-foreground/90">{text}</span>
            </div>
          ))}
        </div>

        <button
          onClick={handleSignup}
          className="w-full h-11 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 transition-all hover:opacity-90 active:scale-[0.98]"
          style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' }}
        >
          <Sparkles size={16} />
          Sign Up Free
        </button>

        <button
          onClick={handleDismiss}
          className="w-full h-9 mt-2 rounded-xl text-sm text-muted-foreground hover:text-foreground hover:bg-accent/40 transition-colors"
        >
          Maybe later
        </button>
      </div>
    </div>
  );
}
