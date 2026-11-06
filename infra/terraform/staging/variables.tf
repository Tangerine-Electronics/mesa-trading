variable "project_id" {
  type    = string
  default = "tangerine-staging-510423"
}

variable "region" {
  type    = string
  default = "northamerica-south1"
}

variable "scheduler_region" {
  type    = string
  default = "us-south1"
}

variable "project_number" {
  type    = string
  default = "241478288591"
}

variable "image" {
  type = string
}

variable "git_sha" {
  type    = string
  default = "dev"
}

variable "manage_project_services" {
  description = "Si es true, este root crea google_project_service. En staging queda en false: las APIs ya están habilitadas y sa-forge-staging no puede llamar a serviceusage.services.enable."
  type        = bool
  default     = false
}

locals {
  labels = {
    env        = "staging"
    app        = "mesa-trading"
    managed_by = "terraform"
  }
}
