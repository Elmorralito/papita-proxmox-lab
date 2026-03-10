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

  backend "s3" {

  }
}

locals {
  hybrid_proxmox_aws_cluster_params = lookup(var.plan_specific_aws_security_params, "hybrid_proxmox_aws_cluster", {
    aws_kms_key_arn                = null
    aws_create_vpc                 = false
    aws_vpc_name                   = null
    aws_vpc_cidr                   = "10.0.0.0/16"
    aws_vpc_id                     = null
    availability_zones             = ["a", "b", "c"]
    aws_private_subnet_cidrs       = []
    aws_private_subnet_ids         = null
    aws_efs_posix_user_uid         = 1000
    aws_efs_posix_user_gid         = 1000
    aws_efs_performance_mode       = "generalPurpose"
    aws_efs_throughput_mode        = "elastic"
    aws_efs_provisioned_throughput = null
    aws_efs_transition_to_ia       = "AFTER_30_DAYS"
    aws_efs_root_path              = "/pve"
    aws_efs_backup_policy_status   = "ENABLED"
    tailscale_cidr_blocks          = ["100.64.0.0/10"]
  })
}

module "hybrid_proxmox_aws_cluster" {
  source                     = "./hybrid_proxmox_aws_cluster"
  environment                = var.environment
  owner                      = var.owner
  plan_version               = "v2"
  profile                    = var.aws_profile
  region                     = var.aws_region
  kms_key_arn                = local.hybrid_proxmox_aws_cluster_params.aws_kms_key_arn
  aws_create_vpc             = local.hybrid_proxmox_aws_cluster_params.aws_create_vpc
  aws_vpc_name               = local.hybrid_proxmox_aws_cluster_params.aws_vpc_name
  aws_vpc_cidr               = local.hybrid_proxmox_aws_cluster_params.aws_vpc_cidr
  aws_vpc_id                 = local.hybrid_proxmox_aws_cluster_params.aws_vpc_id
  availability_zones         = local.hybrid_proxmox_aws_cluster_params.availability_zones
  aws_private_subnet_cidrs   = local.hybrid_proxmox_aws_cluster_params.aws_private_subnet_cidrs
  aws_private_subnet_ids     = local.hybrid_proxmox_aws_cluster_params.aws_private_subnet_ids
  efs_performance_mode       = local.hybrid_proxmox_aws_cluster_params.aws_efs_performance_mode
  efs_throughput_mode        = local.hybrid_proxmox_aws_cluster_params.aws_efs_throughput_mode
  efs_provisioned_throughput = local.hybrid_proxmox_aws_cluster_params.aws_efs_provisioned_throughput
  efs_transition_to_ia       = local.hybrid_proxmox_aws_cluster_params.aws_efs_transition_to_ia
  efs_root_path              = local.hybrid_proxmox_aws_cluster_params.aws_efs_root_path
  efs_posix_user_uid         = local.hybrid_proxmox_aws_cluster_params.aws_efs_posix_user_uid
  efs_posix_user_gid         = local.hybrid_proxmox_aws_cluster_params.aws_efs_posix_user_gid
  efs_backup_policy_status   = local.hybrid_proxmox_aws_cluster_params.aws_efs_backup_policy_status
  tailscale_cidr_blocks      = local.hybrid_proxmox_aws_cluster_params.tailscale_cidr_blocks
}
