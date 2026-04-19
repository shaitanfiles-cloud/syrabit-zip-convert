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
page.on('pageerror', e => errs.push(e.message));
try { await page.goto(URL,{waitUntil:'networkidle0',timeout:30000}); } catch(e){console.log('NAV:',e.message);}
await new Promise(r=>setTimeout(r,5000));
const r = await page.evaluate(()=>({
  bodyText: document.body.innerText.slice(0,400).replace(/\s+/g,' '),
  hasErrBox: document.body.innerText.includes('Something went wrong'),
  rootChildCount: document.getElementById('root')?.children?.length || 0,
  rootHTMLPreview: document.getElementById('root')?.innerHTML?.slice(0,300) || '',
  chapterH1: document.querySelector('.chapter-textbook h1')?.innerText || null,
  hydrated: window.__SYRABIT_HYDRATED__ === true,
}));
console.log(JSON.stringify(r,null,2));
console.log('--- console (' + cons.length + ') ---');
cons.forEach(c=>console.log(c.slice(0,1200)));
console.log('--- pageerrors ---');
errs.forEach(e=>console.log(e.slice(0,1500)));
await browser.close();
