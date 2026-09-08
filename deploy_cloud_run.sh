#!/usr/bin/env bash
set -e

# Ensure gcloud CLI is in PATH
export PATH="$PATH:$HOME/google-cloud-sdk/bin:/opt/homebrew/bin:/usr/local/bin"

# ==============================================================================
# 🚀 One-Click Google Cloud Run Deployment Script for CXAS Slot-Filling Visualizer
# ==============================================================================
# Usage:
#   ./deploy_cloud_run.sh [PROJECT_ID] [REGION] [AGENT_PATH] [AGENT_NAME]
#
# Example:
#   ./deploy_cloud_run.sh rising-field-487920-k9 us-central1 "../schwab_cashiering" "Cashiering"
# ==============================================================================

PROJECT_ID="${1:-gbot-test-080}"
REGION="${2:-us-central1}"
AGENT_PATH="${3:-../schwab_cashiering}"
AGENT_NAME="${4:-Cashiering}"
SERVICE_NAME="cxas-slot-visualizer"

echo "============================================================"
echo "📦 Packaging CXAS Agent from: ${AGENT_PATH}"
echo "🤖 Target Subagent          : ${AGENT_NAME}"
echo "☁️  Deploying to Cloud Run   : ${SERVICE_NAME} (${PROJECT_ID} / ${REGION})"
echo "============================================================"

# Stage the target CXAS agent into ./cxas_agent for the container build
rm -rf ./cxas_agent
cp -r "${AGENT_PATH}" ./cxas_agent

# Deploy directly from source to Cloud Run
gcloud run deploy "${SERVICE_NAME}" \
  --source . \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --allow-unauthenticated \
  --set-env-vars="AGENT_NAME=${AGENT_NAME}" \
  --command="python3" \
  --args="server.py,--app-dir,/app/cxas_agent,--agent,${AGENT_NAME}"

# Grant IAM Invoker access to Google Workspace domain users
echo "🔐 Granting Cloud Run Invoker role to domain:google.com..."
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --member="domain:google.com" \
  --role="roles/run.invoker" || true

# Clean up temporary staging folder
rm -rf ./cxas_agent

echo "============================================================"
echo "✅ Deployment complete!"
echo ""
echo "💡 Because corporate GCP projects block public unauthenticated access (allUsers),"
echo "   run this command to open the live Cloud Run container in your browser:"
echo ""
echo "   gcloud run services proxy ${SERVICE_NAME} --project=${PROJECT_ID} --region=${REGION} --port=8088"
echo ""
echo "   Then open: http://localhost:8088"
echo "============================================================"
