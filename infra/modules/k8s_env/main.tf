# -----------------------------------------------------------------------------
# Aislamiento del ambiente DENTRO del clúster: namespace aegisvolt-<env>, ConfigMap con los outputs de la
# infraestructura (nombres de tablas, prefijo de logs, endpoint AWS), credenciales, cuotas y NetworkPolicies
# que impiden que pods de un ambiente llamen a servicios de otro.
# Los manifiestos de aplicación (deploy/k8s) consumen este ConfigMap: Terraform -> Kubernetes sin copiar valores.
# -----------------------------------------------------------------------------

locals {
  namespace = "${var.project}-${var.environment}"
  labels = {
    "app.kubernetes.io/part-of"    = var.project
    "aegisvolt.io/environment"     = var.environment
    "app.kubernetes.io/managed-by" = "terraform"
  }
}

resource "kubernetes_namespace_v1" "env" {
  metadata {
    name   = local.namespace
    labels = local.labels
  }
}

resource "kubernetes_config_map_v1" "infra" {
  metadata {
    name      = "aegisvolt-infra"
    namespace = kubernetes_namespace_v1.env.metadata[0].name
    labels    = local.labels
  }

  data = merge(
    {
      AEGIS_ENV               = var.environment
      AWS_REGION              = var.aws_region
      LOG_GROUP_PREFIX        = var.log_group_prefix
      API_GATEWAY_ID          = var.rest_api_id
      CLOUDWATCH_LOGS_ENABLED = "true"
      SAGA_STEP_DELAY_MS      = tostring(var.saga_step_delay_ms)
    },
    var.aws_endpoint_url_in_cluster != null ? { AWS_ENDPOINT_URL = var.aws_endpoint_url_in_cluster } : {},
    { for k, v in var.table_names : "TABLE_${upper(replace(k, "-", "_"))}" => v }
  )
}

resource "random_password" "admin_token" {
  length  = 32
  special = false
}

resource "kubernetes_secret_v1" "app" {
  metadata {
    name      = "aegisvolt-app"
    namespace = kubernetes_namespace_v1.env.metadata[0].name
    labels    = local.labels
  }

  # En AWS real las credenciales NO van aquí: los pods usan IRSA (ServiceAccount -> rol IAM).
  data = merge(
    { ADMIN_TOKEN = random_password.admin_token.result },
    var.static_aws_credentials ? { AWS_ACCESS_KEY_ID = "test", AWS_SECRET_ACCESS_KEY = "test" } : {}
  )
}

resource "kubernetes_resource_quota_v1" "env" {
  metadata {
    name      = "aegisvolt-quota"
    namespace = kubernetes_namespace_v1.env.metadata[0].name
  }
  spec {
    hard = {
      "requests.cpu"    = var.quota_cpu
      "requests.memory" = var.quota_memory
      pods              = var.quota_pods
    }
  }
}

resource "kubernetes_limit_range_v1" "env" {
  metadata {
    name      = "aegisvolt-defaults"
    namespace = kubernetes_namespace_v1.env.metadata[0].name
  }
  spec {
    limit {
      type = "Container"
      default_request = {
        cpu    = "50m"
        memory = "96Mi"
      }
      default = {
        cpu    = "500m"
        memory = "384Mi"
      }
    }
  }
}

# --- NetworkPolicies: deny-all de entrada + permitir dentro del namespace + borde (gateway/frontend)
resource "kubernetes_network_policy_v1" "default_deny" {
  metadata {
    name      = "default-deny-ingress"
    namespace = kubernetes_namespace_v1.env.metadata[0].name
  }
  spec {
    pod_selector {}
    policy_types = ["Ingress"]
  }
}

resource "kubernetes_network_policy_v1" "same_namespace" {
  metadata {
    name      = "allow-same-namespace"
    namespace = kubernetes_namespace_v1.env.metadata[0].name
  }
  spec {
    pod_selector {}
    ingress {
      from {
        pod_selector {}
      }
    }
    policy_types = ["Ingress"]
  }
}

resource "kubernetes_network_policy_v1" "edge" {
  metadata {
    name      = "allow-edge-to-gateway-and-frontend"
    namespace = kubernetes_namespace_v1.env.metadata[0].name
  }
  spec {
    pod_selector {
      match_expressions {
        key      = "app"
        operator = "In"
        values   = ["graphql-gateway", "frontend"]
      }
    }
    ingress {}
    policy_types = ["Ingress"]
  }
}
