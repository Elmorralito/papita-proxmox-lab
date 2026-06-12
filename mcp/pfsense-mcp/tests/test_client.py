"""Tests for pfREST HTTP client."""

import httpx
import pytest
import respx

from pfsense_mcp.client.errors import PfsApiError
from pfsense_mcp.client.http import PfsClient
from pfsense_mcp.config import PfsSettings


@pytest.fixture
async def client() -> PfsClient:
    settings = PfsSettings(host="172.16.0.1", api_key="test-key", verify_ssl=False)
    instance = PfsClient(settings)
    yield instance
    await instance.aclose()


@respx.mock
@pytest.mark.asyncio
async def test_get_version_unwraps_data(client: PfsClient) -> None:
    route = respx.get("https://172.16.0.1:443/api/v2/system/version").mock(
        return_value=httpx.Response(
            200,
            json={"code": 200, "status": "ok", "data": {"version": "26.03"}},
        )
    )
    data = await client.get("/system/version")
    assert route.called
    assert data["version"] == "26.03"


@respx.mock
@pytest.mark.asyncio
async def test_pfrest_error_code(client: PfsClient) -> None:
    respx.get("https://172.16.0.1:443/api/v2/firewall/rules").mock(
        return_value=httpx.Response(
            200,
            json={"code": 403, "status": "error", "message": "permission denied", "data": None},
        )
    )
    with pytest.raises(PfsApiError) as exc_info:
        await client.get("/firewall/rules")
    assert exc_info.value.pfrest_code == 403


@respx.mock
@pytest.mark.asyncio
async def test_http_403_includes_hint(client: PfsClient) -> None:
    respx.get("https://172.16.0.1:443/api/v2/interfaces").mock(
        return_value=httpx.Response(
            403,
            json={
                "message": "The requested action is not allowed by admin policy",
                "response_id": "ENDPOINT_INTERFACE_NOT_ALLOWED",
            },
        )
    )
    with pytest.raises(PfsApiError) as exc_info:
        await client.get("/interfaces")
    payload = exc_info.value.to_dict()
    assert payload["code"] == "PFS_FORBIDDEN"
    assert "hint" in payload
    assert payload["pfrest_response_id"] == "ENDPOINT_INTERFACE_NOT_ALLOWED"


@respx.mock
@pytest.mark.asyncio
async def test_patch_restapi_settings(client: PfsClient) -> None:
    route = respx.patch("https://172.16.0.1:443/api/v2/system/restapi/settings").mock(
        return_value=httpx.Response(
            200,
            json={"code": 200, "status": "ok", "data": {"allowed_interfaces": []}},
        )
    )
    data = await client.patch("/system/restapi/settings", json_body={"allowed_interfaces": []})
    assert route.called
    assert data["allowed_interfaces"] == []


@respx.mock
@pytest.mark.asyncio
async def test_http_404_non_json(client: PfsClient) -> None:
    respx.get("https://172.16.0.1:443/api/v2/vpn/tailscale/settings").mock(
        return_value=httpx.Response(404, text="<html>not found</html>")
    )
    with pytest.raises(PfsApiError) as exc_info:
        await client.get("/vpn/tailscale/settings")
    assert exc_info.value.status_code == 404
    assert "404" in str(exc_info.value)
