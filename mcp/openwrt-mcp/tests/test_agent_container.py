"""Router agent functional + fault tests against a real OpenWrt rootfs container.

Run with:  OPENWRT_MCP_DOCKER_TESTS=1 pytest tests/test_agent_container.py
Requires docker and network (apk add ucode-mod-digest). Uses the real ucode agent, real usign signature
verification, real firewall4 (`fw4 check/reload`) and the real Python control plane.
"""

import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from openwrt_mcp.approval import grant as grant_mod
from openwrt_mcp.canonical import plan_digest
from openwrt_mcp.config import OpenwrtSettings
from openwrt_mcp.context import AppContext, build_context
from openwrt_mcp.errors import RouterError
from openwrt_mcp.tools.firewall import firewall_plan_rule_impl
from openwrt_mcp.tools.plans import apply_plan_impl, confirm_plan_impl, plan_status_impl, rollback_plan_impl

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENWRT_MCP_DOCKER_TESTS") != "1" or shutil.which("docker") is None,
    reason="set OPENWRT_MCP_DOCKER_TESTS=1 (needs docker + network)",
)

IMAGE = os.environ.get("OPENWRT_MCP_TEST_IMAGE", "openwrt/rootfs:aarch64_generic-25.12.5")
AGENT_DIR = Path(__file__).resolve().parents[1] / "router-agent"
PASS = b"correct horse battery"


def _d(*args: str, stdin: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=stdin, capture_output=True, check=check, timeout=180)


