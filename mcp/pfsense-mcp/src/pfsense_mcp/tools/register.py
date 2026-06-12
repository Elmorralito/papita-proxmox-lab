"""Register MCP tools on a FastMCP server."""

from collections.abc import Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from pfsense_mcp.tools.network import pfs_list_firewall_rules_impl, pfs_list_interfaces_impl
from pfsense_mcp.tools.policy import pfs_verify_lab_policy_impl
from pfsense_mcp.tools.registry import TOOL_REGISTRY, ToolClass
from pfsense_mcp.tools.smoke_test import pfs_run_smoke_tests_impl
from pfsense_mcp.tools.system import (
    pfs_get_tailscale_status_impl,
    pfs_get_version_impl,
    pfs_system_summary_impl,
)

ToolFn = Callable[..., Awaitable[str]]


def _track(name: str, tool_class: ToolClass) -> Callable[[ToolFn], ToolFn]:
    """Register a tool name and class in ``TOOL_REGISTRY`` when the decorator runs."""

    def decorator(fn: ToolFn) -> ToolFn:
        TOOL_REGISTRY[name] = tool_class
        return fn

    return decorator


def register_tools(mcp: FastMCP) -> None:
    """Register all v1 read-only MCP tools on the FastMCP server instance."""

    @mcp.tool(name="pfs_get_version")
    @_track("pfs_get_version", ToolClass.READ)
    async def pfs_get_version() -> str:
        """Get pfSense / pfREST version (validates API key and TLS)."""
        return await pfs_get_version_impl()

    @mcp.tool(name="pfs_list_interfaces")
    @_track("pfs_list_interfaces", ToolClass.READ)
    async def pfs_list_interfaces() -> str:
        """List pfSense interfaces; warns if lab LAN 172.16.0.0/16 is not present."""
        return await pfs_list_interfaces_impl()

    @mcp.tool(name="pfs_get_tailscale_status")
    @_track("pfs_get_tailscale_status", ToolClass.READ)
    async def pfs_get_tailscale_status() -> str:
        """Tailscale on pfSense: enabled state, advertised routes, accept-routes."""
        return await pfs_get_tailscale_status_impl()

    @mcp.tool(name="pfs_system_summary")
    @_track("pfs_system_summary", ToolClass.READ)
    async def pfs_system_summary() -> str:
        """Operator dashboard: version, interfaces count, Tailscale, gateways, static routes, REST API."""
        return await pfs_system_summary_impl()

    @mcp.tool(name="pfs_list_firewall_rules")
    @_track("pfs_list_firewall_rules", ToolClass.READ)
    async def pfs_list_firewall_rules(
        interface: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> str:
        """List firewall rules (paginated; default limit 50). Optional interface filter."""
        return await pfs_list_firewall_rules_impl(interface=interface, limit=limit, offset=offset)

    @mcp.tool(name="pfs_run_smoke_tests")
    @_track("pfs_run_smoke_tests", ToolClass.READ)
    async def pfs_run_smoke_tests() -> str:
        """Run post-install smoke tests: config, auth, REST API, LAN, Tailscale route, lab policies."""
        return await pfs_run_smoke_tests_impl()

    @mcp.tool(name="pfs_verify_lab_policy")
    @_track("pfs_verify_lab_policy", ToolClass.READ)
    async def pfs_verify_lab_policy() -> str:
        """Evaluate Tailscale firewall, REST API access, and MCP endpoint privilege policies."""
        return await pfs_verify_lab_policy_impl()
