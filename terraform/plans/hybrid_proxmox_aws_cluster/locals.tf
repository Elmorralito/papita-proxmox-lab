#  data "aws_caller_identity" "current" {}

locals {
  resource_basename = "${var.owner}-${var.project}-${var.environment}-${var.region}-${var.plan_version}"
  # aws_account       = data.aws_caller_identity.current.account_id
}
