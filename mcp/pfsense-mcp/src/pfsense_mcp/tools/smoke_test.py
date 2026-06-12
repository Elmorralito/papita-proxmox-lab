"""Post-install smoke tests for pfSense MCP."""

from __future__ import annotations

import time
from typing import Any, Literal

from pfsense_mcp.client.errors import PfsApiError
from pfsense_mcp.client.tailscale_fetch import fetch_tailscale_settings
from pfsense_mcp.config import PfsSettings
from pfsense_mcp.constants import EP_INTERFACES, EP_SYSTEM_VERSION, LAB_LAN_CIDR
from pfsense_mcp.context import get_client, get_settings
from pfsense_mcp.policy.registry import policy_smoke_checks, verify_all_policies
from pfsense_mcp.tools.helpers import normalize_list
from pfsense_mcp.tools.response import ok_response, tool_handler
from pfsense_mcp.tools.system import (
    _interface_has_lan_cidr,
    _parse_tailscale_status,
    fetch_restapi_settings,
)

TestStatus = Literal["pass", "fail"]

# Optional smoke checks — failure does not block core lab MCP / firewall apply success.
OPTIONAL_SMOKE_CHECKS = frozenset({"tailscale_subnet_route"})


def smoke_core_passed(report: dict[str, Any]) -> bool:
    """True when all non-optional smoke checks pass."""
    return all(
        item["status"] == "pass" for item in report.get("tests", []) if item.get("name") not in OPTIONAL_SMOKE_CHECKS
    )


def _failure(name: str, exc: Exception) -> dict[str, Any]:
    """Build a failed smoke-test row from an exception."""
    detail = str(exc)
    result: dict[str, Any] = {"name": name, "status": "fail", "error": detail}
    if isinstance(exc, PfsApiError):
        payload = exc.to_dict()
        result["error"] = payload.get("message", detail)
        if payload.get("hint"):
            result["hint"] = payload["hint"]
        if payload.get("pfrest_response_id"):
            result["pfrest_response_id"] = payload["pfrest_response_id"]
        if exc.status_code is not None:
            result["http_status"] = exc.status_code
    return result


async def _run_check(name: str, coro: Any) -> dict[str, Any]:
    """Run an async probe and return pass/fail metadata."""
    try:
        await coro
        return {"name": name, "status": "pass"}
    except Exception as exc:
        return _failure(name, exc)


def _is_transport_error(exc: PfsApiError) -> bool:
    """Return True when pfREST was not reached due to TLS or connection failure."""
    if exc.status_code is not None:
        return False
    lowered = str(exc).lower()
    return "certificate verify failed" in lowered or "ssl" in lowered or "connect" in lowered


async def _check_lab_policies(client: Any, settings: PfsSettings) -> list[dict[str, Any]]:
    """Evaluate registered lab policy domains and map them to smoke rows."""
    suite = await verify_all_policies(client, settings=settings)
    return policy_smoke_checks(suite)


def _check_config_valid(active_settings: PfsSettings) -> dict[str, Any]:
    """Validate that core ``PfsSettings`` fields reload cleanly."""
    try:
        PfsSettings(
            host=active_settings.host,
            port=active_settings.port,
            api_key=active_settings.api_key,
            api_user=active_settings.api_user,
            verify_ssl=active_settings.verify_ssl,
        )
        return {"name": "config_valid", "status": "pass"}
    except Exception as exc:
        return {"name": "config_valid", "status": "fail", "error": str(exc)}


def _auth_checks_from_transport(exc: PfsApiError, active_settings: PfsSettings) -> list[dict[str, Any]]:
    """Build smoke rows when pfREST is unreachable before auth."""
    hint = None
    if "certificate verify failed" in str(exc).lower() and active_settings.verify_ssl:
        hint = (
            "TLS certificate is not valid for the configured IP. "
            "Set PFSENSE_VERIFY_SSL=false when using a Tailscale IP, "
            "or use the LAN IP when the subnet route is active."
        )
    return [
        _failure("api_reachable", exc) | ({"hint": hint} if hint else {}),
        {
            "name": "api_key_valid",
            "status": "fail",
            "error": "blocked before pfREST auth (transport/TLS failure)",
        },
    ]


def _auth_checks_from_403(exc: PfsApiError) -> list[dict[str, Any]]:
    """Build smoke rows when pfREST returns HTTP 403 on version probe."""
    results: list[dict[str, Any]] = [
        {"name": "api_reachable", "status": "pass", "http_status": 403},
    ]
    if exc.pfrest_response_id == "ENDPOINT_INTERFACE_NOT_ALLOWED":
        results.append(
            {
                "name": "api_key_valid",
                "status": "fail",
                "error": "not verified — interface policy blocked before auth",
                "hint": exc.to_dict().get("hint"),
                "pfrest_response_id": exc.pfrest_response_id,
            }
        )
    else:
        results.append({"name": "api_key_valid", "status": "pass", "http_status": 403})
    results.extend([_failure("restapi_settings", exc), _failure("lan_cidr", exc)])
    return results


