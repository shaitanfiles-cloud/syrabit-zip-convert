import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ShieldOff, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';
import { getAdsOptOut, setAdsOptOut } from '@/utils/adsConfig';

export default function PrivacyControls() {
  const [optedOut, setOptedOut] = useState(false);

  useEffect(() => {
    setOptedOut(getAdsOptOut());
  }, []);

  const handleToggle = () => {
    const next = !optedOut;
    setAdsOptOut(next);
    setOptedOut(next);
    toast.success(
      next
        ? 'Ads disabled — takes effect on next page load'
        : 'Ads re-enabled — thanks for supporting Syrabit'
    );
  };

  return (
    <div className="glass-card rounded-2xl overflow-hidden" data-testid="privacy-controls">
      <div className="px-4 py-3 border-b border-border">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Privacy
        </p>
      </div>
      <div className="p-4 space-y-3">
        <div
          className="flex items-start gap-3 p-3 rounded-xl"
          style={{
            background: 'rgba(124,58,237,0.06)',
            border: '1px solid rgba(139,92,246,0.18)',
          }}
        >
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
            style={{ background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.25)' }}
          >
            <ShieldOff size={16} style={{ color: 'hsl(var(--primary))' }} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-foreground">Opt out of ads</p>
            <p className="text-xs text-muted-foreground/70 mt-0.5">
              Stop ad scripts from loading on your device. Your preference is stored locally
              and applies on the next page you open.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={optedOut}
            aria-label="Opt out of ads"
            onClick={handleToggle}
            data-testid="ads-optout-toggle"
            className="relative flex-shrink-0 w-11 h-6 rounded-full transition-colors"
            style={{
              background: optedOut ? 'hsl(var(--primary))' : 'rgba(148,163,184,0.35)',
            }}
          >
            <span
              className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform shadow"
              style={{ transform: optedOut ? 'translateX(22px)' : 'translateX(2px)' }}
            />
          </button>
        </div>

        <Link
          to="/privacy"
          className="flex items-center justify-between px-3 py-2 rounded-xl text-xs text-muted-foreground hover:bg-foreground/5 transition-colors"
        >
          <span>Read full privacy policy</span>
          <ChevronRight size={14} />
        </Link>
      </div>
    </div>
  );
}
