"""Tests for Sprint 2 cluster tools."""

import httpx
import pytest
import respx

from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import init_context
from proxmox_ve_mcp.tools.cluster import (
    pve_get_cluster_config_nodes_impl,
    pve_list_tasks_impl,
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
async def test_pve_get_cluster_config_nodes(init_pve) -> None:
    respx.get("https://pve.local:8006/api2/json/cluster/config/nodes").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"node": "pvenode-001", "ring0_addr": "10.0.0.11", "nodeid": 1},
                ]
            },
        )
    )
    result = await pve_get_cluster_config_nodes_impl()
    assert "pvenode-001" in result
    assert "10.0.0.11" in result


@respx.mock
@pytest.mark.asyncio
async def test_pve_list_tasks(init_pve) -> None:
    respx.get("https://pve.local:8006/api2/json/cluster/tasks").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"upid": "UPID:pvenode-001:001:ABC", "status": "running"}]},
        )
    )
    result = await pve_list_tasks_impl()
    assert "UPID:pvenode-001" in result
