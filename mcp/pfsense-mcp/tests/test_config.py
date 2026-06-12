"""Tests for pfSense MCP settings."""

import pytest
from pydantic import ValidationError

from pfsense_mcp.config import PfsSettings


def test_settings_valid_ipv4() -> None:
    settings = PfsSettings(host="172.16.0.1", api_key="test-key", length_bytes=16)
    assert settings.base_url == "https://172.16.0.1:443/api/v2/"
    assert settings.api_user == "mcp-cursor-agent"
    assert settings.hash_algo == "sha256"
    assert settings.length_bytes == 16
    assert settings.log_level == "INFO"


def test_settings_log_level_normalized() -> None:
    settings = PfsSettings(host="172.16.0.1", api_key="test-key", log_level="debug")
    assert settings.log_level == "DEBUG"


def test_settings_rejects_invalid_log_level() -> None:
    with pytest.raises(ValueError, match="Invalid log level"):
        PfsSettings(host="172.16.0.1", api_key="k", log_level="VERBOSE")


def test_settings_custom_api_user() -> None:
    settings = PfsSettings(host="172.16.0.1", api_key="test-key", api_user="custom-bot")
    assert settings.api_user == "custom-bot"


def test_settings_hash_algo_and_length_bytes() -> None:
    settings = PfsSettings(
        host="172.16.0.1",
        api_key="test-key",
        hash_algo="sha512",
        length_bytes=32,
    )
    assert settings.hash_algo == "sha512"
    assert settings.length_bytes == 32


def test_settings_rejects_invalid_hash_algo() -> None:
    with pytest.raises(ValidationError, match="hash_algo"):
        PfsSettings(host="172.16.0.1", api_key="k", hash_algo="md5")


def test_settings_rejects_invalid_length_bytes() -> None:
    with pytest.raises(ValueError, match="PFSENSE_LENGTH_BYTES"):
        PfsSettings(host="172.16.0.1", api_key="k", length_bytes=8)


def test_settings_valid_ipv6() -> None:
    settings = PfsSettings(host="2001:db8::1", api_key="test-key")
    assert settings.host == "2001:db8::1"


def test_settings_rejects_hostname() -> None:
    with pytest.raises(ValueError, match="address literal"):
        PfsSettings(host="pfsense.local", api_key="k")


def test_settings_rejects_fqdn() -> None:
    with pytest.raises(ValueError, match="address literal"):
        PfsSettings(host="fw.example.ts.net", api_key="k")


def test_settings_rejects_scheme() -> None:
    with pytest.raises(ValueError, match="scheme"):
        PfsSettings(host="https://172.16.0.1", api_key="k")


def test_settings_requires_api_key() -> None:
    with pytest.raises(ValueError, match="PFSENSE_API_KEY"):
        PfsSettings(host="172.16.0.1", api_key="")


def test_settings_requires_api_user() -> None:
    with pytest.raises(ValueError, match="PFSENSE_API_USER"):
        PfsSettings(host="172.16.0.1", api_key="k", api_user="  ")
