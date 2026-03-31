import { AnimatePresence, motion } from 'framer-motion';
import { X, Zap, CreditCard, Loader2 } from 'lucide-react';
import { TOPUP_OPTIONS } from './shared';

export default function TopUpModal({
  showTopUpModal, topUpCredits, setTopUpCredits,
  topUpLoading, planInfo, creditsRemaining,
  setShowTopUpModal, handleTopUpCheckout,
}) {
  return (
    <AnimatePresence>
      {showTopUpModal && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowTopUpModal(false); }}
        >
          <motion.div
            className="w-full max-w-sm rounded-2xl p-5 space-y-4"
            style={{ background: 'hsl(var(--card))', border: '1px solid rgba(139,92,246,0.25)' }}
            initial={{ opacity: 0, scale: 0.95, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.18 }}
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

            <div className="space-y-2">
              {TOPUP_OPTIONS.map((opt) => (
                <button
                  key={opt.credits}
                  onClick={() => setTopUpCredits(opt.credits)}
                  className="w-full flex items-center justify-between p-3 rounded-xl transition-all text-left"
                  style={
                    topUpCredits === opt.credits
                      ? { background: 'rgba(124,58,237,0.12)', border: '1px solid rgba(139,92,246,0.40)' }
                      : { background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }
                  }
                >
                  <div className="flex items-center gap-3">
                    <Zap size={16} className={topUpCredits === opt.credits ? 'text-violet-400' : 'text-muted-foreground/50'} />
                    <div>
                      <p className="text-sm font-semibold text-foreground">{opt.label}</p>
                    </div>
                  </div>
                  <span className="text-sm font-bold" style={{ color: topUpCredits === opt.credits ? 'hsl(var(--primary))' : 'inherit' }}>
                    {opt.price}
                  </span>
                </button>
              ))}
            </div>

            <button
              onClick={handleTopUpCheckout}
              disabled={topUpLoading || !topUpCredits}
              className="w-full h-11 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 transition-all hover:opacity-90 active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
              style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)', boxShadow: '0 4px 20px rgba(124,58,237,0.30)' }}
            >
              {topUpLoading ? <Loader2 size={16} className="animate-spin" /> : <CreditCard size={16} />}
              {topUpLoading ? 'Processing…' : topUpCredits ? `Buy ${topUpCredits} credits` : 'Select a pack'}
            </button>

            <p className="text-center text-xs text-muted-foreground/40">
              Secured by Razorpay · UPI, Cards, Net Banking accepted
            </p>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
