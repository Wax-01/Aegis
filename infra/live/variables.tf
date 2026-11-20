variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "aws_endpoint_url" {
  description = "Endpoint del emulador AWS (Floci) visto desde donde corre Terraform. null = AWS real."
  type        = string
  default     = null
}

# --------------------------------------------------------------------- red / borde
variable "enable_nat_gateway" {
  type    = bool
  default = false
}

variable "enable_interface_endpoints" {
  type    = bool
  default = true
}

variable "api_endpoint_type" {
  description = "PRIVATE (AWS real, vía VPCE execute-api) o REGIONAL (emulador)."
  type        = string
  default     = "PRIVATE"
}

variable "use_vpc_link" {
  description = "API Gateway -> VPC Link -> NLB (AWS real). false: integración directa al NodePort (emulador)."
  type        = bool
  default     = true
}

variable "enable_k8s_privatelink" {
  type    = bool
  default = true
}

variable "k8s_node_host" {
  description = "Host del nodo Kubernetes alcanzable desde API Gateway cuando use_vpc_link = false."
  type        = string
  default     = "aegisvolt-control-plane"
}

# --------------------------------------------------------------------- compatibilidad emulador
variable "enable_metric_filters" {
  type    = bool
  default = true
}

variable "enable_alarms" {
  type    = bool
  default = true
}

variable "enable_api_access_logs" {
  type    = bool
  default = true
}

variable "enable_api_method_settings" {
  type    = bool
  default = true
}

variable "enable_point_in_time_recovery" {
  description = "Permite apagar PITR en emuladores que no lo soportan (prod lo pide por defecto)."
  type        = bool
  default     = true
}

# --------------------------------------------------------------------- Kubernetes
variable "create_eks" {
  description = "true en AWS real. En el emulador se usa un clúster kind local."
  type        = bool
  default     = false
}

variable "manage_kubernetes" {
  description = "Crear namespace/ConfigMap/Secret/NetworkPolicies del ambiente en el clúster."
  type        = bool
  default     = true
}

variable "kubeconfig_path" {
  type    = string
  default = "~/.kube/config"
}

variable "kube_context" {
  type    = string
  default = "kind-aegisvolt"
}

variable "cluster_aws_endpoint_url" {
  description = "Endpoint AWS visto desde los pods (Floci en la red docker de kind). null en AWS real."
  type        = string
  default     = null
}

variable "extra_cors_origins" {
  description = "Orígenes adicionales del frontend (p. ej. el dominio público en AWS real) para CORS y WebSocket"
  type        = list(string)
  default     = []
}
