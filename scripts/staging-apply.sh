#!/usr/bin/env bash
# Despliega la mesa a staging. Auth: Workload Identity, sin llaves JSON.
set -euo pipefail

PROJECT="${GCP_PROJECT:-tangerine-staging-510423}"
REGION="${GCP_REGION:-northamerica-south1}"
TF_BUCKET="tangerine-staging-510423-mesa-trading-tfstate"
REPO="mesa-trading"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/mesa-trading"
SHA="$(git rev-parse --short HEAD)"
IMAGE="${IMAGE_NAME}:${SHA}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

gcloud config set project "${PROJECT}"

gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  --project "${PROJECT}"

if ! gcloud storage buckets describe "gs://${TF_BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${TF_BUCKET}" \
    --project "${PROJECT}" \
    --location "${REGION}" \
    --uniform-bucket-level-access \
    --public-access-prevention
  gcloud storage buckets update "gs://${TF_BUCKET}" --versioning
fi

cd "${ROOT}/infra/terraform/staging"
terraform init -input=false
terraform apply -input=false -auto-approve \
  -target=google_project_service.services \
  -target=google_artifact_registry_repository.app \
  -var "image=${IMAGE}" \
  -var "git_sha=${SHA}"

gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker build -t "${IMAGE}" "${ROOT}"
docker push "${IMAGE}"

terraform apply -input=false -auto-approve \
  -var "image=${IMAGE}" \
  -var "git_sha=${SHA}"

terraform plan -input=false -detailed-exitcode \
  -var "image=${IMAGE}" \
  -var "git_sha=${SHA}" \
  -out=plan.tfplan || {
    code=$?
    if [ "${code}" -eq 2 ]; then
      echo "plan con cambios despues del apply" >&2
      exit 2
    fi
    exit "${code}"
  }

echo "IMAGE=${IMAGE}"
terraform output -raw api_url
