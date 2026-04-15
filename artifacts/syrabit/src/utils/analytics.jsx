/**
 * analytics.js — Syrabit.ai event tracking
 *
 * Tracks custom events to PostHog (already loaded in index.html).
 * Page-view tracking is handled by Cloudflare Web Analytics (beacon in index.html).
 *
 * Usage: import Analytics from '@/utils/analytics'; Analytics.signup(email);
 */

// ── Internal helpers ─────────────────────────────────────────────────────────

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
    if (import.meta.env.DEV) console.debug('[PostHog]', event, properties);
  }
};

const identify = (userId, traits = {}) => {
  try {
    if (window.posthog) window.posthog.identify(userId, traits);
  } catch {}
};

const reset = () => {
  try { if (window.posthog) window.posthog.reset(); } catch {}
};

const _getAttribution = () => {
  try {
    const params = new URLSearchParams(window.location.search);
    const curSource = params.get('utm_source') || params.get('ref') || '';
    const curMedium = params.get('utm_medium') || '';
    const curCampaign = params.get('utm_campaign') || '';
    const curContent = params.get('utm_content') || '';
    const curTerm = params.get('utm_term') || '';

    if (curSource && !localStorage.getItem('syrabit_ft_utm_source')) {
      localStorage.setItem('syrabit_ft_utm_source', curSource);
      localStorage.setItem('syrabit_ft_utm_medium', curMedium);
      localStorage.setItem('syrabit_ft_utm_campaign', curCampaign);
      localStorage.setItem('syrabit_ft_utm_content', curContent);
      localStorage.setItem('syrabit_ft_utm_term', curTerm);
      localStorage.setItem('syrabit_ft_landing_page', window.location.pathname);
      localStorage.setItem('syrabit_ft_timestamp', new Date().toISOString());
    }

    if (curSource) {
      sessionStorage.setItem('syrabit_utm_source', curSource);
      sessionStorage.setItem('syrabit_utm_medium', curMedium);
      sessionStorage.setItem('syrabit_utm_campaign', curCampaign);
    }
    if (!sessionStorage.getItem('syrabit_landing_page')) {
      sessionStorage.setItem('syrabit_landing_page', window.location.pathname);
    }

    const ftSource = localStorage.getItem('syrabit_ft_utm_source') || '';
    const ftMedium = localStorage.getItem('syrabit_ft_utm_medium') || '';
    const ftCampaign = localStorage.getItem('syrabit_ft_utm_campaign') || '';
    const ftLanding = localStorage.getItem('syrabit_ft_landing_page') || '';

    const source = ftSource || sessionStorage.getItem('syrabit_utm_source') || '';
    const medium = ftMedium || sessionStorage.getItem('syrabit_utm_medium') || '';
    const campaign = ftCampaign || sessionStorage.getItem('syrabit_utm_campaign') || '';
    const landing = ftLanding || sessionStorage.getItem('syrabit_landing_page') || '';
    return [source, medium, campaign, landing].filter(Boolean).join(' | ') || 'direct';
  } catch { return 'direct'; }
};

// ── Public API ───────────────────────────────────────────────────────────────

export const Analytics = {

  // ── Page views ─────────────────────────────────────────────────────────────
  pageView: (path, title) => {
    track('$pageview', { path: path || window.location.pathname });
  },

  // ── Auth ───────────────────────────────────────────────────────────────────
  signup: (email, plan = 'free') => {
    track('user_signed_up', { email_domain: email.split('@')[1], plan, attribution_source: _getAttribution() });
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

  // ── Chat ───────────────────────────────────────────────────────────────────
  chatStart: (subjectId, subjectName, model) => {
    track('chat_started', { subject_id: subjectId, subject: subjectName, model });
  },

  chatMessage: (source, creditsRemaining, model) => {
    track('chat_message_sent', { source, credits_remaining: creditsRemaining, model });
  },

  chatCreditsExhausted: () => {
    track('credits_exhausted');
  },

  chapterView: (chapterId, chapterTitle, subjectName, board, wordCount) => {
    track('chapter_viewed', { chapter_id: chapterId, chapter: chapterTitle, subject: subjectName, board, word_count: wordCount });
  },

  chapterShare: (chapterTitle, url) => {
    track('chapter_shared', { chapter: chapterTitle, url });
  },

  chapterRetry: (chapterSlug) => {
    track('chapter_retry', { chapter: chapterSlug });
  },

  chapterAskAi: (subjectSlug, chapterTitle) => {
    track('chapter_ask_ai_clicked', { subject: subjectSlug, chapter: chapterTitle });
  },

  tocClick: (heading, chapterTitle) => {
    track('toc_click', { heading, chapter: chapterTitle });
  },

  scrollDepth: (depth, chapterTitle) => {
    track('scroll_depth', { depth, chapter: chapterTitle });
  },

  searchUsed: (query, resultCount) => {
    track('search_used', { query, result_count: resultCount });
  },

  // ── Library ────────────────────────────────────────────────────────────────
  subjectBookmarked: (subjectName, saved) => {
    track('subject_bookmarked', { subject: subjectName, action: saved ? 'save' : 'unsave' });
  },

  subjectOpened: (subjectId, subjectName) => {
    track('subject_opened', { subject_id: subjectId, subject: subjectName });
  },

  subjectShared: (subjectName, url) => {
    track('subject_shared', { subject: subjectName, url });
  },

  // ── SEO Content pages ──────────────────────────────────────────────────────
  seoPageView: (board, classSlug, subjectSlug, topicSlug, pageType) => {
    track('seo_page_viewed', { board, class: classSlug, subject: subjectSlug, topic: topicSlug, type: pageType });
  },

  // ── Payment ────────────────────────────────────────────────────────────────
  upgradeInitiated: (plan, priceInr) => {
    track('upgrade_initiated', { plan, price_inr: priceInr, attribution_source: _getAttribution() });
  },

  purchaseComplete: (plan, priceInr, orderId) => {
    track('purchase_completed', { plan, price_inr: priceInr, order_id: orderId, attribution_source: _getAttribution() });
  },

  purchaseFailed: (plan, reason, orderId) => {
    track('purchase_failed', { plan, reason, order_id: orderId, attribution_source: _getAttribution() });
  },

  paymentModalClosed: (plan) => {
    track('payment_modal_closed', { plan, attribution_source: _getAttribution() });
  },

  // ── Admin ──────────────────────────────────────────────────────────────────
  // ── PWA ────────────────────────────────────────────────────────────────
  pwaPromptShown: () => {
    track('pwa_prompt_shown');
  },

  pwaInstalled: () => {
    track('pwa_installed');
  },

  pwaPromptDismissed: () => {
    track('pwa_prompt_dismissed');
  },

  getFirstTouchAttribution: () => {
    try {
      return {
        source: localStorage.getItem('syrabit_ft_utm_source') || '',
        medium: localStorage.getItem('syrabit_ft_utm_medium') || '',
        campaign: localStorage.getItem('syrabit_ft_utm_campaign') || '',
        content: localStorage.getItem('syrabit_ft_utm_content') || '',
        term: localStorage.getItem('syrabit_ft_utm_term') || '',
        landing_page: localStorage.getItem('syrabit_ft_landing_page') || '',
        timestamp: localStorage.getItem('syrabit_ft_timestamp') || '',
      };
    } catch { return {}; }
  },

  adminLogin: (email) => {
    track('admin_logged_in', { email_domain: email.split('@')[1] });
  },
};

export default Analytics;
