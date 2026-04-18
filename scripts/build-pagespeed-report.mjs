#!/usr/bin/env node
// Reads docs/audits/pagespeed-<date>-raw/*.json and emits a single audit
// report markdown file with executive summary, per-URL tables (mobile +
// desktop), aggregated Top 10 fixes, and links back to the raw JSON.

import fs from 'fs';
import path from 'path';

const DATE = process.env.AUDIT_DATE || '2026-04-18';
const ORIGIN = process.env.AUDIT_ORIGIN || 'https://syrabit.ai';
const RAW_DIR = `docs/audits/pagespeed-${DATE}-raw`;
const OUT_FILE = `docs/audits/pagespeed-${DATE}.md`;

const ROUTE_LABELS = {
  'home':             { label: 'Home (`/home`)',                                 path: '/home' },
  'library':          { label: 'Library (`/library`)',                           path: '/library' },
  'subject-landing':  { label: 'Subject landing (`/assamboard/class-12/physics`)', path: '/assamboard/class-12/physics' },
  'chapter':          { label: 'Chapter (`/assamboard/class-12/physics/electric-charges-and-fields`)', path: '/assamboard/class-12/physics/electric-charges-and-fields' },
  'chat':             { label: 'AI Chat (`/chat`)',                              path: '/chat' },
  'login':            { label: 'Login (`/login`)',                               path: '/login' },
  'signup':           { label: 'Signup (`/signup`)',                             path: '/signup' },
  'profile':          { label: 'Profile (`/profile`, logged-out shell)',         path: '/profile' },
  'pricing':          { label: 'Pricing (`/pricing`)',                           path: '/pricing' },
  'admin-login':      { label: 'Admin login (`/admin/login`)',                   path: '/admin/login' },
  'about':            { label: 'About (`/about`)',                               path: '/about' },
  'technology':       { label: 'Technology (`/technology`)',                     path: '/technology' },
};

const ROUTE_ORDER = Object.keys(ROUTE_LABELS);

// Google Core Web Vitals thresholds (lab Lighthouse units).
const CWV_THRESHOLDS = {
  LCP:  { good: 2500, poor: 4000, unit: 'ms' },
  INP:  { good: 200,  poor: 500,  unit: 'ms' }, // PSI lab uses TBT/INP estimate; we read CrUX INP if present, lab INP rarely emitted
  TBT:  { good: 200,  poor: 600,  unit: 'ms' }, // Lab proxy for INP
  CLS:  { good: 0.1,  poor: 0.25, unit: '' },
  FCP:  { good: 1800, poor: 3000, unit: 'ms' },
  TTFB: { good: 800,  poor: 1800, unit: 'ms' },
};

function loadJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch { return null; }
}

function pct(n) { return n == null ? '—' : Math.round(n * 100); }
function fmtMs(n) { return n == null ? '—' : `${Math.round(n)} ms`; }
function fmtCls(n) { return n == null ? '—' : (Math.round(n * 1000) / 1000).toFixed(3); }
function fmtKb(bytes) { return bytes == null ? '—' : `${(bytes / 1024).toFixed(0)} KB`; }
function badge(value, kind) {
  if (value == null) return '—';
  const t = CWV_THRESHOLDS[kind];
  if (!t) return String(value);
  if (value <= t.good) return `🟢 ${kind === 'CLS' ? fmtCls(value) : fmtMs(value)}`;
  if (value <= t.poor) return `🟡 ${kind === 'CLS' ? fmtCls(value) : fmtMs(value)}`;
  return `🔴 ${kind === 'CLS' ? fmtCls(value) : fmtMs(value)}`;
}

function scoreBadge(score) {
  if (score == null) return '—';
  const v = Math.round(score * 100);
  if (v >= 90) return `🟢 ${v}`;
  if (v >= 50) return `🟡 ${v}`;
  return `🔴 ${v}`;
}

