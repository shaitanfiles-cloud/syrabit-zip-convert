#!/usr/bin/env bash
# Task #606 — local "build, push, deploy" helper for Cloud Run.
#
# Use this when you don't want to wait for a Cloud Build trigger and just
# want to roll out a fresh revision from your machine. It builds the
# image with `gcloud builds submit` (so the build still happens in GCP,
# not on your laptop), then deploys to Cloud Run.
#
# Required env vars:
#   PROJECT_ID            GCP project (e.g. syrabit-prod)
#   REGION                e.g. asia-south1
#   AR_REPO               Artifact Registry repo (e.g. syrabit)
#   SERVICE               Cloud Run service name (e.g. syrabit-backend)
#   IMAGE                 Image name within the repo (default: backend)
#   RUNTIME_SA            Cloud Run runtime service account email
#   SECRETS               Comma-separated KEY=SECRET_NAME:VERSION pairs
#                         (mirror the Railway env, see CLOUDRUN-DEPLOY.md)
#
# Optional env vars (with defaults):
#   MIN_INSTANCES=1   MAX_INSTANCES=10   CONCURRENCY=80
#   CPU=2             MEMORY=2Gi          TIMEOUT=300
#
# Usage:
#   PROJECT_ID=syrabit-prod REGION=asia-south1 AR_REPO=syrabit \
#   SERVICE=syrabit-backend RUNTIME_SA=syrabit-backend@syrabit-prod.iam.gserviceaccount.com \
#   SECRETS=MONGO_URL=mongo-url:latest,JWT_SECRET=jwt-secret:latest \
#   ./scripts/deploy_cloud_run.sh

set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID is required}"
: "${REGION:?REGION is required}"
: "${AR_REPO:?AR_REPO is required}"
: "${SERVICE:?SERVICE is required}"
: "${RUNTIME_SA:?RUNTIME_SA is required}"
: "${SECRETS:?SECRETS is required (comma-separated KEY=NAME:VERSION pairs)}"

IMAGE="${IMAGE:-backend}"
MIN_INSTANCES="${MIN_INSTANCES:-1}"
MAX_INSTANCES="${MAX_INSTANCES:-10}"
CONCURRENCY="${CONCURRENCY:-80}"
CPU="${CPU:-2}"
MEMORY="${MEMORY:-2Gi}"
TIMEOUT="${TIMEOUT:-300}"

SHA="$(git rev-parse --short=10 HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S)"
IMG="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${IMAGE}:${SHA}"
LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${IMAGE}:latest"

cd "$(dirname "$0")/.."

echo ">> Building ${IMG} via Cloud Build…"
gcloud builds submit \
  --project="${PROJECT_ID}" \
  --tag="${IMG}" \
  --gcs-log-dir="gs://${PROJECT_ID}_cloudbuild/logs" \
  .

# Tag the same digest as :latest so cache-from is useful next time.
gcloud artifacts docker tags add \
  --project="${PROJECT_ID}" \
  "${IMG}" "${LATEST}" || true

echo ">> Deploying revision to Cloud Run service ${SERVICE} in ${REGION}…"
gcloud run deploy "${SERVICE}" \
  --project="${PROJECT_ID}" \
  --image="${IMG}" \
  --region="${REGION}" \
  --platform=managed \
  --port=8080 \
  --min-instances="${MIN_INSTANCES}" \
  --max-instances="${MAX_INSTANCES}" \
  --concurrency="${CONCURRENCY}" \
  --cpu="${CPU}" \
  --memory="${MEMORY}" \
  --timeout="${TIMEOUT}" \
  --cpu-boost \
  --execution-environment=gen2 \
  --allow-unauthenticated \
  --ingress=all \
  --service-account="${RUNTIME_SA}" \
  --set-env-vars=PORT=8080,LOG_LEVEL=warning,GUNICORN_WORKERS=2 \
  --update-secrets="${SECRETS}"

URL="$(gcloud run services describe "${SERVICE}" --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"
echo ">> Deployed: ${URL}"
echo ">> Health check:"
curl -fsS -H "X-Origin-Auth: ${ORIGIN_SHARED_SECRET:-}" "${URL}/api/health" || true
echo
echo ">> To roll back: gcloud run services update-traffic ${SERVICE} --region=${REGION} --to-revisions=<previous-revision>=100"
