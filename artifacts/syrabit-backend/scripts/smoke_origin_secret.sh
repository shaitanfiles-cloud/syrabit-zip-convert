#!/usr/bin/env bash
# Task #606 — origin shared-secret smoke test.
#
# Hits a Cloud Run revision (or any backend URL) and confirms the
# OriginSharedSecretMiddleware is wired correctly:
#   • /api/health          → 200 (open path, Cloud Run probes need this)
#   • /api/auth/me w/o hdr → 403 (locked down)
#   • /api/auth/me w/  hdr → NOT 403 (middleware bypassed; downstream
#                                     usually answers 401 because no JWT)
#
# Usage:
#   BACKEND_URL=https://syrabit-backend-abc123-as.a.run.app \
#   ORIGIN_SHARED_SECRET=...                                \
#   ./scripts/smoke_origin_secret.sh
#
# Exit code is non-zero if any assertion fails — wire this into CI / a
# Cloud Build post-deploy step to catch regressions during cutover.

set -euo pipefail

: "${BACKEND_URL:?BACKEND_URL is required (e.g. https://syrabit-backend-xxx.run.app)}"
: "${ORIGIN_SHARED_SECRET:?ORIGIN_SHARED_SECRET is required}"

PROBE_PATH="${PROBE_PATH:-/api/auth/me}"

_status() {
  curl -sS -o /dev/null -w '%{http_code}' "$@"
}

echo ">> 1/3  GET ${BACKEND_URL}/api/health  (no header — must be 200)"
code=$(_status "${BACKEND_URL}/api/health")
echo "   got: ${code}"
if [ "${code}" != "200" ]; then
  echo "FAIL: /api/health should be open (got ${code})" >&2
  exit 1
fi

echo ">> 2/3  GET ${BACKEND_URL}${PROBE_PATH}  (no header — must be 403)"
code=$(_status "${BACKEND_URL}${PROBE_PATH}")
echo "   got: ${code}"
if [ "${code}" != "403" ]; then
  echo "FAIL: ${PROBE_PATH} without secret should be 403 (got ${code}). " \
       "Origin is NOT locked down." >&2
  exit 1
fi

echo ">> 3/3  GET ${BACKEND_URL}${PROBE_PATH}  (with header — must NOT be 403)"
code=$(_status -H "X-Origin-Auth: ${ORIGIN_SHARED_SECRET}" \
              "${BACKEND_URL}${PROBE_PATH}")
echo "   got: ${code}"
if [ "${code}" = "403" ]; then
  echo "FAIL: secret header was not honoured (still 403). Check that " \
       "ORIGIN_SHARED_SECRET on the server matches the one you supplied." >&2
  exit 1
fi

echo ""
echo "PASS — origin shared-secret middleware is correctly wired."
