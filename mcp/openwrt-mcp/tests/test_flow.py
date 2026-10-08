"""End-to-end plan -> approve -> apply -> confirm flow and negative cases (fake router)."""

import json
import time

import pytest

from openwrt_mcp.approval import grant as grant_mod
from openwrt_mcp.errors import RouterError
from openwrt_mcp.tools.firewall import firewall_inspect_impl, firewall_plan_rule_impl
from openwrt_mcp.tools.plans import apply_plan_impl, confirm_plan_impl, plan_status_impl, rollback_plan_impl
from owrt_testlib import load_fixture

NEW_REV = "sha256:c71d" + "0" * 60


def _result(text: str) -> dict:
    data = json.loads(text)
    assert data["isError"] is False, data
    return data["structuredContent"]


def _error(text: str) -> dict:
    data = json.loads(text)
    assert data["isError"] is True
    return data["error"]


@pytest.fixture
def keys(settings):
    grant_mod.generate_keypair(settings.approver_key_path, settings.approver_pubkey_path, b"correct horse battery")


def approve(ctx, plan_id: str, *, passphrase: bytes = b"correct horse battery", now: int | None = None) -> str:
    plan = ctx.store.require_plan(plan_id)
    payload, nonce = grant_mod.build_payload(plan=plan, requester="mcp-client", approver="tester", now=now)
    text, sig = grant_mod.sign_payload(payload, ctx.settings.approver_key_path, passphrase)
    ctx.store.add_grant(
        plan_id=plan_id, nonce=nonce, payload=text, signature=sig, approver="tester", expires_at=payload["expires_at"]
    )
    return nonce


def script_router(transport, *, apply_ok=True, after_ok=True):
    """Router that reports the new revision/rule after a successful apply."""
    state = {"applied": False}
    before = load_fixture("inspect_ok.json")

    def inspect(_):
        if not state["applied"]:
            return before
        extra = (
            {"nft_rules": ["mcp_allow_metrics", "mcp_allow_alt"]}
            if after_ok
            else {"nft_loaded": False}
        )
        return {**before, "config_revision": NEW_REV, **extra}

    def apply(_):
        state["applied"] = True
        return {"ok": True, "state": "applied_unconfirmed", "new_revision": NEW_REV, "journal_id": "j-1"}

    def rollback(_):
        state["applied"] = False
        return {"ok": True, "state": "rolled_back"}

    transport.handlers.update(
        inspect=inspect,
        apply=apply
        if apply_ok
        else {"ok": False, "error": {"code": "VALIDATION_FAILED", "message": "fw4 check failed"}},
        confirm={"ok": True, "state": "confirmed"},
        rollback=rollback,
        status={"ok": True, "state": "applied_unconfirmed", "new_revision": NEW_REV},
    )


async def make_plan(ctx, key="idem-key-0001", port=8080):
    out = await firewall_plan_rule_impl(
        ctx, router_id="openwrt-pi", rule_id="allow-alt", idempotency_key=key, dest_port=port
    )
    return _result(out)


async def test_inspect_shape(ctx):
    data = _result(await firewall_inspect_impl(ctx, "openwrt-pi"))
    assert data["router_id"] == "openwrt-pi" and data["config_revision"].startswith("sha256:")
    assert data["agent_owned_rules"][0]["id"] == "allow-metrics"


async def test_unauthorized_target(ctx):
    assert _error(await _safe(firewall_inspect_impl(ctx, "other-router")))["code"] == "TARGET_NOT_AUTHORIZED"


async def _safe(coro):
    from openwrt_mcp.errors import DomainError, error_result

    try:
        return await coro
    except DomainError as exc:
        return error_result(exc)


async def test_plan_is_idempotent(ctx):
    a = await make_plan(ctx)
    b = await make_plan(ctx)
    assert a["plan_id"] == b["plan_id"] and a["plan_digest"] == b["plan_digest"]
    with pytest.raises(Exception, match="idempotency_key already used"):
        await make_plan(ctx, port=9090)


