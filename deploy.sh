#!/usr/bin/env bash
set -euo pipefail

# ─── Configuration ──────────────────────────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID env var}"
REGION="${GCP_REGION:-asia-south1}"
SERVICE_NAME="${SERVICE_NAME:-vexyl-tts}"
REPO_NAME="${REPO_NAME:-vexyl-tts}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}"

echo "=== VEXYL-TTS → Cloud Run ==="
echo "Project:  ${PROJECT_ID}"
echo "Region:   ${REGION}"
echo "Service:  ${SERVICE_NAME}"
echo "Image:    ${IMAGE}"
echo ""

# ─── Step 1: Enable required GCP APIs ──────────────────────────────────────────
echo "→ Step 1/4: Enabling GCP APIs..."
gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    --project="${PROJECT_ID}" --quiet

# ─── Step 2: Create Artifact Registry repo (if needed) ─────────────────────────
echo "→ Step 2/4: Ensuring Artifact Registry repo exists..."
gcloud artifacts repositories describe "${REPO_NAME}" \
    --location="${REGION}" \
    --project="${PROJECT_ID}" 2>/dev/null || \
gcloud artifacts repositories create "${REPO_NAME}" \
    --repository-format=docker \
    --location="${REGION}" \
    --project="${PROJECT_ID}" \
    --quiet
echo "  Repo: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"

# ─── Step 3: Build image with Cloud Build ──────────────────────────────────────
echo "→ Step 3/4: Building image with Cloud Build (this takes ~20-30 min)..."
gcloud builds submit . \
    --tag="${IMAGE}" \
    --machine-type=e2-highcpu-8 \
    --timeout=3600s \
    --project="${PROJECT_ID}" \
    --quiet

# ─── Step 4: Deploy to Cloud Run ───────────────────────────────────────────────
echo "→ Step 4/4: Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
    --image="${IMAGE}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --cpu=2 \
    --memory=8Gi \
    --timeout=3600 \
    --concurrency=50 \
    --min-instances=0 \
    --max-instances=5 \
    --cpu-boost \
    --session-affinity \
    --no-cpu-throttling \
    --startup-probe-path=/health \
    --startup-probe-initial-delay=0 \
    --startup-probe-period=10 \
    --startup-probe-failure-threshold=18 \
    --liveness-probe-path=/health \
    --allow-unauthenticated \
    --quiet

# ─── Done ──────────────────────────────────────────────────────────────────────
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format="value(status.url)")

echo ""
echo "=== Deployment complete ==="
echo "Service URL:    ${SERVICE_URL}"
echo "Health check:   curl ${SERVICE_URL}/health"
echo "WebSocket URL:  ${SERVICE_URL/https/wss}"
echo ""
echo "To use with VEXYL Voice Gateway, set:"
echo "  VEXYL_TTS_URL=${SERVICE_URL/https/wss}"
