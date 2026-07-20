// Verifies the v3.1 performance/zoom changes:
//   - cross-origin isolation (COOP/COEP) -> crossOriginIsolated === true
//     (this is what unlocks multi-threaded wasm on the phone)
//   - digital center-crop zoom actually crops the working frame, and the
//     full pipeline still logs a plate while zoomed
//   - frame-skip setting is honoured (no crash; still logs)
//
// Serves the folder from a tiny Node server that sends the SAME COOP/COEP
// headers as serve_https.py, and feeds a fake camera (fakecam.y4m).
//   node tools/test-perf-zoom.js
const http = require('http');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const ROOT = path.join(__dirname, '..');
const Y4M = path.join(__dirname, 'fakecam.y4m');
const PORT = 8124;
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.wasm': 'application/wasm', '.json': 'application/json', '.webmanifest': 'application/manifest+json',
  '.tflite': 'application/octet-stream', '.png': 'image/png' };

const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
  fs.readFile(p, (err, buf) => {
    if (err) { res.writeHead(404); res.end('nf'); return; }
    res.writeHead(200, {
      'Content-Type': MIME[path.extname(p)] || 'application/octet-stream',
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
      'Cross-Origin-Resource-Policy': 'same-origin',
    });
    res.end(buf);
  });
});

let passed = 0, failed = 0;
const ok = (n, c, x = '') => { (c ? passed++ : failed++); console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${x ? ' — ' + x : ''}`); };

(async () => {
  await new Promise(r => server.listen(PORT, r));
  const browser = await chromium.launch({
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-video-capture=${Y4M}`],
  });
  const context = await browser.newContext({ permissions: ['camera', 'geolocation'], geolocation: { latitude: 42.36, longitude: -71.06, accuracy: 10 } });
  const page = await context.newPage();
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  page.on('console', m => { if (m.type() === 'error') console.log('[console.error]', m.text().slice(0, 200)); });
  // start zoomed at 1.5x so the crop path is exercised from the first frame
  await page.addInitScript(() => localStorage.setItem('alpr-scanner-settings', JSON.stringify({ zoom: 1.5, frameEvery: 2, confirm: 2 })));
  await page.goto(`http://localhost:${PORT}/index.html`);
  await page.waitForFunction(() => !!window.alprDb && !!window.alprDebug, null, { timeout: 30000 });

  // ---- cross-origin isolation ----
  const iso = await page.evaluate(() => self.crossOriginIsolated);
  const cores = await page.evaluate(() => navigator.hardwareConcurrency);
  ok('isolation: crossOriginIsolated === true (SharedArrayBuffer available)', iso === true, `cores=${cores}`);
  ok('isolation: SharedArrayBuffer defined', await page.evaluate(() => typeof SharedArrayBuffer !== 'undefined'));

  // ---- zoom + pipeline ----
  await page.evaluate(() => window.alprDb.clearAll());
  await page.click('#startBtn');
  await page.waitForFunction(() => document.getElementById('status').textContent.includes('Scanning'), null, { timeout: 120000 });

  // wait for a plate to be logged while zoomed
  const t0 = Date.now();
  let rows = [];
  while (Date.now() - t0 < 120000) {
    rows = await page.evaluate(() => window.alprDb.getRecent(10));
    if (rows.length >= 1) break;
    await page.waitForTimeout(300);
  }
  const crop = await page.evaluate(() => window.alprDebug.lastCrop);
  ok('zoom: working frame is center-cropped (~1.5x)', crop.cropW > 0 && crop.cropW < crop.vW &&
     Math.abs(crop.cropW - crop.vW / 1.5) <= 2, `cropW=${crop.cropW} vW=${crop.vW}`);
  ok('zoom: crop is centered', Math.abs(crop.cx0 - (crop.vW - crop.cropW) / 2) <= 1, `cx0=${crop.cx0}`);
  ok('zoom: plate still detected & logged at 1.5x', rows.length >= 1 && rows[0].plate === 'AAA000', `rows=${rows.length} plate=${rows[0]?.plate}`);

  // ---- setZoom clamps ----
  const clamp = await page.evaluate(() => { window.alprDebug.setZoom(99); const hi = window.alprDebug.settings.zoom; window.alprDebug.setZoom(0.1); const lo = window.alprDebug.settings.zoom; return { hi, lo }; });
  ok('zoom: setZoom clamps to [1,8]', clamp.hi === 8 && clamp.lo === 1, JSON.stringify(clamp));

  await page.evaluate(() => { window.alprDebug.setZoom(1); return window.alprDb.clearAll(); });
  await browser.close();
  await new Promise(r => server.close(r));
  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
