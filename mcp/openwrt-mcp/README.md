# openwrt-mcp

Policy-constrained MCP server (stdio, FastMCP) for the OpenWrt gateway firewall. Deny by default: no shell, UCI
or ubus passthrough. Writes follow **plan → human approval → apply → pending confirmation → confirm**, with an
on-router watchdog that auto-rolls back unconfirmed changes.

## Tools

| Tool                       | Class             | Purpose                                             |
| -------------------------- | ----------------- | --------------------------------------------------- |
| `owrt_firewall_inspect`    | read              | Fresh inspect via restricted SSH agent              |
| `owrt_run_smoke_tests`     | read              | Connectivity, forced-command and audit-chain checks |
| `owrt_firewall_plan_rule`  | write (plan only) | Build a plan for `allow_tcp_from_lan`               |
| `owrt_plan_status`         | read              | Plan / router journal state                         |
| `owrt_firewall_apply_plan` | destructive       | Apply an approved plan (needs signed grant)         |
| `owrt_plan_confirm`        | write             | Re-verify and confirm                               |
| `owrt_plan_rollback`       | destructive       | Roll back an applied plan                           |

Approval happens out of band with `openwrt-mcp-approve` (TTY + digest prefix + passphrase-protected key).

## Setup

```bash
cd mcp/openwrt-mcp
cp .env.example .env            # OPENWRT_* settings (never commit)
poetry install
poetry run openwrt-mcp-approve keygen
deploy/setup/misc/openwrt/papita-openwrt-mcp-agent-install.sh install --host <ip> --admin-key <key>
poetry run openwrt-mcp-smoke
```

Cursor config: see `mcp.json.example` (server id `openwrt`). Details in `docs/`:
`REQUIREMENTS.md`, `THREAT_MODEL.md`, `AGENT_CONTRACT.md`, `DISCOVERY.md`, `RUNBOOK.md`, `GO_NO_GO.md`.

## Tests

```bash
pytest                                       # unit tests
OPENWRT_MCP_DOCKER_TESTS=1 pytest tests/test_agent_container.py   # needs docker, openwrt/rootfs 25.12.5
```

## Limits

Firewall domain only (tcp allow from LAN, prohibited ports 22/53/80/443/41641). Live canary on the real router is
gated by `docs/GO_NO_GO.md`.
