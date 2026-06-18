"""Pydantic input schemas for TrueNAS MCP tools."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ReportGraphName = Literal[
    "cpu",
    "cputemp",
    "disk",
    "interface",
    "load",
    "processes",
    "memory",
    "uptime",
    "arcsize",
    "disktemp",
]

ReportingUnit = Literal["HOUR", "DAY", "WEEK", "MONTH", "YEAR"]


class LimitInput(BaseModel):
    """Pagination limit for query tools."""

    limit: int = Field(default=50, ge=1, le=500)


class ReportingDataInput(BaseModel):
    """Parameters for ``reporting.get_data``."""

    graph: ReportGraphName = Field(default="cpu", description="Reporting graph name")
    identifier: str | None = Field(default=None, description="Device/interface identifier or null for system-wide")
    start: int | None = Field(default=None, description="Unix timestamp start (use with end)")
    end: int | None = Field(default=None, description="Unix timestamp end (use with start)")
    unit: ReportingUnit | None = Field(default="HOUR", description="Aggregation unit when not using start/end")
    page: int = Field(default=1, ge=1, description="Page when using unit aggregation")
    aggregate: bool = Field(default=True, description="Return min/max/mean aggregates when available")


class ConfirmInput(BaseModel):
    """Explicit confirmation gate for mutating tools."""

    confirm: bool = Field(description="Must be true to execute mutating operation")

    @field_validator("confirm")
    @classmethod
    def check_confirm(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("confirm must be true")
        return value


class CreateDatasetInput(ConfirmInput):
    """Create a ZFS dataset under a pool."""

    pool: str = Field(description="Pool name (e.g. pve-cluster-oldtimers-ha-storage)")
    name: str = Field(description="Dataset name segment (e.g. pve-nfs)")
    dataset_type: str = Field(default="FILESYSTEM", description="ZFS dataset type")


class UpdateNfsShareInput(ConfirmInput):
    """Update an existing NFS share by id."""

    share_id: int = Field(ge=1, description="NFS share id from sharing.nfs.query")
    enabled: bool | None = Field(default=None, description="Enable or disable the share")
    comment: str | None = Field(default=None, description="Optional comment update")


class DismissAlertInput(ConfirmInput):
    """Dismiss an active alert."""

    alert_id: str = Field(min_length=1, description="Alert uuid from alert.list")


class WriteJobOptions(BaseModel):
    """Optional job wait behavior for write tools."""

    wait_for_job: bool = Field(default=True, description="Poll core.get_jobs until completion")
    job_timeout_sec: float = Field(default=120.0, ge=5.0, le=600.0)


def query_options(*, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Build standard TrueNAS query options dict."""
    return {"limit": limit, "offset": offset}
