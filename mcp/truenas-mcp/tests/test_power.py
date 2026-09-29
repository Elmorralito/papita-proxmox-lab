"""Unit tests for guarded TrueNAS shutdown/reboot."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from truenas_mcp.client.errors import TnasApiError
from truenas_mcp.config import TnasSettings
from truenas_mcp.tools.power import truenas_reboot_impl, truenas_shutdown_impl

SETTINGS = TnasSettings(host="172.16.0.100", api_key="test-key")
NFS4_PVE001 = {"id": "1", "info": {"address": "172.16.0.101:780", "status": "confirmed", "minor version": 1}}
NFS4_PVE002 = {"id": "2", "info": {"address": "172.16.0.102:781", "status": "confirmed", "minor version": 1}}


def _fake_client(
    *, nfs4: list[dict] | None = None, jobs: list[dict] | None = None, power: Any = 42
) -> AsyncMock:
    calls: list[tuple[str, Any]] = []

    async def fake_call(method: str, params: list[Any] | None = None) -> Any:
        calls.append((method, params))
        if method == "nfs.get_nfs3_clients":
            return []
        if method == "nfs.get_nfs4_clients":
            return nfs4 or []
        if method == "core.get_jobs":
            return jobs or []
        if method.startswith("system."):
            if isinstance(power, Exception):
                raise power
            return power
        raise AssertionError(method)

    client = AsyncMock()
    client.call.side_effect = fake_call
    client.calls = calls
    return client


@pytest.fixture
def patched() -> Iterator[Any]:
    def _install(client: AsyncMock) -> Any:
        return (
            patch("truenas_mcp.tools.power.get_client", return_value=client),
            patch("truenas_mcp.tools.power.get_settings", return_value=SETTINGS),
        )

    yield _install


def _power_calls(client: AsyncMock) -> list[tuple[str, Any]]:
    return [c for c in client.calls if c[0].startswith("system.")]


@pytest.mark.asyncio
async def test_shutdown_allows_expected_entry_node_client(patched) -> None:
    client = _fake_client(nfs4=[NFS4_PVE001])
    p1, p2 = patched(client)
    with p1, p2:
        payload = json.loads(
            await truenas_shutdown_impl(
                "lab off", confirm=True, delay_s=300, expected_clients=["172.16.0.101"]
            )
        )
    assert payload["ok"] is True
    assert payload["data"]["job_id"] == 42
    assert _power_calls(client) == [("system.shutdown", ["lab off", {"delay": 300}])]


@pytest.mark.asyncio
async def test_shutdown_refuses_unexpected_nfs_clients(patched) -> None:
    client = _fake_client(nfs4=[NFS4_PVE001, NFS4_PVE002])
    p1, p2 = patched(client)
    with p1, p2:
        payload = json.loads(
            await truenas_shutdown_impl("lab off", confirm=True, expected_clients=["172.16.0.101"])
        )
    assert payload["ok"] is False
    assert payload["error"]["code"] == "POWER_GUARD"
    assert "172.16.0.102" in payload["error"]["message"]
    assert not _power_calls(client)


@pytest.mark.asyncio
async def test_shutdown_refuses_running_scrub_unless_forced(patched) -> None:
    jobs = [{"id": 9, "method": "pool.scrub.scrub", "state": "RUNNING", "progress": {"percent": 40}}]
    client = _fake_client(jobs=jobs)
    p1, p2 = patched(client)
    with p1, p2:
        refused = json.loads(await truenas_shutdown_impl("lab off", confirm=True))
        forced = json.loads(await truenas_shutdown_impl("lab off", confirm=True, force=True))
    assert refused["ok"] is False
    assert "pool.scrub.scrub" in refused["error"]["message"]
    assert forced["ok"] is True
    assert any("force=true" in w for w in forced["warnings"])


@pytest.mark.asyncio
async def test_plan_only_needs_no_confirm_and_submits_nothing(patched) -> None:
    client = _fake_client(nfs4=[NFS4_PVE002])
    p1, p2 = patched(client)
    with p1, p2:
        payload = json.loads(await truenas_reboot_impl("check", plan_only=True))
    assert payload["ok"] is True
    assert payload["data"]["would_execute"] is False
    assert payload["data"]["action"] == "reboot"
    assert not _power_calls(client)


@pytest.mark.asyncio
async def test_connection_drop_during_shutdown_is_success(patched) -> None:
    client = _fake_client(power=TnasApiError("closed", code="CONNECTION_ERROR", method="system.shutdown"))
    p1, p2 = patched(client)
    with p1, p2:
        payload = json.loads(await truenas_shutdown_impl("lab off", confirm=True))
    assert payload["ok"] is True
    assert payload["data"]["connection_dropped"] is True


@pytest.mark.asyncio
async def test_requires_confirm_and_reason(patched) -> None:
    client = _fake_client()
    p1, p2 = patched(client)
    with p1, p2:
        no_confirm = json.loads(await truenas_shutdown_impl("lab off"))
        no_reason = json.loads(await truenas_shutdown_impl("", confirm=True))
    assert no_confirm["ok"] is False
    assert no_reason["ok"] is False
    assert not _power_calls(client)
