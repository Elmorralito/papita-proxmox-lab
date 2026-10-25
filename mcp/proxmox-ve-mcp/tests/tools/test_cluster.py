"""Tests for cluster MCP tools."""

import json

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
    respx.get("https://pve.local:8006/api2/json/cluster/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"type": "cluster", "name": "pvecm-test", "nodes": 1, "quorate": 1, "version": 3},
                    {"type": "node", "name": "pvenode-001", "online": 1, "local": 1, "ip": "10.0.0.11"},
                ]
            },
        )
    )
    respx.get("https://pve.local:8006/api2/json/cluster/config/qdevice").mock(
        return_value=httpx.Response(200, json={"data": {"State": "Connected"}})
    )
    result = await pve_cluster_health_impl()
    data = json.loads(result)["data"]
    assert data["approx_all_nodes_online"] is True
    assert data["quorate"] is True
    assert data["entry_node"] == "pvenode-001"
    assert data["cluster_name"] == "pvecm-test"
    assert data["qdevice"] == {"configured": True, "status": {"State": "Connected"}}


@respx.mock
@pytest.mark.asyncio
async def test_pve_cluster_health_not_quorate(init_pve) -> None:
    respx.get("https://pve.local:8006/api2/json/cluster/resources", params={"type": "node"}).mock(
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
    respx.get("https://pve.local:8006/api2/json/cluster/config/nodes").mock(
        return_value=httpx.Response(200, json={"data": [{"node": "pvenode-001"}, {"node": "pvenode-002"}]})
    )
    respx.get("https://pve.local:8006/api2/json/cluster/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"type": "cluster", "name": "pvecm-test", "nodes": 2, "quorate": 0},
                    {"type": "node", "name": "pvenode-001", "online": 1, "local": 1},
                    {"type": "node", "name": "pvenode-002", "online": 0, "local": 0},
                ]
            },
        )
    )
    respx.get("https://pve.local:8006/api2/json/cluster/config/qdevice").mock(
        return_value=httpx.Response(500, json={"data": None, "message": "no qdevice"})
    )
    payload = json.loads(await pve_cluster_health_impl())
    assert payload["ok"] is True
    assert payload["data"]["quorate"] is False
    assert payload["data"]["qdevice"] == {"configured": None}
    assert any("NOT quorate" in w for w in payload["warnings"])
