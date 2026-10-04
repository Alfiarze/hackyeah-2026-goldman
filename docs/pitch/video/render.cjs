// Renders docs/pitch/video/index.html frame by frame (render(t) is deterministic) and assembles the MP4.
//   node render.cjs <out.mp4> [fps]            full film
//   node render.cjs --stills <dir> t1 t2 ...   preview frames
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const { spawn } = require("child_process");
const path = require("path");

(async () => {
  const args = process.argv.slice(2);
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined, args: ["--allow-file-access-from-files"] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto("file://" + path.join(__dirname, "index.html") + "?t=0");
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(500);
  if (args[0] === "--stills") {
    for (const t of args.slice(2)) {
      await page.evaluate((x) => window.render(x), Number(t));
      await page.screenshot({ path: path.join(args[1], `t${String(t).padStart(5, "0")}.png`) });
    }
  } else {
    const out = args[0] || "aegis-film.mp4", fps = Number(args[1] || 30), total = 60 * fps;
    const audio = path.join(__dirname, "score.wav");
    const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-i", "-",
      "-i", audio, "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
      "-shortest", "-movflags", "+faststart", out], { stdio: ["pipe", "inherit", "inherit"] });
    for (let f = 0; f < total; f++) {
      await page.evaluate((x) => window.render(x), f / fps);
      const buf = await page.screenshot({ type: "jpeg", quality: 92 });
      if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
      if (f % (fps * 5) === 0) console.log(`${(f / fps).toFixed(0)} s`);
    }
    ff.stdin.end();
    await new Promise((r) => ff.on("close", r));
  }
  await browser.close();
})();
