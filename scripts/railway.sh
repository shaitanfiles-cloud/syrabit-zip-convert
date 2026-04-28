#!/usr/bin/env bash
#
# scripts/railway.sh — dispatcher for driving the syrabit-backend Railway
# service from this workspace and from CI.
#
# Subcommands:
#   redeploy           Redeploy the latest already-built image on Railway.
#                      No source upload. Polls until SUCCESS.
#   deploy             Upload the current artifacts/syrabit-backend/ tree as
#                      a new deploy (railway up). Streams build logs and
#                      exits 0 only on SUCCESS.
#   logs [-d|-b]       Print recent service logs and exit. Default: deploy
#         [-n LINES]   logs, last 200 lines. Use -b for build logs.
#         [--deployment ID]
#                      Override deployment ID (defaults to latest non-removed).
#   status             Print active deployment id, status, region, and a
#                      live /api/health probe of the service domain.
#   vars               List variables for the current service+environment.
#   var-set KEY=VAL... Set one or more variables (triggers a redeploy).
#   var-unset KEY...   Delete one or more variables (triggers a redeploy).
#
# Required env:
#   RAILWAY_API_TOKEN     Account or team token with access to the project.
#
# Targeting env (must resolve to a single service+environment):
#   RAILWAY_PROJECT_ID    Project UUID. Required.
#   RAILWAY_SERVICE_ID    Service UUID. Required (for everything except
#                         status without a deployment).
#   RAILWAY_ENVIRONMENT   Environment name (default: production).
#   RAILWAY_ENVIRONMENT_ID
#                         Optional. If unset, we resolve it from
#                         RAILWAY_ENVIRONMENT via the GraphQL API.
#   RAILWAY_HEALTHCHECK_URL
#                         Optional. Public URL probed by `status`
#                         (default: https://api.syrabit.ai/api/health).
#
# Exit codes:
#   0  success (deploy reported SUCCESS, or read-only command printed data)
#   1  usage / config / auth error
#   2  the deploy or operation failed on Railway's side
#
set -Eeuo pipefail

SCRIPT_NAME="$(basename "$0")"
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &> /dev/null && pwd)"
BACKEND_DIR="${REPO_ROOT}/artifacts/syrabit-backend"
RAILWAY_API="${RAILWAY_API:-https://backboard.railway.app/graphql/v2}"
HEALTHCHECK_URL_DEFAULT="https://api.syrabit.ai/api/health"

# ─── production defaults ───────────────────────────────────────────────────
# These are the live syrabit-backend Railway IDs (NOT secrets — they're
# just opaque identifiers visible in the dashboard URL). Override via env
# vars to target a different project/service (e.g. a staging environment).
# The misleading "mockup-sandbox" service name is historical; per
# workers/edge-proxy/wrangler.toml the corresponding URL
# `workspacemockup-sandbox-production-df37.up.railway.app` IS the live
# Syrabit.ai API origin that api.syrabit.ai proxies to.
: "${RAILWAY_PROJECT_ID:=313c0409-d55b-421e-88e1-89569c3db8e1}"
: "${RAILWAY_SERVICE_ID:=5acc87f2-f785-45dd-bdbf-8b3c32712d19}"
: "${RAILWAY_ENVIRONMENT:=production}"

# ─── helpers ────────────────────────────────────────────────────────────────
log()   { printf '[%s] %s\n' "$SCRIPT_NAME" "$*" >&2; }
die()   { log "ERROR: $*"; exit 1; }
die2()  { log "FAIL:  $*"; exit 2; }

require_token() {
  if [[ -z "${RAILWAY_API_TOKEN:-}" ]]; then
    die "RAILWAY_API_TOKEN is not set. Export it first (it's stored as a Replit Secret in this workspace)."
  fi
}

require_project() {
  if [[ -z "${RAILWAY_PROJECT_ID:-}" ]]; then
    die "RAILWAY_PROJECT_ID is not set. Find it in Railway dashboard → Project Settings → General."
  fi
}

