"""Tests for PVE HTTP client."""

import httpx
import pytest
import respx

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.client.http import PveClient
from proxmox_ve_mcp.config import PveSettings


@pytest.fixture
async def client() -> PveClient:
    settings = PveSettings(
        host="pve.local",
        api_token="mcp-agent@pam!test=secret",
        verify_ssl=False,
    )
    instance = PveClient(settings)
    yield instance
    await instance.aclose()


@respx.mock
@pytest.mark.asyncio
async def test_get_version(client: PveClient) -> None:
    route = respx.get("https://pve.local:8006/api2/json/version").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"version": "8.3.1", "release": "8.3"}},
        )
    )
    data = await client.get("/version")
    assert route.called
    assert data["version"] == "8.3.1"


@respx.mock
@pytest.mark.asyncio
async def test_api_error_body(client: PveClient) -> None:
    respx.get("https://pve.local:8006/api2/json/cluster/resources").mock(
        return_value=httpx.Response(
            403,
            json={"data": None, "errors": {"userid": "permission denied"}},
        )
    )
    with pytest.raises(PveApiError) as exc_info:
        await client.get("/cluster/resources")
    assert exc_info.value.status_code == 403
