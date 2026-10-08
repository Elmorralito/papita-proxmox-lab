"""Shared fixtures: settings in a temp dir and a scripted fake router transport."""

from pathlib import Path

import pytest
from owrt_testlib import FakeTransport

from openwrt_mcp.config import OpenwrtSettings
from openwrt_mcp.context import AppContext, build_context


@pytest.fixture
def settings(tmp_path: Path) -> OpenwrtSettings:
    """Settings pointing at temp paths."""
    (tmp_path / "id").write_text("k")
    (tmp_path / "kh").write_text("100.78.68.87 ssh-ed25519 AAAA\n")
    return OpenwrtSettings(
        host="100.78.68.87",
        ssh_key_path=tmp_path / "id",
        known_hosts_path=tmp_path / "kh",
        state_dir=tmp_path / "state",
        approver_key_path=tmp_path / "approver.key",
        approver_pubkey_path=tmp_path / "approver.pub",
        probe_host="",
    )


@pytest.fixture
def transport() -> FakeTransport:
    """Fake router."""
    return FakeTransport()


@pytest.fixture
def ctx(settings: OpenwrtSettings, transport: FakeTransport) -> AppContext:
    """Application context with a fake router."""
    return build_context(settings, transport)  # type: ignore[arg-type]
