"""Automated checks against REQUIREMENTS.md v1 read-only catalog."""

import pytest

from pfsense_mcp.constants import (
    OUT_OF_SCOPE_V1,
    PFS_TESTED_MAJOR_VERSION,
    RUNBOOK_REFS,
)
from pfsense_mcp.server import create_server
from pfsense_mcp.tools.helpers import require_confirm
from pfsense_mcp.tools.registry import TOOL_REGISTRY, ToolClass

V1_READ_TOOLS: dict[str, ToolClass] = {
    "pfs_get_version": ToolClass.READ,
    "pfs_list_interfaces": ToolClass.READ,
    "pfs_get_tailscale_status": ToolClass.READ,
    "pfs_system_summary": ToolClass.READ,
    "pfs_list_firewall_rules": ToolClass.READ,
    "pfs_run_smoke_tests": ToolClass.READ,
    "pfs_verify_lab_policy": ToolClass.READ,
}


@pytest.fixture(scope="module", autouse=True)
def register_all_tools() -> None:
    TOOL_REGISTRY.clear()
    create_server()


def test_no_destructive_tools() -> None:
    assert ToolClass.DESTRUCTIVE not in TOOL_REGISTRY.values()
    assert ToolClass.WRITE not in TOOL_REGISTRY.values()


def test_v1_read_tool_catalog() -> None:
    assert set(V1_READ_TOOLS.keys()) == set(TOOL_REGISTRY.keys())
    for name, expected in V1_READ_TOOLS.items():
        assert TOOL_REGISTRY[name] == expected


def test_runbook_refs_for_v1_tools() -> None:
    for tool in V1_READ_TOOLS:
        assert tool in RUNBOOK_REFS


def test_out_of_scope_documented() -> None:
    assert "write-tools" in OUT_OF_SCOPE_V1
    assert "tailscale-admin-api" in OUT_OF_SCOPE_V1


def test_require_confirm_gate() -> None:
    with pytest.raises(ValueError, match="confirm must be true"):
        require_confirm(False)


def test_pfs_version_documented() -> None:
    assert "pfREST" in PFS_TESTED_MAJOR_VERSION
