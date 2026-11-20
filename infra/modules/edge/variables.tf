variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "vpce_security_group_id" {
  type = string
}

variable "execute_api_vpce_id" {
  description = "Interface VPCE execute-api (obligatorio si api_endpoint_type = PRIVATE)."
  type        = string
  default     = null
}

variable "api_endpoint_type" {
  description = "PRIVATE en AWS real; REGIONAL en el emulador (Floci no emula APIs privadas)."
  type        = string
  default     = "PRIVATE"

  validation {
    condition     = contains(["PRIVATE", "REGIONAL"], var.api_endpoint_type)
    error_message = "api_endpoint_type debe ser PRIVATE o REGIONAL."
  }
}

variable "use_vpc_link" {
  description = "Integración vía VPC Link -> NLB (AWS real). false = integración HTTP directa (emulador)."
  type        = bool
  default     = true
}

variable "direct_backend_url" {
  description = "URL base del graphql-gateway cuando use_vpc_link = false (p. ej. NodePort del clúster kind)."
  type        = string
  default     = ""
}

variable "gateway_node_port" {
  type = number
}

variable "node_autoscaling_group_name" {
  type    = string
  default = null
}

variable "enable_k8s_privatelink" {
  type    = bool
  default = true
}

variable "enable_access_logs" {
  type    = bool
  default = true
}

variable "access_log_group_arn" {
  type = string
}

variable "enable_method_settings" {
  type    = bool
  default = true
}

variable "throttle_rate" {
  type = number
}

variable "throttle_burst" {
  type = number
}
