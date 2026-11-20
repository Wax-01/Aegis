terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

locals {
  emulator = var.aws_endpoint_url != null
}

provider "aws" {
  region = var.aws_region

  # Con Floci: credenciales ficticias y endpoints locales. Con AWS real: null => valores por defecto.
  access_key                  = local.emulator ? "test" : null
  secret_key                  = local.emulator ? "test" : null
  skip_credentials_validation = local.emulator
  skip_metadata_api_check     = local.emulator
  skip_requesting_account_id  = local.emulator
  s3_use_path_style           = local.emulator

  endpoints {
    s3       = var.aws_endpoint_url
    dynamodb = var.aws_endpoint_url
    sts      = var.aws_endpoint_url
    iam      = var.aws_endpoint_url
  }

  default_tags {
    tags = {
      Project   = "aegisvolt"
      ManagedBy = "terraform"
      Stack     = "bootstrap"
    }
  }
}
