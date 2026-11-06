#!/usr/bin/env bash
# Despliega la mesa a staging. Auth: Workload Identity, sin llaves JSON.
# No llama a `gcloud services enable` si las APIs ya están habilitadas:
# sa-forge-staging no tiene serviceusage.services.enable, y enable falla
# aunque el servicio ya esté encendido.
set -euo pipefail

STAGING_PROJECT="tangerine-staging-510423"
EXPECTED_SA="sa-forge-staging@${STAGING_PROJECT}.iam.gserviceaccount.com"

REQUIRED_SERVICES=(
  run.googleapis.com
  cloudscheduler.googleapis.com
  secretmanager.googleapis.com
  storage.googleapis.com
  artifactregistry.googleapis.com
  iam.googleapis.com
)

refuse_unless_staging_project() {
  local project="$1"
  if [[ "${project}" != "${STAGING_PROJECT}" ]]; then
    echo "ERROR: PROJECT_ID=${project} no es staging (${STAGING_PROJECT}). Este script no aplica otro proyecto." >&2
    exit 1
  fi
}

account_from_credentials_file() {
  local path="$1"
  python3 - "${path}" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
email = str(data.get("client_email") or "").strip()
if email:
    print(email)
    raise SystemExit(0)
url = str(data.get("service_account_impersonation_url") or "")
match = re.search(r"serviceAccounts/([^:/]+)", url)
if match:
    print(match.group(1))
PY
}

