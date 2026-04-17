/**
 * Central AdSense configuration (Task #401).
 *
 * One place to update slot IDs / formats so every placement stays
 * consistent. Slot IDs marked PLACEHOLDER must be replaced with real
 * values from the AdSense dashboard once the units are created — until
 * then the slots will simply request house ads and earn near-zero, but
 * the markup is harmless.
 *
 * Path policy:
 *   - allowlist : surfaces where SEO content is shown to anonymous
 *                 visitors. Manual <ins> units render only here.
 *   - denylist  : auth, payment, admin, profile, onboarding. We never
 *                 emit manual ad markup on these routes, and Auto Ads
 *                 are gated to the allowlist by isAdsAllowed().
 */

export const AD_CLIENT = 'ca-pub-8958003374183515';

// Reuse the two real slot IDs we already had from earlier tasks.
const REAL_IN_ARTICLE = '8964159403';
const REAL_IN_FEED = '5324297294';

// PLACEHOLDER slot IDs — replace once the units are minted in AdSense.
// They are kept distinct so each placement reports separately even when
// the IDs are still placeholders.
const PLACEHOLDER_TOP_LEADERBOARD = '1100000001';
const PLACEHOLDER_BOTTOM_LEADERBOARD = '1100000002';
const PLACEHOLDER_SIDEBAR_SKYSCRAPER = '1100000003';
const PLACEHOLDER_MULTIPLEX = '1100000004';

export const AD_SLOTS = {
  inArticle: {
    slot: REAL_IN_ARTICLE,
    format: 'fluid',
    layout: 'in-article',
    minHeight: 250,
  },
  inFeed: {
    slot: REAL_IN_FEED,
    format: 'fluid',
    layoutKey: '-fb+5w+4e-db+86',
    minHeight: 200,
  },
  topDisplay: {
    slot: PLACEHOLDER_TOP_LEADERBOARD,
    format: 'auto',
    fullWidthResponsive: true,
    minHeight: 100,
  },
  bottomDisplay: {
    slot: PLACEHOLDER_BOTTOM_LEADERBOARD,
    format: 'auto',
    fullWidthResponsive: true,
    minHeight: 250,
  },
  sidebar: {
    slot: PLACEHOLDER_SIDEBAR_SKYSCRAPER,
    format: 'auto',
    fullWidthResponsive: false,
    minHeight: 600,
  },
  multiplex: {
    slot: PLACEHOLDER_MULTIPLEX,
    format: 'autorelaxed',
    minHeight: 300,
  },
};

// Routes (path prefixes) where ads MUST NOT render. Order matters only
// in that we test prefixes; '/admin' covers '/admin/login' too.
export const AD_DENY_PREFIXES = [
  '/login',
  '/signup',
  '/reset-password',
  '/payment',
  '/admin',
  '/profile',
  '/onboarding',
  '/history',
];

export function isAdsAllowed(pathname = '/') {
  if (!pathname) return false;
  for (const p of AD_DENY_PREFIXES) {
    if (pathname === p || pathname.startsWith(p + '/')) return false;
  }
  return true;
}
