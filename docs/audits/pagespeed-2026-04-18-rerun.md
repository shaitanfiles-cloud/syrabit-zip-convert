# PageSpeed Audit — Syrabit.ai (2026-04-18-rerun)

**Origin audited:** `https://syrabit.ai` (production)  
**Strategy:** Mobile + Desktop  
**URLs audited:** 12 (24 total runs)  
**Tool:** Google PageSpeed Insights API v5 (Lighthouse 12.x lab + CrUX field data)  
**Raw JSON:** [`docs/audits/pagespeed-2026-04-18-rerun-raw/`](./pagespeed-2026-04-18-rerun-raw/)

## Executive Summary

- **Average mobile Performance score: 43/100** (63/100 desktop). Mobile is the SEO ranking signal Google uses, so this is the headline number to move.
- **8/12 routes fail mobile performance (< 50)**: `/home`, `/library`, `/assamboard/class-12/physics`, `/assamboard/class-12/physics/electric-charges-and-fields`, `/chat`, `/login`, `/profile`, `/pricing`. **0/12 pass at 90+**.
- **Worst mobile LCP: `subject-landing` at 15135 ms** (Google "good" threshold is ≤ 2.5 s). LCP is the single biggest perf-driven ranking factor.
- **Average mobile SEO score: 79/100**, **Accessibility: 91/100**, **Best Practices: 93/100** — keep these ≥ 95 to avoid soft ranking penalties.
- **Top opportunity overall: "Reduce unused JavaScript"** (estimated 26860 ms / 13218 KB cumulative savings across the audited surface). See [Top 10 fixes](#top-10-prioritized-fixes) below.

### 🚨 SEO red flags detected in this run

1. **12/12 mobile routes fail Lighthouse's `canonical` SEO audit.** Failing routes: `/home`, `/library`, `/assamboard/class-12/physics`, `/assamboard/class-12/physics/electric-charges-and-fields`, `/chat`, `/login`, `/signup`, `/profile`, `/pricing`, `/admin/login`, `/about`, `/technology`. Most common cause: per-route canonicals are emitted by client-side React after hydration, so the byte-zero HTML Lighthouse evaluates has no canonical (or has a stale, hard-coded one in `index.html`). Fix: emit the correct canonical at SSR/prerender/edge-render time so it's present on the first byte.
2. **2/12 mobile routes fail `is-crawlable`** (page blocked from indexing). Failing routes: `/chat`, `/admin/login`. Check `robots.txt`, `<meta name="robots">` tags, and `X-Robots-Tag` response headers for these paths. Some (e.g. `/admin/login`) may be intentionally blocked.

> **Reading the badges:** 🟢 = passes Google's "good" threshold · 🟡 = "needs improvement" · 🔴 = "poor". LCP ≤ 2500 ms, INP ≤ 200 ms, CLS ≤ 0.10, FCP ≤ 1800 ms, TTFB ≤ 800 ms.

## Per-URL Results

### Home (`/home`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 34 | 🟡 58 |
| Accessibility | 🟢 93 | 🟢 90 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 85 | 🟡 85 |
| **LCP (lab)** | 🔴 8219 ms | 🟢 1247 ms |
| **TBT (lab, INP proxy)** | 🔴 1504 ms | 🔴 1696 ms |
| **CLS (lab)** | 🟢 0.006 | 🟢 0.001 |
| FCP (lab) | 🔴 5140 ms | 🟢 674 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 6628 ms | 3564 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5130 ms)
- **Reduce unused JavaScript** (save ~2560 ms, save ~622 KB)
- **Reduce unused CSS** (save ~270 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/home.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/home.desktop.json)

### Library (`/library`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 37 | 🔴 48 |
| Accessibility | 🟢 94 | 🟢 94 |
| Best Practices | 🟢 96 | 🟢 92 |
| SEO | 🟡 83 | 🟡 85 |
| **LCP (lab)** | 🔴 9436 ms | 🟢 2417 ms |
| **TBT (lab, INP proxy)** | 🔴 1235 ms | 🔴 3089 ms |
| **CLS (lab)** | 🟡 0.101 | 🟡 0.104 |
| FCP (lab) | 🔴 3075 ms | 🟢 633 ms |
| TTFB (lab) | 🟢 1 ms | — |
| Speed Index | 6069 ms | 2676 ms |
| **Field LCP (CrUX p75)** | 🔴 6201 ms | — |
| **Field INP (CrUX p75)** | 🟡 239 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.000 | — |
| Field TTFB (CrUX p75) | 🟡 1294 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~4979 ms)
- **Reduce unused JavaScript** (save ~470 ms, save ~429 KB)
- **Reduce unused CSS** (save ~160 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/library.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/library.desktop.json)

