/**
 * analytics.js — Syrabit.ai event tracking
 *
 * Tracks events to two destinations in parallel:
 *   1. PostHog (already loaded in index.html — free, unlimited)
 *   2. Google Analytics 4 (loaded dynamically when VITE_GA_MEASUREMENT_ID is set)
 *
 * Usage: import Analytics from '@/utils/analytics'; Analytics.signup(email);
 */

const GA_ID = import.meta.env.VITE_GA_MEASUREMENT_ID || import.meta.env.VITE_GA4_ID;

// ── GA4 initialiser ─────────────────────────────────────────────────────────

export function initGA4() {
  if (!GA_ID || typeof window === 'undefined') return;

  // Load the gtag.js library
  const script = document.createElement('script');
  script.src = `https://www.googletagmanager.com/gtag/js?id=${GA_ID}`;
  script.async = true;
  document.head.appendChild(script);

  // Bootstrap dataLayer + gtag()
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag('js', new Date());
  window.gtag('config', GA_ID, {
    send_page_view: false,       // We send page_view manually on route change
    anonymize_ip: true,
  });
}

// ── Internal helpers ─────────────────────────────────────────────────────────

const trackGA4 = (eventName, params = {}) => {
  try {
    if (GA_ID && window.gtag) {
      window.gtag('event', eventName, params);
    }
  } catch {}
};

const track = (event, properties = {}) => {
  // PostHog
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

  // GA4 — map PostHog event names → GA4 recommended event names where possible
  const GA4_EVENT_MAP = {
    '$pageview': 'page_view',
    'user_signed_up': 'sign_up',
    'user_logged_in': 'login',
    'upgrade_initiated': 'begin_checkout',
    'purchase_completed': 'purchase',
  };
  const ga4Event = GA4_EVENT_MAP[event] || event;
  trackGA4(ga4Event, properties);
};

const identify = (userId, traits = {}) => {
  try {
    if (window.posthog) window.posthog.identify(userId, traits);
  } catch {}
  try {
    if (GA_ID && window.gtag) {
      window.gtag('config', GA_ID, { user_id: userId });
    }
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
    if (curSource && !sessionStorage.getItem('syrabit_utm_source')) {
      sessionStorage.setItem('syrabit_utm_source', curSource);
      sessionStorage.setItem('syrabit_utm_medium', curMedium);
      sessionStorage.setItem('syrabit_utm_campaign', curCampaign);
    }
    if (!sessionStorage.getItem('syrabit_landing_page')) {
      sessionStorage.setItem('syrabit_landing_page', window.location.pathname);
    }
    const source = sessionStorage.getItem('syrabit_utm_source') || '';
    const medium = sessionStorage.getItem('syrabit_utm_medium') || '';
    const campaign = sessionStorage.getItem('syrabit_utm_campaign') || '';
    const landing = sessionStorage.getItem('syrabit_landing_page') || '';
    return [source, medium, campaign, landing].filter(Boolean).join(' | ') || 'direct';
  } catch { return 'direct'; }
};

// ── Public API ───────────────────────────────────────────────────────────────

