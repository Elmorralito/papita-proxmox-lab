"""Tests for TrueNAS MCP settings."""

import os

import pytest

from truenas_mcp.config import TnasSettings


@pytest.fixture(autouse=True)
def _isolate_truenas_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("TRUENAS_"):
            monkeypatch.delenv(key, raising=False)


def test_settings_valid() -> None:
    settings = TnasSettings(host="172.16.0.100", api_key="test-key", port=443)
    assert settings.ws_uri == "wss://172.16.0.100:443/websocket"
    assert settings.verify_ssl is False
    assert settings.log_level == "INFO"


def test_settings_custom_ws_path() -> None:
    settings = TnasSettings(
        host="172.16.0.100",
        api_key="test-key",
        port=443,
        ws_path="/api/v2.0/websocket",
    )
    assert settings.ws_uri == "wss://172.16.0.100:443/api/v2.0/websocket"


def test_settings_log_level_normalized() -> None:
    settings = TnasSettings(host="172.16.0.100", api_key="test-key", log_level="debug")
    assert settings.log_level == "DEBUG"


def test_settings_rejects_invalid_log_level() -> None:
    with pytest.raises(ValueError, match="Invalid log level"):
        TnasSettings(host="172.16.0.100", api_key="k", log_level="VERBOSE")


def test_settings_rejects_scheme() -> None:
    with pytest.raises(ValueError, match="scheme"):
        TnasSettings(host="https://172.16.0.100", api_key="k")


def test_settings_requires_api_key() -> None:
    with pytest.raises(ValueError, match="TRUENAS_API_KEY"):
        TnasSettings(host="172.16.0.100", api_key="")


def test_settings_rejects_placeholder_key() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        TnasSettings(host="172.16.0.100", api_key="REPLACE_FROM_SECRET_STORE")


def test_settings_allows_hostname() -> None:
    settings = TnasSettings(host="truenas.lab.ts.net", api_key="test-key")
    assert settings.host == "truenas.lab.ts.net"