class ContainerRouter:
    """A throwaway OpenWrt 'router' with the agent installed."""

    def __init__(self, tmp: Path) -> None:
        self.name = "owrt-mcp-test-" + uuid.uuid4().hex[:8]
        self.key, self.pub = tmp / "approver.key", tmp / "approver.pub"
        grant_mod.generate_keypair(self.key, self.pub, PASS)
        _d("run", "-d", "--name", self.name, "--cap-add", "NET_ADMIN", IMAGE, "sleep", "3600")
        self.sh("mkdir -p /var/lock /var/run /etc/openwrt-mcp && apk add ucode-mod-digest >/dev/null")
        _d("cp", str(AGENT_DIR / "openwrt-mcp-agent.uc"), f"{self.name}:/usr/libexec/openwrt-mcp-agent")
        _d("cp", str(AGENT_DIR / "openwrt-mcp-watchdog"), f"{self.name}:/usr/libexec/openwrt-mcp-watchdog")
        _d("cp", str(self.pub), f"{self.name}:/etc/openwrt-mcp/approver.pub")
        self.sh("chmod 755 /usr/libexec/openwrt-mcp-*; fw4 -q start")
        # Stand-in for the Tailscale daemon so the 'tailscale_running' verification has something to see.
        self.sh(
            "printf '#!/bin/sh\\nwhile :; do sleep 60; done\\n'"
            " > /usr/sbin/tailscaled; chmod +x /usr/sbin/tailscaled"
        )
        _d("exec", "-d", self.name, "/usr/sbin/tailscaled")
        self.start_watchdog()

    def sh(self, cmd: str, check: bool = True) -> str:
        return _d("exec", self.name, "sh", "-c", cmd, check=check).stdout.decode()

    def start_watchdog(self) -> None:
        _d("exec", "-d", self.name, "/usr/libexec/openwrt-mcp-watchdog")
        for _ in range(20):
            if self.sh("test -f /var/run/openwrt-mcp/watchdog.alive && echo y", check=False).strip() == "y":
                return
            time.sleep(0.3)
        raise RuntimeError("watchdog did not start")

    def stop_watchdog(self) -> None:
        # The [g] keeps this very command line from matching its own pattern.
        self.sh(
            "for d in /proc/[0-9]*; do"
            " grep -q 'openwrt-mcp-watchdo[g]' $d/cmdline 2>/dev/null && kill ${d#/proc/};"
            " done; sleep 1; rm -f /var/run/openwrt-mcp/watchdog.alive",
            check=False,
        )

    async def call(self, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", self.name, "/usr/libexec/openwrt-mcp-agent",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()), timeout or 120)
        try:
            return json.loads(out.decode())
        except json.JSONDecodeError as exc:
            raise RouterError(f"bad agent output: {out!r} {err!r}") from exc

    def destroy(self) -> None:
        _d("rm", "-f", self.name, check=False)


@pytest.fixture(scope="module")
def router(tmp_path_factory):
    r = ContainerRouter(tmp_path_factory.mktemp("router"))
    yield r
    r.destroy()


@pytest.fixture
def cctx(router, tmp_path) -> AppContext:
    settings = OpenwrtSettings(
        host="100.78.68.87", ssh_key_path=tmp_path / "id", known_hosts_path=tmp_path / "kh",
        state_dir=tmp_path / "state", approver_key_path=router.key, approver_pubkey_path=router.pub,
        probe_host="", verify_deadline_sec=30,
    )
    # Reset router state between tests
    router.sh(
        "rm -f /etc/openwrt-mcp/journal/* /etc/openwrt-mcp/used/*; uci revert firewall; "
        "uci -q delete firewall.mcp_allow_alt; uci -q delete firewall.mcp_two; "
        "uci commit firewall; fw4 -q reload",
        check=False,
    )
    if router.sh("test -f /var/run/openwrt-mcp/watchdog.alive && echo y", check=False).strip() != "y":
        router.start_watchdog()
    return build_context(settings, router)  # type: ignore[arg-type]


def approve(ctx: AppContext, plan_id: str, passphrase: bytes = PASS) -> dict:
    plan = ctx.store.require_plan(plan_id)
    payload, nonce = grant_mod.build_payload(plan=plan, requester="mcp-client", approver="tester")
    text, sig = grant_mod.sign_payload(payload, ctx.settings.approver_key_path, passphrase)
    ctx.store.add_grant(plan_id=plan_id, nonce=nonce, payload=text, signature=sig, approver="tester",
                        expires_at=payload["expires_at"])
    return {"payload": text, "signature": sig}


async def plan(ctx: AppContext, key="idem-key-0001", port=8080, rule="allow-alt") -> dict:
    out = json.loads(await firewall_plan_rule_impl(ctx, router_id="openwrt-pi", rule_id=rule,
                                                   idempotency_key=key, dest_port=port))
    assert out["isError"] is False, out
    return out["structuredContent"]


def _op(port=8080, rule="allow-alt"):
    return {"type": "firewall.rule.upsert", "rule_id": rule,
            "fields": {
                "template": "allow_tcp_from_lan",
                "src": "lan",
                "proto": "tcp",
                "dest_port": port,
                "family": "ipv4",
            }}


async def raw_apply(router, ctx, plan_row, grant, **overrides):
    req = {"v": 1, "op": "apply", "plan_id": plan_row["plan_id"], "plan_digest": plan_row["digest"],
           "router_id": plan_row["router_id"], "policy_revision": plan_row["policy_revision"],
           "state_precondition": plan_row["state_precondition"], "operations": plan_row["operations"],
           "recovery": plan_row["recovery"], "grant": grant}
    req.update(overrides)
    return await router.call(req)


def err_code(resp: dict) -> str:
    assert resp["ok"] is False, resp
    return resp["error"]["code"]


# ------------------------------------------------------------------ happy path

async def test_inspect_real_agent(router, cctx):
    snap = await cctx.agent.inspect()
    assert snap["config_revision"].startswith("sha256:") and snap["watchdog_alive"] is True
    assert snap["pending_changes"] is False and snap["clock_ok"] is True


async def test_apply_confirm_and_rule_is_loaded(router, cctx):
    p = await plan(cctx)
    approve(cctx, p["plan_id"])
    out = json.loads(await apply_plan_impl(cctx, p["plan_id"], p["plan_digest"]))
    assert out["isError"] is False, out
    checks = out["structuredContent"]["checks"]
    assert checks["rule_state"] == "ok" and checks["uci_committed"] == "ok", checks
    assert "mcp_allow_alt" in router.sh("uci show firewall.mcp_allow_alt")
    assert "dport 8080" in router.sh("nft list table inet fw4")
    assert json.loads(await confirm_plan_impl(cctx, p["plan_id"]))["structuredContent"]["status"] == "confirmed"
    journal = json.loads(router.sh("cat /etc/openwrt-mcp/journal/last.json"))
    assert journal["state"] == "confirmed" and not router.sh("ls /etc/openwrt-mcp/journal/active.json", check=False)


async def test_manual_rollback_restores_exact_config(router, cctx):
    before = router.sh("sha256sum /etc/config/firewall")
    p = await plan(cctx)
    approve(cctx, p["plan_id"])
    await apply_plan_impl(cctx, p["plan_id"], p["plan_digest"])
    assert router.sh("sha256sum /etc/config/firewall") != before
    assert json.loads(await rollback_plan_impl(cctx, p["plan_id"]))["structuredContent"]["status"] == "rolled_back"
    assert router.sh("sha256sum /etc/config/firewall") == before
    assert "dport 8080" not in router.sh("nft list table inet fw4")


# ------------------------------------------------------------------ fault tests

async def test_unconfirmed_change_is_rolled_back_by_watchdog_alone(router, cctx):
    before = router.sh("sha256sum /etc/config/firewall")
    p = await plan(cctx)
    approve(cctx, p["plan_id"])
    await apply_plan_impl(cctx, p["plan_id"], p["plan_digest"])
    # MCP side "disappears": never confirm. Deadline is 30 s after apply.
    for _ in range(60):
        await asyncio.sleep(1)
        if router.sh("test -f /etc/openwrt-mcp/journal/active.json && echo y", check=False).strip() != "y":
            break
    assert router.sh("sha256sum /etc/config/firewall") == before
    last = json.loads(router.sh("cat /etc/openwrt-mcp/journal/last.json"))
    assert last["state"] == "rolled_back" and "deadline" in last["reason"]
    status = json.loads(await plan_status_impl(cctx, p["plan_id"]))["structuredContent"]
    assert status["status"] == "rolled_back"
    assert cctx.store.lock_holder("openwrt-pi") is None


async def test_confirm_after_deadline_rolls_back(router, cctx):
    p = await plan(cctx)
    approve(cctx, p["plan_id"])
    await apply_plan_impl(cctx, p["plan_id"], p["plan_digest"])
    router.stop_watchdog()  # make the agent itself enforce the deadline on confirm
    await asyncio.sleep(31)
    resp = await router.call({"v": 1, "op": "confirm", "plan_id": p["plan_id"]})
    assert err_code(resp) == "VALIDATION_FAILED" and "rolled back" in resp["error"]["message"]
    assert "dport 8080" not in router.sh("nft list table inet fw4")


async def test_reboot_while_unconfirmed_is_reconciled(router, cctx):
    before = router.sh("sha256sum /etc/config/firewall")
    p = await plan(cctx)
    approve(cctx, p["plan_id"])
    await apply_plan_impl(cctx, p["plan_id"], p["plan_digest"])
    # Simulate a reboot: the journal now belongs to a different boot.
    router.sh("sed -i 's/\"boot_id\": \"[^\"]*\"/\"boot_id\": \"previous-boot\"/' /etc/openwrt-mcp/journal/active.json")
    for _ in range(15):
        await asyncio.sleep(1)
        if router.sh("test -f /etc/openwrt-mcp/journal/active.json && echo y", check=False).strip() != "y":
            break
    assert router.sh("sha256sum /etc/config/firewall") == before
    assert "across reboot" in router.sh("cat /etc/openwrt-mcp/journal/last.json")


async def test_killed_agent_mid_apply_is_recovered(router, cctx):
    """An 'armed' journal (agent died after backup, before/while mutating) is recovered by the watchdog."""
    before = router.sh("sha256sum /etc/config/firewall")
    p = await plan(cctx)
    approve(cctx, p["plan_id"])
    cur = router.sh("sha256sum /etc/config/firewall | cut -d' ' -f1").strip()
    router.sh("cp /etc/config/firewall /etc/openwrt-mcp/journal/plan_killed.bak; "
              "printf '\\n# half applied\\n' >> /etc/config/firewall; "
              "BOOT=$(cat /proc/sys/kernel/random/boot_id); UP=$(cut -d. -f1 /proc/uptime); "
              "echo '{\"plan_id\":\"plan_deadbeef\",\"state\":\"armed\","
              "\"backup\":\"/etc/openwrt-mcp/journal/plan_killed.bak\","
              f"\"pre_revision\":\"sha256:{cur}\",\"new_revision\":null,"
              "\"boot_id\":\"'$BOOT'\",\"deadline_uptime\":'$((UP+2))'}' "
              "> /etc/openwrt-mcp/journal/active.json")
    # new_revision is null: the half-applied file hash matches neither revision -> needs_manual, not a blind overwrite.
    await asyncio.sleep(8)
    state = json.loads(router.sh("cat /etc/openwrt-mcp/journal/active.json"))["state"]
    assert state == "needs_manual"
    assert router.sh("sha256sum /etc/config/firewall") != before  # untouched: operator decides
    router.sh(
        "/usr/libexec/openwrt-mcp-agent --clear; "
        "cp /etc/openwrt-mcp/journal/plan_killed.bak /etc/config/firewall"
    )


async def test_watchdog_unavailable_refuses_to_mutate(router, cctx):
    p = await plan(cctx)
    grant = approve(cctx, p["plan_id"])
    router.stop_watchdog()
    before = router.sh("sha256sum /etc/config/firewall")
    row = cctx.store.require_plan(p["plan_id"])
    resp = await raw_apply(router, cctx, row, grant)
    assert err_code(resp) == "WATCHDOG_UNAVAILABLE"
    assert router.sh("sha256sum /etc/config/firewall") == before
    assert not router.sh("ls /etc/openwrt-mcp/journal/ | grep active", check=False)


async def test_reload_failure_rolls_back(router, cctx):
    router.sh(
        "mv /sbin/fw4 /sbin/fw4.real; "
        "printf '#!/bin/sh\\n[ \"$2\" = reload ] && exit 1\\n"
        "exec /sbin/fw4.real \"$@\"\\n' > /sbin/fw4; chmod +x /sbin/fw4"
    )
    try:
        before = router.sh("sha256sum /etc/config/firewall")
        p = await plan(cctx)
        approve(cctx, p["plan_id"])
        with pytest.raises(Exception):
            await apply_plan_impl(cctx, p["plan_id"], p["plan_digest"])
        assert router.sh("sha256sum /etc/config/firewall") == before
        assert cctx.store.lock_holder("openwrt-pi") is None
    finally:
        router.sh("mv /sbin/fw4.real /sbin/fw4")


async def test_reload_hang_times_out_and_rolls_back(router, cctx):
    """fw4 reload hangs on the first call only (the agent's 60 s timeout must fire, then recovery runs)."""
    router.sh("mv /sbin/fw4 /sbin/fw4.real; rm -f /tmp/hung; printf '#!/bin/sh\\n"
              "if [ \"$2\" = reload ] && [ ! -e /tmp/hung ]; then touch /tmp/hung; sleep 300; fi\\n"
              "exec /sbin/fw4.real \"$@\"\\n' > /sbin/fw4; chmod +x /sbin/fw4")
    try:
        before = router.sh("sha256sum /etc/config/firewall")
        p = await plan(cctx)
        approve(cctx, p["plan_id"])
        with pytest.raises(Exception):
            await apply_plan_impl(cctx, p["plan_id"], p["plan_digest"])
        assert router.sh("sha256sum /etc/config/firewall") == before
        assert not router.sh("ls /etc/openwrt-mcp/journal/ | grep active", check=False)
        assert json.loads(router.sh("cat /etc/openwrt-mcp/journal/last.json"))["state"] == "rolled_back"
    finally:
        router.sh("pkill sleep; mv /sbin/fw4.real /sbin/fw4; rm -f /tmp/hung", check=False)


# ------------------------------------------------------------------ router-side authorization (negative)

async def test_replayed_grant_is_refused_by_router(router, cctx):
    p = await plan(cctx)
    grant = approve(cctx, p["plan_id"])
    row = cctx.store.require_plan(p["plan_id"])
    assert (await raw_apply(router, cctx, row, grant))["ok"] is True
    await router.call({"v": 1, "op": "rollback", "plan_id": p["plan_id"]})
    assert err_code(await raw_apply(router, cctx, row, grant)) == "APPROVAL_INVALID"


async def test_tampered_operations_fail_digest(router, cctx):
    p = await plan(cctx)
    grant = approve(cctx, p["plan_id"])
    row = cctx.store.require_plan(p["plan_id"])
    resp = await raw_apply(router, cctx, row, grant, operations=[_op(port=9999)])
    assert err_code(resp) == "APPROVAL_INVALID"


async def test_forged_signature_refused(router, cctx, tmp_path):
    p = await plan(cctx)
    row = cctx.store.require_plan(p["plan_id"])
    k, pub = tmp_path / "evil.key", tmp_path / "evil.pub"
    grant_mod.generate_keypair(k, pub, b"another long passphrase")
    payload, _ = grant_mod.build_payload(plan=row, requester="mcp-client", approver="evil")
    text, sig = grant_mod.sign_payload(payload, k, b"another long passphrase")
    assert err_code(await raw_apply(router, cctx, row, {"payload": text, "signature": sig})) == "APPROVAL_INVALID"


async def test_grant_for_other_plan_refused(router, cctx):
    a = await plan(cctx, key="idem-key-000a", port=8080)
    b = await plan(cctx, key="idem-key-000b", port=8081, rule="two")
    grant_a = approve(cctx, a["plan_id"])
    row_b = cctx.store.require_plan(b["plan_id"])
    assert err_code(await raw_apply(router, cctx, row_b, grant_a)) == "APPROVAL_INVALID"


async def test_state_drift_refused(router, cctx):
    p = await plan(cctx)
    grant = approve(cctx, p["plan_id"])
    router.sh("printf '\\n# drift\\n' >> /etc/config/firewall")
    row = cctx.store.require_plan(p["plan_id"])
    assert err_code(await raw_apply(router, cctx, row, grant)) == "STATE_PRECONDITION_FAILED"
    router.sh("sed -i '/# drift/d' /etc/config/firewall")


async def test_pending_uci_changes_refused(router, cctx):
    p = await plan(cctx)
    grant = approve(cctx, p["plan_id"])
    router.sh("uci set firewall.@defaults[0].drop_invalid=0")
    row = cctx.store.require_plan(p["plan_id"])
    assert err_code(await raw_apply(router, cctx, row, grant)) == "TARGET_LOCKED"
    router.sh("uci revert firewall")


@pytest.mark.parametrize("mutate,code", [
    (lambda f: f.update(dest_port=22), "OPERATION_PROHIBITED"),
    (lambda f: f.update(src="wan"), "OPERATION_PROHIBITED"),
    (lambda f: f.update(proto="udp"), "OPERATION_PROHIBITED"),
    (lambda f: f.update(src_ip="8.8.8.0/24"), "OPERATION_PROHIBITED"),
    (lambda f: f.update(shell_cmd="id"), "BAD_REQUEST"),
    (lambda f: f.update(template="allow_any"), "OPERATION_PROHIBITED"),
])
async def test_agent_reauthorizes_independently_of_service(router, cctx, mutate, code):
    op = _op()
    mutate(op["fields"])
    resp = await router.call({"v": 1, "op": "validate", "operations": [op], "state_precondition": "sha256:x"})
    assert err_code(resp) == code


async def test_agent_rejects_unknown_ops_and_oversize(router, cctx):
    assert err_code(await router.call({"v": 1, "op": "shell", "cmd": "id"})) == "BAD_REQUEST"
    assert err_code(await router.call({"v": 2, "op": "inspect"})) == "BAD_REQUEST"
    assert err_code(await router.call({"v": 1, "op": "inspect", "extra": 1})) == "BAD_REQUEST"
    big = {"v": 1, "op": "validate", "operations": [], "pad": "x" * 70000}
    proc = subprocess.run(
        ["docker", "exec", "-i", router.name, "/usr/libexec/openwrt-mcp-agent"],
        input=json.dumps(big).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert json.loads(proc.stdout)["error"]["code"] == "BAD_REQUEST"


async def test_agent_refuses_to_touch_foreign_sections(router, cctx):
    router.sh("uci set firewall.mcp_allow_alt=rule; uci set firewall.mcp_allow_alt.name=mine; uci commit firewall")
    p = await plan(cctx)
    grant = approve(cctx, p["plan_id"])
    row = cctx.store.require_plan(p["plan_id"])
    resp = await raw_apply(router, cctx, row, grant)
    assert err_code(resp) == "OPERATION_PROHIBITED"
    router.sh("uci delete firewall.mcp_allow_alt; uci commit firewall")


async def test_validate_op_stages_checks_and_reverts(router, cctx):
    snap = await cctx.agent.inspect()
    resp = await router.call({"v": 1, "op": "validate", "operations": [_op()],
                              "state_precondition": snap["config_revision"]})
    assert resp["ok"] is True, resp
    assert (await cctx.agent.inspect())["pending_changes"] is False


async def test_digest_vector_matches_python(router, cctx):
    """Canonical JSON + sha256 in ucode must equal Python's (cross-language contract)."""
    ops = [_op()]
    rec = {"mode": "auto_revert", "deadline_s": 30}
    expected = plan_digest(router_id="openwrt-pi", operations=ops, state_precondition="sha256:aa",
                           policy_revision=1, recovery=rec)
    resp = await router.call({"v": 1, "op": "apply", "plan_id": "plan_00000000", "plan_digest": expected,
                              "router_id": "openwrt-pi", "policy_revision": 1, "state_precondition": "sha256:aa",
                              "operations": ops, "recovery": rec,
                              "grant": {"payload": "{}", "signature": "x"}})
    # Passing the digest check means the failure comes LATER (grant), not from a digest mismatch.
    assert resp["error"]["message"] != "plan digest does not match request contents"
    assert err_code(resp) == "APPROVAL_INVALID" and "signature" in resp["error"]["message"]
