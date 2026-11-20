variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "deletion_protection" {
  description = "Protección contra borrado (prod)."
  type        = bool
  default     = false
}

variable "point_in_time_recovery" {
  description = "Backups continuos PITR (prod)."
  type        = bool
  default     = false
}

variable "server_side_encryption" {
  type    = bool
  default = true
}
