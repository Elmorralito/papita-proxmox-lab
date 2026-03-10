terraform {
  required_version = ">=1.6.5, <2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.28"
    }

    tailscale = {
      source  = "tailscale/tailscale"
      version = "~> 0.13"
    }

    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7.0"
    }

    null = {
      source  = "hashicorp/null"
      version = "~> 3.2.3"
    }

    external = {
      source  = "hashicorp/external"
      version = "~> 2.3.5" # Specify your desired version constraint here
    }

    local = {
      source  = "hashicorp/local"
      version = "~> 2.5.3"
    }

    random = {
      source  = "hashicorp/random"
      version = "~> 3.8.1"
    }
  }

}

provider "aws" {
  region  = var.region
  profile = var.profile

  default_tags {
    tags = {
      Project     = "${var.owner}-${var.project}"
      Version     = var.plan_version
      Environment = var.environment
      Region      = var.region
      Company     = var.owner
      Owner       = var.owner
    }
  }
}

# provider "tailscale" {
#   api_key = var.tailscale_api_key
#   tailnet = var.tailscale_tailnet
# }

module "aws" {
  source                     = "./aws"
  resource_basename          = local.resource_basename
  plan_version               = var.plan_version
  region                     = var.region
  kms_key_arn                = var.kms_key_arn
  create_vpc                 = var.aws_create_vpc
  vpc_name                   = var.aws_vpc_name
  vpc_cidr                   = var.aws_vpc_cidr
  vpc_id                     = var.aws_vpc_id
  availability_zones         = var.availability_zones
  private_subnet_cidrs       = var.aws_private_subnet_cidrs
  private_subnet_ids         = var.aws_private_subnet_ids
  tailscale_cidr_blocks      = var.tailscale_cidr_blocks
  efs_performance_mode       = var.efs_performance_mode
  efs_throughput_mode        = var.efs_throughput_mode
  efs_provisioned_throughput = var.efs_provisioned_throughput
  efs_transition_to_ia       = var.efs_transition_to_ia
  efs_root_path              = var.efs_root_path
  efs_posix_user_uid         = var.efs_posix_user_uid
  efs_posix_user_gid         = var.efs_posix_user_gid
  efs_backup_policy_status   = var.efs_backup_policy_status
  efs_enable_encryption      = true
  efs_enable_access_point    = true
}
