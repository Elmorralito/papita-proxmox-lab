variable "project" {
  description = "The project name"
  type        = string
  default     = "hybrid-proxmox-aws-cluster"
  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project))
    error_message = "Project name must be in the format a-z0-9-."
  }
}

variable "environment" {
  description = "The environment name"
  type        = string
  validation {
    condition     = contains(["dev", "prod", "poc"], var.environment)
    error_message = "Environment name must be either dev or prod."
  }
}

variable "owner" {
  description = "The owner of the project"
  type        = string
}

variable "plan_version" {
  description = "The version of the project"
  type        = string
  validation {
    condition     = can(regex("^v[0-9]+$", var.plan_version))
    error_message = "Version must be in the format vX (e.g. v1)."
  }
}

variable "profile" {
  description = "The AWS profile"
  type        = string
  default     = "default"
}

variable "region" {
  description = "The AWS region"
  type        = string
}

# --- Security & Networking Configuration ────────────────────────
variable "kms_key_arn" {
  description = "KMS key ARN for EFS encryption (null = AWS managed key)"
  type        = string
  default     = null
}

variable "aws_create_vpc" {
  description = "When true, create a new VPC and private subnets; when false, use existing aws_vpc_id and aws_private_subnet_ids"
  type        = bool
  default     = false
}

variable "aws_vpc_name" {
  description = "Name of the VPC (used when aws_create_vpc is true)"
  type        = string
  default     = null
}

variable "aws_vpc_cidr" {
  description = "CIDR block for the VPC (used when aws_create_vpc is true)"
  type        = string
  default     = "10.0.0.0/16"
}

variable "aws_vpc_id" {
  description = "ID of an existing VPC (required when aws_create_vpc is false)"
  type        = string
  default     = null
}

variable "availability_zones" {
  description = "Availability zone suffixes (e.g. [\"a\", \"b\", \"c\"]) when aws_create_vpc is true; full AZ = region + suffix."
  type        = list(string)
  default     = ["a", "b", "c"]
}

variable "aws_private_subnet_cidrs" {
  description = "When aws_create_vpc is false: CIDRs for EFS security group ingress. When true: ignored."
  type        = list(string)
  default     = []
}

variable "aws_private_subnet_ids" {
  description = "When aws_create_vpc is false: existing private subnet IDs for EFS mount targets."
  type        = list(string)
  default     = null
}

variable "tailscale_cidr_blocks" {
  description = "CIDR blocks for Tailscale (allowed to access EFS on port 2049)."
  type        = list(string)
  default     = []
}

# --- EFS Configuration ───────────────────────────────────────────
variable "efs_performance_mode" {
  description = "EFS performance mode: generalPurpose or maxIO"
  type        = string
  default     = "generalPurpose"
  validation {
    condition     = contains(["generalPurpose", "maxIO"], var.efs_performance_mode)
    error_message = "Performance mode must be generalPurpose or maxIO."
  }
}

variable "efs_throughput_mode" {
  description = "EFS throughput mode: bursting, provisioned, or elastic"
  type        = string
  default     = "elastic"
  validation {
    condition     = contains(["bursting", "provisioned", "elastic"], var.efs_throughput_mode)
    error_message = "Throughput mode must be bursting, provisioned, or elastic."
  }
}

variable "efs_provisioned_throughput" {
  description = "Provisioned throughput in MiB/s (only when throughput_mode=provisioned)"
  type        = number
  default     = null
}

variable "efs_transition_to_ia" {
  description = "Lifecycle policy: days before transitioning to IA storage"
  type        = string
  default     = "AFTER_30_DAYS"
  validation {
    condition = contains([
      "AFTER_7_DAYS", "AFTER_14_DAYS", "AFTER_30_DAYS",
      "AFTER_60_DAYS", "AFTER_90_DAYS"
    ], var.efs_transition_to_ia)
    error_message = "Invalid lifecycle transition value."
  }
}

variable "efs_root_path" {
  description = "The root path for the Proxmox file system"
  type        = string
  default     = "/pve"
}

variable "efs_posix_user_uid" {
  description = "The UID of the POSIX user"
  type        = number
  default     = 1000
}

variable "efs_posix_user_gid" {
  description = "The GID of the POSIX user"
  type        = number
  default     = 1000
}

variable "efs_backup_policy_status" {
  description = "The status of the EFS backup policy (e.g. ENABLED, DISABLED)"
  type        = string
  default     = "ENABLED"
  validation {
    condition     = contains(["ENABLED", "DISABLED"], var.efs_backup_policy_status)
    error_message = "Backup policy status must be ENABLED or DISABLED."
  }
}

# --- Tailscale Configuration ──────────────────────────────────────

# variable "tailscale_api_key" {
#   description = "The Tailscale API key"
#   type        = string
#   default     = null
# }

# variable "tailscale_tailnet" {
#   description = "The Tailscale tailnet"
#   type        = string
#   default     = null
# }
