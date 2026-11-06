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

variable "image" {
  type = string
}

variable "git_sha" {
  type    = string
  default = "dev"
}

locals {
  labels = {
    env        = "staging"
    app        = "mesa-trading"
    managed_by = "terraform"
  }
}
