"""Shared constants for pfSense MCP."""

API_PREFIX = "/api/v2/"

DEFAULT_HASH_ALGO = "sha256"
DEFAULT_LENGTH_BYTES = 16
ALLOWED_HASH_ALGOS = frozenset({"sha256", "sha384", "sha512"})
ALLOWED_LENGTH_BYTES = frozenset({16, 24, 32, 64})

DEFAULT_HTTP_TIMEOUT_SEC = 30.0
LONG_HTTP_TIMEOUT_SEC = 120.0

# Documented lab target; confirm on your pfSense instance
PFS_TESTED_MAJOR_VERSION = "pfSense Plus 26.03 / pfREST v2"

# Lab topology (papita-proxmox-lab)
LAB_LAN_CIDR = "172.16.0.0/16"
LAB_PFSENSE_LAN_IP = "172.16.0.1"
PFS_TAILSCALE_DEVICE_NAME = "pfsense-fw001"
DEFAULT_API_USER = "mcp-cursor-agent"

# pfREST paths — confirm on live Swagger if requests fail (System → REST API → Documentation)
EP_SYSTEM_VERSION = "/system/version"
EP_RESTAPI_SETTINGS = "/system/restapi/settings"
EP_INTERFACES = "/interfaces"
EP_GATEWAYS = "/routing/gateways"
EP_STATIC_ROUTES = "/routing/static_routes"
EP_FIREWALL_RULES = "/firewall/rules"
EP_FIREWALL_RULE = "/firewall/rule"
EP_FIREWALL_APPLY = "/firewall/apply"
EP_TAILSCALE_CANDIDATES = (
    "/vpn/tailscale/settings",
    "/services/tailscale/settings",
)
EP_TAILSCALE_SETTINGS = EP_TAILSCALE_CANDIDATES[0]

DEFAULT_FIREWALL_RULE_LIMIT = 50

RUNBOOK_REFS: dict[str, str] = {
    "pfs_get_version": "https://pfrest.org/",
    "pfs_list_interfaces": "docs/TIPSNTRICKS.md — pfSense LAN (Step 5)",
    "pfs_get_tailscale_status": "docs/TIPSNTRICKS.md — pfSense Tailscale §9",
    "pfs_system_summary": "deploy/tailscale-pfsense-lan.sh verify",
    "pfs_list_firewall_rules": "docs/TIPSNTRICKS.md — pfSense firewall §7",
    "pfs_run_smoke_tests": "mcp/pfsense-mcp/docs/PFSENSE_API_KEY_SETUP.md",
    "pfs_verify_lab_policy": "mcp/pfsense-mcp/docs/POLICY.md",
}

OUT_OF_SCOPE_V1: tuple[str, ...] = (
    "tailscale-admin-api",
    "graphql",
    "write-tools",
    "pfsense-webgui-install",
)
