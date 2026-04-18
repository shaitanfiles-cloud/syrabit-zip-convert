# PageSpeed Audit — Syrabit.ai (2026-04-18-rerun-2)

**Origin audited:** `https://syrabit.ai` (production)  
**Strategy:** Mobile + Desktop  
**URLs audited:** 12 (24 total runs)  
**Tool:** Google PageSpeed Insights API v5 (Lighthouse 12.x lab + CrUX field data)  
**Raw JSON:** [`docs/audits/pagespeed-2026-04-18-rerun-2-raw/`](./pagespeed-2026-04-18-rerun-2-raw/)

## Executive Summary

- **Average mobile Performance score: 46/100** (70/100 desktop). Mobile is the SEO ranking signal Google uses, so this is the headline number to move.
- **6/12 routes fail mobile performance (< 50)**: `/home`, `/library`, `/assamboard/class-12/physics`, `/assamboard/class-12/physics/electric-charges-and-fields`, `/login`, `/profile`. **0/12 pass at 90+**.
- **Worst mobile LCP: `library` at 22436 ms** (Google "good" threshold is ≤ 2.5 s). LCP is the single biggest perf-driven ranking factor.
- **Average mobile SEO score: 79/100**, **Accessibility: 91/100**, **Best Practices: 91/100** — keep these ≥ 95 to avoid soft ranking penalties.
- **Top opportunity overall: "Reduce unused JavaScript"** (estimated 40390 ms / 14300 KB cumulative savings across the audited surface). See [Top 10 fixes](#top-10-prioritized-fixes) below.

### 🚨 SEO red flags detected in this run

1. **12/12 mobile routes fail Lighthouse's `canonical` SEO audit.** Failing routes: `/home`, `/library`, `/assamboard/class-12/physics`, `/assamboard/class-12/physics/electric-charges-and-fields`, `/chat`, `/login`, `/signup`, `/profile`, `/pricing`, `/admin/login`, `/about`, `/technology`. Most common cause: per-route canonicals are emitted by client-side React after hydration, so the byte-zero HTML Lighthouse evaluates has no canonical (or has a stale, hard-coded one in `index.html`). Fix: emit the correct canonical at SSR/prerender/edge-render time so it's present on the first byte.
2. **2/12 mobile routes fail `is-crawlable`** (page blocked from indexing). Failing routes: `/chat`, `/admin/login`. Check `robots.txt`, `<meta name="robots">` tags, and `X-Robots-Tag` response headers for these paths. Some (e.g. `/admin/login`) may be intentionally blocked.

> **Reading the badges:** 🟢 = passes Google's "good" threshold · 🟡 = "needs improvement" · 🔴 = "poor". LCP ≤ 2500 ms, INP ≤ 200 ms, CLS ≤ 0.10, FCP ≤ 1800 ms, TTFB ≤ 800 ms.

## Per-URL Results

### Home (`/home`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 44 | 🟡 67 |
| Accessibility | 🟢 93 | 🟢 90 |
| Best Practices | 🟢 96 | 🟡 77 |
| SEO | 🟡 85 | 🟡 85 |
| **LCP (lab)** | 🔴 7494 ms | 🟢 1723 ms |
| **TBT (lab, INP proxy)** | 🔴 766 ms | 🟡 507 ms |
| **CLS (lab)** | 🟢 0.006 | 🟢 0.004 |
| FCP (lab) | 🔴 3988 ms | 🟢 697 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 2 ms |
| Speed Index | 5924 ms | 2022 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~4979 ms)
- **Reduce unused JavaScript** (save ~2610 ms, save ~622 KB)
- **Reduce unused CSS** (save ~150 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/home.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/home.desktop.json)

### Library (`/library`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 32 | 🔴 46 |
| Accessibility | 🟢 94 | 🟢 94 |
| Best Practices | 🟡 77 | 🟢 96 |
| SEO | 🟡 83 | 🟡 85 |
| **LCP (lab)** | 🔴 22436 ms | 🟡 2854 ms |
| **TBT (lab, INP proxy)** | 🔴 1150 ms | 🔴 1821 ms |
| **CLS (lab)** | 🟡 0.101 | 🟡 0.104 |
| FCP (lab) | 🔴 5941 ms | 🟢 654 ms |
| TTFB (lab) | 🟢 2 ms | 🟢 1 ms |
| Speed Index | 7531 ms | 2472 ms |
| **Field LCP (CrUX p75)** | 🔴 6201 ms | — |
| **Field INP (CrUX p75)** | 🟡 239 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.000 | — |
| Field TTFB (CrUX p75) | 🟡 1294 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~8148 ms)
- **Reduce unused JavaScript** (save ~3770 ms, save ~733 KB)
- **Reduce unused CSS** (save ~300 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/library.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/library.desktop.json)

