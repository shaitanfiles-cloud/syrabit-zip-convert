import { X, Zap, CreditCard, Loader2 } from 'lucide-react';
import { TOPUP_OPTIONS } from './shared';

export default function TopUpModal({
  showTopUpModal, topUpCredits, setTopUpCredits,
  topUpLoading, planInfo, creditsRemaining,
  setShowTopUpModal, handleTopUpCheckout,
}) {
  if (!showTopUpModal) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) setShowTopUpModal(false); }}
    >
      <div
        className="w-full max-w-sm rounded-2xl p-5 space-y-4"
        style={{ background: 'hsl(var(--card))', border: '1px solid rgba(139,92,246,0.25)' }}
      >
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-foreground">Buy More Credits</h3>
          <button onClick={() => setShowTopUpModal(false)} className="text-muted-foreground hover:text-foreground p-1 rounded-lg hover:bg-accent/40">
            <X size={16} />
          </button>
        </div>

        <p className="text-sm text-muted-foreground">
          Add credits to your <span className="font-semibold text-foreground">{planInfo.label}</span> plan.
          Current balance: <span className="font-bold" style={{ color: 'hsl(var(--primary))' }}>{creditsRemaining}</span> credits
        </p>

        <div className="grid grid-cols-2 gap-2">
          {TOPUP_OPTIONS.map((opt) => (
            <button
              key={opt.credits}
              onClick={() => setTopUpCredits(opt.credits)}
              className={`rounded-xl p-3 text-center border transition-all ${
                topUpCredits === opt.credits
                  ? 'border-violet-500 bg-violet-500/15'
                  : 'border-border hover:border-violet-500/30 bg-card'
              }`}
            >
              <div className="flex items-center justify-center gap-1 mb-1">
                <Zap size={12} style={{ color: 'hsl(var(--primary))' }} />
                <span className="text-sm font-bold text-foreground">{opt.credits}</span>
              </div>
              <p className="text-xs text-muted-foreground">{opt.price}</p>
            </button>
          ))}
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => setShowTopUpModal(false)}
            className="flex-1 h-9 rounded-xl text-sm font-medium text-muted-foreground border border-border hover:bg-accent/40 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleTopUpCheckout}
            disabled={topUpLoading}
            className="flex-1 h-9 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-1.5 transition-all hover:opacity-90 disabled:opacity-50"
            style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' }}
          >
            {topUpLoading ? <Loader2 size={14} className="animate-spin" /> : <CreditCard size={14} />}
            Buy Now
          </button>
        </div>
      </div>
    </div>
  );
}
