"""CLI smoke test runner for pfSense MCP."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

from pfsense_mcp.config import PfsSettings
from pfsense_mcp.context import init_context
from pfsense_mcp.logging_config import configure_cli_logging, configure_logging
from pfsense_mcp.tools.smoke_test import run_smoke_tests

logger = logging.getLogger("pfsense_mcp.smoke_cli")


def main() -> None:
    """CLI entrypoint for post-install pfSense MCP smoke tests."""
    parser = argparse.ArgumentParser(description="Run pfSense MCP smoke tests.")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    load_dotenv()
    configure_logging()
    try:
        settings = PfsSettings()
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(2)

    cli = configure_cli_logging(settings.log_level)

    async def _run() -> dict:
        """Initialize the client, run smoke tests, and tear down connections."""
        client = init_context(settings)
        try:
            return await run_smoke_tests()
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
            mark = "OK" if test["status"] == "pass" else "FAIL"
            line = f"[{mark}] {test['name']}"
            if test.get("error"):
                line += f" — {test['error']}"
            cli.info(line)
            if test.get("hint"):
                cli.info("      hint: %s", test["hint"])
        cli.info(
            "\n%d/%d passed (core=%s, api_base=%s)",
            report["passed"],
            report["total"],
            "OK" if report.get("core_passed") else "FAIL",
            report.get("api_base", "?"),
        )

    sys.exit(0 if report.get("core_passed") else 1)


if __name__ == "__main__":
    main()
