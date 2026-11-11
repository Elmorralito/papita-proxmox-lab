---
name: openwrt-mcp
description: >-
  Uses Cursor MCP server openwrt (package mcp/openwrt-mcp) for the OpenWrt
  gateway firewall over a restricted SSH agent. Loads settings from
  "${CURSOR_HOME:-${HOME}/.cursor}/mcp.json"
  (mcpServers.openwrt.env). Use when inspecting the firewall, running smoke
  tests, planning an allow_tcp_from_lan rule, or applying/confirming/rolling
  back a human-approved plan. Do not use for UCI/ubus/shell, DNS/DHCP,
  Tailscale, WAN/VPN, SSH, or package changes.
---

# openwrt MCP

Package: `mcp/openwrt-mcp` · Cursor server name: **`openwrt`** · 7 tools (3 read, 3 write, 1 destructive). Spec: [README](../../../mcp/openwrt-mcp/README.md). Do not paste the README into context.

Token design: call **1–3 tools**, summarize, never dump envelopes. Unload unused MCP servers; this skill does not load proxmox-ve/TrueNAS/pfSense.

Deny by default. Transport is **restricted SSH** (forced command, no PTY) to the on-router ucode agent. No shell, UCI, or ubus passthrough.

## Cursor `mcp.json` (this profile)

**Live config (read; never commit; never echo secrets):**

`"${CURSOR_HOME:-"${HOME}/.cursor}"}/mcp.json`

`CURSOR_HOME` is the Cursor config **directory** (`mcp.json` is `$CURSOR_HOME/mcp.json`). Unset → `${HOME}/.cursor`. Set/export it in repo `.env` and the integrated terminal. After edits: Settings → MCP → reload `openwrt` (green). Template without secrets: [mcp.json.example](../../../mcp/openwrt-mcp/mcp.json.example).

Expected shape:

```json
{
  "mcpServers": {
    "openwrt": {
      "command": "poetry",
      "args": ["run", "openwrt-mcp"],
      "cwd": "<repo-root papita-proxmox-lab>",
      "env": {
        "OPENWRT_ROUTER_ID": "openwrt-pi",
        "OPENWRT_HOST": "<Tailscale IP literal, no scheme>",
        "OPENWRT_LAN_HOST": "172.16.0.1",
        "OPENWRT_SSH_KEY_PATH": "~/.ssh/id_ed25519_openwrt_mcp",
        "OPENWRT_KNOWN_HOSTS_PATH": "~/.config/openwrt-mcp/known_hosts",
        "OPENWRT_PROBE_HOST": "172.16.0.101",
        "OPENWRT_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Usage:

1. Parse `mcpServers.openwrt` — `command`/`args`/`cwd` start the stdio server; `env` is the connection.
2. If Cursor MCP tools are connected, use them; `env` is already injected. Do not re-read key files.
3. If tools are **missing**, load `env` from that file (or set `MCP_JSON` to it). Fallback: `$MCP_JSON` → `"${CURSOR_HOME:-"${HOME}/.cursor}"}/mcp.json`. Then use Fallback below.
4. Never print private keys, approver passphrases, or grant signatures. Log only `OPENWRT_ROUTER_ID`, `OPENWRT_HOST`, `OPENWRT_LAN_HOST`, `KEY_SET=true|false`.
5. `cwd` must be **repo root** so Poetry finds the `openwrt-mcp` path dep.
6. `OPENWRT_SSH_KEY_PATH` is the **dedicated restricted agent key**, never the root admin key (`id_ed25519_NASGW`). `OPENWRT_HOST` and `OPENWRT_LAN_HOST` are IP literals.
7. Install/sync: `./deploy/mcp.sh install --server openwrt-mcp` then `./deploy/mcp.sh cursor-sync` (preserves existing env).

## Connect

1. Discover tools in namespace matching `openwrt` / `owrt_`. If none: reload MCP from the profile `mcp.json`, then Fallback.
2. Creds: profile `mcp.json` `env` first; else `OPENWRT_*`. Never print key material.
3. Agent install (admin key, one time): `deploy/setup/misc/openwrt/papita-openwrt-mcp-agent-install.sh install --host <ip> --admin-key <admin-key>`. It installs the agent, watchdog, approver pubkey, and a forced-command `authorized_keys` line. It does not change firewall, network, Tailscale, or sshd.
4. Pin the router host key into `OPENWRT_KNOWN_HOSTS_PATH` (`ssh-keyscan -t ed25519`). Compare with `dropbearkey -y` on the router.
5. Approver key: `poetry run openwrt-mcp-approve keygen` (TTY, passphrase ≥ 12). Public key is installed by the agent installer.
6. SSH/auth fail → wrong key (admin vs agent), unpinned host key, or Tailscale/LAN unreachable. Confirm `:22` to `OPENWRT_HOST`.

