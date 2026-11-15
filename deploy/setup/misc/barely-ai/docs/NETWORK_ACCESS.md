# Network access (LAN + Tailscale, not public)

| Port | Service | Allowed sources |
|------|---------|-----------------|
| 22 | SSH | `172.16.0.0/16`, `100.64.0.0/10` |
| 8080 | Qwen (llama.cpp) | same |
| 8009 | Kev System One | same |

- **Outbound** (WAN): allowed — package/model maintenance.
- **Inbound from public WAN**: denied (host nftables + OpenWrt `wan` forward DROP, no DNAT).
- **OpenWrt**: `tailscale`↔`lan` forwarding enabled; no redirects to this host.
- **Current Tailscale VPN only** (this lab’s tailnet, via OpenWrt subnet router): those nodes can reach this host like LAN clients — host nftables accepts `100.64.0.0/10` on SSH/API ports. Not exposed beyond that VPN / public internet.
- Clients: `http://172.16.0.105:8080` / `:8009` with Bearer keys (`ai-show-keys` / `/etc/llama/secrets`).
- On-host copy: keep in sync with `/home/llama/docs/NETWORK_ACCESS.md`.
