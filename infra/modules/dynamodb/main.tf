# -----------------------------------------------------------------------------
# Database-per-Service: cada microservicio es dueño EXCLUSIVO de su tabla, separada por ambiente.
#   aegisvolt-reservations-<env>   station-reservation-service
#   aegisvolt-billing-<env>        billing-wallet-service
#   aegisvolt-dispatch-<env>       energy-dispatch-service (TTL sobre la telemetría)
#   aegisvolt-sagas-<env>          graphql-gateway / orquestador (saga log + GSI por estado)
#   aegisvolt-feature-flags-<env>  estado de las feature flags de ESTE ambiente
# Como el nombre incluye el workspace, un apply en `test` jamás puede tocar las tablas de `prod`.
# -----------------------------------------------------------------------------

locals {
  single_table_services = {
    reservations = "station-reservation-service"
    billing      = "billing-wallet-service"
    dispatch     = "energy-dispatch-service"
  }
}

resource "aws_dynamodb_table" "service" {
  for_each = local.single_table_services

  name                        = "${var.project}-${each.key}-${var.environment}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "pk"
  range_key                   = "sk"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  dynamic "ttl" {
    for_each = each.key == "dispatch" ? [1] : []
    content {
      attribute_name = "expires_at"
      enabled        = true
    }
  }

  dynamic "point_in_time_recovery" {
    for_each = var.point_in_time_recovery ? [1] : []
    content {
      enabled = true
    }
  }

  server_side_encryption {
    enabled = var.server_side_encryption
  }

  tags = {
    Name         = "${var.project}-${each.key}-${var.environment}"
    OwnerService = each.value
  }
}

resource "aws_dynamodb_table" "sagas" {
  name                        = "${var.project}-sagas-${var.environment}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "saga_id"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "saga_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  # Prefect consulta este índice para encontrar sagas huérfanas (STARTED/COMPENSATING antiguas).
  global_secondary_index {
    name            = "status-created_at-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "status"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "created_at"
      key_type       = "RANGE"
    }
  }

  dynamic "point_in_time_recovery" {
    for_each = var.point_in_time_recovery ? [1] : []
    content {
      enabled = true
    }
  }

  server_side_encryption {
    enabled = var.server_side_encryption
  }

  tags = {
    Name         = "${var.project}-sagas-${var.environment}"
    OwnerService = "graphql-gateway"
  }
}

resource "aws_dynamodb_table" "feature_flags" {
  name                        = "${var.project}-feature-flags-${var.environment}"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "flag_key"
  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "flag_key"
    type = "S"
  }

  server_side_encryption {
    enabled = var.server_side_encryption
  }

  tags = {
    Name         = "${var.project}-feature-flags-${var.environment}"
    OwnerService = "platform"
  }
}
