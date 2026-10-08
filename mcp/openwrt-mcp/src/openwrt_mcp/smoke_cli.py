"""``openwrt-mcp-smoke``: post-install smoke tests."""

import asyncio
import sys

from dotenv import load_dotenv

from openwrt_mcp.config import OpenwrtSettings
from openwrt_mcp.context import build_context
from openwrt_mcp.tools.smoke_test import run_smoke


def main() -> None:
    """Run smoke tests; exit 1 on any hard failure."""
    load_dotenv()
    try:
        settings = OpenwrtSettings()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"FAIL config: {exc.__class__.__name__}: check OPENWRT_* variables", file=sys.stderr)
        sys.exit(1)
    results = asyncio.run(run_smoke(build_context(settings)))
    for item in results:
        print(f"[{item['status'].upper():4}] {item['name']}: {item['detail']}")
    sys.exit(1 if any(r["status"] == "fail" for r in results) else 0)


if __name__ == "__main__":
    main()