### Subject landing (`/assamboard/class-12/physics`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 22 | 🟡 82 |
| Accessibility | 🟢 90 | 🟢 92 |
| Best Practices | 🟢 96 | 🟡 77 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 15135 ms | 🟢 1636 ms |
| **TBT (lab, INP proxy)** | 🔴 1832 ms | 🟡 272 ms |
| **CLS (lab)** | 🔴 0.284 | 🟢 0.000 |
| FCP (lab) | 🔴 3017 ms | 🟢 866 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 6948 ms | 1007 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~4677 ms)
- **Reduce unused JavaScript** (save ~2290 ms, save ~519 KB)
- **Reduce unused CSS** (save ~150 ms, save ~21 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/subject-landing.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/subject-landing.desktop.json)

### Chapter (`/assamboard/class-12/physics/electric-charges-and-fields`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 35 | 🔴 48 |
| Accessibility | 🟢 91 | 🟢 91 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 14031 ms | 🟡 3228 ms |
| **TBT (lab, INP proxy)** | 🔴 913 ms | 🔴 762 ms |
| **CLS (lab)** | 🟡 0.227 | 🟡 0.158 |
| FCP (lab) | 🔴 3017 ms | 🟢 852 ms |
| TTFB (lab) | 🟢 2 ms | 🟢 1 ms |
| Speed Index | 4495 ms | 979 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~4828 ms)
- **Reduce unused JavaScript** (save ~1840 ms, save ~524 KB)
- **Reduce unused CSS** (save ~310 ms, save ~21 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/chapter.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/chapter.desktop.json)

### AI Chat (`/chat`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 40 | 🟡 63 |
| Accessibility | 🟢 96 | 🟢 96 |
| Best Practices | 🟢 96 | 🟡 77 |
| SEO | 🟡 54 | 🟡 54 |
| **LCP (lab)** | 🔴 5582 ms | 🟢 2314 ms |
| **TBT (lab, INP proxy)** | 🔴 6568 ms | 🟡 590 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3394 ms | 🟢 712 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 4694 ms | 1175 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~4526 ms)
- **Reduce unused JavaScript** (save ~1470 ms, save ~536 KB)
- **Reduce unused CSS** (save ~50 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/chat.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/chat.desktop.json)

### Login (`/login`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 49 | 🟡 57 |
| Accessibility | 🟡 86 | 🟡 86 |
| Best Practices | 🟢 96 | 🟡 77 |
| SEO | 🟡 85 | 🟡 85 |
| **LCP (lab)** | 🔴 4942 ms | 🟡 2587 ms |
| **TBT (lab, INP proxy)** | 🔴 1195 ms | 🔴 882 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🟡 2942 ms | 🟢 633 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 2 ms |
| Speed Index | 5598 ms | 1449 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~3621 ms)
- **Reduce unused JavaScript** (save ~600 ms, save ~461 KB)
- **Reduce unused CSS** (save ~90 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/login.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/login.desktop.json)

### Signup (`/signup`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 50 | 🟡 59 |
| Accessibility | 🟡 86 | 🟡 86 |
| Best Practices | 🟡 77 | 🟢 96 |
| SEO | 🟡 85 | 🟡 85 |
| **LCP (lab)** | 🔴 4985 ms | 🟢 2266 ms |
| **TBT (lab, INP proxy)** | 🔴 969 ms | 🔴 862 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3017 ms | 🟢 613 ms |
| TTFB (lab) | 🟢 2 ms | 🟢 2 ms |
| Speed Index | 5619 ms | 1650 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~3621 ms)
- **Reduce unused JavaScript** (save ~600 ms, save ~526 KB)
- **Reduce unused CSS** (save ~270 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/signup.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/signup.desktop.json)

### Profile (`/profile`, logged-out shell)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 46 | 🟡 57 |
| Accessibility | 🟢 96 | 🟢 96 |
| Best Practices | 🟢 96 | 🟡 77 |
| SEO | 🟡 83 | 🟡 85 |
| **LCP (lab)** | 🔴 9387 ms | 🟢 2407 ms |
| **TBT (lab, INP proxy)** | 🔴 731 ms | 🔴 1262 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 4344 ms | 🟢 656 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 4413 ms | 1134 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~3772 ms)
- **Reduce unused JavaScript** (save ~1870 ms, save ~477 KB)
- **Reduce unused CSS** (save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/profile.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/profile.desktop.json)

