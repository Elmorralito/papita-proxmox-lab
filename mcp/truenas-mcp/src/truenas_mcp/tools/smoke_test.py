"""Post-install smoke tests for TrueNAS MCP."""

from __future__ import annotations

import json
from typing import Any, Literal

from truenas_mcp.client.errors import TnasApiError
from truenas_mcp.config import TnasSettings
from truenas_mcp.context import get_client, get_settings
from truenas_mcp.tools.helpers import critical_alerts, normalize_list, pool_health_warnings
from truenas_mcp.tools.monitoring import _scrutiny_warnings
from truenas_mcp.tools.sharing import nfs_lab_warnings
from truenas_mcp.tools.storage import truenas_list_pools_impl, truenas_list_scrub_tasks_impl
from truenas_mcp.tools.system import truenas_get_system_info_impl, truenas_system_summary_impl

TestStatus = Literal["pass", "fail", "warn"]

CORE_SMOKE_CHECKS = frozenset({"config_valid", "websocket_auth", "system_info", "pools_query"})
OPTIONAL_SMOKE_CHECKS = frozenset(
    {
        "lab_ha_pool",
        "lab_nfs_export",
        "alerts_no_critical",
        "disk_temperature_alerts",
        "scrutiny_app_running",
        "reporting_graph",
    }
)
EXTENDED_SMOKE_CHECKS = frozenset(
    {
        "system_info_tool",
        "list_pools_tool",
        "system_summary_tool",
        "list_nfs_shares_tool",
        "list_scrub_tasks_tool",
        "list_apps_tool",
        "check_api_key_tool",
        "disk_temperature_alerts",
        "reporting_graph",
    }
)


def smoke_core_passed(report: dict[str, Any]) -> bool:
    """True when all core (non-optional) smoke checks pass."""
    return all(item["status"] == "pass" for item in report.get("tests", []) if item.get("name") in CORE_SMOKE_CHECKS)


def _tool_response_ok(response: str) -> bool:
    normalized = response.replace(" ", "").lower()
    return '"ok":true' in normalized


def _failure(name: str, exc: Exception) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "status": "fail", "error": str(exc)}
    if isinstance(exc, TnasApiError):
        payload = exc.to_dict()
        result["error"] = payload.get("message", str(exc))
        if exc.method:
            result["method"] = exc.method
    return result


async def _run_api_check(name: str, coro: Any) -> dict[str, Any]:
    try:
        await coro
        return {"name": name, "status": "pass"}
    except Exception as exc:
        return _failure(name, exc)


def _check_config_valid(settings: TnasSettings) -> dict[str, Any]:
    try:
        TnasSettings.model_validate(settings.model_dump())
        return {"name": "config_valid", "status": "pass"}
    except Exception as exc:
        return {
            "name": "config_valid",
            "status": "fail",
            "error": str(exc),
            "hint": "Set TRUENAS_HOST and TRUENAS_API_KEY in ~/.cursor/mcp.json",
        }


async def _check_system_info(client: Any) -> dict[str, Any]:
    try:
        info = await client.call("system.info")
        if not isinstance(info, dict) or not info.get("version"):
            return {
                "name": "system_info",
                "status": "fail",
                "error": "system.info missing version field",
            }
        return {
            "name": "system_info",
            "status": "pass",
            "data": {
                "hostname": info.get("hostname"),
                "version": info.get("version"),
            },
        }
    except Exception as exc:
        return _failure("system_info", exc)


async def _check_system_state_ready(client: Any) -> dict[str, Any]:
    try:
        state = await client.call("system.state")
        if str(state).upper() != "READY":
            return {
                "name": "system_state_ready",
                "status": "warn",
                "error": f"system.state is {state!r} (expected READY)",
            }
        return {"name": "system_state_ready", "status": "pass", "data": {"state": state}}
    except Exception as exc:
        return _failure("system_state_ready", exc)


