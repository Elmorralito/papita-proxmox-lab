"""Automated checks against REQUIREMENTS.md v0.2 tool catalog and scope."""

import pytest

from truenas_mcp.constants import BASH_ONLY_WORKFLOWS, RUNBOOK_REFS, TNAS_TESTED_MAJOR_VERSION
from truenas_mcp.server import create_server
from truenas_mcp.tools.registry import TOOL_REGISTRY, ToolClass

REQUIRED_READ_TOOLS: dict[str, ToolClass] = {
    "truenas_get_system_info": ToolClass.READ,
    "truenas_check_api_key": ToolClass.READ,
    "truenas_list_alerts": ToolClass.READ,
    "truenas_list_alert_policies": ToolClass.READ,
    "truenas_list_pools": ToolClass.READ,
    "truenas_list_datasets": ToolClass.READ,
    "truenas_list_disks": ToolClass.READ,
    "truenas_list_smart_results": ToolClass.READ,
    "truenas_get_reporting_data": ToolClass.READ,
    "truenas_list_apps": ToolClass.READ,
    "truenas_list_jobs": ToolClass.READ,
    "truenas_list_nfs_shares": ToolClass.READ,
    "truenas_list_scrub_tasks": ToolClass.READ,
    "truenas_system_summary": ToolClass.READ,
    "truenas_run_smoke_tests": ToolClass.READ,
}

REQUIRED_WRITE_TOOLS: dict[str, ToolClass] = {
    "truenas_create_dataset": ToolClass.WRITE,
    "truenas_update_nfs_share": ToolClass.WRITE,
    "truenas_dismiss_alert": ToolClass.WRITE,
}

REQUIRED_TOOLS = {**REQUIRED_READ_TOOLS, **REQUIRED_WRITE_TOOLS}


@pytest.fixture(scope="module", autouse=True)
def register_all_tools() -> None:
    TOOL_REGISTRY.clear()
    create_server()


def test_no_destructive_tools() -> None:
    assert ToolClass.DESTRUCTIVE not in TOOL_REGISTRY.values()


def test_tool_catalog_complete() -> None:
    assert set(REQUIRED_TOOLS.keys()) == set(TOOL_REGISTRY.keys())
    for name, expected_class in REQUIRED_TOOLS.items():
        assert TOOL_REGISTRY[name] == expected_class


def test_write_tools_are_gated() -> None:
    assert set(REQUIRED_WRITE_TOOLS) == {
        name for name, cls in TOOL_REGISTRY.items() if cls == ToolClass.WRITE
    }


def test_runbook_refs_for_ha_and_nfs() -> None:
    assert "truenas_list_nfs_shares" in RUNBOOK_REFS
    assert "truenas_list_apps" in RUNBOOK_REFS
    assert (
        "Path B" in RUNBOOK_REFS["truenas_system_summary"]
        or "quorum" in RUNBOOK_REFS["truenas_system_summary"].lower()
    )


def test_bash_only_workflows_documented() -> None:
    assert "setup-cluster-ha" in BASH_ONLY_WORKFLOWS
    assert "scrutiny-webui" in BASH_ONLY_WORKFLOWS
    assert "uptime-kuma-pve-cluster" in BASH_ONLY_WORKFLOWS


def test_truenas_version_documented() -> None:
    assert TNAS_TESTED_MAJOR_VERSION.startswith("25")
