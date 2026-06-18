"""CLI smoke test runner for TrueNAS MCP."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

from truenas_mcp.config import TnasSettings
from truenas_mcp.context import init_context
from truenas_mcp.logging_config import configure_cli_logging, configure_logging
from truenas_mcp.tools.smoke_test import run_smoke_tests

logger = logging.getLogger("truenas_mcp.smoke_cli")


def main() -> None:
    """CLI entrypoint for post-install TrueNAS MCP smoke tests."""
    parser = argparse.ArgumentParser(description="Run TrueNAS MCP smoke tests.")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Also run MCP tool wrappers and disk temperature checks",
    )
    args = parser.parse_args()

    load_dotenv()
    configure_logging()
    try:
        settings = TnasSettings()
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(2)

    cli = configure_cli_logging(settings.log_level)

    async def _run() -> dict:
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
        cli.info(json.dumps(report, indent=2))
    else:
        for test in report["tests"]:
            status = test["status"]
            mark = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}.get(status, status.upper())
            line = f"[{mark}] {test['name']}"
            if test.get("error"):
                line += f" — {test['error']}"
            cli.info(line)
            if test.get("hint"):
                cli.info("      hint: %s", test["hint"])
        cli.info(
            "\n%d/%d passed, %d warned, %d failed (core=%s, extended=%s, ws_uri=%s)",
            report["passed"],
            report["total"],
            report.get("warned", 0),
            report.get("failed", 0),
            "OK" if report.get("core_passed") else "FAIL",
            report.get("extended", False),
            report.get("ws_uri", "?"),
        )

    sys.exit(0 if report.get("core_passed") else 1)


if __name__ == "__main__":
    main()
