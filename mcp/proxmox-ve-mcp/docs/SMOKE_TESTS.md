# Proxmox VE MCP — post-install smoke tests

Run these after installing the MCP server and configuring `PVE_*` credentials (Cursor `mcp.json` or `.env`).

## Purpose

Verify **connectivity**, **authentication**, and **access level** before relying on the MCP for cluster operations. Tests are read-only and make no changes to the cluster.

## How to run

### Option A — MCP tool (Cursor / agent)

Call **`pve_run_smoke_tests`**:

| Parameter  | Default | Meaning                                                        |
| ---------- | ------- | -------------------------------------------------------------- |
| `extended` | `false` | Also run extended read probes (network, guests, storage, Ceph) |

Example agent prompt: _"Run the Proxmox MCP smoke tests with extended checks."_

### Option B — CLI (terminal)

From the repo root (with `PVE_*` env set or `.env` in `mcp/proxmox-ve-mcp/`):

```bash
poetry run proxmox-ve-mcp-smoke           # basic suite
poetry run proxmox-ve-mcp-smoke --extended  # full read-level matrix
```

Exit code `0` = all required tests for the selected mode passed; `1` = one or more failures.

## Test catalog

### Tier 1 — Connectivity & auth (always run)

| ID                  | Checks                       | Pass criteria                       |
| ------------------- | ---------------------------- | ----------------------------------- |
| `connectivity_tls`  | HTTPS to `PVE_HOST:PVE_PORT` | `GET /version` succeeds             |
| `auth_token`        | API token                    | Response is not HTTP 401            |
| `token_permissions` | Token ACL endpoint           | `GET /access/permissions` reachable |

### Tier 2 — Read core (always run)

| ID                   | Checks             | Pass criteria                               |
| -------------------- | ------------------ | ------------------------------------------- |
| `cluster_list_nodes` | Cluster membership | At least one node returned                  |
| `cluster_all_online` | Node status        | All configured nodes `online` (warn if not) |
| `cluster_health`     | Health summary     | Derived health payload returned             |

### Tier 3 — Read extended (`extended=true`)

| ID                     | Checks                        | Privilege                      | Pass criteria                        |
| ---------------------- | ----------------------------- | ------------------------------ | ------------------------------------ |
| `cluster_config_nodes` | Corosync `ring0_addr`         | `Sys.Audit` on `/`             | Config nodes returned                |
| `node_network_detail`  | Interface CIDR on sample node | `Sys.Audit` on `/nodes/{node}` | At least one address                 |
| `node_status`          | CPU / memory / uptime         | `Sys.Audit` on `/nodes/{node}` | Status payload returned              |
| `guest_inventory`      | VM + CT list                  | `VM.Audit` on `/`              | Guest list returned                  |
| `storage_list`         | Storage definitions           | `Sys.Audit` on `/`             | Storage list returned                |
| `ceph_status`          | Ceph health (optional)        | Ceph present                   | Pass, skip if Ceph N/A, warn on deny |

### Tier 4 — Write capability (informational, `extended=true`)

| ID                  | Checks                                   | Meaning                                                           |
| ------------------- | ---------------------------------------- | ----------------------------------------------------------------- |
| `write_permissions` | `/access/permissions` for `VM.PowerMgmt` | Reports whether write tools _may_ work (does not mutate anything) |

## Access levels

The smoke test runner assigns one label based on results:

| Level           | Meaning                                     |
| --------------- | ------------------------------------------- |
| `none`          | Cannot reach API or auth fails              |
| `minimal`       | TLS + token auth only                       |
| `read_basic`    | Can list cluster nodes                      |
| `read_extended` | Extended read probes mostly pass            |
| `read_full`     | All extended read probes pass               |
| `write_capable` | `VM.PowerMgmt` visible in token permissions |

## Interpreting failures

| Failure                                        | Likely fix                                                                                      |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `connectivity_tls`                             | Check Tailscale/LAN, firewall, `PVE_HOST`, `PVE_VERIFY_SSL`                                     |
| `auth_token`                                   | Regenerate token secret; verify `PVE_USER`, `PVE_TOKEN_ID`, `PVE_TOKEN_SECRET`                  |
| `cluster_config_nodes` / `node_network_detail` | Assign `Sys.Audit` to the **API token** at `/` — see [PVE_TOKEN_SETUP.md](./PVE_TOKEN_SETUP.md) |
| `guest_inventory`                              | Assign `VM.Audit` to the token at `/`                                                           |
| `write_permissions`                            | Expected for read-only tokens; add `VM.PowerMgmt` only if write tools are needed                |

For a quick permission matrix without the full suite, call **`pve_check_token`**.

## Recommended post-install sequence

1. `poetry install` from repo root
2. Configure `~/.cursor/mcp.json` (see [mcp.json.example](../mcp.json.example))
3. Reload Cursor → confirm MCP server `proxmox-ve` is connected
4. **`pve_run_smoke_tests`** (basic)
5. If warnings on extended reads → fix token ACL → **`pve_run_smoke_tests`** with `extended=true`
6. Day-to-day: `pve_list_nodes`, `pve_cluster_health`, `pve_list_node_addresses`