require_service() {
  if [[ -z "${RAILWAY_SERVICE_ID:-}" ]]; then
    die "RAILWAY_SERVICE_ID is not set. Find it in Railway dashboard → Service Settings → Service ID."
  fi
}

# Run a GraphQL query against Railway. $1 = JSON body. Stdout = response JSON.
gql() {
  local body="$1"
  local resp
  resp=$(curl -sS --fail-with-body -m 30 \
    -X POST "$RAILWAY_API" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $RAILWAY_API_TOKEN" \
    -d "$body") || {
      log "GraphQL request failed (HTTP/transport error):"
      printf '%s\n' "$resp" >&2
      return 1
    }
  # Railway returns HTTP 200 with a top-level "errors" array on auth /
  # permission / schema problems. Treat those as failures so callers
  # don't keep walking with null data.
  if printf '%s' "$resp" | python3 -c '
import json, sys
try:
    data = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
errs = data.get("errors")
if errs:
    msgs = []
    for e in errs:
        if isinstance(e, dict) and e.get("message"):
            msgs.append(str(e["message"]))
        else:
            msgs.append(str(e))
    print("; ".join(msgs) or "graphql error")
    sys.exit(1)
sys.exit(0)
' >/tmp/railway_gql_err 2>/dev/null; then
    printf '%s' "$resp"
    return 0
  else
    log "GraphQL returned errors: $(cat /tmp/railway_gql_err 2>/dev/null || echo unknown)"
    rm -f /tmp/railway_gql_err
    return 1
  fi
}

# Print JSON via python3 (always available) for parsing.
json() { python3 -c "$1" "$2"; }

# Resolve RAILWAY_ENVIRONMENT_ID from RAILWAY_ENVIRONMENT name if not set.
resolve_environment_id() {
  local env_name="${RAILWAY_ENVIRONMENT:-production}"
  if [[ -n "${RAILWAY_ENVIRONMENT_ID:-}" ]]; then
    return 0
  fi
  local q='{"query":"query($id: String!) { project(id: $id) { environments { edges { node { id name } } } } }","variables":{"id":"'"$RAILWAY_PROJECT_ID"'"}}'
  local resp
  resp=$(gql "$q") || die "could not list environments for project $RAILWAY_PROJECT_ID"
  local env_id
  env_id=$(python3 - "$resp" "$env_name" <<'PY'
import json, sys
data = json.loads(sys.argv[1])
name = sys.argv[2]
edges = (data.get("data") or {}).get("project", {}).get("environments", {}).get("edges", [])
for e in edges:
    n = e["node"]
    if n["name"] == name:
        print(n["id"])
        sys.exit(0)
sys.exit(1)
PY
) || die "environment '$env_name' not found in project $RAILWAY_PROJECT_ID"
  RAILWAY_ENVIRONMENT_ID="$env_id"
  export RAILWAY_ENVIRONMENT_ID
}

# Ensure the Railway CLI is available, install on demand into a workspace
# cache so CI runs that don't pre-install one still work.
ensure_cli() {
  if command -v railway >/dev/null 2>&1; then
    RAILWAY_BIN="$(command -v railway)"
    return 0
  fi
  die "the railway CLI is not installed. Install it with: npm i -g @railway/cli"
}

# Link the project/service/environment into a per-invocation temp dir so
# we never touch the user's working tree. Echoes the temp dir.
link_into_tempdir() {
  require_project
  resolve_environment_id
  local link_dir
  link_dir="$(mktemp -d -t railway-link-XXXXXX)"
  pushd "$link_dir" >/dev/null
  local args=(--project "$RAILWAY_PROJECT_ID" --environment "${RAILWAY_ENVIRONMENT:-production}")
  if [[ -n "${RAILWAY_SERVICE_ID:-}" ]]; then
    args+=(--service "$RAILWAY_SERVICE_ID")
  fi
  if ! railway link "${args[@]}" >/dev/null 2>&1; then
    popd >/dev/null
    rm -rf "$link_dir"
    die "railway link failed for project $RAILWAY_PROJECT_ID. Check that RAILWAY_API_TOKEN has access."
  fi
  popd >/dev/null
  printf '%s' "$link_dir"
}

