resource "google_project_service" "services" {
  for_each = var.manage_project_services ? toset([
    "run.googleapis.com",
    "cloudscheduler.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
  ]) : toset([])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "tick" {
  account_id   = "mesa-trading-tick"
  display_name = "mesa-trading-tick"
}

resource "google_service_account" "judge" {
  account_id   = "mesa-trading-judge"
  display_name = "mesa-trading-judge"
}

resource "google_service_account" "api" {
  account_id   = "mesa-trading-api"
  display_name = "mesa-trading-api"
}

resource "google_service_account" "report" {
  account_id   = "mesa-trading-report"
  display_name = "mesa-trading-report"
}

resource "google_service_account" "scheduler" {
  account_id   = "mesa-trading-scheduler"
  display_name = "mesa-trading-scheduler"
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "mesa-trading"
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.services]
}

resource "google_storage_bucket" "data" {
  name                        = "mesa-trading-staging-data"
  location                    = var.region
  labels                      = local.labels
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age            = 90
      matches_prefix = ["logs/"]
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_storage_bucket_iam_member" "tick_writes" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.tick.email}"
}

resource "google_storage_bucket_iam_member" "report_writes" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.report.email}"
}

resource "google_storage_bucket_iam_member" "api_reads" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.api.email}"
}

resource "google_storage_bucket_iam_member" "judge_budget" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.judge.email}"
  condition {
    title       = "solo-budget"
    description = "El juez solo escribe el contador mensual de Jev"
    expression  = "resource.name.startsWith(\"projects/_/buckets/mesa-trading-staging-data/objects/budget/\")"
  }
}

resource "google_secret_manager_secret" "jev" {
  secret_id = "mesa-trading-jev-key"
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.services]
}

resource "google_secret_manager_secret_iam_member" "judge_reads_jev" {
  secret_id = google_secret_manager_secret.jev.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.judge.email}"
}

resource "google_cloud_run_v2_service" "judge" {
  name                = "mesa-trading-judge"
  location            = var.region
  labels              = local.labels
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.judge.email
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image   = var.image
      command = ["python", "-m", "mesa_trading.cli.judge"]
      env {
        name  = "GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "MESA_JEV_SECRET_ID"
        value = google_secret_manager_secret.jev.secret_id
      }
      env {
        name  = "MESA_BUCKET"
        value = google_storage_bucket.data.name
      }
      env {
        name  = "MESA_GIT_SHA"
        value = var.git_sha
      }
      env {
        name  = "MESA_DESK_CONFIG"
        value = "/app/config/desk.yaml"
      }
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      # Arranque en frío de uvicorn. Si el proceso revienta, /health nunca responde 200.
      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 5
        timeout_seconds       = 5
        period_seconds        = 10
        failure_threshold     = 6
      }
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_run_v2_service" "api" {
  name                = "mesa-trading-api"
  location            = var.region
  labels              = local.labels
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.api.email
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image   = var.image
      command = ["python", "-m", "mesa_trading.cli.api"]
      env {
        name  = "MESA_BUCKET"
        value = google_storage_bucket.data.name
      }
      env {
        name  = "MESA_GIT_SHA"
        value = var.git_sha
      }
      env {
        name  = "MESA_DESK_CONFIG"
        value = "/app/config/desk.yaml"
      }
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      # Arranque en frío de uvicorn. Si el proceso revienta, /health nunca responde 200.
      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 5
        timeout_seconds       = 5
        period_seconds        = 10
        failure_threshold     = 6
      }
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_run_v2_job" "tick" {
  name                = "mesa-trading-tick"
  location            = var.region
  labels              = local.labels
  deletion_protection = false

  template {
    parallelism = 1
    task_count  = 1
    template {
      timeout         = "120s"
      max_retries     = 0
      service_account = google_service_account.tick.email
      containers {
        image   = var.image
        command = ["python", "-m", "mesa_trading.cli.tick"]
        env {
          name  = "MESA_BUCKET"
          value = google_storage_bucket.data.name
        }
        env {
          name  = "MESA_JUDGE_URL"
          value = google_cloud_run_v2_service.judge.uri
        }
        env {
          name  = "MESA_GIT_SHA"
          value = var.git_sha
        }
        env {
          name  = "MESA_DESK_CONFIG"
          value = "/app/config/desk.yaml"
        }
        env {
          name  = "MESA_FEES_CONFIG"
          value = "/app/config/fees.yaml"
        }
        env {
          name  = "MESA_POLICY_CONFIG"
          value = "/app/config/policy.yaml"
        }
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
    }
  }

  depends_on = [google_project_service.services, google_cloud_run_v2_service.judge]
}

resource "google_cloud_run_v2_job" "report" {
  name                = "mesa-trading-report"
  location            = var.region
  labels              = local.labels
  deletion_protection = false

  template {
    parallelism = 1
    task_count  = 1
    template {
      timeout         = "180s"
      max_retries     = 0
      service_account = google_service_account.report.email
      containers {
        image   = var.image
        command = ["python", "-m", "mesa_trading.cli.report"]
        env {
          name  = "MESA_BUCKET"
          value = google_storage_bucket.data.name
        }
        env {
          name  = "MESA_GIT_SHA"
          value = var.git_sha
        }
        env {
          name  = "MESA_DESK_CONFIG"
          value = "/app/config/desk.yaml"
        }
        env {
          name  = "MESA_PROMOTION_CONFIG"
          value = "/app/config/promotion.yaml"
        }
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
    }
  }

  depends_on = [google_project_service.services]
}

resource "google_cloud_run_v2_service_iam_member" "tick_invokes_judge" {
  name     = google_cloud_run_v2_service.judge.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.tick.email}"
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_tick" {
  name     = google_cloud_run_v2_job.tick.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_report" {
  name     = google_cloud_run_v2_job.report.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "tick" {
  name             = "mesa-trading-tick-every-5m"
  region           = var.scheduler_region
  schedule         = "*/5 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "180s"

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/mesa-trading-tick:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_project_service.services, google_cloud_run_v2_job.tick]
}

resource "google_cloud_scheduler_job" "report" {
  name             = "mesa-trading-report-daily"
  region           = var.scheduler_region
  schedule         = "0 7 * * *"
  time_zone        = "America/Mexico_City"
  attempt_deadline = "300s"

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/mesa-trading-report:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_project_service.services, google_cloud_run_v2_job.report]
}
