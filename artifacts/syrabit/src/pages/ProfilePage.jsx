import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AppLayout } from '@/components/layout/AppLayout';
import { isDegreeBoard } from '@/utils/courseTypes';
import { useAuth } from '@/context/AuthContext';
import { PageTitle } from '@/components/PageTitle';
import { apiClient, createPaymentOrder, verifyPayment, createCreditTopUp, verifyCreditTopUp } from '@/utils/api';
import { toast } from 'sonner';
import { PLANS, loadRazorpay, ga4Track } from './profile/shared';
import ProfileHeader from './profile/ProfileHeader';
import AcademicDetails from './profile/AcademicDetails';
import AiCredits from './profile/AiCredits';
import SubscriptionPlans from './profile/SubscriptionPlans';
import DangerZone, { DeletionBanner } from './profile/DangerZone';
import EditFieldDialog from './profile/EditFieldDialog';
import DeleteConfirmDialog from './profile/DeleteConfirmDialog';
import PaymentModal from './profile/PaymentModal';
import TopUpModal from './profile/TopUpModal';

export default function ProfilePage() {
  const { user, refreshUser } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [profile, setProfile]               = useState(null);
  const [loading, setLoading]               = useState(true);
  const [stats, setStats]                   = useState({ conversations: 0, saved_subjects: 0, total_tokens: 0, credits_used: 0 });
  const [editField, setEditField]           = useState(null);
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
  const editInputRef = useRef(null);

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

  useEffect(() => {
    const upgradePlan = searchParams.get('upgrade');
    if (upgradePlan && ['starter', 'pro'].includes(upgradePlan)) {
      setPaymentPlan(upgradePlan);
      setShowPaymentModal(true);
      setSearchParams({}, { replace: true });
    }
  }, [searchParams]);

  useEffect(() => {
    if (editField) {
      setTimeout(() => editInputRef.current?.focus(), 80);
    }
  }, [editField]);

  const getInitials = (name) =>
    (name || 'U').split(' ').map((n) => n[0]).join('').toUpperCase().slice(0, 2);

  const plan            = profile?.plan || 'free';
  const planInfo        = PLANS[plan] || PLANS.free;
  const isDegreeProfile = isDegreeBoard(profile?.board_name);
  const creditsUsed      = profile?.credits_used  ?? 0;
  const creditsLimit     = profile?.credits_limit ?? 0;
  const creditsRemaining = Math.max(0, profile?.credits_remaining ?? 0);
  const creditPercent = creditsLimit > 0 ? Math.min(100, (creditsUsed / creditsLimit) * 100) : 0;
  const isLowCredits  = creditsLimit > 0 && creditsRemaining <= 5;

  const getDeletionHoursLeft = () => {
    if (!deletionHardAt) return 0;
    const diff = new Date(deletionHardAt) - new Date();
    return Math.max(0, Math.floor(diff / 3600000));
  };

  const handleSaveField = async () => {
    if (!editField || !editValue.trim()) return;
    setEditLoading(true);
    try {
      await apiClient().patch('/user/profile', { [editField.key]: editValue.trim() });
      setProfile((p) => ({ ...p, [editField.key]: editValue.trim() }));
      toast.success(`${editField.label} updated`);
      setEditField(null);
    } catch {
      toast.error('Failed to update');
    } finally {
      setEditLoading(false);
    }
  };

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

  const handleCopyId = () => {
    navigator.clipboard.writeText(profile?.id || '');
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  const refreshData = async () => {
    await Promise.all([
      apiClient().get('/user/profile').then(r => setProfile(r.data)),
      apiClient().get('/user/stats').then(r => setStats(r.data)),
    ]);
    if (refreshUser) refreshUser();
  };

  const prefillData = () => ({
    name: profile?.name || '', email: profile?.email || user?.email || '', contact: profile?.phone || '',
  });

  const openRzp = (orderData, setLoadingFn, onSuccess) => {
    const options = {
      key: orderData.key_id, amount: orderData.amount, currency: orderData.currency,
      name: 'Syrabit.ai', description: orderData._desc, order_id: orderData.order_id,
      prefill: prefillData(), theme: { color: '#7c3aed' },
      modal: { ondismiss: () => setLoadingFn(false) },
      handler: onSuccess,
    };
    const rzp = new window.Razorpay(options);
    rzp.on('payment.failed', (r) => { toast.error(`Payment failed: ${r.error?.description || 'Unknown error'}`); setLoadingFn(false); });
    rzp.open();
  };

  const handleRazorpayCheckout = async () => {
    if (!paymentPlan) return;
    setPaymentLoading(true);
    try {
      const loaded = await loadRazorpay();
      if (!loaded) { toast.error('Failed to load payment gateway. Check your internet connection.'); setPaymentLoading(false); return; }
      let orderData;
      try { orderData = (await createPaymentOrder(paymentPlan)).data; }
      catch (err) { toast.error(err?.response?.data?.detail || 'Payment gateway not configured. Contact admin@syrabit.ai.'); setPaymentLoading(false); return; }
      ga4Track('begin_checkout', { currency: 'INR', value: orderData.amount / 100, items: [{ item_id: paymentPlan, item_name: `${paymentPlan}_plan`, item_category: 'subscription' }] });
      orderData._desc = `${orderData.plan_label} Plan — ${PLANS[paymentPlan]?.credits.toLocaleString()} AI credits`;
      openRzp(orderData, setPaymentLoading, async (response) => {
        try {
          await verifyPayment({ razorpay_order_id: response.razorpay_order_id, razorpay_payment_id: response.razorpay_payment_id, razorpay_signature: response.razorpay_signature, plan: paymentPlan });
          ga4Track('purchase', { transaction_id: response.razorpay_payment_id, currency: 'INR', value: orderData.amount / 100, items: [{ item_id: paymentPlan, item_name: `${paymentPlan}_plan`, item_category: 'subscription' }] });
          toast.success(`🎉 ${PLANS[paymentPlan]?.label} plan activated!`, { description: `${PLANS[paymentPlan]?.credits.toLocaleString()} AI credits added to your account.` });
          setShowPaymentModal(false);
          await refreshData();
        } catch { toast.error('Payment received but verification failed. Please contact admin@syrabit.ai.'); }
        finally { setPaymentLoading(false); }
      });
    } catch { toast.error('Something went wrong. Please try again.'); setPaymentLoading(false); }
  };

  const handleTopUpCheckout = async () => {
    if (!topUpCredits) return;
    setTopUpLoading(true);
    try {
      const loaded = await loadRazorpay();
      if (!loaded) { toast.error('Failed to load payment gateway.'); setTopUpLoading(false); return; }
      let orderData;
      try { orderData = (await createCreditTopUp(topUpCredits)).data; }
      catch (err) { toast.error(err?.response?.data?.detail || 'Failed to create top-up order.'); setTopUpLoading(false); return; }
      ga4Track('begin_checkout', { currency: 'INR', value: orderData.amount / 100, items: [{ item_id: 'credit_topup', item_name: `topup_${topUpCredits}`, item_category: 'credits', quantity: topUpCredits }] });
      orderData._desc = `Credit Top-up — ${topUpCredits} credits`;
      openRzp(orderData, setTopUpLoading, async (response) => {
        try {
          await verifyCreditTopUp({ razorpay_order_id: response.razorpay_order_id, razorpay_payment_id: response.razorpay_payment_id, razorpay_signature: response.razorpay_signature, credits: topUpCredits });
          ga4Track('purchase', { transaction_id: response.razorpay_payment_id, currency: 'INR', value: orderData.amount / 100, items: [{ item_id: 'credit_topup', item_name: `topup_${topUpCredits}`, item_category: 'credits', quantity: topUpCredits }] });
          toast.success(`${topUpCredits} credits added to your account!`);
          setShowTopUpModal(false);
          await refreshData();
        } catch { toast.error('Payment received but verification failed. Contact admin@syrabit.ai.'); }
        finally { setTopUpLoading(false); }
      });
    } catch { toast.error('Something went wrong. Please try again.'); setTopUpLoading(false); }
  };

  const openEdit = (key, label, placeholder) => {
    setEditField({ key, label, placeholder });
    setEditValue(profile?.[key] || '');
  };

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
        <ProfileHeader
          profile={profile} stats={stats} planInfo={planInfo}
          creditsLimit={creditsLimit} creditsRemaining={creditsRemaining}
          copiedId={copiedId} handleCopyId={handleCopyId} getInitials={getInitials}
        />
        <DeletionBanner
          deletionPending={deletionPending} getDeletionHoursLeft={getDeletionHoursLeft}
          cancellingDelete={cancellingDelete} handleCancelDeletion={handleCancelDeletion}
        />
        <AcademicDetails profile={profile} isDegreeProfile={isDegreeProfile} openEdit={openEdit} />
        <AiCredits
          stats={stats} creditsRemaining={creditsRemaining} creditsUsed={creditsUsed}
          creditsLimit={creditsLimit} creditPercent={creditPercent} isLowCredits={isLowCredits}
          plan={plan} setShowTopUpModal={setShowTopUpModal}
        />
        <SubscriptionPlans
          plan={plan} planInfo={planInfo} profile={profile}
          setPaymentPlan={setPaymentPlan} setShowPaymentModal={setShowPaymentModal}
        />
        <DangerZone
          profile={profile} deletionPending={deletionPending}
          setShowDeleteConfirm={setShowDeleteConfirm}
        />
      </div>

      <EditFieldDialog
        editField={editField} editValue={editValue} setEditValue={setEditValue}
        editLoading={editLoading} editInputRef={editInputRef}
        handleSaveField={handleSaveField} setEditField={setEditField}
      />
      <DeleteConfirmDialog
        showDeleteConfirm={showDeleteConfirm} deleteText={deleteText} setDeleteText={setDeleteText}
        deleting={deleting} handleDeleteAccount={handleDeleteAccount} setShowDeleteConfirm={setShowDeleteConfirm}
      />
      <PaymentModal
        showPaymentModal={showPaymentModal} paymentPlan={paymentPlan} paymentLoading={paymentLoading}
        setShowPaymentModal={setShowPaymentModal} handleRazorpayCheckout={handleRazorpayCheckout}
      />
      <TopUpModal
        showTopUpModal={showTopUpModal} topUpCredits={topUpCredits} setTopUpCredits={setTopUpCredits}
        topUpLoading={topUpLoading} planInfo={planInfo} creditsRemaining={creditsRemaining}
        setShowTopUpModal={setShowTopUpModal} handleTopUpCheckout={handleTopUpCheckout}
      />
    </AppLayout>
  );
}
