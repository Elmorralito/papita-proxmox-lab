"""Network read tools — interfaces and firewall rules."""

import time

from pfsense_mcp.constants import EP_FIREWALL_RULES, EP_INTERFACES, LAB_LAN_CIDR
from pfsense_mcp.context import get_client
from pfsense_mcp.tools.helpers import (
    firewall_has_anti_lockout,
    normalize_list,
    parse_model,
    redact_sensitive,
)
from pfsense_mcp.tools.response import ok_response, tool_handler
from pfsense_mcp.tools.schemas import ListFirewallRulesInput
from pfsense_mcp.tools.system import _interface_has_lan_cidr


@tool_handler("pfs_list_interfaces")
async def pfs_list_interfaces_impl() -> str:
    """Fetch pfSense interfaces and warn when the lab LAN CIDR is absent."""
    started = time.perf_counter()
    raw = await get_client().get(EP_INTERFACES)
    interfaces = redact_sensitive(normalize_list(raw))
    warnings: list[str] = []
    if not _interface_has_lan_cidr(normalize_list(raw)):
        warnings.append(f"No interface address found in lab LAN {LAB_LAN_CIDR}")
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pfs_list_interfaces",
        {"interfaces": interfaces, "count": len(interfaces)},
        duration_ms=duration_ms,
        warnings=warnings,
    )


@tool_handler("pfs_list_firewall_rules")
async def pfs_list_firewall_rules_impl(
    interface: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    """Fetch paginated firewall rules with optional interface filter and anti-lockout check."""
    parsed = parse_model(
        ListFirewallRulesInput,
        interface=interface,
        limit=limit,
        offset=offset,
    )
    params: dict[str, int | str] = {"limit": parsed.limit, "offset": parsed.offset}
    if parsed.interface:
        params["interface"] = parsed.interface

    started = time.perf_counter()
    raw = await get_client().get(EP_FIREWALL_RULES, params=params)
    rules = redact_sensitive(normalize_list(raw))
    anti_lockout = firewall_has_anti_lockout(normalize_list(raw))
    warnings: list[str] = []
    if not anti_lockout:
        warnings.append("No anti-lockout rule detected in this page of results")
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pfs_list_firewall_rules",
        {
            "rules": rules,
            "count": len(rules),
            "limit": parsed.limit,
            "offset": parsed.offset,
            "interface_filter": parsed.interface,
            "anti_lockout_present": anti_lockout,
        },
        duration_ms=duration_ms,
        warnings=warnings,
    )
