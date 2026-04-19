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
const p = await browser.newPage();
p.on('console', m => {
  const t = m.text();
  if (t.includes('hydrat') || t.includes('mismatch') || t.includes('Warning') || t.includes('Error') || t.includes('expected') || t.includes('server')) {
    console.log('[console.'+m.type()+']', t.slice(0,3000));
  }
});
p.on('pageerror', e => console.log('[pageerror]', String(e).slice(0,3000)));
await p.goto(URL,{waitUntil:'networkidle0',timeout:40000});
await new Promise(r=>setTimeout(r,5000));
await browser.close();
