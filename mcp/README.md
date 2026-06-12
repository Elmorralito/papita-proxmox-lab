# MCP servers — installation and updates

This directory holds [Model Context Protocol](https://modelcontextprotocol.io/) servers used by **Cursor** (and other MCP clients) to operate the lab without ad-hoc SSH.

| Package                                | Cursor server id | Purpose                                                                              |
| -------------------------------------- | ---------------- | ------------------------------------------------------------------------------------ |
| [`proxmox-ve-mcp/`](./proxmox-ve-mcp/) | `proxmox-ve`     | Proxmox VE REST API (`:8006`) — cluster read + gated guest power                     |
| [`pfsense-mcp/`](./pfsense-mcp/)       | `pfsense`        | pfSense pfREST (`:443`) — read-only firewall / Tailscale inspect + lab policy verify |

**pfSense CLIs** (install via `./deploy/mcp.sh install`): `pfsense-mcp-smoke`, `pfsense-mcp-bootstrap` (REST API Allowed Interfaces), `pfsense-mcp-firewall` (Tailscale-tab rules). See [pfsense-mcp/docs/POLICY.md](./pfsense-mcp/docs/POLICY.md).

---

## Quick install (automation)

From the **repo root**:

```bash
chmod +x deploy/mcp.sh   # once
./deploy/mcp.sh install
./deploy/mcp.sh cursor-sync
# Edit ~/.cursor/mcp.json → set PVE_TOKEN_SECRET (and host/user if needed)
./deploy/mcp.sh smoke --extended
```

Reload **Cursor** after `cursor-sync`. In Settings → MCP, confirm `proxmox-ve` is green.

---

## `deploy/mcp.sh` actions

| Action        | What it does                                                                                            |
| ------------- | ------------------------------------------------------------------------------------------------------- |
| `list`        | Show packages under `mcp/` and their Cursor server names                                                |
| `install`     | `poetry lock` + `poetry install --with test`; `pip install -e` each MCP package (registers CLI scripts) |
| `update`      | Same as `install` — run after `git pull` when MCP code changed                                          |
| `test`        | `pytest` for MCP test suites                                                                            |
| `smoke`       | Run post-install smoke tests (loads `PVE_*` from `~/.cursor/mcp.json`)                                  |
| `cursor-sync` | Merge each `mcp/*/mcp.json.example` into `~/.cursor/mcp.json` (preserves existing `env` secrets)        |

### Options

```bash
./deploy/mcp.sh install --server proxmox-ve-mcp   # one package only
./deploy/mcp.sh smoke --extended                   # full access-level matrix
./deploy/mcp.sh cursor-sync --cursor-config ~/.cursor/mcp.json
```

---

## Manual install

If you prefer not to use the script:

```bash
cd /path/to/papita-proxmox-lab
poetry install --with test
poetry run pip install -e mcp/proxmox-ve-mcp --no-deps --force-reinstall
```

Copy and edit Cursor config:

```bash
cp mcp/proxmox-ve-mcp/mcp.json.example ~/.cursor/mcp.json
# Replace /absolute/path/... with your repo path and paste API token secret
```

**Important:** set `"cwd"` to the **repo root**, not `mcp/proxmox-ve-mcp`, so Poetry reuses the workspace virtualenv.

---

## Post-install verification

### CLI smoke test

```bash
./deploy/mcp.sh smoke              # basic (6 checks)
./deploy/mcp.sh smoke --extended   # full (13 checks)
```

Or directly (with `PVE_*` exported):

```bash
poetry run proxmox-ve-mcp-smoke --extended
```

### Cursor / agent

Call MCP tool **`pve_run_smoke_tests`** with `extended=true`.

See [proxmox-ve-mcp/docs/SMOKE_TESTS.md](./proxmox-ve-mcp/docs/SMOKE_TESTS.md) for the test catalog and access levels.

---

## Updating after git pull

```bash
git pull
./deploy/mcp.sh update
# Reload Cursor if pyproject.toml or entry points changed
./deploy/mcp.sh smoke --extended
```

---

## Adding a new MCP package

1. Create `mcp/<name>-mcp/` with `pyproject.toml`, `src/`, tests, and `mcp.json.example`.
2. Add path dependency to root [`pyproject.toml`](../pyproject.toml) (optional but recommended).
3. Run `./deploy/mcp.sh install` — discovery picks up any directory with `pyproject.toml`.
4. Document the server in this README table.

---

## Credentials and security

- **Never commit** API tokens or `~/.cursor/mcp.json` with real secrets.
- Proxmox: follow [proxmox-ve-mcp/docs/PVE_TOKEN_SETUP.md](./proxmox-ve-mcp/docs/PVE_TOKEN_SETUP.md) — assign roles to the **API token**, not only the user.
- `cursor-sync` updates `command`, `args`, and `cwd` but **keeps existing `env`** values when a server is already configured.

---

## Troubleshooting

| Issue                                     | Fix                                                             |
| ----------------------------------------- | --------------------------------------------------------------- |
| `Command not found: proxmox-ve-mcp-smoke` | `./deploy/mcp.sh install`                                       |
| MCP not visible in Cursor                 | Reload Cursor; check `~/.cursor/mcp.json` syntax                |
| Poetry wrong Python                       | Requires 3.11+; run from repo root                              |
| Smoke test 403                            | Fix token ACL — run `pve_check_token` or see PVE_TOKEN_SETUP.md |
| `ModuleNotFoundError`                     | `./deploy/mcp.sh update`                                        |

Package-specific docs: [proxmox-ve-mcp/README.md](./proxmox-ve-mcp/README.md), [pfsense-mcp/README.md](./pfsense-mcp/README.md).
