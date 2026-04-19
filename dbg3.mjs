import puppeteer from '/home/runner/workspace/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js';
const env = { ...process.env };
import fs from 'fs';
try { const mesaLibs=fs.readdirSync('/nix/store').filter(n=>/^[a-z0-9]+-mesa-\d/.test(n)).map(n=>'/nix/store/'+n+'/lib').filter(p=>{try{return fs.existsSync(p+'/libgbm.so.1');}catch{return false;}}); if(mesaLibs.length) env.LD_LIBRARY_PATH=[env.LD_LIBRARY_PATH,...mesaLibs].filter(Boolean).join(':'); } catch{}
process.env.LD_LIBRARY_PATH = env.LD_LIBRARY_PATH;
const URL = process.argv[2];
console.log('LOAD:', URL);
const browser = await puppeteer.launch({
  headless:'new',
  args:['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage'],
  env,
});
const page = await browser.newPage();
// Disable service workers entirely
const cdp = await page.target().createCDPSession();
await cdp.send('ServiceWorker.enable');
await cdp.send('ServiceWorker.setForceUpdateOnPageLoad',{forceUpdateOnPageLoad:true});
await page.setBypassServiceWorker(true).catch(()=>{});
// Block sw.js entirely
await page.setRequestInterception(true);
page.on('request',req=>{
  const u=req.url();
  if (u.endsWith('/sw.js')||u.includes('serviceworker')) return req.abort();
  req.continue();
});
const errs=[]; page.on('pageerror',e=>errs.push(e.message));
try { await page.goto(URL,{waitUntil:'networkidle0',timeout:30000}); } catch(e){console.log('NAV:',e.message);}
await new Promise(r=>setTimeout(r,4000));
console.log('PAGEERRORS('+errs.length+'):'); errs.forEach(e=>console.log(' ',e));
const body = await page.evaluate(()=>document.body.innerText.slice(0,150).replace(/\s+/g,' '));
console.log('BODY:',body);
await browser.close();
