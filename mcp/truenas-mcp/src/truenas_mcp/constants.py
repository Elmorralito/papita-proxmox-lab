"""Shared constants for TrueNAS MCP."""

DEFAULT_WS_PATH = "/websocket"
DEFAULT_WS_TIMEOUT_SEC = 60.0
LAB_TRUENAS_HOST = "172.16.0.100"
LAB_HA_POOL_NAME = "pve-cluster-oldtimers-ha-storage"
LAB_NFS_EXPORT = "/mnt/pve-cluster-oldtimers-ha-storage/pve-nfs"
LAB_SCRUTINY_APP_NAME = "scrutiny"
LAB_CLUSTER_NAME = "pvecm-oldtimers"
TNAS_TESTED_MAJOR_VERSION = "25"

BASH_ONLY_WORKFLOWS: tuple[str, ...] = (
    "setup-cluster-ha",
    "pvesm-add-nfs",
    "qdevice-bootstrap",
    "scrutiny-webui",
    "uptime-kuma-pve-cluster",
)

RUNBOOK_REFS: dict[str, str] = {
    "truenas_get_system_info": "docs/TIPSNTRICKS.md#truenas-scale--storage-pools-scrutiny-and-uptime-kuma",
    "truenas_list_alerts": "docs/TIPSNTRICKS.md#truenas-scale-monitoring--quick-reference",
    "truenas_list_pools": "docs/TIPSNTRICKS.md#truenas-scale--storage-pools-scrutiny-and-uptime-kuma",
    "truenas_list_datasets": "deploy/setup/misc/cluster/default.truenas.nfs.env",
    "truenas_list_disks": "docs/TIPSNTRICKS.md#scrutiny--truenas-app-install-checklist",
    "truenas_list_jobs": "docs/TIPSNTRICKS.md",
    "truenas_list_nfs_shares": "docs/TIPSNTRICKS.md#quorum-qdevice-truenas-nfs-and-ha-path-b",
    "truenas_list_scrub_tasks": "docs/TIPSNTRICKS.md#truenas-scale--storage-pools-scrutiny-and-uptime-kuma",
    "truenas_system_summary": "docs/TIPSNTRICKS.md#quorum-qdevice-truenas-nfs-and-ha-path-b",
    "truenas_run_smoke_tests": "mcp/truenas-mcp/README.md",
    "truenas_check_api_key": "mcp/truenas-mcp/docs/API_KEY_SETUP.md",
    "truenas_list_smart_results": "docs/TIPSNTRICKS.md#scrutiny--truenas-app-install-checklist",
    "truenas_list_alert_policies": "docs/TIPSNTRICKS.md#truenas-scale-monitoring--quick-reference",
    "truenas_get_reporting_data": "docs/TIPSNTRICKS.md#truenas-scale-monitoring--quick-reference",
    "truenas_list_apps": "docs/TIPSNTRICKS.md#scrutiny--truenas-app-install-checklist",
    "truenas_create_dataset": "deploy/setup/misc/cluster/default.truenas.nfs.env",
    "truenas_update_nfs_share": "docs/TIPSNTRICKS.md#quorum-qdevice-truenas-nfs-and-ha-path-b",
    "truenas_dismiss_alert": "docs/TIPSNTRICKS.md",
}
