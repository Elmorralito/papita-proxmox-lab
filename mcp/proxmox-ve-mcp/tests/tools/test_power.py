"""Tests for node power tools and the hard guest stop."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import init_context
from proxmox_ve_mcp.tools.guests import pve_stop_guest_impl
from proxmox_ve_mcp.tools.power import pve_shutdown_node_impl, pve_wake_on_lan_impl, qdevice_votes, quorum_impact

BASE = "https://pve.local:8006/api2/json"
FOUR_UP = {"pve-001": 1, "pve-002": 1, "pve-003": 1, "pve-004": 1}


@pytest.fixture
async def init_pve():
    settings = PveSettings(host="pve.local", api_token="mcp-agent@pam!test=secret", verify_ssl=False)
    client = init_context(settings)
    yield
    await client.aclose()


def _status(nodes: dict[str, int], entry: str = "pve-001", quorate: int = 1) -> httpx.Response:
    entries = [{"type": "cluster", "name": "c", "quorate": quorate, "nodes": len(nodes)}]
    entries += [
        {"type": "node", "name": name, "online": online, "local": int(name == entry)} for name, online in nodes.items()
    ]
    return httpx.Response(200, json={"data": entries})


def _mock_cluster(
    nodes: dict[str, int], *, policy: str = "freeze", qdevice: bool = True, ha_current: list[dict] | None = None
) -> None:
    respx.get(f"{BASE}/cluster/status").mock(return_value=_status(nodes))
    respx.get(f"{BASE}/cluster/options").mock(
        return_value=httpx.Response(200, json={"data": {"ha": f"shutdown_policy={policy}"}})
    )
    respx.get(f"{BASE}/cluster/ha/status/current").mock(
        return_value=httpx.Response(200, json={"data": ha_current or []})
    )
    respx.get(f"{BASE}/cluster/config/qdevice").mock(
        return_value=httpx.Response(200, json={"data": {"State": "Connected"} if qdevice else None})
    )


def _mock_guests(node: str, qemu: list[dict] | None = None, lxc: list[dict] | None = None) -> None:
    respx.get(f"{BASE}/nodes/{node}/qemu").mock(return_value=httpx.Response(200, json={"data": qemu or []}))
    respx.get(f"{BASE}/nodes/{node}/lxc").mock(return_value=httpx.Response(200, json={"data": lxc or []}))


def test_quorum_impact_four_nodes_plus_qdevice() -> None:
    members = {"pve-001": "online", "pve-002": "online", "pve-003": "offline", "pve-004": "offline"}
    impact = quorum_impact(members, "pve-002", qdevice_expected=1)
    assert impact["expected_votes"] == 5
    assert impact["quorum_votes"] == 3
    assert impact["online_votes_now"] == 3
    assert impact["quorate_after"] is False


def test_disconnected_qdevice_vote_not_counted() -> None:
    warnings: list[str] = []
    expected, live = qdevice_votes({"configured": True, "status": {"State": "Disconnected"}}, warnings)
    members = dict.fromkeys(("pve-001", "pve-002", "pve-003", "pve-004"), "online")
    impact = quorum_impact(members, "pve-004", expected, live)
    assert (expected, live) == (1, 0)
    assert impact["online_votes_now"] == 4
    assert impact["online_votes_after"] == 3
    assert any("Disconnected" in w for w in warnings)


@respx.mock
@pytest.mark.asyncio
async def test_shutdown_peer_node_submits(init_pve) -> None:
    _mock_cluster(FOUR_UP)
    _mock_guests("pve-004")
    route = respx.post(f"{BASE}/nodes/pve-004/status").mock(return_value=httpx.Response(200, json={"data": None}))

    payload = json.loads(await pve_shutdown_node_impl(node="pve-004", reason="maintenance", confirm=True))

    assert payload["ok"] is True
    assert route.called
    assert b"command=shutdown" in route.calls.last.request.content
    assert payload["data"]["quorum_impact"]["quorate_after"] is True
    assert "offline" in payload["data"]["next_step"]


@respx.mock
@pytest.mark.asyncio
async def test_shutdown_refuses_without_freeze(init_pve) -> None:
    _mock_cluster(FOUR_UP, policy="conditional")
    _mock_guests("pve-004")
    route = respx.post(f"{BASE}/nodes/pve-004/status")

    payload = json.loads(await pve_shutdown_node_impl(node="pve-004", reason="maintenance", confirm=True))

    assert payload["ok"] is False
    assert payload["error"]["code"] == "PVE_POWER_GUARD"
    assert "freeze" in payload["error"]["message"]
    assert not route.called


@respx.mock
@pytest.mark.asyncio
async def test_shutdown_entry_node_needs_allow_flag(init_pve) -> None:
    _mock_cluster(FOUR_UP)
    _mock_guests("pve-001")
    payload = json.loads(await pve_shutdown_node_impl(node="pve-001", reason="maintenance", confirm=True))
    assert payload["ok"] is False
    assert "entry node" in payload["error"]["message"]


@respx.mock
@pytest.mark.asyncio
async def test_shutdown_plan_only_reports_without_confirm(init_pve) -> None:
    _mock_cluster({"pve-001": 1, "pve-002": 1, "pve-003": 0, "pve-004": 0})
    _mock_guests("pve-002", qemu=[{"vmid": 200, "name": "web", "status": "running"}])
    route = respx.post(f"{BASE}/nodes/pve-002/status")

    payload = json.loads(await pve_shutdown_node_impl(node="pve-002", reason="dry run", plan_only=True))

    assert payload["ok"] is True
    assert payload["data"]["would_execute"] is True
    assert payload["data"]["running_guests"][0]["vmid"] == 200
    assert any("loses quorum" in w for w in payload["warnings"])
    assert any("still running" in w for w in payload["warnings"])
    assert not route.called


@respx.mock
@pytest.mark.asyncio
async def test_shutdown_refuses_when_survivor_would_self_fence(init_pve) -> None:
    _mock_cluster(
        {"pve-001": 1, "pve-002": 1, "pve-003": 0, "pve-004": 0},
        ha_current=[{"type": "lrm", "node": "pve-001", "status": "active"}],
    )
    _mock_guests("pve-002")
    route = respx.post(f"{BASE}/nodes/pve-002/status")

    payload = json.loads(await pve_shutdown_node_impl(node="pve-002", reason="maintenance", confirm=True))

    assert payload["ok"] is False
    assert payload["error"]["code"] == "PVE_POWER_GUARD"
    assert "self-fence" in payload["error"]["message"]
    assert not route.called


@respx.mock
@pytest.mark.asyncio
async def test_shutdown_entry_node_api_loss_is_success(init_pve) -> None:
    _mock_cluster({"pve-001": 1, "pve-002": 0, "pve-003": 0, "pve-004": 0})
    _mock_guests("pve-001", qemu=[{"vmid": 100, "name": "router", "status": "running"}])
    respx.post(f"{BASE}/nodes/pve-001/status").mock(side_effect=httpx.ConnectTimeout(""))

    payload = json.loads(
        await pve_shutdown_node_impl(node="pve-001", reason="lab off", confirm=True, allow_entry_host=True)
    )

    assert payload["ok"] is True
    assert payload["data"]["api_lost"] is True
    assert any("LAN router" in w for w in payload["warnings"])


@respx.mock
@pytest.mark.asyncio
async def test_shutdown_requires_confirm(init_pve) -> None:
    payload = json.loads(await pve_shutdown_node_impl(node="pve-004", reason="maintenance"))
    assert payload["ok"] is False
    assert "confirm" in payload["error"]["message"]


@respx.mock
@pytest.mark.asyncio
async def test_wake_all_offline_with_missing_mac_hint(init_pve) -> None:
    respx.get(f"{BASE}/cluster/status").mock(
        return_value=_status({"pve-001": 1, "pve-002": 1, "pve-003": 0, "pve-004": 0})
    )
    respx.post(f"{BASE}/nodes/pve-003/wakeonlan").mock(
        return_value=httpx.Response(200, json={"data": "aa:bb:cc:dd:ee:03"})
    )
    respx.post(f"{BASE}/nodes/pve-004/wakeonlan").mock(
        return_value=httpx.Response(500, json={"message": "No wake on LAN MAC address defined for 'pve-004'!"})
    )

    payload = json.loads(await pve_wake_on_lan_impl(confirm=True, all_offline=True))

    assert payload["ok"] is True
    assert payload["data"]["sent"] == ["pve-003"]
    failed = next(r for r in payload["data"]["results"] if r["node"] == "pve-004")
    assert "pvenode config set -wakeonlan" in failed["hint"]


@respx.mock
@pytest.mark.asyncio
async def test_wake_skips_online_and_rejects_unknown(init_pve) -> None:
    respx.get(f"{BASE}/cluster/status").mock(return_value=_status(FOUR_UP))
    payload = json.loads(await pve_wake_on_lan_impl(confirm=True, nodes=["pve-002"]))
    assert payload["data"]["results"][0]["skipped"] == "already online"

    payload = json.loads(await pve_wake_on_lan_impl(confirm=True, nodes=["pve-099"]))
    assert payload["ok"] is False


@pytest.mark.asyncio
async def test_wake_requires_exactly_one_target(init_pve) -> None:
    payload = json.loads(await pve_wake_on_lan_impl(confirm=True))
    assert payload["ok"] is False
    assert "exactly one" in payload["error"]["message"]


@respx.mock
@pytest.mark.asyncio
async def test_stop_guest_warns_for_infra_vmid(init_pve) -> None:
    route = respx.post(f"{BASE}/nodes/pve-001/qemu/100/status/stop").mock(
        return_value=httpx.Response(200, json={"data": "UPID:pve-001:1:2:3:qmstop:100:root@pam:"})
    )
    payload = json.loads(
        await pve_stop_guest_impl(
            node="pve-001",
            vmid=100,
            guest_type="qemu",
            confirm=True,
            reason="hung router",
            overrule_shutdown=True,
        )
    )
    assert payload["ok"] is True
    assert b"overrule-shutdown=1" in route.calls.last.request.content
    assert any("LAN router" in w for w in payload["warnings"])


@respx.mock
@pytest.mark.asyncio
async def test_stop_guest_ha_warning_and_wait_timeout_keeps_upid(init_pve) -> None:
    upid = "UPID:pve-002:1:2:3:hastop:200:root@pam:"
    respx.get(f"{BASE}/cluster/ha/status/current").mock(
        return_value=httpx.Response(
            200, json={"data": [{"type": "service", "sid": "vm:200", "node": "pve-002", "state": "started"}]}
        )
    )
    respx.post(f"{BASE}/nodes/pve-002/qemu/200/status/stop").mock(
        return_value=httpx.Response(200, json={"data": upid})
    )

    with patch("proxmox_ve_mcp.tools.guests.wait_for_task", AsyncMock(side_effect=TimeoutError("slow"))):
        payload = json.loads(
            await pve_stop_guest_impl(
                node="pve-002",
                vmid=200,
                guest_type="qemu",
                confirm=True,
                reason="hung guest",
                wait_for_completion=True,
            )
        )

    assert payload["ok"] is True, payload
    assert payload["data"]["task"] == {"upid": upid, "finished": False}
    assert any("vm:200 is HA-managed" in w for w in payload["warnings"])
    assert any("pve_wait_for_task" in w for w in payload["warnings"])


@pytest.mark.asyncio
async def test_stop_guest_requires_reason(init_pve) -> None:
    payload = json.loads(
        await pve_stop_guest_impl(node="pve-001", vmid=200, guest_type="qemu", confirm=True, reason=" ")
    )
    assert payload["ok"] is False
    assert "reason" in payload["error"]["message"]
