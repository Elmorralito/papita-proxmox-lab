"""System and Tailscale MCP tool implementations."""

from __future__ import annotations

import asyncio
import ipaddress
import time
from typing import Any

from pfsense_mcp.client.errors import PfsApiError
from pfsense_mcp.client.tailscale_fetch import fetch_tailscale_settings
from pfsense_mcp.constants import (
    EP_GATEWAYS,
    EP_INTERFACES,
    EP_RESTAPI_SETTINGS,
    EP_STATIC_ROUTES,
    EP_SYSTEM_VERSION,
    LAB_LAN_CIDR,
    LAB_PFSENSE_LAN_IP,
)
from pfsense_mcp.context import get_client, get_settings
from pfsense_mcp.tools.helpers import normalize_list, redact_sensitive
from pfsense_mcp.tools.response import ok_response, tool_handler


def _interface_has_lan_cidr(interfaces: list[dict[str, Any]]) -> bool:
    """Return True when any interface address falls inside the lab LAN CIDR."""
    network = ipaddress.ip_network(LAB_LAN_CIDR, strict=False)
    for iface in interfaces:
        for field in ("ipaddr", "ip_address", "address", "subnet"):
            value = iface.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            candidate = value.split("/")[0].strip()
            try:
                if ipaddress.ip_address(candidate) in network:
                    return True
            except ValueError:
                continue
        subnet = iface.get("subnet")
        if isinstance(subnet, str) and subnet.strip() == LAB_LAN_CIDR:
            return True
    return False


def _extract_advertised_routes(tailscale_data: Any) -> list[str]:
    """Parse advertised subnet routes from heterogeneous pfREST Tailscale payloads."""
    if not isinstance(tailscale_data, dict):
        return []
    for key in ("advertised_routes", "advertisedroutes", "routes", "subnet_routes"):
        raw = tailscale_data.get(key)
        if isinstance(raw, list):
            return [str(item) for item in raw if item]
        if isinstance(raw, str) and raw.strip():
            return [part.strip() for part in raw.split(",") if part.strip()]
    return []


def _parse_tailscale_status(data: Any) -> dict[str, Any]:
    """Normalize pfREST or Admin API Tailscale payloads into a stable status dict."""
    if not isinstance(data, dict):
        return {
            "enabled": None,
            "authenticated": None,
            "advertised_routes": [],
            "accept_routes": None,
            "raw": data,
        }
    advertised = _extract_advertised_routes(data)
    enabled = data.get("enable") if "enable" in data else data.get("enabled")
    accept = data.get("accept_routes") if "accept_routes" in data else data.get("acceptsubnetroutes")
    authenticated = data.get("authenticated") or data.get("auth") or data.get("logged_in")
    return {
        "enabled": enabled,
        "authenticated": authenticated,
        "advertised_routes": advertised,
        "accept_routes": accept,
        "device_name": data.get("hostname") or data.get("device_name"),
    }


def _tailscale_warnings(status: dict[str, Any]) -> list[str]:
    """Return operator warnings when Tailscale state drifts from lab expectations."""
    warnings: list[str] = []
    routes = status.get("advertised_routes") or []
    if LAB_LAN_CIDR not in routes:
        warnings.append(f"Tailscale is not advertising {LAB_LAN_CIDR} (lab subnet route missing)")
    if status.get("accept_routes") is False:
        warnings.append("Tailscale 'accept subnet routes' appears disabled (site-to-site may fail)")
    if status.get("enabled") is False:
        warnings.append("Tailscale package appears disabled on pfSense")
    return warnings


def _system_identity(version_data: Any) -> dict[str, Any]:
    """Extract hostname, version, and product fields from ``/system/version`` data."""
    if not isinstance(version_data, dict):
        return {}
    identity: dict[str, Any] = {}
    for key in ("hostname", "host", "domain", "product", "version", "patch", "build"):
        if key in version_data and version_data[key] is not None:
            identity[key] = version_data[key]
    return identity


def _restapi_settings_summary(data: Any) -> dict[str, Any]:
    """Return a redacted summary of pfREST package settings for dashboards."""
    if not isinstance(data, dict):
        return {"reachable": True}
    return redact_sensitive(
        {
            "enabled": data.get("enabled"),
            "auth_methods": data.get("auth_methods"),
            "allowed_interfaces": data.get("allowed_interfaces"),
        }
    )


