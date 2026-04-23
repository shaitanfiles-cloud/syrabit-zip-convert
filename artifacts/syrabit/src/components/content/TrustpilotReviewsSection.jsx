/**
 * TrustpilotReviewsSection — Task #724
 *
 * Renders the official Trustpilot TrustBox widget at the bottom of
 * content pages (Landing, Library, Subject, Chapter, PYQ). The widget
 * is lazy-loaded via an IntersectionObserver so it never blocks first
 * paint or hurts LCP, and the bootstrap script is fetched at most once
 * per page lifecycle. The business unit ID and review URL come from a
 * server-exposed config endpoint backed by the Trustpilot secret —
 * never hard-coded in the JS bundle.
 *
 * If Trustpilot is not configured, the script fails to load, or the
 * widget never renders, the section hides itself gracefully so the
 * page below the footer stays clean.
 */
import { useEffect, useRef, useState } from 'react';
import { API_BASE } from '@/utils/api';

const TRUSTPILOT_SCRIPT_ID = 'trustpilot-widget-script';
const TRUSTPILOT_SCRIPT_SRC =
  'https://widget.trustpilot.com/bootstrap/v5/tp.widget.bootstrap.min.js';

let _configPromise = null;
let _configCache = null;

export function fetchTrustpilotConfigOnce() {
  if (_configCache) return Promise.resolve(_configCache);
  if (_configPromise) return _configPromise;
  _configPromise = fetch(`${API_BASE}/config/trustpilot`, { credentials: 'omit' })
    .then((r) => (r.ok ? r.json() : null))
    .then((json) => {
      _configCache = json && typeof json === 'object' ? json : null;
      return _configCache;
    })
    .catch(() => null)
    .finally(() => { _configPromise = null; });
  return _configPromise;
}

// Aggregate rating fetched once per app session and reused across every
// page — feeds the Organization-level JSON-LD so Google can render
// stars next to Syrabit.ai listings (Task #725). The backend already
// caches the upstream Trustpilot Business API call for several hours,
// so this single client-side fetch is the entire cost per session.
let _aggregatePromise = null;
let _aggregateCache = null;

export function fetchTrustpilotAggregateOnce() {
  if (_aggregateCache) return Promise.resolve(_aggregateCache);
  if (_aggregatePromise) return _aggregatePromise;
  _aggregatePromise = fetch(`${API_BASE}/config/trustpilot/aggregate`, { credentials: 'omit' })
    .then((r) => (r.ok ? r.json() : null))
    .then((json) => {
      if (
        json &&
        typeof json === 'object' &&
        typeof json.ratingValue === 'number' &&
        typeof json.ratingCount === 'number' &&
        json.ratingCount > 0
      ) {
        _aggregateCache = json;
      } else {
        _aggregateCache = null;
      }
      return _aggregateCache;
    })
    .catch(() => null)
    .finally(() => { _aggregatePromise = null; });
  return _aggregatePromise;
}

let _scriptPromise = null;
function loadTrustpilotScript(src) {
  if (typeof window === 'undefined') return Promise.resolve(false);
  if (window.Trustpilot) return Promise.resolve(true);
  if (_scriptPromise) return _scriptPromise;
  _scriptPromise = new Promise((resolve) => {
    const existing = document.getElementById(TRUSTPILOT_SCRIPT_ID);
    if (existing) {
      existing.addEventListener('load', () => resolve(!!window.Trustpilot));
      existing.addEventListener('error', () => resolve(false));
      return;
    }
    const s = document.createElement('script');
    s.id = TRUSTPILOT_SCRIPT_ID;
    s.src = src || TRUSTPILOT_SCRIPT_SRC;
    s.async = true;
    s.onload = () => resolve(!!window.Trustpilot);
    s.onerror = () => { _scriptPromise = null; resolve(false); };
    document.head.appendChild(s);
  });
  return _scriptPromise;
}

