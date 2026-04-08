import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { gzipSync, brotliCompressSync, constants } from "zlib";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, "..", "dist");

const COMPRESSIBLE = /\.(js|css|html|json|svg|xml|txt|map)$/;
const MIN_SIZE = 1024;

let gzCount = 0;
let brCount = 0;

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full);
      continue;
    }
    if (!COMPRESSIBLE.test(entry.name)) continue;
    if (entry.name.endsWith(".gz") || entry.name.endsWith(".br")) continue;

    const buf = fs.readFileSync(full);
    if (buf.length < MIN_SIZE) continue;

    const gz = gzipSync(buf, { level: 9 });
    if (gz.length < buf.length) {
      fs.writeFileSync(full + ".gz", gz);
      gzCount++;
    }

    const br = brotliCompressSync(buf, {
      params: { [constants.BROTLI_PARAM_QUALITY]: 11 },
    });
    if (br.length < buf.length) {
      fs.writeFileSync(full + ".br", br);
      brCount++;
    }
  }
}

walk(distDir);
console.log(`Compressed: ${gzCount} .gz, ${brCount} .br files`);
