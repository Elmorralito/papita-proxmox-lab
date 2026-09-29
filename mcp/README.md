# MCP servers — installation and updates

This directory holds [Model Context Protocol](https://modelcontextprotocol.io/) servers used by **Cursor** (and other MCP clients) to operate the lab without ad-hoc SSH.

| Package                                | Cursor server id | Purpose                                                                              |
| -------------------------------------- | ---------------- | ------------------------------------------------------------------------------------ |
| [`proxmox-ve-mcp/`](./proxmox-ve-mcp/) | `proxmox-ve`     | Proxmox VE REST API (`:8006`) — cluster read + gated guest power                     |
| [`pfsense-mcp/`](./pfsense-mcp/)       | `pfsense`        | pfSense pfREST (`:443`) — read-only firewall / Tailscale inspect + lab policy verify |
| [`truenas-mcp/`](./truenas-mcp/)       | `truenas`        | TrueNAS WebSocket API — storage health, Scrutiny app, gated writes                   |

**pfSense CLIs** (install via `./deploy/mcp.sh install`): `pfsense-mcp-smoke`, `pfsense-mcp-bootstrap` (REST API Allowed Interfaces), `pfsense-mcp-firewall` (Tailscale-tab rules). See [pfsense-mcp/docs/POLICY.md](./pfsense-mcp/docs/POLICY.md).

---

## Quick install (automation)

From the **repo root**:

```bash
chmod +x deploy/mcp.sh   # once
./deploy/mcp.sh install                 # Poetry venv + sync user + project mcp.json + skills
# Edit ~/.cursor/mcp.json → set API secrets (project .cursor/mcp.json is seeded from user)
./deploy/mcp.sh smoke --extended
```

Reload **Cursor** after install. In Settings → MCP, confirm servers are green.

### Project vs user scope

Python packages always land in the **repo Poetry venv** (`poetry run …` with `cwd` = repo root). `--scope` chooses which Cursor config file(s) get `command` / `args` / `cwd` merges (existing `env` secrets are preserved) and whether agent skills are copied to the user skills directory:

| Scope | Cursor config | Skills |
| ----- | ------------- | ------ |
| `user` | `~/.cursor/mcp.json` | Copy → `~/.cursor/skills/` |
| `project` | `.cursor/mcp.json` | Use in-repo `.cursor/skills/` only |
| `both` (default for install/update) | user + project | project source + user copies |

Bundled skills (teach agents when to invoke MCPs):

| Skill | Role |
| ----- | ---- |
| `papita-proxmox-lab-map` | Repo map / file inventory |
| `proxmox-ve-mcp` | Invoke `proxmox-ve` MCP |
| `truenas-mcp` | Invoke `truenas` MCP |

```bash
./deploy/mcp.sh install --scope user
./deploy/mcp.sh install --scope project
./deploy/mcp.sh install --scope both      # default
./deploy/mcp.sh install --no-sync         # packages only; sync mcp.json later
./deploy/mcp.sh install --no-skills       # skip skill copies
./deploy/mcp.sh skills-sync               # refresh skills only
```

---

## `deploy/mcp.sh` actions

| Action        | What it does                                                                                            |
| ------------- | ------------------------------------------------------------------------------------------------------- |
| `list`        | Show packages under `mcp/`, Cursor server names, and bundled skills                         |
| `install`     | `poetry lock` + `poetry install --with test`; `pip install -e` each MCP; sync mcp.json; install skills |
| `update`      | Same reinstall as install, then refresh mcp.json + skills for `--scope` (run after `git pull`) |
| `test`        | `pytest` for MCP test suites                                                                            |
| `smoke`       | Run post-install smoke tests (loads creds from `~/.cursor/mcp.json`)                                    |
| `cursor-sync` | Merge each `mcp/*/mcp.json.example` into Cursor MCP configs (preserves existing `env` secrets)          |
| `skills-sync` | Install/refresh `.cursor/skills/{papita-proxmox-lab-map,proxmox-ve-mcp,truenas-mcp}` for `--scope`     |

**Auto-sync (recommended once per clone):**

```bash
./deploy/install-git-hooks.sh
```

This installs:

- **Git hooks** (`post-merge`, `post-checkout`) — refresh MCP configs after `git pull`
- **Cursor `sessionStart` hook** — sync when an agent session opens in this repo

Both run `./deploy/mcp.sh cursor-sync --all-targets --if-changed --enable-agent` (`--all-targets` ≡ `--scope both`), which updates:

| Target | Used by |
| ------ | ------- |
| `~/.cursor/mcp.json` | cursor-agent CLI, Cursor IDE (user-level) |
| `.cursor/mcp.json` | cursor-agent when `--workspace` is this repo (project-level) |

The first project sync seeds `.cursor/mcp.json` from your user config so secrets carry over. Edit API tokens once in `~/.cursor/mcp.json`; later syncs preserve them.

### Options

```bash
./deploy/mcp.sh install --server proxmox-ve-mcp   # one package only
./deploy/mcp.sh update --scope user               # refresh packages + user mcp.json + skills
./deploy/mcp.sh skills-sync --scope both          # skills only
./deploy/mcp.sh smoke --extended                   # proxmox-ve full matrix
./deploy/mcp.sh smoke --server truenas-mcp         # TrueNAS WebSocket auth
./deploy/mcp.sh cursor-sync --scope both
./deploy/mcp.sh cursor-sync --all-targets          # same as --scope both
./deploy/mcp.sh cursor-sync --cursor-config ~/.cursor/mcp.json
./deploy/mcp.sh cursor-sync --scope both --if-changed --enable-agent
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
./deploy/mcp.sh update            # reinstall + sync user+project mcp.json
# Or: ./deploy/mcp.sh update --scope project
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
- `cursor-sync` / install sync updates `command`, `args`, and `cwd` but **keeps existing `env`** values when a server is already configured.

---

## Troubleshooting

| Issue                                     | Fix                                                             |
| ----------------------------------------- | --------------------------------------------------------------- |
| `Command not found: proxmox-ve-mcp-smoke` | `./deploy/mcp.sh install`                                       |
| MCP not visible in Cursor                 | Reload Cursor; check `~/.cursor/mcp.json` / `.cursor/mcp.json`  |
| Poetry wrong Python                       | Requires 3.11+; run from repo root                              |
| Smoke test 403                            | Fix token ACL — run `pve_check_token` or see PVE_TOKEN_SETUP.md |
| `ModuleNotFoundError`                     | `./deploy/mcp.sh update`                                        |

Package-specific docs: [proxmox-ve-mcp/README.md](./proxmox-ve-mcp/README.md), [pfsense-mcp/README.md](./pfsense-mcp/README.md), [truenas-mcp/README.md](./truenas-mcp/README.md).
