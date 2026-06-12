"""REST API access policy — Allowed Interfaces aligned with PFSENSE_HOST path."""

from __future__ import annotations

import ipaddress
from typing import Any

from pfsense_mcp.constants import DEFAULT_API_USER, LAB_LAN_CIDR
from pfsense_mcp.policy.types import PolicyReport

LAN_INTERFACE_MARKERS = frozenset({"lan", "vtnet1", "localhost", "lo0"})
TAILNET_CGNAT = "100.64.0.0/10"


def _normalize_interface_list(raw: Any) -> list[str]:
    """Coerce pfREST allowed-interfaces values into a lowercase string list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip().lower()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(item).strip().lower() for item in raw if str(item).strip()]
    return []


def _host_access_mode(host: str) -> str:
    """Classify ``PFSENSE_HOST`` as localhost, tailscale, lan, or unknown."""
    try:
        address = ipaddress.ip_address(host.strip())
    except ValueError:
        return "unknown"
    if address.is_loopback:
        return "localhost"
    if str(address).startswith("100."):
        return "tailscale"
    return "lan"


def _access_list_entries(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract REST API access-list entries from heterogeneous settings payloads."""
    for key in ("access_lists", "access_list", "acl", "acls"):
        raw = settings.get(key)
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
    return []


def evaluate_restapi_access_policy(
    settings: Any,
    *,
    host: str,
    api_user: str = DEFAULT_API_USER,
    lan_cidr: str = LAB_LAN_CIDR,
) -> PolicyReport:
    """Verify pfREST Allowed Interfaces (and access-list hints) for the configured host path."""
    issues: list[str] = []
    details: dict[str, Any] = {"host": host, "access_mode": _host_access_mode(host)}

    if not isinstance(settings, dict):
        return PolicyReport(
            domain="restapi_access",
            compliant=False,
            issues=["REST API settings payload is not a dict"],
            planned_changes=0,
            details=details,
            hint="docs/PFSENSE_API_KEY_SETUP.md § Restrict access",
        )

    allowed = _normalize_interface_list(settings.get("allowed_interfaces"))
    details["allowed_interfaces"] = allowed
    mode = details["access_mode"]

    if not allowed:
        details["allowed_interfaces_note"] = "empty — all interfaces (OK for any path)"
    elif mode == "tailscale":
        issues.append(
            "allowed_interfaces is non-empty while PFSENSE_HOST is a Tailscale IP; "
            "deselect all or run ./deploy/pfsense-restapi-access.sh fix-access"
        )
    elif mode == "lan":
        if not LAN_INTERFACE_MARKERS.intersection(set(allowed)):
            issues.append(
                "allowed_interfaces must include LAN and/or localhost for direct LAN API access "
                f"(expected one of {sorted(LAN_INTERFACE_MARKERS)}, got {allowed})"
            )
    elif mode == "unknown":
        issues.append(f"cannot classify host access mode for PFSENSE_HOST={host}")

    entries = _access_list_entries(settings)
    details["access_list_count"] = len(entries)
    if entries:
        has_lan_allow = False
        has_tailnet_allow = False
        for entry in entries:
            if str(entry.get("type", "")).lower() != "allow":
                continue
            network = str(entry.get("network") or entry.get("source") or "").strip()
            users = entry.get("users") or entry.get("user") or []
            if isinstance(users, str):
                users = [users]
            user_text = " ".join(str(item).lower() for item in users)
            if api_user.lower() not in user_text and users:
                continue
            if lan_cidr in network or network.startswith("172.16."):
                has_lan_allow = True
            if network == TAILNET_CGNAT or network.startswith("100."):
                has_tailnet_allow = True
        details["access_list_allows"] = {
            "lan_cidr": has_lan_allow,
            "tailnet_cgnat": has_tailnet_allow,
        }
        if mode == "lan" and not has_lan_allow:
            issues.append(
                f"Access Lists exist but no Allow rule covers {lan_cidr} for {api_user}; " "LAN API calls may get 403"
            )

    return PolicyReport(
        domain="restapi_access",
        compliant=not issues,
        issues=issues,
        planned_changes=0,
        details=details,
        hint="docs/PFSENSE_API_KEY_SETUP.md § Restrict access",
    )
