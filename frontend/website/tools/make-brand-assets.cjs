// Regenerates favicon, app icons and the social preview image into src/static.
// Needs Playwright with Chromium available:  npm run assets
const { chromium } = require('playwright');
const { writeFileSync } = require('node:fs');
const { join } = require('node:path');

const out = join(__dirname, '..', 'src', 'static');
const MARK = (stroke, node) => `<path d="M12 2.6c-3.4 4.2-5.7 7-5.7 9.9a5.7 5.7 0 0 0 11.4 0c0-2.9-2.3-5.7-5.7-9.9z" fill="none" stroke="${stroke}" stroke-width="1.5"/><path d="M12 9.6 9.2 14.4M12 9.6l2.8 4.8M9.2 14.4h5.6" stroke="${stroke}" stroke-width="1" opacity=".55"/><circle cx="12" cy="9.6" r="1.7" fill="#D92D20"/><circle cx="9.2" cy="14.4" r="1.3" fill="${node}"/><circle cx="14.8" cy="14.4" r="1.3" fill="${node}"/>`;

// Scalable favicon: follows the browser's light or dark tab strip.
writeFileSync(join(out, 'favicon.svg'),
`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><style>.m{stroke:#0F1A2B}.n{fill:#0F1A2B}@media (prefers-color-scheme:dark){.m{stroke:#F3F6FB}.n{fill:#F3F6FB}}</style><path class="m" d="M12 2.6c-3.4 4.2-5.7 7-5.7 9.9a5.7 5.7 0 0 0 11.4 0c0-2.9-2.3-5.7-5.7-9.9z" fill="none" stroke-width="1.7"/><path class="m" d="M12 9.6 9.2 14.4M12 9.6l2.8 4.8M9.2 14.4h5.6" stroke-width="1.1" opacity=".55"/><circle cx="12" cy="9.6" r="1.9" fill="#D92D20"/><circle class="n" cx="9.2" cy="14.4" r="1.5"/><circle class="n" cx="14.8" cy="14.4" r="1.5"/></svg>\n`);

const tile = (size, pad) => `<!doctype html><html><body style="margin:0;background:#0F1A2B;width:${size}px;height:${size}px;display:grid;place-items:center"><svg width="${size * pad}" height="${size * pad}" viewBox="0 0 24 24">${MARK('#FFFFFF', '#FFFFFF')}</svg></body></html>`;

(async () => {
  const browser = await chromium.launch();
  const shot = async (html, w, h, file) => {
    const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    await page.setContent(html);
    await page.waitForTimeout(150);
    const buf = await page.screenshot({ type: 'png' });
    await page.close();
    if (file) writeFileSync(join(out, file), buf);
    return buf;
  };

  await shot(tile(180, 0.7), 180, 180, 'apple-touch-icon.png');
  await shot(tile(192, 0.62), 192, 192, 'icon-192.png');
  await shot(tile(512, 0.62), 512, 512, 'icon-512.png');
  const p32 = await shot(tile(32, 0.82), 32, 32);

  // favicon.ico: one 32x32 PNG image inside an ICO container.
  const head = Buffer.alloc(22);
  head.writeUInt16LE(0, 0); head.writeUInt16LE(1, 2); head.writeUInt16LE(1, 4);
  head[6] = 32; head[7] = 32; head.writeUInt16LE(1, 10); head.writeUInt16LE(32, 12);
  head.writeUInt32LE(p32.length, 14); head.writeUInt32LE(22, 18);
  writeFileSync(join(out, 'favicon.ico'), Buffer.concat([head, p32]));

  const og = require('node:fs').readFileSync(join(__dirname, 'og-image.html'), 'utf8');
  await shot(og, 1200, 630, 'og-image.png');
  await browser.close();
  console.log('Brand assets written to src/static');
})();
