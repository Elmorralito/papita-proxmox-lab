"""Policy registry — evaluate lab compliance across pfREST domains."""

from __future__ import annotations

from typing import Any

from pfsense_mcp.client.http import PfsClient
from pfsense_mcp.config import PfsSettings
from pfsense_mcp.constants import EP_RESTAPI_SETTINGS
from pfsense_mcp.firewall_policy import (
    evaluate_tailscale_firewall_policy,
    fetch_firewall_rules,
)
from pfsense_mcp.policy.api_endpoints import evaluate_api_endpoints_policy
from pfsense_mcp.policy.restapi_access import evaluate_restapi_access_policy
from pfsense_mcp.policy.types import PolicyReport, PolicySuiteReport


def _wrap_tailscale_firewall(raw: dict[str, Any]) -> PolicyReport:
    """Map raw Tailscale firewall evaluation output into a ``PolicyReport``."""
    return PolicyReport(
        domain="tailscale_firewall",
        compliant=bool(raw.get("compliant")),
        issues=list(raw.get("issues") or []),
        planned_changes=int(raw.get("planned_changes") or 0),
        details={"rules": raw.get("rules") or {}},
        hint="./deploy/pfsense-firewall-tailscale.sh apply --dry-run",
    )


async def verify_all_policies(
    client: PfsClient,
    *,
    settings: PfsSettings | None = None,
) -> PolicySuiteReport:
    """Evaluate all registered policy domains (read-only)."""
    active_settings = settings if settings is not None else PfsSettings()
    domains: dict[str, PolicyReport] = {}

    firewall_rules = await fetch_firewall_rules(client)
    domains["tailscale_firewall"] = _wrap_tailscale_firewall(evaluate_tailscale_firewall_policy(firewall_rules))

    restapi_raw = await client.get(EP_RESTAPI_SETTINGS)
    domains["restapi_access"] = evaluate_restapi_access_policy(
        restapi_raw,
        host=active_settings.host,
        api_user=active_settings.api_user,
    )

    domains["api_endpoints"] = await evaluate_api_endpoints_policy(client)

    issues: list[str] = []
    for name, report in domains.items():
        for issue in report.get("issues") or []:
            issues.append(f"{name}: {issue}")

    return PolicySuiteReport(
        compliant=all(report.get("compliant") for report in domains.values()),
        domains=domains,
        issues=issues,
    )


def policy_smoke_checks(suite: PolicySuiteReport) -> list[dict[str, Any]]:
    """Map policy domains to smoke-test result rows."""
    rows: list[dict[str, Any]] = []
    for domain, report in suite["domains"].items():
        name = f"{domain}_policy"
        if report.get("compliant"):
            rows.append({"name": name, "status": "pass"})
            continue
        row: dict[str, Any] = {
            "name": name,
            "status": "fail",
            "error": "; ".join(report.get("issues") or ["policy drift"]),
        }
        if report.get("hint"):
            row["hint"] = report["hint"]
        if report.get("planned_changes"):
            row["planned_changes"] = report["planned_changes"]
        rows.append(row)
    return rows
