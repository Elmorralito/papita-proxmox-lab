"""Apply agreed Tailscale-tab firewall rules via pfREST (one-shot bootstrap)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from dotenv import load_dotenv

from pfsense_mcp.client.http import PfsClient
from pfsense_mcp.config import PfsSettings
from pfsense_mcp.firewall_policy import apply_tailscale_firewall_rules
from pfsense_mcp.logging_config import configure_cli_logging, configure_logging
from pfsense_mcp.tools.smoke_test import smoke_core_passed

logger = logging.getLogger("pfsense_mcp.firewall_cli")


async def _run(*, dry_run: bool, run_smoke: bool) -> dict:
    """Apply Tailscale firewall rules using a short-lived pfREST client."""
    settings = PfsSettings()
    client = PfsClient(settings)
    try:
        return await apply_tailscale_firewall_rules(client, dry_run=dry_run, run_smoke=run_smoke)
    finally:
        await client.aclose()


def main() -> None:
    """CLI entrypoint to apply agreed Tailscale-tab firewall rules via pfREST."""
    load_dotenv()
    configure_logging()
    try:
        settings = PfsSettings()
    except Exception as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(2)

    cli = configure_cli_logging(settings.log_level)

    parser = argparse.ArgumentParser(description="Apply agreed Tailscale-tab pfSense firewall rules.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned changes without applying")
    parser.add_argument("--skip-smoke", action="store_true", help="Do not run MCP smoke tests after apply")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    args = parser.parse_args()

    try:
        result = asyncio.run(_run(dry_run=args.dry_run, run_smoke=not args.skip_smoke))
    except Exception as exc:
        logger.error("Firewall apply failed: %s", exc)
        sys.exit(1)

    if args.json:
        cli.info(json.dumps(result, indent=2))
    else:
        if result.get("dry_run"):
            cli.info("Dry run — %d change(s) planned:", len(result.get("changes", [])))
        else:
            applied_count = len(result.get("applied", []))
            if applied_count:
                cli.info("Applied %d change(s).", applied_count)
            else:
                cli.info("No firewall changes required.")
        for change in result.get("changes", []):
            action = change["action"]
            kind = change.get("kind", "?")
            rule_id = change.get("id")
            suffix = f" id={rule_id}" if rule_id is not None else ""
            cli.info("  - %s [%s]%s", action, kind, suffix)
        if result.get("firewall_apply") and result.get("firewall_apply") != {"skipped": "no changes"}:
            cli.info("Firewall changes applied (POST /firewall/apply).")
        policy = result.get("policy_after")
        if policy is not None:
            state = "compliant" if policy.get("compliant") else "drift"
            cli.info("Policy after apply: %s", state)
        smoke = result.get("smoke_test")
        if smoke:
            cli.info(
                "Post-change smoke: %d/%d passed (core=%s)",
                smoke["passed"],
                smoke["total"],
                "OK" if smoke.get("core_passed") else "FAIL",
            )
            for test in smoke.get("tests", []):
                mark = "OK" if test["status"] == "pass" else "FAIL"
                line = f"  [{mark}] {test['name']}"
                if test.get("error"):
                    line += f" — {test['error']}"
                cli.info(line)

    if result.get("dry_run"):
        sys.exit(0)

    smoke = result.get("smoke_test")
    if smoke and not smoke_core_passed(smoke):
        sys.exit(1)
    if result.get("policy_after") and not result["policy_after"].get("compliant"):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
