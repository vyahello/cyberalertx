#!/usr/bin/env node
/* Regenerate brand PNG fallbacks from the master SVG sources.
 *
 * Run after editing any of:
 *   - public/brand/og-mark.svg     →  public/brand/og-image.png  (1200×630)
 *   - public/brand/icon-180.svg    →  public/brand/apple-touch-icon.png (180×180)
 *   - public/brand/icon-32.svg     →  public/brand/favicon-32.png (32×32)
 *
 * Why PNG copies at all when SVGs work everywhere modern:
 *   - Twitter / LinkedIn / Slack / Discord OG-card crawlers prefer raster.
 *   - iOS < 12 doesn't honor SVG apple-touch-icons.
 *   - Some headless / printer pipelines reject SVG entirely.
 *
 * `sharp` ships transitively via next.js (next/image uses it), so no
 * separate dependency install is required for this script to run.
 */
const sharp = require('sharp');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', 'public', 'brand');

const jobs = [
  { src: 'og-mark.svg',  out: 'og-image.png',         w: 1200, h: 630 },
  { src: 'icon-180.svg', out: 'apple-touch-icon.png', w: 180,  h: 180 },
  { src: 'icon-32.svg',  out: 'favicon-32.png',       w: 32,   h: 32  },
];

(async () => {
  for (const job of jobs) {
    const srcPath = path.join(ROOT, job.src);
    const outPath = path.join(ROOT, job.out);
    await sharp(fs.readFileSync(srcPath))
      .resize(job.w, job.h)
      .png({ compressionLevel: 9 })
      .toFile(outPath);
    console.log(`✓ ${job.out} (${job.w}×${job.h})`);
  }
})().catch((err) => {
  console.error('brand:png failed —', err.message);
  process.exit(1);
});
