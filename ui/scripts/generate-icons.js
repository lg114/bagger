import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import sharp from "sharp";
import pngToIco from "png-to-ico";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, "..");
const srcSvg = fs.readFileSync(path.join(root, "src", "assets", "logo.svg"), "utf-8");
// Replace currentColor with white for rasterization (background will be dark).
const svgWhite = srcSvg.replace(/currentColor/g, "#ffffff");

const outDir = path.join(root, "src-tauri", "icons");
const publicDir = path.join(root, "public");
fs.mkdirSync(outDir, { recursive: true });
fs.mkdirSync(publicDir, { recursive: true });

async function renderPng(size, outPath) {
  await sharp(Buffer.from(svgWhite))
    .resize(size, size, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png({ compressionLevel: 9 })
    .toFile(outPath);
  console.log(`generated ${outPath}`);
}

async function main() {
  await renderPng(32, path.join(outDir, "32x32.png"));
  await renderPng(128, path.join(outDir, "128x128.png"));
  await renderPng(256, path.join(outDir, "128x128@2x.png"));
  await renderPng(512, path.join(outDir, "512x512.png"));
  await renderPng(32, path.join(publicDir, "favicon.png"));

  // ICO with 256px and 32px frames.
  const icoBuf = await pngToIco([
    path.join(outDir, "128x128@2x.png"), // 256x256
    path.join(outDir, "32x32.png"),
  ]);
  fs.writeFileSync(path.join(outDir, "icon.ico"), icoBuf);
  console.log(`generated ${path.join(outDir, "icon.ico")}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
