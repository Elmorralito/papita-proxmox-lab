"""Tests for gated write tools."""

import httpx
import pytest
import respx

from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import init_context
from proxmox_ve_mcp.tools.guests import pve_start_guest_impl, pve_stopall_guests_impl


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


@pytest.mark.asyncio
async def test_start_guest_rejects_without_confirm(init_pve) -> None:
    result = await pve_start_guest_impl(
        node="pvenode-001",
        vmid=101,
        guest_type="qemu",
        confirm=False,
    )
    assert '"ok": false' in result
    assert "confirm must be true" in result


@respx.mock
@pytest.mark.asyncio
async def test_start_guest_with_confirm(init_pve) -> None:
    respx.post("https://pve.local:8006/api2/json/nodes/pvenode-001/qemu/101/status/start").mock(
        return_value=httpx.Response(200, json={"data": "UPID:pvenode-001:001:ABC:start:u@pam:"})
    )
    result = await pve_start_guest_impl(
        node="pvenode-001",
        vmid=101,
        guest_type="qemu",
        confirm=True,
    )
    assert '"ok": true' in result
    assert "UPID:pvenode-001" in result


@respx.mock
@pytest.mark.asyncio
async def test_stopall_guests_with_confirm(init_pve) -> None:
    respx.post("https://pve.local:8006/api2/json/nodes/pvenode-001/stopall").mock(
        return_value=httpx.Response(200, json={"data": "UPID:pvenode-001:002:DEF:stopall:u@pam:"})
    )
    result = await pve_stopall_guests_impl(node="pvenode-001", confirm=True, timeout=60)
    assert '"ok": true' in result
    assert "runbook_ref" in result
