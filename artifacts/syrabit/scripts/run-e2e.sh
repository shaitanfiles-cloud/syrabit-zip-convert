#!/usr/bin/env bash
# scripts/run-e2e.sh — Replit/NixOS-friendly Playwright launcher.
#
# Why this wrapper exists (Task #904)
# -----------------------------------
# Playwright bundles its own Chromium / chrome-headless-shell. On the
# Replit NixOS image those binaries fail to load with one of:
#
#   error while loading shared libraries: libgbm.so.1: cannot open shared
#     object file: No such file or directory
#   libatk-bridge-2.0.so.0: undefined symbol: atk_object_get_help_text
#
# The cause is twofold:
#   (1) `libgbm.so.1` lives in a transitively-pulled `mesa-libgbm-*` nix
#       store path that is *not* on the default loader search path here.
#       (`pkgs.mesa` in replit.nix gives us the GL/EGL/etc. libs but the
#       gbm split-out is its own derivation.)
#   (2) Only `libudev.so.0` is shipped (via `libudev0-shim`); Chromium
#       needs `libudev.so.1`. The two ABIs are compatible enough for
#       headless Chromium's minimal udev usage, so we present a
#       `libudev.so.1 -> libudev.so.0` symlink in a writable shim dir.
#
# Doing the fix here (instead of in `replit.nix`) avoids forcing a Nix
# rebuild on every contributor and keeps the workaround localised to the
# e2e command. CI already sees a different libc and does not need this.
#
# Effect: `pnpm --filter @workspace/syrabit run test:e2e` runs end-to-end
# without any further setup beyond `pnpm exec playwright install chromium`
# (which `test:e2e:install` already wraps).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PKG_DIR="$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)"

# --- 1. Find a libgbm.so.1 -------------------------------------------------
GBM_LIB="$(ls -d /nix/store/*-mesa-libgbm-*/lib 2>/dev/null | sort | tail -1 || true)"
if [ -z "${GBM_LIB}" ] || [ ! -e "${GBM_LIB}/libgbm.so.1" ]; then
  # Fallback: some Nix profiles ship libgbm directly inside the mesa output.
  GBM_LIB="$(ls -d /nix/store/*-mesa-*/lib 2>/dev/null \
    | while read -r d; do [ -e "$d/libgbm.so.1" ] && echo "$d"; done \
    | sort | tail -1 || true)"
fi
if [ -z "${GBM_LIB:-}" ]; then
  echo "run-e2e.sh: could not locate libgbm.so.1 in /nix/store." >&2
  echo "  Add 'pkgs.mesa-libgbm' (or rebuild replit.nix) so the lib is" >&2
  echo "  materialised, then re-run." >&2
  exit 1
fi

# --- 2. Build the libudev.so.1 shim ---------------------------------------
SHIM_DIR="${HOME}/.cache/playwright-libs"
mkdir -p "${SHIM_DIR}"
UDEV0="$(ls /nix/store/*-libudev0-shim-*/lib/libudev.so.0 2>/dev/null | sort | tail -1 || true)"
if [ -z "${UDEV0}" ]; then
  echo "run-e2e.sh: could not locate libudev.so.0 in /nix/store." >&2
  echo "  Replit images normally ship libudev0-shim; if it is missing," >&2
  echo "  add a systemd/udev package to replit.nix." >&2
  exit 1
fi
ln -sfn "${UDEV0}" "${SHIM_DIR}/libudev.so.1"

# --- 3. Compose LD_LIBRARY_PATH and exec ----------------------------------
export LD_LIBRARY_PATH="${GBM_LIB}:${SHIM_DIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

# Useful for debugging in CI logs without spamming success runs.
if [ "${DEBUG_E2E_LIBS:-0}" = "1" ]; then
  echo "run-e2e.sh: LD_LIBRARY_PATH=${LD_LIBRARY_PATH}" >&2
fi

cd "${PKG_DIR}"
exec ./node_modules/.bin/playwright test "$@"