async def test_full_happy_path(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    pid, dig = plan["plan_id"], plan["plan_digest"]
    approve(ctx, pid)
    applied = _result(await apply_plan_impl(ctx, pid, dig))
    assert applied["status"] == "pending_confirmation" and applied["watchdog_armed"] is True
    assert applied["checks"]["new_mgmt_connection"] == "ok" and applied["checks"]["rule_state"] == "ok"
    assert ctx.store.lock_holder("openwrt-pi") == pid
    confirmed = _result(await confirm_plan_impl(ctx, pid))
    assert confirmed["status"] == "confirmed" and ctx.store.lock_holder("openwrt-pi") is None
    apply_call = next(c for c in transport.calls if c["op"] == "apply")
    assert set(apply_call["grant"]) == {"payload", "signature"} and "shell" not in json.dumps(apply_call)
    assert ctx.audit.verify()


async def test_apply_without_grant_is_refused(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    with pytest.raises(Exception) as ei:
        await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])
    assert ei.value.code == "APPROVAL_REQUIRED"
    assert "apply" not in transport.ops()


async def test_wrong_digest_refused(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"])
    with pytest.raises(Exception, match="plan_digest"):
        await apply_plan_impl(ctx, plan["plan_id"], "sha256:" + "0" * 64)


async def test_grant_replay_refused(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"])
    await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])
    await confirm_plan_impl(ctx, plan["plan_id"])
    with pytest.raises(Exception, match="only 'planned' plans"):
        await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])


async def test_expired_grant(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"], now=int(time.time()) - 2000)  # payload expiry in the past
    with pytest.raises(Exception) as ei:
        await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])
    assert ei.value.code == "APPROVAL_EXPIRED"


async def test_forged_or_wrong_key_grant_refused(ctx, transport, keys, tmp_path):
    script_router(transport)
    plan = await make_plan(ctx)
    other_key, other_pub = tmp_path / "evil.key", tmp_path / "evil.pub"
    grant_mod.generate_keypair(other_key, other_pub, b"another long passphrase")
    p = ctx.store.require_plan(plan["plan_id"])
    payload, nonce = grant_mod.build_payload(plan=p, requester="mcp-client", approver="evil")
    text, sig = grant_mod.sign_payload(payload, other_key, b"another long passphrase")
    ctx.store.add_grant(
        plan_id=p["plan_id"],
        nonce=nonce,
        payload=text,
        signature=sig,
        approver="evil",
        expires_at=payload["expires_at"],
    )
    with pytest.raises(Exception, match="signature"):
        await apply_plan_impl(ctx, p["plan_id"], p["digest"])


async def test_tampered_payload_refused(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    nonce = approve(ctx, plan["plan_id"])
    g = ctx.store.get_valid_grant(plan["plan_id"])
    tampered = g["payload"].replace("plan_", "plan_"[:-1] + "x")
    ctx.store._db.execute(  # pylint: disable=protected-access
        "UPDATE grants SET payload=? WHERE nonce=?",
        (tampered, nonce),
    )
    with pytest.raises(Exception, match="signature"):
        await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])


async def test_grant_bound_to_other_plan_refused(ctx, transport, keys):
    script_router(transport)
    a = await make_plan(ctx, key="idem-key-000a", port=8080)
    b = await make_plan(ctx, key="idem-key-000b", port=8081)
    pa = ctx.store.require_plan(a["plan_id"])
    payload, nonce = grant_mod.build_payload(plan=pa, requester="mcp-client", approver="tester")
    text, sig = grant_mod.sign_payload(payload, ctx.settings.approver_key_path, b"correct horse battery")
    ctx.store.add_grant(
        plan_id=b["plan_id"],
        nonce=nonce,
        payload=text,
        signature=sig,
        approver="tester",
        expires_at=payload["expires_at"],
    )
    with pytest.raises(Exception, match="not bound"):
        await apply_plan_impl(ctx, b["plan_id"], b["plan_digest"])


async def test_stale_state_refused_before_apply(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"])
    transport.handlers["inspect"] = {**load_fixture("inspect_ok.json"), "config_revision": "sha256:" + "1" * 64}
    with pytest.raises(Exception) as ei:
        await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])
    assert ei.value.code == "STATE_PRECONDITION_FAILED"
    assert "apply" not in transport.ops() and ctx.store.lock_holder("openwrt-pi") is None


