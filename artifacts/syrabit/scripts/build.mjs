// Task #535: top-level build orchestrator with hard wall-clock budget.
//
// The Cloudflare Pages build wall is 35 minutes. We aim for < 8 min
// worst-case (typical < 5 min) and abort with a clear error well
// before that ceiling so the actual failure cause is in the log
// instead of an opaque "build killed" line.
//
// Stages (each is an individually runnable npm script too):
//   1. build:env           — fail fast on missing/invalid env vars
//   2. build:lint          — ad-policy linter (cheap)
//   3. build:client + build:ssr — Vite client and SSR builds, IN
//                            PARALLEL (they emit to different dirs)
//   4. build:prerender     — orchestrated parallel prerender of all
//                            four routes scripts, sharing a single
//                            backend cache fetch
//   5. build:verify        — single-pass dist/ walk + headless
//                            hydration check
//   6. build:precache      — generate the SW precache manifest
//
// All envs that gate behaviour are documented in CLOUDFLARE_PAGES.md.

import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");

const BUDGET_MS = (() => {
  const raw = process.env.BUILD_BUDGET_MS;
  const n = raw ? Number.parseInt(raw, 10) : NaN;
  // Default 8 min, hard floor 2 min, hard ceiling 30 min.
  return Number.isFinite(n) && n >= 120_000 && n <= 30 * 60_000
    ? n
    : 8 * 60_000;
})();

const overallStart = Date.now();
let timedOut = false;
const watchdog = setTimeout(() => {
  timedOut = true;
  console.error(
    `[build] WALL-CLOCK BUDGET EXCEEDED (${BUDGET_MS}ms). Aborting build.`,
  );
  // Process exit will tear down all child processes.
  process.exit(2);
}, BUDGET_MS);
watchdog.unref();

function fmt(ms) {
  return `${(ms / 1000).toFixed(1)}s`;
}

function runStep(name, command, args, opts = {}) {
  const stepBudgetMs = opts.budgetMs ?? BUDGET_MS;
  const startedAt = Date.now();
  console.log(`\n[build] ▶ ${name}: ${command} ${args.join(" ")}`);
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: "inherit",
      env: process.env,
      cwd: opts.cwd || repoRoot,
    });
    const stepTimer = setTimeout(() => {
      console.error(
        `[build] step ${name} exceeded ${stepBudgetMs}ms — sending SIGTERM`,
      );
      try {
        child.kill("SIGTERM");
      } catch {}
      setTimeout(() => {
        try {
          child.kill("SIGKILL");
        } catch {}
      }, 5_000).unref();
    }, stepBudgetMs);
    stepTimer.unref();
    child.on("error", (err) => {
      clearTimeout(stepTimer);
      reject(err);
    });
    child.on("exit", (code, signal) => {
      clearTimeout(stepTimer);
      const elapsed = Date.now() - startedAt;
      if (code === 0) {
        console.log(`[build] ✓ ${name} (${fmt(elapsed)})`);
        resolve({ name, elapsed });
      } else {
        const err = new Error(
          `[build] ✗ ${name} failed in ${fmt(elapsed)} (code=${code}${signal ? `, signal=${signal}` : ""})`,
        );
        err.exitCode = code ?? 1;
        reject(err);
      }
    });
  });
}

const node = (script, extraArgs = [], opts) =>
  runStep(`node ${path.basename(script)}`, process.execPath, [script, ...extraArgs], opts);

async function main() {
  const summary = [];
  const record = async (label, p) => {
    const r = await p;
    summary.push({ label, elapsed: r?.elapsed ?? 0 });
  };

  // 1. Env check — must come before anything that produces output.
  await record(
    "env",
    node(path.join(__dirname, "check-build-env.mjs"), [], { budgetMs: 30_000 }),
  );

  // 2. Ad-policy lint — cheap, fail fast.
  await record(
    "lint:ads",
    node(path.join(__dirname, "verify-no-ads.mjs"), [], { budgetMs: 30_000 }),
  );

  // 3. Client + SSR builds in parallel. They write to dist/ and
  //    dist-ssr/ respectively, no shared output.
  const clientStart = Date.now();
  const [clientRes, ssrRes] = await Promise.all([
    runStep(
      "vite build (client)",
      "pnpm",
      ["exec", "vite", "build"],
      { cwd: repoRoot, budgetMs: 5 * 60_000 },
    ),
    runStep(
      "vite build (ssr)",
      "pnpm",
      [
        "exec",
        "vite",
        "build",
        "--ssr",
        "src/entry-server.jsx",
        "--outDir",
        "dist-ssr",
        "--emptyOutDir",
      ],
      { cwd: repoRoot, budgetMs: 5 * 60_000 },
    ),
  ]);
  summary.push({ label: "vite parallel", elapsed: Date.now() - clientStart });

  // 4. Prerender — orchestrator pre-warms the backend cache then
  //    spawns the four prerender scripts in parallel.
  await record(
    "prerender",
    node(path.join(__dirname, "prerender-all.mjs"), [], {
      budgetMs: 8 * 60_000,
    }),
  );

  // 5. Verify — single dist/ walk + headless hydration check.
  await record(
    "verify",
    node(path.join(__dirname, "verify-all.mjs"), [], {
      budgetMs: 6 * 60_000,
    }),
  );

  // 6. Precache manifest.
  await record(
    "precache",
    node(path.join(__dirname, "generate-precache-manifest.mjs"), [], {
      budgetMs: 30_000,
    }),
  );

  const total = Date.now() - overallStart;
  console.log("\n[build] === summary ===");
  for (const s of summary) {
    console.log(`  ${s.label.padEnd(20)} ${fmt(s.elapsed)}`);
  }
  console.log(`  ${"TOTAL".padEnd(20)} ${fmt(total)} (budget ${fmt(BUDGET_MS)})`);
  clearTimeout(watchdog);
}

main().catch((err) => {
  if (timedOut) return; // already exited via watchdog
  console.error(err?.stack || err);
  clearTimeout(watchdog);
  process.exit(typeof err?.exitCode === "number" ? err.exitCode : 1);
});
