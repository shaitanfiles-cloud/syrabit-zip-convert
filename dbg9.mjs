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
const page = await browser.newPage();
const cons=[]; const errs=[];
page.on('console', m => cons.push('['+m.type()+'] '+m.text()));
page.on('pageerror', e => errs.push(e.message+' STACK:'+(e.stack||'').slice(0,2000)));
try { await page.goto(URL,{waitUntil:'networkidle0',timeout:30000}); } catch(e){console.log('NAV:',e.message);}
await new Promise(r=>setTimeout(r,5000));
const r = await page.evaluate(()=>({
  hasErrBox: document.body.innerText.includes('Something went wrong'),
  lastErr: window.__LAST_RENDER_ERROR__ || null,
  hydrated: window.__SYRABIT_HYDRATED__ === true,
  preloadKeys: Object.keys(window.__CHAPTER_PRELOAD__ || {}),
}));
console.log(JSON.stringify(r,null,2));
console.log('--- console (' + cons.length + ') ---');
cons.forEach(c=>console.log(c.slice(0,2000)));
console.log('--- pageerrors ---');
errs.forEach(e=>console.log(e.slice(0,2500)));
await browser.close();
