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
