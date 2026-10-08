"""Post-install smoke tests (read-only)."""

from typing import Any

from openwrt_mcp.config import OpenwrtSettings
from openwrt_mcp.context import AppContext
from openwrt_mcp.errors import DomainError
from openwrt_mcp.tools.helpers import ok_result


def _check(name: str, ok: bool, detail: str, *, warn: bool = False) -> dict[str, Any]:
    """Build one smoke-check result entry."""
    status = "pass" if ok else ("warn" if warn else "fail")
    return {"name": name, "status": status, "detail": detail}


def static_checks(settings: OpenwrtSettings) -> list[dict[str, Any]]:
    """Checks that need no router connection."""
    kh = settings.known_hosts_path
    pinned = kh.is_file() and settings.host in kh.read_text(encoding="utf-8", errors="ignore")
    return [
        _check("ssh_key_present", settings.ssh_key_path.is_file(), "dedicated agent key file"),
        _check("host_key_pinned", pinned, "known_hosts contains the router host"),
        _check(
            "approver_pubkey_present", settings.approver_pubkey_path.is_file(), "needed to verify grants", warn=True
        ),
    ]


async def run_smoke(ctx: AppContext) -> list[dict[str, Any]]:
    """Run all smoke checks and return a list of results."""
    results = static_checks(ctx.settings)
    try:
        snap = await ctx.agent.inspect()
        results.append(_check("agent_inspect", True, f"agent {snap.get('agent_version')}"))
        results.append(
            _check("config_revision", str(snap.get("config_revision", "")).startswith("sha256:"), "revision")
        )
        results.append(_check("nft_loaded", bool(snap.get("nft_loaded")), "firewall4 ruleset loaded"))
        results.append(_check("clock_ok", bool(snap.get("clock_ok")), "router clock synchronised", warn=True))
        results.append(_check("no_pending_changes", not snap.get("pending_changes"), "no uncommitted UCI changes"))
        results.append(_check("no_wan_exposure", not snap.get("wan_exposure"), "no mcp rule exposes WAN"))
        results.append(
            _check("watchdog_alive", bool(snap.get("watchdog_alive")), "required before any write", warn=True)
        )
    except DomainError as exc:
        results.append(_check("agent_inspect", False, exc.message))
    results.append(_check("audit_chain", ctx.audit.verify(), "hash chain intact"))
    return results


async def run_smoke_tests_impl(ctx: AppContext) -> str:
    """Tool implementation: summarise smoke results."""
    results = await run_smoke(ctx)
    failed = [r for r in results if r["status"] == "fail"]
    return ok_result({"passed": not failed, "checks": results})