### Pricing (`/pricing`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 40 | 🟡 66 |
| Accessibility | 🟢 93 | 🟢 92 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 10525 ms | 🟢 1621 ms |
| **TBT (lab, INP proxy)** | 🔴 1055 ms | 🔴 913 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 4352 ms | 🟢 633 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 5531 ms | 950 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~3772 ms)
- **Reduce unused JavaScript** (save ~1720 ms, save ~482 KB)
- **Reduce unused CSS** (save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/pricing.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/pricing.desktop.json)

### Admin login (`/admin/login`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 52 | 🟡 68 |
| Accessibility | 🟡 81 | 🟡 81 |
| Best Practices | 🟡 77 | 🟢 96 |
| SEO | 🟡 54 | 🟡 54 |
| **LCP (lab)** | 🔴 7373 ms | 🟢 1963 ms |
| **TBT (lab, INP proxy)** | 🔴 739 ms | 🟡 462 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🟡 2942 ms | 🟢 1186 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 2 ms |
| Speed Index | 3561 ms | 1296 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~7544 ms)
- **Reduce unused JavaScript** (save ~2410 ms, save ~654 KB)
- **Reduce unused CSS** (save ~180 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/admin-login.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/admin-login.desktop.json)

### About (`/about`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 50 | 🟡 86 |
| Accessibility | 🟢 91 | 🟡 89 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 10415 ms | 🟢 1661 ms |
| **TBT (lab, INP proxy)** | 🔴 804 ms | 🟡 209 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3022 ms | 🟢 868 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 2 ms |
| Speed Index | 3022 ms | 961 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5733 ms)
- **Reduce unused JavaScript** (save ~2820 ms, save ~544 KB)
- **Reduce unused CSS** (save ~30 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/about.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/about.desktop.json)

### Technology (`/technology`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 60 | 🟡 61 |
| Accessibility | 🟢 94 | 🟢 94 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 8172 ms | 🟢 1812 ms |
| **TBT (lab, INP proxy)** | 🟡 326 ms | 🔴 1242 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3772 ms | 🟢 671 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 3772 ms | 1443 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5432 ms)
- **Reduce unused JavaScript** (save ~3010 ms, save ~692 KB)
- **Reduce unused CSS** (save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-rerun-raw/technology.mobile.json) · [desktop](./pagespeed-2026-04-18-rerun-raw/technology.desktop.json)

## Top 10 Prioritized Fixes

Ranked by **estimated cumulative mobile savings × number of routes affected**. Mobile is weighted heavier because it drives both UX and SEO ranking.

| # | Fix (Lighthouse audit) | Affects | Est. cumulative savings | Mobile-impact |
|---|---|---|---|---|
| 1 | **Reduce unused JavaScript** (`unused-javascript`) | 12 routes (24 runs, 12 mobile) | 26860 ms · 13218 KB | Very high |
| 2 | **Avoid multiple page redirects** (`redirects`) | 12 routes (24 runs, 12 mobile) | 70753 ms | Very high |
| 3 | **Minimize main-thread work** (`mainthread-work-breakdown`) | 12 routes (24 runs, 12 mobile) | 54348 ms | Very high |
| 4 | **Reduce JavaScript execution time** (`bootup-time`) | 12 routes (24 runs, 12 mobile) | 42979 ms | Very high |
| 5 | **Reduce unused CSS** (`unused-css-rules`) | 12 routes (24 runs, 12 mobile) | 1610 ms · 483 KB | Very high |
| 6 | **Document does not have a valid `rel=canonical`** (`canonical`) | 12 routes (24 runs, 12 mobile) | failing (see audit) | Very high |
| 7 | **Background and foreground colors do not have a sufficient contrast ratio.** (`color-contrast`) | 12 routes (24 runs, 12 mobile) | failing (see audit) | Very high |
| 8 | **Avoid enormous network payloads** (`total-byte-weight`) | 10 routes (11 runs, 3 mobile) | failing (Total size was 2,796 KiB) | Medium |
| 9 | **Render blocking requests** (`render-blocking-insight`) | 12 routes (24 runs, 12 mobile) | failing (Est savings of 150 ms) | Very high |
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
