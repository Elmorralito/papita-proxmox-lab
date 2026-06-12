"""Pydantic input models for MCP tools."""

from pydantic import BaseModel, Field

from pfsense_mcp.constants import DEFAULT_FIREWALL_RULE_LIMIT


class ListFirewallRulesInput(BaseModel):
    """Validated pagination and filter inputs for ``pfs_list_firewall_rules``."""

    interface: str | None = Field(default=None, description="Filter by interface name (e.g. lan)")
    limit: int = Field(default=DEFAULT_FIREWALL_RULE_LIMIT, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
