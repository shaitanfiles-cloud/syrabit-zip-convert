import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(__dirname, "..", "dist");
const htmlPath = path.join(distDir, "index.html");

const assetsDir = path.join(distDir, "assets");
const files = fs.readdirSync(assetsDir);

const targets = ["react-dom", "vendor", "router", "query", "radix"];
const links = [];

for (const name of targets) {
  const match = files.find((f) => new RegExp(`^${name}-[A-Za-z0-9_-]+\\.js$`).test(f));
  if (match) {
    const href = `/assets/${match}`;
    links.push(`<link rel="modulepreload" crossorigin href="${href}">`);
  }
}

if (links.length === 0) {
  console.log("No additional modulepreload hints to inject");
  process.exit(0);
}

let html = fs.readFileSync(htmlPath, "utf-8");

const existingPreloads = html.match(/<link rel="modulepreload"[^>]*>/g) || [];
const existingHrefs = new Set(existingPreloads.map((l) => l.match(/href="([^"]+)"/)?.[1]).filter(Boolean));

const newLinks = links.filter((l) => {
  const href = l.match(/href="([^"]+)"/)?.[1];
  return href && !existingHrefs.has(href);
});

if (newLinks.length === 0) {
  console.log("All modulepreload hints already present in HTML");
  process.exit(0);
}

const insertPoint = html.indexOf('<link rel="modulepreload"');
if (insertPoint === -1) {
  const headEnd = html.indexOf("</head>");
  html = html.slice(0, headEnd) + "    " + newLinks.join("\n    ") + "\n  " + html.slice(headEnd);
} else {
  html = html.slice(0, insertPoint) + newLinks.join("\n    ") + "\n    " + html.slice(insertPoint);
}

fs.writeFileSync(htmlPath, html);
console.log("Injected modulepreload hints:", newLinks);
