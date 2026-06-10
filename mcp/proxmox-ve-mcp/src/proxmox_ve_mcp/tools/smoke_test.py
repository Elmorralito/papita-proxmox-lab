"""Post-install smoke tests for connectivity and access level."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from proxmox_ve_mcp.client.errors import PveApiError
from proxmox_ve_mcp.client.permissions import TOKEN_ACL_HINT
from proxmox_ve_mcp.context import get_client, get_settings
from proxmox_ve_mcp.tools.helpers import normalize_list
from proxmox_ve_mcp.tools.response import ok_response, tool_handler

TestStatus = Literal["pass", "fail", "skip", "warn"]
TestCategory = Literal["connectivity", "auth", "read_core", "read_extended", "write_capability"]


class AccessLevel(StrEnum):
    """Derived token capability tier from smoke test outcomes."""

    NONE = "none"
    MINIMAL = "minimal"
    READ_BASIC = "read_basic"
    READ_EXTENDED = "read_extended"
    READ_FULL = "read_full"
    WRITE_CAPABLE = "write_capable"


@dataclass(frozen=True)
class SmokeTestSpec:
    """Definition of a single smoke test."""

    test_id: str
    category: TestCategory
    name: str
    description: str
    extended_only: bool = False
    required_privilege: str | None = None


SMOKE_TEST_CATALOG: tuple[SmokeTestSpec, ...] = (
    SmokeTestSpec(
        "connectivity_tls",
        "connectivity",
        "TLS connectivity",
        "HTTPS reachability to PVE_HOST:PVE_PORT via GET /version",
    ),
    SmokeTestSpec(
        "auth_token",
        "auth",
        "API token authentication",
        "Token accepted by Proxmox (not HTTP 401)",
    ),
    SmokeTestSpec(
        "token_permissions",
        "auth",
        "Token permissions endpoint",
        "GET /access/permissions reachable",
    ),
    SmokeTestSpec(
        "cluster_list_nodes",
        "read_core",
        "List cluster nodes",
        "GET /cluster/resources?type=node returns members",
    ),
    SmokeTestSpec(
        "cluster_all_online",
        "read_core",
        "All nodes online",
        "Every cluster node reports status=online",
    ),
    SmokeTestSpec(
        "cluster_health",
        "read_core",
        "Cluster health summary",
        "Derived online/offline counts from cluster resources",
    ),
    SmokeTestSpec(
        "cluster_config_nodes",
        "read_extended",
        "Cluster config (ring0_addr)",
        "GET /cluster/config/nodes for corosync addresses",
        extended_only=True,
        required_privilege="Sys.Audit on /",
    ),
    SmokeTestSpec(
        "node_network_detail",
        "read_extended",
        "Node network addresses",
        "Interface CIDR on a sample online node",
        extended_only=True,
        required_privilege="Sys.Audit on /nodes/{node}",
    ),
    SmokeTestSpec(
        "node_status",
        "read_extended",
        "Node runtime status",
        "CPU, memory, and uptime on a sample node",
        extended_only=True,
        required_privilege="Sys.Audit on /nodes/{node}",
    ),
    SmokeTestSpec(
        "guest_inventory",
        "read_extended",
        "Guest inventory",
        "List VMs and containers via /cluster/resources",
        extended_only=True,
        required_privilege="VM.Audit on /",
    ),
    SmokeTestSpec(
        "storage_list",
        "read_extended",
        "Storage definitions",
        "GET /storage returns cluster storage",
        extended_only=True,
        required_privilege="Sys.Audit on /",
    ),
    SmokeTestSpec(
        "ceph_status",
        "read_extended",
        "Ceph health (optional)",
        "Ceph status when Ceph is configured on the cluster",
        extended_only=True,
        required_privilege="Sys.Audit (Ceph)",
    ),
    SmokeTestSpec(
        "write_permissions",
        "write_capability",
        "Write capability probe",
        "Token permissions include VM.PowerMgmt (informational only)",
        extended_only=True,
        required_privilege="VM.PowerMgmt on /",
    ),
)


@dataclass
class SmokeTestResult:
    """Outcome of one smoke test."""

    test_id: str
    category: TestCategory
    name: str
    status: TestStatus
    detail: str | None = None
    error: dict[str, Any] | None = None
    data: dict[str, Any] = field(default_factory=dict)


def _result(
    spec: SmokeTestSpec,
    status: TestStatus,
    *,
    detail: str | None = None,
    error: dict[str, Any] | None = None,
    **data: Any,
) -> SmokeTestResult:
    """Build a :class:`SmokeTestResult` from a catalog spec and status fields."""
    return SmokeTestResult(
        test_id=spec.test_id,
        category=spec.category,
        name=spec.name,
        status=status,
        detail=detail,
        error=error,
        data=dict(data),
    )


def _permissions_include(permissions: Any, privilege: str) -> bool:
    """Return whether any ACL path in *permissions* grants *privilege*."""
    if not isinstance(permissions, dict):
        return False
    for path_perms in permissions.values():
        if not isinstance(path_perms, dict):
            continue
        if privilege in path_perms:
            return True
    return False


async def _find_sample_node(client: Any, cache: dict[str, Any]) -> str | None:
    """Pick the first online cluster node, caching the result in *cache*."""
    if "sample_node" in cache:
        return cache["sample_node"]
    nodes = normalize_list(await client.get("/cluster/resources", params={"type": "node"}))
    online = [n for n in nodes if n.get("status") == "online" and n.get("node")]
    sample = str(online[0]["node"]) if online else (str(nodes[0]["node"]) if nodes else None)
    cache["sample_node"] = sample
    cache["nodes"] = nodes
    return sample


async def _find_iface_with_address(client: Any, node: str) -> str | None:
    """Return the first network interface on *node* that has an assigned address."""
    for candidate in ("vmbr0", "vmbr1", "nic0", "nic1"):
        try:
            detail = await client.get(f"/nodes/{node}/network/{candidate}")
            if detail.get("address") or detail.get("cidr"):
                return candidate
        except PveApiError:
            continue
    interfaces = normalize_list(await client.get(f"/nodes/{node}/network"))
    for iface in interfaces:
        name = iface.get("iface")
        if not name:
            continue
        try:
            detail = await client.get(f"/nodes/{node}/network/{name}")
            if detail.get("address") or detail.get("cidr"):
                return str(name)
        except PveApiError:
            continue
    return None


async def _run_single_test(  # noqa: C901
    spec: SmokeTestSpec,
    client: Any,
    cache: dict[str, Any],
) -> SmokeTestResult:
    """Execute one catalog smoke test against the live Proxmox API."""
    try:
        if spec.test_id == "connectivity_tls":
            data = await client.get("/version")
            version = data.get("version") if isinstance(data, dict) else data
            return _result(spec, "pass", detail=f"Proxmox VE {version}", version=version)

        if spec.test_id == "auth_token":
            data = await client.get("/version")
            return _result(spec, "pass", detail="Token accepted", version=data)

        if spec.test_id == "token_permissions":
            perms = await client.get("/access/permissions")
            cache["permissions"] = perms
            empty = not perms
            return _result(
                spec,
                "pass",
                detail="Empty permissions (privilege separation likely)" if empty else "Permissions returned",
                permissions=perms,
            )

        if spec.test_id == "cluster_list_nodes":
            nodes = normalize_list(await client.get("/cluster/resources", params={"type": "node"}))
            cache["nodes"] = nodes
            if not nodes:
                return _result(spec, "fail", detail="No cluster nodes returned")
            names = [n.get("node") for n in nodes]
            return _result(spec, "pass", detail=f"{len(nodes)} node(s)", nodes=names, count=len(nodes))

        if spec.test_id == "cluster_all_online":
            nodes = cache.get("nodes") or normalize_list(
                await client.get("/cluster/resources", params={"type": "node"})
            )
            offline = [n.get("node") for n in nodes if n.get("status") != "online"]
            if offline:
                return _result(
                    spec,
                    "warn",
                    detail=f"Offline: {', '.join(str(n) for n in offline)}",
                    offline=offline,
                    online_count=len(nodes) - len(offline),
                )
            return _result(spec, "pass", detail=f"All {len(nodes)} node(s) online", count=len(nodes))

        if spec.test_id == "cluster_health":
            nodes = cache.get("nodes") or normalize_list(
                await client.get("/cluster/resources", params={"type": "node"})
            )
            online = [n for n in nodes if n.get("status") == "online"]
            return _result(
                spec,
                "pass",
                detail=f"{len(online)}/{len(nodes)} online",
                online_count=len(online),
                total_count=len(nodes),
            )

        if spec.test_id == "cluster_config_nodes":
            config = normalize_list(await client.get("/cluster/config/nodes"))
            ring0 = {
                str(e.get("name") or e.get("node")): e.get("ring0_addr")
                for e in config
                if e.get("name") or e.get("node")
            }
            return _result(
                spec,
                "pass",
                detail=f"{len(config)} configured node(s)",
                ring0_addrs=ring0,
                count=len(config),
            )

        if spec.test_id == "node_network_detail":
            node = await _find_sample_node(client, cache)
            if not node:
                return _result(spec, "fail", detail="No sample node available")
            iface = await _find_iface_with_address(client, node)
            if not iface:
                return _result(spec, "fail", detail=f"No interface address on {node}")
            detail = await client.get(f"/nodes/{node}/network/{iface}")
            addr = detail.get("address") or detail.get("cidr")
            return _result(
                spec,
                "pass",
                detail=f"{node}/{iface} → {addr}",
                node=node,
                iface=iface,
                address=addr,
            )

        if spec.test_id == "node_status":
            node = await _find_sample_node(client, cache)
            if not node:
                return _result(spec, "fail", detail="No sample node available")
            status = await client.get(f"/nodes/{node}/status")
            return _result(
                spec,
                "pass",
                detail=f"Uptime {status.get('uptime', '?')}s on {node}",
                node=node,
                uptime=status.get("uptime"),
                cpu=status.get("cpu"),
                memory=status.get("memory"),
            )

        if spec.test_id == "guest_inventory":
            resources = normalize_list(await client.get("/cluster/resources"))
            guests = [r for r in resources if r.get("type") in {"qemu", "lxc"}]
            return _result(
                spec,
                "pass",
                detail=f"{len(guests)} guest(s)",
                count=len(guests),
                types={
                    "qemu": sum(1 for g in guests if g.get("type") == "qemu"),
                    "lxc": sum(1 for g in guests if g.get("type") == "lxc"),
                },
            )

        if spec.test_id == "storage_list":
            storage = normalize_list(await client.get("/storage"))
            return _result(
                spec,
                "pass",
                detail=f"{len(storage)} storage entrie(s)",
                count=len(storage),
                storage_ids=[s.get("storage") for s in storage],
            )

        if spec.test_id == "ceph_status":
            node = await _find_sample_node(client, cache)
            if not node:
                return _result(spec, "skip", detail="No sample node for Ceph probe")
            try:
                status = await client.get(f"/nodes/{node}/ceph/status")
                return _result(spec, "pass", detail="Ceph reachable", node=node, health=status)
            except PveApiError as exc:
                if exc.status_code in {404, 501} or (
                    exc.status_code == 500 and exc.pve_message and "ceph" in exc.pve_message.lower()
                ):
                    return _result(spec, "skip", detail="Ceph not configured on cluster")
                raise

        if spec.test_id == "write_permissions":
            perms = cache.get("permissions")
            if perms is None:
                perms = await client.get("/access/permissions")
                cache["permissions"] = perms
            if _permissions_include(perms, "VM.PowerMgmt"):
                return _result(spec, "pass", detail="VM.PowerMgmt present — write tools may work")
            if not perms:
                return _result(
                    spec,
                    "warn",
                    detail="Permissions empty; cannot confirm write access (assign VM.PowerMgmt if needed)",
                )
            return _result(
                spec,
                "warn",
                detail="VM.PowerMgmt not in token permissions — read-only token",
            )

    except PveApiError as exc:
        return _result(
            spec,
            "fail",
            detail=str(exc),
            error=exc.to_dict(),
            required_privilege=spec.required_privilege,
        )

    return _result(spec, "fail", detail="Unknown test id")


def _derive_access_level(results: list[SmokeTestResult]) -> AccessLevel:
    """Map smoke test outcomes to a coarse API access tier."""
    by_id = {r.test_id: r for r in results}

    def ok(*test_ids: str) -> bool:
        return all(by_id[t].status in {"pass", "warn"} for t in test_ids if t in by_id)

    conn = by_id.get("connectivity_tls")
    auth = by_id.get("auth_token")
    if (conn and conn.status == "fail") or (auth and auth.status == "fail"):
        return AccessLevel.NONE
    if not ok("cluster_list_nodes"):
        return AccessLevel.MINIMAL

    extended_ids = (
        "cluster_config_nodes",
        "node_network_detail",
        "node_status",
        "guest_inventory",
        "storage_list",
    )
    present_extended = [t for t in extended_ids if t in by_id]
    if present_extended and not ok(*present_extended):
        if ok("cluster_config_nodes", "node_network_detail"):
            return AccessLevel.READ_EXTENDED
        return AccessLevel.READ_BASIC

    write = by_id.get("write_permissions")
    if write and write.status == "pass":
        return AccessLevel.WRITE_CAPABLE
    if present_extended:
        return AccessLevel.READ_FULL
    return AccessLevel.READ_BASIC


def _build_recommendations(results: list[SmokeTestResult], access_level: AccessLevel) -> list[str]:
    """Suggest ACL or token changes based on failed smoke tests."""
    recs: list[str] = []
    failed = [r for r in results if r.status == "fail"]

    if any(r.test_id == "connectivity_tls" for r in failed):
        recs.append("Verify PVE_HOST, PVE_PORT, Tailscale/LAN routing, and PVE_VERIFY_SSL.")
    if any(r.test_id == "auth_token" for r in failed):
        recs.append("Regenerate the API token and update PVE_TOKEN_SECRET in mcp.json.")
    if any(r.test_id in {"cluster_config_nodes", "node_network_detail", "node_status", "storage_list"} for r in failed):
        recs.append("Assign Sys.Audit (or Administrator) to the API token at path /.")
    if any(r.test_id == "guest_inventory" for r in failed):
        recs.append("Assign VM.Audit to the API token at path /.")
    if failed and not recs:
        recs.append(TOKEN_ACL_HINT)
    if access_level == AccessLevel.READ_BASIC:
        recs.append("Re-run with extended=true after fixing token ACL for full read access.")
    return recs


async def run_smoke_tests(*, extended: bool = False) -> dict[str, Any]:
    """Execute the smoke test suite and return a structured report."""
    client = get_client()
    settings = get_settings()
    cache: dict[str, Any] = {}
    results: list[SmokeTestResult] = []

    specs = [s for s in SMOKE_TEST_CATALOG if extended or not s.extended_only]
    for spec in specs:
        result = await _run_single_test(spec, client, cache)
        results.append(result)
        if spec.test_id in {"connectivity_tls", "auth_token"} and result.status == "fail":
            for remaining in specs[len(results) :]:
                results.append(
                    SmokeTestResult(
                        test_id=remaining.test_id,
                        category=remaining.category,
                        name=remaining.name,
                        status="skip",
                        detail="Skipped after connectivity/auth failure",
                    )
                )
            break

    access_level = _derive_access_level(results)
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    warned = sum(1 for r in results if r.status == "warn")
    skipped = sum(1 for r in results if r.status == "skip")

    run_ok = failed == 0

    return {
        "access_level": access_level.value,
        "api_user": settings.user,
        "token_id": settings.token_id,
        "api_entry_host": settings.host,
        "extended": extended,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "warned": warned,
            "skipped": skipped,
        },
        "tests": [
            {
                "id": r.test_id,
                "category": r.category,
                "name": r.name,
                "status": r.status,
                "detail": r.detail,
                "error": r.error,
                "data": r.data or None,
            }
            for r in results
        ],
        "recommendations": _build_recommendations(results, access_level),
        "all_passed": run_ok,
    }


@tool_handler("pve_run_smoke_tests")
async def pve_run_smoke_tests_impl(extended: bool = False) -> str:
    """Run post-install connectivity and access-level smoke tests (optional after MCP setup)."""
    started = time.perf_counter()
    report = await run_smoke_tests(extended=extended)
    warnings = list(report.pop("recommendations", []))
    if not report.get("all_passed"):
        warnings.insert(0, f"Smoke tests: {report['summary']['failed']} failure(s) — see tests[] for details.")
    duration_ms = int((time.perf_counter() - started) * 1000)
    return ok_response(
        "pve_run_smoke_tests",
        report,
        duration_ms=duration_ms,
        warnings=warnings,
        meta_extra={"all_passed": report.get("all_passed")},
    )
