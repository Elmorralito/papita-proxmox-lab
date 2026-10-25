"""Register MCP tools on a FastMCP server."""

from collections.abc import Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from proxmox_ve_mcp.tools.ceph import pve_get_ceph_status_impl, pve_list_ceph_osds_impl
from proxmox_ve_mcp.tools.cluster import (
    pve_cluster_health_impl,
    pve_get_cluster_config_nodes_impl,
    pve_get_cluster_options_impl,
    pve_get_task_log_impl,
    pve_get_version_impl,
    pve_list_nodes_impl,
    pve_list_resources_impl,
    pve_list_tasks_impl,
)
from proxmox_ve_mcp.tools.cluster_power import pve_shutdown_cluster_impl
from proxmox_ve_mcp.tools.diagnostics import pve_check_token_impl, pve_list_node_addresses_impl
from proxmox_ve_mcp.tools.guests import (
    pve_get_guest_config_impl,
    pve_shutdown_guest_impl,
    pve_start_guest_impl,
    pve_stop_guest_impl,
    pve_stopall_guests_impl,
)
from proxmox_ve_mcp.tools.ha import pve_get_ha_status_impl
from proxmox_ve_mcp.tools.nodes import (
    pve_get_guest_status_impl,
    pve_get_node_status_impl,
    pve_list_guests_impl,
)
from proxmox_ve_mcp.tools.power import pve_shutdown_node_impl, pve_wake_on_lan_impl
from proxmox_ve_mcp.tools.registry import TOOL_REGISTRY, ToolClass
from proxmox_ve_mcp.tools.smoke_test import pve_run_smoke_tests_impl
from proxmox_ve_mcp.tools.storage import pve_list_storage_impl
from proxmox_ve_mcp.tools.waits import pve_wait_for_task_impl, pve_wait_nodes_state_impl

ToolFn = Callable[..., Awaitable[str]]


def _track(name: str, tool_class: ToolClass) -> Callable[[ToolFn], ToolFn]:
    """Register *name* in :data:`TOOL_REGISTRY` when decorating an MCP tool."""

    def decorator(fn: ToolFn) -> ToolFn:
        TOOL_REGISTRY[name] = tool_class
        return fn

    return decorator


