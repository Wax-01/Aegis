output "namespace" {
  value = kubernetes_namespace_v1.env.metadata[0].name
}

output "admin_token" {
  value     = random_password.admin_token.result
  sensitive = true
}
