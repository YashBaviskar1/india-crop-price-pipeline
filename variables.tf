variable "creds" {
  description = "credentials to access the GCP project"
  default     = "/home/yashbaviskar/Desktop/Projects/india-crop-pipeline/creds/india-price-crop-4f158b946fed.json"

}



variable "project_id" {
  description = "GCP Project ID"
  type        = string

}

variable "region_name" {
  description = "Name of the region"
  type        = string
  default     = "asia-south1"
}

variable "location" {
  description = "Location of the Resource"
  default     = "ASIA-SOUTH1"
}


variable "raw_bucket_name" {
  description = "Name of raw data bucket"
  type        = string
  default     = "agmarknet-raw-bucket"
}

variable "processed_bucket_name" {
  description = "Name of processed data bucket"
  type        = string
  default     = "agmarknet-processed-bucket"
}


variable "dataset_id" {
  description = "Name of the DataWareHouse"
  type        = string
  default     = "crop_prices_dwh"
}