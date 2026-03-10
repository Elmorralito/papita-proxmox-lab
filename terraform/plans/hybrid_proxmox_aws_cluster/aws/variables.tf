variable "resource_basename" {
  description = "The basename of the resource"
  type        = string
}

# variable account_id {
#   description = "The AWS account ID"
#   type        = string
# }

variable "region" {
  description = "The AWS region"
  type        = string
}

variable "plan_version" {
  description = "The version of the project"
  type        = string
}

variable "availability_zones" {
  description = "Availability zones for the VPC"
  type        = list(string)
}

# --- Security & Networking Configuration ────────────────────────
variable "kms_key_arn" {
  description = "KMS key ARN for EFS encryption (null = AWS managed key)"
  type        = string
}

variable "create_vpc" {
  description = "When true, create a new VPC and private subnets; when false, use existing vpc_id and private_subnet_ids"
  type        = bool
}

variable "vpc_name" {
  description = "Name of the VPC (used when create_vpc is true)"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC (used when create_vpc is true)"
  type        = string
}

variable "vpc_id" {
  description = "ID of an existing VPC (required when create_vpc is false)"
  type        = string
}

variable "private_subnet_cidrs" {
  description = "When create_vpc is false: CIDRs used for EFS security group ingress. When create_vpc is true: ignored (private subnets derived from vpc_cidr and availability_zones)."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "When create_vpc is false: list of existing private subnet IDs for EFS mount targets. When create_vpc is true: ignored."
  type        = list(string)
}

variable "tailscale_cidr_blocks" {
  description = "CIDR blocks for Tailscale (allowed to access EFS on port 2049)."
  type        = list(string)
}

# --- EFS Configuration ───────────────────────────────────────────
variable "efs_performance_mode" {
  description = "EFS performance mode: generalPurpose or maxIO"
  type        = string
}

variable "efs_throughput_mode" {
  description = "EFS throughput mode: bursting, provisioned, or elastic"
  type        = string
}

variable "efs_provisioned_throughput" {
  description = "Provisioned throughput in MiB/s (only when throughput_mode=provisioned)"
  type        = number
}

variable "efs_transition_to_ia" {
  description = "Lifecycle policy: days before transitioning to IA storage"
  type        = string
}

variable "efs_enable_encryption" {
  description = "Enable EFS encryption at rest"
  type        = bool
}

variable "efs_enable_access_point" {
  description = "Enable EFS Access Points for granular access control"
  type        = bool
}

variable "efs_root_path" {
  description = "The root path for the Proxmox file system"
  type        = string
}

variable "efs_posix_user_uid" {
  description = "The UID of the POSIX user"
  type        = number
}

variable "efs_posix_user_gid" {
  description = "The GID of the POSIX user"
  type        = number
}

variable "efs_backup_policy_status" {
  description = "The status of the EFS backup policy"
  type        = string
}
