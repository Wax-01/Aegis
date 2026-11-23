# -----------------------------------------------------------------------------
# AegisVolt — stack de un ambiente. El ambiente lo determina EXCLUSIVAMENTE el workspace:
#   terraform workspace select dev|test|prod
# -----------------------------------------------------------------------------

module "network" {
  source = "../modules/network"

  project                    = local.project
  environment                = local.env
  aws_region                 = var.aws_region
  vpc_cidr                   = local.cfg.vpc_cidr
  enable_nat_gateway         = var.enable_nat_gateway
  enable_interface_endpoints = var.enable_interface_endpoints
}

module "dynamodb" {
  source = "../modules/dynamodb"

  project                = local.project
  environment            = local.env
  deletion_protection    = local.cfg.protect_data
  point_in_time_recovery = local.cfg.protect_data && var.enable_point_in_time_recovery
}

module "feature_flags" {
  source = "../modules/feature_flags"

  environment = local.env
  table_name  = module.dynamodb.feature_flags_table_name
  flags       = local.cfg.feature_flags
}

module "observability" {
  source = "../modules/observability"

  project               = local.project
  environment           = local.env
  retention_days        = local.cfg.log_retention_days
  enable_metric_filters = var.enable_metric_filters
  enable_alarms         = var.enable_alarms
}

module "eks" {
  source = "../modules/eks"
  count  = var.create_eks ? 1 : 0

  project                 = local.project
  environment             = local.env
  private_subnet_ids      = module.network.private_subnet_ids
  nodes_security_group_id = module.network.k8s_nodes_security_group_id
}

module "edge" {
  source = "../modules/edge"

  project                     = local.project
  environment                 = local.env
  vpc_id                      = module.network.vpc_id
  private_subnet_ids          = module.network.private_subnet_ids
  vpce_security_group_id      = module.network.vpce_security_group_id
  execute_api_vpce_id         = module.network.execute_api_endpoint_id
  api_endpoint_type           = var.api_endpoint_type
  use_vpc_link                = var.use_vpc_link
  direct_backend_url          = "http://${var.k8s_node_host}:${local.cfg.gateway_node_port}"
  gateway_node_port           = local.cfg.gateway_node_port
  node_autoscaling_group_name = var.create_eks ? module.eks[0].node_autoscaling_group_name : null
  enable_k8s_privatelink      = var.enable_k8s_privatelink
  enable_access_logs          = var.enable_api_access_logs
  access_log_group_arn        = module.observability.api_gateway_log_group_arn
  enable_method_settings      = var.enable_api_method_settings
  throttle_rate               = local.cfg.api_throttle_rate
  throttle_burst              = local.cfg.api_throttle_burst
}

module "k8s_env" {
  source = "../modules/k8s_env"
  count  = var.manage_kubernetes ? 1 : 0

  project                     = local.project
  environment                 = local.env
  aws_region                  = var.aws_region
  aws_endpoint_url_in_cluster = var.cluster_aws_endpoint_url
  static_aws_credentials      = local.emulator
  table_names                 = module.dynamodb.table_names
  log_group_prefix            = module.observability.log_group_prefix
  rest_api_id                 = module.edge.rest_api_id
  saga_step_delay_ms          = local.cfg.saga_step_delay_ms
  # Los 3 frontends: la consola de un ambiente LEE las flags de los otros (comparador). Escribir exige token.
  cors_origins = concat(
    flatten([for c in values(local.env_config) : [
      "http://localhost:${c.frontend_node_port}", "http://127.0.0.1:${c.frontend_node_port}",
    ]]),
    var.extra_cors_origins,
  )
}
