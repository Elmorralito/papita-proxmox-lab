data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "tailscale_router_role" {
  name               = "${var.resource_basename}-tailscale-router-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
  description        = "Minimal role for Tailscale subnet router - SSM only, no EFS IAM"

}

# SSM only — for remote management. No EFS permissions attached.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.tailscale_router.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "tailscale_router_profile" {
  name = "${var.resource_basename}-tailscale-router-profile"
  role = aws_iam_role.tailscale_router_role.name
}
