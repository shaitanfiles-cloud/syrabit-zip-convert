// Task #535: thin wrapper. The single-pass verifier in
// scripts/verify-all.mjs reproduces every assertion this script used
// to perform (subject + chapter prerender structural checks, manifest
// vs. disk reconciliation). Kept as a wrapper so existing runbooks /
// docs / muscle memory continue to work.

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