async def test_concurrent_transaction_locked(ctx, transport, keys):
    script_router(transport)
    a = await make_plan(ctx, key="idem-key-000a", port=8080)
    approve(ctx, a["plan_id"])
    await apply_plan_impl(ctx, a["plan_id"], a["plan_digest"])  # pending, lock held
    b = await make_plan_after_lock(ctx)
    approve(ctx, b["plan_id"])
    with pytest.raises(Exception) as ei:
        await apply_plan_impl(ctx, b["plan_id"], b["plan_digest"])
    assert ei.value.code == "TARGET_LOCKED"


async def make_plan_after_lock(ctx):
    # Planning against the pre-change snapshot is still possible via the store directly.
    from openwrt_mcp.policy.engine import build_plan

    draft = build_plan(
        router_id="openwrt-pi",
        snapshot=load_fixture("inspect_ok.json"),
        action="upsert",
        rule_id="allow-two",
        fields={"template": "allow_tcp_from_lan", "dest_port": 8081},
        verify_deadline_sec=120,
        plan_ttl_sec=900,
    )
    plan = ctx.store.create_plan(draft=draft, idempotency_key="idem-key-000c", requester="mcp-client")
    return {"plan_id": plan["plan_id"], "plan_digest": plan["digest"]}


async def test_verification_failure_triggers_rollback(ctx, transport, keys):
    script_router(transport, after_ok=False)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"])
    with pytest.raises(Exception) as ei:
        await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])
    assert ei.value.code == "VERIFICATION_FAILED"
    assert "rollback" in transport.ops()
    assert ctx.store.require_plan(plan["plan_id"])["status"] == "rolled_back"
    assert ctx.store.lock_holder("openwrt-pi") is None


async def test_router_validation_failure_marks_failed_and_unlocks(ctx, transport, keys):
    script_router(transport, apply_ok=False)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"])
    with pytest.raises(Exception) as ei:
        await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])
    assert ei.value.code == "VERIFICATION_FAILED"
    assert ctx.store.require_plan(plan["plan_id"])["status"] == "failed"
    assert ctx.store.lock_holder("openwrt-pi") is None


async def test_lost_response_keeps_lock_and_status_reconciles(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"])
    transport.handlers["apply"] = RouterError("router call timed out")
    with pytest.raises(Exception, match="outcome unknown"):
        await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])
    row = ctx.store.require_plan(plan["plan_id"])
    assert row["status"] == "unknown" and ctx.store.lock_holder("openwrt-pi") == plan["plan_id"]
    status = _result(await plan_status_impl(ctx, plan["plan_id"]))  # router journal says applied_unconfirmed
    assert status["status"] == "pending_confirmation"


async def test_confirm_refused_when_probes_fail(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"])
    await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])
    transport.handlers["inspect"] = RouterError("ssh unreachable")  # management path lost
    with pytest.raises(Exception) as ei:
        await confirm_plan_impl(ctx, plan["plan_id"])
    assert ei.value.code == "VERIFICATION_FAILED" and "confirm" not in transport.ops()


async def test_confirm_after_deadline_is_refused(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"])
    await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])
    ctx.store.update_plan(plan["plan_id"], verify_deadline=int(time.time()) - 1)
    transport.handlers["status"] = {"ok": True, "state": "rolled_back"}
    with pytest.raises(Exception, match="deadline passed"):
        await confirm_plan_impl(ctx, plan["plan_id"])
    assert ctx.store.require_plan(plan["plan_id"])["status"] == "rolled_back"


async def test_manual_rollback_and_needs_manual(ctx, transport, keys):
    script_router(transport)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"])
    await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])
    transport.handlers["rollback"] = {"ok": False, "error": {"code": "NEEDS_MANUAL", "message": "config drifted"}}
    with pytest.raises(Exception) as ei:
        await rollback_plan_impl(ctx, plan["plan_id"])
    assert ei.value.code == "NEEDS_MANUAL"
    assert ctx.store.require_plan(plan["plan_id"])["status"] == "needs_manual"


async def test_audit_outage_does_not_block(ctx, transport, keys, monkeypatch):
    script_router(transport)
    plan = await make_plan(ctx)
    approve(ctx, plan["plan_id"])
    ctx.audit._path = ctx.audit._path.parent / "missing" / "x" / "audit.jsonl"  # pylint: disable=protected-access
    monkeypatch.setattr("pathlib.Path.mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
    await apply_plan_impl(ctx, plan["plan_id"], plan["plan_digest"])  # must not raise
