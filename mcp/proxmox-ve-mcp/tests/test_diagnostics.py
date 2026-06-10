"""Tests for permission hints and diagnostic tools."""

import httpx
import pytest
import respx

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.client.http import PveClient
from proxmox_ve_mcp.client.permissions import parse_permission_message, permission_hint
from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import init_context
from proxmox_ve_mcp.tools.diagnostics import pve_check_token_impl, pve_list_node_addresses_impl


def test_parse_permission_message() -> None:
    parsed = parse_permission_message("Permission check failed (/, Sys.Audit)\n")
    assert parsed["path"] == "/"
    assert parsed["privilege"] == "Sys.Audit"


def test_permission_hint_includes_token_acl_guidance() -> None:
    hint = permission_hint(
        status_code=403,
        message="Permission check failed (/, Sys.Audit)",
    )
    assert hint is not None
    assert "privilege separation" in hint.lower()


def test_pve_api_error_includes_hint() -> None:
    error = PveApiError(
        "Proxmox API HTTP 403: Permission check failed (/, Sys.Audit)",
        status_code=403,
        pve_message="Permission check failed (/, Sys.Audit)",
        endpoint="/cluster/config/nodes",
    )
    body = error.to_dict()
    assert body["code"] == "PVE_FORBIDDEN"
    assert body["required_privilege"] == "Sys.Audit"
    assert "hint" in body


@pytest.fixture
async def init_pve():
    settings = PveSettings(
        host="pve.local",
        api_token="mcp-agent@pam!test=secret",
        verify_ssl=False,
    )
    client = init_context(settings)
    yield
    await client.aclose()


@pytest.fixture
async def pve_client() -> PveClient:
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
async def test_api_error_includes_pve_message(pve_client: PveClient) -> None:
    respx.get("https://pve.local:8006/api2/json/cluster/config/nodes").mock(
        return_value=httpx.Response(
            403,
            json={"data": None, "message": "Permission check failed (/, Sys.Audit)\n"},
        )
    )
    with pytest.raises(PveApiError) as exc_info:
        await pve_client.get("/cluster/config/nodes")
    assert "Sys.Audit" in str(exc_info.value)
    assert exc_info.value.pve_message is not None


@respx.mock
@pytest.mark.asyncio
async def test_pve_check_token_reports_failed_probes(init_pve) -> None:
    respx.get("https://pve.local:8006/api2/json/version").mock(
        return_value=httpx.Response(200, json={"data": {"version": "8.3.1"}})
    )
    respx.get("https://pve.local:8006/api2/json/access/permissions").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    respx.get("https://pve.local:8006/api2/json/cluster/resources").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"type": "node", "node": "pvenode-001", "status": "online"}]},
        )
    )
    respx.get("https://pve.local:8006/api2/json/cluster/config/nodes").mock(
        return_value=httpx.Response(
            403,
            json={"data": None, "message": "Permission check failed (/, Sys.Audit)\n"},
        )
    )
    respx.get("https://pve.local:8006/api2/json/nodes/pvenode-001/network").mock(
        return_value=httpx.Response(
            403,
            json={"data": None, "message": "Permission check failed (/nodes/pvenode-001, Sys.Audit)\n"},
        )
    )
    respx.get("https://pve.local:8006/api2/json/nodes/pvenode-001/network/nic0").mock(
        return_value=httpx.Response(
            403,
            json={"data": None, "message": "Permission check failed (/nodes/pvenode-001, Sys.Audit)\n"},
        )
    )

    result = await pve_check_token_impl()
    assert '"ok": true' in result
    assert "cluster_config_nodes" in result
    assert "Sys.Audit" in result
    assert "privilege separation" in result.lower()


@respx.mock
@pytest.mark.asyncio
async def test_pve_list_node_addresses_returns_ring0_and_interfaces(init_pve) -> None:
    respx.get("https://pve.local:8006/api2/json/cluster/resources").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"type": "node", "node": "pvenode-001", "status": "online"}]},
        )
    )
    respx.get("https://pve.local:8006/api2/json/cluster/config/nodes").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"node": "pvenode-001", "ring0_addr": "172.16.0.11"}]},
        )
    )
    respx.get("https://pve.local:8006/api2/json/nodes/pvenode-001/network").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"iface": "nic0", "active": 1, "type": "eth"}]},
        )
    )
    respx.get("https://pve.local:8006/api2/json/nodes/pvenode-001/network/nic0").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"iface": "nic0", "address": "172.16.0.11/24", "gateway": "172.16.0.1"}},
        )
    )

    result = await pve_list_node_addresses_impl()
    assert '"ring0_addr": "172.16.0.11"' in result
    assert "172.16.0.11/24" in result
