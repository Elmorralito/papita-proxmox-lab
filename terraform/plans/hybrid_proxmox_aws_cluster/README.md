# hybrid_proxmox_aws_cluster

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
| <a name="module_aws"></a> [aws](#module\_aws) | ./aws | n/a |

## Resources

No resources.

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_availability_zones"></a> [availability\_zones](#input\_availability\_zones) | Availability zone suffixes (e.g. ["a", "b", "c"]) when aws\_create\_vpc is true; full AZ = region + suffix. | `list(string)` | <pre>[<br/>  "a",<br/>  "b",<br/>  "c"<br/>]</pre> | no |
| <a name="input_aws_create_vpc"></a> [aws\_create\_vpc](#input\_aws\_create\_vpc) | When true, create a new VPC and private subnets; when false, use existing aws\_vpc\_id and aws\_private\_subnet\_ids | `bool` | `false` | no |
| <a name="input_aws_private_subnet_cidrs"></a> [aws\_private\_subnet\_cidrs](#input\_aws\_private\_subnet\_cidrs) | When aws\_create\_vpc is false: CIDRs for EFS security group ingress. When true: ignored. | `list(string)` | `[]` | no |
| <a name="input_aws_private_subnet_ids"></a> [aws\_private\_subnet\_ids](#input\_aws\_private\_subnet\_ids) | When aws\_create\_vpc is false: existing private subnet IDs for EFS mount targets. | `list(string)` | `null` | no |
| <a name="input_aws_vpc_cidr"></a> [aws\_vpc\_cidr](#input\_aws\_vpc\_cidr) | CIDR block for the VPC (used when aws\_create\_vpc is true) | `string` | `"10.0.0.0/16"` | no |
| <a name="input_aws_vpc_id"></a> [aws\_vpc\_id](#input\_aws\_vpc\_id) | ID of an existing VPC (required when aws\_create\_vpc is false) | `string` | `null` | no |
| <a name="input_aws_vpc_name"></a> [aws\_vpc\_name](#input\_aws\_vpc\_name) | Name of the VPC (used when aws\_create\_vpc is true) | `string` | `null` | no |
| <a name="input_efs_backup_policy_status"></a> [efs\_backup\_policy\_status](#input\_efs\_backup\_policy\_status) | The status of the EFS backup policy (e.g. ENABLED, DISABLED) | `string` | `"ENABLED"` | no |
| <a name="input_efs_performance_mode"></a> [efs\_performance\_mode](#input\_efs\_performance\_mode) | EFS performance mode: generalPurpose or maxIO | `string` | `"generalPurpose"` | no |
| <a name="input_efs_posix_user_gid"></a> [efs\_posix\_user\_gid](#input\_efs\_posix\_user\_gid) | The GID of the POSIX user | `number` | `1000` | no |
| <a name="input_efs_posix_user_uid"></a> [efs\_posix\_user\_uid](#input\_efs\_posix\_user\_uid) | The UID of the POSIX user | `number` | `1000` | no |
| <a name="input_efs_provisioned_throughput"></a> [efs\_provisioned\_throughput](#input\_efs\_provisioned\_throughput) | Provisioned throughput in MiB/s (only when throughput\_mode=provisioned) | `number` | `null` | no |
| <a name="input_efs_root_path"></a> [efs\_root\_path](#input\_efs\_root\_path) | The root path for the Proxmox file system | `string` | `"/pve"` | no |
| <a name="input_efs_throughput_mode"></a> [efs\_throughput\_mode](#input\_efs\_throughput\_mode) | EFS throughput mode: bursting, provisioned, or elastic | `string` | `"elastic"` | no |
| <a name="input_efs_transition_to_ia"></a> [efs\_transition\_to\_ia](#input\_efs\_transition\_to\_ia) | Lifecycle policy: days before transitioning to IA storage | `string` | `"AFTER_30_DAYS"` | no |
| <a name="input_environment"></a> [environment](#input\_environment) | The environment name | `string` | n/a | yes |
| <a name="input_kms_key_arn"></a> [kms\_key\_arn](#input\_kms\_key\_arn) | KMS key ARN for EFS encryption (null = AWS managed key) | `string` | `null` | no |
| <a name="input_owner"></a> [owner](#input\_owner) | The owner of the project | `string` | n/a | yes |
| <a name="input_plan_version"></a> [plan\_version](#input\_plan\_version) | The version of the project | `string` | n/a | yes |
| <a name="input_profile"></a> [profile](#input\_profile) | The AWS profile | `string` | `"default"` | no |
| <a name="input_project"></a> [project](#input\_project) | The project name | `string` | `"hybrid-proxmox-aws-cluster"` | no |
| <a name="input_region"></a> [region](#input\_region) | The AWS region | `string` | n/a | yes |
| <a name="input_tailscale_cidr_blocks"></a> [tailscale\_cidr\_blocks](#input\_tailscale\_cidr\_blocks) | CIDR blocks for Tailscale (allowed to access EFS on port 2049). | `list(string)` | `[]` | no |

## Outputs

No outputs.
<!-- END_TF_DOCS -->
