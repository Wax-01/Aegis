provider "aws" {
  region = var.aws_region

  # Floci: credenciales ficticias + endpoints locales. AWS real: aws_endpoint_url = null => defaults.
  access_key                  = local.emulator ? "test" : null
  secret_key                  = local.emulator ? "test" : null
  skip_credentials_validation = local.emulator
  skip_metadata_api_check     = local.emulator
  skip_requesting_account_id  = local.emulator
  s3_use_path_style           = local.emulator

  endpoints {
    apigateway  = var.aws_endpoint_url
    autoscaling = var.aws_endpoint_url
    cloudwatch  = var.aws_endpoint_url
    dynamodb    = var.aws_endpoint_url
    ec2         = var.aws_endpoint_url
    eks         = var.aws_endpoint_url
    elbv2       = var.aws_endpoint_url
    iam         = var.aws_endpoint_url
    logs        = var.aws_endpoint_url
    s3          = var.aws_endpoint_url
    sts         = var.aws_endpoint_url
  }

  default_tags {
    tags = {
      Project     = local.project
      Environment = local.env
      Workspace   = terraform.workspace
      ManagedBy   = "terraform"
    }
  }
}

provider "kubernetes" {
  config_path    = var.manage_kubernetes ? pathexpand(var.kubeconfig_path) : null
  config_context = var.manage_kubernetes ? var.kube_context : null
}
