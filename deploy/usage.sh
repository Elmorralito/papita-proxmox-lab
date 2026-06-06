#!/usr/bin/env bash
# shellcheck disable=SC1090,SC1091
# Usage message for toolkit.sh. Source from toolkit.sh after utils.sh and after
# setting LIBS_INPUT_PATH and LIBS_OUTPUT_PATH. Uses GREEN_TEXT, NC_TEXT from
# utils.sh if already set.

[[ -z "${GREEN_TEXT:-}" ]] && GREEN_TEXT='\033[0;32m'
[[ -z "${NC_TEXT:-}" ]] && NC_TEXT='\033[0m'

# Directory containing this file (project deploy/ locally, or remote .../deploy/). Used for setup-pve-node manual path.
PAPITA_DEPLOY_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"

usage_toolkit() {
  echo -e "${GREEN_TEXT}Usage:${NC_TEXT} $0 ACTION -e {dev|prod} [OPTIONS]"
  cat << EOM

  ACTION (required, position 1):
    build       Build all library wheels from libs/
    devsync     Build wheels and sync into local dev environment (pip install)
    test        Build wheels and run pytest with coverage
    terraform   Deploy infrastructure via Terraform (same as deploy)
    proxmox     Deploy infrastructure via Proxmox
    deploy_terraform      Same as action terraform
    deploy_proxmox      Same as action proxmox
    none        No action; useful with --pre-commit only

  Environment (required):
    -e, --env, --environment   Target environment: dev or prod

  Paths:
    -lip, --libs-input-path   Libraries source directory. Default: ${LIBS_INPUT_PATH}
    -lop, --libs-output-path  Output directory for built wheels. Default: ${LIBS_OUTPUT_PATH}

  Terraform:
    -ta, --terraform-action   Terraform subcommand (default: deploy)
    *all terraform.sh options
    ----
    $(usage_terraform "0" | sed 's/^/    /')
    ----

  Proxmox:
    -pa, --proxmox-action   Proxmox subcommand (default: setup-node)
    -ip, --ip-address     Proxmox cluster member to SSH into (IP or DNS)
    -hn, --hostname     Proxmox cluster member hostname
    *all proxmox.sh options
    ----
    $(usage_proxmox "0" | sed 's/^/    /')
    ----

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
EOM

  if [[ "${1:-}" == "0" ]]; then
    return 0
  fi

  exit 1
}

usage_terraform() {
  echo -e "${GREEN_TEXT}Usage:${NC_TEXT} $0 ACTION [OPTIONS]"
  cat << EOF

  ACTION (required, position 1):
    init      Initialize Terraform in terraform/plans (S3 backend from tfvars); then select workspace
    plan      Show execution plan (no auto-apply)
    apply     Apply changes with -auto-approve
    deploy    Same as apply
    destroy   Destroy managed resources with -auto-approve

  Flow:
    Always runs init, then workspace select/create (<project>-<env>), then the ACTION above.

  Environment (required):
    -e, --env, --environment   Target environment; loads terraform/environments/config.<env>.tfvars by default

  Terraform:
    --tfvars-file              Override path to the .tfvars file (default: terraform/environments/config.<env>.tfvars)

  AWS:
    -p, --profile, --aws-profile   AWS profile for backend and provider (default: default)
    -r, --region, --aws-region     AWS region; if omitted, taken from tfvars region= or us-east-1

  Tailscale (terraform init only):
    -itp, --input-tailscale-params   Prompt for API key and tailnet instead of env vars
    Otherwise set TAILSCALE_API_KEY and TAILSCALE_TAILNET when your init needs them.

EOF
  if [[ "${1:-}" == "0" ]]; then
    return 0
  fi

  exit 1
}