async def _check_pools(client: Any, settings: TnasSettings) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        pools = normalize_list(await client.call("pool.query"))
        if not pools:
            results.append({"name": "pools_query", "status": "fail", "error": "pool.query returned no pools"})
            return results
        results.append({"name": "pools_query", "status": "pass", "data": {"count": len(pools)}})

        warnings = pool_health_warnings(pools)
        if warnings:
            results.append(
                {
                    "name": "pools_all_online",
                    "status": "fail",
                    "error": "; ".join(warnings),
                }
            )
        else:
            results.append({"name": "pools_all_online", "status": "pass"})

        ha_pool = next((pool for pool in pools if pool.get("name") == settings.lab_ha_pool_name), None)
        if ha_pool is None:
            results.append(
                {
                    "name": "lab_ha_pool",
                    "status": "warn",
                    "error": f"Pool {settings.lab_ha_pool_name!r} not found",
                    "hint": "Expected Proxmox HA storage pool for this lab",
                }
            )
        else:
            results.append(
                {
                    "name": "lab_ha_pool",
                    "status": "pass",
                    "data": {"status": ha_pool.get("status")},
                }
            )
    except Exception as exc:
        results.append(_failure("pools_query", exc))
    return results


async def _check_alerts(client: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        alerts = normalize_list(await client.call("alert.list"))
        results.append({"name": "alerts_listable", "status": "pass", "data": {"count": len(alerts)}})
        critical = critical_alerts(alerts)
        if critical:
            results.append(
                {
                    "name": "alerts_no_critical",
                    "status": "warn",
                    "error": f"{len(critical)} WARNING/CRITICAL alert(s) active",
                    "data": {"critical_count": len(critical)},
                }
            )
        else:
            results.append({"name": "alerts_no_critical", "status": "pass"})
    except Exception as exc:
        results.append(_failure("alerts_listable", exc))
    return results


async def _check_nfs_shares(client: Any, settings: TnasSettings) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        shares = normalize_list(await client.call("sharing.nfs.query", [[], {"limit": 50}]))
        results.append({"name": "nfs_shares_listable", "status": "pass", "data": {"count": len(shares)}})
        warnings = nfs_lab_warnings(shares, lab_export=settings.lab_nfs_export)
        if warnings:
            results.append(
                {
                    "name": "lab_nfs_export",
                    "status": "warn",
                    "error": "; ".join(warnings),
                    "hint": f"Expected export path containing {settings.lab_nfs_export}",
                }
            )
        else:
            results.append({"name": "lab_nfs_export", "status": "pass"})
    except Exception as exc:
        results.append(_failure("nfs_shares_listable", exc))
    return results


async def _check_v11_reads(client: Any, settings: TnasSettings) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        smart = await client.call("smart.test.results")
        count = len(smart) if isinstance(smart, list) else 0
        results.append({"name": "smart_results_query", "status": "pass", "data": {"count": count}})
    except Exception as exc:
        results.append(_failure("smart_results_query", exc))

    try:
        policies = await client.call("alert.list_policies")
        count = len(policies) if isinstance(policies, list) else 1
        results.append({"name": "alert_policies_query", "status": "pass", "data": {"count": count}})
    except Exception as exc:
        results.append(_failure("alert_policies_query", exc))

    try:
        apps = normalize_list(await client.call("app.query", [[], {"limit": 50}]))
        results.append({"name": "apps_query", "status": "pass", "data": {"count": len(apps)}})
        scrutiny_warnings = _scrutiny_warnings(apps, settings.lab_scrutiny_app_name)
        if scrutiny_warnings:
            results.append(
                {
                    "name": "scrutiny_app_running",
                    "status": "warn",
                    "error": "; ".join(scrutiny_warnings),
                }
            )
        else:
            results.append({"name": "scrutiny_app_running", "status": "pass"})
    except Exception as exc:
        results.append(_failure("apps_query", exc))

    return results


async def _check_reporting_graph(client: Any) -> dict[str, Any]:
    import time

    end = int(time.time())
    start = end - 3600
    try:
        await client.call(
            "reporting.get_data",
            [[{"name": "cpu"}], {"start": start, "end": end, "aggregate": True}],
        )
        return {"name": "reporting_graph", "status": "pass"}
    except TnasApiError as exc:
        return {
            "name": "reporting_graph",
            "status": "warn",
            "error": str(exc),
            "hint": "Reporting may require additional API permissions on some TrueNAS versions",
        }
    except Exception as exc:
        return _failure("reporting_graph", exc)


async def _check_extended_api(client: Any) -> list[dict[str, Any]]:
    probes = [
        ("datasets_query", client.call("pool.dataset.query", [[], {"limit": 5}])),
        ("disks_query", client.call("disk.query")),
        ("jobs_query", client.call("core.get_jobs")),
        ("scrub_tasks_query", client.call("pool.scrub.query", [[], {"limit": 20}])),
    ]
    results: list[dict[str, Any]] = []
    for name, coro in probes:
        try:
            payload = await coro
            count = len(payload) if isinstance(payload, list) else 1
            results.append({"name": name, "status": "pass", "data": {"count": count}})
        except Exception as exc:
            results.append(_failure(name, exc))
    return results


async def _check_disk_temperature(client: Any) -> dict[str, Any]:
    try:
        alerts = await client.call("disk.temperature_alerts")
        count = len(alerts) if isinstance(alerts, list) else 0
        if count:
            return {
                "name": "disk_temperature_alerts",
                "status": "warn",
                "error": f"{count} disk(s) over temperature threshold",
                "data": {"count": count},
            }
        return {"name": "disk_temperature_alerts", "status": "pass"}
    except TnasApiError as exc:
        return {
            "name": "disk_temperature_alerts",
            "status": "warn",
            "error": str(exc),
            "hint": "Method may require elevated API permissions or differ on this TrueNAS version",
        }
    except Exception as exc:
        return _failure("disk_temperature_alerts", exc)


async def _check_tool(name: str, coro: Any) -> dict[str, Any]:
    try:
        response = await coro
        if _tool_response_ok(response):
            return {"name": name, "status": "pass"}
        return {"name": name, "status": "fail", "error": "tool returned error JSON"}
    except Exception as exc:
        return _failure(name, exc)


async def _check_extended_tools() -> list[dict[str, Any]]:
    from truenas_mcp.tools.monitoring import truenas_check_api_key_impl, truenas_list_apps_impl
    from truenas_mcp.tools.sharing import truenas_list_nfs_shares_impl

    tool_probes = [
        ("system_info_tool", truenas_get_system_info_impl()),
        ("check_api_key_tool", truenas_check_api_key_impl()),
        ("list_pools_tool", truenas_list_pools_impl()),
        ("system_summary_tool", truenas_system_summary_impl()),
        ("list_nfs_shares_tool", truenas_list_nfs_shares_impl()),
        ("list_scrub_tasks_tool", truenas_list_scrub_tasks_impl()),
        ("list_apps_tool", truenas_list_apps_impl()),
    ]
    results: list[dict[str, Any]] = []
    for name, coro in tool_probes:
        results.append(await _check_tool(name, coro))
    return results


def _smoke_report(results: list[dict[str, Any]], settings: TnasSettings, *, extended: bool) -> dict[str, Any]:
    passed = sum(1 for item in results if item["status"] == "pass")
    warned = sum(1 for item in results if item["status"] == "warn")
    failed = sum(1 for item in results if item["status"] == "fail")
    return {
        "all_passed": failed == 0 and warned == 0,
        "core_passed": smoke_core_passed({"tests": results}),
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "total": len(results),
        "extended": extended,
        "host": settings.host,
        "ws_uri": settings.ws_uri,
        "verify_ssl": settings.verify_ssl,
        "optional_checks": sorted(OPTIONAL_SMOKE_CHECKS),
        "tests": results,
    }


async def run_smoke_tests(*, extended: bool = False) -> dict[str, Any]:
    """Run post-install smoke checks against the configured TrueNAS host."""
    settings = get_settings()
    client = get_client()
    results: list[dict[str, Any]] = [_check_config_valid(settings)]

    auth = await _run_api_check("websocket_auth", client.call("system.state"))
    results.append(auth)

    if auth["status"] != "pass":
        return _smoke_report(results, settings, extended=extended)

    results.append(await _check_system_info(client))
    results.append(await _check_system_state_ready(client))
    results.extend(await _check_pools(client, settings))
    results.extend(await _check_alerts(client))
    results.extend(await _check_nfs_shares(client, settings))
    results.extend(await _check_v11_reads(client, settings))
    results.extend(await _check_extended_api(client))

    if extended:
        results.append(await _check_disk_temperature(client))
        results.append(await _check_reporting_graph(client))
        results.extend(await _check_extended_tools())

    return _smoke_report(results, settings, extended=extended)


async def truenas_run_smoke_tests_impl(*, extended: bool = False) -> str:
    """MCP tool wrapper for ``run_smoke_tests``."""
    report = await run_smoke_tests(extended=extended)
    return json.dumps(report, indent=2, default=str)
