/**
 * scripts/run_git_push.js
 *
 * Clears ALL stale .git lock files (using Node.js fs — no git, no bash) and
 * then runs scripts/git_push.py via child_process.execSync().
 *
 * Usage (from code_execution sandbox):
 *   const { execSync } = await import('child_process');
 *   execSync('node scripts/run_git_push.js', { stdio: 'inherit', cwd: REPO_ROOT });
 *
 * Or inline in code_execution:
 *   await import('/home/runner/workspace/scripts/run_git_push.js');
 */

import fs   from 'fs';
import path from 'path';
import { execSync, spawnSync } from 'child_process';

const REPO_ROOT = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const GIT_DIR   = path.join(REPO_ROOT, '.git');

// Locate python3: prefer workspace virtualenv, fall back to system python3
function findPython() {
  const candidates = [
    path.join(REPO_ROOT, '.pythonlibs', 'bin', 'python3'),
    '/usr/bin/python3',
    '/usr/local/bin/python3',
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  // Last resort: whatever is on PATH
  const r = spawnSync('which', ['python3'], { encoding: 'utf8' });
  return (r.stdout || '').trim() || 'python3';
}
const PYTHON = findPython();

// ── Step 1: Recursively remove every .lock file under .git/ ─────────────────
function clearLocks(dir) {
  let count = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'pack') continue;          // skip large pack directory
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      count += clearLocks(full);
    } else if (entry.name.endsWith('.lock')) {
      try {
        fs.unlinkSync(full);
        console.log(`[run-git-push] cleared: ${path.relative(REPO_ROOT, full)}`);
        count++;
      } catch (e) {
        console.warn(`[run-git-push] WARN could not remove ${full}: ${e.message}`);
      }
    }
  }
  return count;
}

const removed = clearLocks(GIT_DIR);
if (removed === 0) console.log('[run-git-push] No lock files found.');

// ── Step 2: Run git_push.py ──────────────────────────────────────────────────
const args = process.argv.slice(2).join(' ');
const cmd  = `${PYTHON} ${path.join(REPO_ROOT, 'scripts', 'git_push.py')} ${args}`;
console.log(`[run-git-push] Executing: ${cmd}\n`);

try {
  execSync(cmd, { stdio: 'inherit', cwd: REPO_ROOT });
} catch (e) {
  process.exit(e.status ?? 1);
}
