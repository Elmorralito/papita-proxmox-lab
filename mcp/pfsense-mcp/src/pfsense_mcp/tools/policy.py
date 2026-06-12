"""Lab policy verification MCP tool."""

from __future__ import annotations

import time

from pfsense_mcp.context import get_client, get_settings
from pfsense_mcp.policy.registry import verify_all_policies
from pfsense_mcp.tools.response import ok_response, tool_handler


@tool_handler("pfs_verify_lab_policy")
async def pfs_verify_lab_policy_impl() -> str:
    """Read-only: evaluate Tailscale firewall, REST API access, and endpoint privilege policies."""
    started = time.perf_counter()
    suite = await verify_all_policies(get_client(), settings=get_settings())
    duration_ms = int((time.perf_counter() - started) * 1000)
    warnings = suite["issues"] if not suite["compliant"] else []
    return ok_response("pfs_verify_lab_policy", suite, duration_ms=duration_ms, warnings=warnings)
