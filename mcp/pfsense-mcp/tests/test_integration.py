"""Optional live-firewall integration tests."""

import os

import pytest

from pfsense_mcp.config import PfsSettings
from pfsense_mcp.context import init_context
from pfsense_mcp.tools.system import pfs_get_version_impl

pytestmark = pytest.mark.skipif(
    os.environ.get("PFSENSE_INTEGRATION") != "1",
    reason="Set PFSENSE_INTEGRATION=1 and PFSENSE_* env to run live pfSense tests",
)


@pytest.fixture
async def live_client():
    settings = PfsSettings()
    client = init_context(settings)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_live_version(live_client) -> None:  # noqa: ARG001
    result = await pfs_get_version_impl()
    assert '"ok": true' in result
