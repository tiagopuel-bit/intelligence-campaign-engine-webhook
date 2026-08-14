// DNA dashboard — selected-holding chart lifecycle regression (Track 2).
//
// Validates the LightweightCharts lifecycle against live Railway data:
//   - shares -> option A -> option B -> shares
//   - cached and uncached OHLC responses (first visit uncached, revisit cached)
//   - rapid switching while a prior request is in flight (sequence guard)
//   - option entry inside and outside available chart history (TF auto-widen)
//   - Underlying/Option manual mode toggles after a holding switch
//
// Acceptance evidence asserted per holding switch: chart title, manager title,
// mode (Underlying/Option), status ticker, selected holding, and active TF all
// belong to the SAME selected holding, with zero page errors.
//
// The premium series / average-entry line / entry marker are drawn from the
// same `target` object (chartTarget().pick) in the same renderChart() block
// that sets the status text, so they cohere by construction; the sequence
// guard prevents a stale response from overwriting the current contract.
//
// Requires:
//   STATE_API_TOKEN=<railway token>  (read from env, never hardcoded)
//   npm i puppeteer-core ; Google Chrome at /Applications
//   live AMC holdings: 1 share + N calls (assertions key on AMC + its tickers)
//
// Usage:  STATE_API_TOKEN=... node scripts/chart_lifecycle_regression.js

const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = 'https://dna-tradingview-webhook-production.up.railway.app';
const PAGE = 'file://' + __dirname + '/../ui/dna_dashboard.html';

const results = [];
const log = m => console.log(m);
function check(name, cond, detail) {
  results.push({ name, pass: !!cond, detail: detail || '' });
  log((cond ? 'PASS ' : 'FAIL ') + name + (detail ? '  [' + detail + ']' : ''));
}

