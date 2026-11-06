"""El apply de staging no habilita APIs que ya están encendidas."""

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "staging-apply.sh"
STAGING = "tangerine-staging-510423"
SA = f"sa-forge-staging@{STAGING}.iam.gserviceaccount.com"
REQUIRED = (
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
)

GCLOUD = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${GCLOUD_LOG}"
if [[ "$1" == "services" && "$2" == "list" ]]; then
  if [[ "${GCLOUD_LIST_EXIT:-0}" != "0" ]]; then
    echo "list denied" >&2
    exit "${GCLOUD_LIST_EXIT}"
  fi
  printf '%s\\n' "${GCLOUD_ENABLED}"
  exit 0
fi
if [[ "$1" == "services" && "$2" == "enable" ]]; then
  if [[ "${GCLOUD_ENABLE_EXIT:-0}" != "0" ]]; then
    echo "enable denied" >&2
    exit "${GCLOUD_ENABLE_EXIT}"
  fi
  exit 0
fi
if [[ "$1" == "auth" && "$2" == "list" ]]; then
  if [[ "${GCLOUD_ACCOUNT}" != "__none__" ]]; then
    printf '%s\\n' "${GCLOUD_ACCOUNT}"
  fi
  exit 0
fi
exit 0
"""

TERRAFORM = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${TERRAFORM_LOG}"
if [[ "$1" == "output" ]]; then
  printf '%s\\n' "https://mesa-trading-api.example.run.app"
fi
exit 0
"""

