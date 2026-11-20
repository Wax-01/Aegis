locals {
  project = "aegisvolt"

  # ---------------------------------------------------------------------------
  # Guardia de workspace: SOLO dev | test | prod. En `default` (o cualquier otro) el plan falla aquí
  # antes de crear nada, con un mensaje explícito.
  # ---------------------------------------------------------------------------
  allowed_workspaces = ["dev", "test", "prod"]
  env = (
    contains(local.allowed_workspaces, terraform.workspace)
    ? terraform.workspace
    : file("ERROR: workspace '${terraform.workspace}' no permitido. Ejecuta: terraform workspace select dev|test|prod")
  )

  emulator = var.aws_endpoint_url != null

  # ---------------------------------------------------------------------------
  # Parámetros por ambiente estático. Todo nombre de recurso incluye ${local.env} (= terraform.workspace).
  # ---------------------------------------------------------------------------
  env_config = {
    dev = {
      vpc_cidr           = "10.10.0.0/16"
      log_retention_days = 7
      api_throttle_rate  = 50
      api_throttle_burst = 100
      protect_data       = false
      gateway_node_port  = 30080
      frontend_node_port = 30090
      saga_step_delay_ms = 700
      feature_flags = {
        ENABLE_DYNAMIC_SURGE_PRICING    = true
        ENABLE_FAST_CHARGE_BOOST        = true
        SIMULATE_CHARGER_HARDWARE_FAULT = false
      }
    }
    test = {
      vpc_cidr           = "10.20.0.0/16"
      log_retention_days = 14
      api_throttle_rate  = 100
      api_throttle_burst = 200
      protect_data       = false
      gateway_node_port  = 30081
      frontend_node_port = 30091
      saga_step_delay_ms = 700
      feature_flags = {
        ENABLE_DYNAMIC_SURGE_PRICING    = true
        ENABLE_FAST_CHARGE_BOOST        = true
        SIMULATE_CHARGER_HARDWARE_FAULT = false
      }
    }
    prod = {
      vpc_cidr           = "10.30.0.0/16"
      log_retention_days = 30
      api_throttle_rate  = 200
      api_throttle_burst = 400
      protect_data       = true # deletion protection + PITR
      gateway_node_port  = 30082
      frontend_node_port = 30092
      saga_step_delay_ms = 0
      feature_flags = {
        ENABLE_DYNAMIC_SURGE_PRICING    = false
        ENABLE_FAST_CHARGE_BOOST        = false
        SIMULATE_CHARGER_HARDWARE_FAULT = false
      }
    }
  }

  cfg = local.env_config[local.env]
}