function extractMetrics(data) {
  if (!data || !data.lighthouseResult) return null;
  const lh = data.lighthouseResult;
  const cats = lh.categories || {};
  const audits = lh.audits || {};
  const m = audits.metrics?.details?.items?.[0] || {};
  const lab = {
    LCP:  m.largestContentfulPaint ?? audits['largest-contentful-paint']?.numericValue,
    FCP:  m.firstContentfulPaint ?? audits['first-contentful-paint']?.numericValue,
    CLS:  m.cumulativeLayoutShift ?? audits['cumulative-layout-shift']?.numericValue,
    TBT:  m.totalBlockingTime ?? audits['total-blocking-time']?.numericValue,
    SI:   m.speedIndex ?? audits['speed-index']?.numericValue,
    TTFB: audits['server-response-time']?.numericValue,
  };
  const field = data.loadingExperience?.metrics
    ? {
        LCP:  data.loadingExperience.metrics.LARGEST_CONTENTFUL_PAINT_MS?.percentile,
        INP:  data.loadingExperience.metrics.INTERACTION_TO_NEXT_PAINT?.percentile,
        CLS:  data.loadingExperience.metrics.CUMULATIVE_LAYOUT_SHIFT_SCORE?.percentile / 100,
        FCP:  data.loadingExperience.metrics.FIRST_CONTENTFUL_PAINT_MS?.percentile,
        TTFB: data.loadingExperience.metrics.EXPERIMENTAL_TIME_TO_FIRST_BYTE?.percentile,
        category: data.loadingExperience.overall_category,
      }
    : null;
  // Lighthouse v12 collapsed many "opportunities" into "diagnostics" without
  // overallSavingsMs. To get a useful Top-N list we also include high-signal
  // diagnostic audits that fail (score < 0.9) and use their numericValue as
  // a savings-equivalent proxy where meaningful.
  const DIAG_AS_OPP = {
    'bootup-time':                 { useNumericMs: true,  weight: 0.6 },
    'mainthread-work-breakdown':   { useNumericMs: true,  weight: 0.4 },
    'render-blocking-resources':   { useNumericMs: true,  weight: 1.0 },
    'render-blocking-insight':     { useNumericMs: true,  weight: 1.0 },
    'total-byte-weight':           { useNumericMs: false, weight: 1.0, bytesDivisor: 1 },
    'dom-size':                    { useNumericMs: false, weight: 1.0 },
    'uses-long-cache-ttl':         { useNumericMs: false, weight: 1.0 },
    'font-display':                { useNumericMs: false, weight: 1.0 },
    'duplicated-javascript':       { useNumericMs: false, weight: 1.0 },
    'legacy-javascript':           { useNumericMs: false, weight: 1.0 },
    'third-party-summary':         { useNumericMs: false, weight: 1.0 },
    'lcp-lazy-loaded':             { useNumericMs: false, weight: 1.0 },
    'prioritize-lcp-image':        { useNumericMs: false, weight: 1.0 },
    'non-composited-animations':   { useNumericMs: false, weight: 1.0 },
    'unsized-images':              { useNumericMs: false, weight: 1.0 },
    'color-contrast':              { useNumericMs: false, weight: 1.0, category: 'a11y' },
    'image-alt':                   { useNumericMs: false, weight: 1.0, category: 'a11y' },
    'canonical':                   { useNumericMs: false, weight: 1.0, category: 'seo' },
    'meta-description':            { useNumericMs: false, weight: 1.0, category: 'seo' },
    'link-text':                   { useNumericMs: false, weight: 1.0, category: 'seo' },
    'tap-targets':                 { useNumericMs: false, weight: 1.0, category: 'seo' },
    'crawlable-anchors':           { useNumericMs: false, weight: 1.0, category: 'seo' },
    'http-status-code':            { useNumericMs: false, weight: 1.0, category: 'seo' },
    'is-crawlable':                { useNumericMs: false, weight: 1.0, category: 'seo' },
  };
  const opps = [];
  const diagnostics = [];
  for (const [id, audit] of Object.entries(audits)) {
    if (!audit || audit.scoreDisplayMode === 'manual' || audit.scoreDisplayMode === 'notApplicable') continue;
    const det = audit.details;
    const savingsMs = det?.overallSavingsMs;
    const savingsBytes = det?.overallSavingsBytes;
    if ((savingsMs && savingsMs >= 50) || (savingsBytes && savingsBytes >= 5000)) {
      opps.push({ id, title: audit.title, savingsMs: savingsMs || 0, savingsBytes: savingsBytes || 0, score: audit.score, kind: 'opportunity' });
      continue;
    }
    const cfg = DIAG_AS_OPP[id];
    if (cfg && audit.score != null && audit.score < 0.9) {
      const ms = cfg.useNumericMs && audit.numericValue ? audit.numericValue * cfg.weight : 0;
      diagnostics.push({
        id,
        title: audit.title,
        displayValue: audit.displayValue || '',
        score: audit.score,
        savingsMs: ms,
        savingsBytes: 0,
        kind: 'diagnostic',
        category: cfg.category || 'perf',
      });
    }
  }
  opps.sort((a, b) => (b.savingsMs - a.savingsMs) || (b.savingsBytes - a.savingsBytes));
  diagnostics.sort((a, b) => b.savingsMs - a.savingsMs);
  return {
    scores: {
      performance:    cats.performance?.score,
      accessibility:  cats.accessibility?.score,
      bestPractices:  cats['best-practices']?.score,
      seo:            cats.seo?.score,
    },
    lab,
    field,
    opportunities: opps,
    diagnostics,
    fetchTime: lh.fetchTime,
    finalUrl: lh.finalUrl,
  };
}