@tool_handler("pfs_get_version")
async def pfs_get_version_impl() -> str:
    """Return pfSense / pfREST version from ``GET /system/version``."""
    started = time.perf_counter()
    data = redact_sensitive(await get_client().get(EP_SYSTEM_VERSION))
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pfs_get_version", data, duration_ms=duration_ms)


@tool_handler("pfs_get_tailscale_status")
async def pfs_get_tailscale_status_impl() -> str:
    """Return Tailscale state on pfSense, including advertised lab subnet routes."""
    started = time.perf_counter()
    raw = await fetch_tailscale_settings(get_client())
    status = redact_sensitive(_parse_tailscale_status(raw))
    warnings = _tailscale_warnings(status)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pfs_get_tailscale_status",
        status,
        duration_ms=duration_ms,
        warnings=warnings,
    )


@tool_handler("pfs_system_summary")
async def pfs_system_summary_impl() -> str:
    """Aggregate version, interfaces, Tailscale, routing, and REST API health in one call."""
    started = time.perf_counter()
    client = get_client()
    settings = get_settings()
    warnings: list[str] = []

    _results = await asyncio.gather(
        client.get(EP_SYSTEM_VERSION),
        client.get(EP_INTERFACES),
        fetch_tailscale_settings(client),
        client.get(EP_GATEWAYS),
        client.get(EP_STATIC_ROUTES),
        client.get(EP_RESTAPI_SETTINGS),
        return_exceptions=True,
    )
    version_res: Any | BaseException = _results[0]
    interfaces_res: Any | BaseException = _results[1]
    tailscale_res: Any | BaseException = _results[2]
    gateways_res: Any | BaseException = _results[3]
    routes_res: Any | BaseException = _results[4]
    restapi_res: Any | BaseException = _results[5]

    summary: dict[str, Any] = {
        "pfsense_host": settings.host,
        "lab_lan_cidr": LAB_LAN_CIDR,
        "lab_pfsense_lan_ip": LAB_PFSENSE_LAN_IP,
    }

    if isinstance(version_res, Exception):
        warnings.append(f"version: {_error_message(version_res)}")
        summary["version"] = None
        summary["system"] = None
    else:
        summary["version"] = version_res
        summary["system"] = _system_identity(version_res)

    interfaces: list[dict[str, Any]] = []
    if isinstance(interfaces_res, Exception):
        warnings.append(f"interfaces: {_error_message(interfaces_res)}")
    else:
        interfaces = normalize_list(interfaces_res)
        summary["interfaces"] = {"count": len(interfaces)}
        if not _interface_has_lan_cidr(interfaces):
            warnings.append(f"No interface found in lab LAN {LAB_LAN_CIDR}")

    if isinstance(tailscale_res, Exception):
        warnings.append(f"tailscale: {_error_message(tailscale_res)}")
        summary["tailscale"] = None
    else:
        tailscale_status = _parse_tailscale_status(tailscale_res)
        summary["tailscale"] = tailscale_status
        warnings.extend(_tailscale_warnings(tailscale_status))

    if isinstance(gateways_res, Exception):
        warnings.append(f"gateways: {_error_message(gateways_res)}")
        summary["gateways"] = None
    else:
        gateways = normalize_list(gateways_res)
        summary["gateways"] = {"count": len(gateways), "items": redact_sensitive(gateways[:10])}

    if isinstance(routes_res, Exception):
        warnings.append(f"static_routes: {_error_message(routes_res)}")
        summary["static_routes"] = None
    else:
        routes = normalize_list(routes_res)
        summary["static_routes"] = {"count": len(routes), "items": redact_sensitive(routes[:10])}

    if isinstance(restapi_res, Exception):
        warnings.append(f"restapi_settings: {_error_message(restapi_res)}")
        summary["restapi"] = None
    else:
        summary["restapi"] = _restapi_settings_summary(restapi_res)

    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pfs_system_summary",
        summary,
        duration_ms=duration_ms,
        warnings=warnings,
        meta_extra={"proxmox_hint": "Use proxmox-ve MCP to check PVE if LAN route is OK"},
    )


def _error_message(exc: BaseException) -> str:
    """Format an exception for inclusion in system summary warnings."""
    if isinstance(exc, PfsApiError):
        return str(exc)
    return type(exc).__name__ + ": " + str(exc)


async def fetch_restapi_settings() -> Any:
    """Fetch pfREST package settings (used by smoke tests and policy evaluation)."""
    return await get_client().get(EP_RESTAPI_SETTINGS)
