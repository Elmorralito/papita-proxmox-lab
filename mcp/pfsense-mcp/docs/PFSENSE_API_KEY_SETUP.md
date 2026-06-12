# pfSense REST API — API key setup (pfREST v2)

Create a dedicated local user and API key on pfSense. **Do not** use `admin` or grant `WebCfg - All pages`.

## 1. Install pfREST

See [pfrest.org install guide](https://pfrest.org/INSTALL_AND_CONFIG/). Reinstall after pfSense upgrades.

## 2. Create user `mcp-cursor-agent`

1. **System → User Manager → Add**
2. Username: `mcp-cursor-agent` (local)
3. Do **not** assign `WebCfg - All pages`

## 3. Grant API privileges (read v1)

Assign GET privileges for endpoints used by v1 tools:

| Tool area         | Endpoint (indicative)      |
| ----------------- | -------------------------- |
| Version           | `/system/version`          |
| REST API settings | `/system/restapi/settings` |
| Interfaces        | `/interfaces`              |
| Gateways          | `/routing/gateways`        |
| Firewall rules    | `/firewall/rules`          |

Exact privilege names appear in **System → REST API** after package install. Grant minimum GET only for v1.

**One-time bootstrap:** to clear Allowed Interfaces via API, temporarily grant **PATCH** on `/system/restapi/settings`, run `./deploy/pfsense-restapi-access.sh fix-access`, then revoke PATCH. Or deselect all in WebGUI (§5 Option A).

**Tailscale:** pfREST often has **no** Tailscale endpoint. `pfs_get_tailscale_status` falls back to the Tailscale Admin API when `TAILSCALE_API_KEY` and `TAILSCALE_TAILNET` are set (same as `deploy/tailscale-pfsense-lan.sh`).

## 4. Create API key

1. **System → REST API → Keys** (or POST `/api/v2/auth/key`)
2. Generate key for `mcp-cursor-agent` with:
   - **Hash algorithm:** `sha256` (`PFSENSE_HASH_ALGO`, default)
   - **Length (bytes):** `16` (`PFSENSE_LENGTH_BYTES`, default)
3. Store in `PFSENSE_API_KEY` / `~/.cursor/mcp.json` — never commit
4. Set `PFSENSE_API_USER` to the same username (default `mcp-cursor-agent`) so smoke tests and error hints reference the correct account

## 5. Restrict access

pfREST **Allowed Interfaces** lists WAN/LAN/Localhost only — **Tailscale is not selectable** (package-managed interface group). When `PFSENSE_HOST` is a Tailscale IP (`100.x`), requests fail with 403 unless the receiving interface is allowed.

**Recommended:** leave **Allowed Interfaces empty** (pfREST treats that as “all interfaces”). Restrict instead with Access Lists and firewall rules.

### Option A — WebGUI (one-time)

1. **System → REST API → Settings → Allowed Interfaces** → **deselect all** → Save

### Option B — pfREST PATCH (from LAN or any working path)

Requires `mcp-cursor-agent` **PATCH** privilege on `/system/restapi/settings` (temporarily, or use admin from LAN):

```bash
./deploy/pfsense-restapi-access.sh fix-access
```

Equivalent API call:

```http
PATCH /api/v2/system/restapi/settings
Content-Type: application/json
X-API-Key: ...

{"allowed_interfaces": []}
```

The bootstrap CLI retries **`172.16.0.1`** when the primary host returns 403 (LAN is usually still in your allowed list).

### Layered restrictions (after empty Allowed Interfaces)

- **System → REST API → Access Lists:** allow your workstation / tailnet source IP
- Firewall rules: allow HTTPS from workstation / Tailscale to pfSense
- Enable login protection (default)

**Tailscale status:** pfREST has no Tailscale endpoint on most builds. Set `TAILSCALE_API_KEY` + `TAILSCALE_TAILNET` in repo `.env` for Admin API fallback in smoke tests and `pfs_get_tailscale_status`.

### Smoke test: `403 admin policy`

This usually means **allowed interfaces** or **access lists**, not a bad API key (401):

| `response_id`                        | Fix                                                                                                                                                                          |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ENDPOINT_INTERFACE_NOT_ALLOWED`     | Clear **Allowed Interfaces** (empty = all interfaces). Tailscale cannot be added to the list. Run `./deploy/pfsense-restapi-access.sh fix-access` or deselect all in WebGUI. |
| `ENDPOINT_CLIENT_NOT_ALLOWED_BY_ACL` | **System → REST API → Access Lists** — add allow rule for client IP                                                                                                          |

### Smoke test: TLS / certificate errors

When `PFSENSE_HOST` is a Tailscale IP, the WebGUI certificate often does not include that IP. Set:

```json
"PFSENSE_VERIFY_SSL": "false"
```

Or use `172.16.0.1` when the lab subnet route is active on your workstation.

## 6. Cursor config

```bash
./deploy/mcp.sh install
./deploy/mcp.sh cursor-sync
# Edit ~/.cursor/mcp.json → set PFSENSE_API_KEY
# Optional: copy repo .env with TAILSCALE_API_KEY for tailscale smoke fallback
./deploy/mcp.sh smoke --server pfsense-mcp
```

`PFSENSE_HOST` must be an **IP address** (lab default `172.16.0.1`), not a hostname.

## 7. Rotate key

Revoke old key in WebGUI, create new key, update `mcp.json`, reload Cursor.
