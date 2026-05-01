/**
 * Task #137 — TrustpilotReviewsSection render tests.
 *
 * Covers:
 * 1. CTA button appears with the correct Trustpilot profile href when config
 *    is present and provides a profileUrl.
 * 2. The section falls back to the hardcoded href when config is present but
 *    does not supply a profileUrl.
 * 3. The section is not visible (hidden gracefully) when config returns null.
 * 4. The aggregate-rating JSON-LD <script> tag is injected into <head> when
 *    the aggregate endpoint returns valid ratingValue / ratingCount data.
 * 5. No JSON-LD is injected when aggregate data is absent.
 *
 * Implementation note: the module uses module-level singleton caches
 * (_configCache, _aggregateCache). To isolate tests we reset the module
 * registry with vi.resetModules() and dynamically import the component in
 * beforeEach, and mock global fetch so no real network calls are made.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';

// @/utils/api is used for API_BASE — keep it stable across module resets.
vi.mock('@/utils/api', () => ({ API_BASE: 'http://localhost:5000/api' }));

const PROFILE_URL = 'https://www.trustpilot.com/review/syrabit.ai';
const CUSTOM_URL = 'https://www.trustpilot.com/review/custom-biz.example';

/** Build a minimal fetch mock that responds to the two trustpilot endpoints. */
function makeFetch({ configResponse, aggregateResponse }) {
  return vi.fn((url) => {
    if (url.includes('/config/trustpilot/aggregate')) {
      return Promise.resolve({
        ok: aggregateResponse !== null,
        json: () => Promise.resolve(aggregateResponse),
      });
    }
    // /config/trustpilot
    return Promise.resolve({
      ok: configResponse !== null,
      json: () => Promise.resolve(configResponse),
    });
  });
}

describe('TrustpilotReviewsSection', () => {
  let TrustpilotReviewsSection;

  beforeEach(async () => {
    // Reset the module registry so the singleton caches start empty for each test.
    vi.resetModules();
    // Dynamically import the component after the module reset.
    const mod = await import(
      '@/components/content/TrustpilotReviewsSection'
    );
    TrustpilotReviewsSection = mod.default;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    // Remove any injected JSON-LD script tags so tests don't bleed into each other.
    document
      .querySelectorAll('script[type="application/ld+json"]')
      .forEach((el) => el.remove());
  });

  // ------------------------------------------------------------------
  // 1. CTA button links to the profileUrl returned by the config endpoint
  // ------------------------------------------------------------------
  it('shows "Rate us on Trustpilot" button with the profileUrl from config', async () => {
    vi.stubGlobal(
      'fetch',
      makeFetch({
        configResponse: { profileUrl: CUSTOM_URL },
        aggregateResponse: null,
      }),
    );

    render(<TrustpilotReviewsSection heading="Leave a review" />);

    const link = await screen.findByRole('link', { name: /rate us on trustpilot/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', CUSTOM_URL);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  // ------------------------------------------------------------------
  // 2. Falls back to the hardcoded href when config has no profileUrl
  // ------------------------------------------------------------------
  it('falls back to the hardcoded Trustpilot href when config omits profileUrl', async () => {
    vi.stubGlobal(
      'fetch',
      makeFetch({
        configResponse: {}, // valid object but no profileUrl
        aggregateResponse: null,
      }),
    );

    render(<TrustpilotReviewsSection />);

    const link = await screen.findByRole('link', { name: /rate us on trustpilot/i });
    expect(link).toHaveAttribute('href', PROFILE_URL);
  });

  // ------------------------------------------------------------------
  // 3. Section hides gracefully when config returns null
  // ------------------------------------------------------------------
  it('renders nothing visible when the config endpoint returns null', async () => {
    vi.stubGlobal(
      'fetch',
      makeFetch({
        configResponse: null,
        aggregateResponse: null,
      }),
    );

    render(<TrustpilotReviewsSection heading="Hidden section" />);

    // Wait for the async fetch to settle (the component removes itself on null).
    await waitFor(() =>
      expect(
        screen.queryByRole('link', { name: /rate us on trustpilot/i }),
      ).toBeNull(),
    );

    expect(screen.queryByText('Hidden section')).toBeNull();
  });

  // ------------------------------------------------------------------
  // 4. JSON-LD <script> is injected when aggregate data is available
  // ------------------------------------------------------------------
  it('injects an aggregate-rating JSON-LD script tag when aggregate data is present', async () => {
    vi.stubGlobal(
      'fetch',
      makeFetch({
        configResponse: { profileUrl: PROFILE_URL },
        aggregateResponse: { ratingValue: 4.8, ratingCount: 312 },
      }),
    );

    render(
      <TrustpilotReviewsSection
        jsonLdId="test-jsonld"
        jsonLdName="Syrabit.ai"
        jsonLdUrl="https://syrabit.ai"
      />,
    );

    await waitFor(() => {
      const script = document.getElementById('test-jsonld');
      expect(script).not.toBeNull();
    });

    const script = document.getElementById('test-jsonld');
    expect(script).toHaveAttribute('type', 'application/ld+json');

    const ld = JSON.parse(script.textContent);
    expect(ld['@type']).toBe('Organization');
    expect(ld.name).toBe('Syrabit.ai');
    expect(ld.url).toBe('https://syrabit.ai');
    expect(ld.aggregateRating['@type']).toBe('AggregateRating');
    expect(ld.aggregateRating.ratingValue).toBe(4.8);
    expect(ld.aggregateRating.reviewCount).toBe(312);
    expect(ld.aggregateRating.bestRating).toBe(5);
    expect(ld.aggregateRating.worstRating).toBe(1);
  });

  // ------------------------------------------------------------------
  // 5. No JSON-LD injected when aggregate data is absent / zero count
  // ------------------------------------------------------------------
  it('does not inject JSON-LD when the aggregate endpoint returns null', async () => {
    vi.stubGlobal(
      'fetch',
      makeFetch({
        configResponse: { profileUrl: PROFILE_URL },
        aggregateResponse: null,
      }),
    );

    render(
      <TrustpilotReviewsSection
        jsonLdId="missing-jsonld"
        jsonLdName="Syrabit.ai"
      />,
    );

    // Give the component time to settle (wait for the CTA to appear).
    await screen.findByRole('link', { name: /rate us on trustpilot/i });

    expect(document.getElementById('missing-jsonld')).toBeNull();
  });
});
