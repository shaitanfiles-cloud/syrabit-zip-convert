#!/usr/bin/env python3
"""
scripts/clear_locks.py — Remove ALL stale .git lock files (no git commands used)

Run this first if bash is blocked by stale lock files:
  python3 scripts/clear_locks.py

This script uses only Python's os module — zero git subprocess calls —
so it works even when .git lock files exist.
"""
import os
import sys
from pathlib import Path

GIT_DIR = Path(__file__).resolve().parent.parent / ".git"


def clear_all_locks(verbose: bool = True) -> int:
    """Remove all .lock files under .git/. Returns the count removed."""
    removed = 0
    errors  = 0

    for root, dirs, files in os.walk(str(GIT_DIR)):
        # Skip the pack/ sub-directory (very large, no lock files there)
        dirs[:] = [d for d in dirs if d != "pack"]

        for fname in files:
            if not fname.endswith(".lock"):
                continue

            full_path = os.path.join(root, fname)
            rel_path  = os.path.relpath(full_path, GIT_DIR.parent)

            try:
                os.remove(full_path)
                if verbose:
                    print(f"[clear-locks] Removed: {rel_path}")
                removed += 1
            except OSError as exc:
                print(f"[clear-locks] WARN — could not remove {rel_path}: {exc}",
                      file=sys.stderr)
                errors += 1

    if removed == 0 and errors == 0:
        if verbose:
            print("[clear-locks] No lock files found — workspace is clean.")

    return removed


if __name__ == "__main__":
    n = clear_all_locks(verbose=True)
    sys.exit(0)
