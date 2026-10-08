"""``openwrt-mcp-approve``: interactive approver CLI. Refuses to run without a real terminal."""

import argparse
import getpass
import sys
import time
from typing import Any

from dotenv import load_dotenv

from openwrt_mcp.approval import grant as grant_mod
from openwrt_mcp.config import OpenwrtSettings
from openwrt_mcp.store.audit import AuditLog
from openwrt_mcp.store.db import Store


def _require_tty() -> None:
    """Refuse to run without an interactive terminal."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Refusing to run: approval requires an interactive terminal.", file=sys.stderr)
        raise SystemExit(2)


def _print_plan(plan: dict[str, Any]) -> None:
    """Print a human-readable plan summary."""
    print(f"plan_id:            {plan['plan_id']}")
    print(f"router:             {plan['router_id']}")
    print(f"status:             {plan['status']}")
    print(f"risk:               {plan['risk']}")
    print(f"digest:             {plan['digest']}")
    print(f"state_precondition: {plan['state_precondition']}")
    print(f"policy_revision:    {plan['policy_revision']}")
    print(f"expires_at:         {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(plan['expires_at']))}")
    print(f"recovery:           {plan['recovery']}")
    print("diff:")
    for line in plan["diff"]:
        print(f"  {line}")


def cmd_keygen(settings: OpenwrtSettings) -> int:
    """Create the approver key pair (passphrase typed on the terminal)."""
    _require_tty()
    if settings.approver_key_path.exists():
        print(f"{settings.approver_key_path} already exists; refusing to overwrite.", file=sys.stderr)
        return 1
    first = getpass.getpass("New approver passphrase: ")
    if first != getpass.getpass("Repeat passphrase: ") or len(first) < 12:
        print("Passphrases differ or are shorter than 12 characters.", file=sys.stderr)
        return 1
    grant_mod.generate_keypair(settings.approver_key_path, settings.approver_pubkey_path, first.encode())
    print(f"Wrote {settings.approver_key_path} and {settings.approver_pubkey_path}")
    print("Install the public key on the router with deploy/setup/misc/openwrt/papita-openwrt-mcp-agent-install.sh")
    return 0


def cmd_list(store: Store) -> int:
    """List plans that are waiting for approval."""
    plans = store.list_plans("planned")
    now = int(time.time())
    for plan in plans:
        state = "expired" if plan["expires_at"] <= now else "pending"
        print(f"{plan['plan_id']}  {state:8}  {plan['digest'][:19]}  {plan['diff'][-1] if plan['diff'] else ''}")
    if not plans:
        print("No plans awaiting approval.")
    return 0


def cmd_show(store: Store, plan_id: str) -> int:
    """Show a plan in full."""
    plan = store.get_plan(plan_id)
    if plan is None:
        print("Unknown plan.", file=sys.stderr)
        return 1
    _print_plan(plan)
    return 0


def cmd_approve(settings: OpenwrtSettings, store: Store, audit: AuditLog, plan_id: str) -> int:
    """Review an exact plan and sign a one-time grant."""
    _require_tty()
    plan = store.get_plan(plan_id)
    if plan is None:
        print("Unknown plan.", file=sys.stderr)
        return 1
    if plan["status"] != "planned" or plan["expires_at"] <= int(time.time()):
        print(f"Plan is {plan['status']} / expired; cannot approve.", file=sys.stderr)
        return 1
    _print_plan(plan)
    short = plan["digest"].split(":", 1)[1][:12]
    typed = input(f"\nType the first 12 hex characters of the digest ({short}) to approve: ").strip()
    if typed != short:
        print("Digest prefix does not match; not approved.", file=sys.stderr)
        return 1
    passphrase = getpass.getpass("Approver key passphrase: ")
    approver = getpass.getuser()
    payload, nonce = grant_mod.build_payload(plan=plan, requester=plan["requester"], approver=approver)
    try:
        text, signature = grant_mod.sign_payload(payload, settings.approver_key_path, passphrase.encode())
    except (ValueError, OSError):
        print("Could not unlock the approver key.", file=sys.stderr)
        return 1
    store.add_grant(
        plan_id=plan_id,
        nonce=nonce,
        payload=text,
        signature=signature,
        approver=approver,
        expires_at=payload["expires_at"],
    )
    audit.record("grant_created", plan_id=plan_id, digest=plan["digest"], approver=approver, nonce=nonce)
    print(f"Grant created (one-time, expires {time.strftime('%H:%M:%S', time.localtime(payload['expires_at']))}).")
    return 0


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(prog="openwrt-mcp-approve", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen")
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("plan_id")
    approve = sub.add_parser("approve")
    approve.add_argument("plan_id")
    args = parser.parse_args(argv)

    load_dotenv()
    settings = OpenwrtSettings()
    if args.cmd == "keygen":
        raise SystemExit(cmd_keygen(settings))
    store = Store(settings.db_path)
    audit = AuditLog(settings.audit_path)
    if args.cmd == "list":
        raise SystemExit(cmd_list(store))
    if args.cmd == "show":
        raise SystemExit(cmd_show(store, args.plan_id))
    raise SystemExit(cmd_approve(settings, store, audit, args.plan_id))


if __name__ == "__main__":
    main()
