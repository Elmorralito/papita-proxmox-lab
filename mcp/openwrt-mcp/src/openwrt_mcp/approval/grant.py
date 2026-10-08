"""Grant keys, signing and verification (usign/signify-compatible ed25519 signatures)."""

import base64
import secrets
import time
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from openwrt_mcp.canonical import canonical_json
from openwrt_mcp.constants import MAX_GRANT_TTL_SEC
from openwrt_mcp.errors import ApprovalExpired, ApprovalRequired

_ALG = b"Ed"
_KEYNUM_LEN = 8


def _b64(data: bytes) -> str:
    """Return standard base64 text for ``data``."""
    return base64.b64encode(data).decode("ascii")


def generate_keypair(key_path: Path, pub_path: Path, passphrase: bytes) -> None:
    """Create an encrypted PKCS#8 private key and a usign-format public key file."""
    if not passphrase:
        raise ValueError("a passphrase is required")
    key = Ed25519PrivateKey.generate()
    keynum = secrets.token_bytes(_KEYNUM_LEN)
    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase),
    )
    key_path.write_bytes(pem)
    key_path.chmod(0o600)
    raw_pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_path.write_text(
        "untrusted comment: openwrt-mcp approver public key\n" + _b64(_ALG + keynum + raw_pub) + "\n",
        encoding="ascii",
    )
    # The keynum must travel with the key so signatures carry the matching fingerprint.
    key_path.with_suffix(".keynum").write_bytes(keynum)


def _load_private(key_path: Path, passphrase: bytes) -> tuple[Ed25519PrivateKey, bytes]:
    """Load the passphrase-protected ed25519 approver key."""
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=passphrase)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("approver key is not ed25519")
    return key, key_path.with_suffix(".keynum").read_bytes()


def load_public(pub_path: Path) -> tuple[Ed25519PublicKey, bytes]:
    """Parse a usign-format public key file."""
    lines = pub_path.read_text(encoding="ascii").strip().splitlines()
    blob = base64.b64decode(lines[-1])
    if blob[:2] != _ALG or len(blob) != 2 + _KEYNUM_LEN + 32:
        raise ValueError("invalid public key file")
    return Ed25519PublicKey.from_public_bytes(blob[2 + _KEYNUM_LEN :]), blob[2 : 2 + _KEYNUM_LEN]


def build_payload(
    *,
    plan: dict[str, Any],
    requester: str,
    approver: str,
    now: int | None = None,
) -> tuple[dict[str, Any], str]:
    """Return ``(payload_dict, nonce)`` binding the grant to the plan."""
    now = now or int(time.time())
    nonce = secrets.token_hex(8)
    payload = {
        "v": 1,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["digest"],
        "state_precondition": plan["state_precondition"],
        "router_id": plan["router_id"],
        "policy_revision": plan["policy_revision"],
        "requester": requester,
        "approver": approver,
        "expires_at": min(plan["expires_at"], now + MAX_GRANT_TTL_SEC),
        "nonce": nonce,
    }
    return payload, nonce


def sign_payload(payload: dict[str, Any], key_path: Path, passphrase: bytes) -> tuple[str, str]:
    """Sign canonical payload JSON. Returns ``(payload_text, signature_file_text)``."""
    key, keynum = _load_private(key_path, passphrase)
    text = canonical_json(payload)
    sig = key.sign(text.encode("utf-8"))
    sig_file = "untrusted comment: signature from openwrt-mcp approver\n" + _b64(_ALG + keynum + sig) + "\n"
    return text, sig_file


def verify_signature(payload_text: str, signature_file: str, pub_path: Path) -> bool:
    """Verify a usign-format signature over ``payload_text``."""
    try:
        pub, keynum = load_public(pub_path)
        blob = base64.b64decode(signature_file.strip().splitlines()[-1])
        if blob[:2] != _ALG or blob[2 : 2 + _KEYNUM_LEN] != keynum or len(blob) != 2 + _KEYNUM_LEN + 64:
            return False
        pub.verify(blob[2 + _KEYNUM_LEN :], payload_text.encode("utf-8"))
        return True
    except (InvalidSignature, ValueError, OSError, IndexError):
        return False


def verify_grant_for_plan(
    grant: dict[str, Any], plan: dict[str, Any], pub_path: Path, now: int | None = None
) -> dict[str, Any]:
    """Check signature, binding and expiry of a stored grant against a plan; return the parsed payload."""
    import json

    now = now or int(time.time())
    if not verify_signature(grant["payload"], grant["signature"], pub_path):
        raise ApprovalRequired("grant signature is invalid")
    payload = json.loads(grant["payload"])
    bound = {
        "plan_id": plan["plan_id"],
        "plan_digest": plan["digest"],
        "state_precondition": plan["state_precondition"],
        "router_id": plan["router_id"],
        "policy_revision": plan["policy_revision"],
    }
    for key, expected in bound.items():
        if payload.get(key) != expected:
            raise ApprovalRequired(f"grant is not bound to this plan ({key})")
    if int(payload.get("expires_at", 0)) <= now:
        raise ApprovalExpired("grant expired")
    return payload
