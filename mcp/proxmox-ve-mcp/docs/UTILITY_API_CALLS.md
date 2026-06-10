# Utility API calls — proxmox-ve-mcp quick reference

Crosswalk between **MCP tools**, **Proxmox REST paths** (`/api2/json`), and operator CLI (`pvesh` / `curl`). Use this when debugging a tool, calling the API directly, or extending the server.

## Official references

| Resource                                            | URL                                                                            |
| --------------------------------------------------- | ------------------------------------------------------------------------------ |
| Interactive API viewer (paths, parameters, schemas) | [Proxmox VE API viewer](https://pve.proxmox.com/pve-docs/api-viewer/#/cluster) |
| Authentication, base URL, tokens, `pvesh`           | [Proxmox VE API wiki](https://pve.proxmox.com/wiki/Proxmox_VE_API)             |
| Token setup for this MCP                            | [PVE_TOKEN_SETUP.md](./PVE_TOKEN_SETUP.md)                                     |

---

## API basics

**Base URL** (any online cluster member on `:8006`):

```text
https://{PVE_HOST}:{PVE_PORT}/api2/json
```

Default port: `8006`. The MCP client sets this from `PVE_HOST` / `PVE_PORT` — see [`config.py`](../src/proxmox_ve_mcp/config.py).

**Authentication** — API token in the `Authorization` header ([wiki § API Tokens](https://pve.proxmox.com/wiki/Proxmox_VE_API#API_Tokens)):

```http
Authorization: PVEAPIToken=mcp-agent@pam!mcp-cursor=YOUR-SECRET-UUID
```

Equivalent env (MCP / curl):

```bash
export PVE_HOST=pvenode-001.your-tailnet.ts.net
export PVE_TOKEN='mcp-agent@pam!mcp-cursor=YOUR-SECRET-UUID'
```

**Response shape** — JSON wrapper; MCP unwraps the `data` field:

```json
{ "data": { "...": "..." } }
```

**Mutating calls** — Token auth does **not** require a CSRF header (unlike ticket/cookie auth). Write MCP tools additionally require `confirm=true`.

**Task results** — Many POST endpoints return a UPID string, e.g. `UPID:pvenode-001:00001234:...`. Poll with `GET /nodes/{node}/tasks/{upid}/status` or use MCP `wait_for_completion=true`.

---

## MCP tool → REST mapping

Legend: **R** = read, **W** = write (requires `confirm=true` in MCP).

### Cluster & version

| MCP tool                             | HTTP | REST path                                      | Query / body                                             | API viewer                                                                                         |
| ------------------------------------ | ---- | ---------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `pve_get_version` **R**              | GET  | `/version`                                     | —                                                        | [version](https://pve.proxmox.com/pve-docs/api-viewer/#/version)                                   |
| `pve_list_nodes` **R**               | GET  | `/cluster/resources`                           | `type=node`                                              | [cluster/resources](https://pve.proxmox.com/pve-docs/api-viewer/#/cluster/resources)               |
| `pve_get_cluster_config_nodes` **R** | GET  | `/cluster/config/nodes`                        | —                                                        | [cluster/config/nodes](https://pve.proxmox.com/pve-docs/api-viewer/#/cluster/config/nodes)         |
| `pve_get_cluster_options` **R**      | GET  | `/cluster/options`                             | —                                                        | [cluster/options](https://pve.proxmox.com/pve-docs/api-viewer/#/cluster/options)                   |
| `pve_list_tasks` **R**               | GET  | `/cluster/tasks`                               | `statusfilter`, `start`, `limit`                         | [cluster/tasks](https://pve.proxmox.com/pve-docs/api-viewer/#/cluster/tasks)                       |
| `pve_get_task_log` **R**             | GET  | `/nodes/{node}/tasks/{upid}/log`               | —                                                        | [nodes/…/tasks/…/log](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/tasks/{upid}/log) |
| `pve_list_resources` **R**           | GET  | `/cluster/resources`                           | `type`, `start`, `limit`; MCP filters `node` client-side | [cluster/resources](https://pve.proxmox.com/pve-docs/api-viewer/#/cluster/resources)               |
| `pve_cluster_health` **R**           | GET  | `/cluster/resources` + `/cluster/config/nodes` | Derived summary (no single upstream endpoint)            | [cluster](https://pve.proxmox.com/pve-docs/api-viewer/#/cluster)                                   |

### Nodes & guests (read)

| MCP tool                     | HTTP | REST path                                          | Notes                          | API viewer                                                                                                                                                     |
| ---------------------------- | ---- | -------------------------------------------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pve_get_node_status` **R**  | GET  | `/nodes/{node}/status`                             | CPU, memory, uptime            | [nodes/…/status](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/status)                                                                            |
| `pve_list_guests` **R**      | GET  | `/cluster/resources`                               | All nodes; types `qemu`, `lxc` | [cluster/resources](https://pve.proxmox.com/pve-docs/api-viewer/#/cluster/resources)                                                                           |
| `pve_list_guests` **R**      | GET  | `/nodes/{node}/qemu`, `/nodes/{node}/lxc`          | When `node` is set             | [nodes/…/qemu](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/qemu), [nodes/…/lxc](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/lxc) |
| `pve_get_guest_status` **R** | GET  | `/nodes/{node}/{guest_type}/{vmid}/status/current` | `guest_type`: `qemu` or `lxc`  | [status/current](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/qemu/{vmid}/status/current)                                                        |
| `pve_get_guest_config` **R** | GET  | `/nodes/{node}/{guest_type}/{vmid}/config`         | Secrets redacted in MCP output | [config](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/qemu/{vmid}/config)                                                                        |

### Storage & Ceph (read)

| MCP tool                    | HTTP | REST path                                     | Notes                              | API viewer                                                                                    |
| --------------------------- | ---- | --------------------------------------------- | ---------------------------------- | --------------------------------------------------------------------------------------------- |
| `pve_list_storage` **R**    | GET  | `/storage`                                    | Datacenter definitions             | [storage](https://pve.proxmox.com/pve-docs/api-viewer/#/storage)                              |
| `pve_list_storage` **R**    | GET  | `/nodes/{node}/storage`, `…/{storage}/status` | When `node` is set                 | [nodes/…/storage](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/storage)         |
| `pve_get_ceph_status` **R** | GET  | `/cluster/ceph/status`                        | Preferred; falls back to node path | [cluster/ceph/status](https://pve.proxmox.com/pve-docs/api-viewer/#/cluster/ceph/status)      |
| `pve_get_ceph_status` **R** | GET  | `/nodes/{node}/ceph/status`                   | Fallback if cluster path fails     | [nodes/…/ceph/status](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/ceph/status) |
| `pve_list_ceph_osds` **R**  | GET  | `/nodes/{node}/ceph/osd`                      | Read-only OSD list                 | [nodes/…/ceph/osd](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/ceph/osd)       |

### Guest power (write)

| MCP tool                   | HTTP | REST path                                           | Body                | Privilege      |
| -------------------------- | ---- | --------------------------------------------------- | ------------------- | -------------- |
| `pve_start_guest` **W**    | POST | `/nodes/{node}/{guest_type}/{vmid}/status/start`    | —                   | `VM.PowerMgmt` |
| `pve_shutdown_guest` **W** | POST | `/nodes/{node}/{guest_type}/{vmid}/status/shutdown` | `timeout` (seconds) | `VM.PowerMgmt` |
| `pve_stopall_guests` **W** | POST | `/nodes/{node}/stopall`                             | `timeout` (seconds) | `VM.PowerMgmt` |

API viewer: [status/start](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/qemu/{vmid}/status/start), [status/shutdown](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/qemu/{vmid}/status/shutdown), [stopall](https://pve.proxmox.com/pve-docs/api-viewer/#/nodes/{node}/stopall).

---

## Copy-paste examples

Replace placeholders: `{HOST}`, `{NODE}`, `{VMID}`, `{UPID}`, `{TOKEN}`.

### curl

```bash
# Smoke test (same as pve_get_version)
curl -sS -H "Authorization: PVEAPIToken=${PVE_TOKEN}" \
  "https://${PVE_HOST}:8006/api2/json/version" | jq .

# List online nodes (pve_list_nodes)
curl -sS -H "Authorization: PVEAPIToken=${PVE_TOKEN}" \
  "https://${PVE_HOST}:8006/api2/json/cluster/resources?type=node" | jq .

# Cluster resource inventory (pve_list_resources)
curl -sS -H "Authorization: PVEAPIToken=${PVE_TOKEN}" \
  "https://${PVE_HOST}:8006/api2/json/cluster/resources" | jq .

# Guest runtime status (pve_get_guest_status — VM 100 on NODE)
curl -sS -H "Authorization: PVEAPIToken=${PVE_TOKEN}" \
  "https://${PVE_HOST}:8006/api2/json/nodes/{NODE}/qemu/{VMID}/status/current" | jq .

# Start guest (pve_start_guest) — returns UPID in data
curl -sS -X POST -H "Authorization: PVEAPIToken=${PVE_TOKEN}" \
  "https://${PVE_HOST}:8006/api2/json/nodes/{NODE}/qemu/{VMID}/status/start" | jq .

# Task log (pve_get_task_log)
curl -sS -H "Authorization: PVEAPIToken=${PVE_TOKEN}" \
  "https://${PVE_HOST}:8006/api2/json/nodes/{NODE}/tasks/{UPID}/log" | jq .
```

Add `-k` only when `PVE_VERIFY_SSL=false` (self-signed cert during initial setup).

### pvesh (on a PVE node as root)

`pvesh` uses the same API paths locally ([wiki § Using pvesh](https://pve.proxmox.com/wiki/Proxmox_VE_API#Using_'pvesh'_to_Access_the_API)):

```bash
pvesh get /version
pvesh get /cluster/resources --type node
pvesh get /cluster/config/nodes
pvesh get /nodes/{NODE}/status
pvesh get /nodes/{NODE}/qemu
pvesh get /nodes/{NODE}/qemu/{VMID}/status/current
pvesh get /cluster/ceph/status
pvesh create /nodes/{NODE}/qemu/{VMID}/status/start
pvesh create /nodes/{NODE}/stopall --timeout 120
```

Remote workstation access to the API should use HTTPS + token (MCP or curl), not SSH `pvesh`, unless you intentionally shell into a node.

---

## MCP usage (Cursor / agent)

Configure the server via user-level `~/.cursor/mcp.json` or env — see [mcp.json.example](../mcp.json.example) and [PVE_TOKEN_SETUP.md](./PVE_TOKEN_SETUP.md).

Typical read sequence after install:

1. `pve_get_version` — auth + TLS check
2. `pve_list_nodes` — cluster membership
3. `pve_cluster_health` or `pve_list_resources` — inventory / health
4. `pve_list_guests` → `pve_get_guest_status` — drill into a VM/CT

Write tools always need explicit confirmation:

```text
pve_shutdown_guest(node="pvenode-001", vmid=100, guest_type="qemu", confirm=true)
```

Optional `wait_for_completion=true` polls `GET /nodes/{node}/tasks/{upid}/status` until the task stops.

---

## Response envelope (MCP)

All tools return a JSON string shaped like:

```json
{
  "ok": true,
  "data": {},
  "warnings": [],
  "meta": {
    "tool": "pve_list_nodes",
    "tool_class": "read",
    "duration_ms": 42,
    "runbook_ref": null
  }
}
```

Errors surface as `ok: false` with a message; HTTP 401/403 usually means token, role, or path permissions — see [PVE_TOKEN_SETUP.md](./PVE_TOKEN_SETUP.md).

---

## Not exposed via MCP (use Bash / runbooks)

These lab workflows have no REST equivalent in v1 or stay in SSH scripts by design:

| Workflow                            | Where                                                 |
| ----------------------------------- | ----------------------------------------------------- |
| Node bootstrap (`setup-node`)       | `deploy/proxmox.sh` → `setup-pve-node.sh`             |
| Wake-on-LAN / `start-cluster`       | `deploy/proxmox.sh`, `pvenode wakeonlan`              |
| Cluster-wide temperature            | `deploy/proxmox.sh get-temp` (`sensors -j`)           |
| Full node shutdown / `stop-cluster` | `deploy/proxmox.sh`, `pre-shutdown-proc.sh`           |
| Ceph OSD start/stop, deep mutations | [`docs/TIPSNTRICKS.md`](../../../docs/TIPSNTRICKS.md) |

---

## Source of truth in code

| Layer                          | Path                                                                                                                                                                                                                                                                       |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tool registration & docstrings | [`src/proxmox_ve_mcp/tools/register.py`](../src/proxmox_ve_mcp/tools/register.py)                                                                                                                                                                                          |
| REST calls                     | [`cluster.py`](../src/proxmox_ve_mcp/tools/cluster.py), [`nodes.py`](../src/proxmox_ve_mcp/tools/nodes.py), [`guests.py`](../src/proxmox_ve_mcp/tools/guests.py), [`storage.py`](../src/proxmox_ve_mcp/tools/storage.py), [`ceph.py`](../src/proxmox_ve_mcp/tools/ceph.py) |
| HTTP client                    | [`src/proxmox_ve_mcp/client/http.py`](../src/proxmox_ve_mcp/client/http.py)                                                                                                                                                                                                |
| Task polling                   | [`src/proxmox_ve_mcp/client/tasks.py`](../src/proxmox_ve_mcp/client/tasks.py)                                                                                                                                                                                              |

When this document and the code disagree, **trust the code** and update this file.
