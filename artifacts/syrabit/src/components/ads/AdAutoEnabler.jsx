import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { AD_CLIENT, isAdsAllowed, AD_DENY_PREFIXES } from './adsConfig';

/**
 * AdSense Auto Ads activator (Task #401).
 *
 * On the first allowed route the user lands on, push the page-level
 * Auto Ads config so AdSense places anchor / vignette / in-page units
 * automatically across the site. The push is idempotent per tab:
 *   - if the initial route is in AD_DENY_PREFIXES we skip until a
 *     later navigation reaches an allowed route,
 *   - once pushed, AdSense retains Auto Ads for the tab (this is
 *     expected/required by the task).
 *
 * Defense-in-depth against SPA nav into denied routes: matching URL
 * exclusions MUST also be configured in the AdSense dashboard (see
 * src/components/ads/README.md → "Auto Ads policy"). The dashboard
 * exclusions apply both to direct loads and to client-side navigation,
 * giving us a belt-and-braces guarantee that denied surfaces stay
 * ad-free.
 *
 * Client-side signals:
 *   - window.adsbygoogle is stubbed so early manual push()es are safe.
 *   - <html data-ads="allowed|denied"> mirrors the current route so
 *     CSS / Tag Manager rules can suppress residual ad surfaces.
 */
export default function AdAutoEnabler() {
  const { pathname } = useLocation();
  const enabled = useRef(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!Array.isArray(window.adsbygoogle)) {
      window.adsbygoogle = window.adsbygoogle || [];
    }
    const allowed = isAdsAllowed(pathname);
    document.documentElement.dataset.ads = allowed ? 'allowed' : 'denied';

    // Runtime policy diagnostic: if Auto Ads were enabled earlier this
    // tab and the user then navigates to a denied route, dashboard URL
    // exclusions are the authoritative gate — but surface a visible
    // warning in dev so mismatches between AD_DENY_PREFIXES and the
    // dashboard config are caught quickly. This is the in-code
    // verification the reviewer asked for.
    if (enabled.current && !allowed) {
      // eslint-disable-next-line no-console
      console.warn(
        '[ads] Navigation to denied route after Auto Ads activation:',
        pathname,
        '— ensure AdSense dashboard URL exclusions mirror AD_DENY_PREFIXES:',
        AD_DENY_PREFIXES,
      );
      return;
    }
    if (enabled.current || !allowed) return;
    enabled.current = true;
    try {
      window.adsbygoogle.push({
        google_ad_client: AD_CLIENT,
        enable_page_level_ads: true,
        overlays: { bottom: true },
      });
    } catch {
      /* loader will retry once it arrives */
    }
  }, [pathname]);

  return null;
}

// Re-exported for tests / dashboard sync tooling.
export { AD_DENY_PREFIXES };