# Print the id of the latest deployment for the current service+environment.
# Empty string if none. Requires require_project/require_service/resolve_environment_id.
get_latest_deployment_id() {
  local resp
  resp=$(gql '{"query":"query($svc: String!, $env: String!) { deployments(first: 1, input: {serviceId: $svc, environmentId: $env}) { edges { node { id } } } }","variables":{"svc":"'"$RAILWAY_SERVICE_ID"'","env":"'"$RAILWAY_ENVIRONMENT_ID"'"}}') || return 1
  python3 -c '
import json, sys
edges = json.loads(sys.argv[1]).get("data", {}).get("deployments", {}).get("edges", [])
print(edges[0]["node"]["id"] if edges else "")
' "$resp"
}

# Wait until a deployment with an id different from $1 (the previous latest)
# appears for this service+environment, then poll_deployment it.
# $1 = previous latest deployment id (may be empty if there were none).
wait_for_new_deployment_then_poll() {
  local prev="$1"
  local max_wait="${RAILWAY_NEW_DEPLOY_TIMEOUT:-180}"  # 3 min to enqueue
  local start=$SECONDS
  local new_id=""
  log "waiting for Railway to enqueue a new deployment (was: ${prev:-none})…"
  while true; do
    new_id=$(get_latest_deployment_id 2>/dev/null || true)
    if [[ -n "$new_id" && "$new_id" != "$prev" ]]; then
      log "new deployment detected: $new_id"
      break
    fi
    if (( SECONDS - start > max_wait )); then
      die2 "timed out after ${max_wait}s waiting for Railway to enqueue a new deployment after the variable change"
    fi
    sleep 3
  done
  poll_deployment "$new_id"
}

# Poll a deployment until it reaches a terminal state. $1 = deployment id.
poll_deployment() {
  local dep_id="$1"
  local max_wait="${RAILWAY_DEPLOY_TIMEOUT:-1800}"  # 30 min
  local start=$SECONDS
  local last_status=""
  log "polling deployment $dep_id (timeout ${max_wait}s)…"
  while true; do
    local resp status
    resp=$(gql '{"query":"query($id: String!) { deployment(id: $id) { id status canRedeploy createdAt updatedAt staticUrl } }","variables":{"id":"'"$dep_id"'"}}') \
      || { log "could not query deployment status; retrying"; sleep 5; continue; }
    status=$(python3 -c '
import json, sys
d = json.loads(sys.argv[1]).get("data", {}).get("deployment") or {}
print(d.get("status", "UNKNOWN"))
' "$resp")
    if [[ "$status" != "$last_status" ]]; then
      log "deployment status: $status"
      last_status="$status"
    fi
    case "$status" in
      SUCCESS)
        log "deployment $dep_id succeeded."
        return 0
        ;;
      FAILED|CRASHED|REMOVED|SKIPPED)
        die2 "deployment $dep_id ended in state: $status"
        ;;
    esac
    if (( SECONDS - start > max_wait )); then
      die2 "timed out after ${max_wait}s waiting for deployment $dep_id (last status: $last_status)"
    fi
    sleep 5
  done
}

# ─── subcommands ────────────────────────────────────────────────────────────

