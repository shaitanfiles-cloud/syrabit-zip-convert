/**
 * scripts/run_upgrade.js
 *
 * Clears ALL stale .git lock files (using Node.js fs) and then runs
 * scripts/upgrade.py via child_process.execSync().
 *
 * Usage (from code_execution sandbox):
 *   const { execSync } = await import('child_process');
 *   execSync('node scripts/run_upgrade.js', { stdio: 'inherit', cwd: REPO_ROOT });
 *
 * Pass extra flags after --:
 *   node scripts/run_upgrade.js -- --no-migrate --push
 */

import fs   from 'fs';
import path from 'path';
import { execSync, spawnSync } from 'child_process';

const REPO_ROOT = new URL('..', import.meta.url).pathname.replace(/\/$/, '');
const GIT_DIR   = path.join(REPO_ROOT, '.git');

function findPython() {
  const candidates = [
    path.join(REPO_ROOT, '.pythonlibs', 'bin', 'python3'),
    '/usr/bin/python3',
    '/usr/local/bin/python3',
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  const r = spawnSync('which', ['python3'], { encoding: 'utf8' });
  return (r.stdout || '').trim() || 'python3';
}
const PYTHON = findPython();

function clearLocks(dir) {
  let count = 0;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'pack') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      count += clearLocks(full);
    } else if (entry.name.endsWith('.lock')) {
      try {
        fs.unlinkSync(full);
        console.log(`[run-upgrade] cleared lock: ${path.relative(REPO_ROOT, full)}`);
        count++;
      } catch (e) {
        console.warn(`[run-upgrade] WARN could not remove ${full}: ${e.message}`);
      }
    }
  }
  return count;
}

const removed = clearLocks(GIT_DIR);
if (removed === 0) console.log('[run-upgrade] No lock files found.');

const args = process.argv.slice(2).join(' ');
const cmd  = `${PYTHON} ${path.join(REPO_ROOT, 'scripts', 'upgrade.py')} ${args}`;
console.log(`[run-upgrade] Executing: ${cmd}\n`);

try {
  execSync(cmd, { stdio: 'inherit', cwd: REPO_ROOT });
} catch (e) {
  process.exit(e.status ?? 1);
}
