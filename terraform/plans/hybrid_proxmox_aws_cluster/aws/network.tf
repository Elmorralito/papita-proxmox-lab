# ─── Data: Availability zones (used when creating VPC) ─────────────
data "aws_availability_zones" "available" {
  count = var.create_vpc ? 1 : 0

  state = "available"
}

# ─── VPC (only when create_vpc is true) ───────────────────────────
resource "aws_vpc" "this" {
  count = var.create_vpc ? 1 : 0

  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = coalesce(var.vpc_name, "${var.resource_basename}-vpc")
  }

  lifecycle {
    precondition {
      condition     = !var.create_vpc || length(local.availability_zones_available) == length(local.requested_az_names)
      error_message = "One or more requested availability zones are not available in region ${var.region}. Requested: ${join(", ", local.requested_az_names)}. Available: ${join(", ", local.available_az_names)}."
    }
  }
}

# ─── Subnets (only when create_vpc is true) ───────────────

# Private Subnets (Internal-only); only in AZs that passed the available check
resource "aws_subnet" "private" {
  count = var.create_vpc ? length(local.availability_zones_available) : 0

  vpc_id            = local.vpc_id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, 8 + count.index)
  availability_zone = local.availability_zones_available[count.index]
  tags = {
    Name = "${var.resource_basename}-private-${count.index + 1}-${local.availability_zones_available[count.index]}"
  }
}

# ─── EFS security group ──────────────────────────────────────────
resource "aws_security_group" "efs_tailscale_sg" {
  name        = "${var.resource_basename}-efs-tailscale-sg"
  description = "Security group for the EFS file system"
  vpc_id      = local.vpc_id

  ingress {
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = var.tailscale_cidr_blocks
  }

  ingress {
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = local.private_subnet_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "efs_mount_target_sg" {
  name        = "${var.resource_basename}-efs-mount-target-sg"
  description = "Security group for EFS mount targets"
  vpc_id      = local.vpc_id

  ingress {
    description     = "NFS from VPC endpoint and Tailscale SG"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.efs_tailscale_sg.id]
  }

  ingress {
    description = "NFS from Tailscale CGNAT directly"
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = var.tailscale_cidr_blocks
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.resource_basename}-efs-mount-target-sg"
  }
}

# ─── VPC Endpoints ──────────────────────────────────────────────
resource "aws_vpc_endpoint" "efs_endpoint" {
  count = var.create_vpc ? 1 : 0

  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.region}.elasticfilesystem"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.efs_tailscale_sg.id]
  private_dns_enabled = true

  tags = {
    Name = "${var.resource_basename}-efs-endpoint"
  }
}
