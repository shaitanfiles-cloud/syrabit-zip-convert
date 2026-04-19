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
const errs=[]; page.on('pageerror', e => errs.push(e.message));
try { await page.goto(URL,{waitUntil:'networkidle0',timeout:30000}); } catch(e){console.log('NAV:',e.message);}
await new Promise(r=>setTimeout(r,4500));
const r = await page.evaluate(()=>{
  const errBox = document.body.innerText.includes('Something went wrong');
  const h1 = document.querySelector('h1.text-xl, h1.text-2xl, h1.text-3xl, .chapter-textbook h1, article h1');
  const title = document.title;
  const articleLen = (document.querySelector('article')?.innerText||'').length;
  return {errBox, h1: h1?.innerText, title, articleLen};
});
console.log(JSON.stringify({url: URL.split('?')[0], pageErrs: errs.length, ...r}));
await browser.close();