DOCKER = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${DOCKER_LOG}"
exit 0
"""


def _write_bin(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("gcloud", GCLOUD), ("terraform", TERRAFORM), ("docker", DOCKER)):
        path = bindir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    return bindir


def _run(
    tmp_path: Path,
    *,
    project: str = STAGING,
    account: str = SA,
    enabled: str | None = None,
    enable_exit: int = 0,
    list_exit: int = 0,
    creds: Path | None = None,
    deployer_sa: str | None = SA,
):
    bindir = _write_bin(tmp_path)
    env = os.environ.copy()
    for key in (
        "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_GHA_CREDS_PATH",
        "DEPLOYER_SA",
    ):
        env.pop(key, None)
    env.update(
        {
            "PATH": f"{bindir}{os.pathsep}{env.get('PATH', '')}",
            "GCP_PROJECT": project,
            "GCP_REGION": "northamerica-south1",
            "GCLOUD_LOG": str(tmp_path / "gcloud.log"),
            "TERRAFORM_LOG": str(tmp_path / "terraform.log"),
            "DOCKER_LOG": str(tmp_path / "docker.log"),
            "GCLOUD_ACCOUNT": account,
            "GCLOUD_ENABLED": "\n".join(REQUIRED) if enabled is None else enabled,
            "GCLOUD_ENABLE_EXIT": str(enable_exit),
            "GCLOUD_LIST_EXIT": str(list_exit),
        }
    )
    if deployer_sa is not None:
        env["DEPLOYER_SA"] = deployer_sa
    if creds is not None:
        env["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds)
        env["GCLOUD_ACCOUNT"] = "__none__"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _lines(tmp_path: Path, name: str) -> list[str]:
    path = tmp_path / name
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def test_required_apis_match_terraform():
    script = SCRIPT.read_text(encoding="utf-8")
    tf = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "infra" / "terraform" / "staging").glob("*.tf")
    )
    script_body = re.search(r"REQUIRED_SERVICES=\((.*?)\)", script, re.S).group(1)
    tf_body = re.search(
        r"var\.manage_project_services \? toset\(\[(.*?)\]\)",
        tf,
        re.S,
    ).group(1)
    script_services = set(re.findall(r"[a-z0-9.]+\.googleapis\.com", script_body))
    tf_services = set(re.findall(r"[a-z0-9.]+\.googleapis\.com", tf_body))
    assert script_services == tf_services == set(REQUIRED)


def test_untaints_cloud_run_services_before_full_apply(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    terraform = _lines(tmp_path, "terraform.log")
    untaint_api = terraform.index("untaint google_cloud_run_v2_service.api")
    untaint_judge = terraform.index("untaint google_cloud_run_v2_service.judge")
    applies = [i for i, line in enumerate(terraform) if line.startswith("apply ")]
    assert len(applies) == 3
    registry, services, full = (terraform[i] for i in applies)
    assert "-target=google_artifact_registry_repository.app" in registry
    assert "-target=google_cloud_run_v2_service" not in registry
    assert "-target=google_cloud_run_v2_service.api" in services
    assert "-target=google_cloud_run_v2_service.judge" in services
    assert "google_cloud_run_v2_job.tick" not in services
    assert "-target=" not in full
    assert applies[0] < untaint_api < applies[1] < applies[2]
    assert applies[0] < untaint_judge < applies[1]
    assert "google_cloud_run_v2_job" not in "\n".join(
        line for line in terraform if line.startswith("untaint ")
    )


def test_happy_path_skips_enable_and_does_not_manage_services(tmp_path):
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    gcloud = _lines(tmp_path, "gcloud.log")
    assert not [line for line in gcloud if line.startswith("services enable")]
    assert any(line.startswith("services list") for line in gcloud)
    terraform_lines = _lines(tmp_path, "terraform.log")
    terraform = "\n".join(terraform_lines)
    with_vars = [
        line for line in terraform_lines if "manage_project_services=false" in line
    ]
    assert len(with_vars) == 4
    assert sum(line.startswith("apply ") for line in with_vars) == 3
    assert sum(line.startswith("plan ") for line in with_vars) == 1
    assert "project_id=tangerine-staging-510423" in terraform
    assert "region=northamerica-south1" in terraform
    assert "scheduler_region" not in terraform
    assert "-target=google_project_service.services" not in terraform
    assert "-target=google_artifact_registry_repository.app" in terraform
    assert "Las APIs requeridas ya están habilitadas" in result.stdout


def test_missing_api_is_enabled_and_terraform_manages_services(tmp_path):
    enabled = "\n".join(svc for svc in REQUIRED if svc != "iam.googleapis.com")
    result = _run(tmp_path, enabled=enabled)
    assert result.returncode == 0, result.stderr
    enable = [line for line in _lines(tmp_path, "gcloud.log") if line.startswith("services enable")]
    assert enable == [
        "services enable iam.googleapis.com --project tangerine-staging-510423 --quiet"
    ]
    terraform = "\n".join(_lines(tmp_path, "terraform.log"))
    assert "manage_project_services=true" in terraform
    assert "-target=google_project_service.services" in terraform


def test_enable_failure_prints_owner_command_and_stops(tmp_path):
    enabled = "\n".join(
        svc for svc in REQUIRED if svc not in {"secretmanager.googleapis.com", "iam.googleapis.com"}
    )
    result = _run(tmp_path, enabled=enabled, enable_exit=1)
    assert result.returncode == 1
    assert "serviceusage.services.enable" in result.stderr
    assert (
        "gcloud services enable secretmanager.googleapis.com iam.googleapis.com "
        f"--project {STAGING}"
    ) in result.stderr
    assert _lines(tmp_path, "terraform.log") == []
    assert _lines(tmp_path, "docker.log") == []


def test_list_failure_prints_owner_command_for_every_required_api(tmp_path):
    result = _run(tmp_path, list_exit=1)
    assert result.returncode == 1
    command = "gcloud services enable " + " ".join(REQUIRED) + f" --project {STAGING}"
    assert command in result.stderr
    assert _lines(tmp_path, "terraform.log") == []


def test_refuses_non_staging_project(tmp_path):
    result = _run(tmp_path, project="tangerine-prod-000")
    assert result.returncode == 1
    assert "no es staging" in result.stderr
    assert _lines(tmp_path, "gcloud.log") == []


def test_refuses_other_account(tmp_path):
    result = _run(tmp_path, account="someone@example.com")
    assert result.returncode == 1
    assert SA in result.stderr
    assert "someone@example.com" in result.stderr
    assert not any(line.startswith("services list") for line in _lines(tmp_path, "gcloud.log"))


def test_refuses_mismatched_deployer_sa_env(tmp_path):
    result = _run(tmp_path, deployer_sa="other@example.com")
    assert result.returncode == 1
    assert "DEPLOYER_SA=other@example.com" in result.stderr
    assert _lines(tmp_path, "gcloud.log") == []


def test_wif_credential_file_counts_as_forge_sa(tmp_path):
    creds = tmp_path / "wif.json"
    creds.write_text(
        json.dumps(
            {
                "type": "external_account",
                "service_account_impersonation_url": (
                    "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
                    f"{SA}:generateAccessToken"
                ),
            }
        ),
        encoding="utf-8",
    )
    result = _run(tmp_path, creds=creds)
    assert result.returncode == 0, result.stderr
    assert not [
        line for line in _lines(tmp_path, "gcloud.log") if line.startswith("services enable")
    ]
