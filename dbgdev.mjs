import puppeteer from 'puppeteer';
const url = process.argv[2];
const browser = await puppeteer.launch({
  headless: 'new',
  args:['--no-sandbox','--disable-setuid-sandbox','--disable-dev-shm-usage'],
});
const page = await browser.newPage();
const errs=[], warns=[];
page.on('console', m => {
  const t=m.type(); const txt=m.text();
  if (t==='error' || t==='warning') (t==='error'?errs:warns).push(txt);
});
page.on('pageerror', e => errs.push('PAGEERROR: '+e.message+'\n'+(e.stack||'').split('\n').slice(0,4).join('\n')));
try { await page.goto(url, {waitUntil:'networkidle0', timeout:25000}); }
catch(e){ console.log('NAV ERR',e.message); }
await new Promise(r=>setTimeout(r,1500));
console.log('=== ERRORS ('+errs.length+') ===');
errs.forEach(e=>console.log('---\n'+e));
console.log('\n=== WARNINGS ('+warns.length+') ===');
warns.forEach(w=>console.log('---\n'+w.slice(0,1500)));
await browser.close();
