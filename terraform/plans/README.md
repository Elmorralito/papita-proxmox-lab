# plans

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | >=1.6.5, <2.0.0 |
| <a name="requirement_archive"></a> [archive](#requirement\_archive) | ~> 2.7.0 |
| <a name="requirement_aws"></a> [aws](#requirement\_aws) | ~> 5.28 |
| <a name="requirement_external"></a> [external](#requirement\_external) | ~> 2.3.5 |
| <a name="requirement_local"></a> [local](#requirement\_local) | ~> 2.5.3 |
| <a name="requirement_null"></a> [null](#requirement\_null) | ~> 3.2.3 |
| <a name="requirement_random"></a> [random](#requirement\_random) | ~> 3.8.1 |
| <a name="requirement_tailscale"></a> [tailscale](#requirement\_tailscale) | ~> 0.13 |

## Providers

No providers.

## Modules

| Name | Source | Version |
|------|--------|---------|
| <a name="module_hybrid_proxmox_aws_cluster"></a> [hybrid\_proxmox\_aws\_cluster](#module\_hybrid\_proxmox\_aws\_cluster) | ./hybrid_proxmox_aws_cluster | n/a |

## Resources

No resources.

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_aws_profile"></a> [aws\_profile](#input\_aws\_profile) | The AWS profile | `string` | `"default"` | no |
| <a name="input_aws_region"></a> [aws\_region](#input\_aws\_region) | The AWS region | `string` | n/a | yes |
| <a name="input_environment"></a> [environment](#input\_environment) | The environment name | `string` | n/a | yes |
| <a name="input_owner"></a> [owner](#input\_owner) | The owner of the project | `string` | n/a | yes |
| <a name="input_plan_specific_aws_security_params"></a> [plan\_specific\_aws\_security\_params](#input\_plan\_specific\_aws\_security\_params) | Plan specific security parameters | <pre>map(object({<br/>    aws_kms_key_arn                = optional(string, null)<br/>    aws_create_vpc                 = optional(bool, false)<br/>    aws_vpc_name                   = optional(string, null)<br/>    aws_vpc_cidr                   = optional(string, "10.0.0.0/16")<br/>    aws_vpc_id                     = optional(string, null)<br/>    availability_zones             = optional(list(string), ["a", "b", "c"])<br/>    aws_private_subnet_cidrs       = optional(list(string), [])<br/>    aws_private_subnet_ids         = optional(list(string), null)<br/>    tailscale_cidr_blocks          = optional(list(string), [])<br/>    aws_efs_performance_mode       = optional(string, "generalPurpose")<br/>    aws_efs_throughput_mode        = optional(string, "elastic")<br/>    aws_efs_provisioned_throughput = optional(number, null)<br/>    aws_efs_transition_to_ia       = optional(string, "AFTER_30_DAYS")<br/>    aws_efs_root_path              = optional(string, "/pve")<br/>    aws_efs_posix_user_uid         = optional(number, 1000)<br/>    aws_efs_posix_user_gid         = optional(number, 1000)<br/>    aws_efs_backup_policy_status   = optional(string, "ENABLED")<br/>  }))</pre> | n/a | yes |

## Outputs

No outputs.
<!-- END_TF_DOCS -->
