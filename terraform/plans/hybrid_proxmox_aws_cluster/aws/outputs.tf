output "vpc_id" {
  value       = local.vpc_id
  description = "ID of the VPC (created or existing)"
}

output "private_subnet_ids" {
  value       = local.private_subnet_ids
  description = "IDs of the private subnets (created or existing)"
}

output "efs_file_system_id" {
  value       = aws_efs_file_system.efs.id
  description = "The ID of the EFS file system"
}

output "efs_file_system_arn" {
  value       = aws_efs_file_system.efs.arn
  description = "The ARN of the EFS file system"
}

output "efs_file_system_dns_name" {
  value       = aws_efs_file_system.efs.dns_name
  description = "The DNS name of the EFS file system"
}

output "efs_security_group_id" {
  value       = aws_security_group.efs_tailscale_sg.id
  description = "The ID of the EFS security group"
}

output "efs_security_group_arn" {
  value       = aws_security_group.efs_tailscale_sg.arn
  description = "The ARN of the EFS security group"
}
