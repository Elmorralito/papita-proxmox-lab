"""Tests for PVE HTTP client."""

import socket
import ssl

import httpx
import pytest
import respx

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.client.http import PveClient, transport_error
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


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("side_effect", "code"),
    [
        (httpx.ConnectTimeout(""), "PVE_CONNECT_TIMEOUT"),
        (httpx.ReadTimeout(""), "PVE_TIMEOUT"),
        (httpx.ConnectError("[Errno -2] Name or service not known"), "PVE_DNS_ERROR"),
        (httpx.ConnectError("[Errno 111] Connection refused"), "PVE_CONNECTION_REFUSED"),
        (httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]"), "PVE_TLS_ERROR"),
        (httpx.RemoteProtocolError("Server disconnected"), "PVE_CONNECTION_ERROR"),
    ],
)
async def test_transport_errors_have_code_and_message(
    client: PveClient, side_effect: httpx.HTTPError, code: str
) -> None:
    respx.get("https://pve.local:8006/api2/json/cluster/status").mock(side_effect=side_effect)
    with pytest.raises(PveApiError) as exc_info:
        await client.get("/cluster/status")
    body = exc_info.value.to_dict()
    assert body["code"] == code
    assert body["message"] and not body["message"].endswith(": ")
    assert body["hint"]
    assert body["endpoint"] == "/cluster/status"


@pytest.mark.parametrize(
    ("cause", "code"),
    [
        (ssl.SSLCertVerificationError("certificate verify failed"), "PVE_TLS_ERROR"),
        (socket.gaierror(-2, "Name or service not known"), "PVE_DNS_ERROR"),
        (ConnectionRefusedError(111, "refused"), "PVE_CONNECTION_REFUSED"),
    ],
)
def test_transport_error_from_cause_chain(cause: BaseException, code: str) -> None:
    settings = PveSettings(host="pve.local", api_token="mcp-agent@pam!test=secret")
    exc = httpx.ConnectError("")
    exc.__cause__ = cause
    err = transport_error(exc, settings, endpoint="/version", timeout=30)
    assert err.to_dict()["code"] == code
