"""Shared constants for the Proxmox VE MCP server.

Centralizes HTTP client defaults, input validation patterns, documentation metadata, and
pointers to repo runbooks. Values here are imported across the HTTP client, tool
implementations, and response ``meta`` builders so behavior stays consistent without
scattering magic strings.

Module-level symbols:

    API_PREFIX:
        Path segment appended to ``https://{host}:{port}`` for Proxmox JSON API requests.
    NODE_NAME_PATTERN:
        Regular expression accepted for Proxmox cluster node names in tool inputs.
    DEFAULT_HTTP_TIMEOUT_SEC:
        Default per-request timeout for routine API calls.
    LONG_HTTP_TIMEOUT_SEC:
        Extended timeout for operations that may block longer (for example task polling).
    MAX_CONCURRENT_REQUESTS:
        Upper bound on parallel in-flight HTTP requests from a single client instance.
    PVE_TESTED_MAJOR_VERSION:
        Documented Proxmox VE major release line validated against this MCP package.
    RUNBOOK_REFS:
        Maps MCP tool names to repo-relative runbook paths surfaced in ``meta.runbook_ref``.
    BASH_ONLY_WORKFLOWS:
        Maps lab workflow keys to Bash entrypoints not exposed as MCP tools; included in
        ``pve_cluster_health`` so agents know where to look for gaps in API coverage.
"""

API_PREFIX = "/api2/json"
NODE_NAME_PATTERN = r"^[a-zA-Z0-9._-]+$"
DEFAULT_HTTP_TIMEOUT_SEC = 30.0
LONG_HTTP_TIMEOUT_SEC = 120.0
MAX_CONCURRENT_REQUESTS = 4
PVE_TESTED_MAJOR_VERSION = "8.x"

# Non-executable runbook pointers (repo-relative paths); keys are MCP tool names.
RUNBOOK_REFS: dict[str, str] = {
    "pve_check_token": "mcp/proxmox-ve-mcp/docs/PVE_TOKEN_SETUP.md — token ACL and privilege separation",
    "pve_run_smoke_tests": "mcp/proxmox-ve-mcp/docs/SMOKE_TESTS.md — post-install connectivity and access checks",
    "pve_list_node_addresses": "deploy/proxmox.sh local-node; ring0_addr for peer SSH",
    "pve_list_nodes": "docs/TIPSNTRICKS.md — Proxmox VE cluster configuration & troubleshooting",
    "pve_get_cluster_config_nodes": "deploy/proxmox.sh local-node; ring0_addr for peer SSH",
    "pve_cluster_health": "docs/TIPSNTRICKS.md — verify communication between cluster nodes",
    "pve_list_resources": "deploy/proxmox.sh cluster-nodes; docs/TIPSNTRICKS.md cluster verify",
    "pve_list_tasks": "docs/TIPSNTRICKS.md — cluster troubleshooting (async operations)",
    "pve_list_storage": "docs/TIPSNTRICKS.md — pvesm status",
    "pve_get_ceph_status": "docs/TIPSNTRICKS.md — OSD Storage at startup (manual only; MCP read-only)",
    "pve_list_ceph_osds": "docs/TIPSNTRICKS.md — OSD Storage at startup (manual only)",
    "pve_stopall_guests": "src/bash/pre-shutdown-proc.sh — pair with ceph osd set noout manually",
    "pve_shutdown_guest": "src/bash/pre-shutdown-proc.sh — graceful shutdown before maintenance",
    "pve_start_guest": "deploy/proxmox.sh — guest power; use read tools to verify target first",
}

# Bash-only workflows for agents; values are deploy/script entrypoints, not MCP tools.
BASH_ONLY_WORKFLOWS: dict[str, str] = {
    "setup-node": "deploy/proxmox.sh setup-node",
    "get-temp": "deploy/proxmox.sh get-temp",
    "start-cluster": "deploy/proxmox.sh start-cluster (WoL)",
    "stop-cluster": "deploy/proxmox.sh stop-cluster (node shutdown)",
    "ceph-noout": "src/bash/pre-shutdown-proc.sh / post-startup-proc.sh",
}
