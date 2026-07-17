const { chromium } = require('playwright');
const path = require('path');

const Y4M = path.join(__dirname, 'fakecam.y4m');
const URL = 'http://localhost:8123/index.html';
const GEO = { latitude: 52.37017, longitude: 4.89998, accuracy: 12 };

async function newPage(context) {
  const page = await context.newPage();
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  page.on('console', m => { if (m.type() === 'error' && !/INFO:|WARNING:/.test(m.text())) console.log('[console.error]', m.text().slice(0, 200)); });
  await page.goto(URL);
  await page.waitForFunction(() => !!window.alprDb, null, { timeout: 30000 });
  return page;
}

const start = page => page.click('#startBtn');
const waitScanning = page =>
  page.waitForFunction(() => document.getElementById('status').textContent.includes('Scanning'), null, { timeout: 120000 });
const dbRows = page => page.evaluate(() => window.alprDb.getRecent(100));
const toastText = page => page.evaluate(() => document.getElementById('toasts').innerText);
async function waitRows(page, n, timeoutMs = 120000) {
  const t0 = Date.now();
  for (;;) {
    const rows = await dbRows(page);
    if (rows.length >= n) return rows;
    if (Date.now() - t0 > timeoutMs) throw new Error(`timeout waiting for ${n} rows (have ${rows.length})`);
    await page.waitForTimeout(300);
  }
}
async function waitToast(page, re, timeoutMs = 120000) {
  const t0 = Date.now();
  for (;;) {
    const t = await toastText(page);
    if (re.test(t)) return t;
    if (Date.now() - t0 > timeoutMs) throw new Error(`timeout waiting for toast ${re}`);
    await page.waitForTimeout(300);
  }
}

