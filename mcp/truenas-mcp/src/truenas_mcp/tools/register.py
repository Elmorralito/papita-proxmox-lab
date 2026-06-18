"""Register MCP tools on a FastMCP server."""

from collections.abc import Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from truenas_mcp.tools.monitoring import (
    truenas_check_api_key_impl,
    truenas_get_reporting_data_impl,
    truenas_list_alert_policies_impl,
    truenas_list_apps_impl,
    truenas_list_smart_results_impl,
)
from truenas_mcp.tools.registry import TOOL_REGISTRY, ToolClass
from truenas_mcp.tools.sharing import truenas_list_nfs_shares_impl
from truenas_mcp.tools.smoke_test import truenas_run_smoke_tests_impl
from truenas_mcp.tools.storage import (
    truenas_list_datasets_impl,
    truenas_list_disks_impl,
    truenas_list_pools_impl,
    truenas_list_scrub_tasks_impl,
)
from truenas_mcp.tools.system import (
    truenas_get_system_info_impl,
    truenas_list_alerts_impl,
    truenas_list_jobs_impl,
    truenas_system_summary_impl,
)
from truenas_mcp.tools.writes import (
    truenas_create_dataset_impl,
    truenas_dismiss_alert_impl,
    truenas_update_nfs_share_impl,
)

ToolFn = Callable[..., Awaitable[str]]


def _track(name: str, tool_class: ToolClass) -> Callable[[ToolFn], ToolFn]:
    def decorator(fn: ToolFn) -> ToolFn:
        TOOL_REGISTRY[name] = tool_class
        return fn

    return decorator


