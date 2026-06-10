"""Tests for PVE settings."""

import pytest

from proxmox_ve_mcp.config import PveSettings


def test_settings_from_split_token_fields() -> None:
    settings = PveSettings(
        host="10.0.0.11",
        user="mcp-agent@pam",
        token_id="cursor",
        token_secret="s3cr3t",
    )
    assert settings.authorization_header() == "PVEAPIToken=mcp-agent@pam!cursor=s3cr3t"
    assert settings.base_url == "https://10.0.0.11:8006/api2/json"


def test_settings_from_combined_api_token() -> None:
    settings = PveSettings(
        host="pvenode-001",
        api_token="mcp-agent@pam!cursor=s3cr3t",
    )
    assert settings.authorization_header() == "PVEAPIToken=mcp-agent@pam!cursor=s3cr3t"


def test_settings_rejects_host_with_scheme() -> None:
    with pytest.raises(ValueError, match="scheme"):
        PveSettings(host="https://bad.example", api_token="u@pam!t=s")


def test_settings_requires_auth() -> None:
    with pytest.raises(ValueError, match="PVE_API_TOKEN"):
        PveSettings(host="pvenode-001")
