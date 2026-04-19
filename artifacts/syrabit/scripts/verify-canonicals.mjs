// Task #535: thin wrapper — see scripts/verify-all.mjs for the
// canonical implementation (it reproduces every canonical assertion
// this script used to perform, including subject + chapter sampling
// and the no-canonical-on-root-html guard).

import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const child = spawn(
  process.execPath,
  [path.join(__dirname, "verify-all.mjs")],
  { stdio: "inherit", env: process.env },
);
child.on("exit", (code) => process.exit(code ?? 1));
