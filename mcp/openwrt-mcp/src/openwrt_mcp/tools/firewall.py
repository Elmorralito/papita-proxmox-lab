"""Firewall read and plan tools."""

import re
import time
from typing import Any

from openwrt_mcp.context import AppContext
from openwrt_mcp.errors import InvalidInput, TargetNotAuthorized
from openwrt_mcp.policy.engine import build_plan
from openwrt_mcp.tools.helpers import iso, ok_result

IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9_.-]{8,64}$"


def check_target(ctx: AppContext, router_id: str) -> None:
    """Only the configured router is addressable."""
    if router_id != ctx.settings.router_id:
        raise TargetNotAuthorized("router_id is not an authorized target")


async def firewall_inspect_impl(ctx: AppContext, router_id: str) -> str:
    """Return the router firewall state (revision, agent-owned rules, runtime summary)."""
    check_target(ctx, router_id)
    snap = await ctx.agent.inspect()
    return ok_result(
        {
            "router_id": router_id,
            "config_revision": snap.get("config_revision"),
            "observed_at": iso(int(time.time())),
            "agent_owned_rules": snap.get("agent_owned_rules", []),
            "runtime_summary": {
                "nft_loaded": bool(snap.get("nft_loaded")),
                "wan_exposure": bool(snap.get("wan_exposure")),
                "tailscale_running": bool(snap.get("tailscale_running")),
            },
            "pending_changes": bool(snap.get("pending_changes")),
            "active_txn": snap.get("active_txn"),
            "watchdog_alive": bool(snap.get("watchdog_alive")),
            "agent_version": snap.get("agent_version"),
        }
    )


async def firewall_plan_rule_impl(
    ctx: AppContext,
    *,
    router_id: str,
    rule_id: str,
    idempotency_key: str,
    action: str = "upsert",
    template: str = "allow_tcp_from_lan",
    dest_port: int | None = None,
    family: str = "ipv4",
    src_ip: str | None = None,
) -> str:
    """Create an immutable plan (no router change)."""
    check_target(ctx, router_id)
    if not re.match(IDEMPOTENCY_PATTERN, idempotency_key or ""):
        raise InvalidInput("idempotency_key must match " + IDEMPOTENCY_PATTERN)
    fields: dict[str, Any] | None = None
    if action == "upsert":
        if dest_port is None:
            raise InvalidInput("dest_port is required for upsert")
        fields = {"template": template, "dest_port": dest_port, "family": family}
        if src_ip is not None:
            fields["src_ip"] = src_ip
    snapshot = await ctx.agent.inspect()
    draft = build_plan(
        router_id=router_id,
        snapshot=snapshot,
        action=action,
        rule_id=rule_id,
        fields=fields,
        verify_deadline_sec=ctx.settings.verify_deadline_sec,
        plan_ttl_sec=ctx.settings.plan_ttl_sec,
    )
    plan = ctx.store.create_plan(draft=draft, idempotency_key=idempotency_key, requester="mcp-client")
    ctx.audit.record("plan_created", plan_id=plan["plan_id"], digest=plan["digest"], router_id=router_id)
    return ok_result(plan_view(plan))


def plan_view(plan: dict[str, Any]) -> dict[str, Any]:
    """Public representation of a plan (never includes grants)."""
    return {
        "plan_id": plan["plan_id"],
        "plan_digest": plan["digest"],
        "router_id": plan["router_id"],
        "state_precondition": plan["state_precondition"],
        "policy_revision": plan["policy_revision"],
        "risk": plan["risk"],
        "approval": "exact_plan_human",
        "recovery": "auto_revert_on_unconfirmed",
        "status": plan["status"],
        "expires_at": iso(plan["expires_at"]),
        "verify_deadline": iso(plan["verify_deadline"]) if plan.get("verify_deadline") else None,
        "new_revision": plan.get("new_revision"),
        "diff": plan["diff"],
        "approve_with": f"openwrt-mcp-approve approve {plan['plan_id']}",
    }
