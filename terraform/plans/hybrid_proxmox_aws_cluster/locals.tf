#  data "aws_caller_identity" "current" {}

locals {
  resource_basename = "${var.plan_version}-${var.owner}-${var.project}-${var.environment}-${var.region}"
  # aws_account       = data.aws_caller_identity.current.account_id
}
