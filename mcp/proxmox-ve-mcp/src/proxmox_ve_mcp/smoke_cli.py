"""Command-line entry point for post-install Proxmox VE MCP smoke tests.

Exposes the ``proxmox-ve-mcp-smoke`` console script (see ``pyproject.toml``). Loads ``PVE_*``
settings from the environment or a ``.env`` file, runs :func:`~proxmox_ve_mcp.tools.smoke_test.run_smoke_tests`,
and emits either a human-readable summary or a JSON report on stdout via the CLI logger.

Exit codes:

    ``0`` — all executed tests passed (failures in optional extended probes still yield ``1``).
    ``1`` — one or more tests failed (``all_passed`` is false).
    ``2`` — configuration or unexpected runtime error before a report was produced.

Also invoked indirectly via ``./deploy/mcp.sh smoke`` in the parent repository.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import init_context
from proxmox_ve_mcp.logging_config import configure_cli_logging, configure_logging
from proxmox_ve_mcp.tools.smoke_test import run_smoke_tests

logger = logging.getLogger("proxmox_ve_mcp.smoke_cli")


def main() -> None:
    """Parse CLI arguments, run smoke tests, and exit with an appropriate status code."""
    parser = argparse.ArgumentParser(
        description="Run Proxmox VE MCP post-install connectivity and access smoke tests.",
    )
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Include extended read probes (network, guests, storage, Ceph)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON report (default: human summary)",
    )
    args = parser.parse_args()

    load_dotenv()
    configure_logging()
    try:
        settings = PveSettings()
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(2)

    cli = configure_cli_logging(settings.log_level)

    async def _run() -> dict:
        """Initialize the client, run smoke tests, and tear down the HTTP session."""
        client = init_context(settings)
        try:
            return await run_smoke_tests(extended=args.extended)
        finally:
            await client.aclose()

    try:
        report = asyncio.run(_run())
    except Exception as exc:
        logger.error("Smoke test error: %s", exc)
        sys.exit(2)

    if args.json:
        cli.info(json.dumps(report, indent=2, default=str))
    else:
        summary = report["summary"]
        cli.info("Access level: %s", report["access_level"])
        cli.info("Host: %s (%s!%s)", report["api_entry_host"], report["api_user"], report["token_id"])
        cli.info("Mode: %s", "extended" if report["extended"] else "basic")
        cli.info(
            "Results: %d passed, %d failed, %d warned, %d skipped",
            summary["passed"],
            summary["failed"],
            summary["warned"],
            summary["skipped"],
        )
        for test in report["tests"]:
            mark = {"pass": "OK", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}[test["status"]]
            detail = f" — {test['detail']}" if test.get("detail") else ""
            cli.info("  [%s] %s%s", mark, test["id"], detail)
        for rec in report.get("recommendations", []):
            cli.info("  → %s", rec)

    sys.exit(0 if report.get("all_passed") else 1)


if __name__ == "__main__":
    main()
