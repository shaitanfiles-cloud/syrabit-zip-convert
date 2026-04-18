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

## Re-audit follow-up — Task #498 fix landed (2026-04-18)

**Top fix #1 ("Avoid multiple page redirects") root-caused and patched.**

### What Lighthouse was actually reporting

Every audited route showed the `redirects` audit failing with a 2-hop "chain" where both hops have the **same URL** (`/<route>` → `/<route>`) and the first hop "wastes" 3.6–7.5 s of simulated time. A `curl -IL` against any of those URLs returns `HTTP 200` in ~120 ms with `num_redirects=0` — there is no HTTP 3xx hop on the wire.

Inspection of `lighthouseResult.audits.network-requests` for `/home` shows two `Document` requests for `https://syrabit.ai/home`:

| # | networkRequestTime | rendererStartTime | priority | experimentalFromMainFrame |
|---|---|---|---|---|
| 1 | 1 ms | 0 (initial nav) | VeryHigh | true |
| 2 | 854 ms | 853 ms (JS-initiated) | VeryHigh | true |

Lighthouse's `redirects` audit reads the network analysis output and treats this duplicate same-URL Document fetch as a redirect chain on the main resource. The simulator (Slow 4G + 4× CPU) scales the ~850 ms real-world gap to the ~5 s "savings" reported across every route.

### Root cause

`artifacts/syrabit/src/index.jsx` registered the Service Worker on the `load` event. The SW's `activate` handler in `public/sw.js` calls `self.clients.claim()`. On a fresh visit (no prior SW), the page transitions from "uncontrolled" to "controlled by the just-activated SW", which fires `controllerchange` on the page. The page's listener then ran `window.location.reload()` — intended for SW *upgrades* (so users see new assets immediately) but firing on every cold install too.

That reload is the second `/home` Document fetch in the trace. It accounts for 100% of the wasted time the `redirects` audit is reporting.

### Fix

Snapshot `navigator.serviceWorker.controller` *before* registering. Skip the reload when there was no controller at registration time (= first install, not an upgrade).

```diff
+const hadInitialController = !!navigator.serviceWorker.controller;
 navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" })
 …
 navigator.serviceWorker.addEventListener("controllerchange", () => {
-  if (!refreshing) {
-    refreshing = true;
-    window.location.reload();
-  }
+  if (refreshing) return;
+  if (!hadInitialController) return;  // first install, not an upgrade
+  refreshing = true;
+  window.location.reload();
 });
```

Upgrade behaviour is preserved: when a returning user already has a controlling SW and a new SW takes over, `hadInitialController` is `true` and the reload still fires (so they pick up the new bundle in one tick instead of waiting for a manual refresh).

### Expected impact

- `redirects` audit goes from `Est savings of 3,620–7,544 ms` (failing on 12/12 routes) → 0 ms / passing on every route.
- Aggregate mobile Performance: removes ~5 s of simulated TTFB/FCP/LCP from each cold load. Per route, this should translate to roughly +10–15 Lighthouse Performance points (the redirects audit feeds into FCP and LCP).
- No effect on returning users with a SW already controlling the page (upgrade reload still fires as before).

A fresh PSI run cannot be executed from this environment — the change has to land in the next Pages deploy first. After deploy, re-run `node scripts/run-pagespeed-audit.mjs` then `node scripts/build-pagespeed-report.mjs` to confirm the `redirects` audit clears and to capture the per-route Performance delta.

## Re-audit run #2 — Task #503 (2026-04-18, post-contrast-fix verification)

A fresh PSI run was kicked off after Task #500 to confirm the `color-contrast`
audit clears on all 12 routes and that Accessibility lifts to 100 (or ≥ 95).
Raw JSON for this run lives in
[`docs/audits/pagespeed-2026-04-18-rerun-raw/`](./pagespeed-2026-04-18-rerun-raw/)
(the original first-rerun JSON was overwritten — the new files **are** the
post-fix snapshot). The full per-URL tables and Top-10 generated from the new
data are in [`pagespeed-2026-04-18-rerun-2.md`](./pagespeed-2026-04-18-rerun-2.md).

### Headline numbers (mobile)

