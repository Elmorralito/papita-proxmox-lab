---
name: proxmox-ve-mcp
description: >-
  Uses Cursor MCP server proxmox-ve (package mcp/proxmox-ve-mcp) for Proxmox VE
  REST on :8006. Loads creds from
  "${CURSOR_HOME:-${HOME}/.cursor}/mcp.json"
  (mcpServers.proxmox-ve.env). Use when listing cluster nodes, guests, storage,
  Ceph read, token/smoke checks, gated guest start/shutdown/stopall, or guarded
  node power (shutdown/reboot, WoL, hard stop). Do not use for pvecm, sensors,
  node bootstrap, Ceph mutations, or node decommission.
---

# proxmox-ve MCP

Package: `mcp/proxmox-ve-mcp` · Cursor server name: **`proxmox-ve`** · 28 tools (21 read, 4 write, 3 destructive). Spec: [README](../../../mcp/proxmox-ve-mcp/README.md). Do not paste the README into context.

Token design: call **1–3 tools**, summarize, never dump envelopes. Unload unused MCP servers; this skill does not load pfSense/TrueNAS.

## Cursor `mcp.json` (this profile)

**Live config (read; never commit; never echo secrets):**

`"${CURSOR_HOME:-"${HOME}/.cursor}"}/mcp.json`

`CURSOR_HOME` is the Cursor config **directory** (`mcp.json` is `$CURSOR_HOME/mcp.json`). Unset → `${HOME}/.cursor`. Set/export it in repo `.env` and the integrated terminal. After edits: Settings → MCP → reload `proxmox-ve` (green). Template without secrets: [mcp.json.example](../../../mcp/proxmox-ve-mcp/mcp.json.example).

Expected shape:

```json
{
  "mcpServers": {
    "proxmox-ve": {
      "command": "poetry",
      "args": ["run", "proxmox-ve-mcp"],
      "cwd": "<repo-root papita-proxmox-lab>",
      "env": {
        "PVE_HOST": "<online member, no scheme>",
        "PVE_PORT": "8006",
        "PVE_USER": "<user@realm>",
        "PVE_TOKEN_ID": "<id only, not user!id>",
        "PVE_TOKEN_SECRET": "<redacted>",
        "PVE_VERIFY_SSL": "true",
        "PVE_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Usage:

1. Parse `mcpServers.proxmox-ve` — `command`/`args`/`cwd` start the stdio server; `env` is the token.
2. If Cursor MCP tools are connected, use them; `env` is already injected. Do not re-read the secret.
3. If tools are **missing**, load `env` from that file (or set `MCP_JSON` to it). Fallback: `$MCP_JSON` → `"${CURSOR_HOME:-"${HOME}/.cursor}"}/mcp.json`. Then use Fallback below.
4. Never print `PVE_TOKEN_SECRET`. Log only `PVE_HOST`, `PVE_USER`, `PVE_TOKEN_ID`, `SECRET_SET=true|false`.
5. `cwd` must be **repo root** so Poetry finds the `proxmox-ve-mcp` path dep.

## Connect

1. Discover tools in namespace matching `proxmox` / `pve_`. If none: reload MCP from the profile `mcp.json`, then Fallback.
2. Creds: profile `mcp.json` `env` first; else `PVE_*`. Never print `PVE_TOKEN_SECRET` / full `PVE_API_TOKEN`.
3. Header: `PVEAPIToken={PVE_USER}!{PVE_TOKEN_ID}={secret}`. **`PVE_TOKEN_ID` is the id only**. If the file stores `user!id`, strip the `user!` prefix or you get HTTP 401.
4. Auth: either `PVE_API_TOKEN` **or** all of `PVE_USER` + `PVE_TOKEN_ID` + `PVE_TOKEN_SECRET`.
5. `PVE_HOST` = any **online** member, no `https://`. TLS: `PVE_VERIFY_SSL=true` after setup step 17.
6. Token ACL ≠ user ACL (privilege separation). 403 → `pve_check_token`, then [PVE_TOKEN_SETUP.md](../../../mcp/proxmox-ve-mcp/docs/PVE_TOKEN_SETUP.md). Role on the **token** at `/`.

## Pick tools (do not list all)

| Need         | Tool                                                                              |
| ------------ | --------------------------------------------------------------------------------- |
| Alive / TLS  | `pve_get_version`                                                                 |
| 403 / ACL    | `pve_check_token`                                                                 |
| Post-install | `pve_run_smoke_tests` (`extended=true` only if basic pass and Sys.Audit needed)   |
| Members      | `pve_list_nodes`                                                                  |
| ring0 / IPs  | `pve_get_cluster_config_nodes` or `pve_list_node_addresses`                       |
| Quorum       | `pve_cluster_health` (`quorate`, `entry_node`, QDevice)                           |
| HA / freeze  | `pve_get_ha_status` (`shutdown_policy` must be `freeze`)                          |
| Wait         | `pve_wait_for_task` (UPID) / `pve_wait_nodes_state` (online/offline), ≤120 s      |
| VMs/CTs      | `pve_list_guests` (`node` optional)                                               |
| One guest    | `pve_get_guest_status` / `pve_get_guest_config` (`guest_type`: `qemu`\|`lxc`)     |
| Storage      | `pve_list_storage`                                                                |
| Ceph read    | `pve_get_ceph_status` / `pve_list_ceph_osds`                                      |
| Power        | `pve_start_guest` / `pve_shutdown_guest` / `pve_stopall_guests`                   |
| Hung guest   | `pve_stop_guest` (**destructive**, `reason`, `overrule_shutdown`)                 |
| Node power   | `pve_shutdown_node` (**destructive**; `plan_only=true` first) / `pve_wake_on_lan` |
| Full lab off | `pve_shutdown_cluster` (**destructive**; runbook below)                           |