export default function TrustpilotReviewsSection({
  heading = 'What students say',
  subheading = '',
  templateId = '53aa8912dec7e10d38f59f36',
  height = '240px',
  theme = 'light',
  jsonLdId,
  jsonLdName,
  jsonLdUrl,
}) {
  const containerRef = useRef(null);
  const widgetRef = useRef(null);
  const [config, setConfig] = useState(_configCache);
  const [aggregate, setAggregate] = useState(_aggregateCache);
  const [visible, setVisible] = useState(false);
  const [failed, setFailed] = useState(false);

  // Resolve Trustpilot config + live aggregate rating once per app session.
  // The aggregate fetch runs eagerly (not gated on IntersectionObserver)
  // so the JSON-LD is in the DOM before Googlebot leaves the page.
  useEffect(() => {
    let cancelled = false;
    fetchTrustpilotConfigOnce().then((c) => {
      if (cancelled) return;
      setConfig(c);
      if (!c || !c.businessUnitId) setFailed(true);
    });
    fetchTrustpilotAggregateOnce().then((a) => {
      if (cancelled) return;
      if (a) setAggregate(a);
    });
    return () => { cancelled = true; };
  }, []);

  // Defer mounting the widget until the section scrolls near the
  // viewport — avoids paying the Trustpilot script + iframe cost for
  // users who never scroll to the footer.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || visible) return;
    if (typeof IntersectionObserver === 'undefined') { setVisible(true); return; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setVisible(true);
        io.disconnect();
      }
    }, { rootMargin: '400px' });
    io.observe(el);
    return () => io.disconnect();
  }, [visible]);

  // Once visible AND config is ready, load the script + render the widget.
  useEffect(() => {
    if (!visible) return;
    if (!config || !config.businessUnitId) return;
    let cancelled = false;
    loadTrustpilotScript(config.scriptSrc).then((ok) => {
      if (cancelled) return;
      if (!ok || !window.Trustpilot || !widgetRef.current) {
        setFailed(true);
        return;
      }
      try {
        window.Trustpilot.loadFromElement(widgetRef.current, true);
      } catch {
        setFailed(true);
      }
    });
    return () => { cancelled = true; };
  }, [visible, config]);

  const businessUnitId = config?.businessUnitId || '';
  const profileUrl = config?.profileUrl || 'https://www.trustpilot.com/review/syrabit.ai';

  // Render the aggregate-rating JSON-LD whenever we have a real value
  // from the backend, even if the embed widget itself failed to load —
  // the schema is what powers the Google search-result stars.
  const jsonLd = aggregate ? (
    <TrustpilotAggregateRatingJsonLd
      id={jsonLdId}
      name={jsonLdName}
      url={jsonLdUrl}
      ratingValue={aggregate.ratingValue}
      ratingCount={aggregate.ratingCount}
    />
  ) : null;

  if (failed) return jsonLd;

  return (
    <section
      ref={containerRef}
      className="mt-12 max-w-5xl mx-auto px-4"
      aria-label="Trustpilot reviews"
    >
      {jsonLd}
      <div className="rounded-3xl border border-border/40 bg-gradient-to-br from-emerald-50/40 via-background to-violet-50/30 p-6 sm:p-8">
        <div className="mb-5">
          <h2 className="text-xl sm:text-2xl font-bold text-foreground">{heading}</h2>
          {subheading && (
            <p className="text-sm text-muted-foreground mt-1">{subheading}</p>
          )}
        </div>

        {businessUnitId ? (
          <div
            ref={widgetRef}
            className="trustpilot-widget"
            data-locale="en-US"
            data-template-id={templateId}
            data-businessunit-id={businessUnitId}
            data-style-height={height}
            data-style-width="100%"
            data-theme={theme}
          >
            <a
              href={profileUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground"
            >
              See our reviews on Trustpilot
            </a>
          </div>
        ) : (
          <div style={{ minHeight: height }} aria-hidden="true" />
        )}
      </div>
    </section>
  );
}

/**
 * Optional aggregate rating JSON-LD wrapper. Trustpilot does not expose
 * aggregate ratings client-side via the embed widget, so unless a
 * `ratingValue` + `ratingCount` are explicitly provided we render
 * nothing — better to ship no aggregate-rating schema than stale or
 * fabricated numbers that could trigger search-console structured data
 * warnings. (Replaces the Google Places-backed
 * `ReviewsAggregateRatingJsonLd` from Task #652.)
 */
export function TrustpilotAggregateRatingJsonLd({
  id,
  name,
  url,
  ratingValue = null,
  ratingCount = null,
}) {
  useEffect(() => {
    if (typeof document === 'undefined') return;
    if (ratingValue == null || ratingCount == null) return;
    const elId = id || 'trustpilot-aggregaterating-jsonld';
    document.getElementById(elId)?.remove();
    const node = {
      '@context': 'https://schema.org',
      '@type': 'Organization',
      name: name || 'Syrabit.ai',
      url: url || (typeof window !== 'undefined' ? window.location.href : 'https://syrabit.ai'),
      aggregateRating: {
        '@type': 'AggregateRating',
        ratingValue: Number(ratingValue),
        reviewCount: Number(ratingCount),
        bestRating: 5,
        worstRating: 1,
      },
    };
    const s = document.createElement('script');
    s.type = 'application/ld+json';
    s.id = elId;
    s.text = JSON.stringify(node);
    document.head.appendChild(s);
    return () => { document.getElementById(elId)?.remove(); };
  }, [id, name, url, ratingValue, ratingCount]);
  return null;
}
