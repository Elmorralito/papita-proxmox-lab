# pfSense REST API MCP Server

**`pfsense-mcp`** v0.1.0a1 — read-only [Model Context Protocol](https://modelcontextprotocol.io/) server for the community [pfSense REST API v2 (pfREST)](https://pfrest.org/) in **papita-proxmox-lab**.

> **Unofficial API:** pfREST is community-maintained, not Netgate-supported. Reinstall after pfSense upgrades.

## Status

Read-only v1 — **7 read tools**, zero write tools. Lab policy framework: [docs/POLICY.md](./docs/POLICY.md). Strategy: [docs/IMPLEMENTATION.md](./docs/IMPLEMENTATION.md).

## Quick install

From repo root:

```bash
./deploy/mcp.sh install --server pfsense-mcp
./deploy/mcp.sh cursor-sync
# Edit ~/.cursor/mcp.json → set PFSENSE_API_KEY
# If Tailscale IP returns 403: deselect all Allowed Interfaces in WebGUI, or:
./deploy/pfsense-restapi-access.sh fix-access
./deploy/mcp.sh smoke --server pfsense-mcp
```

Reload Cursor. Server id: **`pfsense`**.

## Configuration

| Variable                   | Required | Default            | Notes                                                                       |
| -------------------------- | -------- | ------------------ | --------------------------------------------------------------------------- |
| `PFSENSE_HOST`             | Yes      | —                  | **IPv4/IPv6 only** (e.g. `172.16.0.1`)                                      |
| `PFSENSE_PORT`             | No       | `443`              | HTTPS                                                                       |
| `PFSENSE_API_KEY`          | Yes      | —                  | `X-API-Key` header                                                          |
| `PFSENSE_API_USER`         | No       | `mcp-cursor-agent` | Local pfSense user that owns the API key (error hints)                      |
| `PFSENSE_VERIFY_SSL`       | No       | `true`             | Set `false` for self-signed certs or Tailscale IP access                    |
| `PFSENSE_LOG_LEVEL`        | No       | `INFO`             | stderr JSON log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`                  |
| `PFSENSE_HTTP_TIMEOUT_SEC` | No       | `30`               | pfREST GET timeout (seconds)                                                |
| `PFSENSE_HASH_ALGO`        | No       | `sha256`           | Hash algorithm for pfREST API key creation (`sha256` / `sha384` / `sha512`) |
| `PFSENSE_LENGTH_BYTES`     | No       | `16`               | Key length in bytes for pfREST API key creation (`16` / `24` / `32` / `64`) |

**API base URL:** `https://{PFSENSE_HOST}:{PFSENSE_PORT}/api/v2/` (e.g. `https://172.16.0.1:443/api/v2/system/version`).

Optional (Tailscale Admin API fallback for `pfs_get_tailscale_status` when pfREST has no Tailscale endpoint):

| Variable            | Required     | Notes                                         |
| ------------------- | ------------ | --------------------------------------------- |
| `TAILSCALE_API_KEY` | For fallback | Same key as `deploy/tailscale-pfsense-lan.sh` |
| `TAILSCALE_TAILNET` | For fallback | e.g. `tailf1ad0d.ts.net`                      |
| `PFSENSE_NAME`      | No           | Device name match (default `pfsense-fw001`)   |

Tested against: **pfSense Plus 26.03 / pfREST v2** (community package). Reinstall pfREST after pfSense upgrades.

API key setup: [docs/PFSENSE_API_KEY_SETUP.md](./docs/PFSENSE_API_KEY_SETUP.md).

## Tools (v1)

| Tool                       | Purpose                                                                       |
| -------------------------- | ----------------------------------------------------------------------------- |
| `pfs_get_version`          | pfSense / pfREST version                                                      |
| `pfs_list_interfaces`      | Interfaces + LAN CIDR check                                                   |
| `pfs_get_tailscale_status` | Advertised routes, accept-routes                                              |
| `pfs_system_summary`       | Version, system identity, Tailscale, gateways, static routes, REST API health |
| `pfs_list_firewall_rules`  | Paginated rules (default limit 50)                                            |
| `pfs_verify_lab_policy`    | Evaluate Tailscale firewall, REST API access, endpoint privileges             |
| `pfs_run_smoke_tests`      | Post-install QA (9 checks; core exit code)                                    |

## Smoke tests

```bash
poetry run pfsense-mcp-smoke
poetry run pfsense-mcp-smoke --json
```

Checks: config, API reachability, API key, REST API package, LAN `172.16.0.0/16`, Tailscale subnet route (optional), **lab policy domains** (`tailscale_firewall_policy`, `restapi_access_policy`, `api_endpoints_policy`).

Exit code uses **core** checks (all except optional `tailscale_subnet_route`).

**CLIs** (not MCP tools): `pfsense-mcp-bootstrap` (Allowed Interfaces), `pfsense-mcp-firewall` (Tailscale-tab rules + post-apply smoke). See [docs/POLICY.md](./docs/POLICY.md).

## Caveats

pfREST sits behind pfSense **interface policy**, **access lists**, and **per-user API privileges** — not just a valid API key. Match `PFSENSE_HOST` to the path you actually use (LAN gateway IP, routed subnet, or Tailscale address); hostnames are rejected by design.

**Allowed Interfaces** must include the interface that receives your HTTPS traffic. LAN + localhost is enough when calling the LAN address; enable WAN only if you intentionally reach pfREST from WAN (unusual). If you use a Tailscale IP as `PFSENSE_HOST`, Tailscale is often absent from the WebGUI list — leave Allowed Interfaces empty (all interfaces) or PATCH `allowed_interfaces` to `[]` (see [PFSENSE_API_KEY_SETUP.md](./docs/PFSENSE_API_KEY_SETUP.md)).

**Access Lists** are optional. When present, each Allow rule must cover the **source network pfSense sees** for your client _and_ scope the intended API user (`PFSENSE_API_USER`). A rule for one network (e.g. tailnet CGNAT) does not implicitly permit another (e.g. LAN). Empty Access Lists skip this layer.

**Smoke tests** run six connectivity checks plus three **lab policy** checks (firewall, REST API access, endpoint privileges). The Tailscale route step needs either a pfREST Tailscale endpoint (uncommon) or `TAILSCALE_API_KEY` + `TAILSCALE_TAILNET` in repo `.env` for Admin API fallback. **`./deploy/pfsense-firewall-tailscale.sh apply`** runs the full smoke suite automatically after any live firewall change.

| HTTP    | Usually means                                                             |
| ------- | ------------------------------------------------------------------------- |
| **401** | Bad, missing, or revoked API key — fix under **System → REST API → Keys** |
| **403** | Interface policy, Access List, or missing GET privilege on the endpoint   |

Setup details: [docs/PFSENSE_API_KEY_SETUP.md](./docs/PFSENSE_API_KEY_SETUP.md).

## Out of scope (v1)

- Write/mutating MCP tools (v1.1 — see [POLICY.md](./docs/POLICY.md) backlog)
- Tailscale Admin API as a standalone MCP tool (smoke/`pfs_get_tailscale_status` use it as fallback only; primary workflow remains `deploy/tailscale-pfsense-lan.sh`)
- GraphQL, bulk rule replace, package install via API

## Lab context

- LAN: `172.16.0.0/16`, gateway `172.16.0.1`
- Complements [`proxmox-ve-mcp`](../proxmox-ve-mcp/) for PVE admin via subnet route

## References

- [pfREST guide](https://pfrest.org/)
- [REQUIREMENTS.md](./docs/REQUIREMENTS.md)
- [TIPSNTRICKS.md](../../docs/TIPSNTRICKS.md) — pfSense / Tailscale