## Pick tools (do not list all)

| Need | Tool |
| ---- | ---- |
| Firewall snapshot | `owrt_firewall_inspect` (`router_id`) |
| Post-install | `owrt_run_smoke_tests` |
| Plan a rule (no router change) | `owrt_firewall_plan_rule` |
| Plan / journal | `owrt_plan_status` (`plan_id`) |
| Apply approved plan | `owrt_firewall_apply_plan` (`plan_id`, `plan_digest`) |
| Keep the change | `owrt_plan_confirm` (`plan_id`) |
| Undo | `owrt_plan_rollback` (**destructive**) |

Only template: `allow_tcp_from_lan` (`action`: `upsert`\|`delete`). `upsert` requires `dest_port`. `rule_id` matches `^[a-z0-9][a-z0-9-]{0,31}$` (UCI section `mcp_<id>`). `idempotency_key` is 8–64 of `[A-Za-z0-9_.-]`. `src_ip`, when set, must be inside `172.16.0.0/16`. Prohibited ports (even with approval): **22, 53, 80, 443, 41641**.

## Change flow (plan → approve → apply → confirm)

1. `owrt_run_smoke_tests` (read-only) before any live write.
2. `owrt_firewall_plan_rule` — stores an immutable plan. Report `plan_id`, digest prefix, diff, expiry. Default plan TTL **900 s**.
3. **Stop.** Approval is out of band and **TTY-only**: `poetry run openwrt-mcp-approve approve <plan_id>` (operator types the 12-hex digest prefix and passphrase). The agent cannot approve, pass a grant, or invent `confirm=true`.
4. After the operator approves, show the digest and get an explicit go-ahead, then `owrt_firewall_apply_plan` with the **stored** `plan_digest`. Apply is refused without a valid grant, on digest mismatch, on config drift, or when the watchdog heartbeat is stale.
5. `owrt_plan_confirm` before the verify deadline (default **120 s**). Unconfirmed changes are rolled back by the on-router watchdog, including across reboot.
6. `owrt_plan_rollback` only when the operator asks to undo. `needs_manual` recovery is [RUNBOOK.md](../../../mcp/openwrt-mcp/docs/RUNBOOK.md), not another apply.

Live writes on `openwrt-pi` stay **NO-GO** until [GO_NO_GO.md](../../../mcp/openwrt-mcp/docs/GO_NO_GO.md) sections B–D are signed off. Planning and smoke tests are allowed. Do not apply, confirm, or roll back on the real router without that sign-off plus a fresh go-ahead.

Envelope: `{"isError": false, "structuredContent": ...}` — report status, `plan_id`, digest prefix, and check names. Errors use stable codes (`APPROVAL_REQUIRED`, `APPROVAL_EXPIRED`, `STATE_PRECONDITION_FAILED`, `OPERATION_PROHIBITED`, `VERIFICATION_FAILED`, …). Skip raw firewall dumps.

## Caveats (v1)

- **Restricted agent only.** No LuCI, no UCI/ubus, no package install, no interface or Tailscale edits via this MCP.
- **Not in MCP** — use the router console / [RUNBOOK.md](../../../mcp/openwrt-mcp/docs/RUNBOOK.md):
  - DNS, DHCP, routing, WAN, VPN, SSH, sysupgrade
  - Manual restore from `/etc/openwrt-mcp/journal/<plan>.firewall.bak`
  - `openwrt-mcp-agent --clear` after `needs_manual`
- `pfsense-mcp` stays; this server does not replace it.
- Agent-owned rules only (`owned_by 'openwrt-mcp'`). Do not edit foreign firewall sections.

## Fallback

MCP tools missing this session:

1. Read `"${CURSOR_HOME:-"${HOME}/.cursor}"}/mcp.json` → `mcpServers.openwrt.env`.
2. Export those `OPENWRT_*` keys into the process (do not print key material).
3. From repo root, `poetry run openwrt-mcp-smoke`, or call package impls with `sys.path` = `mcp/openwrt-mcp/src`.
4. Admin SSH only for agent install/status (`papita-openwrt-mcp-agent-install.sh`), not for firewall edits the agent refused.

## Docs (read on demand)

- Operator steps: [RUNBOOK.md](../../../mcp/openwrt-mcp/docs/RUNBOOK.md)
- Live-write gate: [GO_NO_GO.md](../../../mcp/openwrt-mcp/docs/GO_NO_GO.md)
- Agent protocol: [AGENT_CONTRACT.md](../../../mcp/openwrt-mcp/docs/AGENT_CONTRACT.md)
- Threat model: [THREAT_MODEL.md](../../../mcp/openwrt-mcp/docs/THREAT_MODEL.md)
- Traceability: [REQUIREMENTS.md](../../../mcp/openwrt-mcp/docs/REQUIREMENTS.md)
