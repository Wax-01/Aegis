variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "services" {
  type = list(string)
  default = [
    "station-reservation-service",
    "billing-wallet-service",
    "energy-dispatch-service",
    "graphql-gateway",
  ]
}

variable "retention_days" {
  type = number
}

variable "enable_metric_filters" {
  type    = bool
  default = true
}

variable "enable_alarms" {
  type    = bool
  default = true
}
