
provider "google" {
  credentials = file(var.creds)
  project = var.project_id
  region  = var.region_name
}

resource "google_storage_bucket" "raw_bucket" {
  name          = var.raw_bucket_name
  location      = var.location
  force_destroy = true
}

resource "google_storage_bucket" "processed_bucket" {
  name          = var.processed_bucket_name
  location      = var.location
  force_destroy = true
}
