---
name: truenas-mcp
description: >-
  Uses Cursor MCP server truenas (package mcp/truenas-mcp) for TrueNAS SCALE
  WebSocket JSON-RPC on wss://host/websocket. Loads creds from
  "${CURSOR_HOME:-${HOME}/.cursor}/mcp.json"
  (mcpServers.truenas.env). Use when checking NAS health, ZFS pools/datasets,
  disks/SMART, NFS HA export, alerts, apps (Scrutiny), jobs/scrubs, smoke
  tests, or gated dataset/NFS-share/alert writes. Do not use for NIC/IP
  changes, reboot/shutdown, app catalog install, SMB, QDevice, or Uptime Kuma.
---

# truenas MCP

Package: `mcp/truenas-mcp` · Cursor server name: **`truenas`** · 18 tools (15 read, 3 write). Spec: [README](../../../mcp/truenas-mcp/README.md). Do not paste the README into context.

Token design: call **1–3 tools**, summarize, never dump envelopes. Unload unused MCP servers; this skill does not load proxmox-ve/pfSense.

SCALE **25.04+**. Transport is **WSS only** — TrueNAS revokes keys sent over `ws://` / HTTP.

## Cursor `mcp.json` (this profile)

**Live config (read; never commit; never echo secrets):**

`"${CURSOR_HOME:-"${HOME}/.cursor}"}/mcp.json`

`CURSOR_HOME` is the Cursor config **directory** (`mcp.json` is `$CURSOR_HOME/mcp.json`). Unset → `${HOME}/.cursor`. Set/export it in repo `.env` and the integrated terminal. After edits: Settings → MCP → reload `truenas` (green). Template without secrets: [mcp.json.example](../../../mcp/truenas-mcp/mcp.json.example).

Expected shape:

```json
{
  "mcpServers": {
    "truenas": {
      "command": "poetry",
      "args": ["run", "truenas-mcp"],
      "cwd": "<repo-root papita-proxmox-lab>",
      "env": {
        "TRUENAS_HOST": "<NAS IP or Tailscale DNS, no scheme>",
        "TRUENAS_PORT": "443",
        "TRUENAS_API_KEY": "<redacted>",
        "TRUENAS_VERIFY_SSL": "false",
        "TRUENAS_WS_PATH": "/websocket",
        "TRUENAS_LAB_HA_POOL_NAME": "pve-cluster-oldtimers-ha-storage",
        "TRUENAS_LAB_NFS_EXPORT": "/mnt/pve-cluster-oldtimers-ha-storage/pve-nfs",
        "TRUENAS_LAB_SCRUTINY_APP_NAME": "scrutiny",
        "TRUENAS_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Usage:

1. Parse `mcpServers.truenas` — `command`/`args`/`cwd` start the stdio server; `env` is the token.
2. If Cursor MCP tools are connected, use them; `env` is already injected. Do not re-read the secret.
3. If tools are **missing**, load `env` from that file (or set `MCP_JSON` to it). Fallback: `$MCP_JSON` → `"${CURSOR_HOME:-"${HOME}/.cursor}"}/mcp.json`. Then use Fallback below.
4. Never print `TRUENAS_API_KEY`. Log only `TRUENAS_HOST`, `TRUENAS_PORT`, `TRUENAS_VERIFY_SSL`, `SECRET_SET=true|false`.
5. `cwd` must be **repo root** so Poetry finds the `truenas-mcp` path dep.
6. Install/sync: `./deploy/mcp.sh install --server truenas-mcp` then `./deploy/mcp.sh cursor-sync` (preserves existing secrets).

## Connect

1. Discover tools in namespace matching `truenas` / `truenas_`. If none: reload MCP from the profile `mcp.json`, then Fallback.
2. Creds: profile `mcp.json` `env` first; else `TRUENAS_*`. Never print `TRUENAS_API_KEY`.
3. Auth is the API key from TrueNAS UI → **My API Keys** (shown once). Prefer a dedicated service user. See [API_KEY_SETUP.md](../../../mcp/truenas-mcp/docs/API_KEY_SETUP.md).
4. `TRUENAS_HOST` = NAS address, no `https://`. Lab default in repo docs: `172.16.0.100`. Live host may differ — use `mcp.json`, not the README, as source of truth.
5. `TRUENAS_VERIFY_SSL` defaults **false** (self-signed homelab certs). Set `true` only with a trusted CA.
6. Connect/auth fail after a SCALE upgrade → try `TRUENAS_WS_PATH=/api/v2.0/websocket` (25.04+ default is `/websocket`).
7. HTTP 401 / WS auth error → key missing, revoked, or host unreachable. Confirm `:443` from this workstation (LAN or Tailscale). SSH to the NAS is often disabled; do not assume CLI fallback.

