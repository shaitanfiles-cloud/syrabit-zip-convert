#!/usr/bin/env python3
"""
scripts/upgrade.py — Syrabit Repo Upgrade Script
=================================================

Full workflow for safely upgrading the local repo and pushing to GitHub:

  1. Clear stale git lock files
  2. Pull latest from GitHub (merges remote changes into local branch)
  3. Install / sync frontend dependencies  (pnpm install)
  4. Install / sync backend dependencies   (pip install -r requirements.txt)
  5. Run any pending database migrations   (optional, skipped when --no-migrate)
  6. Optionally commit and push the result (--push flag)

Usage:
  python3 scripts/upgrade.py
  python3 scripts/upgrade.py --push
  python3 scripts/upgrade.py --push --message "chore: upgrade deps"
  python3 scripts/upgrade.py --no-migrate --push
  python3 scripts/upgrade.py --pull-only        # just pull, no install
"""

import argparse
import glob
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

REPO_ROOT   = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "artifacts" / "syrabit-backend"
GIT_DIR     = REPO_ROOT / ".git"

# Prevent git from spawning background maintenance after any push/fetch,
# which would create objects/maintenance.lock and block the bash tool.
_GIT_ENV = {
    **os.environ,
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_CONFIG_COUNT":   "1",
    "GIT_CONFIG_KEY_0":   "gc.auto",
    "GIT_CONFIG_VALUE_0": "0",
}


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _run(args: list, *, cwd=None, check=True, capture=True,
         timeout=120) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd or REPO_ROOT,
        capture_output=capture,
        text=True,
        timeout=timeout,
        check=check,
        env=_GIT_ENV,
    )


def _say(msg: str) -> None:
    print(f"[upgrade] {msg}", flush=True)


