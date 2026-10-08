"""Register MCP tools on a FastMCP server."""

from collections.abc import Awaitable, Callable
from typing import Literal

from mcp.server.fastmcp import FastMCP

from openwrt_mcp.context import get_context
from openwrt_mcp.tools.firewall import firewall_inspect_impl, firewall_plan_rule_impl
from openwrt_mcp.tools.helpers import guarded
from openwrt_mcp.tools.plans import apply_plan_impl, confirm_plan_impl, plan_status_impl, rollback_plan_impl
from openwrt_mcp.tools.registry import TOOL_REGISTRY, ToolClass
from openwrt_mcp.tools.smoke_test import run_smoke_tests_impl

ToolFn = Callable[..., Awaitable[str]]


def _track(name: str, tool_class: ToolClass) -> Callable[[ToolFn], ToolFn]:
    """Record a tool name and class in ``TOOL_REGISTRY``."""

    def decorator(fn: ToolFn) -> ToolFn:
        TOOL_REGISTRY[name] = tool_class
        return fn

    return decorator


def forbid_unknown_arguments(mcp: FastMCP) -> None:
    """Reject unknown top-level tool arguments (FastMCP ignores them by default)."""
    for tool in mcp._tool_manager.list_tools():  # pylint: disable=protected-access
        model = tool.fn_metadata.arg_model
        model.model_config["extra"] = "forbid"
        model.model_rebuild(force=True)


def register_tools(mcp: FastMCP) -> None:
    """Register all tools, then lock down argument schemas."""

    @mcp.tool(name="owrt_firewall_inspect")
    @_track("owrt_firewall_inspect", ToolClass.READ)
    @guarded
    async def owrt_firewall_inspect(router_id: str) -> str:
        """Inspect the router firewall: config revision, agent-owned rules, runtime summary."""
        return await firewall_inspect_impl(get_context(), router_id)

    @mcp.tool(name="owrt_run_smoke_tests")
    @_track("owrt_run_smoke_tests", ToolClass.READ)
    @guarded
    async def owrt_run_smoke_tests() -> str:
        """Run read-only smoke tests: key, host-key pin, agent, revision, watchdog, audit chain."""
        return await run_smoke_tests_impl(get_context())

    @mcp.tool(name="owrt_firewall_plan_rule")
    @_track("owrt_firewall_plan_rule", ToolClass.WRITE)
    @guarded
    async def owrt_firewall_plan_rule(
        router_id: str,
        rule_id: str,
        idempotency_key: str,
        action: Literal["upsert", "delete"] = "upsert",
        template: Literal["allow_tcp_from_lan"] = "allow_tcp_from_lan",
        dest_port: int | None = None,
        family: Literal["ipv4", "ipv6", "any"] = "ipv4",
        src_ip: str | None = None,
    ) -> str:
        """Create an immutable plan for an agent-owned `allow_tcp_from_lan` rule. Changes nothing on the router."""
        return await firewall_plan_rule_impl(
            get_context(),
            router_id=router_id,
            rule_id=rule_id,
            idempotency_key=idempotency_key,
            action=action,
            template=template,
            dest_port=dest_port,
            family=family,
            src_ip=src_ip,
        )

    @mcp.tool(name="owrt_plan_status")
    @_track("owrt_plan_status", ToolClass.READ)
    @guarded
    async def owrt_plan_status(plan_id: str) -> str:
        """Plan status; reconciles in-flight transactions with the router journal."""
        return await plan_status_impl(get_context(), plan_id)

    @mcp.tool(name="owrt_firewall_apply_plan")
    @_track("owrt_firewall_apply_plan", ToolClass.WRITE)
    @guarded
    async def owrt_firewall_apply_plan(plan_id: str, plan_digest: str) -> str:
        """Apply a plan that a human approved out-of-band (grant is resolved server-side, never passed here)."""
        return await apply_plan_impl(get_context(), plan_id, plan_digest)

    @mcp.tool(name="owrt_plan_confirm")
    @_track("owrt_plan_confirm", ToolClass.WRITE)
    @guarded
    async def owrt_plan_confirm(plan_id: str) -> str:
        """Confirm an applied plan; refused unless server-side verification passes before the deadline."""
        return await confirm_plan_impl(get_context(), plan_id)

    @mcp.tool(name="owrt_plan_rollback")
    @_track("owrt_plan_rollback", ToolClass.DESTRUCTIVE)
    @guarded
    async def owrt_plan_rollback(plan_id: str) -> str:
        """Roll back an unconfirmed plan to the pre-change firewall configuration."""
        return await rollback_plan_impl(get_context(), plan_id)

    forbid_unknown_arguments(mcp)
