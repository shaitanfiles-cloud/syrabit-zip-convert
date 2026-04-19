import puppeteer from '/home/runner/workspace/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js';
const env = { ...process.env };
env.LD_LIBRARY_PATH = ['/nix/store/8rpwarjmffnrccc8ddx46xmy7998xzp6-mesa-21.2.6/lib', env.LD_LIBRARY_PATH].filter(Boolean).join(':');
const URL = process.argv[2];
console.log('LOAD:', URL);
const browser = await puppeteer.launch({
  headless: 'new',
  args:['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage'],
  env,
});
const page = await browser.newPage();
const errs=[], cons=[];
page.on('console', m => cons.push('['+m.type()+'] '+m.text()));
page.on('pageerror', e => errs.push('PAGEERROR: '+e.message));
try { await page.goto(URL,{waitUntil:'networkidle0',timeout:30000}); } catch(e){console.log('NAV:',e.message);}
await new Promise(r=>setTimeout(r,5000));
console.log('PAGEERRORS('+errs.length+'):'); errs.forEach(e=>console.log(e));
console.log('---ALL ERR/WARN CONSOLE---');
cons.filter(m=>m.startsWith('[error]')||m.startsWith('[warning]')).forEach(m=>console.log(m.slice(0,4000)));
const txt = await page.evaluate(()=>document.body.innerText.slice(0,200));
console.log('BODY:',txt);
await browser.close();
