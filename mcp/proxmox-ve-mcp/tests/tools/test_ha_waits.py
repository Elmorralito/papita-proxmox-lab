"""Tests for HA status and bounded wait tools."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx

from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import init_context
from proxmox_ve_mcp.tools.ha import parse_shutdown_policy, pve_get_ha_status_impl
from proxmox_ve_mcp.tools.waits import pve_wait_for_task_impl, pve_wait_nodes_state_impl

BASE = "https://pve.local:8006/api2/json"
UPID = "UPID:pve-002:0001:0002:0003:stopall::root@pam:"


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


def _status(nodes: dict[str, int]) -> httpx.Response:
    entries = [{"type": "cluster", "name": "c", "quorate": 1}]
    entries += [{"type": "node", "name": name, "online": online} for name, online in nodes.items()]
    return httpx.Response(200, json={"data": entries})


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"ha": {"shutdown_policy": "freeze"}}, "freeze"),
        ({"ha": "shutdown_policy=migrate"}, "migrate"),
        ({"ha": "foo=bar,shutdown_policy=failover"}, "failover"),
        ({}, "conditional"),
    ],
)
def test_parse_shutdown_policy(options: dict, expected: str) -> None:
    assert parse_shutdown_policy(options) == expected


@respx.mock
@pytest.mark.asyncio
async def test_ha_status_freeze_and_lrms(init_pve) -> None:
    respx.get(f"{BASE}/cluster/ha/status/current").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "quorum", "type": "quorum", "quorate": "1", "status": "OK"},
                    {"id": "master", "type": "master", "node": "pve-001", "status": "pve-001 (active, Mon)"},
                    {"id": "lrm:pve-001", "type": "lrm", "node": "pve-001", "status": "pve-001 (idle, Mon)"},
                    {"id": "lrm:pve-002", "type": "lrm", "node": "pve-002", "status": "pve-002 (active, Mon)"},
                    {"id": "service:vm:200", "type": "service", "sid": "vm:200", "node": "pve-002", "state": "started"},
                ]
            },
        )
    )
    respx.get(f"{BASE}/cluster/ha/resources").mock(
        return_value=httpx.Response(200, json={"data": [{"sid": "vm:200", "state": "started"}]})
    )
    respx.get(f"{BASE}/cluster/options").mock(
        return_value=httpx.Response(200, json={"data": {"ha": {"shutdown_policy": "freeze"}}})
    )
    respx.get(f"{BASE}/cluster/ha/rules").mock(
        return_value=httpx.Response(200, json={"data": [{"rule": "papita-ha", "type": "node-affinity"}]})
    )

    payload = json.loads(await pve_get_ha_status_impl())
    data = payload["data"]
    assert payload["ok"] is True
    assert data["shutdown_policy"] == "freeze"
    assert data["shutdown_policy_ok"] is True
    assert data["active_lrm_nodes"] == ["pve-002"]
    assert data["manager"]["node"] == "pve-001"
    assert data["rules_source"] == "rules"
    assert data["resource_count"] == 1
    assert any("self-fence" in w for w in payload["warnings"])


@respx.mock
@pytest.mark.asyncio
async def test_ha_status_warns_when_not_freeze_and_falls_back_to_groups(init_pve) -> None:
    respx.get(f"{BASE}/cluster/ha/status/current").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "quorum", "type": "quorum", "quorate": 1}]})
    )
    respx.get(f"{BASE}/cluster/ha/resources").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{BASE}/cluster/options").mock(return_value=httpx.Response(200, json={"data": {}}))
    respx.get(f"{BASE}/cluster/ha/rules").mock(return_value=httpx.Response(501, json={"data": None}))
    respx.get(f"{BASE}/cluster/ha/groups").mock(
        return_value=httpx.Response(200, json={"data": [{"group": "papita-ha"}]})
    )

    payload = json.loads(await pve_get_ha_status_impl())
    assert payload["data"]["shutdown_policy"] == "conditional"
    assert payload["data"]["shutdown_policy_ok"] is False
    assert payload["data"]["rules_source"] == "groups"
    assert any("freeze" in w for w in payload["warnings"])


@respx.mock
@pytest.mark.asyncio
async def test_wait_for_task_finished_ok(init_pve) -> None:
    respx.get(f"{BASE}/nodes/pve-002/tasks/{UPID}/status").mock(
        return_value=httpx.Response(200, json={"data": {"status": "stopped", "exitstatus": "OK"}})
    )
    respx.get(f"{BASE}/nodes/pve-002/tasks/{UPID}/log").mock(
        return_value=httpx.Response(200, json={"data": [{"n": 1, "t": "stopping vm 101"}, {"n": 2, "t": "TASK OK"}]})
    )
    payload = json.loads(await pve_wait_for_task_impl(upid=UPID, timeout_s=5))
    assert payload["data"]["finished"] is True
    assert payload["data"]["succeeded"] is True
    assert payload["data"]["log_tail"] == ["stopping vm 101", "TASK OK"]


@respx.mock
@pytest.mark.asyncio
async def test_wait_for_task_timeout_is_not_error(init_pve) -> None:
    respx.get(f"{BASE}/nodes/pve-002/tasks/{UPID}/status").mock(
        return_value=httpx.Response(200, json={"data": {"status": "running"}})
    )
    respx.get(f"{BASE}/nodes/pve-002/tasks/{UPID}/log").mock(return_value=httpx.Response(200, json={"data": []}))
    payload = json.loads(await pve_wait_for_task_impl(upid=UPID, timeout_s=1))
    assert payload["ok"] is True
    assert payload["data"]["finished"] is False
    assert payload["data"]["succeeded"] is None


@pytest.mark.asyncio
async def test_wait_for_task_rejects_bad_upid(init_pve) -> None:
    payload = json.loads(await pve_wait_for_task_impl(upid="not-a-upid"))
    assert payload["ok"] is False


@respx.mock
@pytest.mark.asyncio
async def test_wait_nodes_offline_reached(init_pve) -> None:
    respx.get(f"{BASE}/cluster/status").mock(
        side_effect=[
            _status({"pve-001": 1, "pve-002": 1}),
            _status({"pve-001": 1, "pve-002": 0}),
        ]
    )
    payload = json.loads(await pve_wait_nodes_state_impl(target="offline", nodes=["pve-002"], timeout_s=30))
    assert payload["data"]["reached"] is True
    assert payload["data"]["states"] == {"pve-002": "offline"}
    assert payload["data"]["api_lost"] is False


@respx.mock
@pytest.mark.asyncio
async def test_wait_nodes_offline_api_lost_counts_as_offline(init_pve) -> None:
    respx.get(f"{BASE}/cluster/status").mock(
        side_effect=[_status({"pve-001": 1}), httpx.ConnectTimeout("")]
    )
    payload = json.loads(await pve_wait_nodes_state_impl(target="offline", nodes=["pve-001"], timeout_s=30))
    assert payload["ok"] is True
    assert payload["data"]["api_lost"] is True
    assert payload["data"]["states"] == {"pve-001": "offline_assumed"}
    assert any("offline_assumed" in w for w in payload["warnings"])


@respx.mock
@pytest.mark.asyncio
async def test_wait_nodes_online_timeout_and_all_members(init_pve) -> None:
    respx.get(f"{BASE}/cluster/status").mock(return_value=_status({"pve-001": 1, "pve-003": 0}))
    payload = json.loads(await pve_wait_nodes_state_impl(target="online", timeout_s=1))
    assert payload["data"]["reached"] is False
    assert payload["data"]["pending"] == ["pve-003"]
    assert set(payload["data"]["states"]) == {"pve-001", "pve-003"}


@respx.mock
@pytest.mark.asyncio
async def test_wait_nodes_online_api_error_is_error(init_pve) -> None:
    respx.get(f"{BASE}/cluster/status").mock(side_effect=httpx.ConnectTimeout(""))
    payload = json.loads(await pve_wait_nodes_state_impl(target="online", timeout_s=1))
    assert payload["ok"] is False
    assert payload["error"]["code"] == "PVE_CONNECT_TIMEOUT"


@respx.mock
@pytest.mark.asyncio
async def test_wait_nodes_unknown_node(init_pve) -> None:
    respx.get(f"{BASE}/cluster/status").mock(return_value=_status({"pve-001": 1}))
    payload = json.loads(await pve_wait_nodes_state_impl(target="online", nodes=["pve-009"], timeout_s=1))
    assert payload["ok"] is False
