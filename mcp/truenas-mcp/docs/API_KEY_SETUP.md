# TrueNAS — API key setup for MCP

Create a dedicated local user and API key on TrueNAS. **Do not** use the primary admin account for automation if avoidable.

## 1. Prerequisites

- TrueNAS SCALE **25.04+** (WebSocket API at `wss://host/websocket`)
- HTTPS enabled on TrueNAS (port **443**)
- Workstation can reach TrueNAS on LAN (`172.16.0.100`) or Tailscale

## 2. Create service user (recommended)

1. **Credentials → Users → Add**
2. Username: `mcp-cursor-agent` (example)
3. Grant **minimum** privileges needed for read-only inspection (or full read for homelab simplicity)
4. Disable shell / SMB if not required

## 3. Generate API key

1. Log into TrueNAS WebUI
2. User icon (top-right) → **My API Keys** → **Add**
3. Name: `mcp-cursor-agent` (or per-user key under the service account)
4. Optionally set **expiration** (uncheck non-expiring for long-lived lab keys)
5. **Copy the key immediately** — shown once only

## 4. Configure MCP

In `~/.cursor/mcp.json` (after `./deploy/mcp.sh cursor-sync`):

```json
"truenas": {
  "env": {
    "TRUENAS_HOST": "172.16.0.100",
    "TRUENAS_API_KEY": "paste-key-here",
    "TRUENAS_VERIFY_SSL": "false"
  }
}
```

Or export for CLI smoke tests:

```bash
export TRUENAS_HOST=172.16.0.100
export TRUENAS_API_KEY='your-key'
export TRUENAS_VERIFY_SSL=false
poetry run truenas-mcp-smoke
```

## 5. Security rules

| Rule            | Detail                                                               |
| --------------- | -------------------------------------------------------------------- |
| **wss:// only** | Keys sent over `http://` or `ws://` are **revoked** (TrueNAS 25.10+) |
| Rotation        | Delete old keys in UI; generate new; update `mcp.json`               |
| Storage         | Never commit keys; `cursor-sync` preserves existing env secrets      |
| Network         | Restrict `:443` to lab LAN / Tailscale via pfSense if possible       |
| 2FA             | Does not apply to API keys — treat keys like passwords               |

## 6. WebSocket path troubleshooting

If auth or connect fails after a TrueNAS upgrade, try:

```json
"TRUENAS_WS_PATH": "/api/v2.0/websocket"
```

Default for SCALE 25.04+ is `/websocket`.

## 7. Verify

```bash
./deploy/mcp.sh smoke --server truenas-mcp
```

Or in Cursor, call MCP tool **`truenas_run_smoke_tests`**.

## 8. Related

- [REQUIREMENTS.md](./REQUIREMENTS.md)
- [TIPSNTRICKS — TrueNAS NFS + HA](../../../docs/TIPSNTRICKS.md)
- Official alternative: [truenas/truenas-mcp](https://github.com/truenas/truenas-mcp)
