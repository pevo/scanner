// End-to-end verification of the v3.0 features (run against a local HTTP server):
//   0) DB schema versioning (meta.schemaVersion + stamp)
//   1) drive summary popup (total plates + % seen before)
//   2) offline reverse geocoding (lat/lon -> "City, ST")
//   3) plate-crop image storage (put/get round-trip) + CSV import enrichment
//
//   Terminal A:  python -m http.server 8123      (in the Plate folder)
//   Terminal B:  node tools/test-features.js
const { chromium } = require('playwright');
const URL = 'http://localhost:8123/index.html';
const BOSTON = { latitude: 42.3601, longitude: -71.0589, accuracy: 10 };

let passed = 0, failed = 0;
const ok = (name, cond, extra = '') => { (cond ? passed++ : failed++); console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}${extra ? ' — ' + extra : ''}`); };

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ permissions: ['geolocation'], geolocation: BOSTON });
  const page = await context.newPage();
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  page.on('console', m => { if (m.type() === 'error') console.log('[console.error]', m.text().slice(0, 200)); });
  await page.goto(URL);
  await page.waitForFunction(() => !!window.alprDb && !!window.alprDebug, null, { timeout: 30000 });
  await page.evaluate(() => window.alprDb.migrationReady);
  await page.evaluate(() => window.alprDb.clearAll());

  // ---- Feature 0: schema versioning ----
  const schema = await page.evaluate(() => window.alprDb.getMeta('schemaVersion'));
  const appVer = await page.evaluate(() => window.alprDb.getMeta('appVersion'));
  ok('0 schemaVersion stamped == 3', schema === 3, `got ${schema}`);
  ok('0 appVersion stamped', typeof appVer === 'string' && appVer.startsWith('v3'), `got ${appVer}`);

  // ---- Feature 2: offline reverse geocode ----
  await page.evaluate(() => window.alprDebug.loadGeo());
  const boston = await page.evaluate(() => window.alprDebug.reverseGeocode(42.3601, -71.0589));
  const sf = await page.evaluate(() => window.alprDebug.reverseGeocode(37.7749, -122.4194));
  const noLoc = await page.evaluate(() => window.alprDebug.reverseGeocode(null, null));
  ok('2 Boston -> Boston, MA', boston === 'Boston, MA', `got ${boston}`);
  ok('2 SF -> San Francisco, CA', sf === 'San Francisco, CA', `got ${sf}`);
  ok('2 null coords -> null', noLoc === null, `got ${noLoc}`);

  // ---- Feature 3: image store round-trip ----
  const imgResult = await page.evaluate(async () => {
    const id = await window.alprDb.addSighting({ plate: 'IMG001', ts: Date.now(), lat: null, lon: null, accuracy: null, color: 'red', locale: null });
    const c = document.createElement('canvas'); c.width = 60; c.height = 30;
    const cx = c.getContext('2d'); cx.fillStyle = '#c00'; cx.fillRect(0, 0, 60, 30);
    const blob = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.7));
    await window.alprDb.putImage(id, blob);
    const got = await window.alprDb.getImage(id);
    return { id, isBlob: got instanceof Blob, size: got ? got.size : 0, type: got ? got.type : '' };
  });
  ok('3 image stored & retrieved as Blob', imgResult.isBlob && imgResult.size > 0, `size ${imgResult.size} type ${imgResult.type}`);
  const imgCleared = await page.evaluate(async (id) => {
    await window.alprDb.clearAll();
    return await window.alprDb.getImage(id);
  }, imgResult.id);
  ok('3 clearAll removes images', imgCleared === undefined, `got ${imgCleared}`);

  // ---- Feature 3b: CSV import skips '#' marker AND enriches missing locale offline ----
  const csv = '# alpr-export schema=2 app=v2.10\n' +
    'plate,timestamp,iso_date,lat,lon,accuracy_m,color,note\n' +
    'CSV123,1700000000000,2023-11-14T22:13:20.000Z,42.3601,-71.0589,10,blue,imported\n';
  await page.setInputFiles('#importFile', { name: 'old.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
  await page.waitForFunction(() => document.getElementById('toasts').innerText.includes('added') ||
                                   document.getElementById('toasts').innerText.includes('failed'), null, { timeout: 15000 });
  const importToast = await page.evaluate(() => document.getElementById('toasts').innerText);
  const imported = await page.evaluate(() => window.alprDb.getByPlate('CSV123'));
  ok('3b CSV import added the row (marker line skipped)', imported.length === 1, importToast.replace(/\n/g, ' ').slice(0, 80));
  ok('3b CSV import enriched missing locale offline', imported[0] && imported[0].locale === 'Boston, MA', `got ${imported[0] && imported[0].locale}`);

  // ---- Feature 1: drive summary popup ----
  const summary = await page.evaluate(() => {
    window.alprDebug.preDrivePlates = new Set(['AAA111', 'BBB222']);  // known before the drive
    window.alprDebug.drivePlates.clear();
    ['AAA111', 'BBB222', 'CCC333', 'DDD444'].forEach(p => window.alprDebug.drivePlates.add(p)); // 4 seen, 2 known
    window.alprDebug.showDriveSummary();
    const open = document.getElementById('summaryBackdrop').classList.contains('open');
    const text = document.getElementById('summaryCard').innerText;
    return { open, text };
  });
  ok('1 summary popup opens on stop', summary.open === true);
  ok('1 summary shows total plates (4)', /\b4\b/.test(summary.text), summary.text.replace(/\n/g, ' '));
  ok('1 summary shows % seen before (50%)', summary.text.includes('50%'), summary.text.replace(/\n/g, ' '));

  await page.evaluate(() => window.alprDb.clearAll());
  await browser.close();
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
