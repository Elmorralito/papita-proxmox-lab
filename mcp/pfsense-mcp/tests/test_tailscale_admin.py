"""Tests for Tailscale Admin API fallback."""

import httpx
import pytest
import respx

from pfsense_mcp.client.tailscale_admin import fetch_tailscale_routes_via_admin


@pytest.mark.asyncio
@respx.mock
async def test_fetch_tailscale_routes_via_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAILSCALE_API_KEY", "tskey-api-test")
    monkeypatch.setenv("TAILSCALE_TAILNET", "example.ts.net")
    monkeypatch.setenv("PFSENSE_NAME", "pfsense-fw001")

    respx.get("https://api.tailscale.com/api/v2/tailnet/example.ts.net/devices").mock(
        return_value=httpx.Response(
            200,
            json={
                "devices": [
                    {"id": "dev123", "name": "pfsense-fw001.example.ts.net", "hostname": "pfsense-fw001"},
                ]
            },
        )
    )
    respx.get("https://api.tailscale.com/api/v2/device/dev123/routes").mock(
        return_value=httpx.Response(
            200,
            json={
                "advertisedRoutes": ["172.16.0.0/16"],
                "enabledRoutes": ["172.16.0.0/16"],
            },
        )
    )

    data = await fetch_tailscale_routes_via_admin()
    assert data["advertised_routes"] == ["172.16.0.0/16"]
    assert data["source"] == "tailscale_admin_api"