usage_proxmox() {
  echo -e "${GREEN_TEXT}Usage:${NC_TEXT} $0 ACTION [OPTIONS]"
  cat << EOF

  Remote Proxmox helper over SSH (multiplexed session). Requires local jq, ssh, and scp.

  ACTION (required, position 1):
    setup-node     Replace <target-path>/deploy with src/bash/, src/python/ (→ deploy/python/
                   with misc/cluster/*.py and datafiles/default.*), utils.sh, usage.sh,
                   deploy/docs/setup-pve-node.usage.txt; chmod a+rx; run setup-pve-node.sh (TTY).
    get-temp, get-temperature
                   On each cluster member: SSH (env PAPITA_SSH_PASSWORD if needed, else password prompt) and run lm-sensors JSON;
                   print a short temperature table per node.
    start-cluster  On the host at -ip: detect local node (pvecm nodes), list all cluster node
                   names from pvesh (JSON .node, any status—needed for WoL to offline peers),
                   send Wake-on-LAN to
                   each peer via pvenode wakeonlan <node> (skips the local node).
    stop-cluster   From the host at -ip: for each peer node, pvesh create /nodes/<node>/stopall
                   then /nodes/<node>/status --command shutdown (cluster API, not repeated
                   shutdown on the SSH target). Then pvenode stopall on the local node; with
                   -sln, also request local hypervisor shutdown via the same API.

  Required:
    -ip, --ip-address     Proxmox cluster member to SSH into (IP or DNS)

  Optional:
    -user, --username     SSH user (default: root)
    -tp, --target-path   Remote base path for deploy (default: /<username>, e.g. /root)
                         Bundle path: <target-path>/deploy/
    -sln, --shutdown-local-node   With stop-cluster only: also shutdown the local node
    -y, --yes                    Automatic yes to questions

  setup-node flow:
    1. SSH multiplexing; reuse for scp and later ssh
    2. rm -rf remote <target-path>/deploy; tar-stream src/bash → .../deploy/
       (includes misc/tailscale/); tar-stream src/python → .../deploy/python/
    3. scp utils.sh, usage.sh, docs/setup-pve-node.usage.txt; chmod -R a+rx; verify bundle
    4. ssh -tt: cd deploy && bash setup-pve-node.sh

  Other:
    -h, --help     Show this message

EOF
  if [[ "${1:-}" == "0" ]]; then
    return 0
  fi

  exit 1
}

# Interactive setup on the node; shows the manual in a pager and returns (does not exit — for use inside setup-pve-node.sh).
usage_setup_pve_node() {
  local usage_file="${PAPITA_DEPLOY_DIR}/docs/setup-pve-node.usage.txt"
  if [[ ! -f "$usage_file" ]]; then
    echo "[ERROR] Missing usage documentation: ${usage_file}" >&2
    return 1
  fi
  echo -e "${GREEN_TEXT}setup-pve-node.sh${NC_TEXT} — full manual (${usage_file})"
  echo "Pager: use arrow keys / PgUp / PgDn; q quits."
  if [[ -t 1 ]] && command -v less >/dev/null 2>&1; then
    less -- "$usage_file"
  elif [[ -t 1 ]] && command -v more >/dev/null 2>&1; then
    more "$usage_file"
  else
    cat "$usage_file"
  fi
}

usage_tailscale_pfsense_lan() {
  local usage_file="${PAPITA_DEPLOY_DIR}/docs/tailscale-pfsense-lan.usage.txt"
  if [[ ! -f "$usage_file" ]]; then
    echo "[ERROR] Missing usage documentation: ${usage_file}" >&2
    if [[ "${1:-}" == "0" ]]; then
      return 1
    fi
    exit 1
  fi
  echo -e "${GREEN_TEXT}tailscale-pfsense-lan.sh${NC_TEXT} — full manual (${usage_file})"
  echo "Pager: use arrow keys / PgUp / PgDn; q quits."
  if [[ -t 1 ]] && command -v less >/dev/null 2>&1; then
    less -- "$usage_file"
  elif [[ -t 1 ]] && command -v more >/dev/null 2>&1; then
    more "$usage_file"
  else
    cat "$usage_file"
  fi
  if [[ "${1:-}" == "0" ]]; then
    return 0
  fi
  exit 1
}

check_action_help() {
  local function_name action
  function_name="$1"
  action="$2"
  if [[ "${action:-}" == "help" || "${action:-}" == "-h" || "${action:-}" == "--help" ]]; then
    "$function_name"
  fi
}