cmd_redeploy() {
  require_token; require_project; require_service
  resolve_environment_id
  log "redeploying latest built image for service=$RAILWAY_SERVICE_ID env=${RAILWAY_ENVIRONMENT:-production}"
  # Fetch the most recent deployment id via GraphQL, then redeploy it.
  local resp dep_id
  resp=$(gql '{"query":"query($svc: String!, $env: String!) { deployments(first: 1, input: {serviceId: $svc, environmentId: $env}) { edges { node { id status meta } } } }","variables":{"svc":"'"$RAILWAY_SERVICE_ID"'","env":"'"$RAILWAY_ENVIRONMENT_ID"'"}}') \
    || die "could not query deployments"
  dep_id=$(python3 -c '
import json, sys
edges = json.loads(sys.argv[1]).get("data", {}).get("deployments", {}).get("edges", [])
print(edges[0]["node"]["id"] if edges else "")
' "$resp")
  [[ -n "$dep_id" ]] || die "no deployments found for service $RAILWAY_SERVICE_ID in environment $RAILWAY_ENVIRONMENT_ID"
  log "found latest deployment: $dep_id"

  # Trigger redeploy via the official mutation. usePreviousImageTag=true
  # avoids a rebuild — Railway just re-runs the existing image.
  resp=$(gql '{"query":"mutation($id: String!) { deploymentRedeploy(id: $id, usePreviousImageTag: true) { id status } }","variables":{"id":"'"$dep_id"'"}}') \
    || die "redeploy mutation failed"
  local new_id
  new_id=$(python3 -c '
import json, sys
d = json.loads(sys.argv[1]).get("data", {}).get("deploymentRedeploy") or {}
print(d.get("id", ""))
' "$resp")
  [[ -n "$new_id" ]] || die "redeploy mutation returned no deployment id (response: $resp)"
  log "redeploy enqueued as deployment $new_id"
  poll_deployment "$new_id"
}

cmd_deploy() {
  require_token; require_project; require_service
  resolve_environment_id
  ensure_cli
  [[ -d "$BACKEND_DIR" ]] || die "backend directory not found: $BACKEND_DIR"
  log "uploading $BACKEND_DIR → project=$RAILWAY_PROJECT_ID service=$RAILWAY_SERVICE_ID env=${RAILWAY_ENVIRONMENT:-production}"
  # Run from the backend dir so railway respects its .gitignore / watchPatterns
  # and only the backend tree is uploaded (not the entire monorepo).
  pushd "$BACKEND_DIR" >/dev/null
  local args=(
    up
    --project "$RAILWAY_PROJECT_ID"
    --service "$RAILWAY_SERVICE_ID"
    --environment "${RAILWAY_ENVIRONMENT:-production}"
    --ci
  )
  if [[ -n "${RAILWAY_DEPLOY_MESSAGE:-}" ]]; then
    args+=(--message "$RAILWAY_DEPLOY_MESSAGE")
  fi
  # railway up --ci streams build logs and exits non-zero on failure;
  # it returns 0 only after the deployment is healthy.
  if ! RAILWAY_API_TOKEN="$RAILWAY_API_TOKEN" railway "${args[@]}"; then
    popd >/dev/null
    die2 "railway up failed (see logs above)"
  fi
  popd >/dev/null
  log "deploy completed."
}

cmd_logs() {
  require_token; require_project; require_service
  resolve_environment_id
  local kind="deploy" lines="200" dep_id=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -b|--build)      kind="build"; shift ;;
      -d|--deploy)     kind="deploy"; shift ;;
      -n|--lines)      lines="$2"; shift 2 ;;
      --deployment)    dep_id="$2"; shift 2 ;;
      *) die "unknown logs flag: $1" ;;
    esac
  done
  if [[ -z "$dep_id" ]]; then
    # Pick the latest non-removed deployment.
    local resp
    resp=$(gql '{"query":"query($svc: String!, $env: String!) { deployments(first: 5, input: {serviceId: $svc, environmentId: $env}) { edges { node { id status } } } }","variables":{"svc":"'"$RAILWAY_SERVICE_ID"'","env":"'"$RAILWAY_ENVIRONMENT_ID"'"}}') \
      || die "could not query deployments"
    dep_id=$(python3 -c '
import json, sys
edges = json.loads(sys.argv[1]).get("data", {}).get("deployments", {}).get("edges", [])
for e in edges:
    n = e["node"]
    if n["status"] not in ("REMOVED",):
        print(n["id"]); sys.exit(0)
if edges: print(edges[0]["node"]["id"])
' "$resp")
    [[ -n "$dep_id" ]] || die "no deployments found"
  fi
  log "fetching $kind logs for deployment $dep_id (last $lines lines)"
  local q
  if [[ "$kind" == "build" ]]; then
    q='{"query":"query($id: String!, $n: Int!) { buildLogs(deploymentId: $id, limit: $n) { timestamp message severity } }","variables":{"id":"'"$dep_id"'","n":'"$lines"'}}'
  else
    q='{"query":"query($id: String!, $n: Int!) { deploymentLogs(deploymentId: $id, limit: $n) { timestamp message severity } }","variables":{"id":"'"$dep_id"'","n":'"$lines"'}}'
  fi
  local resp
  resp=$(gql "$q") || die "logs query failed"
  python3 -c '
import json, sys
data = json.loads(sys.argv[1]).get("data") or {}
key = "buildLogs" if "buildLogs" in data else "deploymentLogs"
for line in (data.get(key) or []):
    ts = line.get("timestamp") or ""
    sev = (line.get("severity") or "").lower() or "-"
    msg = line.get("message") or ""
    print(f"{ts} [{sev}] {msg}")
' "$resp"
}