def _die(msg: str) -> None:
    print(f"[upgrade] ❌  {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def _section(title: str) -> None:
    print(f"\n{'─' * 60}", flush=True)
    print(f"  {title}", flush=True)
    print(f"{'─' * 60}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Clear git locks
# ─────────────────────────────────────────────────────────────────────────────

def clear_locks() -> None:
    _section("1 / 6  Clear stale git locks")

    found: list[str] = []
    for root, dirs, files in os.walk(str(GIT_DIR)):
        dirs[:] = [d for d in dirs if d not in ["pack"]]
        for fname in files:
            if fname.endswith(".lock"):
                found.append(os.path.join(root, fname))

    if not found:
        _say("No lock files found.")
        return

    for lock in found:
        try:
            os.remove(lock)
            _say(f"Removed: {os.path.relpath(lock, REPO_ROOT)}")
        except OSError as exc:
            _say(f"Warning — could not remove {lock}: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Pull latest from GitHub
# ─────────────────────────────────────────────────────────────────────────────

def get_auth_url(remote: str = "origin") -> tuple[str, str]:
    """Return (auth_url, token) for the given remote."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    user  = os.environ.get("GITHUB_USERNAME", "").strip()
    if not token:
        _die("GITHUB_TOKEN is not set in environment / Replit Secrets.")
    if not user:
        _die("GITHUB_USERNAME is not set in environment / Replit Secrets.")

    r = _run(["git", "remote", "get-url", remote], check=False)
    if r.returncode != 0:
        _die(f"Remote '{remote}' is not configured.")

    raw_url = r.stdout.strip()
    if "@" in raw_url:
        raw_url = "https://" + raw_url.split("@", 1)[1]

    enc_user  = urllib.parse.quote(user,  safe="")
    enc_token = urllib.parse.quote(token, safe="")
    auth_url  = raw_url.replace("https://", f"https://{enc_user}:{enc_token}@", 1)
    return auth_url, token


def pull_latest(remote: str, branch: str) -> None:
    _section(f"2 / 6  Pull latest from {remote}/{branch}")

    auth_url, token = get_auth_url(remote)

    def _safe(s: str) -> str:
        return s.replace(token, "***")

    # Fetch
    fetch = _run(
        ["git", "fetch", auth_url, f"{branch}:refs/remotes/{remote}/{branch}"],
        check=False,
        timeout=60,
    )
    if fetch.returncode != 0:
        _say(f"Warning — fetch failed: {_safe(fetch.stderr.strip()[:200])}")
        _say("Continuing without pull (offline mode).")
        return

    _say(f"Fetch OK: {_safe(fetch.stderr.strip()[:200])}")

    # Check if we're behind
    behind = _run(
        ["git", "log", "--oneline", f"HEAD..refs/remotes/{remote}/{branch}"],
        check=False,
    )
    if not behind.stdout.strip():
        _say("Already up to date.")
        return

    commit_count = len(behind.stdout.strip().splitlines())
    _say(f"Merging {commit_count} new commit(s) from remote …")

    merge = _run(
        ["git", "merge", f"refs/remotes/{remote}/{branch}", "--no-edit"],
        check=False,
        timeout=30,
    )
    if merge.returncode != 0:
        _die(
            f"Merge failed — resolve conflicts manually:\n"
            f"{merge.stdout.strip()}\n{merge.stderr.strip()}"
        )

    _say(f"Merge complete: {merge.stdout.strip()[:200]}")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Frontend dependencies (pnpm)
# ─────────────────────────────────────────────────────────────────────────────

def install_frontend_deps() -> None:
    _section("3 / 6  Frontend dependencies (pnpm install)")

    pnpm = _run(["which", "pnpm"], check=False)
    if pnpm.returncode != 0:
        _say("pnpm not found — skipping frontend install.")
        return

    result = _run(["pnpm", "install", "--frozen-lockfile"], check=False, timeout=180)
    if result.returncode == 0:
        _say("pnpm install OK")
    else:
        _say(f"pnpm install (frozen) failed — retrying without frozen lockfile …")
        result2 = _run(["pnpm", "install"], check=False, timeout=180)
        if result2.returncode != 0:
            _say(f"Warning — pnpm install failed:\n{result2.stderr.strip()[:300]}")
        else:
            _say("pnpm install OK (non-frozen)")


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Backend dependencies (pip)
# ─────────────────────────────────────────────────────────────────────────────

def install_backend_deps() -> None:
    _section("4 / 6  Backend dependencies (pip install)")

    req_file = BACKEND_DIR / "requirements.txt"
    if not req_file.exists():
        _say("No requirements.txt found in backend — skipping.")
        return

    pip = _run(["which", "pip3"], check=False)
    pip_cmd = "pip3" if pip.returncode == 0 else "pip"

    result = _run(
        [pip_cmd, "install", "-r", str(req_file), "--quiet"],
        cwd=BACKEND_DIR,
        check=False,
        timeout=240,
    )
    if result.returncode == 0:
        _say("pip install OK")
    else:
        _say(f"Warning — pip install encountered issues:\n{result.stderr.strip()[:300]}")


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Database migrations (optional)
# ─────────────────────────────────────────────────────────────────────────────

def run_migrations() -> None:
    _section("5 / 6  Database migrations")

    # Check for alembic (Python migrations)
    alembic = _run(["which", "alembic"], check=False)
    if alembic.returncode == 0:
        alembic_ini = BACKEND_DIR / "alembic.ini"
        if alembic_ini.exists():
            result = _run(
                ["alembic", "upgrade", "head"],
                cwd=BACKEND_DIR,
                check=False,
                timeout=120,
            )
            if result.returncode == 0:
                _say("Alembic migrations: OK")
            else:
                _say(f"Warning — Alembic upgrade failed:\n{result.stderr.strip()[:200]}")
            return

    # Check for Drizzle / pnpm db:push
    pkg_json = REPO_ROOT / "package.json"
    if pkg_json.exists():
        import json
        try:
            scripts = json.loads(pkg_json.read_text()).get("scripts", {})
            if "db:push" in scripts:
                result = _run(["pnpm", "run", "db:push"], check=False, timeout=120)
                if result.returncode == 0:
                    _say("Drizzle db:push OK")
                else:
                    _say(f"Warning — db:push failed:\n{result.stderr.strip()[:200]}")
                return
        except Exception:
            pass

    _say("No migration tool detected — skipping.")


# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Push to GitHub (delegates to git_push.py)
# ─────────────────────────────────────────────────────────────────────────────

def push_to_github(message: str, remote: str, branch: str) -> None:
    _section(f"6 / 6  Push to GitHub ({remote}/{branch})")

    push_script = Path(__file__).parent / "git_push.py"
    if not push_script.exists():
        _die("scripts/git_push.py not found — cannot push.")

    result = _run(
        [sys.executable, str(push_script),
         "--message", message,
         "--remote",  remote,
         "--branch",  branch],
        capture=False,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        _die("Push failed — see output above.")


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Full Syrabit repo upgrade: pull → install deps → migrate → push."
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="After upgrading, stage all changes and push to GitHub.",
    )
    parser.add_argument(
        "--message", "-m",
        default="chore: upgrade deps and sync repo",
        help="Commit message used when --push is set.",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote to pull from and push to (default: origin).",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Branch to use (default: current branch).",
    )
    parser.add_argument(
        "--no-migrate",
        action="store_true",
        help="Skip database migration step.",
    )
    parser.add_argument(
        "--pull-only",
        action="store_true",
        help="Only pull from GitHub — skip install, migrate, and push.",
    )
    args = parser.parse_args()

    # Resolve branch
    if args.branch is None:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True
        )
        args.branch = r.stdout.strip() or "master"

    print(f"\n{'=' * 60}")
    print(f"  Syrabit Repo Upgrade")
    print(f"  branch={args.branch}  remote={args.remote}")
    print(f"{'=' * 60}")

    clear_locks()
    pull_latest(args.remote, args.branch)

    if args.pull_only:
        _say("--pull-only set, stopping here.")
        return

    install_frontend_deps()
    install_backend_deps()

    if not args.no_migrate:
        run_migrations()
    else:
        _say("Skipping migrations (--no-migrate).")

    if args.push:
        push_to_github(args.message, args.remote, args.branch)
    else:
        _say("Skipping push (pass --push to push after upgrade).")

    print(f"\n{'=' * 60}")
    _say("✅  Upgrade complete.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