Writes: **`confirm=true` required**. Optional `wait_for_completion=true` (UPID poll). Destructive tools also need a `reason`; never auto-run them. Run `pve_shutdown_node(plan_only=true)` and show refusals/warnings before the real call. Entry node goes **last** (`allow_entry_host=true`), after the delayed `truenas_shutdown` — see `docs/MCP_POWER_PLAN.md`.

`pve_list_resources` `type` at API: `vm` \| `storage` \| `node` \| `sdn` (not `haresource`; use `pve_get_ha_status`). Prefer `pve_list_guests` for qemu/lxc.

Envelope: `{ok, data, warnings, meta}` — report `ok`, counts, names; skip permission dumps.

## Full-lab shutdown runbook (with the `truenas` MCP)

1. `pve_cluster_health` (quorate) → `pve_get_ha_status` (`shutdown_policy_ok`) → `truenas_list_nfs_clients`.
2. `pve_shutdown_cluster(reason, plan_only=true)` → show stages/warnings; get the user's go-ahead.
3. `pve_shutdown_cluster(reason, confirm=true)`; re-call with the same args while `done=false` → `stage=ready_for_nas`. It refuses if the entry node would self-fence (HA resources or an active LRM there), and leaves HA-managed guests to the `freeze` node shutdown.
4. `truenas_shutdown(reason, delay_s=300, expected_clients=[entry IP], confirm=true)` (copy from `next_steps`).
5. `pve_shutdown_cluster(reason, include_entry_node=true, confirm=true)` → `entry_shutdown_submitted` (API loss = success).
6. Startup is Bash: `./deploy/proxmox.sh wake-lab --ip-address 172.16.0.99`, then `pve_wake_on_lan(all_offline=true)` for stragglers.

Full runbook: `docs/TIPSNTRICKS.md` → "Full-lab shutdown / startup via MCP".

## Caveats (v1)

- **REST only.** No SSH, no `pvesh`/`pvecm`/`pvenode`/`ceph` CLI via MCP.
- **Not in MCP** — use Bash / [TIPSNTRICKS.md](../../../docs/TIPSNTRICKS.md) / `deploy/proxmox.sh`:
  - `pvecm add`/`delnode`, corosync edits, `/etc/hosts`
  - Cold start with the lab fully off (`deploy/proxmox.sh wake-lab` via the QDevice host)
  - `setup-node`, `get-temp` (sensors)
  - Ceph `noout`, OSD start/destroy
  - migrate, HA group CRUD
- `pve_cluster_health` returns true `quorate` (from `/cluster/status`), `entry_node` (node answering the API), and best-effort `qdevice` status. Per-vote detail still needs SSH `pvecm status`.
- Ceph HTTP 500 `ceph-mon` binary missing = Ceph not installed, not a bad token.
- `pve_stopall_guests` does **not** set Ceph `noout`.
- Guest config redacts passwords/keys; still do not echo tokens.
- Node names: `^[a-zA-Z0-9._-]+$`. Lab short names may be `pve-00N` not `pvenode-00N` — use API names.
- Concurrency: client max 4 in-flight HTTP requests.
- Package tested **PVE 8.x**; lab may run 9.x — treat as compatible unless tools fail.

## Fallback

MCP tools missing this session:

1. Read `"${CURSOR_HOME:-"${HOME}/.cursor}"}/mcp.json` → `mcpServers.proxmox-ve.env`.
2. Export those `PVE_*` keys into the process (do not print the secret).
3. From repo root, call package impls (`pve_get_version_impl`, `pve_list_nodes_impl`, `pve_cluster_health_impl`) with `sys.path` = `mcp/proxmox-ve-mcp/src`, or `poetry run` equivalent.
4. SSH / `deploy/proxmox.sh` only for bash-only work.

## Docs (read on demand)

- Tools ↔ REST: [UTILITY_API_CALLS.md](../../../mcp/proxmox-ve-mcp/docs/UTILITY_API_CALLS.md)
- Smoke catalog: [SMOKE_TESTS.md](../../../mcp/proxmox-ve-mcp/docs/SMOKE_TESTS.md)
- Traceability: [REQUIREMENTS.md](../../../mcp/proxmox-ve-mcp/docs/REQUIREMENTS.md) (FR-901: no `pvecm` in v1)
