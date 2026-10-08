"""MCP surface: tool catalog, tool classes, unknown-argument rejection, redaction."""

import json

import pytest

from openwrt_mcp.context import init_context
from openwrt_mcp.server import create_server
from openwrt_mcp.tools.helpers import redact_sensitive
from openwrt_mcp.tools.registry import TOOL_REGISTRY, ToolClass

EXPECTED = {
    "owrt_firewall_inspect": ToolClass.READ,
    "owrt_run_smoke_tests": ToolClass.READ,
    "owrt_firewall_plan_rule": ToolClass.WRITE,
    "owrt_plan_status": ToolClass.READ,
    "owrt_firewall_apply_plan": ToolClass.WRITE,
    "owrt_plan_confirm": ToolClass.WRITE,
    "owrt_plan_rollback": ToolClass.DESTRUCTIVE,
}


@pytest.fixture
def server(settings, transport):
    init_context(settings, transport)
    return create_server()


async def test_catalog_and_classes(server):
    names = {t.name for t in await server.list_tools()}
    assert names == set(EXPECTED)
    assert {k: TOOL_REGISTRY[k] for k in EXPECTED} == EXPECTED


async def test_no_passthrough_tools_and_no_approval_argument(server):
    for tool in await server.list_tools():
        props = set(tool.inputSchema.get("properties", {}))
        assert not props & {"grant", "approval", "approved", "token", "shell_cmd", "command", "uci", "ubus"}, tool.name


async def test_unknown_argument_is_rejected(server):
    with pytest.raises(Exception, match="(?i)extra|unexpected|forbidden"):
        await server.call_tool("owrt_firewall_inspect", {"router_id": "openwrt-pi", "shell_cmd": "id"})


async def test_known_call_works_through_mcp(server):
    content, _ = await server.call_tool("owrt_firewall_inspect", {"router_id": "openwrt-pi"})
    data = json.loads(content[0].text)
    assert data["isError"] is False


async def test_domain_errors_are_stable_and_traceback_free(server):
    content, _ = await server.call_tool("owrt_firewall_inspect", {"router_id": "nope"})
    data = json.loads(content[0].text)
    assert data["error"]["code"] == "TARGET_NOT_AUTHORIZED" and "Traceback" not in content[0].text


async def test_invalid_enum_rejected(server):
    with pytest.raises(Exception):
        await server.call_tool(
            "owrt_firewall_plan_rule",
            {"router_id": "openwrt-pi", "rule_id": "x", "idempotency_key": "idem-key-0001", "template": "allow_any"},
        )


def test_redaction():
    out = redact_sensitive({"api_token": "abc", "nested": [{"password": "p", "ok": "fine"}], "idempotency_key": "k"})
    assert out["api_token"] == "[REDACTED]" and out["nested"][0]["password"] == "[REDACTED]"
    assert out["nested"][0]["ok"] == "fine" and out["idempotency_key"] == "k"
