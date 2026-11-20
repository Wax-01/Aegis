terraform {
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.30.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6.0"
    }
  }

  # Backend remoto S3 (configuración parcial: los valores vienen de backend/*.s3.tfbackend).
  # Con workspaces, el estado de cada ambiente queda en una llave DISTINTA del mismo bucket:
  #   env:/dev/aegisvolt/terraform.tfstate
  #   env:/test/aegisvolt/terraform.tfstate
  #   env:/prod/aegisvolt/terraform.tfstate
  # y el bucket tiene versioning => cada apply deja la versión anterior como backup recuperable.
  backend "s3" {}
}
