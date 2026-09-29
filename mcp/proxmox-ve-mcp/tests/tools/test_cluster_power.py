"""Tests for the ordered, resumable cluster shutdown."""

import json
import re
from unittest.mock import patch

import httpx
import pytest
import respx

from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import init_context
from proxmox_ve_mcp.tools.cluster_power import (
    STAGE_BLOCKED,
    STAGE_READY_FOR_NAS,
    STAGE_SHUTDOWN_ENTRY,
    STAGE_SHUTDOWN_PEERS,
    STAGE_STOP_GUESTS,
    ClusterState,
    next_stage,
    pve_shutdown_cluster_impl,
    simulate,
)
from proxmox_ve_mcp.tools.ha import parse_ha_placement

BASE = "https://pve.local:8006/api2/json"
KEEP = frozenset({100})


@pytest.fixture
async def init_pve():
    settings = PveSettings(host="pve.local", api_token="mcp-agent@pam!test=secret", verify_ssl=False)
    client = init_context(settings)
    yield
    await client.aclose()


@pytest.fixture(autouse=True)
def no_sleep():
    async def _instant(_seconds: float) -> None:
        return None

    with patch("proxmox_ve_mcp.client.tasks.asyncio.sleep", _instant):
        yield


def _guest(vmid: int, node: str, guest_type: str = "qemu") -> dict:
    return {"vmid": vmid, "node": node, "guest_type": guest_type, "name": f"g{vmid}"}


def _state(members: dict[str, str], running: list[dict]) -> ClusterState:
    return ClusterState(members=members, entry="pve-001", running=running)


def test_next_stage_order() -> None:
    both = {"pve-001": "online", "pve-002": "online"}
    running = [_guest(100, "pve-001"), _guest(101, "pve-001"), _guest(200, "pve-002")]

    stage = next_stage(_state(both, running), KEEP, include_entry=False)
    assert stage["stage"] == STAGE_STOP_GUESTS
    assert {"op": "stopall", "node": "pve-002"} in stage["actions"]
    assert [a["vmid"] for a in stage["actions"] if a["op"] == "shutdown_guest"] == [101]

    stage = next_stage(_state(both, [_guest(100, "pve-001")]), KEEP, include_entry=False)
    assert stage["stage"] == STAGE_SHUTDOWN_PEERS

    peers_off = {"pve-001": "online", "pve-002": "offline"}
    assert next_stage(_state(peers_off, [_guest(100, "pve-001")]), KEEP, False)["stage"] == STAGE_READY_FOR_NAS
    assert next_stage(_state(peers_off, [_guest(100, "pve-001")]), KEEP, True)["stage"] == STAGE_SHUTDOWN_ENTRY


def test_next_stage_skips_ha_guests() -> None:
    both = {"pve-001": "online", "pve-002": "online", "pve-003": "online"}
    running = [_guest(101, "pve-001"), _guest(200, "pve-002"), _guest(201, "pve-002"), _guest(301, "pve-003")]
    state = _state(both, running)
    state.ha = parse_ha_placement(
        [
            {"type": "service", "sid": "vm:101", "node": "pve-001", "state": "started"},
            {"type": "service", "sid": "vm:201", "node": "pve-002", "state": "started"},
            {"type": "service", "sid": "vm:301", "node": "pve-003", "state": "started"},
        ]
    )

    stage = next_stage(state, KEEP, include_entry=False)

    assert stage["actions"] == [{"op": "shutdown_guest", **_guest(200, "pve-002")}]


def test_keep_guest_on_peer_blocks() -> None:
    stage = next_stage(_state({"pve-001": "online", "pve-002": "online"}, [_guest(100, "pve-002")]), KEEP, False)
    assert stage["stage"] == STAGE_BLOCKED
    assert "100@pve-002" in stage["reason"]


def test_simulate_projects_all_stages() -> None:
    state = _state({"pve-001": "online", "pve-002": "online"}, [_guest(100, "pve-001"), _guest(200, "pve-002")])
    stages = [s["stage"] for s in simulate(state, KEEP, include_entry=True)]
    assert stages == [STAGE_STOP_GUESTS, STAGE_SHUTDOWN_PEERS, STAGE_SHUTDOWN_ENTRY]