def register_tools(mcp: FastMCP) -> None:  # noqa: C901
    """Attach v1 read and gated write tools to the MCP server."""

    @mcp.tool(name="pve_get_version")
    @_track("pve_get_version", ToolClass.READ)
    async def pve_get_version() -> str:
        """Get Proxmox VE version (GET /version). Validates API token and TLS."""
        return await pve_get_version_impl()

    @mcp.tool(name="pve_check_token")
    @_track("pve_check_token", ToolClass.READ)
    async def pve_check_token() -> str:
        """Diagnose API token permissions; run first when tools return HTTP 403."""
        return await pve_check_token_impl()

    @mcp.tool(name="pve_run_smoke_tests")
    @_track("pve_run_smoke_tests", ToolClass.READ)
    async def pve_run_smoke_tests(extended: bool = False) -> str:
        """Post-install smoke tests: connectivity, auth, and access level (set extended=true for full matrix)."""
        return await pve_run_smoke_tests_impl(extended=extended)

    @mcp.tool(name="pve_list_node_addresses")
    @_track("pve_list_node_addresses", ToolClass.READ)
    async def pve_list_node_addresses() -> str:
        """List node corosync ring0_addr and interface IPs (requires Sys.Audit on /)."""
        return await pve_list_node_addresses_impl()

    @mcp.tool(name="pve_list_nodes")
    @_track("pve_list_nodes", ToolClass.READ)
    async def pve_list_nodes() -> str:
        """List cluster nodes and status. Replaces deploy/proxmox.sh cluster-nodes."""
        return await pve_list_nodes_impl()

    @mcp.tool(name="pve_get_cluster_config_nodes")
    @_track("pve_get_cluster_config_nodes", ToolClass.READ)
    async def pve_get_cluster_config_nodes() -> str:
        """Cluster node config with ring0_addr (deploy/proxmox.sh get-temp ring0 lookup)."""
        return await pve_get_cluster_config_nodes_impl()

    @mcp.tool(name="pve_get_cluster_options")
    @_track("pve_get_cluster_options", ToolClass.READ)
    async def pve_get_cluster_options() -> str:
        """Read datacenter cluster options (mailto, mailfrom, etc.)."""
        return await pve_get_cluster_options_impl()

    @mcp.tool(name="pve_list_tasks")
    @_track("pve_list_tasks", ToolClass.READ)
    async def pve_list_tasks(
        statusfilter: str | None = None,
        start: int | None = None,
        limit: int | None = None,
    ) -> str:
        """List cluster tasks; optional statusfilter (Running, stopped, ...) and pagination."""
        return await pve_list_tasks_impl(
            statusfilter=statusfilter,
            start=start,
            limit=limit,
        )

    @mcp.tool(name="pve_get_task_log")
    @_track("pve_get_task_log", ToolClass.READ)
    async def pve_get_task_log(node: str, upid: str) -> str:
        """Task log for a Proxmox UPID on the given node."""
        return await pve_get_task_log_impl(node=node, upid=upid)

    @mcp.tool(name="pve_list_resources")
    @_track("pve_list_resources", ToolClass.READ)
    async def pve_list_resources(
        type: str | None = None,
        node: str | None = None,
        start: int | None = None,
        limit: int | None = None,
    ) -> str:
        """List cluster resources with optional type, node, start, and limit filters."""
        return await pve_list_resources_impl(type=type, node=node, start=start, limit=limit)

    @mcp.tool(name="pve_cluster_health")
    @_track("pve_cluster_health", ToolClass.READ)
    async def pve_cluster_health() -> str:
        """Cluster health: true quorum (/cluster/status), entry node, QDevice, online/offline counts."""
        return await pve_cluster_health_impl()

    @mcp.tool(name="pve_get_ha_status")
    @_track("pve_get_ha_status", ToolClass.READ)
    async def pve_get_ha_status() -> str:
        """HA manager, per-node LRM state, resources, rules, and ha.shutdown_policy (must be freeze)."""
        return await pve_get_ha_status_impl()

    @mcp.tool(name="pve_wait_for_task")
    @_track("pve_wait_for_task", ToolClass.READ)
    async def pve_wait_for_task(upid: str, timeout_s: float = 120.0) -> str:
        """Wait ≤120 s for a task UPID; returns finished/succeeded and log tail. Re-call while finished=false."""
        return await pve_wait_for_task_impl(upid=upid, timeout_s=timeout_s)

    @mcp.tool(name="pve_wait_nodes_state")
    @_track("pve_wait_nodes_state", ToolClass.READ)
    async def pve_wait_nodes_state(
        target: str,
        nodes: list[str] | None = None,
        timeout_s: float = 120.0,
    ) -> str:
        """Wait ≤120 s for nodes (default all) to be online/offline; API loss counts as offline."""
        return await pve_wait_nodes_state_impl(target=target, nodes=nodes, timeout_s=timeout_s)

    @mcp.tool(name="pve_get_node_status")
    @_track("pve_get_node_status", ToolClass.READ)
    async def pve_get_node_status(node: str) -> str:
        """Get CPU, memory, and uptime for a node."""
        return await pve_get_node_status_impl(node=node)

    @mcp.tool(name="pve_list_guests")
    @_track("pve_list_guests", ToolClass.READ)
    async def pve_list_guests(node: str | None = None) -> str:
        """List VMs and containers (qemu + lxc)."""
        return await pve_list_guests_impl(node=node)

    @mcp.tool(name="pve_get_guest_status")
    @_track("pve_get_guest_status", ToolClass.READ)
    async def pve_get_guest_status(node: str, vmid: int, guest_type: str) -> str:
        """Runtime status for a VM (guest_type=qemu) or CT (guest_type=lxc)."""
        return await pve_get_guest_status_impl(node=node, vmid=vmid, guest_type=guest_type)

    @mcp.tool(name="pve_get_guest_config")
    @_track("pve_get_guest_config", ToolClass.READ)
    async def pve_get_guest_config(node: str, vmid: int, guest_type: str) -> str:
        """Guest configuration with secrets redacted."""
        return await pve_get_guest_config_impl(node=node, vmid=vmid, guest_type=guest_type)

    @mcp.tool(name="pve_list_storage")
    @_track("pve_list_storage", ToolClass.READ)
    async def pve_list_storage(node: str | None = None) -> str:
        """List storage definitions; pass node for per-node capacity status."""
        return await pve_list_storage_impl(node=node)

    @mcp.tool(name="pve_get_ceph_status")
    @_track("pve_get_ceph_status", ToolClass.READ)
    async def pve_get_ceph_status(node: str | None = None) -> str:
        """Ceph health summary (read-only). OSD startup is manual — see TIPSNTRICKS."""
        return await pve_get_ceph_status_impl(node=node)

    @mcp.tool(name="pve_list_ceph_osds")
    @_track("pve_list_ceph_osds", ToolClass.READ)
    async def pve_list_ceph_osds(node: str) -> str:
        """List Ceph OSDs on a node (read-only)."""
        return await pve_list_ceph_osds_impl(node=node)

    @mcp.tool(name="pve_start_guest")
    @_track("pve_start_guest", ToolClass.WRITE)
    async def pve_start_guest(
        node: str,
        vmid: int,
        guest_type: str,
        confirm: bool,
        wait_for_completion: bool = False,
    ) -> str:
        """Start a VM or CT. Requires confirm=true."""
        return await pve_start_guest_impl(
            node=node,
            vmid=vmid,
            guest_type=guest_type,
            confirm=confirm,
            wait_for_completion=wait_for_completion,
        )

    @mcp.tool(name="pve_shutdown_guest")
    @_track("pve_shutdown_guest", ToolClass.WRITE)
    async def pve_shutdown_guest(
        node: str,
        vmid: int,
        guest_type: str,
        confirm: bool,
        timeout: int = 60,
        wait_for_completion: bool = False,
    ) -> str:
        """ACPI shutdown for a VM or CT. Requires confirm=true."""
        return await pve_shutdown_guest_impl(
            node=node,
            vmid=vmid,
            guest_type=guest_type,
            confirm=confirm,
            timeout=timeout,
            wait_for_completion=wait_for_completion,
        )

    @mcp.tool(name="pve_stopall_guests")
    @_track("pve_stopall_guests", ToolClass.WRITE)
    async def pve_stopall_guests(
        node: str,
        confirm: bool,
        timeout: int = 120,
        wait_for_completion: bool = False,
    ) -> str:
        """Stop all guests on a node. Requires confirm=true."""
        return await pve_stopall_guests_impl(
            node=node,
            confirm=confirm,
            timeout=timeout,
            wait_for_completion=wait_for_completion,
        )

    @mcp.tool(name="pve_stop_guest")
    @_track("pve_stop_guest", ToolClass.DESTRUCTIVE)
    async def pve_stop_guest(  # pylint: disable=too-many-arguments
        node: str,
        vmid: int,
        guest_type: str,
        confirm: bool,
        reason: str,
        overrule_shutdown: bool = False,
        wait_for_completion: bool = False,
    ) -> str:
        """DESTRUCTIVE hard stop (power off) of a VM or CT; unsaved state is lost.

        Use only when pve_shutdown_guest hangs. overrule_shutdown aborts a running shutdown task.
        Requires confirm=true and a reason.
        """
        return await pve_stop_guest_impl(
            node=node,
            vmid=vmid,
            guest_type=guest_type,
            confirm=confirm,
            reason=reason,
            overrule_shutdown=overrule_shutdown,
            wait_for_completion=wait_for_completion,
        )

    @mcp.tool(name="pve_shutdown_node")
    @_track("pve_shutdown_node", ToolClass.DESTRUCTIVE)
    async def pve_shutdown_node(
        node: str,
        reason: str,
        confirm: bool = False,
        command: str = "shutdown",
        allow_entry_host: bool = False,
        plan_only: bool = False,
    ) -> str:
        """DESTRUCTIVE: shut down or reboot one PVE node (POST /nodes/{node}/status).

        Refuses unless ha.shutdown_policy=freeze, the node is online, and (for the API entry
        node) allow_entry_host=true. Warns on quorum loss, running guests, and the LAN router
        guest. plan_only=true runs every check without confirm and changes nothing.
        """
        return await pve_shutdown_node_impl(
            node=node,
            reason=reason,
            confirm=confirm,
            command=command,
            allow_entry_host=allow_entry_host,
            plan_only=plan_only,
        )

    @mcp.tool(name="pve_shutdown_cluster")
    @_track("pve_shutdown_cluster", ToolClass.DESTRUCTIVE)
    async def pve_shutdown_cluster(  # pylint: disable=too-many-arguments
        reason: str,
        confirm: bool = False,
        plan_only: bool = False,
        include_entry_node: bool = False,
        keep_running_vmids: list[int] | None = None,
        guest_timeout_s: int = 120,
        continue_on_error: bool = False,
        wait_for_completion: bool = True,
        timeout_s: float = 120.0,
    ) -> str:
        """DESTRUCTIVE: ordered full-cluster shutdown; resumable, ≤timeout_s (120) per call.

        Stages: stop guests (peers via stopall; entry node per guest except keep_running_vmids,
        default PVE_LAB_INFRA_VMIDS) → shut down peers while quorate → ready_for_nas (run the
        delayed truenas_shutdown from next_steps) → entry node when include_entry_node=true.
        Re-call with the same args while done=false. Refuses unless ha.shutdown_policy=freeze.
        plan_only=true projects every stage without confirm.
        """
        return await pve_shutdown_cluster_impl(
            reason=reason,
            confirm=confirm,
            plan_only=plan_only,
            include_entry_node=include_entry_node,
            keep_running_vmids=keep_running_vmids,
            guest_timeout_s=guest_timeout_s,
            continue_on_error=continue_on_error,
            wait_for_completion=wait_for_completion,
            timeout_s=timeout_s,
        )

    @mcp.tool(name="pve_wake_on_lan")
    @_track("pve_wake_on_lan", ToolClass.WRITE)
    async def pve_wake_on_lan(
        confirm: bool,
        nodes: list[str] | None = None,
        all_offline: bool = False,
    ) -> str:
        """Wake offline nodes via WoL sent from the API entry node (POST /nodes/{node}/wakeonlan).

        Pass nodes=[...] or all_offline=true. Online nodes are skipped. Requires confirm=true.
        """
        return await pve_wake_on_lan_impl(confirm=confirm, nodes=nodes, all_offline=all_offline)
