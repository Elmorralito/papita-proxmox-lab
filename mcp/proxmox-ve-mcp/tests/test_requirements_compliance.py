"""Automated checks against REQUIREMENTS.md v1 tool catalog and scope."""

import pytest

from proxmox_ve_mcp.constants import BASH_ONLY_WORKFLOWS, PVE_TESTED_MAJOR_VERSION, RUNBOOK_REFS
from proxmox_ve_mcp.server import create_server
from proxmox_ve_mcp.tools.registry import TOOL_REGISTRY, ToolClass

# §7.1 + §7.2 v1 tools
REQUIRED_V1_TOOLS: dict[str, ToolClass] = {
    "pve_get_version": ToolClass.READ,
    "pve_check_token": ToolClass.READ,
    "pve_run_smoke_tests": ToolClass.READ,
    "pve_list_node_addresses": ToolClass.READ,
    "pve_list_nodes": ToolClass.READ,
    "pve_get_cluster_config_nodes": ToolClass.READ,
    "pve_cluster_health": ToolClass.READ,
    "pve_list_resources": ToolClass.READ,
    "pve_get_node_status": ToolClass.READ,
    "pve_list_guests": ToolClass.READ,
    "pve_get_guest_status": ToolClass.READ,
    "pve_list_storage": ToolClass.READ,
    "pve_list_tasks": ToolClass.READ,
    "pve_get_task_log": ToolClass.READ,
    "pve_get_cluster_options": ToolClass.READ,
    "pve_get_ceph_status": ToolClass.READ,
    "pve_get_guest_config": ToolClass.READ,
    "pve_list_ceph_osds": ToolClass.READ,
    "pve_start_guest": ToolClass.WRITE,
    "pve_shutdown_guest": ToolClass.WRITE,
    "pve_stopall_guests": ToolClass.WRITE,
    "pve_get_ha_status": ToolClass.READ,
    "pve_wait_for_task": ToolClass.READ,
    "pve_wait_nodes_state": ToolClass.READ,
    "pve_wake_on_lan": ToolClass.WRITE,
    "pve_stop_guest": ToolClass.DESTRUCTIVE,
    "pve_shutdown_node": ToolClass.DESTRUCTIVE,
}

# FR-903 exceptions: only these power tools may be destructive (docs/MCP_POWER_PLAN.md).
APPROVED_DESTRUCTIVE_TOOLS = {"pve_stop_guest", "pve_shutdown_node"}


@pytest.fixture(scope="module", autouse=True)
def register_all_tools():
    TOOL_REGISTRY.clear()
    create_server()


def test_only_approved_destructive_tools() -> None:
    destructive = {name for name, cls in TOOL_REGISTRY.items() if cls == ToolClass.DESTRUCTIVE}
    assert destructive == APPROVED_DESTRUCTIVE_TOOLS


def test_v1_tool_catalog_complete() -> None:
    assert set(REQUIRED_V1_TOOLS.keys()) == set(TOOL_REGISTRY.keys())
    for name, expected_class in REQUIRED_V1_TOOLS.items():
        assert TOOL_REGISTRY[name] == expected_class


def test_runbook_refs_for_ceph_and_stopall() -> None:
    assert "pve_get_ceph_status" in RUNBOOK_REFS
    assert "OSD Storage" in RUNBOOK_REFS["pve_get_ceph_status"]
    assert "pve_stopall_guests" in RUNBOOK_REFS


def test_bash_only_workflows_documented() -> None:
    assert "get-temp" in BASH_ONLY_WORKFLOWS
    assert "start-cluster" in BASH_ONLY_WORKFLOWS


def test_pve_version_documented() -> None:
    assert PVE_TESTED_MAJOR_VERSION.startswith("8")
