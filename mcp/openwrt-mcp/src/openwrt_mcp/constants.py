"""Lab constants and policy defaults."""

DEFAULT_ROUTER_ID = "openwrt-pi"
DEFAULT_LAN_CIDR = "172.16.0.0/16"
DEFAULT_ROUTER_LAN_IP = "172.16.0.1"
DEFAULT_PROBE_HOST = "172.16.0.101"

AGENT_PROTOCOL_VERSION = 1
AGENT_REMOTE_PATH = "/usr/libexec/openwrt-mcp-agent"
APPROVER_PUBKEY_REMOTE_PATH = "/etc/openwrt-mcp/approver.pub"

POLICY_REVISION = 1
"""Bump whenever templates, prohibited ports or field rules change (invalidates outstanding plans)."""

RULE_PREFIX = "mcp_"
RULE_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"
TEMPLATE_ALLOW_TCP_FROM_LAN = "allow_tcp_from_lan"
SUPPORTED_TEMPLATES = (TEMPLATE_ALLOW_TCP_FROM_LAN,)

PROHIBITED_PORTS = frozenset({22, 53, 80, 443, 41641})
"""SSH, DNS, LuCI HTTP(S) and Tailscale WireGuard: never agent-managed."""

DEFAULT_PLAN_TTL_SEC = 900
DEFAULT_VERIFY_DEADLINE_SEC = 120
MAX_VERIFY_DEADLINE_SEC = 300
DEFAULT_SSH_TIMEOUT_SEC = 30.0
MAX_AGENT_REQUEST_BYTES = 65536
MAX_AGENT_RESPONSE_BYTES = 1_048_576
MAX_GRANT_TTL_SEC = 900

ROUTER_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"