export const Analytics = {

  // ── Page views ─────────────────────────────────────────────────────────────
  pageView: (path, title) => {
    track('$pageview', { path: path || window.location.pathname });
    trackGA4('page_view', {
      page_path: path || window.location.pathname,
      page_title: title || document.title,
      page_location: window.location.href,
    });
  },

  // ── Auth ───────────────────────────────────────────────────────────────────
  signup: (email, plan = 'free') => {
    track('user_signed_up', { email_domain: email.split('@')[1], plan, attribution_source: _getAttribution() });
    identify(email, { plan, signed_up_at: new Date().toISOString() });
    trackGA4('sign_up', { method: 'email', plan });
  },

  login: (userId, email) => {
    track('user_logged_in', { user_id: userId });
    identify(userId, { email, last_login: new Date().toISOString() });
    trackGA4('login', { method: 'email' });
  },

  logout: () => {
    track('user_logged_out');
    reset();
  },

  onboardingComplete: (boardName, className, streamName) => {
    track('onboarding_completed', { board: boardName, class: className, stream: streamName });
    trackGA4('tutorial_complete', { board: boardName });
  },

  // ── Chat ───────────────────────────────────────────────────────────────────
  chatStart: (subjectId, subjectName, model) => {
    track('chat_started', { subject_id: subjectId, subject: subjectName, model });
    trackGA4('select_content', { content_type: 'chat', content_id: subjectId, item_name: subjectName });
  },

  chatMessage: (ragSource, creditsRemaining, model) => {
    track('chat_message_sent', { rag_source: ragSource, credits_remaining: creditsRemaining, model });
    trackGA4('chat_message_sent', { rag_source: ragSource, model, credits_remaining: creditsRemaining });
  },

  chatCreditsExhausted: () => {
    track('credits_exhausted');
    trackGA4('credits_exhausted');
  },

  chapterView: (chapterId, chapterTitle, subjectName, board, wordCount) => {
    track('chapter_viewed', { chapter_id: chapterId, chapter: chapterTitle, subject: subjectName, board, word_count: wordCount });
    trackGA4('view_item', { item_id: chapterId, item_name: chapterTitle, item_category: subjectName, item_variant: board, content_type: 'chapter' });
  },

  chapterShare: (chapterTitle, url) => {
    track('chapter_shared', { chapter: chapterTitle, url });
    trackGA4('share', { method: 'native', content_type: 'chapter', item_id: chapterTitle });
  },

  chapterRetry: (chapterSlug) => {
    track('chapter_retry', { chapter: chapterSlug });
    trackGA4('chapter_retry', { chapter: chapterSlug });
  },

  chapterAskAi: (subjectSlug, chapterTitle) => {
    track('chapter_ask_ai_clicked', { subject: subjectSlug, chapter: chapterTitle });
    trackGA4('select_content', { content_type: 'ask_ai', item_id: subjectSlug, item_name: chapterTitle });
  },

  tocClick: (heading, chapterTitle) => {
    track('toc_click', { heading, chapter: chapterTitle });
    trackGA4('select_content', { content_type: 'toc', item_id: heading, item_name: chapterTitle });
  },

  scrollDepth: (depth, chapterTitle) => {
    track('scroll_depth', { depth, chapter: chapterTitle });
    trackGA4('scroll_depth', { percent: depth, chapter: chapterTitle });
  },

  searchUsed: (query, resultCount) => {
    track('search_used', { query, result_count: resultCount });
    trackGA4('search', { search_term: query });
  },

  // ── Library ────────────────────────────────────────────────────────────────
  subjectBookmarked: (subjectName, saved) => {
    track('subject_bookmarked', { subject: subjectName, action: saved ? 'save' : 'unsave' });
  },

  subjectOpened: (subjectId, subjectName) => {
    track('subject_opened', { subject_id: subjectId, subject: subjectName });
    trackGA4('view_item', { item_id: subjectId, item_name: subjectName, item_category: 'subject' });
  },

  subjectShared: (subjectName, url) => {
    track('subject_shared', { subject: subjectName, url });
    trackGA4('share', { method: 'native', content_type: 'subject', item_id: subjectName });
  },

  // ── SEO Content pages ──────────────────────────────────────────────────────
  seoPageView: (board, classSlug, subjectSlug, topicSlug, pageType) => {
    track('seo_page_viewed', { board, class: classSlug, subject: subjectSlug, topic: topicSlug, type: pageType });
    trackGA4('view_item', { item_id: topicSlug, item_name: topicSlug, item_category: subjectSlug, item_variant: pageType });
  },

  // ── Payment ────────────────────────────────────────────────────────────────
  upgradeInitiated: (plan, priceInr) => {
    track('upgrade_initiated', { plan, price_inr: priceInr, attribution_source: _getAttribution() });
    trackGA4('begin_checkout', { currency: 'INR', value: priceInr / 100, items: [{ item_name: plan, price: priceInr / 100 }] });
  },

  purchaseComplete: (plan, priceInr, orderId) => {
    track('purchase_completed', { plan, price_inr: priceInr, order_id: orderId, attribution_source: _getAttribution() });
    trackGA4('purchase', {
      transaction_id: orderId,
      currency: 'INR',
      value: priceInr / 100,
      items: [{ item_name: plan, price: priceInr / 100 }],
    });
  },

  purchaseFailed: (plan, reason, orderId) => {
    track('purchase_failed', { plan, reason, order_id: orderId, attribution_source: _getAttribution() });
    trackGA4('purchase_failed', { plan, reason, order_id: orderId });
  },

  paymentModalClosed: (plan) => {
    track('payment_modal_closed', { plan, attribution_source: _getAttribution() });
    trackGA4('payment_modal_closed', { plan });
  },

  // ── Admin ──────────────────────────────────────────────────────────────────
  // ── PWA ────────────────────────────────────────────────────────────────
  pwaPromptShown: () => {
    track('pwa_prompt_shown');
    trackGA4('pwa_prompt_shown');
  },

  pwaInstalled: () => {
    track('pwa_installed');
    trackGA4('pwa_installed');
  },

  pwaPromptDismissed: () => {
    track('pwa_prompt_dismissed');
    trackGA4('pwa_prompt_dismissed');
  },

  adminLogin: (email) => {
    track('admin_logged_in', { email_domain: email.split('@')[1] });
  },
};

export default Analytics;
