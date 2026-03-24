/**
 * analytics.js — Syrabit.ai event tracking
 *
 * PostHog is already loaded in index.html.
 * This module provides typed event methods so every key action is tracked.
 * Gracefully no-ops if PostHog is not available.
 */

const track = (event, properties = {}) => {
  try {
    if (window.posthog && typeof window.posthog.capture === 'function') {
      window.posthog.capture(event, {
        app: 'syrabit.ai',
        timestamp: new Date().toISOString(),
        ...properties,
      });
    }
  } catch (e) {
    // Never throw — analytics must not break the app
    if (process.env.NODE_ENV !== 'production') {
      console.debug('[Analytics]', event, properties);
    }
  }
};

const identify = (userId, traits = {}) => {
  try {
    if (window.posthog) window.posthog.identify(userId, traits);
  } catch (e) {}
};

const reset = () => {
  try {
    if (window.posthog) window.posthog.reset();
  } catch (e) {}
};

export const Analytics = {
  // ── Auth ───────────────────────────────────────────────────────────
  signup: (email, plan = 'free') => {
    track('user_signed_up', { email_domain: email.split('@')[1], plan });
    identify(email, { plan, signed_up_at: new Date().toISOString() });
  },

  login: (userId, email) => {
    track('user_logged_in', { user_id: userId });
    identify(userId, { email, last_login: new Date().toISOString() });
  },

  logout: () => {
    track('user_logged_out');
    reset();
  },

  onboardingComplete: (boardName, className, streamName) => {
    track('onboarding_completed', { board: boardName, class: className, stream: streamName });
  },

  // ── Chat ──────────────────────────────────────────────────────────
  chatStart: (subjectId, subjectName, model) => {
    track('chat_started', { subject_id: subjectId, subject: subjectName, model });
  },

  chatMessage: (ragSource, creditsRemaining, model) => {
    track('chat_message_sent', { rag_source: ragSource, credits_remaining: creditsRemaining, model });
  },

  chatCreditsExhausted: () => {
    track('credits_exhausted');
  },

  // ── Library ───────────────────────────────────────────────────────
  subjectBookmarked: (subjectName, saved) => {
    track('subject_bookmarked', { subject: subjectName, action: saved ? 'save' : 'unsave' });
  },

  subjectOpened: (subjectId, subjectName) => {
    track('subject_opened', { subject_id: subjectId, subject: subjectName });
  },

  // ── Payment ──────────────────────────────────────────────────────
  upgradeInitiated: (plan, priceInr) => {
    track('upgrade_initiated', { plan, price_inr: priceInr });
  },

  purchaseComplete: (plan, priceInr, orderId) => {
    track('purchase_completed', { plan, price_inr: priceInr, order_id: orderId });
  },

  // ── Admin ──────────────────────────────────────────────────────
  adminLogin: (email) => {
    track('admin_logged_in', { email_domain: email.split('@')[1] });
  },

  // ── Page ───────────────────────────────────────────────────────
  pageView: (page) => {
    track('$pageview', { path: page || window.location.pathname });
  },
};

export default Analytics;
