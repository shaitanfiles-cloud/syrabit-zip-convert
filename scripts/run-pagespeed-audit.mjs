#!/usr/bin/env node
// One-shot PageSpeed Insights audit runner.
// Calls the public PSI API for each URL × strategy pair and writes raw JSON
// to docs/audits/pagespeed-<date>-raw/. No API key required (rate-limited).

import fs from 'fs';
import path from 'path';

const ORIGIN = process.env.AUDIT_ORIGIN || 'https://syrabit.ai';
const OUT_DIR = process.env.AUDIT_OUT_DIR || 'docs/audits/pagespeed-2026-04-18-raw';
const CATEGORIES = ['performance', 'accessibility', 'best-practices', 'seo'];

const ROUTES = [
  { id: 'home',                 path: '/home' },
  { id: 'library',              path: '/library' },
  { id: 'subject-landing',      path: '/assamboard/class-12/physics' },
  { id: 'chapter',              path: '/assamboard/class-12/physics/electric-charges-and-fields' },
  { id: 'chat',                 path: '/chat' },
  { id: 'login',                path: '/login' },
  { id: 'signup',               path: '/signup' },
  { id: 'profile',              path: '/profile' },
  { id: 'pricing',              path: '/pricing' },
  { id: 'admin-login',          path: '/admin/login' },
  { id: 'about',                path: '/about' },
  { id: 'technology',           path: '/technology' },
];

const STRATEGIES = ['mobile', 'desktop'];

fs.mkdirSync(OUT_DIR, { recursive: true });

const API_KEY = process.env.PAGESPEED_API_KEY || '';

function buildUrl(url, strategy) {
  const u = new URL('https://www.googleapis.com/pagespeedonline/v5/runPagespeed');
  u.searchParams.set('url', url);
  u.searchParams.set('strategy', strategy);
  for (const c of CATEGORIES) u.searchParams.append('category', c);
  if (API_KEY) u.searchParams.set('key', API_KEY);
  return u.toString();
}

async function runOne(route, strategy, attempt = 1) {
  const target = `${ORIGIN}${route.path}`;
  const out = path.join(OUT_DIR, `${route.id}.${strategy}.json`);
  if (fs.existsSync(out) && fs.statSync(out).size > 1000) {
    console.log(`SKIP ${route.id} ${strategy} (cached)`);
    return { route, strategy, ok: true, cached: true };
  }
  const apiUrl = buildUrl(target, strategy);
  const t0 = Date.now();
  try {
    const res = await fetch(apiUrl, { headers: { 'accept': 'application/json' } });
    const text = await res.text();
    if (!res.ok) {
      if ((res.status === 429 || res.status >= 500) && attempt < 4) {
        const wait = 2000 * attempt;
        console.warn(`RETRY ${route.id} ${strategy} status=${res.status} in ${wait}ms`);
        await new Promise((r) => setTimeout(r, wait));
        return runOne(route, strategy, attempt + 1);
      }
      fs.writeFileSync(out + '.error', `HTTP ${res.status}\n${text.slice(0, 4000)}`);
      console.error(`FAIL ${route.id} ${strategy} status=${res.status}`);
      return { route, strategy, ok: false, status: res.status };
    }
    fs.writeFileSync(out, text);
    const dt = ((Date.now() - t0) / 1000).toFixed(1);
    console.log(`OK   ${route.id.padEnd(18)} ${strategy.padEnd(7)} ${dt}s`);
    return { route, strategy, ok: true };
  } catch (e) {
    if (attempt < 4) {
      const wait = 2000 * attempt;
      console.warn(`RETRY ${route.id} ${strategy} err=${e.message} in ${wait}ms`);
      await new Promise((r) => setTimeout(r, wait));
      return runOne(route, strategy, attempt + 1);
    }
    fs.writeFileSync(out + '.error', String(e));
    console.error(`FAIL ${route.id} ${strategy} ${e.message}`);
    return { route, strategy, ok: false, err: e.message };
  }
}

async function pool(items, n, fn) {
  const results = [];
  let i = 0;
  const workers = Array.from({ length: n }, async () => {
    while (i < items.length) {
      const idx = i++;
      results[idx] = await fn(items[idx]);
    }
  });
  await Promise.all(workers);
  return results;
}

const tasks = [];
for (const r of ROUTES) for (const s of STRATEGIES) tasks.push({ route: r, strategy: s });

console.log(`Running ${tasks.length} PSI calls against ${ORIGIN} → ${OUT_DIR}`);
const concurrency = parseInt(process.env.AUDIT_CONCURRENCY || '6', 10);
const t0 = Date.now();
const results = await pool(tasks, concurrency, (t) => runOne(t.route, t.strategy));
const dt = ((Date.now() - t0) / 1000).toFixed(1);
const ok = results.filter((r) => r && r.ok).length;
console.log(`\nDone: ${ok}/${tasks.length} in ${dt}s`);
process.exit(ok === tasks.length ? 0 : 1);
