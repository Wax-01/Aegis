output "environment" {
  value = local.env
}

output "state_object_key" {
  description = "Llave del tfstate de este workspace dentro del bucket versionado."
  value       = "env:/${terraform.workspace}/aegisvolt/terraform.tfstate"
}

output "vpc_id" {
  value = module.network.vpc_id
}

output "private_subnet_ids" {
  value = module.network.private_subnet_ids
}

output "vpc_endpoints" {
  value = merge(module.network.gateway_endpoint_ids, module.network.interface_endpoint_ids, {
    k8s_privatelink = module.edge.k8s_vpce_id
  })
}

output "dynamodb_tables" {
  value = module.dynamodb.table_names
}

output "feature_flags_initial_state" {
  value = module.feature_flags.initial_state
}

output "log_groups" {
  value = module.observability.log_group_names
}

output "api_gateway" {
  value = {
    rest_api_id = module.edge.rest_api_id
    invoke_url  = module.edge.stage_invoke_url
    type        = var.api_endpoint_type
    vpc_link_id = module.edge.vpc_link_id
  }
}

output "k8s_namespace" {
  value = var.manage_kubernetes ? module.k8s_env[0].namespace : null
}

output "local_urls" {
  description = "URLs de la demo local (NodePorts publicados por kind)."
  value = {
    graphql  = "http://localhost:${local.cfg.gateway_node_port}/graphql"
    frontend = "http://localhost:${local.cfg.frontend_node_port}"
  }
}

output "admin_token" {
  value     = var.manage_kubernetes ? module.k8s_env[0].admin_token : null
  sensitive = true
}