cmd_status() {
  require_token; require_project; require_service
  resolve_environment_id
  local resp
  resp=$(gql '{"query":"query($svc: String!, $env: String!) { deployments(first: 5, input: {serviceId: $svc, environmentId: $env}) { edges { node { id status createdAt updatedAt staticUrl meta canRedeploy } } } service(id: $svc) { id name } environment(id: $env) { id name } }","variables":{"svc":"'"$RAILWAY_SERVICE_ID"'","env":"'"$RAILWAY_ENVIRONMENT_ID"'"}}') \
    || die "status query failed"
  local health="${RAILWAY_HEALTHCHECK_URL:-$HEALTHCHECK_URL_DEFAULT}"
  local hc_code
  hc_code=$(curl -sS -o /dev/null -m 10 -w '%{http_code}' "$health" || echo "000")
  python3 - "$resp" "$health" "$hc_code" <<'PY'
import json, sys
data = json.loads(sys.argv[1]).get("data", {})
svc = data.get("service") or {}
env = data.get("environment") or {}
deploys = [e["node"] for e in (data.get("deployments") or {}).get("edges", [])]

def short(d):
    meta = d.get("meta") or {}
    manifest = meta.get("serviceManifest") or {}
    deploy = manifest.get("deploy") or {}
    multi = deploy.get("multiRegionConfig") or {}
    region = next(iter(multi.keys()), deploy.get("region"))
    return {
        "id": d["id"],
        "status": d["status"],
        "createdAt": d["createdAt"],
        "updatedAt": d.get("updatedAt"),
        "staticUrl": d.get("staticUrl"),
        "region": region,
        "commit": (meta.get("commitHash") or "")[:12],
        "reason": meta.get("reason"),
        "buildOnly": meta.get("buildOnly"),
        "imageDigest": meta.get("imageDigest"),
    }

out = {
    "service": svc.get("name"),
    "service_id": svc.get("id"),
    "environment": env.get("name"),
    "environment_id": env.get("id"),
    "active_deployment": (short(deploys[0]) if deploys else None),
    "recent_deployments": [
        {"id": d["id"], "status": d["status"], "createdAt": d["createdAt"]}
        for d in deploys
    ],
    "healthcheck": {
        "url": sys.argv[2],
        "status_code": int(sys.argv[3]) if sys.argv[3].isdigit() else sys.argv[3],
    },
}
print(json.dumps(out, indent=2))
PY
}

