#!/usr/bin/env python3
"""Bootstrap Uptime Kuma: admin account, homelab monitors, optional Telegram (HTML template)."""

from __future__ import annotations

import os
import secrets
import string
import sys
from pathlib import Path

from uptime_kuma_api import MonitorType, NotificationType, UptimeKumaApi

TELEGRAM_TEMPLATE = """{%- assign is_down = false -%}
{%- assign is_up = false -%}
{%- if heartbeatJSON -%}
  {%- if heartbeatJSON.status == 0 -%}
    {%- assign is_down = true -%}
  {%- elsif heartbeatJSON.status == 1 -%}
    {%- assign is_up = true -%}
  {%- endif -%}
{%- endif -%}

{%- if is_down -%}
🚨 <b>ALERT — SERVICE DOWN</b>
{%- elsif is_up -%}
✅ <b>RECOVERED — SERVICE UP</b>
{%- else -%}
⚠️ <b>STATUS UPDATE</b>
{%- endif -%}

━━━━━━━━━━━━━━━━━━━━
<b>Monitor:</b> {{ name }}
<b>Status:</b> {{ status }}
<b>Target:</b> <code>{{ hostnameOrURL }}</code>
<b>Message:</b> {{ msg }}

{%- if heartbeatJSON -%}
{%- if heartbeatJSON.localDateTime -%}
<b>Time:</b> {{ heartbeatJSON.localDateTime }}
{%- endif -%}
{%- if heartbeatJSON.ping -%}
<b>Response:</b> {{ heartbeatJSON.ping }} ms
{%- endif -%}
{%- if heartbeatJSON.retries and heartbeatJSON.retries > 0 -%}
<b>Retries:</b> {{ heartbeatJSON.retries }}
{%- endif -%}
{%- endif -%}

{%- if monitorJSON.type -%}
<b>Type:</b> <code>{{ monitorJSON.type | upcase }}</code>
{%- endif -%}

{%- if is_down -%}
<b>Hints:</b>
{%- if name contains "pfSense" or name contains "Gateway" -%}
 Check WAN, DNS, Tailscale subnet routes
{%- elsif name contains "Proxmox" or name contains "PVE" -%}
 Check quorum: <code>pvecm status</code>
{%- elsif name contains "TrueNAS" or name contains "NAS" -%}
 Check <code>zpool status</code> and Scrutiny
{%- elsif name contains "Internet" -%}
 WAN down while LAN may still work — check pfSense gateway
{%- else -%}
 Compare LAN vs Tailscale monitors if both exist
{%- endif -%}
{%- endif -%}

<i>Homelab • Uptime Kuma</i>"""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _gen_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _parse_ips(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _existing_names(api: UptimeKumaApi) -> set[str]:
    return {m.get("name", "") for m in api.get_monitors()}


def _add_http(
    api: UptimeKumaApi,
    *,
    name: str,
    url: str,
    notification_ids: list[int],
    keyword: str | None = None,
    ignore_tls: bool = False,
    interval: int = 60,
) -> None:
    if name in _existing_names(api):
        print(f"  skip (exists): {name}")
        return
    payload: dict = {
        "type": MonitorType.HTTP,
        "name": name,
        "url": url,
        "interval": interval,
        "retryInterval": 60,
        "maxretries": 2,
        "notificationIDList": notification_ids,
        "ignoreTls": ignore_tls,
    }
    if keyword:
        payload["keyword"] = keyword
    result = api.add_monitor(**payload)
    print(f"  added: {name} (id={result.get('monitorId')})")


def _add_tcp(
    api: UptimeKumaApi,
    *,
    name: str,
    hostname: str,
    port: int,
    notification_ids: list[int],
    interval: int = 60,
) -> None:
    if name in _existing_names(api):
        print(f"  skip (exists): {name}")
        return
    result = api.add_monitor(
        type=MonitorType.TCP,
        name=name,
        hostname=hostname,
        port=port,
        interval=interval,
        retryInterval=60,
        maxretries=2,
        notificationIDList=notification_ids,
    )
    print(f"  added: {name} (id={result.get('monitorId')})")


def _add_dns(
    api: UptimeKumaApi,
    *,
    name: str,
    hostname: str,
    resolver: str,
    notification_ids: list[int],
) -> None:
    if name in _existing_names(api):
        print(f"  skip (exists): {name}")
        return
    result = api.add_monitor(
        type=MonitorType.DNS,
        name=name,
        hostname=hostname,
        port=53,
        dns_resolve_server=resolver,
        dns_resolve_type="A",
        interval=120,
        retryInterval=60,
        maxretries=2,
        notificationIDList=notification_ids,
    )
    print(f"  added: {name} (id={result.get('monitorId')})")


def _ensure_telegram(api: UptimeKumaApi, bot_token: str, chat_id: str) -> list[int]:
    for note in api.get_notifications():
        if note.get("type") == NotificationType.TELEGRAM and note.get("name") == "Homelab Telegram":
            print(f"  reuse notification id={note.get('id')}")
            return [int(note["id"])]

    result = api.add_notification(
        type=NotificationType.TELEGRAM,
        name="Homelab Telegram",
        telegramBotToken=bot_token,
        telegramChatID=chat_id,
        isDefault=True,
        applyExisting=True,
    )
    note_id = int(result["id"])
    print(f"  added Telegram notification id={note_id}")
    # Custom HTML template must be pasted in UI (Settings → Notifications → Homelab Telegram).
    # See docs/TIPSNTRICKS.md § Uptime Kuma — Telegram notification template (HTML).
    _ = TELEGRAM_TEMPLATE  # kept in-script for operators copying into the WebUI
    api.test_notification(
        type=NotificationType.TELEGRAM,
        name="Homelab Telegram",
        telegramBotToken=bot_token,
        telegramChatID=chat_id,
        isDefault=True,
        applyExisting=True,
    )
    print("  Telegram test sent")
    return [note_id]


def _ensure_admin(api: UptimeKumaApi, username: str, password: str, creds_path: Path | None) -> str:
    if api.need_setup():
        if not password:
            password = _gen_password()
        api.setup(username, password)
        print(f"Created admin user '{username}'")
        if creds_path:
            creds_path.parent.mkdir(parents=True, exist_ok=True)
            creds_path.write_text(
                f"UPTIME_KUMA_USERNAME={username}\nUPTIME_KUMA_PASSWORD={password}\n", encoding="utf-8"
            )
            creds_path.chmod(0o600)
            print(f"Credentials saved to {creds_path}")
        return password

    if not password:
        raise SystemExit(
            "UPTIME_KUMA_PASSWORD is required when the instance is already configured "
            "(or set credentials file on the node)."
        )
    api.login(username, password)
    print(f"Logged in as '{username}'")
    return password


def main() -> int:
    url = _env("UPTIME_KUMA_URL", "http://172.16.1.12:3001")
    username = _env("UPTIME_KUMA_USERNAME", "admin")
    password = _env("UPTIME_KUMA_PASSWORD")
    bot_token = _env("TELEGRAM_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")
    pfsense_ip = _env("PFSENSE_IP", "172.16.0.1")
    truenas_ip = _env("TRUENAS_IP", "172.16.0.100")
    pve_ips = _parse_ips(_env("PVE_NODE_IPS", "172.16.0.101,172.16.0.102,172.16.0.103"))
    creds_file = _env("UPTIME_KUMA_CREDENTIALS_FILE", "/root/deploy/misc/monitoring/uptime-kuma.credentials")

    creds_path = Path(creds_file) if creds_file else None

    print(f"Connecting to {url}")
    with UptimeKumaApi(url, ssl_verify=False, timeout=30) as api:
        _ensure_admin(api, username, password, creds_path)

        notification_ids: list[int] = []
        if bot_token and chat_id:
            print("Configuring Telegram…")
            notification_ids = _ensure_telegram(api, bot_token, chat_id)
        else:
            print("Skipping Telegram (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable)")

        print("Adding homelab monitors…")
        _add_http(
            api,
            name="Internet / WAN",
            url="https://1.1.1.1/cdn-cgi/trace",
            notification_ids=notification_ids,
        )
        _add_dns(
            api,
            name="pfSense DNS",
            hostname="google.com",
            resolver=pfsense_ip,
            notification_ids=notification_ids,
        )
        _add_http(
            api,
            name="pfSense GUI",
            url=f"https://{pfsense_ip}",
            notification_ids=notification_ids,
            ignore_tls=True,
        )
        _add_http(
            api,
            name="TrueNAS GUI",
            url=f"https://{truenas_ip}",
            notification_ids=notification_ids,
            ignore_tls=True,
        )
        for idx, ip in enumerate(pve_ips, start=1):
            _add_http(
                api,
                name=f"Proxmox pvenode-{idx:03d}",
                url=f"https://{ip}:8006",
                notification_ids=notification_ids,
                keyword="Proxmox",
                ignore_tls=True,
            )
            _add_tcp(
                api,
                name=f"Proxmox SSH pvenode-{idx:03d}",
                hostname=ip,
                port=22,
                notification_ids=notification_ids,
            )
        _add_tcp(api, name="TrueNAS SMB", hostname=truenas_ip, port=445, notification_ids=notification_ids)
        _add_tcp(api, name="TrueNAS NFS", hostname=truenas_ip, port=2049, notification_ids=notification_ids)
        _add_http(
            api,
            name="Scrutiny",
            url=f"http://{truenas_ip}:31054",
            notification_ids=notification_ids,
        )
        _add_http(
            api,
            name="Tailscale control plane",
            url="https://controlplane.tailscale.com",
            notification_ids=notification_ids,
        )

    print("Bootstrap complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
