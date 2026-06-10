# Proxmox VE API token setup for MCP

Create a dedicated **group**, **user**, and **role** for MCP automation — **avoid `root@pam` in production**. For a lab token owned by root, the token ACL rules in [Critical: token ACL vs user ACL](#critical-token-acl-vs-user-acl) still apply.

Recommended identity chain:

```text
Role (MCPAgentRead) ──► Group (mcp-agents) ──► User (mcp-agent@pam) ──► API token (cursor)
                              │                        │
                              └──── Permissions ───────┴──► Token ACL (separate step)
```

---

## Critical: token ACL vs user ACL

Proxmox API tokens use **privilege separation** by default. The token receives only permissions assigned **to the token**, not the owning user's or group's role.

| Misconception                                             | Reality                                                                                     |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| "I set `PVE_USER=root@pam`, so the token has full access" | The token still needs its own role at path `/`                                              |
| "I assigned a role to the user/group"                     | That applies to the user login; the token needs its own ACL when privilege separation is on |
| "`pve_list_nodes` works, so permissions are fine"         | `/cluster/resources` needs less privilege than `/cluster/config/nodes`                      |

When tools return **HTTP 403**, call **`pve_check_token`** in Cursor or run `./deploy/mcp.sh smoke --extended`.

### Fix (choose one)

**Option A — lab / full access**

1. Datacenter → Permissions → API Tokens → edit your token
2. Disable **Privilege Separation**
3. Token inherits the user's effective permissions from group + user ACLs

**Option B — least privilege (recommended)**

1. Keep **Privilege Separation** enabled on the token
2. Datacenter → Permissions → **Add** → select the **API Token** (`mcp-agent@pam!cursor`)
3. Path `/`, Role `MCPAgentRead` (or `MCPAgent` if write tools are needed)

---

## Step-by-step setup

Work in **Datacenter → Permissions** unless noted. Order matters: role → group → user → token.

### 1. Create roles

**Permissions → Roles → Add**

#### Read-only MCP (recommended first)

| Field      | Value                   |
| ---------- | ----------------------- |
| Name       | `MCPAgentRead`          |
| Privileges | `Sys.Audit`, `VM.Audit` |

| Privilege   | Purpose                           |
| ----------- | --------------------------------- |
| `Sys.Audit` | Cluster/node/storage/network read |
| `VM.Audit`  | Guest read                        |

#### Write-capable MCP (optional)

| Field      | Value                                   |
| ---------- | --------------------------------------- |
| Name       | `MCPAgent`                              |
| Privileges | `Sys.Audit`, `VM.Audit`, `VM.PowerMgmt` |

Required privileges for common MCP tools:

| Tool / endpoint                                           | Privilege                          |
| --------------------------------------------------------- | ---------------------------------- |
| `pve_get_version`, `pve_list_nodes`                       | Often works with minimal token ACL |
| `pve_get_cluster_config_nodes`, `pve_list_node_addresses` | `Sys.Audit` on `/`                 |
| `pve_get_node_status`, network detail                     | `Sys.Audit` on `/nodes/{node}`     |
| `pve_list_guests`, `pve_get_guest_status`                 | `VM.Audit` on `/`                  |
| `pve_start_guest`, `pve_shutdown_guest`                   | `VM.PowerMgmt` on `/`              |

---

### 2. Create a group

**Permissions → Groups → Add**

| Field   | Value                              |
| ------- | ---------------------------------- |
| Name    | `mcp-agents`                       |
| Comment | Cursor / MCP automation (optional) |

---

### 3. Link the group to a role

**Permissions → Add → Permission**

| Field     | Value                                          |
| --------- | ---------------------------------------------- |
| Path      | `/` (entire datacenter)                        |
| Group     | `mcp-agents`                                   |
| Role      | `MCPAgentRead` (or `MCPAgent` for write tools) |
| Propagate | enabled (default)                              |

This grants every member of `mcp-agents` the role at `/` and below.

---

### 4. Create the automation user

**Permissions → Users → Add**

| Field    | Value                                                                         |
| -------- | ----------------------------------------------------------------------------- |
| Userid   | `mcp-agent@pam`                                                               |
| Password | Set a strong password (or disable password login later; MCP uses tokens only) |
| Groups   | `mcp-agents`                                                                  |
| Enable   | yes                                                                           |
| Expire   | never (or set a rotation policy)                                              |
| Comment  | MCP / Cursor API automation                                                   |

**Do not enable TOTP/2FA** on this user — API tokens bypass TOTP anyway, and 2FA complicates non-interactive use.

The user inherits **`MCPAgentRead`** via group membership. You do not need a separate user-level permission unless you want to override the group (usually not).

Optional CLI equivalent (on any PVE node as root):

```bash
pveum group add mcp-agents --comment "MCP automation"
pveum role add MCPAgentRead -privs "Sys.Audit,VM.Audit"
pveum acl modify / -group mcp-agents -role MCPAgentRead
pveum user add mcp-agent@pam -groups mcp-agents -enable 1
```

---

### 5. Create the API token (for `mcp-agent@pam`)

**Permissions → API Tokens → Add**

| Field                | Value                                                                |
| -------------------- | -------------------------------------------------------------------- |
| User                 | `mcp-agent@pam`                                                      |
| Token ID             | `cursor` (matches `PVE_TOKEN_ID`; full id is `mcp-agent@pam!cursor`) |
| Privilege Separation | **enabled** (recommended)                                            |
| Expire               | set a rotation date, or leave blank for lab                          |
| Comment              | Cursor MCP (optional)                                                |

Copy the **secret** immediately — Proxmox shows it only once.

---

### 6. Link the token to a role (privilege separation)

With privilege separation **on**, assign permissions to the **token**, not only the user/group.

**Permissions → Add → Permission**

| Field     | Value                                                             |
| --------- | ----------------------------------------------------------------- |
| Path      | `/`                                                               |
| API Token | `mcp-agent@pam!cursor`                                            |
| Role      | `MCPAgentRead` (same as the group, or `MCPAgent` for write tools) |
| Propagate | enabled                                                           |

CLI equivalent:

```bash
pveum user token add mcp-agent@pam cursor --privsep 1
# Copy secret from output, then:
pveum acl modify / -token 'mcp-agent@pam!cursor' -role MCPAgentRead
```

If you skip step 6 and leave privilege separation enabled, the token has **no effective privileges** even though the user is in `mcp-agents`.

---

### 7. Configure MCP env

Use `./deploy/mcp.sh cursor-sync` or edit Cursor `~/.cursor/mcp.json` manually (repo root `cwd`):

```json
{
  "mcpServers": {
    "proxmox-ve": {
      "command": "poetry",
      "args": ["run", "proxmox-ve-mcp"],
      "cwd": "/absolute/path/to/papita-proxmox-lab",
      "env": {
        "PVE_HOST": "pvenode-001.your-tailnet.ts.net",
        "PVE_PORT": "8006",
        "PVE_USER": "mcp-agent@pam",
        "PVE_TOKEN_ID": "cursor",
        "PVE_TOKEN_SECRET": "<paste-secret>",
        "PVE_VERIFY_SSL": "true"
      }
    }
  }
}
```

Single-line alternative:

```bash
PVE_API_TOKEN=mcp-agent@pam!cursor=<secret>
```

---

### 8. Verify

From repo root:

```bash
./deploy/mcp.sh install
./deploy/mcp.sh smoke --extended
```

In Cursor (after reload):

1. **`pve_run_smoke_tests`** with `extended=true`
2. `pve_check_token` — permission matrix
3. `pve_list_nodes` / `pve_list_node_addresses`

See [SMOKE_TESTS.md](./SMOKE_TESTS.md) and [../../README.md](../../README.md).

---

## Troubleshooting

| Symptom                                    | Fix                                                               |
| ------------------------------------------ | ----------------------------------------------------------------- |
| MCP server not listed in agent             | Reload Cursor; Settings → MCP → `proxmox-ve` green                |
| `Configuration error: host Field required` | Set `PVE_*` in `mcp.json` `env`                                   |
| HTTP 403 on cluster config / network       | Run `pve_check_token`; assign role to **token** at `/` (step 6)   |
| User in group but token still 403          | Privilege separation on — token ACL is separate from group ACL    |
| Poetry / script errors                     | `./deploy/mcp.sh update`; set `cwd` to repo root                  |
| TLS errors                                 | `PVE_VERIFY_SSL=false` only during initial self-signed cert setup |

---

## Rotate token

1. **Permissions → API Tokens → Add** — new token e.g. `cursor-2` for `mcp-agent@pam`
2. **Permissions → Add** — assign `MCPAgentRead` to `mcp-agent@pam!cursor-2` at `/`
3. Update `PVE_TOKEN_ID` / `PVE_TOKEN_SECRET` in `~/.cursor/mcp.json`
4. Revoke the old token

---

## Network

- Tailscale MagicDNS to `:8006` (TLS from `setup-pve-node.sh` step 17)
- Or LAN via pfSense subnet route (`deploy/tailscale-pfsense-lan.sh`)
- `PVE_VERIFY_SSL=false` only for default self-signed cert during initial setup

---

## References

- [REQUIREMENTS.md](../REQUIREMENTS.md) — TR-016, NFR-001
- [Proxmox user management](https://pve.proxmox.com/pve-docs/chapter-pveum.html)
- [Proxmox API tokens](https://pve.proxmox.com/pve-docs/chapter-pveum.html#pveum_tokens)
- [mcp/README.md](../../README.md) — install automation
