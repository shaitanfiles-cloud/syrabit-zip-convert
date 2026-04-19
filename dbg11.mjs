import fs from 'fs';
import puppeteer from '/home/runner/workspace/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js';
const env = { ...process.env };
try {
  const mesa = fs.readdirSync('/nix/store').filter(n => /^[a-z0-9]+-mesa-\d/.test(n))
    .map(n => '/nix/store/'+n+'/lib').filter(p => { try { return fs.existsSync(p+'/libgbm.so.1'); } catch { return false; } });
  if (mesa.length) env.LD_LIBRARY_PATH = [env.LD_LIBRARY_PATH, ...mesa].filter(Boolean).join(':');
} catch {}
process.env.LD_LIBRARY_PATH = env.LD_LIBRARY_PATH;
const URL = process.argv[2];
const browser = await puppeteer.launch({headless:'new',args:['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage'],env});
// SSR-only capture: disable JS
const p1 = await browser.newPage();
await p1.setJavaScriptEnabled(false);
await p1.goto(URL,{waitUntil:'load',timeout:30000});
const ssrRoot = await p1.evaluate(()=>document.getElementById('root')?.innerHTML || '');
await p1.close();
// Client capture: with JS, wait for crash, capture #root + a snapshot of CHAPTER article specifically
const p2 = await browser.newPage();
await p2.goto(URL,{waitUntil:'networkidle0',timeout:30000});
await new Promise(r=>setTimeout(r,5000));
// Get React's own client tree by reading what would render — actually we just diff what's there now (ErrorBoundary)
// Better: take the SSR root and diff against pre-error client. But pre-error is ErrorBoundary. 
// Trick: the prerender baked in HTML; let's just do structural diff on outer tags.
const clientRoot = await p2.evaluate(()=>document.getElementById('root')?.innerHTML || '');
console.log('SSR root len:', ssrRoot.length);
console.log('Client root len:', clientRoot.length);
// Save both and run a quick diff
fs.writeFileSync('/tmp/ssr.html', ssrRoot);
fs.writeFileSync('/tmp/client.html', clientRoot);
console.log('SSR first 300:', ssrRoot.slice(0,300));
console.log('---');
console.log('Client first 300:', clientRoot.slice(0,300));
await browser.close();
