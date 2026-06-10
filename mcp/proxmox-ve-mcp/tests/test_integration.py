"""Optional integration tests against a live cluster.

Set PVE_INTEGRATION=1 and all PVE_* env vars to run.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PVE_INTEGRATION") != "1",
    reason="Set PVE_INTEGRATION=1 with live PVE_* env to run",
)


@pytest.mark.asyncio
async def test_live_get_version() -> None:
    from proxmox_ve_mcp.config import PveSettings
    from proxmox_ve_mcp.context import init_context
    from proxmox_ve_mcp.tools.cluster import pve_get_version_impl

    client = init_context(PveSettings())
    try:
        result = await pve_get_version_impl()
        assert '"ok": true' in result
    finally:
        await client.aclose()
