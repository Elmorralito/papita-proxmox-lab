"""Command-line entry point for post-install Proxmox VE MCP smoke tests.

Exposes the ``proxmox-ve-mcp-smoke`` console script (see ``pyproject.toml``). Loads ``PVE_*``
settings from the environment or a ``.env`` file, runs :func:`~proxmox_ve_mcp.tools.smoke_test.run_smoke_tests`,
and prints either a human-readable summary or a JSON report on stdout.

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
import sys

from dotenv import load_dotenv

from proxmox_ve_mcp.config import PveSettings
from proxmox_ve_mcp.context import init_context
from proxmox_ve_mcp.tools.smoke_test import run_smoke_tests


def main() -> None:
    """Parse CLI arguments, run smoke tests, and exit with an appropriate status code.

    Loads environment variables, validates settings, initializes the HTTP client, executes
    the smoke test suite, and prints results. Errors during settings validation or test
    execution are written to stderr.

    Command-line flags:

        ``--extended``:
            Include extended read probes (network, guests, storage, Ceph, write capability).
        ``--json``:
            Print the full structured report as JSON instead of the default text summary.

    Side Effects:
        Exits with code ``2`` on configuration or unhandled runtime errors, ``1`` when any
        test failed, and ``0`` when ``all_passed`` is true. Closes the HTTP client after tests
        complete.

    Note:
        Requires the same ``PVE_*`` variables as the MCP server; ``deploy/mcp.sh smoke`` can
        load them from ``~/.cursor/mcp.json`` before invoking this script.
    """
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
    try:
        settings = PveSettings()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(2)

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
        print(f"Smoke test error: {exc}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        summary = report["summary"]
        print(f"Access level: {report['access_level']}")
        print(f"Host: {report['api_entry_host']} ({report['api_user']}!{report['token_id']})")
        print(f"Mode: {'extended' if report['extended'] else 'basic'}")
        print(
            f"Results: {summary['passed']} passed, {summary['failed']} failed, "
            f"{summary['warned']} warned, {summary['skipped']} skipped"
        )
        for test in report["tests"]:
            mark = {"pass": "OK", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}[test["status"]]
            detail = f" — {test['detail']}" if test.get("detail") else ""
            print(f"  [{mark}] {test['id']}{detail}")
        for rec in report.get("recommendations", []):
            print(f"  → {rec}")

    sys.exit(0 if report.get("all_passed") else 1)


if __name__ == "__main__":
    main()
