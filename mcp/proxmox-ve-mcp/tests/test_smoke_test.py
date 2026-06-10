"""Tests for post-install smoke test suite."""

import httpx
import pytest
import respx

from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import init_context
from proxmox_ve_mcp.tools.smoke_test import (
    AccessLevel,
    run_smoke_tests,
    pve_run_smoke_tests_impl,
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


def _mock_basic_cluster(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("https://pve.local:8006/api2/json/version").mock(
        return_value=httpx.Response(200, json={"data": {"version": "8.3.1", "release": "8.3"}})
    )
    respx_mock.get("https://pve.local:8006/api2/json/access/permissions").mock(
        return_value=httpx.Response(200, json={"data": {"/": {"Sys.Audit": 1, "VM.Audit": 1}}})
    )
    respx_mock.get("https://pve.local:8006/api2/json/cluster/resources").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"type": "node", "node": "pvenode-001", "status": "online"},
                    {"type": "node", "node": "pvenode-002", "status": "online"},
                ]
            },
        )
    )


@respx.mock
@pytest.mark.asyncio
async def test_smoke_tests_basic_pass(init_pve) -> None:
    _mock_basic_cluster(respx)
    report = await run_smoke_tests(extended=False)
    assert report["all_passed"] is True
    assert report["access_level"] == AccessLevel.READ_BASIC.value
    assert report["summary"]["failed"] == 0
    assert len(report["tests"]) == 6


@respx.mock
@pytest.mark.asyncio
async def test_smoke_tests_extended_full_access(init_pve) -> None:
    _mock_basic_cluster(respx)
    respx.get("https://pve.local:8006/api2/json/cluster/config/nodes").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"node": "pvenode-001", "ring0_addr": "172.16.0.101"}]},
        )
    )
    respx.get("https://pve.local:8006/api2/json/nodes/pvenode-001/network/vmbr0").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"iface": "vmbr0", "address": "172.16.0.101/24", "type": "bridge"}},
        )
    )
    respx.get("https://pve.local:8006/api2/json/nodes/pvenode-001/status").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"uptime": 3600, "cpu": 0.05, "memory": {"used": 1, "total": 32}}},
        )
    )
    respx.get("https://pve.local:8006/api2/json/storage").mock(
        return_value=httpx.Response(200, json={"data": [{"storage": "local-lvm", "type": "lvm"}]})
    )
    respx.get("https://pve.local:8006/api2/json/nodes/pvenode-001/ceph/status").mock(
        return_value=httpx.Response(501, json={"data": None})
    )

    report = await run_smoke_tests(extended=True)
    assert report["summary"]["failed"] == 0
    assert report["access_level"] == AccessLevel.READ_FULL.value
    ids = {t["id"] for t in report["tests"]}
    assert "cluster_config_nodes" in ids
    assert "ceph_status" in ids


@respx.mock
@pytest.mark.asyncio
async def test_smoke_tests_auth_failure(init_pve) -> None:
    respx.get("https://pve.local:8006/api2/json/version").mock(
        return_value=httpx.Response(401, json={"data": None, "message": "authentication failure"})
    )
    report = await run_smoke_tests(extended=False)
    assert report["all_passed"] is False
    assert report["access_level"] == AccessLevel.NONE.value


@respx.mock
@pytest.mark.asyncio
async def test_pve_run_smoke_tests_tool(init_pve) -> None:
    _mock_basic_cluster(respx)
    result = await pve_run_smoke_tests_impl(extended=False)
    assert '"ok": true' in result
    assert "pve_run_smoke_tests" in result
    assert '"all_passed": true' in result
