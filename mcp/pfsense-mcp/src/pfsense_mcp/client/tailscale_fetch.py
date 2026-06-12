"""Fetch Tailscale status via pfREST (if available) or Tailscale Admin API."""

from __future__ import annotations

from typing import Any

from pfsense_mcp.client.errors import PfsApiError
from pfsense_mcp.client.http import PfsClient
from pfsense_mcp.client.tailscale_admin import fetch_tailscale_routes_via_admin, tailscale_admin_configured
from pfsense_mcp.constants import EP_TAILSCALE_CANDIDATES


async def fetch_tailscale_settings(client: PfsClient) -> Any:
    """Return Tailscale settings from pfREST or Tailscale Admin API fallback."""
    last_error: PfsApiError | None = None
    for path in EP_TAILSCALE_CANDIDATES:
        try:
            return await client.get(path)
        except PfsApiError as exc:
            if exc.status_code == 404:
                last_error = exc
                continue
            raise

    if tailscale_admin_configured():
        return await fetch_tailscale_routes_via_admin()

    if last_error is not None:
        raise PfsApiError(
            "Tailscale settings are not exposed by pfREST on this firewall (HTTP 404 on all known paths). "
            "Set TAILSCALE_API_KEY and TAILSCALE_TAILNET for Admin API fallback, or run "
            "./deploy/tailscale-pfsense-lan.sh verify",
            status_code=404,
            pfrest_response_id=last_error.pfrest_response_id,
            endpoint=last_error.endpoint,
            host=last_error.host,
        ) from last_error

    raise PfsApiError(
        "Tailscale settings are not exposed by pfREST and Tailscale Admin API is not configured.",
        status_code=404,
    )
