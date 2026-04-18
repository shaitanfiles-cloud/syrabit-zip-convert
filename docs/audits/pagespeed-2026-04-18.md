# PageSpeed Audit — Syrabit.ai (2026-04-18)

**Origin audited:** `https://syrabit.ai` (production)  
**Strategy:** Mobile + Desktop  
**URLs audited:** 12 (24 total runs)  
**Tool:** Google PageSpeed Insights API v5 (Lighthouse 12.x lab + CrUX field data)  
**Raw JSON:** [`docs/audits/pagespeed-2026-04-18-raw/`](./pagespeed-2026-04-18-raw/)

## Executive Summary

- **Average mobile Performance score: 47/100** (65/100 desktop). Mobile is the SEO ranking signal Google uses, so this is the headline number to move.
- **5/12 routes fail mobile performance (< 50)**: `/library`, `/assamboard/class-12/physics`, `/assamboard/class-12/physics/electric-charges-and-fields`, `/signup`, `/profile`. **0/12 pass at 90+**.
- **Worst mobile LCP: `chapter` at 18018 ms** (Google "good" threshold is ≤ 2.5 s). LCP is the single biggest perf-driven ranking factor.
- **Average mobile SEO score: 79/100**, **Accessibility: 91/100**, **Best Practices: 91/100** — keep these ≥ 95 to avoid soft ranking penalties.
- **Top opportunity overall: "Reduce unused JavaScript"** (estimated 36000 ms / 13961 KB cumulative savings across the audited surface). See [Top 10 fixes](#top-10-prioritized-fixes) below.

### 🚨 Two SEO red flags worth flagging before perf work

1. **Every audited URL fails Lighthouse's `canonical` SEO audit (12/12 routes, mobile + desktop).** `index.html` ships a single hard-coded `<link rel="canonical" href="https://syrabit.ai/">` that is the same on every route, so Lighthouse treats every non-root URL as having a canonical that points elsewhere. Per-route canonicals (already set inside the React tree via `PageMeta`) likely arrive after Lighthouse evaluates the SEO category. Fix: emit a route-specific canonical at SSR/prerender time, or remove the static one from `index.html` and let `react-helmet-async` own it. **Risk: Google may merge ranking signals from all routes onto `/`.**
2. **`/chat` is blocked from indexing by `robots.txt` (line 248).** `/chat` is the destination of the `/` redirect — i.e. it _is_ the user-facing homepage — but the audit confirms it returns "Page is blocked from indexing." `/admin/login` failing the same check is fine and expected. Fix: remove `/chat` from the `Disallow` block, or change `/` to render the chat shell directly instead of redirecting.

> **Reading the badges:** 🟢 = passes Google's "good" threshold · 🟡 = "needs improvement" · 🔴 = "poor". LCP ≤ 2500 ms, INP ≤ 200 ms, CLS ≤ 0.10, FCP ≤ 1800 ms, TTFB ≤ 800 ms.

## Per-URL Results

### Home (`/home`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 62 | 🔴 48 |
| Accessibility | 🟢 93 | 🟢 90 |
| Best Practices | 🟡 77 | 🟢 96 |
| SEO | 🟡 85 | 🟡 85 |
| **LCP (lab)** | 🔴 4845 ms | 🟡 3532 ms |
| **TBT (lab, INP proxy)** | 🟡 419 ms | 🔴 948 ms |
| **CLS (lab)** | 🟢 0.006 | 🟢 0.001 |
| FCP (lab) | 🔴 3106 ms | 🟢 1031 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 5960 ms | 1892 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~3788 ms)
- **Reduce unused JavaScript** (save ~450 ms, save ~528 KB)
- **Reduce unused CSS** (save ~130 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/home.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/home.desktop.json)

### Library (`/library`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 39 | 🔴 49 |
| Accessibility | 🟢 94 | 🟢 94 |
| Best Practices | 🟡 77 | 🟢 96 |
| SEO | 🟡 83 | 🟡 85 |
| **LCP (lab)** | 🔴 4701 ms | 🟢 2204 ms |
| **TBT (lab, INP proxy)** | 🔴 3990 ms | 🔴 4186 ms |
| **CLS (lab)** | 🟡 0.101 | 🟡 0.104 |
| FCP (lab) | 🔴 3030 ms | 🟢 633 ms |
| TTFB (lab) | — | 🟢 1 ms |
| Speed Index | 6629 ms | 2903 ms |
| **Field LCP (CrUX p75)** | 🔴 6201 ms | — |
| **Field INP (CrUX p75)** | 🟡 239 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.000 | — |
| Field TTFB (CrUX p75) | 🟡 1294 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~4979 ms)
- **Reduce unused JavaScript** (save ~300 ms, save ~509 KB)
- **Reduce unused CSS** (save ~130 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/library.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/library.desktop.json)