async def _check_api_auth(active_client: Any, active_settings: PfsSettings) -> list[dict[str, Any]]:
    """Probe version endpoint for reachability and API key validity."""
    try:
        await active_client.get(EP_SYSTEM_VERSION)
        return [
            {"name": "api_reachable", "status": "pass"},
            {"name": "api_key_valid", "status": "pass"},
        ]
    except PfsApiError as exc:
        if _is_transport_error(exc):
            return _auth_checks_from_transport(exc, active_settings)
        if exc.status_code == 401:
            return [
                {"name": "api_reachable", "status": "pass", "http_status": 401},
                _failure("api_key_valid", exc),
            ]
        if exc.status_code == 403:
            return _auth_checks_from_403(exc)
        return [
            _failure("api_reachable", exc),
            {"name": "api_key_valid", "status": "fail", "error": "blocked before auth OK"},
        ]
    except Exception as exc:
        return [_failure("api_reachable", exc), _failure("api_key_valid", exc)]


async def _check_dependent_reads(active_client: Any) -> list[dict[str, Any]]:
    """Fetch REST API settings and verify lab LAN CIDR presence."""
    results: list[dict[str, Any]] = [await _run_check("restapi_settings", fetch_restapi_settings())]
    try:
        interfaces = normalize_list(await active_client.get(EP_INTERFACES))
        if _interface_has_lan_cidr(interfaces):
            results.append({"name": "lan_cidr", "status": "pass"})
        else:
            results.append(
                {
                    "name": "lan_cidr",
                    "status": "fail",
                    "error": f"No interface in {LAB_LAN_CIDR}",
                }
            )
    except Exception as exc:
        results.append(_failure("lan_cidr", exc))
    return results


async def _check_tailscale_route(active_client: Any) -> dict[str, Any]:
    """Verify the lab subnet route is advertised on pfSense Tailscale."""
    try:
        raw = await fetch_tailscale_settings(active_client)
        status = _parse_tailscale_status(raw)
        routes = status.get("advertised_routes") or []
        if LAB_LAN_CIDR in routes:
            return {"name": "tailscale_subnet_route", "status": "pass"}
        return {
            "name": "tailscale_subnet_route",
            "status": "fail",
            "error": f"{LAB_LAN_CIDR} not in advertised routes: {routes}",
        }
    except Exception as exc:
        return _failure("tailscale_subnet_route", exc)


def _smoke_report(results: list[dict[str, Any]], active_settings: PfsSettings) -> dict[str, Any]:
    """Aggregate smoke rows into the final report dict."""
    passed = sum(1 for item in results if item["status"] == "pass")
    return {
        "all_passed": passed == len(results),
        "core_passed": smoke_core_passed({"tests": results}),
        "passed": passed,
        "total": len(results),
        "host": active_settings.host,
        "api_user": active_settings.api_user,
        "api_base": active_settings.base_url,
        "verify_ssl": active_settings.verify_ssl,
        "tests": results,
    }


async def run_smoke_tests(
    *,
    client: Any | None = None,
    settings: PfsSettings | None = None,
) -> dict[str, Any]:
    """Run the full post-install smoke suite against pfREST and lab policy domains."""
    active_client = client or get_client()
    active_settings = settings or get_settings()
    results: list[dict[str, Any]] = [_check_config_valid(active_settings)]
    results.extend(await _check_api_auth(active_client, active_settings))

    if not any(item["name"] == "restapi_settings" for item in results):
        results.extend(await _check_dependent_reads(active_client))

    results.append(await _check_tailscale_route(active_client))

    try:
        results.extend(await _check_lab_policies(active_client, active_settings))
    except Exception as exc:
        results.append(_failure("lab_policy", exc))

    return _smoke_report(results, active_settings)


async def run_post_firewall_smoke_tests(
    *,
    client: Any,
    settings: PfsSettings,
) -> dict[str, Any]:
    """Run full MCP smoke suite after a live firewall apply."""
    return await run_smoke_tests(client=client, settings=settings)


@tool_handler("pfs_run_smoke_tests")
async def pfs_run_smoke_tests_impl() -> str:
    """MCP tool wrapper that runs ``run_smoke_tests`` and returns a JSON report."""
    started = time.perf_counter()
    report = await run_smoke_tests()
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response("pfs_run_smoke_tests", report, duration_ms=duration_ms)
