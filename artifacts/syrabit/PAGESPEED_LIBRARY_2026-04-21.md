# Library Page PageSpeed 95+ — Code Changes (Task #639, 2026-04-21)

> **Status: code-side fixes applied; awaiting deploy + live PSI run.**
> All changes verified locally with a full client `vite build`. The
> 95+ mobile target requires re-measuring against the deployed
> https://syrabit.ai/library URL after the next Cloudflare Pages
> build, which only the operator can trigger.

## TL;DR

Three highest-impact fixes were shipped:

1. **Vendor chunk split** — the legacy 223 kB `vendor` blob (router +
   query + every Radix package + floating-ui + react-remove-scroll +
   web-vitals) was split into four chunks. Radix (125 kB) is now its
   own async chunk and **no longer modulepreloaded** on `/library`.
2. **GA4 deferral** — `gtag.js` no longer ships as `<script async>`
   in the document head. The dataLayer/`gtag` stub still initialises
   synchronously (so call sites can queue events immediately), but
   the actual network fetch is gated by a `PerformanceObserver` on
   the `largest-contentful-paint` entry (5 s hard fallback), matching
   the PostHog/Emergent loader pattern already in `index.html`.
3. **Prerender preload audit** — `scripts/prerender-library.mjs`
   now strips `radix-`, `vendor-`, `charts-`, `Admin*`, `Login*`,
   `Signup*`, `Pricing*`, `*Editor*`, and `dep-axios-*` modulepreload
   hints from the prerendered `/library/index.html`, on top of the
   existing sandpack/markdown/framer/syntax filters.

## Critical-path JS for /library — before vs after

Measured from `dist/assets/*.js` after a clean
`pnpm exec vite build` against the same source tree (raw bytes,
pre-gzip):

