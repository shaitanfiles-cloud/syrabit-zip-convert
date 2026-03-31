import { AnimatePresence, motion } from 'framer-motion';
import { X, CheckCircle, Loader2 } from 'lucide-react';
import { PLANS, PLAN_FEATURES } from './shared';
import { DOC_ACCESS_CONFIG } from '@/utils/plans';

export default function PaymentModal({
  showPaymentModal, paymentPlan, paymentLoading,
  setShowPaymentModal, handleRazorpayCheckout,
}) {
  return (
    <AnimatePresence>
      {showPaymentModal && paymentPlan && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)' }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowPaymentModal(false); }}
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
              <h3 className="font-semibold text-foreground">Upgrade to {PLANS[paymentPlan].label}</h3>
              <button onClick={() => setShowPaymentModal(false)} className="text-muted-foreground hover:text-foreground p-1 rounded-lg hover:bg-accent/40">
                <X size={16} />
              </button>
            </div>

            <div className="rounded-xl p-4 text-center"
              style={{ background: 'rgba(124,58,237,0.08)', border: '1px solid rgba(139,92,246,0.20)' }}>
              <p className="text-3xl font-bold" style={{ color: paymentPlan === 'pro' ? '#f59e0b' : 'hsl(var(--primary))' }}>
                {PLANS[paymentPlan].price}
              </p>
              <p className="text-muted-foreground text-sm">{PLANS[paymentPlan].period.trim()}</p>
              <p className="text-foreground font-medium mt-1">
                {PLANS[paymentPlan].credits.toLocaleString()} AI credits
              </p>
              <p className={`text-sm font-semibold mt-1 ${DOC_ACCESS_CONFIG[PLANS[paymentPlan].docAccess]?.color}`}>
                {DOC_ACCESS_CONFIG[PLANS[paymentPlan].docAccess]?.icon} {DOC_ACCESS_CONFIG[PLANS[paymentPlan].docAccess]?.label}
              </p>
            </div>

            <ul className="space-y-2">
              {PLAN_FEATURES[paymentPlan].map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm text-muted-foreground/80">
                  <CheckCircle size={14} className="text-emerald-400 flex-shrink-0" />
                  {f}
                </li>
              ))}
            </ul>

            <div className="space-y-3">
              <div className="rounded-xl px-4 py-2.5 flex items-center gap-2.5 text-xs text-muted-foreground"
                style={{ background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.14)' }}>
                <span className="text-lg">📱</span>
                <span>Pay using any UPI app — Google Pay, PhonePe, Paytm, or scan the QR code</span>
              </div>

              <button
                onClick={handleRazorpayCheckout}
                disabled={paymentLoading}
                className="w-full h-12 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2.5 transition-all hover:opacity-90 active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
                style={{
                  background: paymentPlan === 'pro'
                    ? 'linear-gradient(135deg,#d97706,#f59e0b)'
                    : 'linear-gradient(135deg,#7c3aed,#8b5cf6)',
                  boxShadow: paymentPlan === 'pro'
                    ? '0 4px 20px rgba(245,158,11,0.30)'
                    : '0 4px 20px rgba(124,58,237,0.30)',
                }}
                data-testid="payment-confirm-button"
              >
                {paymentLoading ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <span className="text-base">🔗</span>
                )}
                {paymentLoading ? 'Opening UPI payment…' : `Pay ${PLANS[paymentPlan]?.price} via UPI / Scanner`}
              </button>
            </div>

            <p className="text-center text-xs text-muted-foreground/40">
              Secured by Razorpay · Supports all UPI apps & QR scanner
            </p>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