### Subject landing (`/assamboard/class-12/physics`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 31 | 🟡 65 |
| Accessibility | 🟢 90 | 🟢 90 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 16752 ms | 🟡 3085 ms |
| **TBT (lab, INP proxy)** | 🔴 661 ms | 🟡 240 ms |
| **CLS (lab)** | 🔴 0.284 | 🟡 0.121 |
| FCP (lab) | 🔴 3838 ms | 🟢 1010 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 6365 ms | 1989 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~6639 ms)
- **Reduce unused JavaScript** (save ~4550 ms, save ~671 KB)
- **Reduce unused CSS** (save ~300 ms, save ~21 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/subject-landing.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/subject-landing.desktop.json)

### Chapter (`/assamboard/class-12/physics/electric-charges-and-fields`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 36 | 🟡 62 |
| Accessibility | 🟢 91 | 🟢 91 |
| Best Practices | 🟢 96 | 🟡 77 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 15469 ms | 🟡 3002 ms |
| **TBT (lab, INP proxy)** | 🔴 972 ms | 🟡 292 ms |
| **CLS (lab)** | 🟡 0.227 | 🟡 0.158 |
| FCP (lab) | 🔴 3017 ms | 🟢 993 ms |
| TTFB (lab) | 🟢 1 ms | — |
| Speed Index | 3082 ms | 1279 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~6639 ms)
- **Reduce unused JavaScript** (save ~3210 ms, save ~547 KB)
- **Reduce unused CSS** (save ~150 ms, save ~21 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/chapter.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/chapter.desktop.json)

### AI Chat (`/chat`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 53 | 🟡 80 |
| Accessibility | 🟢 96 | 🟢 96 |
| Best Practices | 🟡 77 | 🟢 96 |
| SEO | 🟡 54 | 🟡 54 |
| **LCP (lab)** | 🔴 10714 ms | 🟢 2075 ms |
| **TBT (lab, INP proxy)** | 🟡 522 ms | 🟡 251 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3699 ms | 🟢 717 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 4080 ms | 843 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5582 ms)
- **Reduce unused JavaScript** (save ~3480 ms, save ~768 KB)
- **Reduce unused CSS** (save ~180 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/chat.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/chat.desktop.json)

### Login (`/login`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 47 | 🟡 88 |
| Accessibility | 🟡 86 | 🟡 86 |
| Best Practices | 🟡 77 | 🟢 96 |
| SEO | 🟡 85 | 🟡 85 |
| **LCP (lab)** | 🔴 4537 ms | 🟢 1973 ms |
| **TBT (lab, INP proxy)** | 🔴 5931 ms | 🟢 131 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🟡 2942 ms | 🟢 648 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 2 ms |
| Speed Index | 4415 ms | 1057 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~4526 ms)
- **Reduce unused JavaScript** (save ~910 ms, save ~513 KB)
- **Reduce unused CSS** (save ~120 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/login.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/login.desktop.json)

### Signup (`/signup`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 51 | 🟡 65 |
| Accessibility | 🟡 86 | 🟡 86 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 85 | 🟡 85 |
| **LCP (lab)** | 🔴 9588 ms | 🟢 1314 ms |
| **TBT (lab, INP proxy)** | 🔴 702 ms | 🔴 1277 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🟡 2942 ms | 🟢 654 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 3867 ms | 1533 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~4828 ms)
- **Reduce unused JavaScript** (save ~1660 ms, save ~404 KB)
- **Reduce unused CSS** (save ~130 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/signup.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/signup.desktop.json)

### Profile (`/profile`, logged-out shell)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 39 | 🟡 87 |
| Accessibility | 🟢 96 | 🟢 96 |
| Best Practices | 🟢 92 | 🟡 77 |
| SEO | 🟡 83 | 🟡 85 |
| **LCP (lab)** | 🔴 9711 ms | 🟢 2268 ms |
| **TBT (lab, INP proxy)** | 🔴 1310 ms | 🟢 119 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 4355 ms | 🟢 749 ms |
| TTFB (lab) | 🟢 2 ms | 🟢 1 ms |
| Speed Index | 4831 ms | 805 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~3772 ms)
- **Reduce unused JavaScript** (save ~2010 ms, save ~457 KB)
- **Reduce unused CSS** (save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/profile.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/profile.desktop.json)

### Pricing (`/pricing`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 51 | 🟡 52 |
| Accessibility | 🟢 93 | 🟢 92 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 10940 ms | 🟡 3077 ms |
| **TBT (lab, INP proxy)** | 🔴 634 ms | 🔴 1532 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3249 ms | 🟢 654 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 4141 ms | 1251 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5582 ms)
- **Reduce unused JavaScript** (save ~2280 ms, save ~507 KB)
- **Reduce unused CSS** (save ~330 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/pricing.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/pricing.desktop.json)

