import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "infra" / "terraform" / "staging"


def _text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(ROOT.glob("*.tf")))


def test_a5_a27_a28_policy():
    text = _text()
    assert text.count('secret_id = "mesa-trading-jev-key"') == 1
    assert "google_secret_manager_secret_version" not in text
    assert "google_billing_budget" not in text
    assert "google_billing_account" not in text
    assert "google_organization_iam" not in text
    assert "google_project_iam" not in text
    assert 'role      = "roles/secretmanager.secretAccessor"' in text or 'role      = "roles/secretmanager.secretAccessor"' in text
    assert "secretmanager.secretAccessor" in text
    assert text.count("allUsers") == 1
    assert "google_cloud_run_v2_service_iam_member" in text and "api_public" in text
    assert "tick_invokes_judge" in text
    assert "mesa-trading-scheduler" in text
    assert text.count("google_cloud_run_v2_job_iam_member") == 2
    assert 'name             = "mesa-trading-tick-every-5m"' in text
    assert 'schedule         = "*/5 * * * *"' in text
    assert 'name             = "mesa-trading-report-daily"' in text
    assert 'schedule         = "0 7 * * *"' in text
    assert 'time_zone        = "America/Mexico_City"' in text
    assert 'default = "us-south1"' in text
    assert "matches_prefix = [\"logs/\"]" in text
    assert "age            = 90" in text
    assert 'env        = "staging"' in text
    assert 'app        = "mesa-trading"' in text
    assert 'managed_by = "terraform"' in text
    assert "mesa-trading-staging-data" in text
    assert "tangerine-staging-510423" in text
    assert "northamerica-south1" in text
    assert 'path = "/health"' in text
    assert "/healthz" not in text
    assert "mesa-trading-tick" in text
    assert "mesa-trading-report" in text
    assert "mesa-trading-judge" in text
    assert "mesa-trading-api" in text
    assert text.count("var.scheduler_region") == 2
    assert 'variable "manage_project_services"' in text
    assert re.search(
        r'variable "manage_project_services"[\s\S]*?default\s*=\s*false',
        text,
    )
    assert "var.manage_project_services ? toset([" in text
    assert ": toset([])" in text
    assert "disable_on_destroy = false" in text


def test_cloud_run_config_paths_and_startup_probe():
    text = _text()
    flat = " ".join(text.split())
    assert text.count('name  = "MESA_DESK_CONFIG"') == 4
    assert text.count('value = "/app/config/desk.yaml"') == 4
    assert text.count('name  = "MESA_PROMOTION_CONFIG"') == 1
    assert 'value = "/app/config/promotion.yaml"' in text
    assert text.count('name  = "MESA_FEES_CONFIG"') == 1
    assert 'value = "/app/config/fees.yaml"' in text
    assert text.count('name  = "MESA_POLICY_CONFIG"') == 1
    assert 'value = "/app/config/policy.yaml"' in text
    assert flat.count("initial_delay_seconds = 5") == 2
    assert flat.count("timeout_seconds = 5") == 2
    assert flat.count("period_seconds = 10") == 2
    assert flat.count("failure_threshold = 6") == 2
    assert "initial_delay_seconds = 0" not in flat
    assert "google_project_iam" not in text
    docker = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY config ./config" in docker
    assert "MESA_DESK_CONFIG=/app/config/desk.yaml" in docker
    assert "MESA_PROMOTION_CONFIG=/app/config/promotion.yaml" in docker
    assert "MESA_FEES_CONFIG=/app/config/fees.yaml" in docker
    assert "MESA_POLICY_CONFIG=/app/config/policy.yaml" in docker


def test_tick_job_depends_on_judge_service():
    """Tick reads judge.uri. The service has to exist before that job is planned."""
    text = _text()
    blocks = re.split(r'(?=^resource ")', text, flags=re.M)
    tick = next(
        block
        for block in blocks
        if block.startswith('resource "google_cloud_run_v2_job" "tick"')
    )
    assert 'name  = "MESA_JUDGE_URL"' in tick
    assert "google_cloud_run_v2_service.judge.uri" in tick
    assert re.search(
        r"depends_on\s*=\s*\[[^\]]*google_project_service\.services,\s*"
        r"google_cloud_run_v2_service\.judge[^\]]*\]",
        tick,
    )


def test_staging_cloud_run_can_be_replaced():
    """Provider 6.x defaults deletion_protection to true and refuses destroy."""
    text = _text()
    assert "deletion_protection = true" not in text
    blocks = re.split(r'(?=^resource ")', text, flags=re.M)
    protected = [
        block
        for block in blocks
        if block.startswith('resource "google_cloud_run_v2_service"')
        or block.startswith('resource "google_cloud_run_v2_job"')
    ]
    names = []
    for block in protected:
        header = block.split("{", 1)[0]
        names.append(header.strip())
        assert "deletion_protection = false" in block, header
    assert names == [
        'resource "google_cloud_run_v2_service" "judge"',
        'resource "google_cloud_run_v2_service" "api"',
        'resource "google_cloud_run_v2_job" "tick"',
        'resource "google_cloud_run_v2_job" "report"',
    ]
