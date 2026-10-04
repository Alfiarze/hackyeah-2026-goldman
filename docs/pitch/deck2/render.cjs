// Renders docs/pitch/deck2/index.html (one <section> per 1920x1080 slide).
//   node render.cjs                 -> ../aegis-deck-v2.pdf
//   node render.cjs --png <dir>     -> <dir>/s01.png … (previews)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "/opt/node22/lib/node_modules/playwright");
const path = require("path");
const fs = require("fs");

(async () => {
  const args = process.argv.slice(2);
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/opt/pw-browsers/chromium",
    args: ["--allow-file-access-from-files"],
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto("file://" + path.join(__dirname, "index.html"));
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => Promise.all([...document.images].map((i) => i.complete ? 0 : new Promise((r) => (i.onload = i.onerror = r)))));
  await page.waitForTimeout(300);

  if (args[0] === "--png") {
    const dir = args[1] || "/tmp/claude-0/deck2";
    fs.mkdirSync(dir, { recursive: true });
    const n = await page.locator("section.slide").count();
    for (let i = 0; i < n; i++) {
      await page.locator("section.slide").nth(i).screenshot({ path: path.join(dir, `s${String(i + 1).padStart(2, "0")}.png`) });
    }
    console.log(`${n} slides -> ${dir}`);
  } else {
    const out = args[0] || path.join(__dirname, "..", "aegis-deck-v2.pdf");
    await page.emulateMedia({ media: "print" });
    await page.pdf({ path: out, width: "1920px", height: "1080px", printBackground: true, preferCSSPageSize: true });
    console.log(`PDF -> ${out} (${(fs.statSync(out).size / 1048576).toFixed(2)} MB)`);
  }
  await browser.close();
})();
