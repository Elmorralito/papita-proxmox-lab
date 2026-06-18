"""Unit tests for Pydantic tool input schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from truenas_mcp.tools.schemas import (
    ConfirmInput,
    CreateDatasetInput,
    DismissAlertInput,
    ReportingDataInput,
    UpdateNfsShareInput,
)


def test_confirm_input_requires_true() -> None:
    with pytest.raises(ValidationError):
        ConfirmInput(confirm=False)


def test_create_dataset_input() -> None:
    parsed = CreateDatasetInput(pool="tank", name="data", confirm=True)
    assert parsed.pool == "tank"
    assert parsed.name == "data"


def test_update_nfs_share_input() -> None:
    parsed = UpdateNfsShareInput(share_id=1, confirm=True, enabled=False)
    assert parsed.share_id == 1
    assert parsed.enabled is False


def test_dismiss_alert_input() -> None:
    parsed = DismissAlertInput(alert_id="abc-123", confirm=True)
    assert parsed.alert_id == "abc-123"


def test_reporting_data_defaults() -> None:
    parsed = ReportingDataInput()
    assert parsed.graph == "cpu"
    assert parsed.unit == "HOUR"
