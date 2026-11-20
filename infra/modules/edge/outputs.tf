output "rest_api_id" {
  value = aws_api_gateway_rest_api.this.id
}

output "stage_invoke_url" {
  value = aws_api_gateway_stage.this.invoke_url
}

output "nlb_dns_name" {
  value = aws_lb.k8s.dns_name
}

output "k8s_endpoint_service_name" {
  value = try(aws_vpc_endpoint_service.k8s[0].service_name, null)
}

output "k8s_vpce_id" {
  value = try(aws_vpc_endpoint.k8s[0].id, null)
}

output "vpc_link_id" {
  value = try(aws_api_gateway_vpc_link.k8s[0].id, null)
}
