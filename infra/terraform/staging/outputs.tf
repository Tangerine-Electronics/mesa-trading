output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "judge_url" {
  value = google_cloud_run_v2_service.judge.uri
}

output "bucket" {
  value = google_storage_bucket.data.name
}

output "tick_job" {
  value = google_cloud_run_v2_job.tick.name
}

output "report_job" {
  value = google_cloud_run_v2_job.report.name
}
