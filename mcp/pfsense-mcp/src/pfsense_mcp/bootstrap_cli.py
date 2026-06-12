"""One-shot pfREST bootstrap helpers (allowed interfaces, connectivity probes)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from dotenv import load_dotenv

from pfsense_mcp.client.errors import PfsApiError
from pfsense_mcp.client.http import PfsClient
from pfsense_mcp.config import PfsSettings
from pfsense_mcp.constants import EP_RESTAPI_SETTINGS, EP_SYSTEM_VERSION, LAB_PFSENSE_LAN_IP
from pfsense_mcp.logging_config import configure_cli_logging, configure_logging

logger = logging.getLogger("pfsense_mcp.bootstrap_cli")


async def _probe_version(client: PfsClient) -> dict[str, Any]:
    """Probe ``GET /system/version`` for bootstrap connectivity checks."""
    data = await client.get(EP_SYSTEM_VERSION)
    return {"ok": True, "endpoint": EP_SYSTEM_VERSION, "data": data}


async def _fetch_restapi_settings(client: PfsClient) -> dict[str, Any]:
    """Fetch pfREST package settings for bootstrap diagnostics."""
    data = await client.get(EP_RESTAPI_SETTINGS)
    return {"ok": True, "endpoint": EP_RESTAPI_SETTINGS, "data": data}


async def allow_all_interfaces(client: PfsClient) -> dict[str, Any]:
    """Clear allowed_interfaces so pfREST accepts calls on any interface (incl. Tailscale)."""
    before = await client.get(EP_RESTAPI_SETTINGS)
    payload: dict[str, Any] = {"allowed_interfaces": []}
    updated = await client.patch(EP_RESTAPI_SETTINGS, json_body=payload)
    return {
        "ok": True,
        "endpoint": EP_RESTAPI_SETTINGS,
        "before": before,
        "patched": updated,
        "note": "Empty allowed_interfaces permits API on all interfaces; restrict via Access Lists.",
    }


async def _run_with_client(settings: PfsSettings, coro_name: str) -> dict[str, Any]:
    """Run a named bootstrap action with a short-lived pfREST client."""
    client = PfsClient(settings)
    try:
        if coro_name == "allow-all-interfaces":
            return await allow_all_interfaces(client)
        if coro_name == "show-restapi-settings":
            return await _fetch_restapi_settings(client)
        if coro_name == "probe-version":
            return await _probe_version(client)
        raise ValueError(f"Unknown action: {coro_name}")
    finally:
        await client.aclose()


def _settings_for_host(base: PfsSettings, host: str) -> PfsSettings:
    """Clone settings while overriding ``host`` for LAN fallback attempts."""
    return PfsSettings(
        host=host,
        port=base.port,
        api_key=base.api_key,
        api_user=base.api_user,
        verify_ssl=base.verify_ssl,
        hash_algo=base.hash_algo,
        length_bytes=base.length_bytes,
        http_timeout_sec=base.http_timeout_sec,
        log_level=base.log_level,
    )


async def _run_action(action: str, *, fallback_lan: bool) -> dict[str, Any]:
    """Execute a bootstrap action, optionally retrying via the lab LAN IP."""
    settings = PfsSettings()
    hosts = [settings.host]
    if fallback_lan and settings.host != LAB_PFSENSE_LAN_IP:
        hosts.append(LAB_PFSENSE_LAN_IP)

    attempts: list[dict[str, str]] = []
    last_error: Exception | None = None
    for host in hosts:
        attempt_settings = _settings_for_host(settings, host)
        try:
            result = await _run_with_client(attempt_settings, action)
            result["host_used"] = host
            result["hosts_tried"] = hosts
            return result
        except Exception as exc:
            attempts.append({"host": host, "error": str(exc)})
            last_error = exc
            continue

    message = "; ".join(f"{item['host']}: {item['error']}" for item in attempts)
    raise RuntimeError(f"All hosts failed ({message})") from last_error


def main() -> None:
    """CLI entrypoint for pfREST bootstrap utilities."""
    parser = argparse.ArgumentParser(description="pfSense pfREST bootstrap utilities.")
    parser.add_argument(
        "action",
        choices=("allow-all-interfaces", "show-restapi-settings", "probe-version"),
        help="Bootstrap action",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    parser.add_argument(
        "--no-lan-fallback",
        action="store_true",
        help="Do not retry against lab LAN IP when primary host fails",
    )
    args = parser.parse_args()

    load_dotenv()
    configure_logging()
    try:
        settings = PfsSettings()
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(2)

    cli = configure_cli_logging(settings.log_level)

    try:
        report = asyncio.run(_run_action(args.action, fallback_lan=not args.no_lan_fallback))
    except PfsApiError as exc:
        detail = exc.to_dict()
        if args.json:
            cli.info(json.dumps({"ok": False, "error": detail}, indent=2))
        else:
            logger.error("pfREST error: %s", detail.get("message", exc))
            if detail.get("hint"):
                logger.error("hint: %s", detail["hint"])
        sys.exit(1)
    except Exception as exc:
        logger.error("Bootstrap error: %s", exc)
        sys.exit(2)

    if args.json:
        cli.info(json.dumps(report, indent=2, default=str))
    else:
        host = report.get("host_used", "?")
        cli.info("OK (%s) via %s", args.action, host)
        if args.action == "allow-all-interfaces":
            before = report.get("before") or {}
            cli.info("  allowed_interfaces before: %r", before.get("allowed_interfaces"))
            cli.info("  allowed_interfaces after: [] (all interfaces)")


if __name__ == "__main__":
    main()
