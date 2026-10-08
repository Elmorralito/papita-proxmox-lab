"""Plan lifecycle tools: status, apply, confirm, rollback."""

import time

from openwrt_mcp.approval.grant import verify_grant_for_plan
from openwrt_mcp.context import AppContext
from openwrt_mcp.errors import (
    ApprovalExpired,
    ApprovalRequired,
    DomainError,
    InvalidInput,
    RouterError,
    StatePreconditionFailed,
    VerificationFailed,
)
from openwrt_mcp.tools.firewall import plan_view
from openwrt_mcp.tools.helpers import ok_result
from openwrt_mcp.verify.probes import run_probes

_ROUTER_TO_PLAN_STATE = {
    "applied_unconfirmed": "pending_confirmation",
    "armed": "applying",
    "confirmed": "confirmed",
    "rolled_back": "rolled_back",
    "needs_manual": "needs_manual",
}


def _failed_checks(result: dict) -> str:
    """Summarize failed verification checks."""
    bad = sorted(k for k, v in result["checks"].items() if v not in ("ok", "pass", "skipped"))
    return "failed checks: " + ", ".join(bad)


async def _sync_from_router(ctx: AppContext, plan: dict) -> dict:
    """Reconcile local state with the router journal (used after lost responses and deadlines)."""
    try:
        resp = await ctx.agent.status(plan["plan_id"])
    except DomainError as exc:
        if exc.code == "NOT_FOUND" and plan["status"] in ("applying", "unknown"):
            ctx.store.update_plan(plan["plan_id"], status="failed", detail="router has no journal for plan")
            ctx.store.release_lock(plan["router_id"], plan["plan_id"])
            return ctx.store.require_plan(plan["plan_id"])
        return plan
    mapped = _ROUTER_TO_PLAN_STATE.get(str(resp.get("state")))
    if mapped and mapped != plan["status"]:
        ctx.store.update_plan(plan["plan_id"], status=mapped, new_revision=resp.get("new_revision"))
        if mapped in ("confirmed", "rolled_back", "needs_manual"):
            ctx.store.release_lock(plan["router_id"], plan["plan_id"])
        ctx.audit.record("plan_synced", plan_id=plan["plan_id"], status=mapped)
        return ctx.store.require_plan(plan["plan_id"])
    return plan


async def plan_status_impl(ctx: AppContext, plan_id: str) -> str:
    """Return plan status, reconciling with the router for in-flight transactions."""
    plan = ctx.store.require_plan(plan_id)
    now = int(time.time())
    if plan["status"] == "planned" and plan["expires_at"] <= now:
        ctx.store.update_plan(plan_id, status="expired")
        plan = ctx.store.require_plan(plan_id)
    elif plan["status"] in ("applying", "pending_confirmation", "unknown"):
        plan = await _sync_from_router(ctx, plan)
    view = plan_view(plan)
    view["has_valid_grant"] = ctx.store.get_valid_grant(plan_id) is not None
    return ok_result(view)