### Subject landing (`/assamboard/class-12/physics`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 37 | 🔴 44 |
| Accessibility | 🟢 90 | 🟢 90 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 16800 ms | 🟡 3548 ms |
| **TBT (lab, INP proxy)** | 🟡 466 ms | 🔴 1137 ms |
| **CLS (lab)** | 🔴 0.284 | 🟡 0.121 |
| FCP (lab) | 🔴 3686 ms | 🟢 634 ms |
| TTFB (lab) | — | 🟢 1 ms |
| Speed Index | 5970 ms | 2052 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~6941 ms)
- **Reduce unused JavaScript** (save ~4680 ms, save ~646 KB)
- **Reduce unused CSS** (save ~320 ms, save ~21 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/subject-landing.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/subject-landing.desktop.json)

### Chapter (`/assamboard/class-12/physics/electric-charges-and-fields`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 36 | 🔴 49 |
| Accessibility | 🟢 91 | 🟢 91 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 18018 ms | 🟡 3129 ms |
| **TBT (lab, INP proxy)** | 🟡 480 ms | 🔴 667 ms |
| **CLS (lab)** | 🟡 0.227 | 🟡 0.158 |
| FCP (lab) | 🔴 6670 ms | 🟢 975 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 6670 ms | 1248 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~6488 ms)
- **Reduce unused JavaScript** (save ~4090 ms, save ~617 KB)
- **Reduce unused CSS** (save ~150 ms, save ~21 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/chapter.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/chapter.desktop.json)

### AI Chat (`/chat`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 60 | 🟡 76 |
| Accessibility | 🟢 96 | 🟢 96 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 54 | 🟡 54 |
| **LCP (lab)** | 🔴 10646 ms | 🟢 2339 ms |
| **TBT (lab, INP proxy)** | 🟢 187 ms | 🟡 255 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 4850 ms | 🟢 1022 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 4850 ms | 1265 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5281 ms)
- **Reduce unused JavaScript** (save ~3300 ms, save ~665 KB)
- **Reduce unused CSS** (save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/chat.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/chat.desktop.json)

### Login (`/login`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 53 | 🟡 67 |
| Accessibility | 🟡 86 | 🟡 86 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 85 | 🟡 85 |
| **LCP (lab)** | 🔴 8559 ms | 🟢 1929 ms |
| **TBT (lab, INP proxy)** | 🔴 703 ms | 🟡 518 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🟡 2866 ms | 🟢 987 ms |
| TTFB (lab) | 🟢 2 ms | 🟢 1 ms |
| Speed Index | 2866 ms | 1243 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5432 ms)
- **Reduce unused JavaScript** (save ~2240 ms, save ~525 KB)
- **Reduce unused CSS** (save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/login.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/login.desktop.json)

### Signup (`/signup`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 19 | 🟡 77 |
| Accessibility | 🟡 87 | 🟡 86 |
| Best Practices | 🟡 77 | 🟢 96 |
| SEO | 🟡 85 | 🟡 85 |
| **LCP (lab)** | 🔴 10262 ms | 🟢 2380 ms |
| **TBT (lab, INP proxy)** | 🔴 993 ms | 🟡 232 ms |
| **CLS (lab)** | 🔴 0.536 | 🟢 0.000 |
| FCP (lab) | 🟡 2942 ms | 🟢 985 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 7623 ms | 1323 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5733 ms)
- **Reduce unused JavaScript** (save ~2580 ms, save ~629 KB)
- **Reduce unused CSS** (save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/signup.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/signup.desktop.json)

### Profile (`/profile`, logged-out shell)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🔴 44 | 🟡 77 |
| Accessibility | 🟢 96 | 🟢 96 |
| Best Practices | 🟢 96 | 🟡 77 |
| SEO | 🟡 83 | 🟡 85 |
| **LCP (lab)** | 🔴 4975 ms | 🟢 2389 ms |
| **TBT (lab, INP proxy)** | 🔴 3440 ms | 🟡 269 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3093 ms | 🟢 655 ms |
| TTFB (lab) | 🟢 2 ms | 🟢 2 ms |
| Speed Index | 4626 ms | 700 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~4375 ms)
- **Reduce unused JavaScript** (save ~1200 ms, save ~469 KB)
- **Reduce unused CSS** (save ~260 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/profile.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/profile.desktop.json)