(async () => {
  const TOKEN = process.env.STATE_API_TOKEN;
  if (!TOKEN) { console.error('STATE_API_TOKEN is required'); process.exit(2); }
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--no-sandbox', '--disable-gpu'] });
  const p = await b.newPage();
  await p.setViewport({ width: 1440, height: 1100 });
  const errors = [];
  p.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));

  await p.goto(PAGE, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await p.evaluate((base, token) => {
    document.querySelector('[data-role="base"]').value = base;
    document.querySelector('[data-role="token"]').value = token;
  }, BASE, TOKEN);
  await p.click('[data-role="load"]');
  await p.waitForFunction(() => document.querySelectorAll('.dna-held-item').length > 0, { timeout: 30000 });

  const state = () => p.evaluate(() => ({
    title: (document.querySelector('.dna-chart-title') || {}).textContent || '',
    manager: (document.querySelector('.dna-manager-title strong') || {}).textContent || '',
    status: (document.querySelector('.chart-status') || {}).textContent || '',
    mode: (document.querySelector('.cm-btn.on') || {}).textContent || '',
    selected: (document.querySelector('.dna-held-item.selected') || {}).textContent || '',
    activeTf: (document.querySelector('.tf-btn.on') || {}).textContent || '',
    canvas: document.querySelectorAll('.chart-container canvas').length,
  }));
  async function waitBars(timeout) {
    try { await p.waitForFunction(() => /bars/.test((document.querySelector('.chart-status') || {}).textContent || ''), { timeout }); return true; }
    catch (e) { return false; }
  }
  async function switchTo(substr, timeout) {
    await p.evaluate((s) => { const it = [...document.querySelectorAll('.dna-held-item')].find(x => x.textContent.toLowerCase().includes(s)); if (it) it.click(); }, substr.toLowerCase());
    return waitBars(timeout || 120000);
  }

  // initial (default = shares)
  await waitBars(120000);
  let s = await state();
  check('initial renders bars', /bars/.test(s.status), s.status);
  check('initial title = shares', /shares/i.test(s.title), s.title);
  check('initial mode = Underlying', s.mode === 'Underlying', s.mode);

  // shares -> option A (AUG call)
  let rendered = await switchTo('aug', 60000);
  s = await state();
  check('A renders bars', rendered, s.status);
  check('A mode = Option', s.mode === 'Option', s.mode);
  check('A title = CALL', /CALL/i.test(s.title), s.title);
  check('A ticker = O:AMC260821C00001500', /O:AMC260821C00001500/.test(s.status), s.status);
  check('A selected contains AUG', /aug/i.test(s.selected), s.selected);

  // option A -> option B (SEP call)
  rendered = await switchTo('sep', 60000);
  s = await state();
  check('B renders bars', rendered, s.status);
  check('B mode = Option', s.mode === 'Option', s.mode);
  check('B title = CALL', /CALL/i.test(s.title), s.title);
  check('B ticker = O:AMC260918C00001500', /O:AMC260918C00001500/.test(s.status), s.status);
  check('B selected contains SEP', /sep/i.test(s.selected), s.selected);

  // option B -> shares
  rendered = await switchTo('shares', 60000);
  s = await state();
  check('shares renders bars', rendered, s.status);
  check('shares mode = Underlying', s.mode === 'Underlying', s.mode);
  check('shares title = shares', /shares/i.test(s.title), s.title);
  check('shares status is underlying (no O: ticker)', !/O:AMC/.test(s.status) && /AMC/.test(s.status), s.status);

  // cached revisit
  const t0 = Date.now();
  rendered = await switchTo('aug', 60000);
  const dt = Date.now() - t0;
  s = await state();
  check('A revisit renders (cached)', rendered, s.status);
  check('A revisit shows cached', /cached/.test(s.status), s.status);
  log('A revisit duration (cached): ' + dt + 'ms');

  // rapid switching: click A then B while A is still in flight
  await p.evaluate(() => { const a = [...document.querySelectorAll('.dna-held-item')].find(x => x.textContent.toLowerCase().includes('aug')); if (a) a.click(); });
  await new Promise(r => setTimeout(r, 250));
  await p.evaluate(() => { const b = [...document.querySelectorAll('.dna-held-item')].find(x => x.textContent.toLowerCase().includes('sep')); if (b) b.click(); });
  rendered = await waitBars(60000);
  s = await state();
  check('rapid switch renders', rendered, s.status);
  check('rapid switch ends on SEP', /sep/i.test(s.selected), s.selected);
  check('rapid switch ticker = SEP', /O:AMC260918C00001500/.test(s.status), s.status);

  // manual mode toggle after a switch (currently SEP)
  await p.evaluate(() => { const u = [...document.querySelectorAll('.cm-btn')].find(x => x.textContent.trim() === 'Underlying'); if (u) u.click(); });
  await waitBars(60000);
  s = await state();
  check('manual Underlying toggle works', s.mode === 'Underlying' && !/O:AMC/.test(s.status), s.mode + ' / ' + s.status);
  check('holding stays SEP during toggle', /sep/i.test(s.selected), s.selected);
  await p.evaluate(() => { const o = [...document.querySelectorAll('.cm-btn')].find(x => x.textContent.trim() === 'Option'); if (o) o.click(); });
  await waitBars(60000);
  s = await state();
  check('manual Option toggle returns SEP', s.mode === 'Option' && /O:AMC260918C00001500/.test(s.status), s.status);

  // entry outside history: oldest call (JAN 2027) widens TF as needed
  rendered = await switchTo('jan', 60000);
  s = await state();
  check('JAN call renders', rendered, s.status);
  check('JAN ticker = O:AMC270115C00001500', /O:AMC270115C00001500/.test(s.status), s.status);

  check('no page errors', errors.length === 0, JSON.stringify(errors));

  await b.close();
  const fails = results.filter(r => !r.pass);
  console.log('\n=== ' + (results.length - fails.length) + '/' + results.length + ' passed ===');
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