async def apply_plan_impl(ctx: AppContext, plan_id: str, plan_digest: str) -> str:
    """Apply an approved plan: verify grant, lock, apply with watchdog, verify."""
    plan = ctx.store.require_plan(plan_id)
    if plan["digest"] != plan_digest:
        raise InvalidInput("plan_digest does not match the stored plan")
    if plan["status"] != "planned":
        raise InvalidInput(f"plan is {plan['status']}; only 'planned' plans can be applied")
    now = int(time.time())
    if plan["expires_at"] <= now:
        ctx.store.update_plan(plan_id, status="expired")
        raise ApprovalExpired("plan expired")

    grant = ctx.store.get_valid_grant(plan_id)
    if grant is None:
        if ctx.store.has_expired_grant(plan_id):
            raise ApprovalExpired("The grant for this plan has expired.")
        raise ApprovalRequired("No valid grant for plan_digest.")
    verify_grant_for_plan(grant, plan, ctx.settings.approver_pubkey_path)

    ctx.store.acquire_lock(plan["router_id"], plan_id)
    keep_lock = False
    try:
        snap = await ctx.agent.inspect()
        if snap.get("config_revision") != plan["state_precondition"]:
            raise StatePreconditionFailed("Configuration changed since planning.")
        if not ctx.store.consume_grant(grant["nonce"]):
            raise ApprovalRequired("grant already consumed")
        ctx.store.update_plan(plan_id, status="applying")
        ctx.audit.record("apply_started", plan_id=plan_id, digest=plan_digest, approver=grant["approver"])
        try:
            resp = await ctx.agent.apply(
                plan_id=plan_id,
                plan_digest=plan_digest,
                router_id=plan["router_id"],
                policy_revision=plan["policy_revision"],
                state_precondition=plan["state_precondition"],
                operations=plan["operations"],
                recovery=plan["recovery"],
                grant={"payload": grant["payload"], "signature": grant["signature"]},
            )
        except RouterError as exc:
            if exc.code == "ROUTER_ERROR":
                # Response may have been lost; the router may have applied. Query status before retrying.
                keep_lock = True
                ctx.store.update_plan(plan_id, status="unknown", detail="apply response lost")
                ctx.audit.record("apply_unknown", plan_id=plan_id)
                raise RouterError(
                    "apply outcome unknown; call owrt_plan_status before retrying", retryable=False
                ) from exc
            raise
        except DomainError:
            ctx.store.update_plan(plan_id, status="failed")
            raise

        deadline = now + int(plan["recovery"]["deadline_s"])
        ctx.store.update_plan(
            plan_id, status="pending_confirmation", new_revision=resp.get("new_revision"), verify_deadline=deadline
        )
        ctx.audit.record("applied_unconfirmed", plan_id=plan_id, new_revision=resp.get("new_revision"))
        result = await run_probes(ctx.settings, ctx.agent, plan, expect_revision=resp.get("new_revision"))
        if not result["passed"]:
            ctx.audit.record("verification_failed", plan_id=plan_id, checks=result["checks"])
            try:
                await ctx.agent.rollback(plan_id)
                ctx.store.update_plan(plan_id, status="rolled_back", detail=_failed_checks(result))
            except DomainError:
                keep_lock = True  # watchdog will recover; status/sync will reconcile
            raise VerificationFailed("Verification failed; recovery executed or escalated. " + _failed_checks(result))
        view = plan_view(ctx.store.require_plan(plan_id))
        view.update(
            {
                "status": "pending_confirmation",
                "watchdog_armed": True,
                "checks": result["checks"],
                "next": "call owrt_plan_confirm before verify_deadline or the router rolls back automatically",
            }
        )
        keep_lock = True
        return ok_result(view)
    finally:
        if not keep_lock:
            ctx.store.release_lock(plan["router_id"], plan_id)


async def confirm_plan_impl(ctx: AppContext, plan_id: str) -> str:
    """Confirm only if server-side verification passes before the deadline."""
    plan = ctx.store.require_plan(plan_id)
    if plan["status"] in ("applying", "unknown"):
        plan = await _sync_from_router(ctx, plan)
    if plan["status"] != "pending_confirmation":
        raise InvalidInput(f"plan is {plan['status']}; nothing to confirm")
    if plan.get("verify_deadline") and int(time.time()) >= plan["verify_deadline"]:
        plan = await _sync_from_router(ctx, plan)
        raise VerificationFailed(f"Verify deadline passed; plan is {plan['status']}.")
    result = await run_probes(ctx.settings, ctx.agent, plan, expect_revision=plan.get("new_revision"))
    if not result["passed"]:
        ctx.audit.record("confirm_refused", plan_id=plan_id, checks=result["checks"])
        raise VerificationFailed("Confirmation refused; " + _failed_checks(result))
    await ctx.agent.confirm(plan_id)
    ctx.store.update_plan(plan_id, status="confirmed")
    ctx.store.release_lock(plan["router_id"], plan_id)
    ctx.audit.record("confirmed", plan_id=plan_id)
    return ok_result({"plan_id": plan_id, "status": "confirmed", "watchdog_disarmed": True, "checks": result["checks"]})


async def rollback_plan_impl(ctx: AppContext, plan_id: str) -> str:
    """Roll back an unconfirmed transaction."""
    plan = ctx.store.require_plan(plan_id)
    if plan["status"] not in ("pending_confirmation", "unknown", "applying"):
        raise InvalidInput(f"plan is {plan['status']}; nothing to roll back")
    try:
        await ctx.agent.rollback(plan_id)
    except RouterError as exc:
        if exc.code == "NEEDS_MANUAL":
            ctx.store.update_plan(plan_id, status="needs_manual", detail="rollback refused: config drifted")
            ctx.store.release_lock(plan["router_id"], plan_id)
            ctx.audit.record("needs_manual", plan_id=plan_id)
        raise
    ctx.store.update_plan(plan_id, status="rolled_back")
    ctx.store.release_lock(plan["router_id"], plan_id)
    ctx.audit.record("rolled_back", plan_id=plan_id, by="operator")
    return ok_result({"plan_id": plan_id, "status": "rolled_back"})
