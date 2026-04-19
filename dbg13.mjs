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
// SSR (no JS)
const p1 = await browser.newPage();
await p1.setJavaScriptEnabled(false);
await p1.goto(URL,{waitUntil:'load',timeout:30000});
const ssr = await p1.evaluate(()=>document.getElementById('root')?.innerHTML || '');
await p1.close();
// Client: snapshot DOM right when first reconciliation happens
const p2 = await browser.newPage();
// Inject pre-script that overrides Element.prototype.removeChild & replaceChild to log errors but allow
await p2.evaluateOnNewDocument(() => {
  window.__CLIENT_DOM__ = '';
  const captureOnce = () => {
    if (window.__CLIENT_DOM__) return;
    const r = document.getElementById('root');
    window.__CLIENT_DOM__ = r ? r.innerHTML : '';
  };
  // Capture on the next animation frame after first render
  const orig = window.requestAnimationFrame;
  let frames = 0;
  window.requestAnimationFrame = function(cb) {
    return orig.call(window, function(t) {
      frames++;
      if (frames === 2) captureOnce();
      cb(t);
    });
  };
});
await p2.goto(URL,{waitUntil:'networkidle0',timeout:30000});
await new Promise(r=>setTimeout(r,4000));
const clientFirst = await p2.evaluate(()=>window.__CLIENT_DOM__ || '');
const clientNow = await p2.evaluate(()=>document.getElementById('root')?.innerHTML || '');
console.log('SSR len:', ssr.length);
console.log('Client first len:', clientFirst.length);
console.log('Client now len:', clientNow.length);
fs.writeFileSync('/tmp/ssr.html', ssr);
fs.writeFileSync('/tmp/client_first.html', clientFirst);
fs.writeFileSync('/tmp/client_now.html', clientNow);
// Run a quick textual diff
const ss = ssr.split(/(?=<)/);
const cs = clientFirst.split(/(?=<)/);
const min = Math.min(ss.length, cs.length);
for (let i = 0; i < min; i++) {
  if (ss[i] !== cs[i]) {
    console.log('FIRST DIFF at chunk', i);
    console.log('SSR :', ss.slice(Math.max(0,i-1), i+3).join('').slice(0,400));
    console.log('CLI :', cs.slice(Math.max(0,i-1), i+3).join('').slice(0,400));
    break;
  }
}
console.log('SSR chunks:', ss.length, 'CLI chunks:', cs.length);
await browser.close();
