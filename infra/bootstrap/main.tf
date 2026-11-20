# -----------------------------------------------------------------------------
# BOOTSTRAP — recursos de "nivel cuenta" que deben existir ANTES del backend remoto
#
#   * Bucket S3 del estado remoto con VERSIONING ENABLED (backups históricos de cada tfstate)
#   * Tabla DynamoDB de locks (evita dos `terraform apply` simultáneos sobre el mismo workspace)
#
# Este root module usa estado LOCAL a propósito (problema del huevo y la gallina: no puede guardar su
# estado en un bucket que él mismo crea). Se ejecuta una sola vez por cuenta/emulador.
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "tfstate" {
  bucket        = var.state_bucket_name
  force_destroy = false

  tags = {
    Name    = var.state_bucket_name
    Purpose = "terraform-remote-state"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Requisito del proyecto: cada `terraform apply` crea una NUEVA VERSIÓN del objeto
# env:/<workspace>/aegisvolt/terraform.tfstate; las anteriores quedan como versiones no actuales.
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Retención de backups: se conservan las últimas N versiones no actuales y se expiran las más viejas.
resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  count  = var.enable_state_lifecycle ? 1 : 0
  bucket = aws_s3_bucket.tfstate.id

  rule {
    id     = "retain-state-history"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days           = var.noncurrent_version_retention_days
      newer_noncurrent_versions = var.noncurrent_versions_to_keep
    }
  }

  depends_on = [aws_s3_bucket_versioning.tfstate]
}

resource "aws_dynamodb_table" "locks" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Name    = var.lock_table_name
    Purpose = "terraform-state-locking"
  }
}