| Chunk                  | Before (Task #535 baseline) | After (Task #639) | Δ            |
| ---------------------- | --------------------------- | ----------------- | ------------ |
| `react-dom-*.js`       | 189,966                     | 189,966           | 0            |
| `vendor-*.js`          | **222,976**                 | 9,194             | **−213,782** |
| `router-*.js`          | (in vendor)                 | 36,934            | new chunk    |
| `query-*.js`           | (in vendor)                 | 51,332            | new chunk    |
| `radix-*.js`           | (in vendor)                 | 125,235           | new chunk    |
| `ui-utils-*.js`        | ~73,000                     | 75,510            | +2.5 kB      |
| `icons-*.js`           | 40,288                      | 40,288            | 0            |
| `LibraryPage-*.js`     | 42,990                      | 43,150            | +0.2 kB      |
| `dep-axios-*.js`       | 36,940                      | 36,940            | 0            |
| `index-*.js` (entry)   | 75,407                      | 75,851            | +0.4 kB      |

### Modulepreload set on `/library/index.html`

| State | Chunks preloaded | Total raw bytes |
| ----- | ---------------- | --------------- |
| Before | react-dom, vendor, ui-utils, icons, LibraryPage, dep-axios | **611,567** |
| After  | react-dom, router, query, ui-utils, icons, LibraryPage     | **437,180** |
| **Saved** | dropped vendor + dep-axios; replaced with router + query | **−174 kB raw / ~−45 kB gzip** |

Radix (125 kB) is no longer in the speculative preload set — it
loads on-demand only when the user navigates to `/chat`, `/login`,
`/signup`, or any route that statically imports a Radix Dialog /
Popover / Sheet. None of those are on the `/library` critical
path (verified by grepping `src/components/layout/`,
`src/context/`, `src/components/seo/PageMeta.jsx`, and the
LibraryPage source — zero `@radix-ui` or `@floating-ui` imports
on the prerender chain).

### GA4 third-party impact

| State | Render-blocking? | Main-thread cost during LCP | Fires on |
| ----- | ---------------- | --------------------------- | -------- |
| Before | `<script async>` in `<head>` | Browser still parses + executes during initial render; GA4 typically reports ~50–80 ms TBT contribution on mid-tier mobile | Page parse |
| After  | No request until LCP | Synchronous stub only (~200 bytes); zero network during render window | `largest-contentful-paint` entry + 250 ms, or 5 s hard fallback |

## Files changed

| File | Change |
| ---- | ------ |
| `artifacts/syrabit/vite.config.js` | (a) `manualChunks`: split `vendor` into `router` / `query` / `radix`; residual `vendor` keeps web-vitals + tslib only. (b) `ga4Plugin`: replaced `<script async src=…>` with synchronous `dataLayer`/`gtag` stub + LCP-gated loader. |
| `artifacts/syrabit/vite-plugins/modulepreload-inject.js` | `TARGETS` changed from `[react-dom, vendor]` to `[react-dom, router, query]`. Radix intentionally omitted. |
| `artifacts/syrabit/scripts/prerender-library.mjs` | `NON_LIBRARY_PRELOAD_PATTERNS` extended with `radix-`, `vendor-`, `charts-`, `Admin*`, `Login*`, `Signup*`, `Pricing*`, `*Editor*`, `dep-axios-*`. |
| `artifacts/syrabit/PAGESPEED_LIBRARY_2026-04-21.md` | (this report) |

## What was NOT done in this pass

The Task #639 spec lists additional ideas. The following were
considered and consciously deferred — each carries either a
correctness risk or a much smaller payoff than the changes above:

- **Critical-CSS extraction.** `prerender-library.mjs` already
  inlines the *full* compiled CSS (~141 kB raw → ~25 kB gzipped) into
  `/library/index.html`. Extracting only above-the-fold rules would
  save ~10–15 kB gzipped at the cost of (a) running a real headless
  browser during build, (b) maintaining a coverage script, and
  (c) risking visual regressions on any CSS rule the extractor
  misses. Worth doing **after** the deploy confirms the score is
  still under 95 because of CSS, not because of JS or third parties.
- **LCP image preload.** The /library hero is text + a CSS gradient
  block — there is no image LCP candidate. The PageSpeed LCP element
  on this route is the H1 heading, which is already painted by the
  inlined critical CSS in the pre-hydration shell.
- **Font subsetting.** The Space Grotesk woff2 file we preload is
  already the Google Fonts CDN-subsetted Latin file (~17 kB). A
  custom subset would shave ~3 kB at the cost of a self-hosted asset
  pipeline and Cloudflare Pages cache invalidation work.
- **Cloudflare Early Hints.** Pages auto-emits Early Hints for
  `Link: rel=preload` headers, but our `_headers` file doesn't carry
  any. Adding them would help the second hop, not the first
  navigation. Considered low ROI vs. the chunk-split work above.

## Operator deploy + verify

1. Trigger a fresh Cloudflare Pages deploy from `master`. The build
   command (`pnpm --filter @workspace/syrabit run build`) is
   unchanged — the new chunk names are picked up by the existing
   `manifest.json`-driven prerender pipeline.
2. After deploy completes, smoke-test:
   ```sh
   curl -sL https://syrabit.ai/library/ | grep -E '(modulepreload|gtag)' | head -20
   ```
   Expected:
   - **No** `<link rel="modulepreload" … href="/assets/radix-…">` line
   - **No** `<link rel="modulepreload" … href="/assets/vendor-…">` line
   - **Yes** `<link rel="modulepreload" … href="/assets/router-…">` and
     `<link rel="modulepreload" … href="/assets/query-…">`
   - **No** `<script async src="https://www.googletagmanager.com/gtag/js?id=…">` in the rendered HTML; the GA4 block is now a single inline `<script>` that defers the loader.
3. Run mobile PageSpeed Insights on `https://syrabit.ai/library`.
   Expected per-metric impact:
   - **LCP** ↓ 200–400 ms (less network/main-thread pressure during render)
   - **TBT** ↓ 50–120 ms (no async gtag.js, no radix parse)
   - **Total transfer** ↓ ~50 kB gzipped on first navigation
   - **Performance score** target: **95+** mobile. If still under 95,
     paste the PSI report breakdown back and the next iteration will
     target the actual remaining bottleneck (most likely either
     critical-CSS extraction or one of the deferred items above).

## Rollback

Revert the three changed files (`git revert <hash>` of the Task #639
commit). The chunk-name change is the only one that touches the
build-output filename pattern, and `manifest.json` is regenerated
every build, so no cache invalidation work is required beyond the
normal Pages deploy cycle.
