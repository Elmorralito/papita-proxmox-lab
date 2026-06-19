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
    proxmox     Deploy infrastructure via Proxmox
    deploy_proxmox      Same as action proxmox
    none        No action; useful with --pre-commit only

  Environment (required):
    -e, --env, --environment   Target environment: dev or prod

  Paths:
    -lip, --libs-input-path   Libraries source directory. Default: ${LIBS_INPUT_PATH}
    -lop, --libs-output-path  Output directory for built wheels. Default: ${LIBS_OUTPUT_PATH}

  Proxmox:
    -pa, --proxmox-action   Proxmox subcommand (default: setup-node)
    -ip, --ip-address     Proxmox cluster member to SSH into (IP or DNS)
    -hn, --hostname     Proxmox cluster member hostname
    -if, --identity-file SSH private key path (or env PAPITA_SSH_IDENTITY_FILE)
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

usage_proxmox() {
  echo -e "${GREEN_TEXT}Usage:${NC_TEXT} $0 ACTION [OPTIONS]"
  cat << EOF

  Remote Proxmox helper over SSH (multiplexed session). Requires local jq, ssh, and scp.

  ACTION (required, position 1):
    setup-node     Replace <target-path>/deploy with deploy/setup/, deploy/python/ (→ python/
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
    setup-cluster-ha
                   Deploy misc/cluster bundle; on every online member install corosync-qdevice
                   + softdog (papita-node-qdevice-client.sh); on the SSH entry host register
                   QDevice, add TrueNAS NFS (172.16.0.100), create HA group, verify quorum.
                   Prerequisite: corosync-qnetd on the host in misc/cluster/default.qdevice.host
                   (NOT TrueNAS). Edit misc/cluster/default.truenas.nfs.env for export path.

  Required:
    -ip, --ip-address     Proxmox cluster member to SSH into (IP or DNS)

  Optional:
    -user, --username     SSH user (default: root)
    -if, --identity-file SSH private key path (or env PAPITA_SSH_IDENTITY_FILE; uses IdentitiesOnly)
    -tp, --target-path   Remote base path for deploy (default: /<username>, e.g. /root)
                         Bundle path: <target-path>/deploy/
    -sln, --shutdown-local-node   With stop-cluster only: also shutdown the local node
    -y, --yes                    Automatic yes to questions

  setup-node flow:
    1. SSH multiplexing; reuse for scp and later ssh
    2. rm -rf remote <target-path>/deploy; tar-stream deploy/setup → .../deploy/
       (includes misc/tailscale/); tar-stream deploy/python → .../deploy/python/
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

usage_pfsense_restapi_access() {
  echo -e "${GREEN_TEXT}Usage:${NC_TEXT} deploy/pfsense-restapi-access.sh ACTION"
  cat << EOF

  Bootstrap pfREST access when Tailscale IP returns 403 (Allowed Interfaces).

  ACTION (default: fix-access):
    fix-access         PATCH allowed_interfaces=[] then smoke test
    show-settings      GET /system/restapi/settings (JSON)
    webgui-steps       Print manual WebGUI instructions
    -h, --help         Show this message

  Requires PFSENSE_* in ~/.cursor/mcp.json (./deploy/mcp.sh cursor-sync).
  PATCH needs mcp-cursor-agent privilege on /system/restapi/settings, or clear Allowed
  Interfaces manually in WebGUI first.

  See mcp/pfsense-mcp/docs/PFSENSE_API_KEY_SETUP.md
EOF

  if [[ "${1:-}" == "0" ]]; then
    return 0
  fi
  exit 1
}

usage_pfsense_firewall_tailscale() {
  echo -e "${GREEN_TEXT}Usage:${NC_TEXT} deploy/pfsense-firewall-tailscale.sh [apply] [OPTIONS]"
  cat << EOF

  Apply agreed Tailscale-tab firewall rules on pfSense via pfREST.

  Default action: apply

  OPTIONS:
    --dry-run          Show planned rule changes without applying
    --skip-smoke       Do not run MCP smoke tests after a live apply
    --json             JSON output
    -h, --help         Show this message

  Requires PFSENSE_* in ~/.cursor/mcp.json. The API user needs POST/PATCH/DELETE
  on /firewall/rule and POST on /firewall/apply (temporarily grant write on
  firewall endpoints, or run with an admin key).

  See docs/TIPSNTRICKS.md §9.6 Layer 2 and deploy/tailscale-pfsense-lan.sh pfsense-steps
EOF

  if [[ "${1:-}" == "0" ]]; then
    return 0
  fi
  exit 1
}

usage_mcp() {
  echo -e "${GREEN_TEXT}Usage:${NC_TEXT} deploy/mcp.sh ACTION [OPTIONS]"
  cat << EOF

  Install and maintain Cursor MCP servers under mcp/.

  ACTION (required, position 1):
    list          List MCP packages and Cursor server names
    install       poetry install + register console scripts (all or --server)
    update        Same as install (re-lock and reinstall)
    test          Run pytest for MCP package test suites
    smoke         Post-install connectivity smoke test (proxmox-ve-mcp)
    cursor-sync   Merge mcp.json.example into Cursor MCP configs (keeps env secrets)

  Options:
    -s, --server NAME     MCP package or server id (e.g. proxmox-ve-mcp or proxmox-ve)
    --extended            Pass --extended to smoke test (full access matrix)
    -c, --cursor-config   Single target mcp.json path (default: ~/.cursor/mcp.json)
    --all-targets         Sync ~/.cursor/mcp.json and .cursor/mcp.json (cursor-agent + IDE)
    --if-changed          Skip when mcp.json.example files are unchanged
    --enable-agent        Run cursor-agent mcp enable for each repo MCP server
    -h, --help            Show this message

  Quick start:
    ./deploy/mcp.sh install
    ./deploy/mcp.sh cursor-sync --all-targets    # edit secrets in ~/.cursor/mcp.json once
    ./deploy/install-git-hooks.sh                # auto-sync on git pull + agent session
    ./deploy/mcp.sh smoke --extended
    # Reload Cursor → Settings → MCP → proxmox-ve connected

  See mcp/README.md for full installation guide.

  pfSense API access (403 on Tailscale IP):
    ./deploy/pfsense-restapi-access.sh fix-access
EOF

  if [[ "${1:-}" == "0" ]]; then
    return 0
  fi
  exit 1
}
