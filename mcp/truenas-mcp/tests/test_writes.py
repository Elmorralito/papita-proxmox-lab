"""Unit tests for gated write tools."""

from __future__ import annotations

import pytest

from truenas_mcp.tools.helpers import require_confirm


def test_require_confirm_rejects_false() -> None:
    with pytest.raises(ValueError, match="confirm must be true"):
        require_confirm(False)


def test_require_confirm_accepts_true() -> None:
    require_confirm(True)