cmd_vars() {
  require_token; require_project; require_service
  resolve_environment_id
  local resp
  resp=$(gql '{"query":"query($p: String!, $e: String!, $s: String!) { variables(projectId: $p, environmentId: $e, serviceId: $s) }","variables":{"p":"'"$RAILWAY_PROJECT_ID"'","e":"'"$RAILWAY_ENVIRONMENT_ID"'","s":"'"$RAILWAY_SERVICE_ID"'"}}') \
    || die "variables query failed"
  python3 -c '
import json, sys
v = json.loads(sys.argv[1]).get("data", {}).get("variables") or {}
for k in sorted(v):
    print(k)
' "$resp"
}

cmd_var_set() {
  require_token; require_project; require_service
  resolve_environment_id
  [[ $# -gt 0 ]] || die "usage: $SCRIPT_NAME var-set KEY=VALUE [KEY=VALUE...]"
  local prev_dep
  prev_dep=$(get_latest_deployment_id || true)
  local pair k v resp
  for pair in "$@"; do
    [[ "$pair" == *"="* ]] || die "expected KEY=VALUE, got: $pair"
    k="${pair%%=*}"
    v="${pair#*=}"
    log "setting $k (value redacted)…"
    # variableUpsert handles both create and update.
    local payload
    payload=$(python3 -c '
import json, sys
print(json.dumps({
    "query": "mutation($i: VariableUpsertInput!) { variableUpsert(input: $i) }",
    "variables": {"i": {
        "projectId": sys.argv[1],
        "environmentId": sys.argv[2],
        "serviceId": sys.argv[3],
        "name": sys.argv[4],
        "value": sys.argv[5],
    }},
}))
' "$RAILWAY_PROJECT_ID" "$RAILWAY_ENVIRONMENT_ID" "$RAILWAY_SERVICE_ID" "$k" "$v")
    resp=$(gql "$payload") || die "failed to set $k"
    if echo "$resp" | grep -q '"errors"'; then
      log "response: $resp"
      die "Railway returned an error for $k"
    fi
  done
  log "all variables applied; waiting for Railway to roll out a new deployment…"
  wait_for_new_deployment_then_poll "$prev_dep"
}

cmd_var_unset() {
  require_token; require_project; require_service
  resolve_environment_id
  [[ $# -gt 0 ]] || die "usage: $SCRIPT_NAME var-unset KEY [KEY...]"
  local prev_dep
  prev_dep=$(get_latest_deployment_id || true)
  local k resp payload
  for k in "$@"; do
    log "unsetting $k…"
    payload=$(python3 -c '
import json, sys
print(json.dumps({
    "query": "mutation($i: VariableDeleteInput!) { variableDelete(input: $i) }",
    "variables": {"i": {
        "projectId": sys.argv[1],
        "environmentId": sys.argv[2],
        "serviceId": sys.argv[3],
        "name": sys.argv[4],
    }},
}))
' "$RAILWAY_PROJECT_ID" "$RAILWAY_ENVIRONMENT_ID" "$RAILWAY_SERVICE_ID" "$k")
    resp=$(gql "$payload") || die "failed to unset $k"
    if echo "$resp" | grep -q '"errors"'; then
      log "response: $resp"
      die "Railway returned an error for $k"
    fi
  done
  log "all variables removed; waiting for Railway to roll out a new deployment…"
  wait_for_new_deployment_then_poll "$prev_dep"
}

# ─── dispatch ───────────────────────────────────────────────────────────────

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

main() {
  [[ $# -gt 0 ]] || usage 1
  local sub="$1"; shift
  # pnpm forwards a literal `--` separator before user args; skip it.
  if [[ "${1:-}" == "--" ]]; then shift; fi
  case "$sub" in
    redeploy)   cmd_redeploy "$@" ;;
    deploy)     cmd_deploy "$@" ;;
    logs)       cmd_logs "$@" ;;
    status)     cmd_status "$@" ;;
    vars)       cmd_vars "$@" ;;
    var-set)    cmd_var_set "$@" ;;
    var-unset)  cmd_var_unset "$@" ;;
    -h|--help|help) usage 0 ;;
    *) log "unknown subcommand: $sub"; usage 1 ;;
  esac
}

main "$@"
