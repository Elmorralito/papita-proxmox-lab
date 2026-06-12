"""Optional Tailscale Admin API fallback when pfREST has no Tailscale endpoint."""

from __future__ import annotations

import os
from typing import Any

import httpx

from pfsense_mcp.constants import LAB_LAN_CIDR, PFS_TAILSCALE_DEVICE_NAME

TAILSCALE_API_BASE = "https://api.tailscale.com/api/v2"


def tailscale_admin_configured() -> bool:
    """Return whether Tailscale Admin API credentials are present in the environment."""
    return bool(os.environ.get("TAILSCALE_API_KEY", "").strip() and os.environ.get("TAILSCALE_TAILNET", "").strip())


def _tailscale_env() -> tuple[str, str]:
    """Load Tailscale Admin API credentials from the environment."""
    api_key = os.environ.get("TAILSCALE_API_KEY", "").strip()
    tailnet = os.environ.get("TAILSCALE_TAILNET", "").strip()
    if not api_key or not tailnet:
        raise RuntimeError(
            "Tailscale Admin API not configured (set TAILSCALE_API_KEY and TAILSCALE_TAILNET). "
            "pfREST does not expose Tailscale settings on most builds."
        )
    return api_key, tailnet


def _device_name() -> str:
    """Resolve the pfSense device name used for Tailscale Admin API lookups."""
    return os.environ.get("PFSENSE_NAME", PFS_TAILSCALE_DEVICE_NAME).strip() or PFS_TAILSCALE_DEVICE_NAME


async def fetch_tailscale_routes_via_admin() -> dict[str, Any]:
    """Return pfSense Tailscale route data from the Tailscale Admin API."""
    api_key, tailnet = _tailscale_env()
    device_name = _device_name()
    timeout = httpx.Timeout(30.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        devices_resp = await client.get(
            f"{TAILSCALE_API_BASE}/tailnet/{tailnet}/devices",
            auth=(api_key, ""),
        )
        if devices_resp.status_code == 401:
            raise RuntimeError(
                "Tailscale Admin API rejected TAILSCALE_API_KEY (HTTP 401). "
                "Regenerate at https://login.tailscale.com/admin/settings/keys "
                "(prefix tskey-api-) and update repo .env"
            )
        devices_resp.raise_for_status()
        devices_payload = devices_resp.json()

        device_id = _find_device_id(devices_payload.get("devices") or [], device_name)
        if not device_id:
            raise RuntimeError(f"Tailscale device matching '{device_name}' not found in tailnet {tailnet}")

        routes_resp = await client.get(
            f"{TAILSCALE_API_BASE}/device/{device_id}/routes",
            auth=(api_key, ""),
        )
        routes_resp.raise_for_status()
        routes_payload = routes_resp.json()

    advertised = [str(item) for item in routes_payload.get("advertisedRoutes") or [] if item]
    enabled = [str(item) for item in routes_payload.get("enabledRoutes") or [] if item]
    return {
        "enabled": True,
        "authenticated": True,
        "advertised_routes": advertised,
        "accept_routes": LAB_LAN_CIDR in enabled,
        "device_name": device_name,
        "source": "tailscale_admin_api",
        "enabled_routes": enabled,
    }


def _find_device_id(devices: list[dict[str, Any]], needle: str) -> str | None:
    """Find a Tailscale device ID by partial hostname or name match."""
    lowered = needle.lower()
    for device in devices:
        name = str(device.get("name") or "").lower()
        hostname = str(device.get("hostname") or "").lower()
        if lowered in name or lowered in hostname:
            device_id = device.get("id") or device.get("nodeId")
            if device_id:
                return str(device_id)
    return None
