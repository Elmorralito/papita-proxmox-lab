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

variable "aws_profile" {
  description = "The AWS profile"
  type        = string
  default     = "default"
}

variable "aws_region" {
  description = "The AWS region"
  type        = string
}

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

variable "plan_specific_aws_security_params" {
  description = "Plan specific security parameters"
  type = map(object({
    aws_kms_key_arn                = optional(string, null)
    aws_create_vpc                 = optional(bool, false)
    aws_vpc_name                   = optional(string, null)
    aws_vpc_cidr                   = optional(string, "10.0.0.0/16")
    aws_vpc_id                     = optional(string, null)
    availability_zones             = optional(list(string), ["a", "b", "c"])
    aws_private_subnet_cidrs       = optional(list(string), [])
    aws_private_subnet_ids         = optional(list(string), null)
    tailscale_cidr_blocks          = optional(list(string), [])
    aws_efs_performance_mode       = optional(string, "generalPurpose")
    aws_efs_throughput_mode        = optional(string, "elastic")
    aws_efs_provisioned_throughput = optional(number, null)
    aws_efs_transition_to_ia       = optional(string, "AFTER_30_DAYS")
    aws_efs_root_path              = optional(string, "/pve")
    aws_efs_posix_user_uid         = optional(number, 1000)
    aws_efs_posix_user_gid         = optional(number, 1000)
    aws_efs_backup_policy_status   = optional(string, "ENABLED")
  }))
}
