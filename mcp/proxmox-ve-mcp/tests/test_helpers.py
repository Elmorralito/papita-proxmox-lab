"""Tests for shared helpers."""

import pytest

from proxmox_ve_mcp.tools.helpers import redact_config, require_confirm


def test_redact_config_masks_secrets() -> None:
    raw = {
        "name": "test-vm",
        "cipassword": "secret123",
        "cicustom": "user=local:snippets/x.yaml",
        "sshkeys": "ssh-rsa AAAA...",
        "cores": 2,
    }
    redacted = redact_config(raw)
    assert redacted["name"] == "test-vm"
    assert redacted["cores"] == 2
    assert redacted["cipassword"] == "[REDACTED]"
    assert redacted["cicustom"] == "[REDACTED]"
    assert redacted["sshkeys"] == "[REDACTED]"


def test_require_confirm_rejects_false() -> None:
    with pytest.raises(ValueError, match="confirm must be true"):
        require_confirm(False)