## Pick tools (do not list all)

| Need               | Tool                                                               |
| ------------------ | ------------------------------------------------------------------ |
| Alive / auth       | `truenas_check_api_key` or `truenas_get_system_info`               |
| Operator dashboard | `truenas_system_summary`                                           |
| Post-install       | `truenas_run_smoke_tests` (`extended=true` only if basic pass)     |
| Alerts             | `truenas_list_alerts`                                              |
| ZFS pools          | `truenas_list_pools`                                               |
| Datasets           | `truenas_list_datasets`                                            |
| Disks / temps      | `truenas_list_disks`                                               |
| SMART              | `truenas_list_smart_results`                                       |
| NFS HA export      | `truenas_list_nfs_shares`                                          |
| Apps (Scrutiny)    | `truenas_list_apps`                                                |
| Jobs / scrubs      | `truenas_list_jobs` / `truenas_list_scrub_tasks`                   |
| Graphs             | `truenas_get_reporting_data` (`graph`: `cpu`\|`memory`\|`disk`\|…) |
| Create dataset     | `truenas_create_dataset`                                           |
| Enable/disable NFS | `truenas_update_nfs_share` (`share_id`)                            |
| Dismiss alert      | `truenas_dismiss_alert`                                            |

Writes: **`confirm=true` required**. Optional `wait_for_job=true` on dataset/NFS updates. No reboot, interface, or catalog tools in v1/v2.

Envelope: `{ok, data, warnings, meta}` — report `ok`, counts, names, pool/NFS warnings; skip raw permission dumps.

Lab NFS/pool mismatch shows as **warnings** on `truenas_list_nfs_shares` / summary vs `TRUENAS_LAB_*` (overlay: [default.truenas.nfs.env](../../../deploy/setup/misc/cluster/default.truenas.nfs.env)).

## Caveats (v1/v2)

- **WebSocket JSON-RPC only.** No SSH, no `midclt`, no TrueNAS UI automation via this MCP.
- **Not in MCP** — use TrueNAS WebUI / [TIPSNTRICKS.md](../../../docs/TIPSNTRICKS.md) / `deploy/setup/misc/cluster/`:
  - NIC / IP / gateway / `interface.update` + commit/checkin
  - `system.reboot` / `system.shutdown`
  - App catalog install/upgrade (Scrutiny/Tailscale apps)
  - SMB shares, snapshot tasks (backlog)
  - QDevice host (must **not** be this NAS)
  - Uptime Kuma (runs on `pvecm-oldtimers` — use `proxmox-ve` MCP / monitoring bootstrap)
- NFS list validates the **lab export path**; it does not add `pvesm` storage on PVE. Cluster NFS attach is `papita-cluster-quorum-ha.sh` / `pvesm add nfs`.
- `truenas_create_dataset` creates ZFS datasets only; it does not export NFS or register PVE storage.
- `truenas_update_nfs_share` can enable/disable an existing share by id; it does not create shares or change networks/hosts.
- Do not register official [truenas/truenas-mcp](https://github.com/truenas/truenas-mcp) under the same Cursor id `truenas`.

## Fallback

MCP tools missing this session:

1. Read `"${CURSOR_HOME:-"${HOME}/.cursor}"}/mcp.json` → `mcpServers.truenas.env`.
2. Export those `TRUENAS_*` keys into the process (do not print the secret).
3. From repo root, call package impls (`truenas_get_system_info_impl`, `truenas_check_api_key_impl`, `truenas_system_summary_impl`) with `sys.path` = `mcp/truenas-mcp/src`, or `poetry run` equivalent (`truenas-mcp-smoke`).
4. WebUI / SSH only for work that is not in the tool catalog (network, reboot, catalog).

## Docs (read on demand)

- API key: [API_KEY_SETUP.md](../../../mcp/truenas-mcp/docs/API_KEY_SETUP.md)
- Smoke catalog: [SMOKE_TESTS.md](../../../mcp/truenas-mcp/docs/SMOKE_TESTS.md)
- Traceability: [REQUIREMENTS.md](../../../mcp/truenas-mcp/docs/REQUIREMENTS.md) (FR-900–FR-906: no catalog install, no NAS VMs, no reboot, no QDevice on TrueNAS)
