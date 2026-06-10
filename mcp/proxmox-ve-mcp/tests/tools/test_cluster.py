"""Tests for cluster MCP tools."""

import httpx
import pytest
import respx

from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import init_context
from proxmox_ve_mcp.tools.cluster import (
    pve_cluster_health_impl,
    pve_get_version_impl,
    pve_list_nodes_impl,
)


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


@respx.mock
@pytest.mark.asyncio
async def test_pve_get_version_tool(init_pve) -> None:
    respx.get("https://pve.local:8006/api2/json/version").mock(
        return_value=httpx.Response(200, json={"data": {"version": "8.3.1"}})
    )
    result = await pve_get_version_impl()
    assert '"ok": true' in result
    assert "8.3.1" in result


@respx.mock
@pytest.mark.asyncio
async def test_pve_list_nodes_tool(init_pve) -> None:
    respx.get("https://pve.local:8006/api2/json/cluster/resources").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"type": "node", "node": "pvenode-001", "status": "online"},
                    {"type": "node", "node": "pvenode-002", "status": "offline"},
                ]
            },
        )
    )
    result = await pve_list_nodes_impl()
    assert "pvenode-001" in result
    assert '"count": 2' in result


@respx.mock
@pytest.mark.asyncio
async def test_pve_cluster_health_tool(init_pve) -> None:
    respx.get(
        "https://pve.local:8006/api2/json/cluster/resources",
        params={"type": "node"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"type": "node", "node": "pvenode-001", "status": "online"},
                ]
            },
        )
    )
    respx.get("https://pve.local:8006/api2/json/cluster/config/nodes").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"node": "pvenode-001", "ring0_addr": "10.0.0.11"}]},
        )
    )
    result = await pve_cluster_health_impl()
    assert '"approx_all_nodes_online": true' in result
