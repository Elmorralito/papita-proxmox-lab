# ─── KMS Key for EFS Encryption ──────────────────────────────────
resource "aws_kms_key" "efs" {
  count = var.efs_enable_encryption && var.kms_key_arn == null ? 1 : 0

  description             = "KMS key for EFS encryption - Proxmox AWS Cluster"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = {
    Name = "${var.resource_basename}-efs-kms-${var.plan_version}"
  }
}

resource "aws_kms_alias" "efs" {
  count = var.efs_enable_encryption && var.kms_key_arn == null ? 1 : 0

  name          = "alias/${var.resource_basename}-efs-kms-alias-${var.plan_version}"
  target_key_id = aws_kms_key.efs[0].key_id
}

resource "random_id" "efs" {
  byte_length = 4
}

# ─── EFS File System ─────────────────────────────────────────────
resource "aws_efs_file_system" "efs" {
  creation_token   = "${var.resource_basename}-efs-${random_id.efs.hex}"
  performance_mode = var.efs_performance_mode
  throughput_mode  = var.efs_throughput_mode
  encrypted        = var.efs_enable_encryption

  # Conditionally set KMS key
  kms_key_id = var.efs_enable_encryption ? (
    var.kms_key_arn != null ? var.kms_key_arn : aws_kms_key.efs[0].arn
  ) : null

  # Provisioned throughput (only when mode = provisioned)
  provisioned_throughput_in_mibps = var.efs_throughput_mode == "provisioned" && var.efs_provisioned_throughput != null ? var.efs_provisioned_throughput : null

  # Lifecycle Management Policy
  lifecycle_policy {
    transition_to_ia = var.efs_transition_to_ia
  }

  tags = {
    Name        = "${var.resource_basename}-efs"
    Description = "Shared storage for Proxmox HA cluster"
  }
}

# ─── EFS Mount Targets (one per private subnet) ───────────────────
# When create_vpc: one per validated available AZ. When using existing VPC: one per private_subnet_ids.
resource "aws_efs_mount_target" "efs_mount_targets" {
  for_each = var.create_vpc ? { for i in range(length(local.availability_zones_available)) : tostring(i) => i } : { for sid in local.private_subnet_ids : sid => sid }

  file_system_id  = aws_efs_file_system.efs.id
  subnet_id       = var.create_vpc ? aws_subnet.private[each.value].id : each.key
  security_groups = [aws_security_group.efs_mount_target_sg.id]
}

# ─── EFS Access Point for Proxmox ────────────────────────────────
resource "aws_efs_access_point" "efs_access_point_proxmox" {
  count = var.efs_enable_access_point ? 1 : 0

  file_system_id = aws_efs_file_system.efs.id

  posix_user {
    uid = var.efs_posix_user_uid
    gid = var.efs_posix_user_gid
  }

  root_directory {
    path = var.efs_root_path != "" && var.efs_root_path != null ? var.efs_root_path : "/pve"
    creation_info {
      owner_uid   = var.efs_posix_user_uid
      owner_gid   = var.efs_posix_user_gid
      permissions = "0755"
    }
  }

  tags = {
    Name        = "${var.resource_basename}-proxmox-ap"
    Description = "Access point for Proxmox file system"
  }
}

# ─── EFS Backup Policy ───────────────────────────────────────────
resource "aws_efs_backup_policy" "efs_backup_policy_main" {
  file_system_id = aws_efs_file_system.efs.id

  backup_policy {
    status = var.efs_backup_policy_status
  }
}

# ─── EFS File System Policy ──────────────────────────────────────
# resource "aws_efs_file_system_policy" "efs_file_system_policy_main" {
#   file_system_id = aws_efs_file_system.efs.id

#   policy = jsonencode({
#     Version = "2012-10-17"
#     Statement = [
#       {
#         Sid    = "DenyInsecureTransport"
#         Effect = "Deny"
#         Principal = {
#           AWS = "*"
#         }
#         Action   = "*"
#         Resource = aws_efs_file_system.efs.arn
#         Condition = {
#           Bool = {
#             "aws:SecureTransport" = "false"
#           }
#         }
#       },
#       {
#         Sid    = "AllowProxmoxAccessOverTLS"
#         Effect = "Allow"
#         Principal = {
#           AWS = aws_iam_role.proxmox_efs_role.arn
#         }
#         Action = [
#           "elasticfilesystem:ClientMount",
#           "elasticfilesystem:ClientWrite",
#           "elasticfilesystem:ClientRootAccess"
#         ]
#         Resource = aws_efs_file_system.efs.arn
#         Condition = {
#           Bool = {
#             "aws:SecureTransport" = "true"
#           }
#         }
#       }
#     ]
#   })
# }