active_account() {
  local lines=()
  local line
  while IFS= read -r line; do
    if [[ -n "${line}" ]]; then
      lines+=("${line}")
    fi
  done < <(gcloud auth list --filter='status:ACTIVE' --format='value(account)' || true)

  if [[ ${#lines[@]} -eq 0 ]]; then
    local creds="${CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE:-${GOOGLE_APPLICATION_CREDENTIALS:-${GOOGLE_GHA_CREDS_PATH:-}}}"
    if [[ -n "${creds}" && -f "${creds}" ]]; then
      account_from_credentials_file "${creds}" || true
    fi
    return 0
  fi

  local joined="${lines[0]}"
  local extra
  for extra in "${lines[@]:1}"; do
    joined+=",${extra}"
  done
  printf '%s\n' "${joined}"
}

refuse_unless_forge_sa() {
  if [[ -n "${DEPLOYER_SA:-}" && "${DEPLOYER_SA}" != "${EXPECTED_SA}" ]]; then
    echo "ERROR: DEPLOYER_SA=${DEPLOYER_SA} no es ${EXPECTED_SA}." >&2
    exit 1
  fi
  local account
  account="$(active_account)"
  account="${account//$'\r'/}"
  if [[ "${account}" != "${EXPECTED_SA}" ]]; then
    echo "ERROR: hay que aplicar como ${EXPECTED_SA}. Cuenta activa: ${account:-ninguna}." >&2
    exit 1
  fi
}

missing_services() {
  local enabled="$1"
  local svc
  for svc in "${REQUIRED_SERVICES[@]}"; do
    if ! printf '%s\n' "${enabled}" | grep -qxF -- "${svc}"; then
      printf '%s\n' "${svc}"
    fi
  done
}

print_owner_enable() {
  local project="$1"
  shift
  {
    echo "Un Owner de ${project} debe ejecutar:"
    printf 'gcloud services enable'
    local svc
    for svc in "$@"; do
      printf ' %s' "${svc}"
    done
    printf ' --project %s\n' "${project}"
  } >&2
}

main() {
  local project="${GCP_PROJECT:-${STAGING_PROJECT}}"
  local region="${GCP_REGION:-northamerica-south1}"
  local tf_bucket="${STAGING_PROJECT}-mesa-trading-tfstate"
  local image_name="${region}-docker.pkg.dev/${project}/mesa-trading/mesa-trading"
  local sha root image
  sha="$(git rev-parse --short HEAD)"
  image="${image_name}:${sha}"
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

  refuse_unless_staging_project "${project}"
  refuse_unless_forge_sa

  gcloud config set project "${project}"

  local enabled
  if ! enabled="$(gcloud services list --enabled --project "${project}" --format='value(config.name)' --quiet)"; then
    echo "ERROR: no se pudo listar las APIs de ${project}." >&2
    print_owner_enable "${project}" "${REQUIRED_SERVICES[@]}"
    exit 1
  fi

  local missing=()
  local svc
  while IFS= read -r svc; do
    if [[ -n "${svc}" ]]; then
      missing+=("${svc}")
    fi
  done < <(missing_services "${enabled}")

  local manage_project_services="true"
  if [[ ${#missing[@]} -eq 0 ]]; then
    manage_project_services="false"
    echo "Las APIs requeridas ya están habilitadas. No se llama a gcloud services enable y Terraform no administra google_project_service."
  else
    echo "Faltan APIs: ${missing[*]}"
    if ! gcloud services enable "${missing[@]}" --project "${project}" --quiet; then
      echo "ERROR: ${EXPECTED_SA} no pudo habilitar APIs (hace falta serviceusage.services.enable)." >&2
      print_owner_enable "${project}" "${missing[@]}"
      exit 1
    fi
  fi

  if ! gcloud storage buckets describe "gs://${tf_bucket}" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://${tf_bucket}" \
      --project "${project}" \
      --location "${region}" \
      --uniform-bucket-level-access \
      --public-access-prevention
    gcloud storage buckets update "gs://${tf_bucket}" --versioning
  fi

  local tf_vars=(
    -var "image=${image}"
    -var "git_sha=${sha}"
    -var "project_id=${project}"
    -var "region=${region}"
    -var "manage_project_services=${manage_project_services}"
  )
  local apply_targets=(-target=google_artifact_registry_repository.app)
  if [[ "${manage_project_services}" == "true" ]]; then
    apply_targets=(-target=google_project_service.services "${apply_targets[@]}")
  fi

  cd "${root}/infra/terraform/staging"
  terraform init -input=false
  terraform apply -input=false -auto-approve "${apply_targets[@]}" "${tf_vars[@]}"

  gcloud auth configure-docker "${region}-docker.pkg.dev" --quiet
  docker build -t "${image}" "${root}"
  docker push "${image}"

  # deletion_protection se lee del state, no del config pendiente. Con el
  # default true, un servicio tainted se destruye en este apply y el provider
  # rechaza el destroy antes de guardar false. Quitamos el taint para publicar
  # la revisión nueva y dejar el flag en false; un replace posterior sí puede.
  for addr in google_cloud_run_v2_service.api google_cloud_run_v2_service.judge; do
    terraform untaint "${addr}" || true
  done

  # judge.uri sale vacío del state si el servicio falló o venía tainted. Planear
  # el job tick en ese mismo apply guarda MESA_JUDGE_URL como "" y el provider
  # de Google rechaza el plan cuando la URI aparece a mitad del apply. Primero
  # los servicios (y nada que lea judge.uri); el apply completo ya la conoce.
  local service_targets=(
    -target=google_cloud_run_v2_service.api
    -target=google_cloud_run_v2_service.judge
  )
  terraform apply -input=false -auto-approve "${service_targets[@]}" "${tf_vars[@]}"

  terraform apply -input=false -auto-approve "${tf_vars[@]}"

  local code
  set +e
  terraform plan -input=false -detailed-exitcode "${tf_vars[@]}" -out=plan.tfplan
  code=$?
  set -e
  if [[ "${code}" -eq 2 ]]; then
    echo "plan con cambios despues del apply" >&2
    exit 2
  fi
  if [[ "${code}" -ne 0 ]]; then
    exit "${code}"
  fi

  echo "IMAGE=${image}"
  terraform output -raw api_url
  echo
  ensure_live_cycles "${project}" "${region}"
}

ensure_live_cycles() {
  local project="$1"
  local region="$2"
  local bucket="mesa-trading-staging-data"
  echo "Scheduler (us-south1):"
  gcloud scheduler jobs describe mesa-trading-tick-every-5m \
    --project="${project}" \
    --location=us-south1 \
    --format='yaml(name,state,schedule,timeZone,httpTarget.uri,httpTarget.oauthToken.serviceAccountEmail)'
  local state
  state="$(gcloud scheduler jobs describe mesa-trading-tick-every-5m --project="${project}" --location=us-south1 --format='value(state)')"
  if [[ "${state}" != "ENABLED" ]]; then
    gcloud scheduler jobs resume mesa-trading-tick-every-5m --project="${project}" --location=us-south1
  fi
  local have
  have="$(gcloud storage ls --recursive "gs://${bucket}/logs/**" --project="${project}" 2>/dev/null | grep -c '\.jsonl$' || true)"
  have="${have:-0}"
  echo "jsonl en gs://${bucket}/logs/: ${have}"
  if [[ "${have}" -ge 12 ]]; then
    return 0
  fi
  local need=$((12 - have))
  local i cid
  for i in $(seq 1 "${need}"); do
    cid="$(date -u +%Y%m%dT%H%M%SZ)-$(printf '%02d' "${i}")"
    echo "ejecutando ciclo ${cid}"
    gcloud run jobs execute mesa-trading-tick \
      --project="${project}" \
      --region="${region}" \
      --wait \
      --args="--cycle-id,${cid}"
    if [[ "${MESA_CYCLE_PAUSE_S:-12}" != "0" ]]; then
      sleep "${MESA_CYCLE_PAUSE_S:-12}"
    fi
  done
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