(async () => {
  const browser = await chromium.launch({
    args: [
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-video-capture=${Y4M}`,
    ],
  });
  const context = await browser.newContext({ permissions: ['camera', 'geolocation'], geolocation: GEO });
  let failures = 0;
  const check = (name, cond, detail = '') => {
    console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}${detail ? '  |  ' + detail : ''}`);
    if (!cond) failures++;
  };

  // ---------- Phase A: fresh DB -> new plate logged with GPS ----------
  let page = await newPage(context);
  await page.evaluate(() => window.alprDb.clearAll());
  await start(page);
  await waitScanning(page);
  let rows = await waitRows(page, 1);
  let t = await toastText(page);
  check('A: exactly one row inserted', rows.length === 1, `rows=${rows.length}`);
  check('A: plate is AAA000', rows[0]?.plate === 'AAA000', `plate=${rows[0]?.plate}`);
  check('A: GPS stored', Math.abs(rows[0]?.lat - GEO.latitude) < 1e-4 && Math.abs(rows[0]?.lon - GEO.longitude) < 1e-4,
        `lat=${rows[0]?.lat} lon=${rows[0]?.lon}`);
  check('A: "new plate" toast shown', /new plate logged/.test(t), JSON.stringify(t.slice(0, 80)));
  const palette = ['white', 'silver', 'gray', 'black', 'red', 'orange', 'brown', 'yellow', 'green', 'blue', 'purple'];
  check('A: car color estimated', palette.includes(rows[0]?.color), `color=${rows[0]?.color}`);
  // keep scanning a few more seconds: no duplicate rows may appear (dedup 60 min)
  await page.waitForTimeout(4000);
  rows = await dbRows(page);
  check('A: still one row after continued scanning', rows.length === 1, `rows=${rows.length}`);
  await page.close();

  // ---------- Phase B: old history -> seen-before toast + re-logged ----------
  page = await newPage(context);
  await page.evaluate(() => window.alprDb.clearAll());
  await page.evaluate(() => {
    const now = Date.now(), H = 3600 * 1000;
    return Promise.all([
      window.alprDb.addSighting({ plate: 'AAA000', ts: now - 2 * H, lat: 51.5, lon: -0.12, accuracy: 10 }),
      window.alprDb.addSighting({ plate: 'AAA000', ts: now - 26 * H, lat: 48.85, lon: 2.35, accuracy: 20 }),
      window.alprDb.addSighting({ plate: 'AAA000', ts: now - 50 * H, lat: 40.71, lon: -74.0, accuracy: 30 }),
    ]);
  });
  await start(page);
  await waitScanning(page);
  rows = await waitRows(page, 4);
  t = await toastText(page);
  check('B: re-logged after window expired (4 rows)', rows.length === 4, `rows=${rows.length}`);
  check('B: seen-before toast with count', /seen 3× before/.test(t), JSON.stringify(t.slice(0, 120)));
  check('B: toast lists 3 prior locations', (t.match(/51\.5|48\.85|40\.71/g) || []).length === 3, '');
  await page.close();

  // ---------- Phase C: recent sighting within window -> dedup skip ----------
  page = await newPage(context);
  await page.evaluate(() => window.alprDb.clearAll());
  await page.evaluate(() =>
    window.alprDb.addSighting({ plate: 'AAA000', ts: Date.now() - 5 * 60 * 1000, lat: 51.5, lon: -0.12, accuracy: 10, color: 'blue' }));
  await page.evaluate(() => window.alprDb.setNote('AAA000', 'my neighbors car'));
  await start(page);
  await waitScanning(page);
  t = await waitToast(page, /seen/);
  await page.waitForTimeout(3000);
  rows = await dbRows(page);
  check('C: duplicate NOT logged (still 1 row)', rows.length === 1, `rows=${rows.length}`);
  check('C: toast says not re-logged', /not re-logged/.test(t), JSON.stringify(t.slice(0, 140)));
  check('C: toast shows the note', /my neighbors car/.test(t), '');
  check('C: toast shows prior color', /blue/.test(t), '');

  // ---------- Phase D: CSV import (merge + duplicate skip + note) ----------
  await page.click('#startBtn');   // stop scanning — D tests import logic only
  await page.waitForFunction(() => document.getElementById('status').textContent.includes('Stopped'));
  await page.waitForTimeout(1500); // let any in-flight frame finish
  await page.evaluate(() => window.alprDb.clearAll());
  const seedTs = Date.now() - 3600_000;
  await page.evaluate(ts =>
    window.alprDb.addSighting({ plate: 'AAA000', ts, lat: 51.5, lon: -0.12, accuracy: 10, color: 'blue' }), seedTs);
  const csv = 'plate,timestamp,iso_date,lat,lon,accuracy_m,color,note\n' +
    `AAA000,${seedTs},${new Date(seedTs).toISOString()},51.5,-0.12,10,blue,\n` +               // duplicate
    `XYZ789,${seedTs - 1000},${new Date(seedTs - 1000).toISOString()},48.85,2.35,20,red,"the, ""quoted"" car"\n`;
  await page.setInputFiles('#importFile', { name: 'import.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  t = await waitToast(page, /Import/, 30000);
  rows = await dbRows(page);
  const note = await page.evaluate(() => window.alprDb.getNote('XYZ789'));
  check('D: import added 1, skipped 1 dup (2 rows total)', rows.length === 2, `rows=${rows.length}`);
  check('D: import toast reports counts', /1 added, 1 duplicates skipped/.test(t), JSON.stringify(t.slice(0, 120)));
  check('D: imported row fields', rows.some(r => r.plate === 'XYZ789' && r.color === 'red' && r.lat === 48.85), '');
  check('D: quoted note imported', note === 'the, "quoted" car', `note=${JSON.stringify(note)}`);
  // re-import same file -> everything skipped
  await page.setInputFiles('#importFile', { name: 'import.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  await waitToast(page, /0 added/, 30000);
  rows = await dbRows(page);
  check('D: re-import adds nothing', rows.length === 2, `rows=${rows.length}`);

  await page.screenshot({ path: 'scanner-result.png' });
  await browser.close();
  console.log(failures ? `\n${failures} FAILURE(S)` : '\nALL PASS');
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error('FAILED:', e); process.exit(1); });
