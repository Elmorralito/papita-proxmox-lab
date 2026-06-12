# Lab policy framework (pfSense MCP)

Policy logic mirrors **`firewall_policy.py`**: each domain exposes **evaluate** (read-only), optional **plan/apply** (CLI), and a **smoke check** row.

## Domains (v1)

| Domain               | pfREST source                  | Smoke check                 | Apply CLI                                       |
| -------------------- | ------------------------------ | --------------------------- | ----------------------------------------------- |
| `tailscale_firewall` | `GET /firewall/rules`          | `tailscale_firewall_policy` | `./deploy/pfsense-firewall-tailscale.sh apply`  |
| `restapi_access`     | `GET /system/restapi/settings` | `restapi_access_policy`     | `./deploy/pfsense-restapi-access.sh fix-access` |
| `api_endpoints`      | Probes required GET paths      | `api_endpoints_policy`      | Grant privileges in WebGUI (see setup doc)      |

**MCP tool:** `pfs_verify_lab_policy` — runs all domains read-only.

**Smoke:** `./deploy/mcp.sh smoke --server pfsense-mcp` includes all three policy checks. Exit code uses **core** checks (optional: `tailscale_subnet_route` only).

After a **live firewall apply**, `pfsense-mcp-firewall` runs the full smoke suite automatically.

---

## Domain details

### `tailscale_firewall`

Three **Tailscale** tab rules for `AUTH_CLIENTS`:

1. This firewall (TCP admin)
2. `172.16.0.1/32` (pfSense LAN IP)
3. `172.16.0.0/16` (lab LAN)

See [TIPSNTRICKS.md](../../docs/TIPSNTRICKS.md) §9.6 Layer 2.

### `restapi_access`

Validates **Allowed Interfaces** against `PFSENSE_HOST`:

| Host path              | Expected Allowed Interfaces                          |
| ---------------------- | ---------------------------------------------------- |
| LAN IP (`172.16.0.1`)  | Empty **or** includes `lan` / `vtnet1` / `localhost` |
| Tailscale IP (`100.x`) | **Empty** (all interfaces)                           |

Advisory: if Access Lists exist, warns when no Allow covers `172.16.0.0/16` for `PFSENSE_API_USER`.

### `api_endpoints`

Probes GET on paths required by MCP read tools:

- `/system/version`
- `/system/restapi/settings`
- `/interfaces`
- `/firewall/rules` (limit 1)
- `/routing/gateways`
- `/routing/static_routes`

Fails on **401** (key) or **403** (privilege / access policy).

---

## P2 backlog (planned domains)

| Domain                 | Endpoint(s)                  | Purpose                                                          |
| ---------------------- | ---------------------------- | ---------------------------------------------------------------- |
| `nat_outbound`         | `GET /firewall/nat/outbound` | Hybrid NAT Tailscale SNAT for site-to-site                       |
| `restapi_access_lists` | Access list CRUD             | Structured Allow rows for LAN + tailnet (apply via MCP v1.1)     |
| `tailscale_routes`     | Tailscale Admin API fallback | Advertised `172.16.0.0/16` when pfREST has no Tailscale endpoint |

### v1.1 MCP writes (planned)

| Tool                        | Domain               | Notes                                        |
| --------------------------- | -------------------- | -------------------------------------------- |
| `pfs_apply_firewall_policy` | `tailscale_firewall` | Wraps `pfsense-mcp-firewall`; `confirm=true` |
| `pfs_apply_restapi_access`  | `restapi_access`     | Allowed interfaces + access list convergence |
| `pfs_apply_*` (generic)     | any                  | Audit JSON logging, `dry_run` first          |

---

## Code layout

```
src/pfsense_mcp/
├── policy/
│   ├── types.py           # PolicyReport, PolicySuiteReport
│   ├── registry.py      # verify_all_policies(), policy_smoke_checks()
│   ├── restapi_access.py
│   └── api_endpoints.py
├── firewall_policy.py     # tailscale_firewall evaluate + apply
└── tools/policy.py        # pfs_verify_lab_policy
```

---

## Operator commands

```bash
./deploy/mcp.sh smoke --server pfsense-mcp
poetry run pfsense-mcp-firewall --dry-run
./deploy/pfsense-firewall-tailscale.sh apply
./deploy/pfsense-restapi-access.sh show-settings
```

Cursor: call **`pfs_verify_lab_policy`** or **`pfs_run_smoke_tests`**.
