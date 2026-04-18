import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ShieldOff, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';
import { getAdsOptOut, setAdsOptOut } from '@/utils/adsConfig';
import { apiClient } from '@/utils/api';

export default function PrivacyControls({ profile }) {
  const [optedOut, setOptedOut] = useState(false);
  const [saving, setSaving] = useState(false);

  // Hydrate from the server-side value when the profile loads, so the
  // toggle reflects the cross-device preference instead of whatever
  // localStorage happened to hold on this device.
  useEffect(() => {
    if (profile && typeof profile.ads_opt_out === 'boolean') {
      setOptedOut(profile.ads_opt_out);
    } else {
      setOptedOut(getAdsOptOut());
    }
  }, [profile?.ads_opt_out]);

  const handleToggle = async () => {
    if (saving) return;
    const next = !optedOut;
    // Optimistic local update so the UI is instant.
    setOptedOut(next);
    setAdsOptOut(next);
    setSaving(true);
    try {
      await apiClient().patch('/user/profile', { ads_opt_out: next });
      toast.success(
        next
          ? 'Ads disabled across all your devices — takes effect on next page load'
          : 'Ads re-enabled across all your devices — thanks for supporting Syrabit'
      );
    } catch {
      // Server save failed — keep the local change but warn the user
      // that other devices won't pick it up until they're online.
      toast.warning(
        'Saved on this device, but we couldn\'t sync it across your other devices. Try again when you\'re back online.'
      );
    } finally {
      setSaving(false);
    }
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
              Stop ad scripts from loading. While you're signed in, this preference is saved to
              your account and synced across all your devices, and applies on the next page you open.
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