### Pricing (`/pricing`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 55 | 🟡 85 |
| Accessibility | 🟢 93 | 🟢 92 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 5255 ms | 🟢 2351 ms |
| **TBT (lab, INP proxy)** | 🔴 654 ms | 🟢 88 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3168 ms | 🟢 967 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 5070 ms | 1341 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~4073 ms)
- **Reduce unused JavaScript** (save ~900 ms, save ~480 KB)
- **Reduce unused CSS** (save ~260 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/pricing.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/pricing.desktop.json)

### Admin login (`/admin/login`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 53 | 🟡 74 |
| Accessibility | 🟡 81 | 🟡 81 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 54 | 🟡 54 |
| **LCP (lab)** | 🔴 9210 ms | 🟢 1971 ms |
| **TBT (lab, INP proxy)** | 🟡 355 ms | 🟡 342 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 5284 ms | 🟢 1088 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 5284 ms | 1088 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5432 ms)
- **Reduce unused JavaScript** (save ~3370 ms, save ~651 KB)
- **Reduce unused CSS** (save ~150 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/admin-login.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/admin-login.desktop.json)

### About (`/about`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 51 | 🟡 65 |
| Accessibility | 🟢 91 | 🟡 89 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 9859 ms | 🟢 2353 ms |
| **TBT (lab, INP proxy)** | 🔴 742 ms | 🟡 530 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3017 ms | 🟢 633 ms |
| TTFB (lab) | 🟢 2 ms | 🟢 2 ms |
| Speed Index | 3647 ms | 938 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5733 ms)
- **Reduce unused JavaScript** (save ~2430 ms, save ~544 KB)
- **Reduce unused CSS** (save ~180 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/about.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/about.desktop.json)

### Technology (`/technology`)

| Metric | 📱 Mobile | 💻 Desktop |
|---|---|---|
| Performance | 🟡 50 | 🟡 64 |
| Accessibility | 🟢 94 | 🟢 94 |
| Best Practices | 🟢 96 | 🟢 96 |
| SEO | 🟡 83 | 🟡 83 |
| **LCP (lab)** | 🔴 11388 ms | 🟢 2435 ms |
| **TBT (lab, INP proxy)** | 🔴 611 ms | 🟡 551 ms |
| **CLS (lab)** | 🟢 0.000 | 🟢 0.000 |
| FCP (lab) | 🔴 3838 ms | 🟢 615 ms |
| TTFB (lab) | 🟢 1 ms | 🟢 1 ms |
| Speed Index | 4280 ms | 1100 ms |
| **Field LCP (CrUX p75)** | 🔴 5659 ms | — |
| **Field INP (CrUX p75)** | 🟢 192 ms | — |
| **Field CLS (CrUX p75)** | 🟢 0.010 | — |
| Field TTFB (CrUX p75) | 🟡 1159 ms | — |

**Top mobile opportunities:**

- **Avoid multiple page redirects** (save ~5582 ms)
- **Reduce unused JavaScript** (save ~4480 ms, save ~683 KB)
- **Reduce unused CSS** (save ~150 ms, save ~20 KB)

📄 Raw JSON: [mobile](./pagespeed-2026-04-18-raw/technology.mobile.json) · [desktop](./pagespeed-2026-04-18-raw/technology.desktop.json)

## Top 10 Prioritized Fixes

Ranked by **estimated cumulative mobile savings × number of routes affected**. Mobile is weighted heavier because it drives both UX and SEO ranking.

| # | Fix (Lighthouse audit) | Affects | Est. cumulative savings | Mobile-impact |
|---|---|---|---|---|
| 1 | **Reduce unused JavaScript** (`unused-javascript`) | 12 routes (24 runs, 12 mobile) | 36000 ms · 13961 KB | Very high |
| 2 | **Avoid multiple page redirects** (`redirects`) | 12 routes (24 runs, 12 mobile) | 77817 ms | Very high |
| 3 | **Minimize main-thread work** (`mainthread-work-breakdown`) | 12 routes (24 runs, 12 mobile) | 46100 ms | Very high |
| 4 | **Reduce JavaScript execution time** (`bootup-time`) | 12 routes (23 runs, 12 mobile) | 35929 ms | Very high |
| 5 | **Reduce unused CSS** (`unused-css-rules`) | 12 routes (24 runs, 12 mobile) | 1900 ms · 494 KB | Very high |
| 6 | **Document does not have a valid `rel=canonical`** (`canonical`) | 12 routes (24 runs, 12 mobile) | failing (see audit) | Very high |
| 7 | **Background and foreground colors do not have a sufficient contrast ratio.** (`color-contrast`) | 12 routes (24 runs, 12 mobile) | failing (see audit) | Very high |
| 8 | **Render blocking requests** (`render-blocking-insight`) | 12 routes (24 runs, 12 mobile) | failing (Est savings of 40 ms) | Very high |
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