function loadRoute(id) {
  const m = loadJson(path.join(RAW_DIR, `${id}.mobile.json`));
  const d = loadJson(path.join(RAW_DIR, `${id}.desktop.json`));
  return {
    id,
    label: ROUTE_LABELS[id]?.label || id,
    path: ROUTE_LABELS[id]?.path || '/',
    mobile: extractMetrics(m),
    desktop: extractMetrics(d),
  };
}

const routes = ROUTE_ORDER.map(loadRoute);

// ── Aggregate Top 10 fixes ──────────────────────────────────────────────────
const oppMap = new Map(); // id -> { title, totalMs, totalBytes, count, mobileCount, kind }
for (const r of routes) {
  for (const which of ['mobile', 'desktop']) {
    const m = r[which];
    if (!m) continue;
    for (const o of [...m.opportunities, ...m.diagnostics]) {
      const k = o.id;
      const cur = oppMap.get(k) || {
        id: k, title: o.title, totalMs: 0, totalBytes: 0,
        count: 0, mobileCount: 0, routes: new Set(), kind: o.kind,
        sampleDisplay: o.displayValue || '',
      };
      cur.totalMs += o.savingsMs || 0;
      cur.totalBytes += o.savingsBytes || 0;
      cur.count += 1;
      if (which === 'mobile') cur.mobileCount += 1;
      cur.routes.add(r.id);
      if (o.displayValue && !cur.sampleDisplay) cur.sampleDisplay = o.displayValue;
      oppMap.set(k, cur);
    }
  }
}
const topFixes = [...oppMap.values()]
  // Rank by mobile-weighted savings × frequency. Mobile counts double because
  // mobile LCP/INP drive both UX and SEO ranking.
  .map((o) => ({
    ...o,
    score: (o.totalMs * (1 + o.mobileCount / Math.max(o.count, 1)))
         + (o.totalBytes / 1024) * 5,
  }))
  .sort((a, b) => b.score - a.score)
  .slice(0, 10);

