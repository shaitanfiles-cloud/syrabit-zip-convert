/**
 * ProfilePage — /profile
 * Full spec rebuild: Gradient header, Academic details, AI Models card,
 * Usage stats 2×2, Subscription plans, Admin portal, Danger zone.
 * 17 useState + parallel data loading + edit/delete dialogs.
 */
import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  User, Mail, BookOpen, Zap, Crown, TrendingUp,
  Edit2, Save, X, Trash2, Loader2, ShieldCheck,
  Star, MessageSquare, Database, Clock, Phone,
  AlertTriangle, ChevronRight, Check, Copy,
  GraduationCap, BookMarked, Layers,
  Sparkles, Globe, CheckCircle, CreditCard,
  FileText, Plus, Calendar, Target, Lock,
} from 'lucide-react';
import { AppLayout } from '@/components/layout/AppLayout';
import { isDegreeBoard } from '@/utils/courseTypes';
import { useAuth } from '@/context/AuthContext';
import { PageTitle } from '@/components/PageTitle';
import { LogoMark } from '@/components/Logo';
import { apiClient, createPaymentOrder, verifyPayment, createCreditTopUp, verifyCreditTopUp, cmsPersonalize, cmsListPlans } from '@/utils/api';
import { toast } from 'sonner';

// ── Load Razorpay checkout.js script once ─────────────────────────────────────
function loadRazorpay() {
  return new Promise((resolve) => {
    if (window.Razorpay) { resolve(true); return; }
    const existing = document.querySelector('script[src="https://checkout.razorpay.com/v1/checkout.js"]');
    if (existing) {
      existing.onload = () => resolve(true);
      existing.onerror = () => resolve(false);
      return;
    }
    const script = document.createElement('script');
    script.src = 'https://checkout.razorpay.com/v1/checkout.js';
    script.onload  = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}

// ── Plan config ───────────────────────────────────────────────────────────────
import { DOC_ACCESS_CONFIG } from '@/utils/plans';

// ── Local plan display config (badge + color mapping) ─────────────────────────
const PLANS = {
  free:    { label: 'Free',    credits: 30,   price: '₹0',   period: '/month',    badge: 'FREE TIER',   badgeColor: 'text-slate-400 bg-slate-400/10 border-slate-400/20',  docAccess: 'zero'    },
  starter: { label: 'Starter', credits: 300,  price: '₹99',  period: ' one-time', badge: 'POPULAR',     badgeColor: 'text-violet-400 bg-violet-400/10 border-violet-400/20', docAccess: 'limited' },
  pro:     { label: 'Pro',     credits: 4000, price: '₹999', period: ' one-time', badge: 'BEST VALUE',  badgeColor: 'text-amber-400 bg-amber-400/10 border-amber-400/20',    docAccess: 'full'    },
};

// Plan hierarchy — higher number = higher tier
const PLAN_RANK = { free: 0, starter: 1, pro: 2 };

const PLAN_FEATURES = {
  free:    ['30 AI credits/month', 'All subjects access', 'Chat history (limited)', 'Zero document access'],
  starter: ['300 AI credits', 'All subjects access', 'Full chat history', 'Limited document access', 'Priority responses'],
  pro:     ['4,000 AI credits', 'Unlimited subjects access', 'Unlimited history', 'Full document access', 'All AI models'],
};

// ── Star rating component ─────────────────────────────────────────────────────
function StarRating({ value = 4, max = 5 }) {
  return (
    <div className="flex items-center gap-0.5">
      {[...Array(max)].map((_, i) => (
        <Star
          key={i}
          size={12}
          className={i < value ? 'text-amber-400 fill-amber-400' : 'text-muted-foreground/30'}
        />
      ))}
    </div>
  );
}

// ── Usage dots ────────────────────────────────────────────────────────────────
function UsageDots({ value = 3, max = 4, color = 'bg-primary' }) {
  return (
    <div className="flex items-center gap-1">
      {[...Array(max)].map((_, i) => (
        <div
          key={i}
          className={`w-2 h-2 rounded-full ${i < value ? color : 'bg-muted'}`}
        />
      ))}
    </div>
  );
}

// ── ProfilePage ───────────────────────────────────────────────────────────────
export default function ProfilePage() {
  const { user, logout, refreshUser } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // ── 17 useState ──────────────────────────────────────────────────────────
  const [profile, setProfile]               = useState(null);
  const [loading, setLoading]               = useState(true);
  const [stats, setStats]                   = useState({ conversations: 0, saved_subjects: 0, total_tokens: 0, credits_used: 0 });
  const [editField, setEditField]           = useState(null); // { key, label, value, placeholder }
  const [editValue, setEditValue]           = useState('');
  const [editLoading, setEditLoading]       = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteText, setDeleteText]         = useState('');
  const [deleting, setDeleting]             = useState(false);
  const [deletionPending, setDeletionPending] = useState(false);
  const [deletionHardAt, setDeletionHardAt] = useState(null);
  const [cancellingDelete, setCancellingDelete] = useState(false);
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [paymentPlan, setPaymentPlan]       = useState(null);
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [copiedId, setCopiedId]             = useState(false);
  const [showTopUpModal, setShowTopUpModal] = useState(false);
  const [topUpCredits, setTopUpCredits]     = useState(null);
  const [topUpLoading, setTopUpLoading]     = useState(false);
  const [myPlans, setMyPlans]               = useState([]);
  const [plansLoading, setPlansLoading]     = useState(false);
  const [genLoading, setGenLoading]         = useState(false);
  const [showGenModal, setShowGenModal]     = useState(false);
  const [genForm, setGenForm]               = useState({ subject_name: '', context: '', days: 7 });

  const editInputRef = useRef(null);

  // ── Parallel data loading ────────────────────────────────────────────────
  useEffect(() => {
    if (!user) return;
    setLoading(true);
    Promise.all([
      apiClient().get('/user/profile'),
      apiClient().get('/user/stats'),
    ])
      .then(([profileRes, statsRes]) => {
        const p = profileRes.data;
        setProfile(p);
        setStats(statsRes.data);
        if (p.status === 'pending_deletion' && p.deletion_hard_at) {
          setDeletionPending(true);
          setDeletionHardAt(p.deletion_hard_at);
        }
      })
      .catch(() => toast.error('Failed to load profile'))
      .finally(() => setLoading(false));
  }, [user]);

  // ── Load personalized plans (paid users only) ─────────────────────────────
  useEffect(() => {
    if (!profile || !['starter', 'pro'].includes(profile.plan)) return;
    setPlansLoading(true);
    cmsListPlans(profile.id)
      .then(r => setMyPlans(r.data?.plans || []))
      .catch(() => {})
      .finally(() => setPlansLoading(false));
  }, [profile]);

  // ── Generate personalized plan handler ────────────────────────────────────
  const handleGeneratePlan = async () => {
    if (!genForm.subject_name.trim() && !genForm.context.trim()) {
      toast.error('Enter a subject or describe your weak areas.');
      return;
    }
    setGenLoading(true);
    try {
      const res = await cmsPersonalize({
        subject_name: genForm.subject_name,
        context:      genForm.context,
        days:         Number(genForm.days) || 7,
        board_name:   profile?.board_name || '',
        class_name:   profile?.class_name || '',
      });
      const { url, title, id: docId, slug } = res.data;
      toast.success(`Plan created: "${title}"`, { description: 'Opening now…' });
      setMyPlans(prev => [res.data.doc, ...prev]);
      setShowGenModal(false);
      setGenForm({ subject_name: '', context: '', days: 7 });
      navigate(`/cms/${profile.id}/${slug}`);
    } catch (e) {
      const status = e.response?.status;
      if (status === 402) {
        toast.error('Upgrade to Starter or Pro to generate personalized plans.');
        setShowGenModal(false);
        setShowPaymentModal(true);
        setPaymentPlan('starter');
      } else {
        toast.error(e.response?.data?.detail || 'Plan generation failed. Try again.');
      }
    } finally {
      setGenLoading(false);
    }
  };

  // ── Auto-open payment modal from ?upgrade= query param ───────────────────
  useEffect(() => {
    const upgradePlan = searchParams.get('upgrade');
    if (upgradePlan && ['starter', 'pro'].includes(upgradePlan)) {
      setPaymentPlan(upgradePlan);
      setShowPaymentModal(true);
      setSearchParams({}, { replace: true }); // clean up URL
    }
  }, [searchParams]);

  // ── Auto-focus edit dialog input ─────────────────────────────────────────
  useEffect(() => {
    if (editField) {
      setTimeout(() => editInputRef.current?.focus(), 80);
    }
  }, [editField]);

  // ── Derived state ────────────────────────────────────────────────────────
  const getInitials = (name) =>
    (name || 'U').split(' ').map((n) => n[0]).join('').toUpperCase().slice(0, 2);

  const plan            = profile?.plan || 'free';
  const planInfo        = PLANS[plan] || PLANS.free;
  const isDegreeProfile = isDegreeBoard(profile?.board_name);
  const creditsUsed      = profile?.credits_used  ?? 0;
  const creditsLimit     = profile?.credits_limit ?? 0;
  const creditsRemaining = Math.max(0, profile?.credits_remaining ?? 0);
  const docAccess        = profile?.document_access || PLANS[plan]?.docAccess || 'zero';
  const docCfg           = DOC_ACCESS_CONFIG[docAccess] || DOC_ACCESS_CONFIG.zero;
  // Guard against NaN when free plan (0/0); creditsLimit === 0 → 0% (empty bar)
  const creditPercent = creditsLimit > 0 ? Math.min(100, (creditsUsed / creditsLimit) * 100) : 0;
  const isLowCredits  = creditsLimit > 0 && creditsRemaining <= 5;

  // Deletion hours remaining
  const getDeletionHoursLeft = () => {
    if (!deletionHardAt) return 0;
    const diff = new Date(deletionHardAt) - new Date();
    return Math.max(0, Math.floor(diff / 3600000));
  };

  // ── Save edit field ───────────────────────────────────────────────────────
  const handleSaveField = async () => {
    if (!editField || !editValue.trim()) return;
    setEditLoading(true);
    try {
      await apiClient().patch(
        '/user/profile',
        { [editField.key]: editValue.trim() }
      );
      setProfile((p) => ({ ...p, [editField.key]: editValue.trim() }));
      toast.success(`${editField.label} updated`);
      setEditField(null);
    } catch {
      toast.error('Failed to update');
    } finally {
      setEditLoading(false);
    }
  };


  // ── Delete account ────────────────────────────────────────────────────────
  const handleDeleteAccount = async () => {
    if (deleteText !== 'DELETE') return;
    setDeleting(true);
    try {
      const res = await apiClient().delete('/user/account');
      setDeletionPending(true);
      setDeletionHardAt(res.data.hard_delete_at);
      setShowDeleteConfirm(false);
      setDeleteText('');
      toast.success('Account scheduled for deletion — 72 hours to cancel');
    } catch {
      toast.error('Failed to schedule deletion');
    } finally {
      setDeleting(false);
    }
  };

  // ── Cancel deletion ───────────────────────────────────────────────────────
  const handleCancelDeletion = async () => {
    setCancellingDelete(true);
    try {
      await apiClient().post('/user/account/cancel-delete', {});
      setDeletionPending(false);
      setDeletionHardAt(null);
      setProfile((p) => ({ ...p, status: 'active' }));
      toast.success('Account deletion cancelled — your account is safe!');
    } catch {
      toast.error('Failed to cancel deletion');
    } finally {
      setCancellingDelete(false);
    }
  };

  // ── Copy user ID ──────────────────────────────────────────────────────────
  const handleCopyId = () => {
    navigator.clipboard.writeText(profile?.id || '');
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  // ── Razorpay checkout ─────────────────────────────────────────────────────
  const handleRazorpayCheckout = async () => {
    if (!paymentPlan) return;
    setPaymentLoading(true);

    try {
      // 1. Load Razorpay script
      const loaded = await loadRazorpay();
      if (!loaded) {
        toast.error('Failed to load payment gateway. Check your internet connection.');
        setPaymentLoading(false);
        return;
      }

      // 2. Create order on backend
      let orderData;
      try {
        const res = await createPaymentOrder(paymentPlan);
        orderData = res.data;
      } catch (err) {
        const msg = err?.response?.data?.detail || 'Payment gateway not configured. Contact admin@syrabit.ai.';
        toast.error(msg);
        setPaymentLoading(false);
        return;
      }

      // 3. Open Razorpay checkout — all payment methods
      const options = {
        key:          orderData.key_id,
        amount:       orderData.amount,
        currency:     orderData.currency,
        name:         'Syrabit.ai',
        description:  `${orderData.plan_label} Plan — ${PLANS[paymentPlan]?.credits.toLocaleString()} AI credits`,
        order_id:     orderData.order_id,
        prefill: {
          name:  profile?.name  || '',
          email: profile?.email || user?.email || '',
          contact: profile?.phone || '',
        },
        theme: { color: '#7c3aed' },
        modal: {
          ondismiss: () => setPaymentLoading(false),
        },
        handler: async (response) => {
          // 4. Verify payment on backend
          try {
            await verifyPayment({
              razorpay_order_id:   response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature:  response.razorpay_signature,
              plan:                paymentPlan,
            });
            toast.success(`🎉 ${PLANS[paymentPlan]?.label} plan activated!`, {
              description: `${PLANS[paymentPlan]?.credits.toLocaleString()} AI credits added to your account.`,
            });
            setShowPaymentModal(false);
            // Refresh profile to show new plan/credits
            await Promise.all([
              apiClient().get('/user/profile').then(r => setProfile(r.data)),
              apiClient().get('/user/stats').then(r => setStats(r.data)),
            ]);
            if (refreshUser) refreshUser();
          } catch (err) {
            toast.error('Payment received but verification failed. Please contact admin@syrabit.ai.');
          } finally {
            setPaymentLoading(false);
          }
        },
      };

      const rzp = new window.Razorpay(options);
      rzp.on('payment.failed', (response) => {
        toast.error(`Payment failed: ${response.error?.description || 'Unknown error'}`);
        setPaymentLoading(false);
      });
      rzp.open();
    } catch (err) {
      toast.error('Something went wrong. Please try again.');
      setPaymentLoading(false);
    }
  };


  // ── Credit top-up checkout ──────────────────────────────────────────────
  const TOPUP_OPTIONS = [
    { credits: 100,  price: '₹49',  label: '100 credits' },
    { credits: 500,  price: '₹199', label: '500 credits' },
    { credits: 1000, price: '₹349', label: '1,000 credits' },
  ];

  const handleTopUpCheckout = async () => {
    if (!topUpCredits) return;
    setTopUpLoading(true);
    try {
      const loaded = await loadRazorpay();
      if (!loaded) {
        toast.error('Failed to load payment gateway.');
        setTopUpLoading(false);
        return;
      }
      let orderData;
      try {
        const res = await createCreditTopUp(topUpCredits);
        orderData = res.data;
      } catch (err) {
        const msg = err?.response?.data?.detail || 'Failed to create top-up order.';
        toast.error(msg);
        setTopUpLoading(false);
        return;
      }
      const options = {
        key: orderData.key_id,
        amount: orderData.amount,
        currency: orderData.currency,
        name: 'Syrabit.ai',
        description: `Credit Top-up — ${topUpCredits} credits`,
        order_id: orderData.order_id,
        prefill: {
          name: profile?.name || '',
          email: profile?.email || user?.email || '',
          contact: profile?.phone || '',
        },
        theme: { color: '#7c3aed' },
        modal: { ondismiss: () => setTopUpLoading(false) },
        handler: async (response) => {
          try {
            await verifyCreditTopUp({
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
              credits: topUpCredits,
            });
            toast.success(`${topUpCredits} credits added to your account!`);
            setShowTopUpModal(false);
            await Promise.all([
              apiClient().get('/user/profile').then(r => setProfile(r.data)),
              apiClient().get('/user/stats').then(r => setStats(r.data)),
            ]);
            if (refreshUser) refreshUser();
          } catch {
            toast.error('Payment received but verification failed. Contact admin@syrabit.ai.');
          } finally {
            setTopUpLoading(false);
          }
        },
      };
      const rzp = new window.Razorpay(options);
      rzp.on('payment.failed', (response) => {
        toast.error(`Payment failed: ${response.error?.description || 'Unknown error'}`);
        setTopUpLoading(false);
      });
      rzp.open();
    } catch {
      toast.error('Something went wrong. Please try again.');
      setTopUpLoading(false);
    }
  };

  // ── Open edit field dialog ────────────────────────────────────────────────
  const openEdit = (key, label, placeholder) => {
    setEditField({ key, label, placeholder });
    setEditValue(profile?.[key] || '');
  };

  // ── Skeleton loading ──────────────────────────────────────────────────────
  if (loading) {
    return (
      <AppLayout pageTitle="Profile">
        <PageTitle title="Profile | Syrabit.ai" />
        <div className="max-w-lg mx-auto px-4 py-6 space-y-4 animate-pulse">
          <div className="h-48 rounded-3xl" style={{ background: 'rgba(124,58,237,0.10)' }} />
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-20 rounded-2xl" style={{ background: 'rgba(255,255,255,0.04)' }} />
          ))}
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout pageTitle="Profile">
      <PageTitle title="Profile | Syrabit.ai" />

      <div className="max-w-lg mx-auto px-4 py-6 space-y-4 pb-20 md:pb-6" data-testid="profile-page">

        {/* ═══════════════════════════════════════════════════
            SECTION 1 — GRADIENT HEADER
            ═══════════════════════════════════════════════════ */}
        <div
          className="relative rounded-3xl overflow-hidden p-6"
          style={{
            background: 'linear-gradient(135deg, rgba(124,58,237,0.25) 0%, rgba(139,92,246,0.15) 50%, rgba(6,6,14,0.5) 100%)',
            border: '1px solid rgba(139,92,246,0.25)',
            boxShadow: '0 8px 40px rgba(124,58,237,0.15)',
          }}
        >
          {/* Animated blobs */}
          <div
            className="absolute top-0 right-0 w-48 h-48 rounded-full pointer-events-none"
            style={{
              background: 'radial-gradient(circle, rgba(139,92,246,0.20), transparent 70%)',
              filter: 'blur(20px)',
              animation: 'float 6s ease-in-out infinite',
            }}
          />
          <div
            className="absolute bottom-0 left-0 w-32 h-32 rounded-full pointer-events-none"
            style={{
              background: 'radial-gradient(circle, rgba(167,139,250,0.12), transparent 70%)',
              filter: 'blur(16px)',
              animation: 'float 8s ease-in-out infinite reverse',
            }}
          />
          {/* Dot grid */}
          <div
            className="absolute inset-0 pointer-events-none opacity-[0.06]"
            style={{
              backgroundImage: 'radial-gradient(rgba(167,139,250,1) 1px, transparent 1px)',
              backgroundSize: '20px 20px',
            }}
          />

          <div className="relative z-10 flex items-start gap-4">
            {/* Avatar with orbit ring */}
            <div className="relative flex-shrink-0">
              {profile?.avatar_url ? (
                <div style={{ width: 72, height: 72 }}>
                  <img
                    src={profile.avatar_url}
                    alt={profile?.name || 'Avatar'}
                    className="w-full h-full rounded-2xl object-cover shadow-xl"
                    style={{ boxShadow: '0 0 24px rgba(139,92,246,0.4)' }}
                  />
                </div>
              ) : (
                <div
                  className="rounded-2xl flex items-center justify-center text-2xl font-bold text-white shadow-xl"
                  style={{
                    width: 72, height: 72,
                    background: 'linear-gradient(135deg, #7c3aed, #8b5cf6)',
                    boxShadow: '0 0 24px rgba(139,92,246,0.4)',
                  }}
                >
                  {getInitials(profile?.name)}
                </div>
              )}
              <div
                className="absolute pointer-events-none"
                style={{
                  inset: -6,
                  borderRadius: '50%',
                  border: '1.5px solid rgba(167,139,250,0.4)',
                  animation: 'orbit 8s linear infinite',
                }}
              />
            </div>

            {/* Name + subtitle */}
            <div className="flex-1 min-w-0">
              <h1 className="text-xl font-bold text-white truncate" style={{ textShadow: '0 0 20px rgba(167,139,250,0.4)' }}>
                {profile?.name || 'User'}
              </h1>
              <p className="text-white/50 text-sm mt-0.5 truncate">{profile?.email}</p>

              {/* Plan badge */}
              <div className="flex items-center gap-2 mt-2">
                <span
                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold border ${planInfo.badgeColor}`}
                >
                  <Crown size={10} />
                  {planInfo.label}
                </span>
                {profile?.board_name && (
                  <span className="text-xs text-white/40">{profile.board_name}</span>
                )}
              </div>
            </div>

            {/* Copy ID */}
            <button
              onClick={handleCopyId}
              className="text-white/30 hover:text-white/60 transition-colors p-1"
              title="Copy User ID"
            >
              {copiedId ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
            </button>
          </div>

          {/* 3 Stat pills */}
          <div className="relative z-10 flex items-center gap-3 mt-5">
            {[
              { icon: BookMarked, label: 'Saved',  value: stats.saved_subjects },
              { icon: MessageSquare, label: 'Chats', value: stats.conversations },
              { icon: Zap, label: 'Credits', value: creditsLimit === 0 ? 'Upgrade' : `${creditsRemaining}/${creditsLimit}` },
            ].map(({ icon: Icon, label, value }) => (
              <div
                key={label}
                className="flex-1 flex flex-col items-center p-2 rounded-xl"
                style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)' }}
              >
                <Icon size={14} className="text-white/50 mb-1" />
                <span className="text-white text-sm font-semibold">{value}</span>
                <span className="text-white/40 text-[10px]">{label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* ═══════════════════════════════════════════════════
            PENDING DELETION BANNER (conditional)
            ═══════════════════════════════════════════════════ */}
        {deletionPending && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-2xl p-4"
            style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)' }}
          >
            <div className="flex items-start gap-3">
              <Clock size={18} className="text-amber-400 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-amber-400 font-semibold text-sm">Account deletion scheduled</p>
                <p className="text-amber-400/70 text-xs mt-0.5">
                  Your account will be permanently deleted in ~{getDeletionHoursLeft()} hours.
                  All data will be erased.
                </p>
              </div>
              <button
                onClick={handleCancelDeletion}
                disabled={cancellingDelete}
                className="flex-shrink-0 px-3 py-1.5 rounded-xl text-xs font-semibold text-amber-400 border border-amber-400/30 hover:bg-amber-400/10 transition-colors"
              >
                {cancellingDelete ? <Loader2 size={12} className="animate-spin" /> : 'Cancel Deletion'}
              </button>
            </div>
          </motion.div>
        )}

        {/* ═══════════════════════════════════════════════════
            SECTION 2 — ACADEMIC DETAILS
            ═══════════════════════════════════════════════════ */}
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Academic Details</p>
          </div>
          {[
            { key: 'name',         label: 'Display Name', value: profile?.name,        icon: User,          placeholder: 'Your full name' },
            { key: 'board_name',   label: 'Board',        value: profile?.board_name,  icon: Globe,         placeholder: 'AssamBoard division (AHSEC, DEGREE or SEBA)' },
            { key: 'class_name',   label: 'Class / Sem',  value: profile?.class_name,  icon: GraduationCap, placeholder: 'e.g. Class 12, 2nd Sem' },
            { key: 'stream_name',  label: isDegreeProfile ? 'Course Type' : 'Stream', value: profile?.stream_name, icon: Layers, placeholder: isDegreeProfile ? 'e.g. Major, Minor, MDC' : 'e.g. Science (PCM), B.Com' },
            { key: 'phone',        label: 'Phone',        value: profile?.phone,       icon: Phone,         placeholder: 'Optional phone number' },
          ].map(({ key, label, value, icon: Icon, placeholder }, i, arr) => (
            <button
              key={key}
              onClick={() => openEdit(key, label, placeholder)}
              className={`w-full flex items-center gap-3 px-4 py-3.5 hover:bg-accent/30 transition-colors text-left ${
                i < arr.length - 1 ? 'border-b border-border/50' : ''
              }`}
              data-testid={`edit-field-${key}`}
            >
              <div className="w-8 h-8 rounded-xl flex items-center justify-center flex-shrink-0"
                style={{ background: 'rgba(124,58,237,0.08)', border: '1px solid rgba(139,92,246,0.15)' }}>
                <Icon size={14} style={{ color: 'hsl(var(--primary))' }} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="text-sm font-medium text-foreground truncate">{value || `Add ${label.toLowerCase()}`}</p>
              </div>
              <ChevronRight size={14} className="text-muted-foreground/50 flex-shrink-0" />
            </button>
          ))}
        </div>

        {/* ═══════════════════════════════════════════════════
            SECTION 3 — PREFERRED AI MODELS
            ═══════════════════════════════════════════════════ */}
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Preferred AI Models</p>
          </div>
          <div className="p-4 space-y-3">
            {[
              { name: 'Syrabit SLM Instant', badge: 'Fast', stars: 4, dots: 4, dotColor: 'bg-emerald-500', desc: 'Best for quick Q&A, fastest responses', available: true },
              { name: 'Syrabit MLM Versatile', badge: 'Coming Soon', stars: 5, dots: 0, dotColor: 'bg-muted', desc: 'Advanced model launching soon', available: false },
            ].map((m) => (
              <div key={m.name} className="flex items-center gap-3 p-3 rounded-xl"
                style={{ 
                  background: m.available ? 'rgba(124,58,237,0.04)' : 'rgba(100,100,100,0.04)', 
                  border: m.available ? '1px solid rgba(139,92,246,0.10)' : '1px solid rgba(150,150,150,0.10)',
                  opacity: m.available ? 1 : 0.6
                }}>
                <LogoMark size="xs" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-foreground">{m.name}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                      style={{ 
                        background: m.available ? 'rgba(139,92,246,0.12)' : 'rgba(245,158,11,0.12)', 
                        color: m.available ? 'hsl(var(--primary))' : 'rgb(245,158,11)' 
                      }}>
                      {m.badge}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground/60 truncate mt-0.5">{m.desc}</p>
                </div>
                <div className="flex flex-col items-end gap-1.5 flex-shrink-0">
                  {m.available && <StarRating value={m.stars} />}
                  {m.available && <UsageDots value={m.dots} dotColor={m.dotColor} />}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ═══════════════════════════════════════════════════
            SECTION 4 — USAGE STATS 2×2
            ═══════════════════════════════════════════════════ */}
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Lifetime Usage</p>
          </div>
          <div className="p-4">
            <div className="grid grid-cols-2 gap-3">
              {[
                { icon: Database, label: 'Total Tokens', value: stats.total_tokens > 1000 ? `${(stats.total_tokens/1000).toFixed(0)}K` : stats.total_tokens, color: 'text-blue-400', bg: 'rgba(59,130,246,0.10)' },
                { icon: Zap,      label: 'Credits Left', value: creditsRemaining,  color: isLowCredits ? 'text-amber-400' : 'text-emerald-400', bg: isLowCredits ? 'rgba(245,158,11,0.10)' : 'rgba(16,185,129,0.10)' },
                { icon: MessageSquare, label: 'Conversations', value: stats.conversations, color: 'text-violet-400', bg: 'rgba(139,92,246,0.10)' },
                { icon: BookMarked, label: 'Saved Subjects', value: stats.saved_subjects, color: 'text-pink-400', bg: 'rgba(244,63,94,0.10)' },
              ].map(({ icon: Icon, label, value, color, bg }) => (
                <div key={label} className="rounded-xl p-3" style={{ background: bg, border: `1px solid ${bg.replace('0.10', '0.20')}` }}>
                  <Icon size={18} className={`${color} mb-2`} />
                  <p className={`text-xl font-bold ${color}`}>{value}</p>
                  <p className="text-muted-foreground/60 text-xs mt-0.5">{label}</p>
                </div>
              ))}
            </div>
            {/* Credit progress bar */}
            <div className="mt-4">
              <div className="flex justify-between text-xs text-muted-foreground mb-1.5">
                <span>{creditsLimit === 0 ? 'No credits — upgrade to chat' : 'Credits used'}</span>
                <span className={isLowCredits ? 'text-amber-400' : ''}>
                  {creditsLimit === 0 ? '' : `${creditsUsed} / ${creditsLimit}`}
                </span>
              </div>
              <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(124,58,237,0.10)' }}>
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: creditsLimit === 0 ? '100%' : `${creditPercent}%`,
                    background: creditsLimit === 0
                      ? 'rgba(100,116,139,0.4)'  // gray for free plan
                      : isLowCredits
                      ? 'linear-gradient(to right, #f59e0b, #f97316)'
                      : 'linear-gradient(to right, #7c3aed, #8b5cf6)',
                    boxShadow: creditsLimit === 0 ? 'none' : isLowCredits ? '0 0 6px rgba(245,158,11,0.5)' : '0 0 6px rgba(139,92,246,0.4)',
                  }}
                />
              </div>
              {plan !== 'free' && (
                <button
                  onClick={() => setShowTopUpModal(true)}
                  className="mt-3 w-full h-8 rounded-lg text-xs font-semibold transition-all hover:opacity-90 active:scale-[0.98] flex items-center justify-center gap-1.5"
                  style={{ background: 'rgba(139,92,246,0.12)', color: 'hsl(var(--primary))', border: '1px solid rgba(139,92,246,0.25)' }}
                >
                  <Zap size={12} /> Buy More Credits
                </button>
              )}
            </div>
          </div>
        </div>

        {/* ═══════════════════════════════════════════════════
            SECTION 5 — SUBSCRIPTION
            ═══════════════════════════════════════════════════ */}
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Subscription</p>
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${planInfo.badgeColor}`}>
              {plan.toUpperCase()}
            </span>
          </div>

          <div className="p-4 space-y-4">
            {/* Current plan hero row */}
            <div className="flex items-center justify-between p-3 rounded-xl"
              style={{ background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.15)' }}>
              <div>
                <p className="text-xs text-muted-foreground">Current plan</p>
                <p className="font-bold text-foreground">{planInfo.label}</p>
              </div>
              <div className="text-right">
                <p className="text-xs text-muted-foreground">Document access</p>
                <p className={`text-sm font-semibold ${docCfg.color}`}>
                  {docCfg.icon} {docCfg.label}
                </p>
              </div>
            </div>

            {/* 3 plan cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {Object.entries(PLANS).map(([planKey, info]) => {
                const isActive    = plan === planKey;
                const isPro       = planKey === 'pro';
                const cardRank    = PLAN_RANK[planKey] ?? 0;
                const userRank    = PLAN_RANK[plan]    ?? 0;
                const isLower     = cardRank < userRank;   // already surpassed this
                const docInfo     = DOC_ACCESS_CONFIG[info.docAccess] || DOC_ACCESS_CONFIG.zero;
                return (
                  <div
                    key={planKey}
                    className="relative rounded-xl p-3 flex flex-col transition-all duration-200"
                    style={
                      isActive
                        ? { border: '1px solid rgba(139,92,246,0.50)', background: 'rgba(124,58,237,0.08)', boxShadow: '0 0 20px rgba(139,92,246,0.12)' }
                        : isLower
                        ? { border: '1px solid rgba(255,255,255,0.04)', background: 'rgba(255,255,255,0.01)', opacity: 0.6 }
                        : { border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }
                    }
                  >
                    {/* Badge */}
                    <div
                      className="absolute -top-2.5 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full text-[10px] font-bold whitespace-nowrap"
                      style={
                        isActive
                          ? { background: 'rgba(124,58,237,0.25)', color: 'hsl(var(--primary))', border: '1px solid rgba(139,92,246,0.35)' }
                          : isPro
                          ? { background: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.30)' }
                          : planKey === 'starter'
                          ? { background: 'rgba(139,92,246,0.15)', color: '#a78bfa', border: '1px solid rgba(139,92,246,0.30)' }
                          : { background: 'rgba(255,255,255,0.05)', color: 'hsl(var(--muted-foreground))', border: '1px solid rgba(255,255,255,0.08)' }
                      }
                    >
                      {isActive ? 'ACTIVE' : info.badge}
                    </div>

                    {/* Plan name */}
                    <p className="text-sm font-semibold text-foreground mt-1">{info.label}</p>

                    {/* Credits */}
                    <p className="font-bold text-2xl mt-1"
                      style={{ color: isPro ? '#f59e0b' : isLower ? 'hsl(var(--muted-foreground))' : 'hsl(var(--primary))' }}>
                      {info.credits.toLocaleString()}
                      <span className="text-xs font-normal text-muted-foreground ml-1">credits</span>
                    </p>

                    {/* Price */}
                    <p className="text-base font-semibold text-foreground mt-0.5">
                      {info.price}
                      <span className="text-xs font-normal text-muted-foreground ml-1">{info.period}</span>
                    </p>

                    {/* Document access row */}
                    <div className="flex items-center gap-1.5 mt-2 mb-1">
                      <span className={`text-[10px] font-semibold ${docInfo.color}`}>
                        {docInfo.icon} {docInfo.label}
                      </span>
                    </div>

                    {/* Features list */}
                    <ul className="mt-1 space-y-1 flex-1">
                      {PLAN_FEATURES[planKey].slice(0, 3).map((f) => (
                        <li key={f} className="flex items-center gap-1 text-[10px] text-muted-foreground/70">
                          <Check size={10} className="text-emerald-400 flex-shrink-0" aria-hidden="true" />
                          {f}
                        </li>
                      ))}
                    </ul>

                    {/* CTA */}
                    {isActive ? (
                      <div className="mt-3 w-full h-8 rounded-lg flex items-center justify-center text-xs font-medium"
                        style={{ background: 'rgba(139,92,246,0.12)', color: 'hsl(var(--primary))' }}>
                        <CheckCircle size={12} className="mr-1" aria-hidden="true" /> Current Plan
                      </div>
                    ) : isLower ? (
                      <div className="mt-3 w-full h-8 rounded-lg flex items-center justify-center text-[10px] font-medium text-muted-foreground/50"
                        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                        Included in your plan
                      </div>
                    ) : (
                      <button
                        onClick={() => { setPaymentPlan(planKey); setShowPaymentModal(true); }}
                        className="mt-3 w-full h-8 rounded-lg text-xs font-semibold text-white transition-all hover:opacity-90 active:scale-[0.98]"
                        style={isPro
                          ? { background: 'linear-gradient(135deg,#d97706,#f59e0b)', boxShadow: '0 4px 12px rgba(245,158,11,0.25)' }
                          : { background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)', boxShadow: '0 4px 12px rgba(124,58,237,0.25)' }}
                        aria-label={`Upgrade to ${info.label} plan`}
                        data-testid={`upgrade-${planKey}-button`}
                      >
                        Upgrade to {info.label}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* ═══════════════════════════════════════════════════
            SECTION 6 — PERSONALIZED STUDY PLANS
            ═══════════════════════════════════════════════════ */}
        <div className="glass-card rounded-2xl overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <div className="flex items-center gap-2">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">My Study Plans</p>
              <span className="text-[10px] px-2 py-0.5 rounded-full font-semibold"
                style={{ background: 'rgba(139,92,246,0.12)', color: 'hsl(var(--primary))', border: '1px solid rgba(139,92,246,0.20)' }}>
                AI-Generated
              </span>
            </div>
            {['starter', 'pro'].includes(plan) ? (
              <button
                onClick={() => setShowGenModal(true)}
                className="flex items-center gap-1.5 h-7 px-3 rounded-lg text-xs font-semibold text-white hover:opacity-90 transition-all"
                style={{ background: 'linear-gradient(135deg,#7c3aed,#6d28d9)' }}>
                <Plus size={12} /> Generate Plan
              </button>
            ) : (
              <button
                onClick={() => { setPaymentPlan('starter'); setShowPaymentModal(true); }}
                className="flex items-center gap-1.5 h-7 px-3 rounded-lg text-xs font-semibold hover:opacity-90 transition-all"
                style={{ background: 'rgba(139,92,246,0.12)', color: 'hsl(var(--primary))', border: '1px solid rgba(139,92,246,0.20)' }}>
                <Lock size={11} /> Starter only
              </button>
            )}
          </div>

          <div className="p-4">
            {!['starter', 'pro'].includes(plan) ? (
              <div className="text-center py-6 space-y-3">
                <div className="w-10 h-10 rounded-xl mx-auto flex items-center justify-center" style={{ background: 'rgba(139,92,246,0.10)' }}>
                  <Sparkles size={18} className="text-violet-400" />
                </div>
                <p className="text-sm font-medium text-foreground">Personalized Exam Plans</p>
                <p className="text-xs text-muted-foreground max-w-xs mx-auto">
                  AI generates a custom day-by-day sprint based on your weak topics.
                  Available on Starter &amp; Pro.
                </p>
                <button
                  onClick={() => { setPaymentPlan('starter'); setShowPaymentModal(true); }}
                  className="inline-flex items-center gap-2 h-9 px-5 rounded-xl text-sm font-semibold text-white hover:opacity-90 transition-all"
                  style={{ background: 'linear-gradient(135deg,#7c3aed,#6d28d9)', boxShadow: '0 4px 16px rgba(124,58,237,0.30)' }}>
                  <Zap size={13} /> Upgrade — ₹99
                </button>
              </div>
            ) : plansLoading ? (
              <div className="flex items-center justify-center py-6">
                <Loader2 size={20} className="animate-spin text-violet-400" />
              </div>
            ) : myPlans.length === 0 ? (
              <div className="text-center py-6 space-y-3">
                <FileText size={28} className="mx-auto text-white/20" />
                <p className="text-sm text-muted-foreground">No plans yet. Generate your first!</p>
                <button
                  onClick={() => setShowGenModal(true)}
                  className="inline-flex items-center gap-2 h-9 px-5 rounded-xl text-sm font-semibold text-white hover:opacity-90 transition-all"
                  style={{ background: 'linear-gradient(135deg,#7c3aed,#6d28d9)', boxShadow: '0 4px 16px rgba(124,58,237,0.30)' }}>
                  <Sparkles size={13} /> Generate My First Plan
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                {myPlans.slice(0, 5).map(p => (
                  <Link
                    key={p.id}
                    to={`/cms/${profile?.id}/${p.slug}`}
                    className="flex items-center gap-3 p-3 rounded-xl hover:opacity-90 transition-all group"
                    style={{ background: 'rgba(139,92,246,0.05)', border: '1px solid rgba(139,92,246,0.12)' }}>
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ background: 'rgba(139,92,246,0.12)' }}>
                      <Target size={14} className="text-violet-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">{p.title}</p>
                      <p className="text-xs text-muted-foreground flex items-center gap-2 mt-0.5">
                        {p.subject_name && <span>{p.subject_name}</span>}
                        {p.created_at && (
                          <span className="flex items-center gap-1">
                            <Calendar size={10} />
                            {new Date(p.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                          </span>
                        )}
                      </p>
                    </div>
                    <ChevronRight size={14} className="text-white/20 group-hover:text-white/50 transition-colors flex-shrink-0" />
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ═══════════════════════════════════════════════════
            SECTION 7 — ADMIN PORTAL (conditional)
            ═══════════════════════════════════════════════════ */}
        {profile?.is_admin && (
          <Link to="/admin">
            <div
              className="rounded-2xl p-4 flex items-center gap-3 transition-all hover:opacity-90 cursor-pointer"
              style={{
                background: 'linear-gradient(135deg, rgba(124,58,237,0.15), rgba(99,102,241,0.10))',
                border: '1px solid rgba(139,92,246,0.30)',
                boxShadow: '0 0 24px rgba(124,58,237,0.08)',
              }}
            >
              <div className="w-10 h-10 rounded-xl flex items-center justify-center"
                style={{ background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.25)' }}>
                <ShieldCheck size={18} style={{ color: 'hsl(var(--primary))' }} />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-foreground">Admin Portal</span>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                    style={{ background: 'rgba(124,58,237,0.15)', color: 'hsl(var(--primary))', border: '1px solid rgba(139,92,246,0.25)' }}>
                    INTERNAL
                  </span>
                  {/* Pulse dot */}
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                </div>
                <p className="text-xs text-muted-foreground/60 mt-0.5">Manage users, content, analytics</p>
              </div>
              <ChevronRight size={14} className="text-muted-foreground/50" />
            </div>
          </Link>
        )}

        {/* ═══════════════════════════════════════════════════
            SECTION 7 — DANGER ZONE
            ═══════════════════════════════════════════════════ */}
        {!deletionPending && (
          <div className="glass-card rounded-2xl overflow-hidden">
            <div className="px-4 py-3 border-b border-border">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Danger Zone</p>
            </div>
            <div className="p-4">
              <div className="flex items-start gap-3 p-3 rounded-xl"
                style={{ background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.15)' }}>
                <AlertTriangle size={16} className="text-red-400 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <p className="text-sm font-semibold text-foreground">Delete Account</p>
                  <p className="text-xs text-muted-foreground/70 mt-0.5">
                    Permanently delete your account and all data after a 72-hour grace period.
                  </p>
                </div>
                <button
                  onClick={() => setShowDeleteConfirm(true)}
                  className="flex-shrink-0 px-3 py-1.5 rounded-xl text-xs font-semibold text-red-400 border border-red-500/25 hover:bg-red-500/10 transition-colors"
                  data-testid="delete-account-button"
                >
                  <Trash2 size={12} className="inline mr-1" />
                  Delete
                </button>
              </div>

              {/* Member since */}
              <p className="text-xs text-muted-foreground/40 mt-3 text-center">
                Member since {profile?.created_at ? new Date(profile.created_at).toLocaleDateString('en-IN', { year: 'numeric', month: 'long' }) : '—'}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* ═══════════════════════════════════════════════════
          DIALOG — EDIT FIELD
          ═══════════════════════════════════════════════════ */}
      <AnimatePresence>
        {editField && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)' }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={(e) => { if (e.target === e.currentTarget) setEditField(null); }}
          >
            <motion.div
              className="w-full max-w-sm rounded-2xl p-5"
              style={{ background: 'hsl(var(--card))', border: '1px solid rgba(139,92,246,0.20)' }}
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.18 }}
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-foreground">Edit {editField.label}</h3>
                <button onClick={() => setEditField(null)} className="text-muted-foreground hover:text-foreground p-1 rounded-lg hover:bg-accent/40">
                  <X size={16} />
                </button>
              </div>
              <input
                ref={editInputRef}
                type="text"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSaveField(); if (e.key === 'Escape') setEditField(null); }}
                placeholder={editField.placeholder}
                className="w-full h-10 px-3 rounded-xl text-sm text-foreground outline-none"
                style={{ background: 'hsl(var(--input))', border: '1px solid rgba(139,92,246,0.20)' }}
              />
              <div className="flex gap-2 mt-4">
                <button onClick={() => setEditField(null)}
                  className="flex-1 h-9 rounded-xl text-sm font-medium text-muted-foreground border border-border hover:bg-accent/40 transition-colors">
                  Cancel
                </button>
                <button
                  onClick={handleSaveField}
                  disabled={editLoading || !editValue.trim()}
                  className="flex-1 h-9 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-1.5 transition-all hover:opacity-90 disabled:opacity-50"
                  style={{ background: 'linear-gradient(135deg,#7c3aed,#8b5cf6)' }}
                  data-testid="edit-field-save-button"
                >
                  {editLoading ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  Save
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ═══════════════════════════════════════════════════
          DIALOG — DELETE CONFIRMATION
          ═══════════════════════════════════════════════════ */}
      <AnimatePresence>
        {showDeleteConfirm && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)' }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <motion.div
              className="w-full max-w-sm rounded-2xl p-5 space-y-4"
              style={{ background: 'hsl(var(--card))', border: '1px solid rgba(239,68,68,0.25)' }}
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.18 }}
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center"
                  style={{ background: 'rgba(239,68,68,0.10)', border: '1px solid rgba(239,68,68,0.20)' }}>
                  <AlertTriangle size={18} className="text-red-400" />
                </div>
                <div>
                  <h3 className="font-semibold text-foreground">Delete Account?</h3>
                  <p className="text-xs text-muted-foreground">This cannot be undone after 72 hours</p>
                </div>
              </div>

              {/* Grace period info */}
              <div className="rounded-xl p-3" style={{ background: 'rgba(245,158,11,0.06)', border: '1px solid rgba(245,158,11,0.15)' }}>
                <p className="text-xs text-amber-400 font-medium">72-hour grace period</p>
                <p className="text-xs text-muted-foreground/70 mt-0.5">
                  You can cancel deletion within 72 hours. After that, all data is permanently erased.
                </p>
              </div>

              {/* What gets deleted */}
              <div className="space-y-1.5">
                {['Your profile and credentials', 'All chat conversations', 'Saved subjects', 'Credits and plan'].map((item) => (
                  <div key={item} className="flex items-center gap-2 text-xs text-muted-foreground/70">
                    <div className="w-1.5 h-1.5 rounded-full bg-red-400/60" />
                    {item}
                  </div>
                ))}
              </div>

              {/* Type DELETE to confirm */}
              <div>
                <label className="text-xs text-muted-foreground mb-1.5 block">
                  Type <span className="font-mono font-bold text-red-400">DELETE</span> to confirm
                </label>
                <input
                  type="text"
                  value={deleteText}
                  onChange={(e) => setDeleteText(e.target.value)}
                  placeholder="DELETE"
                  className="w-full h-10 px-3 rounded-xl text-sm text-foreground outline-none"
                  style={{ background: 'hsl(var(--input))', border: '1px solid rgba(239,68,68,0.30)' }}
                />
              </div>

              <div className="flex gap-2">
                <button onClick={() => { setShowDeleteConfirm(false); setDeleteText(''); }}
                  className="flex-1 h-9 rounded-xl text-sm font-medium text-muted-foreground border border-border hover:bg-accent/40 transition-colors">
                  Cancel
                </button>
                <button
                  onClick={handleDeleteAccount}
                  disabled={deleteText !== 'DELETE' || deleting}
                  className="flex-1 h-9 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-1.5 transition-all disabled:opacity-40"
                  style={{ background: 'linear-gradient(135deg,#dc2626,#ef4444)' }}
                  data-testid="confirm-delete-button"
                >
                  {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                  Schedule Deletion
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ═══════════════════════════════════════════════════
          DIALOG — PAYMENT MODAL
          ═══════════════════════════════════════════════════ */}
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
                {/* Document access */}
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
                {/* UPI QR hint */}
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
      {/* ═══════════════════════════════════════════════════
          DIALOG — CREDIT TOP-UP MODAL
          ═══════════════════════════════════════════════════ */}
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

      {/* ─── Generate Plan Modal ──────────────────────────────────────────── */}
      <AnimatePresence>
        {showGenModal && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            style={{ background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)' }}
            onClick={e => { if (e.target === e.currentTarget) setShowGenModal(false); }}>
            <motion.div
              className="relative w-full max-w-md rounded-2xl overflow-hidden"
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              style={{ background: 'var(--card)', border: '1px solid rgba(139,92,246,0.25)', boxShadow: '0 24px 80px rgba(0,0,0,0.5)' }}>
              {/* Header */}
              <div className="flex items-center justify-between px-5 pt-5 pb-4"
                style={{ borderBottom: '1px solid rgba(139,92,246,0.10)' }}>
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-xl flex items-center justify-center" style={{ background: 'rgba(139,92,246,0.15)' }}>
                    <Sparkles size={15} className="text-violet-400" />
                  </div>
                  <span className="text-sm font-bold text-white">Generate My Study Plan</span>
                </div>
                <button onClick={() => setShowGenModal(false)} className="p-1.5 rounded-lg hover:bg-white/8 transition-colors">
                  <X size={16} className="text-white/50" />
                </button>
              </div>

              {/* Form */}
              <div className="p-5 space-y-4">
                <div>
                  <label className="text-xs font-medium text-white/60 block mb-1.5">Subject</label>
                  <input
                    type="text"
                    value={genForm.subject_name}
                    onChange={e => setGenForm(f => ({ ...f, subject_name: e.target.value }))}
                    placeholder="e.g. Physics, Chemistry, English"
                    className="w-full h-10 px-3 rounded-xl text-sm bg-white/5 border border-white/10 text-white placeholder:text-white/30 focus:outline-none focus:border-violet-500/50"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-white/60 block mb-1.5">What are you weak in?</label>
                  <textarea
                    rows={3}
                    value={genForm.context}
                    onChange={e => setGenForm(f => ({ ...f, context: e.target.value }))}
                    placeholder="e.g. I struggle with Motion, Gravitation, and Optics."
                    className="w-full px-3 py-2 rounded-xl text-sm bg-white/5 border border-white/10 text-white placeholder:text-white/30 focus:outline-none focus:border-violet-500/50 resize-none"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-white/60 block mb-1.5">Sprint length (days)</label>
                  <div className="flex gap-2">
                    {[3, 5, 7, 14].map(d => (
                      <button key={d}
                        onClick={() => setGenForm(f => ({ ...f, days: d }))}
                        className={`flex-1 h-9 rounded-xl text-sm font-semibold border transition-all ${genForm.days === d
                          ? 'text-white border-violet-500/60'
                          : 'text-white/40 border-white/10 hover:border-white/20'}`}
                        style={genForm.days === d ? { background: 'rgba(124,58,237,0.20)' } : {}}>
                        {d}d
                      </button>
                    ))}
                  </div>
                </div>

                <button
                  onClick={handleGeneratePlan}
                  disabled={genLoading}
                  className="w-full h-11 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-60 hover:opacity-90 transition-all"
                  style={{ background: 'linear-gradient(135deg,#7c3aed,#6d28d9)', boxShadow: '0 4px 20px rgba(124,58,237,0.35)' }}>
                  {genLoading ? <><Loader2 size={15} className="animate-spin" /> Generating plan…</> : <><Sparkles size={15} /> Generate My {genForm.days}-Day Plan</>}
                </button>
                <p className="text-center text-[11px] text-white/30">Your plan is private — only you can see it</p>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </AppLayout>
  );
}