class FakeCluster:
    """Stateful respx backend: posts mutate guest/node state."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        running: dict[int, str],
        *,
        stop_works: bool = True,
        policy: str = "freeze",
        ha_current: list[dict] | None = None,
        ha_readable: bool = True,
    ) -> None:
        self.online = {"pve-001": 1, "pve-002": 1}
        self.running = dict(running)
        self.stop_works = stop_works
        self.posts: list[str] = []
        self.bodies: dict[str, bytes] = {}
        self.status_calls = 0
        self.status_fails_after: int | None = None
        self.slow_ack_nodes: set[str] = set()
        ha_route = respx.get(f"{BASE}/cluster/ha/status/current")
        if ha_readable:
            ha_route.mock(return_value=httpx.Response(200, json={"data": ha_current or []}))
        else:
            ha_route.mock(return_value=httpx.Response(403, json={"data": None}))
        respx.get(f"{BASE}/cluster/status").mock(side_effect=self._status)
        respx.get(f"{BASE}/cluster/resources").mock(side_effect=self._resources)
        respx.get(f"{BASE}/cluster/tasks").mock(return_value=httpx.Response(200, json={"data": []}))
        respx.get(f"{BASE}/cluster/options").mock(
            return_value=httpx.Response(200, json={"data": {"ha": f"shutdown_policy={policy}"}})
        )
        respx.get(url__regex=rf"{BASE}/nodes/[^/]+/tasks/.+/status").mock(
            return_value=httpx.Response(200, json={"data": {"status": "stopped", "exitstatus": "OK"}})
        )
        respx.post(url__regex=rf"{BASE}/nodes/.+").mock(side_effect=self._post)

    def _status(self, _request: httpx.Request) -> httpx.Response:
        self.status_calls += 1
        if self.status_fails_after is not None and self.status_calls > self.status_fails_after:
            raise httpx.ConnectTimeout("")
        entries = [{"type": "cluster", "name": "c", "quorate": 1, "nodes": 2}]
        entries += [
            {"type": "node", "name": n, "online": o, "local": int(n == "pve-001"), "ip": f"172.16.0.10{n[-1]}"}
            for n, o in self.online.items()
        ]
        return httpx.Response(200, json={"data": entries})

    def _resources(self, _request: httpx.Request) -> httpx.Response:
        data = [{"vmid": v, "node": n, "type": "qemu", "status": "running"} for v, n in self.running.items()]
        return httpx.Response(200, json={"data": data})

    def _post(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api2/json")
        self.posts.append(path)
        self.bodies[path] = request.content
        if match := re.fullmatch(r"/nodes/([^/]+)/stopall", path):
            if self.stop_works:
                self.running = {v: n for v, n in self.running.items() if n != match.group(1)}
            return httpx.Response(200, json={"data": f"UPID:{match.group(1)}:1:2:3:stopall::root@pam:"})
        if match := re.fullmatch(r"/nodes/([^/]+)/qemu/(\d+)/status/shutdown", path):
            if self.stop_works:
                self.running.pop(int(match.group(2)), None)
            upid = f"UPID:{match.group(1)}:1:2:3:qmshutdown:{match.group(2)}:root@pam:"
            return httpx.Response(200, json={"data": upid})
        if match := re.fullmatch(r"/nodes/([^/]+)/status", path):
            if match.group(1) == "pve-001":
                raise httpx.ConnectTimeout("")
            self.online[match.group(1)] = 0
            if match.group(1) in self.slow_ack_nodes:
                raise httpx.ReadTimeout("", request=request)
            return httpx.Response(200, json={"data": None})
        raise AssertionError(path)


@respx.mock
@pytest.mark.asyncio
async def test_full_run_reaches_ready_for_nas(init_pve) -> None:
    fake = FakeCluster({100: "pve-001", 101: "pve-001", 200: "pve-002"})

    payload = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True))

    assert payload["ok"] is True, payload
    data = payload["data"]
    assert data["stage"] == STAGE_READY_FOR_NAS
    assert data["done"] is True
    assert [h["stage"] for h in data["history"]] == [STAGE_STOP_GUESTS, STAGE_SHUTDOWN_PEERS]
    assert "/nodes/pve-001/qemu/100/status/shutdown" not in fake.posts
    assert "/nodes/pve-001/status" not in fake.posts
    assert b"forceStop=1" in fake.bodies["/nodes/pve-001/qemu/101/status/shutdown"]
    assert 'expected_clients=["172.16.0.101"]' in data["next_steps"][0]


@respx.mock
@pytest.mark.asyncio
async def test_ha_guests_left_to_node_shutdown(init_pve) -> None:
    fake = FakeCluster(
        {100: "pve-001", 200: "pve-002", 201: "pve-002"},
        ha_current=[{"type": "service", "sid": "vm:201", "node": "pve-002", "state": "started"}],
    )

    payload = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True))

    assert payload["ok"] is True, payload
    assert payload["data"]["stage"] == STAGE_READY_FOR_NAS
    assert payload["data"]["ha_managed_vmids"] == [201]
    assert "/nodes/pve-002/qemu/200/status/shutdown" in fake.posts
    assert "/nodes/pve-002/qemu/201/status/shutdown" not in fake.posts
    assert "/nodes/pve-002/stopall" not in fake.posts
    assert "/nodes/pve-002/status" in fake.posts


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ha_current",
    [
        [{"type": "service", "sid": "ct:150", "node": "pve-001", "state": "started"}],
        [{"type": "lrm", "node": "pve-001", "status": "active"}],
    ],
)
async def test_entry_self_fence_risk_refuses(init_pve, ha_current: list[dict]) -> None:
    fake = FakeCluster({100: "pve-001"}, ha_current=ha_current)

    payload = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True))

    assert payload["ok"] is False
    assert payload["error"]["code"] == "PVE_POWER_GUARD"
    assert "self-fences" in payload["error"]["message"]
    assert not fake.posts


@respx.mock
@pytest.mark.asyncio
async def test_unreadable_ha_status_refuses(init_pve) -> None:
    fake = FakeCluster({100: "pve-001"}, ha_readable=False)

    payload = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True))

    assert payload["ok"] is False
    assert "HA status is unreadable" in payload["error"]["message"]
    assert not fake.posts


@respx.mock
@pytest.mark.asyncio
async def test_peer_shutdown_read_timeout_still_waits(init_pve) -> None:
    fake = FakeCluster({100: "pve-001"})
    fake.slow_ack_nodes.add("pve-002")

    payload = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True))

    assert payload["ok"] is True, payload
    assert payload["data"]["stage"] == STAGE_READY_FOR_NAS
    assert payload["data"]["history"][0]["results"][0]["unconfirmed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_api_loss_during_peer_wait_is_not_success(init_pve) -> None:
    fake = FakeCluster({100: "pve-001"})
    fake.status_fails_after = 1

    payload = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True))

    assert payload["ok"] is True, payload
    assert payload["data"]["stage"] == STAGE_SHUTDOWN_PEERS
    assert payload["data"]["done"] is False
    assert payload["data"]["history"][-1]["wait"]["api_error"] == "PVE_CONNECT_TIMEOUT"
    assert any("Lost the API" in w for w in payload["warnings"])


@respx.mock
@pytest.mark.asyncio
async def test_include_entry_node_deferred_while_peers_online(init_pve) -> None:
    fake = FakeCluster({100: "pve-001", 200: "pve-002"})

    payload = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True, include_entry_node=True))

    assert payload["ok"] is True, payload
    assert payload["data"]["stage"] == STAGE_READY_FOR_NAS
    assert "/nodes/pve-001/status" not in fake.posts
    assert any("deferred" in w for w in payload["warnings"])


@respx.mock
@pytest.mark.asyncio
async def test_include_entry_node_submits_entry_shutdown(init_pve) -> None:
    fake = FakeCluster({100: "pve-001"})
    fake.online["pve-002"] = 0

    payload = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True, include_entry_node=True))

    assert payload["ok"] is True, payload
    assert payload["data"]["stage"] == "entry_shutdown_submitted"
    assert payload["data"]["history"][-1]["results"][0]["api_lost"] is True
    assert fake.posts == ["/nodes/pve-001/status"]


@respx.mock
@pytest.mark.asyncio
async def test_stuck_guest_aborts_unless_continue_on_error(init_pve) -> None:
    FakeCluster({100: "pve-001", 200: "pve-002"}, stop_works=False)
    aborted = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True))
    assert aborted["ok"] is False
    assert aborted["error"]["code"] == "PVE_SHUTDOWN_ABORTED"

    forced = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True, continue_on_error=True))
    assert forced["ok"] is True, forced
    assert forced["data"]["stage"] == STAGE_READY_FOR_NAS


@respx.mock
@pytest.mark.asyncio
async def test_plan_only_and_freeze_gate(init_pve) -> None:
    fake = FakeCluster({100: "pve-001", 200: "pve-002"}, policy="conditional")

    plan = json.loads(await pve_shutdown_cluster_impl(reason="dry run", plan_only=True, include_entry_node=True))
    assert plan["ok"] is True
    assert [h["stage"] for h in plan["data"]["history"]] == ["stop_guests", "shutdown_peers", "ready_for_nas"]
    assert any("freeze" in w for w in plan["warnings"])
    assert any("deferred" in w for w in plan["warnings"])
    assert not fake.posts

    refused = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True))
    assert refused["ok"] is False
    assert refused["error"]["code"] == "PVE_POWER_GUARD"
    assert not fake.posts


@respx.mock
@pytest.mark.asyncio
async def test_no_wait_returns_after_first_stage(init_pve) -> None:
    FakeCluster({100: "pve-001", 200: "pve-002"})
    payload = json.loads(await pve_shutdown_cluster_impl(reason="lab off", confirm=True, wait_for_completion=False))
    assert payload["data"]["stage"] == STAGE_STOP_GUESTS
    assert payload["data"]["done"] is False
    assert "again" in payload["data"]["next_steps"][0]
