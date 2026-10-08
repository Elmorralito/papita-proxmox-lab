"""Plan building: operations, digest, diff, risk and recovery plan."""

import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from openwrt_mcp.canonical import plan_digest
from openwrt_mcp.constants import POLICY_REVISION
from openwrt_mcp.errors import InvalidInput, OperationProhibited, TargetLocked
from openwrt_mcp.policy.templates import build_delete, build_upsert, render_rule_line


@dataclass(frozen=True)
class PlanDraft:
    """An immutable plan ready to persist."""

    router_id: str
    operations: list[dict[str, Any]]
    state_precondition: str
    policy_revision: int
    recovery: dict[str, Any]
    digest: str
    diff: list[str]
    risk: str
    expires_at: int


def _owned(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index agent-owned rules in a snapshot by id."""
    return {str(r.get("id")): r for r in snapshot.get("agent_owned_rules", []) if isinstance(r, dict)}


def _unwrap(exc: ValidationError) -> Exception:
    """Surface domain errors raised inside pydantic validators; wrap the rest as InvalidInput."""
    for err in exc.errors():
        ctx_err = (err.get("ctx") or {}).get("error")
        if isinstance(ctx_err, (InvalidInput, OperationProhibited)):
            return ctx_err
    fields = ", ".join(sorted({".".join(str(p) for p in e["loc"]) or "?" for e in exc.errors()}))
    return InvalidInput(f"invalid fields: {fields}")


def build_plan(
    *,
    router_id: str,
    snapshot: dict[str, Any],
    action: str,
    rule_id: str,
    fields: dict[str, Any] | None,
    verify_deadline_sec: int,
    plan_ttl_sec: int,
    now: int | None = None,
) -> PlanDraft:
    """Build an immutable plan from a router snapshot.

    Raises:
        InvalidInput / OperationProhibited / TargetLocked: When the request is not plannable.
    """
    if snapshot.get("pending_changes"):
        raise TargetLocked("router has uncommitted UCI changes; refusing to plan on shared pending state")
    if snapshot.get("active_txn"):
        raise TargetLocked("another transaction is active on this router")
    revision = str(snapshot.get("config_revision", ""))
    if not revision.startswith("sha256:"):
        raise InvalidInput("router snapshot has no config revision")

    owned = _owned(snapshot)
    diff: list[str] = []
    if action == "upsert":
        try:
            op = build_upsert(rule_id, fields or {})
        except ValidationError as exc:
            raise _unwrap(exc) from exc
        existing = owned.get(rule_id)
        new_line = render_rule_line(rule_id, op["fields"])
        if existing is not None:
            old_fields = {
                k: existing.get(k) for k in ("src", "proto", "dest_port", "family", "src_ip") if k in existing
            }
            old_fields.setdefault("family", "ipv4")
            if all(old_fields.get(k) == v for k, v in op["fields"].items() if k != "template") and existing.get(
                "enabled", True
            ):
                raise InvalidInput("rule already matches the requested fields; nothing to change")
            diff.append(
                "- "
                + render_rule_line(
                    rule_id, {**{"src": "lan", "proto": "tcp", "dest_port": 0, "family": "ipv4"}, **old_fields}
                )
            )
        diff.append("+ " + new_line)
    elif action == "delete":
        op = build_delete(rule_id)
        existing = owned.get(rule_id)
        if existing is None:
            raise InvalidInput("rule_id is not an agent-owned rule on this router")
        diff.append(
            "- "
            + render_rule_line(
                rule_id,
                {
                    "src": existing.get("src", "lan"),
                    "proto": existing.get("proto", "tcp"),
                    "dest_port": existing.get("dest_port", 0),
                    "family": existing.get("family", "ipv4"),
                    **({"src_ip": existing["src_ip"]} if "src_ip" in existing else {}),
                },
            )
        )
    else:
        raise InvalidInput("action must be 'upsert' or 'delete'")

    recovery = {"mode": "auto_revert", "deadline_s": verify_deadline_sec}
    operations = [op]
    digest = plan_digest(
        router_id=router_id,
        operations=operations,
        state_precondition=revision,
        policy_revision=POLICY_REVISION,
        recovery=recovery,
    )
    return PlanDraft(
        router_id=router_id,
        operations=operations,
        state_precondition=revision,
        policy_revision=POLICY_REVISION,
        recovery=recovery,
        digest=digest,
        diff=diff,
        risk="low",
        expires_at=(now if now is not None else int(time.time())) + plan_ttl_sec,
    )
