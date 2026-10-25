"""Unit tests for NFS client listing and job polling."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from truenas_mcp.client.jobs import wait_for_job
from truenas_mcp.config import TnasSettings
from truenas_mcp.tools.sharing import normalize_nfs_clients, truenas_list_nfs_clients_impl

SETTINGS = TnasSettings(host="172.16.0.100", api_key="test-key")

NFS4_PVE001 = {
    "id": "1",
    "info": {
        "address": '"172.16.0.101:780"',
        "status": "confirmed",
        "name": '"Linux NFSv4.1 pve-001"',
        "minor version": 1,
    },
}
NFS4_STALE = {"id": "2", "info": {"address": "172.16.0.102:781", "status": "courtesy", "minor version": 1}}
NFS3_UNKNOWN = {"ip": "172.16.0.50", "export": "/mnt/main_data_storage"}


def test_pve_node_by_ip_default_map() -> None:
    assert SETTINGS.pve_node_by_ip["172.16.0.101"] == "pve-001"
    assert len(SETTINGS.pve_node_by_ip) == 4


def test_normalize_nfs_clients() -> None:
    clients = normalize_nfs_clients([NFS3_UNKNOWN], [NFS4_PVE001, NFS4_STALE], SETTINGS.pve_node_by_ip)
    by_ip = {c["ip"]: c for c in clients}
    assert by_ip["172.16.0.101"]["node"] == "pve-001"
    assert by_ip["172.16.0.101"]["nfs_version"] == "4.1"
    assert by_ip["172.16.0.101"]["name"] == "Linux NFSv4.1 pve-001"
    assert by_ip["172.16.0.102"]["stale"] is True
    assert by_ip["172.16.0.50"]["node"] is None
    assert by_ip["172.16.0.50"]["nfs_version"] == 3


@pytest.mark.asyncio
async def test_list_nfs_clients_tool() -> None:
    async def fake_call(method: str, params: list[Any] | None = None) -> Any:
        if method == "nfs.get_nfs3_clients":
            return [NFS3_UNKNOWN]
        if method == "nfs.get_nfs4_clients":
            return [NFS4_PVE001, NFS4_STALE]
        raise AssertionError(method)

    client = AsyncMock()
    client.call.side_effect = fake_call
    with (
        patch("truenas_mcp.tools.sharing.get_settings", return_value=SETTINGS),
        patch("truenas_mcp.tools.sharing.get_client", return_value=client),
    ):
        payload = json.loads(await truenas_list_nfs_clients_impl())

    data = payload["data"]
    assert payload["ok"] is True
    assert data["count"] == 3
    assert data["active_count"] == 2
    assert data["nodes_connected"] == ["pve-001"]
    assert data["unknown_ips"] == ["172.16.0.50"]
    assert any("stale" in w for w in payload["warnings"])


@pytest.mark.asyncio
async def test_list_nfs_clients_partial_failure_warns() -> None:
    async def fake_call(method: str, params: list[Any] | None = None) -> Any:
        if method == "nfs.get_nfs3_clients":
            raise RuntimeError("method not found")
        return [NFS4_PVE001]

    client = AsyncMock()
    client.call.side_effect = fake_call
    with (
        patch("truenas_mcp.tools.sharing.get_settings", return_value=SETTINGS),
        patch("truenas_mcp.tools.sharing.get_client", return_value=client),
    ):
        payload = json.loads(await truenas_list_nfs_clients_impl())
    assert payload["ok"] is True
    assert payload["data"]["nodes_connected"] == ["pve-001"]
    assert any("nfs.get_nfs3_clients" in w for w in payload["warnings"])


@pytest.mark.asyncio
async def test_list_nfs_clients_total_failure_is_error() -> None:
    client = AsyncMock()
    client.call.side_effect = RuntimeError("boom")
    with (
        patch("truenas_mcp.tools.sharing.get_settings", return_value=SETTINGS),
        patch("truenas_mcp.tools.sharing.get_client", return_value=client),
    ):
        payload = json.loads(await truenas_list_nfs_clients_impl())
    assert payload["ok"] is False


@pytest.mark.asyncio
async def test_wait_for_job_filters_by_id() -> None:
    client = AsyncMock()
    client.call.return_value = [{"id": 7, "state": "SUCCESS"}]
    job = await wait_for_job(client, 7, timeout_sec=5)
    assert job["state"] == "SUCCESS"
    client.call.assert_awaited_with("core.get_jobs", [[["id", "=", 7]]])
