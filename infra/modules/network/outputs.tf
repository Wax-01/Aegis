output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "private_route_table_id" {
  value = aws_route_table.private.id
}

output "k8s_nodes_security_group_id" {
  value = aws_security_group.k8s_nodes.id
}

output "vpce_security_group_id" {
  value = aws_security_group.vpce.id
}

output "gateway_endpoint_ids" {
  value = {
    dynamodb = aws_vpc_endpoint.dynamodb.id
    s3       = aws_vpc_endpoint.s3.id
  }
}

output "interface_endpoint_ids" {
  value = { for k, v in aws_vpc_endpoint.interface : k => v.id }
}

output "execute_api_endpoint_id" {
  value = try(aws_vpc_endpoint.interface["execute-api"].id, null)
}
