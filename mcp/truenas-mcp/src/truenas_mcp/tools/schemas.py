"""Pydantic input schemas for TrueNAS MCP tools."""

import ipaddress
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

    pool: str = Field(description="Pool name (e.g. main_data_storage)")
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


class PowerInput(BaseModel):
    """Guarded NAS shutdown/reboot request."""

    reason: str = Field(min_length=3, max_length=200, description="Why the NAS is powered off (logged on the NAS)")
    delay_s: int = Field(default=0, ge=0, le=3600, description="Seconds TrueNAS waits before powering off")
    force: bool = Field(default=False, description="Skip the NFS-client and running-job guards")
    expected_clients: list[str] = Field(
        default_factory=list, description="Client IPs allowed to stay connected (e.g. the entry PVE node)"
    )

    @field_validator("expected_clients")
    @classmethod
    def check_ips(cls, value: list[str]) -> list[str]:
        """Require literal IP addresses."""
        return [str(ipaddress.ip_address(ip.strip())) for ip in value]


class WriteJobOptions(BaseModel):
    """Optional job wait behavior for write tools."""

    wait_for_job: bool = Field(default=True, description="Poll core.get_jobs until completion")
    job_timeout_sec: float = Field(default=120.0, ge=5.0, le=600.0)


def query_options(*, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Build standard TrueNAS query options dict."""
    return {"limit": limit, "offset": offset}
