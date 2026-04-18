/**
 * adsConfig.js — single source of truth for the ad stack on Syrabit.ai.
 *
 * Each placement key is wired to exactly one network. Real publisher IDs
 * and script URLs are read from `import.meta.env.VITE_ADS_*` env vars.
 * If any required value for a placement is missing, `getAdConfig()`
 * returns `{ enabled: false }` and `<AdSlot />` renders nothing — no
 * layout shift, no script tag injected.
 *
 * Routes that intentionally have NO ads:
 *   - /chat       (ChatPage)
 *   - /library    (LibraryPage)
 *   - /browser    (LibraryPage alias)
 *   - /:board/... (ChapterPage and friends)
 *
 * Adding/removing a network or placement is a one-file change here.
 * See ADS.md for the full list of env vars per network.
 */

const env = (typeof import.meta !== 'undefined' && import.meta.env) || {};

// ── Per-network defaults ─────────────────────────────────────────────────────
// Reserved heights are chosen to match the IAB sizes the networks serve in
// practice. They are kept identical whether the slot is enabled or not so
// the layout is stable from first paint.
const NETWORKS = {
  adpushup: {
    scriptUrl: env.VITE_ADS_ADPUSHUP_SCRIPT_URL || '',
    publisherId: env.VITE_ADS_ADPUSHUP_PUBLISHER_ID || '',
  },
  adsterra: {
    scriptUrl: env.VITE_ADS_ADSTERRA_SCRIPT_URL || '',
  },
  propellerads: {
    scriptUrl: env.VITE_ADS_PROPELLERADS_SCRIPT_URL || '',
  },
};

// ── Per-placement wiring ─────────────────────────────────────────────────────
const PLACEMENTS = {
  // PYQ pages — premium display demand (AdPushup / Magnite).
  'pyq.inContent': {
    network: 'adpushup',
    slotId: env.VITE_ADS_ADPUSHUP_PYQ_INCONTENT_ZONE || '',
    height: 280,
    label: 'Advertisement',
  },
  'pyq.endOfContent': {
    network: 'adpushup',
    slotId: env.VITE_ADS_ADPUSHUP_PYQ_END_ZONE || '',
    height: 280,
    label: 'Advertisement',
  },

  // Notes / Learn pages — fallback networks for lighter, mixed traffic.
  'learn.inContent': {
    network: 'adsterra',
    slotId: env.VITE_ADS_ADSTERRA_LEARN_INCONTENT_ZONE || '',
    height: 250,
    label: 'Advertisement',
  },
  'learn.endOfContent': {
    network: 'propellerads',
    slotId: env.VITE_ADS_PROPELLERADS_LEARN_END_ZONE || '',
    height: 250,
    label: 'Advertisement',
  },
};

/**
 * Resolve the config for a placement key. Always returns an object with at
 * least `{ enabled, height }`. `enabled` is false when:
 *   - the placement key is unknown,
 *   - the network has no `scriptUrl`,
 *   - or the placement has no `slotId`.
 *
 * `<AdSlot />` is responsible for the consent + production-build gates.
 */
export function getAdConfig(placement) {
  const p = PLACEMENTS[placement];
  if (!p) return { enabled: false, height: 0 };
  const net = NETWORKS[p.network];
  const enabled = !!(net && net.scriptUrl && p.slotId);
  return {
    enabled,
    network: p.network,
    scriptUrl: net?.scriptUrl || '',
    publisherId: net?.publisherId || '',
    slotId: p.slotId,
    height: p.height,
    label: p.label,
  };
}

/**
 * Returns true when the visitor's consent state allows third-party
 * advertising. Syrabit.ai does not yet ship a consent-management
 * platform, so we default to "load only in production builds" per the
 * task spec. When a CMP is added, hook it in here — `<AdSlot />` is the
 * single caller.
 */
export function adsConsentGranted() {
  if (typeof window === 'undefined') return false;
  // Honor a manual opt-out via localStorage for QA / privacy-conscious users.
  try {
    if (localStorage.getItem('syrabit_ads_optout') === '1') return false;
  } catch {}
  return !!(env && env.PROD);
}
