variable "project" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "availability_zones" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "az_count" {
  type    = number
  default = 2
}

variable "enable_nat_gateway" {
  description = "NAT para que los nodos privados descarguen imágenes. Apagado en el emulador."
  type        = bool
  default     = false
}

variable "enable_interface_endpoints" {
  type    = bool
  default = true
}

variable "interface_endpoint_services" {
  type    = list(string)
  default = ["execute-api", "logs", "monitoring", "sts"]
}
