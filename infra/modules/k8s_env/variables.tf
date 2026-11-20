variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "aws_endpoint_url_in_cluster" {
  description = "Endpoint AWS visto desde los pods (Floci en la red de kind). null en AWS real."
  type        = string
  default     = null
}

variable "static_aws_credentials" {
  description = "true solo con el emulador. En AWS real se usa IRSA."
  type        = bool
  default     = false
}

variable "table_names" {
  type = map(string)
}

variable "log_group_prefix" {
  type = string
}

variable "rest_api_id" {
  type = string
}

variable "saga_step_delay_ms" {
  type    = number
  default = 0
}

variable "quota_cpu" {
  type    = string
  default = "4"
}

variable "quota_memory" {
  type    = string
  default = "4Gi"
}

variable "quota_pods" {
  type    = string
  default = "40"
}
