# aws

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

| Name | Version |
|------|---------|
| <a name="provider_aws"></a> [aws](#provider\_aws) | 5.100.0 |
| <a name="provider_random"></a> [random](#provider\_random) | 3.8.1 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| [aws_efs_access_point.efs_access_point_proxmox](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/efs_access_point) | resource |
| [aws_efs_backup_policy.efs_backup_policy_main](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/efs_backup_policy) | resource |
| [aws_efs_file_system.efs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/efs_file_system) | resource |
| [aws_efs_mount_target.efs_mount_targets](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/efs_mount_target) | resource |
| [aws_kms_alias.efs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_alias) | resource |
| [aws_kms_key.efs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_key) | resource |
| [aws_security_group.efs_mount_target_sg](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_security_group.efs_tailscale_sg](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_subnet.private](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/subnet) | resource |
| [aws_vpc.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc) | resource |
| [aws_vpc_endpoint.efs_endpoint](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_endpoint) | resource |
| [random_id.efs](https://registry.terraform.io/providers/hashicorp/random/latest/docs/resources/id) | resource |
| [aws_availability_zones.available](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/availability_zones) | data source |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_availability_zones"></a> [availability\_zones](#input\_availability\_zones) | Availability zones for the VPC | `list(string)` | n/a | yes |
| <a name="input_create_vpc"></a> [create\_vpc](#input\_create\_vpc) | When true, create a new VPC and private subnets; when false, use existing vpc\_id and private\_subnet\_ids | `bool` | n/a | yes |
| <a name="input_efs_backup_policy_status"></a> [efs\_backup\_policy\_status](#input\_efs\_backup\_policy\_status) | The status of the EFS backup policy | `string` | n/a | yes |
| <a name="input_efs_enable_access_point"></a> [efs\_enable\_access\_point](#input\_efs\_enable\_access\_point) | Enable EFS Access Points for granular access control | `bool` | n/a | yes |
| <a name="input_efs_enable_encryption"></a> [efs\_enable\_encryption](#input\_efs\_enable\_encryption) | Enable EFS encryption at rest | `bool` | n/a | yes |
| <a name="input_efs_performance_mode"></a> [efs\_performance\_mode](#input\_efs\_performance\_mode) | EFS performance mode: generalPurpose or maxIO | `string` | n/a | yes |
| <a name="input_efs_posix_user_gid"></a> [efs\_posix\_user\_gid](#input\_efs\_posix\_user\_gid) | The GID of the POSIX user | `number` | n/a | yes |
| <a name="input_efs_posix_user_uid"></a> [efs\_posix\_user\_uid](#input\_efs\_posix\_user\_uid) | The UID of the POSIX user | `number` | n/a | yes |
| <a name="input_efs_provisioned_throughput"></a> [efs\_provisioned\_throughput](#input\_efs\_provisioned\_throughput) | Provisioned throughput in MiB/s (only when throughput\_mode=provisioned) | `number` | n/a | yes |
| <a name="input_efs_root_path"></a> [efs\_root\_path](#input\_efs\_root\_path) | The root path for the Proxmox file system | `string` | n/a | yes |
| <a name="input_efs_throughput_mode"></a> [efs\_throughput\_mode](#input\_efs\_throughput\_mode) | EFS throughput mode: bursting, provisioned, or elastic | `string` | n/a | yes |
| <a name="input_efs_transition_to_ia"></a> [efs\_transition\_to\_ia](#input\_efs\_transition\_to\_ia) | Lifecycle policy: days before transitioning to IA storage | `string` | n/a | yes |
| <a name="input_kms_key_arn"></a> [kms\_key\_arn](#input\_kms\_key\_arn) | KMS key ARN for EFS encryption (null = AWS managed key) | `string` | n/a | yes |
| <a name="input_plan_version"></a> [plan\_version](#input\_plan\_version) | The version of the project | `string` | n/a | yes |
| <a name="input_private_subnet_cidrs"></a> [private\_subnet\_cidrs](#input\_private\_subnet\_cidrs) | When create\_vpc is false: CIDRs used for EFS security group ingress. When create\_vpc is true: ignored (private subnets derived from vpc\_cidr and availability\_zones). | `list(string)` | n/a | yes |
| <a name="input_private_subnet_ids"></a> [private\_subnet\_ids](#input\_private\_subnet\_ids) | When create\_vpc is false: list of existing private subnet IDs for EFS mount targets. When create\_vpc is true: ignored. | `list(string)` | n/a | yes |
| <a name="input_region"></a> [region](#input\_region) | The AWS region | `string` | n/a | yes |
| <a name="input_resource_basename"></a> [resource\_basename](#input\_resource\_basename) | The basename of the resource | `string` | n/a | yes |
| <a name="input_tailscale_cidr_blocks"></a> [tailscale\_cidr\_blocks](#input\_tailscale\_cidr\_blocks) | CIDR blocks for Tailscale (allowed to access EFS on port 2049). | `list(string)` | n/a | yes |
| <a name="input_vpc_cidr"></a> [vpc\_cidr](#input\_vpc\_cidr) | CIDR block for the VPC (used when create\_vpc is true) | `string` | n/a | yes |
| <a name="input_vpc_id"></a> [vpc\_id](#input\_vpc\_id) | ID of an existing VPC (required when create\_vpc is false) | `string` | n/a | yes |
| <a name="input_vpc_name"></a> [vpc\_name](#input\_vpc\_name) | Name of the VPC (used when create\_vpc is true) | `string` | n/a | yes |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_efs_file_system_arn"></a> [efs\_file\_system\_arn](#output\_efs\_file\_system\_arn) | The ARN of the EFS file system |
| <a name="output_efs_file_system_dns_name"></a> [efs\_file\_system\_dns\_name](#output\_efs\_file\_system\_dns\_name) | The DNS name of the EFS file system |
| <a name="output_efs_file_system_id"></a> [efs\_file\_system\_id](#output\_efs\_file\_system\_id) | The ID of the EFS file system |
| <a name="output_efs_security_group_arn"></a> [efs\_security\_group\_arn](#output\_efs\_security\_group\_arn) | The ARN of the EFS security group |
| <a name="output_efs_security_group_id"></a> [efs\_security\_group\_id](#output\_efs\_security\_group\_id) | The ID of the EFS security group |
| <a name="output_private_subnet_ids"></a> [private\_subnet\_ids](#output\_private\_subnet\_ids) | IDs of the private subnets (created or existing) |
| <a name="output_vpc_id"></a> [vpc\_id](#output\_vpc\_id) | ID of the VPC (created or existing) |
<!-- END_TF_DOCS -->
