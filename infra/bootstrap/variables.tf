variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "aws_endpoint_url" {
  description = "Endpoint del emulador (Floci). null = AWS real."
  type        = string
  default     = null
}

variable "state_bucket_name" {
  description = "Bucket del estado remoto (en AWS real debe ser globalmente único)."
  type        = string
  default     = "aegisvolt-tfstate"
}

variable "lock_table_name" {
  type    = string
  default = "aegisvolt-terraform-locks"
}

variable "enable_state_lifecycle" {
  type    = bool
  default = true
}

variable "noncurrent_version_retention_days" {
  type    = number
  default = 90
}

variable "noncurrent_versions_to_keep" {
  type    = number
  default = 50
}