// ── Executive summary ──────────────────────────────────────────────────────
function avgScore(routes, key, which) {
  const vals = routes.map((r) => r[which]?.scores?.[key]).filter((v) => v != null);
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

const avg = {
  mobilePerf: avgScore(routes, 'performance', 'mobile'),
  desktopPerf: avgScore(routes, 'performance', 'desktop'),
  mobileSeo: avgScore(routes, 'seo', 'mobile'),
  mobileA11y: avgScore(routes, 'accessibility', 'mobile'),
  mobileBp: avgScore(routes, 'bestPractices', 'mobile'),
};

function worstLcp(which) {
  let worst = { id: null, val: -1 };
  for (const r of routes) {
    const v = r[which]?.lab?.LCP;
    if (v != null && v > worst.val) worst = { id: r.id, val: v };
  }
  return worst;
}
const worstMobileLcp = worstLcp('mobile');

const failingMobilePerf = routes.filter((r) => r.mobile?.scores?.performance != null && r.mobile.scores.performance < 0.5);
const passingMobilePerf = routes.filter((r) => r.mobile?.scores?.performance != null && r.mobile.scores.performance >= 0.9);

// ── Markdown output ─────────────────────────────────────────────────────────
let md = '';
md += `# PageSpeed Audit — Syrabit.ai (${DATE})\n\n`;
md += `**Origin audited:** \`${ORIGIN}\` (production)  \n`;
md += `**Strategy:** Mobile + Desktop  \n`;
md += `**URLs audited:** ${routes.length} (24 total runs)  \n`;
md += `**Tool:** Google PageSpeed Insights API v5 (Lighthouse 12.x lab + CrUX field data)  \n`;
md += `**Raw JSON:** [\`docs/audits/pagespeed-${DATE}-raw/\`](./pagespeed-${DATE}-raw/)\n\n`;

md += `## Executive Summary\n\n`;
md += `- **Average mobile Performance score: ${avg.mobilePerf != null ? Math.round(avg.mobilePerf * 100) : '—'}/100** (${avg.desktopPerf != null ? Math.round(avg.desktopPerf * 100) + '/100 desktop' : 'desktop unavailable'}). ` +
      `Mobile is the SEO ranking signal Google uses, so this is the headline number to move.\n`;
md += `- **${failingMobilePerf.length}/${routes.length} routes fail mobile performance (< 50)**: ` +
      `${failingMobilePerf.map((r) => '`' + r.path + '`').join(', ') || 'none'}. ` +
      `**${passingMobilePerf.length}/${routes.length} pass at 90+**.\n`;
md += `- **Worst mobile LCP: \`${worstMobileLcp.id}\` at ${fmtMs(worstMobileLcp.val)}** ` +
      `(Google "good" threshold is ≤ 2.5 s). LCP is the single biggest perf-driven ranking factor.\n`;
md += `- **Average mobile SEO score: ${Math.round((avg.mobileSeo || 0) * 100)}/100**, ` +
      `**Accessibility: ${Math.round((avg.mobileA11y || 0) * 100)}/100**, ` +
      `**Best Practices: ${Math.round((avg.mobileBp || 0) * 100)}/100** — keep these ≥ 95 to avoid soft ranking penalties.\n`;
md += `- **Top opportunity overall: "${topFixes[0]?.title || '—'}"** ` +
      `(estimated ${Math.round(topFixes[0]?.totalMs || 0)} ms / ${fmtKb(topFixes[0]?.totalBytes || 0)} cumulative savings across the audited surface). ` +
      `See [Top 10 fixes](#top-10-prioritized-fixes) below.\n\n`;

// SEO red flags: data-driven from this run's diagnostics so the section
// never goes stale relative to the raw audit data.
function countRouteFailures(auditId) {
  let count = 0;
  const failedRoutes = [];
  for (const r of routes) {
    const m = r.mobile;
    if (!m) continue;
    const hit = m.diagnostics.find((d) => d.id === auditId) || m.opportunities.find((o) => o.id === auditId);
    if (hit) { count += 1; failedRoutes.push(r.path); }
  }
  return { count, failedRoutes };
}
const canonicalFails = countRouteFailures('canonical');
const crawlableFails = countRouteFailures('is-crawlable');
const seoRedFlags = [];
if (canonicalFails.count > 0) {
  seoRedFlags.push(
    `**${canonicalFails.count}/${routes.length} mobile routes fail Lighthouse's \`canonical\` SEO audit.** ` +
    `Failing routes: ${canonicalFails.failedRoutes.map((p) => '`' + p + '`').join(', ')}. ` +
    `Most common cause: per-route canonicals are emitted by client-side React after hydration, so the byte-zero HTML Lighthouse evaluates has no canonical (or has a stale, hard-coded one in \`index.html\`). Fix: emit the correct canonical at SSR/prerender/edge-render time so it's present on the first byte.`
  );
}
if (crawlableFails.count > 0) {
  seoRedFlags.push(
    `**${crawlableFails.count}/${routes.length} mobile routes fail \`is-crawlable\`** (page blocked from indexing). ` +
    `Failing routes: ${crawlableFails.failedRoutes.map((p) => '`' + p + '`').join(', ')}. ` +
    `Check \`robots.txt\`, \`<meta name="robots">\` tags, and \`X-Robots-Tag\` response headers for these paths. Some (e.g. \`/admin/login\`) may be intentionally blocked.`
  );
}
if (seoRedFlags.length > 0) {
  md += `### 🚨 SEO red flags detected in this run\n\n`;
  seoRedFlags.forEach((line, i) => { md += `${i + 1}. ${line}\n`; });
  md += `\n`;
}

md += `> **Reading the badges:** 🟢 = passes Google's "good" threshold · 🟡 = "needs improvement" · 🔴 = "poor". ` +
      `LCP ≤ 2500 ms, INP ≤ 200 ms, CLS ≤ 0.10, FCP ≤ 1800 ms, TTFB ≤ 800 ms.\n\n`;

// Per-URL tables
md += `## Per-URL Results\n\n`;
for (const r of routes) {
  md += `### ${r.label}\n\n`;
  if (!r.mobile && !r.desktop) {
    md += `_No data — both runs failed._\n\n`;
    continue;
  }
  md += `| Metric | 📱 Mobile | 💻 Desktop |\n`;
  md += `|---|---|---|\n`;
  md += `| Performance | ${scoreBadge(r.mobile?.scores.performance)} | ${scoreBadge(r.desktop?.scores.performance)} |\n`;
  md += `| Accessibility | ${scoreBadge(r.mobile?.scores.accessibility)} | ${scoreBadge(r.desktop?.scores.accessibility)} |\n`;
  md += `| Best Practices | ${scoreBadge(r.mobile?.scores.bestPractices)} | ${scoreBadge(r.desktop?.scores.bestPractices)} |\n`;
  md += `| SEO | ${scoreBadge(r.mobile?.scores.seo)} | ${scoreBadge(r.desktop?.scores.seo)} |\n`;
  md += `| **LCP (lab)** | ${badge(r.mobile?.lab.LCP, 'LCP')} | ${badge(r.desktop?.lab.LCP, 'LCP')} |\n`;
  md += `| **TBT (lab, INP proxy)** | ${badge(r.mobile?.lab.TBT, 'TBT')} | ${badge(r.desktop?.lab.TBT, 'TBT')} |\n`;
  md += `| **CLS (lab)** | ${badge(r.mobile?.lab.CLS, 'CLS')} | ${badge(r.desktop?.lab.CLS, 'CLS')} |\n`;
  md += `| FCP (lab) | ${badge(r.mobile?.lab.FCP, 'FCP')} | ${badge(r.desktop?.lab.FCP, 'FCP')} |\n`;
  md += `| TTFB (lab) | ${badge(r.mobile?.lab.TTFB, 'TTFB')} | ${badge(r.desktop?.lab.TTFB, 'TTFB')} |\n`;
  md += `| Speed Index | ${fmtMs(r.mobile?.lab.SI)} | ${fmtMs(r.desktop?.lab.SI)} |\n`;

  // Field (CrUX) data
  const fieldRows = [];
  if (r.mobile?.field || r.desktop?.field) {
    fieldRows.push(`| **Field LCP (CrUX p75)** | ${badge(r.mobile?.field?.LCP, 'LCP')} | ${badge(r.desktop?.field?.LCP, 'LCP')} |`);
    fieldRows.push(`| **Field INP (CrUX p75)** | ${badge(r.mobile?.field?.INP, 'INP')} | ${badge(r.desktop?.field?.INP, 'INP')} |`);
    fieldRows.push(`| **Field CLS (CrUX p75)** | ${badge(r.mobile?.field?.CLS, 'CLS')} | ${badge(r.desktop?.field?.CLS, 'CLS')} |`);
    fieldRows.push(`| Field TTFB (CrUX p75) | ${badge(r.mobile?.field?.TTFB, 'TTFB')} | ${badge(r.desktop?.field?.TTFB, 'TTFB')} |`);
    md += fieldRows.join('\n') + '\n';
  } else {
    md += `\n_No CrUX field data available — page has insufficient real-user traffic._\n`;
  }

  // Top opportunities (mobile)
  const opps = (r.mobile?.opportunities || []).slice(0, 5);
  if (opps.length) {
    md += `\n**Top mobile opportunities:**\n\n`;
    for (const o of opps) {
      const parts = [];
      if (o.savingsMs) parts.push(`save ~${Math.round(o.savingsMs)} ms`);
      if (o.savingsBytes) parts.push(`save ~${fmtKb(o.savingsBytes)}`);
      md += `- **${o.title}** (${parts.join(', ') || 'see audit'})\n`;
    }
  }
  md += `\n📄 Raw JSON: [mobile](./pagespeed-${DATE}-raw/${r.id}.mobile.json) · [desktop](./pagespeed-${DATE}-raw/${r.id}.desktop.json)\n\n`;
}

// Top 10 fixes
md += `## Top 10 Prioritized Fixes\n\n`;
md += `Ranked by **estimated cumulative mobile savings × number of routes affected**. Mobile is weighted heavier because it drives both UX and SEO ranking.\n\n`;
md += `| # | Fix (Lighthouse audit) | Affects | Est. cumulative savings | Mobile-impact |\n`;
md += `|---|---|---|---|---|\n`;
topFixes.forEach((o, i) => {
  const where = `${o.routes.size} route${o.routes.size === 1 ? '' : 's'} (${o.count} runs, ${o.mobileCount} mobile)`;
  const savings = [
    o.totalMs ? `${Math.round(o.totalMs)} ms` : null,
    o.totalBytes ? fmtKb(o.totalBytes) : null,
    o.kind === 'diagnostic' && !o.totalMs && !o.totalBytes ? `failing (${o.sampleDisplay || 'see audit'})` : null,
  ].filter(Boolean).join(' · ') || '—';
  const impact = o.mobileCount >= 8 ? 'Very high' : o.mobileCount >= 4 ? 'High' : 'Medium';
  md += `| ${i + 1} | **${o.title}** (\`${o.id}\`) | ${where} | ${savings} | ${impact} |\n`;
});
md += `\n`;

md += `## Methodology\n\n`;
md += `- Each URL ran twice: \`strategy=mobile\` (Moto G Power, throttled 4G/CPU 4×) and \`strategy=desktop\` (1350×940, throttled cable/CPU 1×). These are Google's standard PSI environments and match what gets used for [Search ranking signals](https://developers.google.com/search/docs/appearance/page-experience).\n`;
md += `- Categories requested: \`performance\`, \`accessibility\`, \`best-practices\`, \`seo\`.\n`;
md += `- Lab metrics (LCP, FCP, CLS, TBT, SI, TTFB) come from Lighthouse running in a Google datacenter; field metrics (CrUX p75 LCP/INP/CLS/TTFB) come from anonymized Chrome real-user data over the trailing 28 days.\n`;
md += `- Top 10 fixes ranking formula: \`savings_ms × (1 + mobileShare) + savings_KB × 5\`. This favours fixes that compound across multiple mobile routes over single-route wins.\n`;
md += `- Reproducibility: re-run \`PAGESPEED_API_KEY=… node scripts/run-pagespeed-audit.mjs\` then \`node scripts/build-pagespeed-report.mjs\`.\n\n`;

md += `## Out of scope (per task #493)\n\n`;
md += `- No code changes were made — this report is audit-only. Fixes from the Top 10 list should be opened as separate, focused tasks.\n`;
md += `- Authenticated-only flows were not exercised: \`/profile\` and \`/admin\` were audited as their logged-out shells (the auth guard renders a redirect/login skeleton, which is what crawlers see anyway).\n`;
md += `- Backend latency was not load-tested separately — TTFB numbers above come from the single PSI request and reflect cold-cache CDN behaviour at the moment of the audit.\n`;

fs.writeFileSync(OUT_FILE, md);
console.log(`Wrote ${OUT_FILE} (${md.length} bytes)`);
