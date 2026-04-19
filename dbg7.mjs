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
// Wrap console BEFORE page loads
await page.evaluateOnNewDocument(() => {
  window.__caught = [];
  const origErr = console.error;
  console.error = function(...args) {
    try { window.__caught.push({type:'console.error', args: args.map(a => {try{return typeof a==='object'?JSON.stringify(a).slice(0,2000):String(a).slice(0,2000);}catch{return String(a).slice(0,500);}})}); } catch {}
    return origErr.apply(this, args);
  };
  window.addEventListener('error', e => {
    window.__caught.push({type:'error-event', message: e.message, filename: e.filename, lineno: e.lineno, colno: e.colno, stack: (e.error && e.error.stack || '').slice(0,2000)});
  });
  window.addEventListener('unhandledrejection', e => {
    window.__caught.push({type:'rejection', reason: String(e.reason).slice(0,500)});
  });
});
const errs=[]; page.on('pageerror', e => errs.push(e.message+'\n'+(e.stack||'').slice(0,1500)));
try { await page.goto(URL,{waitUntil:'networkidle0',timeout:30000}); } catch(e){console.log('NAV:',e.message);}
await new Promise(r=>setTimeout(r,4500));
const caught = await page.evaluate(()=>window.__caught || []);
console.log('--- IN-PAGE CAUGHT ('+caught.length+') ---');
caught.forEach((c,i)=>console.log(i,JSON.stringify(c).slice(0,3000)));
console.log('--- PAGEERRORS ---');
errs.forEach(e=>console.log(e));
await browser.close();
