"""Optional live TrueNAS integration tests (TRUENAS_INTEGRATION=1)."""

from __future__ import annotations

import os

import pytest

from truenas_mcp.tools.smoke_test import run_smoke_tests

pytestmark = pytest.mark.skipif(
    os.environ.get("TRUENAS_INTEGRATION") != "1",
    reason="Set TRUENAS_INTEGRATION=1 and configure TRUENAS_* env to run live tests",
)


@pytest.mark.asyncio
async def test_live_smoke_basic() -> None:
    report = await run_smoke_tests(extended=False)
    assert report["core_passed"], report


@pytest.mark.asyncio
async def test_live_smoke_extended() -> None:
    report = await run_smoke_tests(extended=True)
    assert report["core_passed"], report