| Metric | Before fix (rerun #1) | After fix (rerun #2) | Target | Status |
|---|---|---|---|---|
| Avg Accessibility score | 91 / 100 | **91 / 100** | 100 (≥ 95) | 🔴 unchanged |
| Routes with Accessibility ≥ 95 | 2 / 12 | **2 / 12** | 12 / 12 | 🔴 unchanged |
| Routes with Accessibility = 100 | 0 / 12 | **0 / 12** | 12 / 12 | 🔴 unchanged |
| Routes passing `color-contrast` | 0 / 12 | **0 / 12** | 12 / 12 | 🔴 unchanged |
| Total failing contrast nodes (24 runs, mobile + desktop) | — | **152** | 0 | 🔴 |

Per-route Accessibility / `color-contrast` snapshot (mobile · desktop):

| Route | A11y M · D | `color-contrast` M · D | Failing nodes M · D |
|---|---|---|---|
| `/home` | 93 · 90 | 🔴 0 · 🔴 0 | 20 · 13 |
| `/library` | 94 · 94 | 🔴 0 · 🔴 0 | 12 · 32 |
| `/assamboard/class-12/physics` | 90 · 90 | 🔴 0 · 🔴 0 | 1 · 1 |
| `/assamboard/class-12/physics/electric-charges-and-fields` | 91 · 91 | 🔴 0 · 🔴 0 | 2 · 2 |
| `/chat` | 96 · 96 | 🔴 0 · 🔴 0 | 4 · 6 |
| `/login` | 86 · 86 | 🔴 0 · 🔴 0 | 1 · 1 |
| `/signup` | 86 · 86 | 🔴 0 · 🔴 0 | 1 · 1 |
| `/profile` | 96 · 96 | 🔴 0 · 🔴 0 | 1 · 2 |
| `/pricing` | 93 · 92 | 🔴 0 · 🔴 0 | 6 · 16 |
| `/admin/login` | 81 · 81 | 🔴 0 · 🔴 0 | 1 · 1 |
| `/about` | 91 · 89 | 🔴 0 · 🔴 0 | 1 · 11 |
| `/technology` | 94 · 94 | 🔴 0 · 🔴 0 | 3 · 13 |

### Verdict — task acceptance criteria NOT met

- ❌ `color-contrast` audit does **not** show `score=1` on any of the 12 routes
  (still `score=0` on all 24 mobile + desktop runs, 152 failing nodes total).
- ❌ Accessibility category did not reach 100 on any route, and only 2 / 12
  reach ≥ 95 (`/chat`, `/profile` at 96; identical to rerun #1).
- ✅ Audit pipeline itself ran cleanly (24 / 24 PSI calls succeeded, no errors).

### Why the fix didn't take

The dominant failing color pair is **identical** to what rerun #1 reported, so
the fix from Task #500 did **not** change what the production CSS actually
serves. The five colour pairs that account for **120 / 152** failing nodes are:

| Foreground | Background | Ratio | Needed | Tailwind / CSS source |
|---|---|---|---|---|
| `#607490` | `#f3f3f7` | 4.31 : 1 | 4.5 : 1 | `text-muted-foreground` on default `bg-background` |
| `#607490` | `#f4f3f8` | 4.32 : 1 | 4.5 : 1 | `text-muted-foreground` on slightly tinted card |
| `#607490` | `#eeebf7` | 4.06 : 1 | 4.5 : 1 | `text-muted-foreground` on `library` filter chips |
| `#607490` | `#efedf7` | 4.12 : 1 | 4.5 : 1 | `text-muted-foreground` on `chat` quick-prompt buttons |
| `#8b99af` on `#f0eef7` | — | 2.51 : 1 | 4.5 : 1 | `hsl(var(--muted-foreground) / 0.7)` inline style |

`#607490` is the resolved value of `--muted-foreground` (HSL ≈ `215 22% 47%`).
It is **0.19 contrast points short** of WCAG AA against the page background, so
no amount of "tweaking opacity" inside components will fix it — the token
itself has to be darkened to roughly `215 25% 40%` (approx `#4d5a73`, which
gives ~6.0 : 1) and any `text-muted-foreground/50`, `/70` or
`hsl(var(--muted-foreground) / 0.x)` usages dropped or replaced with a
dedicated lighter token that is only used on *non-text* surfaces (icons, rules).

Two smaller, separate failures remain on form pages:

- `/login`, `/signup`: the password input uses `border-gray-200` on
  `bg-transparent`, resolving to `#e2e8f0` on `#fcfcfd` — **1.2 : 1**, an
  outright invisible border. Bump to `border-gray-300` or darker.
- `/admin/login`: the same input pattern plus a 2nd low-contrast hint string
  pin Accessibility at 81.

### Most likely root cause

The pre-deploy assumption in Task #500 was that the contrast fix had landed in
production, but the new Lighthouse report shows the same exact pixel colours
and node counts as before. Either:
1. The deploy didn't ship — verify the Cloudflare Pages build SHA on
   `https://syrabit.ai` matches the commit that fixed `--muted-foreground`, or
2. The fix only changed Tailwind class definitions in the source bundle but
   the inline `style="color: hsl(var(--muted-foreground) / 0.7)"` usages
   (visible in the failing snippets in `library` and on the home page) bypass
   the token change and still resolve to the old colour.

Either way, the Accessibility = 100 target cannot be claimed yet. A follow-up
should: (a) confirm the build SHA on prod, (b) audit the source for inline
`hsl(var(--muted-foreground) / …)` usages and `text-muted-foreground/{50,70}`
opacity modifiers, (c) darken `--muted-foreground` to ≥ `4.6 : 1` against
`--background` and `--card`, and (d) replace `border-gray-200` with a token
that meets 3 : 1 against the input background. Then re-run this audit.

### How to reproduce

```bash
# Re-audit against prod (uses PAGESPEED_API_KEY from env)
rm -rf docs/audits/pagespeed-2026-04-18-rerun-raw
AUDIT_OUT_DIR=docs/audits/pagespeed-2026-04-18-rerun-raw \
  node scripts/run-pagespeed-audit.mjs

# Build the per-run report (writes pagespeed-2026-04-18-rerun-2.md)
ln -sf pagespeed-2026-04-18-rerun-raw \
  docs/audits/pagespeed-2026-04-18-rerun-2-raw
AUDIT_DATE=2026-04-18-rerun-2 node scripts/build-pagespeed-report.mjs
```
