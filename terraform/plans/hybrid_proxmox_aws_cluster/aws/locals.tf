# ─── Locals: resolved VPC and subnet IDs for use across the module ─
locals {
  # Full AZ names requested (region + suffix from variable)
  requested_az_names = [for s in var.availability_zones : "${var.region}${s}"]

  # Available AZs from the region (only when creating VPC)
  available_az_names = var.create_vpc ? data.aws_availability_zones.available[0].names : []

  # Requested AZs that are actually available; used for subnet placement when create_vpc is true
  availability_zones_available = var.create_vpc ? [for az in local.requested_az_names : az if contains(local.available_az_names, az)] : []

  vpc_id               = var.create_vpc ? aws_vpc.this[0].id : var.vpc_id
  private_subnet_cidrs = var.create_vpc ? aws_subnet.private[*].cidr_block : var.private_subnet_cidrs
  private_subnet_ids   = var.create_vpc ? aws_subnet.private[*].id : coalesce(var.private_subnet_ids, [])
}
