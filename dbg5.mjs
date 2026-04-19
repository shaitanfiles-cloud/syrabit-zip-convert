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
console.log('LOAD:', URL);
const browser = await puppeteer.launch({headless:'new',args:['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage'],env});
const page = await browser.newPage();
const cons=[]; const errs=[];
page.on('console', m => cons.push('['+m.type()+'] '+m.text()));
page.on('pageerror', e => errs.push('PAGEERROR: '+e.message));
try { await page.goto(URL,{waitUntil:'networkidle0',timeout:30000}); } catch(e){console.log('NAV:',e.message);}
await new Promise(r=>setTimeout(r,4500));
console.log('--- ALL CONSOLE ('+cons.length+') ---');
cons.forEach(m=>console.log(m.slice(0,4000)));
console.log('--- PAGEERRORS ---');
errs.forEach(e=>console.log(e));
await browser.close();
