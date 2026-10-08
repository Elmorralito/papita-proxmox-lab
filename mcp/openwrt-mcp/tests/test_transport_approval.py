"""SSH argv hardening, approval signatures, audit chain and config validation."""

import pytest

from openwrt_mcp.approval import grant as grant_mod
from openwrt_mcp.config import OpenwrtSettings
from openwrt_mcp.router.transport import SshTransport
from openwrt_mcp.store.audit import AuditLog


def test_ssh_argv_is_strict_and_has_no_shell(settings):
    argv = SshTransport(settings).argv()
    joined = " ".join(argv)
    assert argv[0] == "ssh" and "StrictHostKeyChecking=yes" in joined and "BatchMode=yes" in joined
    assert "ControlMaster=no" in joined and "ForwardAgent=no" in joined and "GlobalKnownHostsFile=/dev/null" in joined
    assert argv[-1] == "root@100.78.68.87"


def test_signature_roundtrip_and_tamper(tmp_path):
    key, pub = tmp_path / "a.key", tmp_path / "a.pub"
    grant_mod.generate_keypair(key, pub, b"a long enough passphrase")
    plan = {"plan_id": "plan_1", "digest": "sha256:ab", "state_precondition": "sha256:cd", "router_id": "r1",
            "policy_revision": 1, "expires_at": 4_000_000_000}
    payload, _ = grant_mod.build_payload(plan=plan, requester="c", approver="me")
    text, sig = grant_mod.sign_payload(payload, key, b"a long enough passphrase")
    assert grant_mod.verify_signature(text, sig, pub)
    assert not grant_mod.verify_signature(text.replace("me", "yo"), sig, pub)
    with pytest.raises(Exception):
        grant_mod.sign_payload(payload, key, b"wrong passphrase!!")


def test_usign_format(tmp_path):
    key, pub = tmp_path / "a.key", tmp_path / "a.pub"
    grant_mod.generate_keypair(key, pub, b"a long enough passphrase")
    lines = pub.read_text().splitlines()
    assert lines[0].startswith("untrusted comment:") and len(lines) == 2


def test_audit_chain_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(3):
        log.record("e", n=i)
    assert log.verify()
    p = tmp_path / "audit.jsonl"
    p.write_text(p.read_text().replace('"n":1', '"n":9'))
    assert not log.verify()


def test_settings_validation(tmp_path):
    base = {"ssh_key_path": tmp_path / "k", "known_hosts_path": tmp_path / "kh"}
    with pytest.raises(ValueError):
        OpenwrtSettings(host="router.example.com", **base)
    with pytest.raises(ValueError):
        OpenwrtSettings(host="100.78.68.87", router_id="Bad ID", **base)
    with pytest.raises(ValueError):
        OpenwrtSettings(host="100.78.68.87", verify_deadline_sec=900, **base)
