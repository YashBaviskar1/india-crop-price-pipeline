provider "google" {
  credentials = file(var.creds)
  project     = var.project_id
  region      = var.region_name
}

resource "google_project_service" "services" {
  project = var.project_id
  for_each = toset([
    "storage.googleapis.com",
    "bigquery.googleapis.com",
    "compute.googleapis.com"
  ])
  service            = each.key
  disable_on_destroy = false
}

resource "google_storage_bucket" "raw_bucket" {
  depends_on                  = [google_project_service.services]
  name                        = var.raw_bucket_name
  location                    = var.location
  force_destroy               = true
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = 90
    }

    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }
}

resource "google_storage_bucket" "processed_bucket" {
  depends_on                  = [google_project_service.services]
  name                        = var.processed_bucket_name
  location                    = var.location
  force_destroy               = true
  uniform_bucket_level_access = true
}

resource "google_bigquery_dataset" "crop_prices" {
  depends_on  = [google_project_service.services]
  dataset_id  = var.dataset_id
  location    = var.region_name
  description = "India crop mandi price data warehouse — Agmarknet source"

  delete_contents_on_destroy = true
}

resource "google_service_account" "pipeline_sa" {
  depends_on   = [google_project_service.services]
  account_id   = "crop-pipeline-sa"
  display_name = "Crop Pipeline Service Account"
  description  = "Used by Kestra and local PySpark to access GCS and BigQuery"
}

resource "google_project_iam_member" "sa_roles" {
  project = var.project_id
  for_each = toset([
    "roles/storage.admin",
    "roles/bigquery.admin",
  ])
  role   = each.key
  member = "serviceAccount:${google_service_account.pipeline_sa.email}"
}