---

## Re-audit follow-up — 2026-04-18 (rerun)

A second PSI run was executed against `https://syrabit.ai` later the same day to confirm the baseline before kicking off the 100/100 work in task #497. The fresh report is at [`pagespeed-2026-04-18-rerun.md`](./pagespeed-2026-04-18-rerun.md) with raw JSON in [`pagespeed-2026-04-18-rerun-raw/`](./pagespeed-2026-04-18-rerun-raw/).

### Aggregate before → after (mobile)

| Metric | Original | Rerun | Δ |
|---|---|---|---|
| Avg Performance | 47 | **43** | 🔴 −4 |
| Avg Accessibility | 91 | 91 | — |
| Avg Best Practices | 91 | **93** | 🟢 +2 |
| Avg SEO | 79 | 79 | — |
| Routes failing perf (<50) | 5/12 | **8/12** | 🔴 +3 |
| Routes passing perf (≥90) | 0/12 | 0/12 | — |
| Worst mobile LCP | chapter 18.0 s | subject-landing 15.1 s | 🟢 −2.9 s |

### Per-route mobile Performance, before → after

| Route | Original | Rerun | Δ |
|---|---|---|---|
| `/home` | 62 | 34 | 🔴 −28 |
| `/library` | 39 | 37 | 🔴 −2 |
| `/assamboard/class-12/physics` | 37 | 22 | 🔴 −15 |
| `/assamboard/class-12/physics/electric-charges-and-fields` | 36 | 35 | 🔴 −1 |
| `/chat` | 60 | 40 | 🔴 −20 |
| `/login` | 53 | 49 | 🔴 −4 |
| `/signup` | 19 | 50 | 🟢 +31 |
| `/profile` | 44 | 46 | 🟢 +2 |
| `/pricing` | 55 | 40 | 🔴 −15 |
| `/admin/login` | 53 | 52 | 🔴 −1 |
| `/about` | 51 | 50 | 🔴 −1 |
| `/technology` | 50 | 60 | 🟢 +10 |

### What changed since the original report

- The **two SEO red flags called out in the original executive summary are partially resolved in code already**:
  - Static `<link rel="canonical" href="https://syrabit.ai/">` was removed from `artifacts/syrabit/index.html`; per-route canonicals are now owned by `react-helmet-async` via `PageMeta`. **However, Lighthouse still fails the `canonical` audit on all 12 routes** because the canonical isn't in the initial HTML — it's injected by React after hydration. To pass, the canonical must be present in the byte-zero HTML (per-route prerender, edge worker, or backend render).
  - `/chat` is no longer in any `Disallow` block in `robots.txt`. The `is-crawlable` failure on `/chat` and `/admin/login` in the rerun is now driven by other signals (likely `<meta name="robots">` or response header), not robots.txt.
- The **redirect chain (~3.6–7.5 s on every route, top opportunity by cumulative ms)** has not been touched and is still the single biggest perf lever.
- Variance: PSI lab runs are noisy (CPU contention in Google's datacenter), so single-route deltas of ±10 are not unusual. The trend across the surface is what matters: still 0/12 passing, still no green Core Web Vitals on mobile.

### Recommendation for task #497 scope

Hitting **100/100 across 4 categories × 12 routes × 2 strategies = 96 perfect cells** is not a realistic single-task goal — most highly-tuned production SPAs land at 95–99 on mobile Performance and one CrUX p75 drift can knock it off. Suggest:

1. Re-scope #497 as **"all routes ≥ 95 in every category, all CWV in green on mobile lab + CrUX p75"** — that's the bar Google actually rewards in Search rankings.
2. Split the 11 sub-steps in the task description into focused follow-up tasks (redirect chain, per-route SSR canonical, JS code-split, critical CSS, color-contrast tokens, security headers + Best Practices, SEO metadata, CWV CLS/LCP, CI guardrail). Each is a 1–2 day task on its own.
