"""API endpoint privilege policy — required GET paths for MCP read tools."""

from __future__ import annotations

from typing import Any

from pfsense_mcp.client.errors import PfsApiError
from pfsense_mcp.client.http import PfsClient
from pfsense_mcp.constants import (
    EP_FIREWALL_RULES,
    EP_GATEWAYS,
    EP_INTERFACES,
    EP_RESTAPI_SETTINGS,
    EP_STATIC_ROUTES,
    EP_SYSTEM_VERSION,
)
from pfsense_mcp.policy.types import PolicyReport

REQUIRED_READ_ENDPOINTS: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
    (EP_SYSTEM_VERSION, "system version", None),
    (EP_RESTAPI_SETTINGS, "REST API settings", None),
    (EP_INTERFACES, "interfaces", None),
    (EP_FIREWALL_RULES, "firewall rules", {"limit": 1}),
    (EP_GATEWAYS, "gateways", None),
    (EP_STATIC_ROUTES, "static routes", None),
)


async def evaluate_api_endpoints_policy(client: PfsClient) -> PolicyReport:
    """Probe each MCP read endpoint; fail on 401/403/missing privilege."""
    issues: list[str] = []
    details: dict[str, Any] = {"endpoints": []}

    for path, label, params in REQUIRED_READ_ENDPOINTS:
        entry: dict[str, Any] = {"path": path, "label": label}
        try:
            await client.get(path, params=params)
            entry["status"] = "ok"
        except PfsApiError as exc:
            entry["status"] = "fail"
            entry["http_status"] = exc.status_code
            entry["message"] = str(exc)
            if exc.status_code == 401:
                issues.append(f"{label} ({path}): HTTP 401 — API key rejected")
            elif exc.status_code == 403:
                issues.append(f"{label} ({path}): HTTP 403 — privilege or access policy")
            else:
                issues.append(f"{label} ({path}): {exc}")
        except Exception as exc:
            entry["status"] = "fail"
            entry["message"] = str(exc)
            issues.append(f"{label} ({path}): {exc}")
        details["endpoints"].append(entry)

    return PolicyReport(
        domain="api_endpoints",
        compliant=not issues,
        issues=issues,
        planned_changes=0,
        details=details,
        hint="docs/PFSENSE_API_KEY_SETUP.md § Grant API privileges",
    )