def register_tools(mcp: FastMCP) -> None:  # noqa: C901
    """Register all MCP tools on the FastMCP server instance."""

    @mcp.tool(name="truenas_get_system_info")
    @_track("truenas_get_system_info", ToolClass.READ)
    async def truenas_get_system_info() -> str:
        """Get TrueNAS hostname, version, uptime, and middleware state."""
        return await truenas_get_system_info_impl()

    @mcp.tool(name="truenas_check_api_key")
    @_track("truenas_check_api_key", ToolClass.READ)
    async def truenas_check_api_key() -> str:
        """Validate API key authentication and return system state/version."""
        return await truenas_check_api_key_impl()

    @mcp.tool(name="truenas_list_alerts")
    @_track("truenas_list_alerts", ToolClass.READ)
    async def truenas_list_alerts() -> str:
        """List active TrueNAS alerts (pool, disk, hardware, config)."""
        return await truenas_list_alerts_impl()

    @mcp.tool(name="truenas_list_alert_policies")
    @_track("truenas_list_alert_policies", ToolClass.READ)
    async def truenas_list_alert_policies() -> str:
        """List configured alert notification policies."""
        return await truenas_list_alert_policies_impl()

    @mcp.tool(name="truenas_list_pools")
    @_track("truenas_list_pools", ToolClass.READ)
    async def truenas_list_pools() -> str:
        """List ZFS pools with health status."""
        return await truenas_list_pools_impl()

    @mcp.tool(name="truenas_list_datasets")
    @_track("truenas_list_datasets", ToolClass.READ)
    async def truenas_list_datasets(limit: int = 50) -> str:
        """List ZFS datasets with mount points and utilization."""
        return await truenas_list_datasets_impl(limit=limit)

    @mcp.tool(name="truenas_list_disks")
    @_track("truenas_list_disks", ToolClass.READ)
    async def truenas_list_disks() -> str:
        """List physical disks and temperature alerts."""
        return await truenas_list_disks_impl()

    @mcp.tool(name="truenas_list_smart_results")
    @_track("truenas_list_smart_results", ToolClass.READ)
    async def truenas_list_smart_results(limit: int = 20) -> str:
        """List SMART self-test results (complements Scrutiny app)."""
        return await truenas_list_smart_results_impl(limit=limit)

    @mcp.tool(name="truenas_get_reporting_data")
    @_track("truenas_get_reporting_data", ToolClass.READ)
    async def truenas_get_reporting_data(
        graph: str = "cpu",
        identifier: str | None = None,
        start: int | None = None,
        end: int | None = None,
        unit: str | None = "HOUR",
        page: int = 1,
        aggregate: bool = True,
    ) -> str:
        """Fetch reporting metrics (cpu, memory, disk, load, etc.)."""
        return await truenas_get_reporting_data_impl(
            graph=graph,
            identifier=identifier,
            start=start,
            end=end,
            unit=unit,
            page=page,
            aggregate=aggregate,
        )

    @mcp.tool(name="truenas_list_apps")
    @_track("truenas_list_apps", ToolClass.READ)
    async def truenas_list_apps(limit: int = 50) -> str:
        """List TrueNAS apps (Scrutiny, Tailscale) and validate Scrutiny is running."""
        return await truenas_list_apps_impl(limit=limit)

    @mcp.tool(name="truenas_list_jobs")
    @_track("truenas_list_jobs", ToolClass.READ)
    async def truenas_list_jobs(limit: int = 20) -> str:
        """List recent middleware jobs (scrubs, replication, updates)."""
        return await truenas_list_jobs_impl(limit=limit)

    @mcp.tool(name="truenas_list_nfs_shares")
    @_track("truenas_list_nfs_shares", ToolClass.READ)
    async def truenas_list_nfs_shares() -> str:
        """List NFS shares; validate lab HA export path."""
        return await truenas_list_nfs_shares_impl()

    @mcp.tool(name="truenas_list_scrub_tasks")
    @_track("truenas_list_scrub_tasks", ToolClass.READ)
    async def truenas_list_scrub_tasks(limit: int = 20) -> str:
        """List pool scrub tasks and schedules."""
        return await truenas_list_scrub_tasks_impl(limit=limit)

    @mcp.tool(name="truenas_system_summary")
    @_track("truenas_system_summary", ToolClass.READ)
    async def truenas_system_summary() -> str:
        """Operator dashboard: system, alerts, pools, apps, NFS, jobs."""
        return await truenas_system_summary_impl()

    @mcp.tool(name="truenas_create_dataset")
    @_track("truenas_create_dataset", ToolClass.WRITE)
    async def truenas_create_dataset(
        pool: str,
        name: str,
        confirm: bool,
        dataset_type: str = "FILESYSTEM",
        wait_for_job: bool = True,
        job_timeout_sec: float = 120.0,
    ) -> str:
        """Create a ZFS dataset (requires confirm=true)."""
        return await truenas_create_dataset_impl(
            pool,
            name,
            confirm=confirm,
            dataset_type=dataset_type,
            wait_for_job=wait_for_job,
            job_timeout_sec=job_timeout_sec,
        )

    @mcp.tool(name="truenas_update_nfs_share")
    @_track("truenas_update_nfs_share", ToolClass.WRITE)
    async def truenas_update_nfs_share(
        share_id: int,
        confirm: bool,
        enabled: bool | None = None,
        comment: str | None = None,
        wait_for_job: bool = True,
        job_timeout_sec: float = 120.0,
    ) -> str:
        """Update an NFS share by id (requires confirm=true)."""
        return await truenas_update_nfs_share_impl(
            share_id,
            confirm=confirm,
            enabled=enabled,
            comment=comment,
            wait_for_job=wait_for_job,
            job_timeout_sec=job_timeout_sec,
        )

    @mcp.tool(name="truenas_dismiss_alert")
    @_track("truenas_dismiss_alert", ToolClass.WRITE)
    async def truenas_dismiss_alert(alert_id: str, confirm: bool) -> str:
        """Dismiss an active alert (requires confirm=true)."""
        return await truenas_dismiss_alert_impl(alert_id, confirm=confirm)

    @mcp.tool(name="truenas_run_smoke_tests")
    @_track("truenas_run_smoke_tests", ToolClass.READ)
    async def truenas_run_smoke_tests(extended: bool = False) -> str:
        """Run post-install smoke tests (config, auth, pools, NFS, apps; optional extended)."""
        return await truenas_run_smoke_tests_impl(extended=extended)
