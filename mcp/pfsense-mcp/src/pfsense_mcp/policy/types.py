"""Shared types for lab policy evaluation."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class PolicyReport(TypedDict, total=False):
    """Read-only compliance result for a single policy domain."""

    domain: str
    compliant: bool
    issues: list[str]
    planned_changes: int
    details: dict[str, Any]
    hint: str


PolicyDomain = Literal["tailscale_firewall", "restapi_access", "api_endpoints"]
"""Registered lab policy domain identifiers."""


class PolicySuiteReport(TypedDict):
    """Aggregated compliance report across all registered policy domains."""

    compliant: bool
    domains: dict[str, PolicyReport]
    issues: list[str]
