const { chromium } = require('playwright');

const ACCEL = process.argv[2] || 'wasm';

(async () => {
  const browser = await chromium.launch({
    args: ACCEL === 'webgpu'
      ? ['--enable-unsafe-webgpu', '--enable-features=Vulkan', '--use-webgpu-adapter=swiftshader']
      : [],
  });
  const page = await browser.newPage();
  console.log('JSPI available:', await (await browser.newPage()).evaluate(() => 'Suspending' in WebAssembly));
  page.on('console', m => console.log('[console]', m.type(), m.text()));
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  page.on('requestfailed', r => console.log('[reqfail]', r.url(), r.failure()?.errorText));
  page.on('response', r => { if (r.status() >= 400) console.log('[http]', r.status(), r.url()); });
  const poll = setInterval(async () => {
    try {
      const ms = await page.textContent('#modelStatus');
      const rs = await page.textContent('#runStatus');
      console.log('[poll] model:', ms, '| run:', rs);
    } catch {}
  }, 10000);

  await page.goto('http://localhost:8123/alpr-demo.html');

  await page.selectOption('#accel', ACCEL);

  // load model (default path, fetched from server)
  await page.click('#loadBtn');
  await page.waitForFunction(() => {
    const s = document.getElementById('modelStatus');
    return s.classList.contains('ok') || s.classList.contains('err');
  }, null, { timeout: 180000 });
  console.log('MODEL STATUS:', await page.textContent('#modelStatus'));

  const fs = require('fs');
  const path = require('path');
  const dir = path.join(__dirname, '..', 'test_images');
  for (const img of fs.readdirSync(dir).sort()) {
    await page.setInputFiles('#imageFile', path.join(dir, img));
    await page.waitForFunction(() => document.getElementById('runStatus').textContent.includes('Image loaded'));
    await page.click('#runBtn');
    await page.waitForFunction(() => {
      const s = document.getElementById('runStatus');
      return s.classList.contains('ok') || s.classList.contains('err');
    }, null, { timeout: 180000 });
    const logText = await page.textContent('#log');
    const ocrLine = (logText.match(/^OCR:.*$/gm) || ['OCR: (none)']).pop();
    console.log(`\n${img}: ${await page.textContent('#detCount')} | ${await page.textContent('#runStatus')}`);
    console.log('  ' + ocrLine);
  }

  clearInterval(poll);
  await page.screenshot({ path: 'alpr-result.png', fullPage: true });
  await browser.close();
})().catch(e => { console.error('FAILED:', e); process.exit(1); });
