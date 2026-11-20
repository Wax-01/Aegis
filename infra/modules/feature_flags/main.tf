# -----------------------------------------------------------------------------
# Estado INICIAL de las feature flags de este ambiente (declarado como código).
#
# `ignore_changes = [item]`: una vez creada, la flag se puede cambiar EN CALIENTE (CLI / mutación GraphQL)
# y el siguiente `terraform apply` NO la revierte. Así se demuestra "cambiar una flag en dev sin redesplegar"
# mientras prod mantiene su propio valor en su propia tabla.
# -----------------------------------------------------------------------------

resource "aws_dynamodb_table_item" "flag" {
  for_each = var.flags

  table_name = var.table_name
  hash_key   = "flag_key"

  item = jsonencode({
    flag_key    = { S = each.key }
    enabled     = { BOOL = each.value }
    description = { S = lookup(var.descriptions, each.key, each.key) }
    environment = { S = var.environment }
    updated_by  = { S = "terraform" }
  })

  lifecycle {
    ignore_changes = [item]
  }
}
