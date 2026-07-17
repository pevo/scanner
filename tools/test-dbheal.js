const { chromium } = require('playwright');

const ORIGIN = 'http://localhost:8123';
let failures = 0;
const check = (name, cond, detail = '') => {
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}${detail ? '  |  ' + detail : ''}`);
  if (!cond) failures++;
};

// Create the 'alpr' DB in a given (possibly broken) state, from a same-origin page.
function seedDb(page, version, withPlatesStore) {
  return page.evaluate(([version, withPlatesStore]) => new Promise((res, rej) => {
    const del = indexedDB.deleteDatabase('alpr');
    del.onsuccess = del.onerror = () => {
      const req = indexedDB.open('alpr', version);
      req.onupgradeneeded = () => {
        const db = req.result;
        const st = db.createObjectStore('sightings', { keyPath: 'id', autoIncrement: true });
        st.createIndex('plate', 'plate');
        st.createIndex('ts', 'ts');
        if (withPlatesStore) db.createObjectStore('plates', { keyPath: 'plate' });
      };
      req.onsuccess = () => {
        const db = req.result;
        const t = db.transaction('sightings', 'readwrite');
        t.objectStore('sightings').add({ plate: 'OLD111', ts: Date.now() - 1000, lat: null, lon: null, accuracy: null });
        t.oncomplete = () => { db.close(); res('seeded v' + db.version); };
        t.onerror = () => rej(t.error);
      };
      req.onerror = () => rej(req.error);
    };
  }), [version, withPlatesStore]);
}

async function runScenario(browser, name, version, withPlatesStore) {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  await page.goto(ORIGIN + '/README.md');           // same-origin page to seed from
  console.log(' ', await seedDb(page, version, withPlatesStore));
  await page.goto(ORIGIN + '/index.html');
  await page.waitForFunction(() => !!window.alprDb, null, { timeout: 30000 });
  await page.click('#listBtn');
  await page.waitForFunction(() =>
    !document.getElementById('listWrap').textContent.includes('Loading'), null, { timeout: 15000 });
  const wrap = await page.textContent('#listWrap');
  check(`${name}: list renders (no hang)`, /OLD111|No sightings/.test(wrap), JSON.stringify(wrap.slice(0, 90)));
  check(`${name}: old row preserved`, wrap.includes('OLD111'), '');
  const note = await page.evaluate(() =>
    window.alprDb.setNote('OLD111', 'healed').then(() => window.alprDb.getNote('OLD111')));
  check(`${name}: notes store usable after heal`, note === 'healed', `note=${note}`);
  await context.close();
}

(async () => {
  const browser = await chromium.launch();
  await runScenario(browser, 'S1 v1-legacy-db', 1, false);
  await runScenario(browser, 'S2 half-migrated (v3, no plates store)', 3, false);
  await runScenario(browser, 'S3 healthy v2', 2, true);
  await browser.close();
  console.log(failures ? `\n${failures} FAILURE(S)` : '\nALL PASS');
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error('FAILED:', e); process.exit(1); });