### Admin login (`/admin/login`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 58 | 🟡 80 |
| Accessibility | 🟡 81 | 🟡 81 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 54 | 🟡 54 |
| **LCP (lab)** | 🔴 9583 ms | 🟢 1788 ms |
| **TBT (lab, INP proxy)** | 🟢 183 ms | 🟡 301 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 5752 ms | 🟢 613 ms |
| TTFB (lab) | 🟢 2 ms | 🟢 1 ms |
| Speed Index | 5752 ms | 1086 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5432 ms)
- **Reduce unused JavaScript** (save ~3400 ms, save ~651 KB)
- **Reduce unused CSS** (save ~300 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/admin-login.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/admin-login.desktop.json)

### About (`/about`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 62 | 🟡 73 |
| Accessibility | 🟢 91 | 🟡 89 |
| Best Practices | 🟢 96 | 🟡 77 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 8475 ms | 🟢 2085 ms |
| **TBT (lab, INP proxy)** | 🟡 247 ms | 🟡 383 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3772 ms | 🟢 674 ms |
| TTFB (lab) | 🟢 2 ms | 🟢 1 ms |
| Speed Index | 3772 ms | 1028 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5733 ms)
- **Reduce unused JavaScript** (save ~4100 ms, save ~679 KB)
- **Reduce unused CSS** (save ~230 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/about.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/about.desktop.json)

### Technology (`/technology`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 52 | 🟡 74 |
| Accessibility | 🟢 94 | 🟢 94 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 8494 ms | 🟢 2371 ms |
| **TBT (lab, INP proxy)** | 🔴 731 ms | 🟡 284 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3017 ms | 🟢 986 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 3111 ms | 1099 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~3621 ms)
- **Reduce unused JavaScript** (save ~1650 ms, save ~481 KB)
- **Reduce unused CSS** (save ~120 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-2-raw/technology.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-2-raw/technology.desktop.json)

## Top 10 Prioritized Fixes

Ranked by **estimated cumulative mobile savings × number of routes affected**. Mobile is weighted heavier because it drives both UX and SEO ranking.

| # | Fix (Lighthouse audit) | Affects | Est. cumulative savings | Mobile-impact |
|---|---|---|---|---|
| 1 | **Reduce unused JavaScript** (`unused-javascript`) | 12 routes (24 runs, 12 mobile) | 40390 ms · 14300 KB | Very high |
| 2 | **Avoid multiple page redirects** (`redirects`) | 12 routes (24 runs, 12 mobile) | 79540 ms | Very high |
| 3 | **Minimize main-thread work** (`mainthread-work-breakdown`) | 12 routes (23 runs, 12 mobile) | 44545 ms | Very high |
| 4 | **Reduce JavaScript execution time** (`bootup-time`) | 12 routes (21 runs, 12 mobile) | 33960 ms | Very high |
| 5 | **Reduce unused CSS** (`unused-css-rules`) | 12 routes (24 runs, 12 mobile) | 2740 ms · 483 KB | Very high |
| 6 | **Render blocking requests** (`render-blocking-insight`) | 12 routes (24 runs, 12 mobile) | failing (Est savings of 150 ms) | Very high |
| 7 | **Background and foreground colors do not have a sufficient contrast ratio.** (`color-contrast`) | 12 routes (24 runs, 12 mobile) | failing (see audit) | Very high |
| 8 | **Document does not have a valid `rel=canonical`** (`canonical`) | 12 routes (24 runs, 12 mobile) | failing (see audit) | Very high |
| 9 | **Avoid enormous network payloads** (`total-byte-weight`) | 8 routes (14 runs, 8 mobile) | failing (Total size was 2,718 KiB) | Very high |
| 10 | **Page is blocked from indexing** (`is-crawlable`) | 2 routes (4 runs, 2 mobile) | failing (see audit) | Medium |

## Methodology

- Each URL ran twice: `strategy=mobile` (Moto G Power, throttled 4G/CPU 4×) and `strategy=desktop` (1350×940, throttled cable/CPU 1×). These are Google's standard PSI environments and match what gets used for [Search ranking signals](https://developers.google.com/search/docs/appearance/page-experience).
- Categories requested: `performance`, `accessibility`, `best-practices`, `seo`.
- Lab metrics (LCP, FCP, CLS, TBT, SI, TTFB) come from Lighthouse running in a Google datacenter; field metrics (CrUX p75 LCP/INP/CLS/TTFB) come from anonymized Chrome real-user data over the trailing 28 days.
- Top 10 fixes ranking formula: `savings_ms × (1 + mobileShare) + savings_KB × 5`. This favours fixes that compound across multiple mobile routes over single-route wins.
- Reproducibility: re-run `PAGESPEED_API_KEY=… node scripts/run-pagespeed-audit.mjs` then `node scripts/build-pagespeed-report.mjs`.

## Out of scope (per task #493)

- No code changes were made — this report is audit-only. Fixes from the Top 10 list should be opened as separate, focused tasks.
- Authenticated-only flows were not exercised: `/profile` and `/admin` were audited as their logged-out shells (the auth guard renders a redirect/login skeleton, which is what crawlers see anyway).
- Backend latency was not load-tested separately — TTFB numbers above come from the single PSI request and reflect cold-cache CDN behaviour at the moment of the audit.
