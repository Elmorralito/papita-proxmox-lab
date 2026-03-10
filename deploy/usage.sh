#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091
# Usage message for toolkit.sh. Source from toolkit.sh after utils.sh and after
# setting LIBS_INPUT_PATH and LIBS_OUTPUT_PATH. Uses GREEN_TEXT, NC_TEXT from
# utils.sh if already set.

[[ -z "${GREEN_TEXT:-}" ]] && GREEN_TEXT='\033[0;32m'
[[ -z "${NC_TEXT:-}" ]] && NC_TEXT='\033[0m'

usage_toolkit() {
  echo -e "${GREEN_TEXT}Usage:${NC_TEXT} $0 ACTION -e {dev|prod} [OPTIONS]"
  cat << EOF

  ACTION (required, position 1):
    build       Build all library wheels from libs/
    devsync     Build wheels and sync into local dev environment (pip install)
    test        Build wheels and run pytest with coverage
    terraform   Deploy infrastructure via Terraform (same as deploy)
    deploy      Deploy infrastructure via Terraform
    none        No action; useful with --pre-commit only

  Environment (required):
    -e, --env, --environment   Target environment: dev or prod

  Paths:
    -lip, --libs-input-path   Libraries source directory. Default: ${LIBS_INPUT_PATH}
    -lop, --libs-output-path  Output directory for built wheels. Default: ${LIBS_OUTPUT_PATH}

  Terraform:
    -ta, --terraform-action   Terraform subcommand (default: deploy)

  AWS:
    -p, --profile, --aws-profile   AWS profile (default: default)
    -r, --region, --aws-region    AWS region
    -asl, --aws-sso, --aws-sso-login   Log in via AWS SSO
    -aml, --aws-mfa, --aws-mfa-login   Log in via AWS MFA
    -amdev, --aws-mfa-device      MFA device ARN
    -amdr, --aws-mfa-duration     MFA session duration (seconds)
    -amrn, --aws-mfa-role-session-name   MFA role session name
    -amara, --aws-mfa-assume-role-arn   MFA assume-role ARN
    -amf, --aws-mfa-force         Force MFA re-authentication

  Other:
    --pre-commit   Run pre-commit hooks before the chosen action
    -h, --help     Show this message

EOF
  exit 1
}
